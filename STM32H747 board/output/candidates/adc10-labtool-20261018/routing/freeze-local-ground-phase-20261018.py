"""Freeze only the TOProw+dedicatedreturns phase; no fullboardclaim."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
source=HERE/"local-row-routing-short-negative-ground-v2-draft.json"
report=json.loads(source.read_text(encoding="utf8"))
assert not report["exactLiteralCopperConflicts"]
limit=report["localGroundAndSupplyLineCount"]
assert limit==332 and report["rowCoreLineCount"]==300
lines=report["newLineCreates"][:limit];keys={p["key"] for p in lines};roles={p["role"] for p in lines}
report["newLineCreates"]=lines
report["routedConnections"]=[p for p in report["routedConnections"] if set(p["lineKeys"])<=keys]
report["unroutedConnections"]=[p for p in report["unroutedConnections"] if p["role"] in roles]
assert not report["unroutedConnections"]
report["newViaCreates"]=[p for p in report["newViaCreates"] if p["key"].startswith("AFE_PLUS_PORT_J") or p["key"].startswith("AFE_MINUS_PORT_J") or p["key"].startswith("GND_")]
assert len(report["newViaCreates"])==32
report["plannedVias"]=32
report["phaseScope"]="10rowTOPsignal/bypass+20railportstubs+12dedicatedGNDreturns; NOTsharedrails/commonpower/offsetcompletion"
report["frozenArtifactSourceSha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
target=HERE/"frozen-local-ground-phase332-v2.json"
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
print(json.dumps({"target":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"lines":limit,"vias":32}))
