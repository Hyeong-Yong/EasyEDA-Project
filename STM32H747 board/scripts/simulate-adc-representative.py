"""Read-only CAD audit and TI macro-model review in portable ngspice 47.

Writes only output/simulation-20261018; never opens or edits EasyEDA documents.
The .cir files use ordinary SPICE analyses, not embedded ngspice control.
NOISE uses ngspice syntax and requires conversion before reuse in PSpice.
Original TI libraries are included unchanged. This is NOT a Cadence PSpice run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output/simulation-20261018"
EXE = ROOT / ".tools/ngspice-47/Spice64/bin/ngspice_con.exe"
NET = ROOT / "output/validation/native-adc10-labtool_schematic-Protel2-20261018.net"
NET_SHA = "dd848d6113c5ec2a0835c128ed664aff57e1df0f7967b9571fbd861d7ab4c12d"
VBIAS = 2.5 * 10 / 25.8
SOURCE_FACTOR = 100000 / 100050


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_source():
    assert sha(NET) == NET_SHA, "Final schematic export changed; re-review required"
    text = NET.read_text(encoding="utf-8-sig")
    parse = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))["parse_protel2"]
    records = parse(text)
    pins = {(r["ref"], r["number"]): r["net"] for r in records}
    components = {}
    for match in re.finditer(r"(?ms)^\[\s*\n(.*?)^\]", text):
        lines = match.group(1).splitlines()
        props = dict(zip(lines[::2], lines[1::2]))
        if "DESIGNATOR" in props:
            components[props["DESIGNATOR"]] = props
    expected = {
        "R177": ("100k", ["ADC_J2_RAW", "GND"]),
        "R140": ("3.32k", ["ADC_J2_RAW", "ADC_J2_FILTER"]),
        "C97": ("10nF", ["ADC_J2_FILTER", "GND"]),
        "R137": ("4.00k", ["ADC_J2_BUF", "ADC_J2_SUM"]),
        "R187": ("2.80k", ["ADC_J2_SUM", "ADC_J2_DRV"]),
        "C122": ("10nF", ["ADC_J2_SUM", "ADC_J2_DRV"]),
        "R141": ("47", ["ADC_J2_DRV", "ADC1_INP0"]),
        "C80": ("10nF", ["ADC1_INP0", "GND"]),
        "R202": ("15.8k", ["AFE_REF_2V5", "AFE_OFFSET_FILTER"]),
        "R203": ("10k", ["AFE_OFFSET_FILTER", "GND"]),
        "R204": ("1k", ["AFE_OFFSET_BUFFER", "ADC_OFFSET_0V97"]),
        "C158": ("4.7uF", ["AFE_OFFSET_FILTER", "GND"]),
        "C159": ("4.7uF", ["ADC_OFFSET_0V97", "GND"]),
        "C103": ("1uF", ["+5V_AFE", "GND"]),
        "C105": ("1uF", ["AFE_REF_NR", "GND"]),
        "R201": ("1", ["AFE_REF_2V5", "AFE_REF_ESR"]),
        "C104": ("4.7uF", ["AFE_REF_ESR", "GND"]),
        "R200": ("4.7", ["+5V", "+5V_AFE"]),
        "C156": ("4.7uF", ["+5V_AFE", "GND"]),
        "C157": ("4.7uF", ["+5V_AFE", "GND"]),
        "C120": ("100nF", ["+5V_AFE", "GND"]),
        "C121": ("100nF", ["-3V_AFE", "GND"]),
        "C100": ("100nF", ["+3V3", "GND"]),
        "C160": ("100nF", ["+5V_AFE", "GND"]),
        "R198": ("15.4k", ["-3V_AFE", "AFE_NEG_FB"]),
        "R199": ("10k", ["AFE_NEG_FB", "GND"]),
        "C155": ("10nF", ["AFE_NEG_FB", "-3V_AFE"]),
        "C153": ("4.7uF", ["-3V_AFE", "GND"]),
        "C154": ("4.7uF", ["-3V_AFE", "GND"]),
    }
    audit = []
    # Normalization is for displayed unit suffix only, never for pin/net names.
    def norm(value):
        s = value.strip().lower().replace("ω", "").replace("ohm", "").replace("f", "")
        m = re.fullmatch(r"([0-9.]+)([pkmun]?)", s)
        assert m, value
        return float(m[1]) * {"": 1, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3}[m[2]]
    for ref, (value, nets) in expected.items():
        actual = components[ref]["Value"]
        got = [pins[(ref, str(i + 1))] for i in range(2)]
        assert norm(actual) == norm(value), (ref, actual, value)
        assert set(got) == set(nets), (ref, got, nets)
        audit.append({"ref": ref, "value": actual, "pin_nets": got})
    for ref, model, nets in [
        ("U20", "OPA189IDBVR", ["ADC_J2_BUF", "-3V_AFE", "ADC_J2_FILTER", "ADC_J2_BUF", "+5V_AFE"]),
        ("U10", "OPA320AIDBVR", ["ADC_J2_DRV", "GND", "ADC_OFFSET_0V97", "ADC_J2_SUM", "+3V3"]),
        ("U32", "OPA189IDBVR", ["AFE_OFFSET_BUFFER", "GND", "AFE_OFFSET_FILTER", "AFE_OFFSET_BUFFER", "+5V_AFE"]),
    ]:
        actual = components[ref]["Value"]
        assert actual == model, (ref, actual)
        assert [pins[(ref, str(i+1))] for i in range(5)] == nets
        audit.append({"ref": ref, "value": actual, "pin_nets": nets})
    for ref, contract in {
        "U9": {"2": "+5V_AFE", "4": "GND", "5": "AFE_REF_NR", "6": "AFE_REF_2V5"},
        "U31": {"1": "GND", "2": "AFE_VNEG_RAW", "3": "AFE_VNEG_RAW", "4": "AFE_NEG_FB", "5": "-3V_AFE"},
        "U1": {"T1": "ADC1_INP0"},
        "J2": {"1": "ADC_J2_RAW", "2": "GND"},
    }.items():
        assert all(pins[(ref, p)] == n for p, n in contract.items()), (ref, contract)
        audit.append({"ref": ref, "pin_nets": contract})
    save_json(OUT / "source-audit.json", {"source": str(NET), "sha256": NET_SHA,
        "matched_components": audit, "cad_modified": False,
        "scope": "J2 representative + shared reference; remaining analog channel connections not a full MCU SPICE model"})
    return audit


def includes(ref=True, ldo=False, generic=False):
    files = ["OPA189/OPAx189.LIB", "OPA320-generic-TINA/OPAx320.LIB" if generic else "OPA320/OPAx320-Q1.LIB"]
    if ref:
        files.append("REF5025/REF5025.LIB")
    if ldo:
        files = ["TPS72301/TPS72301.LIB"]
    return "\n".join(f'.include "{(OUT / "models" / f).as_posix()}"' for f in files)


def channel(name="j2", source="DC 0 AC 1", op320="OPAx320-Q1", source_r=50, shunt=100000):
    return f"""
