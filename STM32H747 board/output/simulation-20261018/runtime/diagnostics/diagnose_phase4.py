"""Validate internal-opamp-only nodesets and zero DC capacitor currents."""
import concurrent.futures
import json
from pathlib import Path
from diagnose_convergence import HERE, SOURCE, MODELS, digest, run_case

originals = {str(p): digest(p) for p in [SOURCE] + MODELS}
base = SOURCE.read_text(encoding="utf-8-sig")
prior = json.loads((HERE/"diagnostics-phase3-summary.json").read_text())
values = prior["results"][0]["raw"]["point0"]
nodeset = "\n".join(f".nodeset {node}={value:.17g}" for node,value in values.items() if node.startswith("v(xu"))
warm = base.replace(".temp 27", nodeset + "\n.temp 27")
caps = ["c97_j2", "c122_j2", "c80_j2", "c156", "c157"]
warm = warm.replace(".op", ".save " + " ".join(f"@{name}[i]" for name in caps) + "\n.op")
cases = [("warm_internal_nodes", warm, "ps")]
for name, volts in [("warm_internal_plus2", "2"), ("warm_internal_minus2", "-2")]:
    cases.append((name,warm.replace("Vsig_j2 src_j2 0 DC 0 AC 1",f"Vsig_j2 src_j2 0 DC {volts} AC 1"),"ps"))
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(run_case,cases))
for result in results:
    log = Path(result["deck"]).with_suffix(".log").read_text(errors="replace")
    result["transient_op_used"] = "Transient op started" in log
unchanged = all(digest(Path(p)) == h for p,h in originals.items())
(HERE/"diagnostics-phase4-summary.json").write_text(json.dumps({"originals_unchanged":unchanged,"internal_voltage_nodes":len(nodeset.splitlines()),"results":results},indent=2),encoding="utf-8")
assert unchanged
