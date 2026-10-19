"""Freeze the reviewed baseline310route draft; no native calls or source edits."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=HERE/"local-row-routing-draft.json"
report=json.loads(source.read_text(encoding="utf8"))
assert len(report["newLineCreates"])>=310 and not report["exactLiteralCopperConflicts"]
kept=report["newLineCreates"][:310]
assert [p["key"] for p in kept]==[f"LABTOOL_LOCAL_{i:04}" for i in range(1,311)]
assert all(p["role"] not in ("Quiet offsetbus branch to finalOPA320+",) for p in kept)
keepkeys={p["key"] for p in kept}
report["newLineCreates"]=kept
report["routedConnections"]=[p for p in report["routedConnections"] if set(p["lineKeys"])<=keepkeys]
report["unroutedConnections"]=[p for p in report["unroutedConnections"] if p["role"] in {q["role"] for q in kept}]
assert not report["unroutedConnections"]
report["frozenArtifactSourceSha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
report["frozenVariant"]="Initial107placements; negativebypass8.79mm retained only asfallback, not low-noisefinalchoice"
target=HERE/"frozen-row310-initial-placement-route-draft.json"
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
print(json.dumps({"target":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest()}))