* Actual J2 values; source resistance is generator, not board termination.
Vsig_{name} src_{name} 0 {source}
Rsource_{name} src_{name} raw_{name} {source_r}
R177_{name} raw_{name} 0 {shunt}
R140_{name} raw_{name} filt_{name} 3320
C97_{name} filt_{name} 0 10n
XU20_{name} filt_{name} buf_{name} v5afe vn3 buf_{name} OPAx189
C120_{name} v5afe 0 100n
C121_{name} vn3 0 100n
R137_{name} buf_{name} sum_{name} 4000
XU10_{name} off sum_{name} v3 0 drv_{name} {op320}
C100_{name} v3 0 100n
R187_{name} sum_{name} drv_{name} 2800
C122_{name} sum_{name} drv_{name} 10n
R141_{name} drv_{name} adc_{name} 47
C80_{name} adc_{name} 0 10n
"""


def rails(v5="DC 5", v3="DC 3.3", vn="DC -3.01244", shared=True):
    result = f"""
V5 v5 0 {v5}
V3 v3 0 {v3}
VN vn3 0 {vn}
R200 v5 v5afe 4.7
C156 v5afe 0 4.7u
C157 v5afe 0 4.7u
* Nine unsimulated front buffers: explicit nominal 1.3mA DC rail load EACH.
* This load is an assumption, not a full ten-channel coupling simulation.
Iother v5afe vn3 11.7m
"""
    if shared:
        result += """
