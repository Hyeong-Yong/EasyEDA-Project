"""Close API polygon loops explicitly without changing intended native geometry."""
import copy
import hashlib
import json
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-pcb-finish-20261018/strip"
SOURCE=HERE/"adc10-strip-phase1-placement-pad-clearance-20261018.json"
TARGET=HERE/"adc10-strip-phase1-explicit-closed-API-polygon-20261018.json"
G=runpy.run_path(str(ROOT/"scripts/draft-adc10-bucket-placement-readonly-20261017.py"))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def main():
    original=json.loads(SOURCE.read_text())
    plan=copy.deepcopy(original)
    changed=[]
    for fill in plan["fillPathUpdates"]:
        before=copy.deepcopy(fill["afterPath"])
        for i,path in enumerate(fill["afterPath"]):
            assert isinstance(path[0],(int,float)) and isinstance(path[1],(int,float))
            assert all(isinstance(v,(int,float)) or v=="L" for v in path),"Unexpected ARC or other command; do not guess closure"
            if path[-2:]!=path[:2]:
                path.extend(path[:2]);changed.append(i)
            assert path[-2:]==path[:2]
        assert all(G["ring_path"](a)==G["ring_path"](b) for a,b in zip(before,fill["afterPath"]))
        fill["nativeIntendedPathBeforeAPIClosureSha256"]=digest(before)
        fill["afterPathSha256"]=digest(fill["afterPath"])
        fill["explicitClosureAddedRingIndexes"]=changed
    plan["schema"]="stm32h747-adc10-strip-phase1-explicit-api-closure-20261018-v2"
    plan["serializationCorrectionOnly"]={"supersedesFrozenManifest":str(SOURCE),"supersededManifestSha256":sha(SOURCE),"reason":"Native format auto-closes rings, but installed PUBLIC fill API fS() rejects unclosed loops. Every API path now ends at its first point explicitly.","intendedGeometryExactlyEqual":True,"ringsChangedByAppendingOnlyInitialXY":len(changed),"ringIndexes":changed,"all294RingsExplicitlyClosed":all(p[-2:]==p[:2] for u in plan["fillPathUpdates"] for p in u["afterPath"]),"doNotReapplyAlreadyCompletedPlacements":True,"geometryOrElectricalChangeVersusOriginalPlan":False}
    plan["operationOrder"]=["Require parent-restored original FILL body and all34 already-placed bodies; do not reapply placement","Verify every corrected polygon loop explicitly ends with its initial XY before any native mutation","Apply only the corrected single FILL path using public API","Capture actual source and require expected polygon geometry plus protected-body audit"]
    TARGET.write_text(json.dumps(plan,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(TARGET),"sha256":sha(TARGET),"newlyExplicitClosedRings":len(changed),"totalRings":len(plan["fillPathUpdates"][0]["afterPath"]),"allLoopsClosed":plan["serializationCorrectionOnly"]["all294RingsExplicitlyClosed"],"geometryExactlyEqual":True}))


if __name__=="__main__":main()
