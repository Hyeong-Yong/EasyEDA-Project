"""Isolated ngspice convergence diagnostics; original models/decks are read only."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
SIM = HERE.parent.parent
BOARD = SIM.parent.parent
RUNTIME = BOARD / ".tools/ngspice-47/Spice64"
EXE = RUNTIME / "bin/ngspice_con.exe"
SOURCE = SIM / "decks/smoke_ideal_q1.cir"
MODELS = [SIM / "models/OPA189/OPAx189.LIB", SIM / "models/OPA320/OPAx320-Q1.LIB"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_raw(path):
    if not path.exists():
        return {"exists": False}
    text = path.read_text(errors="replace")
    if "Values:" not in text:
        return {"exists": True, "has_values": False, "bytes": path.stat().st_size}
    meta, values = text.split("Values:", 1)
    variables = []
    for line in meta.split("Variables:", 1)[-1].splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0].isdigit():
            variables.append(fields[1])
    points = []
    for line in values.splitlines():
        fields = line.split()
        if fields:
            try:
                points.append(float(fields[-1]))
            except ValueError:
                points.append(math.nan)
    result = dict(zip(variables, points))
    return {"exists": True, "has_values": True, "all_finite": bool(points) and all(math.isfinite(x) for x in points), "point0": result}


def run_case(case):
    name, text, mode, *extra_init = case
    case_dir = HERE / name
    case_dir.mkdir(exist_ok=True)
    deck, log, raw = [case_dir / (name + ext) for ext in (".cir", ".log", ".raw")]
    deck.write_text(text, encoding="utf-8")
    init_dir = case_dir / "init"
    init_dir.mkdir(exist_ok=True)
    (init_dir / ".spiceinit").write_text(f"set ngbehavior={mode}\nset filetype=ascii\n" + "\n".join(extra_init) + "\n", encoding="ascii")
    env = os.environ.copy()
    env["SPICE_USERINIT_DIR"] = str(init_dir)
    env["SPICE_SCRIPTS"] = str(RUNTIME / "share/ngspice/scripts")
    start = time.monotonic()
    result = {"case": name, "mode": mode, "deck": str(deck)}
    try:
        proc = subprocess.run([str(EXE), "-b", "-o", str(log), "-r", str(raw), str(deck)], cwd=RUNTIME / "bin", env=env, text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=35)
        (case_dir / "console.txt").write_text(proc.stdout + proc.stderr, encoding="utf-8")
        log_text = log.read_text(errors="replace") if log.exists() else ""
        result.update(returncode=proc.returncode, raw=parse_raw(raw), issues=[s for s in log_text.splitlines() if re.search(r"warning|error|failed|singular|aborted|solver|data rows|compatibility", s, re.I)][:25])
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
    result["seconds"] = round(time.monotonic() - start, 3)
    printable = dict(result)
    if "raw" in result:
        printable["raw"] = dict(result["raw"])
        if "point0" in printable["raw"]:
            printable["raw"]["point0"] = {k: v for k, v in printable["raw"]["point0"].items() if "." not in k and "#" not in k}
    print(json.dumps(printable, allow_nan=True), flush=True)
    return result


def main():
    originals = {str(p): digest(p) for p in [SOURCE] + MODELS}
    base = SOURCE.read_text(encoding="utf-8-sig")
    cases = []
    for name, option in [
        ("base", ""),
        ("rshunt12", ".options rshunt=1e12\n"),
        ("rshunt9", ".options rshunt=1e9\n"),
        ("gmin10", ".options gmin=1e-10\n"),
        ("rshunt12_gmin10", ".options rshunt=1e12 gmin=1e-10\n"),
        ("klu", ".options klu\n"),
    ]:
        cases.append((name, base.replace(".temp 27", option + ".temp 27"), "ps"))
    cases.extend([(mode, base, mode) for mode in ["psa", "ltpsa"]])
    fixture = """Absolute-zero noiseless resistor diagnostic
.model R_NOISELESS RES (T_ABS=-273.15)
V1 a 0 1
R1 a b R_NOISELESS 1k
R2 b 0 R_NOISELESS 1k
.op
.save v(a) v(b) i(v1)
.end
"""
    cases.append(("noiseless_resistor", fixture, "psa"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(run_case, cases))
    unchanged = all(digest(Path(p)) == h for p, h in originals.items())
    summary = {"original_hashes": originals, "originals_unchanged": unchanged, "results": results}
    (HERE / "diagnostics-summary.json").write_text(json.dumps(summary, indent=2, allow_nan=True), encoding="utf-8")
    assert unchanged


if __name__ == "__main__":
    main()