XU9 v5afe ref_temp 0 nr ref25 REF5025
C103 v5afe 0 1u
C105 nr 0 1u
R201 ref25 ref_esr 1
C104 ref_esr 0 4.7u
R202 ref25 off_filt 15.8k
R203 off_filt 0 10k
C158 off_filt 0 4.7u
XU32 off_filt off_buf v5afe 0 off_buf OPAx189
C160 v5afe 0 100n
R204 off_buf off 1k
C159 off 0 4.7u
* Nine other OPA320 + input capacitances approximated by 4pF each.
Cother off 0 36p
"""
    else:
        result += f"Voff off 0 DC {VBIAS:.12g}\n"
    return result


def write_deck(name, body, analysis, saves, ref=True, ldo=False, generic=False, method="trap", nodeset=None):
    path = OUT / "decks" / f"{name}.cir"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"STM32H747 representative ADC review: {name}\n"
        "* TI vendor model compatibility run in ngspice 47, NOT Cadence PSpice.\n"
        "* CAD files unchanged; see source-audit.json and model-index.json.\n"
        + includes(ref, ldo, generic) + f"\n.options reltol=1e-5 abstol=1e-12 vntol=1e-7 itl1=500 itl4=1000 method={method}\n.temp 27\n"
        + (f'.include "{Path(nodeset).resolve().as_posix()}"\n' if nodeset else "")
        + body + ("\n.save " + " ".join(saves) if not analysis.startswith(".noise") else "")
        + "\n" + analysis + "\n.end\n", encoding="ascii")
    return path


def raw_read(path):
    """Read single ngspice ASCII plot with real or complex vectors."""
    text = path.read_text(encoding="ascii", errors="strict")
    return raw_plot(text)


def raw_plot(text):
    head, rows = text.split("Values:\n", 1)
    n = int(re.search(r"No. Variables:\s*(\d+)", head)[1])
    count = int(re.search(r"No. Points:\s*(\d+)", head)[1])
    variables = re.findall(r"^\s*\d+\s+(\S+)\s+\S+", head.split("Variables:\n", 1)[1], re.M)
    vals = []
    for line in rows.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        token = tokens[-1]
        if "," in token:
            a, b = token.split(",")
            vals.append(complex(float(a), float(b)))
        else:
            vals.append(float(token))
    assert len(variables) == n and len(vals) == n * count, (n, count, len(vals))
    array = np.array(vals).reshape(count, n)
    return {v: array[:, i] for i, v in enumerate(variables)}


def raw_all(path):
    text = path.read_text(encoding="ascii", errors="strict")
    return [raw_plot("Title:" + p) for p in text.split("Title:")[1:]]


def execute(name, timeout=180, optran=False, analysis=None):
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    base = OUT / "runs" / name
    init = OUT / "runtime" / ("init-optran" if optran else "init")
    init.mkdir(parents=True, exist_ok=True)
    init_text = "set ngbehavior=ps\nset filetype=ascii\nset numdgt=15\n" + ("optran 0 0 0 10n 1m 0\n" if optran else "")
    if not (init / ".spiceinit").exists() or (init / ".spiceinit").read_text() != init_text:
        (init / ".spiceinit").write_text(init_text, encoding="ascii")
    env = os.environ.copy()
    env["SPICE_USERINIT_DIR"] = str(init)
    env["SPICE_SCRIPTS"] = str(EXE.parent.parent / "share/ngspice/scripts")
    t = time.monotonic()
    cmd = [str(EXE), "-b", "-r", str(base.with_suffix(".raw")), "-o", str(base.with_suffix(".log")), str(OUT / "decks" / f"{name}.cir")]
    try:
        done = subprocess.run(cmd, cwd=str(EXE.parent), env=env, capture_output=True, text=True, timeout=timeout)
        result = {"case": name, "returncode": done.returncode, "seconds": round(time.monotonic()-t, 3),
                  "stdout": done.stdout, "stderr": done.stderr, "command": cmd}
    except subprocess.TimeoutExpired:
        result = {"case": name, "timeout_s": timeout, "seconds": round(time.monotonic()-t, 3)}
    log = base.with_suffix(".log").read_text(encoding="utf-8", errors="replace") if base.with_suffix(".log").exists() else ""
    result["warnings"] = [line for line in log.splitlines() if re.search(r"warning|error|failed|singular|timestep too small|trouble", line, re.I)]
    result["raw_exists"] = base.with_suffix(".raw").exists()
    result["deck_sha256"] = sha(OUT / "decks" / f"{name}.cir")
    result["optran_used"] = optran
    try:
        plots = raw_all(base.with_suffix(".raw"))
        result["plots"] = [{"vectors": list(p), "points": len(next(iter(p.values()))),
            "all_finite": all(bool(np.all(np.isfinite(v))) for v in p.values())} for p in plots]
        result["numeric_valid"] = bool(plots) and all(p["all_finite"] and p["points"] > 0 for p in result["plots"])
        expected = analysis.split() if analysis else []
        complete = False
        if expected and plots:
            first = plots[0]
            points = len(next(iter(first.values())))
            if expected[0] == ".op":
                complete = points == 1
            elif expected[0] == ".dc":
                count = round((float(expected[3])-float(expected[2])) / float(expected[4]))+1
                complete = points == count
            elif expected[0] in (".ac", ".noise"):
                freq = np.real(first["frequency"])
                lo, hi = (float(x.lower().replace("meg", "e6")) for x in expected[-2:])
                complete = np.isclose(freq[0], lo) and np.isclose(freq[-1], hi) and bool(np.all(np.diff(freq)>0))
                if expected[0] == ".noise":
                    complete = complete and len(plots) == 2 and "v(onoise_total)" in plots[1]
            elif expected[0] == ".tran":
                stop = expected[2].lower()
                mul = {"m": 1e-3, "u": 1e-6, "n": 1e-9}.get(stop[-1], 1)
                target = float(stop[:-1] if mul != 1 else stop) * mul
                complete = np.isclose(first["time"][-1], target) and bool(np.all(np.diff(first["time"])>0))
        result["analysis_complete"] = bool(complete)
    except (OSError, ValueError, AssertionError, IndexError) as err:
        result["numeric_valid"] = False
        result["parse_error"] = str(err)
    result["run_ok"] = bool(result.get("returncode") == 0 and result["numeric_valid"] and result.get("analysis_complete") and not re.search(r"analysis not run|aborted|doAnalyses:.*[Ee]rror|Timestep too small|could not be simulated", log))
    save_json(base.with_suffix(".json"), result)
    print(json.dumps({"case": name, "seconds": result["seconds"], "warnings_count": len(result["warnings"]),
        "first_warnings": result["warnings"][:3], "raw_exists": result["raw_exists"], "run_ok": result["run_ok"]}, ensure_ascii=True), flush=True)
    return result


SAVES = ["v(raw_j2)", "v(filt_j2)", "v(buf_j2)", "v(drv_j2)", "v(adc_j2)", "v(off)", "v(ref25)", "v(v5afe)", "i(v5)", "i(v3)", "i(vn)"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=["smoke", "dc", "ac", "psrr3", "psrr5", "noise", "sine", "step", "startup", "kick", "ldo", "reference", "reference-noise", "reference-startup"])
    parser.add_argument("--ideal-bias", action="store_true")
    parser.add_argument("--generic", action="store_true")
    parser.add_argument("--v5", type=float, default=5)
    parser.add_argument("--v3", type=float, default=3.3)
    parser.add_argument("--sample-pf", type=float, default=16)
    parser.add_argument("--ron", type=float, default=1000)
    parser.add_argument("--optran", action="store_true")
    parser.add_argument("--method", choices=["trap", "gear"], default="trap")
    parser.add_argument("--nodeset")
    parser.add_argument("--tag", default="")
    parser.add_argument("--save-all", action="store_true")
    parser.add_argument("--reverse", action="store_true")
    args = parser.parse_args()
    audit_source()
    shared = not args.ideal_bias
    name = args.case + ("_ideal" if not shared else "_ref") + ("_generic" if args.generic else "_q1")
    if args.tag:
        assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
        name += "_" + args.tag
    body = rails(v5=f"DC {args.v5}", v3=f"DC {args.v3}", shared=shared)
    source = "DC 0 AC 1"
    analyses = {"smoke": ".op", "dc": ".dc Vsig_j2 -2.001 2.001 .010005",
                "ac": ".ac dec 150 .1 100Meg", "noise": ".noise V(adc_j2) Vsig_j2 dec 120 .1 100Meg",
                "sine": ".tran 2u 60m 0 2u", "step": ".tran .1u 3m 0 .1u"}
    saves = SAVES.copy()
    if args.case == "dc":
        name += f"_{args.v5:g}_{args.v3:g}".replace(".", "p")
    elif args.case == "sine":
        source = f"DC 0 SIN(0 {2/SOURCE_FACTOR:.12g} 60)"
    elif args.case in ("psrr3", "psrr5"):
        body = rails(v5=f"DC {args.v5}" + (" AC 1" if args.case == "psrr5" else ""),
                     v3=f"DC {args.v3}" + (" AC 1" if args.case == "psrr3" else ""), shared=shared)
        source = "DC 0 AC 0"
        analyses[args.case] = ".ac dec 150 .1 100Meg"
    elif args.case == "step":
        source = f"DC {-2/SOURCE_FACTOR:.12g} PULSE({-2/SOURCE_FACTOR:.12g} {2/SOURCE_FACTOR:.12g} 1m 10n 10n 5m 10m)"
    elif args.case == "startup":
        # Ideal prescribed rails: NOT TPS60403 switching/real rail sequencing simulation.
        body = rails("PWL(0 0 1m 0 2m 5)", "PWL(0 0 .1m 0 .2m 3.3)", "PWL(0 0 2m 0 3m -3.01244)", shared=shared)
        source = "DC 0"
        analyses["startup"] = ".tran 20u 400m 0 20u"
    elif args.case == "kick":
        name += f"_{args.sample_pf:g}p_{args.ron:g}ohm"
        if args.reverse:
            name += "_reverse"
        # Acquisition surrogate, not the STM32 transistor model or a guaranteed Cs/Ron.
        # Before each acquisition precharge the isolated Cs to the opposite rail value.
        # This tests 2.8V previous-channel memory on one constant-voltage ADC driver.
        source = f"DC {(-2 if args.reverse else 2)/SOURCE_FACTOR:.12g}"
        body += f"""
