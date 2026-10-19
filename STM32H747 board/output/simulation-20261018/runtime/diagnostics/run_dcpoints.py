"""44 independent full-model DC operating points using the main runner read only."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
SIM = HERE.parent.parent
BOARD = SIM.parent.parent
SCRIPT = BOARD / "scripts/simulate-adc-representative.py"
API = runpy.run_path(str(SCRIPT))
NODESET = SIM / "runtime/warm-start-full.inc"
MODELS = [SIM / "models/OPA189/OPAx189.LIB", SIM / "models/OPA320/OPAx320-Q1.LIB", SIM / "models/REF5025/REF5025.LIB"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def token(value):
    return ("n" if value < 0 else "p") + f"{abs(value):.6f}".rstrip("0").rstrip(".").replace(".","p")


def run_one(spec):
    group, v5, v3, sma = spec
    name = "dcpoint_" + group + "_v5" + token(v5) + "_v3" + token(v3) + "_sma" + token(sma)
    source = sma / API["SOURCE_FACTOR"]
    body = API["rails"](v5=f"DC {v5:.15g}",v3=f"DC {v3:.15g}",shared=True)
    body += API["channel"](source=f"DC {source:.15g} AC 1",op320="OPAx320-Q1")
    API["write_deck"](name,body,".op",API["SAVES"],ref=True,method="gear",nodeset=NODESET)
    run = API["execute"](name,timeout=20,optran=False,analysis=".op")
    log = (SIM/"runs"/(name+".log")).read_text(errors="replace")
    item = {"case":name,"group":group,"v5_source_v":v5,"v3_v":v3,"requested_sma_v":sma,"source_dc_v":source,"run":run,"transient_op_fallback_used":"Transient op started" in log}
    if run["run_ok"]:
        raw = API["raw_read"](SIM/"runs"/(name+".raw"))
        item["voltages_currents"] = {k:float(np.real(v[0])) for k,v in raw.items()}
        adc = item["voltages_currents"]["v(adc_j2)"]
        item["adc_within_rails"] = bool(0 <= adc <= v3)
        item["adc_rail_headroom_v"] = float(min(adc,v3-adc))
        item["sma_actual_error_v"] = item["voltages_currents"]["v(raw_j2)"] - sma
    else:
        item["adc_within_rails"] = None
    item["validated_true_dc"] = bool(run["run_ok"] and not run["warnings"] and not item["transient_op_fallback_used"])
    return item


def main():
    models_before = {str(p):digest(p) for p in MODELS}
    known = json.loads((SIM/"runtime/diagnostics/diagnostics-summary.json").read_text())["original_hashes"]
    for p in MODELS[:2]:
        assert models_before[str(p)] == known[str(p)], "Original model changed from initial diagnostic hash"
    names = []
    specs = [("nominal",5.0,3.3,float(v)) for v in np.arange(-2,2.0001,.25)]
    specs += [("corner",v5,v3,sma) for v5 in [4.75,5.0,5.25] for v3 in [3.135,3.3,3.465] for sma in [-2.0,0.0,2.0]]
    for group,v5,v3,sma in specs:
        name = "dcpoint_"+group+"_v5"+token(v5)+"_v3"+token(v3)+"_sma"+token(sma)
        names.append(name)
        assert not (SIM/"decks"/(name+".cir")).exists(), "Refusing to overwrite an existing deck"
        assert not any((SIM/"runs"/(name+ext)).exists() for ext in [".raw",".log",".json"]), "Refusing to overwrite an existing run"
    assert len(specs)==44 and len(set(names))==44
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run_one,specs))
    valid = [r for r in results if r["validated_true_dc"]]
    nominal = [r for r in valid if r["group"]=="nominal"]
    metrics = {"expected_nominal_gain_v_per_v":-.7,"gain_linearity_acceptance_tolerance_specified":False}
    if len(nominal)==17:
        x = np.array([r["voltages_currents"]["v(raw_j2)"] for r in nominal])
        y = np.array([r["voltages_currents"]["v(adc_j2)"] for r in nominal])
        slope,offset = np.polyfit(x,y,1)
        residual = y-(slope*x+offset)
        metrics.update(fitted_gain_v_per_v=float(slope),fitted_offset_v=float(offset),gain_error_percent=float((slope/-.7-1)*100),max_abs_residual_from_fit_v=float(np.max(np.abs(residual))),max_abs_error_from_ideal_offset_and_gain_v=float(np.max(np.abs(y-(API["VBIAS"]*1.7-.7*x)))))
    all_adc = [r["voltages_currents"]["v(adc_j2)"] for r in valid]
    models_after = {str(p):digest(p) for p in MODELS}
    summary = {
        "engine":"ngspice47; original TI PSpice-format libraries, not Cadence PSpice",
        "source_factor":API["SOURCE_FACTOR"],"source_formula":"Vsource = requested actual SMA voltage / (100000 / 100050)",
        "run_method":"Independent fresh-process .op at every input; method=gear; original shared REF5025 + OPA189 U32 + J2 OPA189/OPA320-Q1; warm-start-full.inc initial guesses; optran=False; 20s timeout; max four workers",
        "runner_script":str(SCRIPT),"runner_script_sha256_loaded":digest(SCRIPT),"nodeset":str(NODESET),"nodeset_sha256":digest(NODESET),
        "original_model_hashes_before":models_before,"original_model_hashes_after":models_after,"original_models_unchanged":models_before==models_after,
        "requested_cases":44,"nominal_cases":17,"corner_cases":27,"validated_true_dc_cases":len(valid),
        "failed_or_unvalidated_cases":[r["case"] for r in results if not r["validated_true_dc"]],
        "acceptance":{"all_requested_cases_validated_true_dc":len(valid)==44,"all_validated_adc_points_inside_0_to_v3":all(r["adc_within_rails"] for r in valid) if valid else False,"all_requested_adc_points_inside_0_to_v3":len(valid)==44 and all(r["adc_within_rails"] for r in valid),"adc_min_v":min(all_adc) if all_adc else None,"adc_max_v":max(all_adc) if all_adc else None,"minimum_rail_headroom_v":min(r["adc_rail_headroom_v"] for r in valid) if valid else None,"nominal_gain_linearity":metrics},
        "results":results
    }
    target = SIM/"runtime/dcpoint-summary.json"
    target.write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps({"summary":str(target),"valid":len(valid),"acceptance":summary["acceptance"]}),flush=True)
    assert models_before==models_after


if __name__ == "__main__":
    main()
