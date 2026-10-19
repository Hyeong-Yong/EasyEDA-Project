"""Freeze only the independentlyscreenable10row electricalconnections."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=HERE/"local-row-routing-short-negative-v1b-draft.json"
report=json.loads(source.read_text(encoding="utf8"))
assert not report["exactLiteralCopperConflicts"]
lines=report["newLineCreates"][:290]
assert [p["key"] for p in lines]==[f"LABTOOL_LOCAL_{i:04}" for i in range(1,291)]
keep={p["key"] for p in lines};roles={p["role"] for p in lines}
report["newLineCreates"]=lines
report["routedConnections"]=[p for p in report["routedConnections"] if set(p["lineKeys"])<=keep]
report["unroutedConnections"]=[p for p in report["unroutedConnections"] if p["role"] in roles]
assert not report["unroutedConnections"]
negative=[p["lengthMm"] for p in report["routedConnections"] if p["net"]=="-3V_AFE"]
assert len(negative)==10 and max(negative)<3
report["negativeDecouplerLeadLengthMm"]=negative
report["frozenArtifactSourceSha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
target=HERE/"frozen-short-negative-row290-variant-v1b.json"
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
print(json.dumps({"target":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"negativeLeadLengthsMm":negative}))