Vprev prev 0 DC {0.2472868217 if args.reverse else 3.0472868217}
Vtrack track 0 PULSE(0 1 10u 1n 1n 8u 21.3675213675u)
Vpre pre 0 PULSE(1 0 9.9u 1n 1n 8.2u 21.3675213675u)
Ssample adc_j2 sample track 0 SW_ACQ
Spre sample prev pre 0 SW_PRE
.model SW_ACQ SW(Ron={args.ron:g} Roff=1e14 Vt=.5 Vh=0)
.model SW_PRE SW(Ron=10 Roff=1e14 Vt=.5 Vh=0)
Cs sample 0 {args.sample_pf:g}p
"""
        analyses["kick"] = ".tran 1n 100u 0 1n"
        saves += ["v(sample)", "v(track)", "v(pre)"]
    elif args.case == "ldo":
        body = """
Vraw raw 0 PWL(0 0 1m 0 2m -4.5)
XU31 0 raw raw fb neg TPS72301
R198 neg fb 15.4k
R199 0 fb 10k
C155 fb neg 10n
C153 neg 0 4.7u
C154 neg 0 4.7u
* Positive current into negative rail simulates ten 1.3mA front-buffer returns.
Iload 0 neg 13m
"""
        analyses["ldo"] = ".tran 1u 20m 0 1u"
        saves = ["v(raw)", "v(neg)", "v(fb)", "i(vraw)"]
    elif args.case.startswith("reference"):
        body = """
