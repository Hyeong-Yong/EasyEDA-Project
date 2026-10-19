"""Check settling and use saved internal node voltages for a fresh DC Newton solve."""
import concurrent.futures
import json
import math
import re
from pathlib import Path
from diagnose_convergence import HERE, SOURCE, MODELS, digest, run_case

originals = {str(p): digest(p) for p in [SOURCE] + MODELS}
base = SOURCE.read_text(encoding="utf-8-sig")
all_nodes = re.sub(r"(?m)^\.save .*", ".save all", base)
steady = run_case(("optran3ms_all", all_nodes, "ps", "optran 0 0 0 100n 3m 0"))
results = [steady]
assert steady["raw"]["all_finite"]
nodes = steady["raw"]["point0"]
nodeset = "\n".join(f".nodeset {node}={value:.17g}" for node,value in nodes.items() if node.startswith("v(") and math.isfinite(value))
warm = base.replace(".temp 27", nodeset + "\n.temp 27")
cases = [("warm_full_nodes", warm, "ps")]
for name, volts in [("warm_plus2", "2"), ("warm_minus2", "-2")]:
    cases.append((name, warm.replace("Vsig_j2 src_j2 0 DC 0 AC 1", f"Vsig_j2 src_j2 0 DC {volts} AC 1"), "ps"))
cases += [("optran3ms_coarse", base, "ps", "optran 0 0 0 1u 3m 0"), ("optran10ms_coarse", base, "ps", "optran 0 0 0 1u 10m 0")]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results += list(pool.map(run_case,cases))
for result in results:
    log_path = Path(result["deck"]).with_suffix(".log")
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    result["transient_op_used"] = "Transient op started" in log
unchanged = all(digest(Path(p)) == h for p,h in originals.items())
(HERE / "diagnostics-phase3-summary.json").write_text(json.dumps({"originals_unchanged":unchanged,"saved_voltage_nodes":len(nodeset.splitlines()),"results":results},indent=2),encoding="utf-8")
assert unchanged
