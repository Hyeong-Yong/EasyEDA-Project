"""Keep frozen43ports exact; append only reviewed3newfeed/filterports."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
old=HERE/"six-layer-via-port-candidates-commonpower-v4.json"
new=HERE/"six-layer-via-port-candidates-shared-v5b.json"
a=json.loads(old.read_text());b=json.loads(new.read_text())
assert len(a["viasProposed"])==43 and not b["failedPorts"]
oldkeys={p["key"] for p in a["viasProposed"]}
added=[p for p in b["viasProposed"] if p["key"] not in oldkeys]
assert len(added)==3
b["viasProposed"]=a["viasProposed"]+added
b["original43PortsExactSourceSha256"]=hashlib.sha256(old.read_bytes()).hexdigest()
b["new3PortsSourceSha256"]=hashlib.sha256(new.read_bytes()).hexdigest()
b["note"]="Original43geometrykept;REF_PLUS(29,72.9)wasnotshifted. Subsequenttracesmustpassfull.1535mmcrosscheck. ThreeaddedportswerescreenedagainstsharedTOP/commonV5/RAW5V2."
target=HERE/"frozen-shared46-ports-v5.json"
assert not target.exists()
target.write_text(json.dumps(b,indent=2)+"\n",encoding="utf8")
print(json.dumps({"target":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"count":len(b["viasProposed"])}))