* Standalone actual REF5025 network; divider is a 25.8k DC load.
V5 v5 0 DC 5 AC 1
R200 v5 v5afe 4.7
C156 v5afe 0 4.7u
C157 v5afe 0 4.7u
Iamps v5afe 0 14.3m
XU9 v5afe ref_temp 0 nr ref25 REF5025
C103 v5afe 0 1u
C105 nr 0 1u
R201 ref25 ref_esr 1
C104 ref_esr 0 4.7u
R202 ref25 off_filt 15.8k
R203 off_filt 0 10k
C158 off_filt 0 4.7u
"""
        saves = ["v(v5afe)", "v(ref25)", "v(nr)", "v(off_filt)", "i(v5)"]
        analyses[args.case] = {"reference": ".op", "reference-noise": ".noise V(off_filt) V5 dec 150 .1 10",
            "reference-startup": ".tran 20u 400m 0 20u"}[args.case]
        if args.case == "reference-startup":
            body = body.replace("DC 5 AC 1", "PWL(0 0 1m 0 2m 5)")
    if args.case != "ldo" and not args.case.startswith("reference"):
        body += channel(source=source, op320="OPAx320" if args.generic else "OPAx320-Q1")
    write_deck(name, body, analyses[args.case], ["all"] if args.save_all else saves, ref=shared,
               ldo=args.case == "ldo", generic=args.generic, method=args.method, nodeset=args.nodeset)
    result = execute(name, optran=args.optran, analysis=analyses[args.case])
    if not result["run_ok"]:
        raise SystemExit(1)
    if "noise" not in args.case:
        raw = raw_read(OUT / "runs" / f"{name}.raw")
        print(json.dumps({"vectors": list(raw), "points": len(next(iter(raw.values()))),
            "last": {k: float(np.real(v[-1])) for k, v in raw.items()}}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
