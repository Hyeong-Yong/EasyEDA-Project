"""Exactly one fresh DC retry per failed point using a nearby validated internal seed."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
from pathlib import Path
import runpy
import numpy as np

HERE=Path(__file__).resolve().parent
SIM=HERE.parent.parent
BOARD=SIM.parent.parent
API=runpy.run_path(str(BOARD/"scripts/simulate-adc-representative.py"))
PRIOR=json.loads((SIM/"runtime/dcpoint-summary.json").read_text())
NODESET=SIM/"runtime/warm-start-full.inc"
SEEDDIR=SIM/"runtime/dcpoint-attempt2"
CAPS=["c97_j2","c122_j2","c80_j2","c156","c157","c103","c105","c104","c158","c159","c160","c120_j2","c121_j2","c100_j2","cother"]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def body(spec):
    return API["rails"](v5=f'DC {spec["v5_source_v"]:.15g}',v3=f'DC {spec["v3_v"]:.15g}',shared=True)+API["channel"](source=f'DC {spec["requested_sma_v"]/API["SOURCE_FACTOR"]:.15g} AC 1',op320="OPAx320-Q1")

def true_dc(name,run):
    log=(SIM/"runs"/(name+".log")).read_text(errors="replace")
    return bool(run["run_ok"] and not run["warnings"] and "transient op" not in log.lower())

def one(target):
    valid=[r for r in PRIOR["results"] if r["validated_true_dc"] and r["v5_source_v"]==target["v5_source_v"] and r["v3_v"]==target["v3_v"]]
    nearest=min(valid,key=lambda r:abs(r["requested_sma_v"]-target["requested_sma_v"]))
    seedname=target["case"]+"_attempt2seed"
    name=target["case"]+"_attempt2"
    result={"original_case":target["case"],"nearest_valid_case":nearest["case"],"seed_name":seedname,"case":name,"v5_source_v":target["v5_source_v"],"v3_v":target["v3_v"],"requested_sma_v":target["requested_sma_v"],"group":target["group"],"validated_true_dc":False}
    API["write_deck"](seedname,body(nearest),".op",["all"],ref=True,method="gear",nodeset=NODESET)
    seedrun=API["execute"](seedname,timeout=12,optran=False,analysis=".op")
    result["seed_run"]=seedrun
    result["seed_true_dc"]=true_dc(seedname,seedrun)
    if not result["seed_true_dc"]:
        result["failure"]="Nearest validated operating point did not reproduce a valid fresh DC seed with .save all; target not retried."
        return result
    raw=API["raw_read"](SIM/"runs"/(seedname+".raw"))
    nodes={node:float(np.real(values[0])) for node,values in raw.items() if node.startswith("v(x")}
    init=SEEDDIR/(name+".inc")
    init.write_text("* Numerical guesses only, all internal model nodes from nearest successful fresh DC seed.\n"+"\n".join(f".nodeset {node}={value:.17g}" for node,value in nodes.items())+"\n",encoding="ascii")
    result.update(nodeset=str(init),nodeset_sha256=sha(init),internal_guesses=len(nodes),seed_raw_sha256=sha(SIM/"runs"/(seedname+".raw")))
    API["write_deck"](name,body(target),".op",API["SAVES"]+[f"@{cap}[i]" for cap in CAPS],ref=True,method="gear",nodeset=init)
    run=API["execute"](name,timeout=12,optran=False,analysis=".op")
    result["run"]=run
    accepted_log=(SIM/"runs"/(name+".log")).read_text(errors="replace")
    result["transient_op_fallback_used"]="transient op" in accepted_log.lower()
    result["validated_true_dc"]=true_dc(name,run)
    if run["run_ok"]:
        values=API["raw_read"](SIM/"runs"/(name+".raw"))
        result["voltages_currents"]={k:float(np.real(v[0])) for k,v in values.items()}
        currents={k:v for k,v in result["voltages_currents"].items() if "@c" in k}
        result["dc_capacitor_currents_a"]=currents
        result["all_saved_dc_capacitor_currents_zero"]=len(currents)==len(CAPS) and all(v==0 for v in currents.values())
        result["validated_true_dc"]=result["validated_true_dc"] and result["all_saved_dc_capacitor_currents_zero"]
        adc=result["voltages_currents"]["v(adc_j2)"]
        result["adc_within_rails"]=0<=adc<=target["v3_v"]
        result["adc_rail_headroom_v"]=min(adc,target["v3_v"]-adc)
    return result

def main():
    SEEDDIR.mkdir(exist_ok=True)
    models=[Path(p) for p in PRIOR["original_model_hashes_after"]]
    before={str(p):sha(p) for p in models}
    assert before==PRIOR["original_model_hashes_after"]
    failed=[r for r in PRIOR["results"] if not r["validated_true_dc"]]
    assert len(failed)==6
    for target in failed:
        for suffix in ["_attempt2seed","_attempt2"]:
            name=target["case"]+suffix
            assert not (SIM/"decks"/(name+".cir")).exists()
            assert not any((SIM/"runs"/(name+ext)).exists() for ext in [".log",".raw",".json"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(one,failed))
    after={str(p):sha(p) for p in models}
    summary={"method":"Exactly one requested retry per previously failed input, using all internal v(x*) initial guesses from the nearest successful same-rail point rerun with .save all. Fresh independent process .op, no optran/rshunt/gmin changes, method gear, timeout12s, three workers.","before_hashes":before,"after_hashes":after,"original_models_unchanged":before==after,"retry_count":len(failed),"successful_retries":sum(r["validated_true_dc"] for r in results),"results":results}
    (SIM/"runtime/dcpoint-attempt2-summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    combined=[]
    retries={r["original_case"]:r for r in results}
    for initial in PRIOR["results"]:
        retry=retries.get(initial["case"])
        if retry and retry["validated_true_dc"]:
            combined.append({**initial,**retry,"accepted_attempt":2})
        else:
            combined.append({**initial,"accepted_attempt":1 if initial["validated_true_dc"] else None})
    valid=[r for r in combined if r["validated_true_dc"]]
    normal=[r for r in valid if r["group"]=="nominal"]
    fit={"valid_points":len(normal),"requested_points":17,"complete_coverage":len(normal)==17,"acceptance_tolerance_specified":False}
    if len(normal)>=3:
        x=np.array([r["voltages_currents"]["v(raw_j2)"] for r in normal]);y=np.array([r["voltages_currents"]["v(adc_j2)"] for r in normal]);slope,offset=np.polyfit(x,y,1)
        fit.update(gain_v_per_v=float(slope),offset_v=float(offset),gain_error_percent=float((slope/-.7-1)*100),max_abs_residual_v=float(np.max(np.abs(y-(slope*x+offset)))))
    accepted={"requested_points":44,"accepted_true_dc_points":len(valid),"remaining_failed_cases":[r["case"] for r in combined if not r["validated_true_dc"]],"all_accepted_adc_within_rails":all(r["adc_within_rails"] for r in valid),"all_requested_points_validated":len(valid)==44,"minimum_rail_headroom_v":min(r["adc_rail_headroom_v"] for r in valid),"nominal_fit":fit,"results":combined,"original_models_unchanged":before==after,"attempt1_summary_preserved":str(SIM/"runtime/dcpoint-summary.json"),"attempt2_summary":str(SIM/"runtime/dcpoint-attempt2-summary.json")}
    (SIM/"runtime/dcpoint-accepted-summary.json").write_text(json.dumps(accepted,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in accepted.items() if k!="results"}),flush=True)
    assert before==after

if __name__=="__main__":
    main()
