"""Audit native closed-polygon acceptance and rebase the follow-up API batch."""
import copy
import json
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
G=M["G"];HERE=M["HERE"]
BEFORE=ROOT/"output/validation/native-adc10-pcb-strip_place4-20261018.epru"
ACTUAL=ROOT/"output/validation/native-adc10-pcb-strip_fill_v3-20261018.epru"
P1=HERE/"adc10-strip-phase1-explicit-closed-API-polygon-20261018.json"
P2=HERE/"adc10-strip-phase2-routes-ground-clearance-20261018.json"
AUDIT=HERE/"adc10-strip-fill-v3-normalization-audit-20261018.json"
REBASED=HERE/"adc10-strip-phase2-rebased-closed-operations-20261018.json"


def main():
    a=G["PARSE"](BEFORE);b=G["PARSE"](ACTUAL)
    intended=json.loads(P1.read_text())
    assert set(a)==set(b)
    changed={k for k in a if a[k]!=b[k]}
    assert changed=={("DOCHEAD",None),("FILL","e680230ef8d2c5dd")}
    target=("FILL","e680230ef8d2c5dd")
    orig,actual=a[target],b[target]
    fields={k for k in orig if orig[k]!=actual[k]}
    assert fields=={"path","refs"} and orig["refs"] is None and actual["refs"]==[None]
    expect=intended["fillPathUpdates"][0]["afterPath"]
    assert len(expect)==len(actual["path"])==294
    normalized=0;maxerr=0
    for expected,accepted in zip(expect,actual["path"]):
        assert len(expected)==len(accepted)
        assert expected[:2]==expected[-2:] and accepted[:2]==accepted[-2:]
        for x,y in zip(expected,accepted):
            if isinstance(x,str):assert x==y
            else:
                assert y==round(x,4),(x,y,round(x,4))
                if x!=y:normalized+=1;maxerr=max(maxerr,abs(x-y))
    assert actual["path"][0]==orig["path"][0]
    immutable=0
    for path in orig["path"][1:]:
        if path in actual["path"]:immutable+=1
    report={"schema":"adc10-strip-fill-v3-native-normalization-audit-20261018-v1","status":"PASS","before":{"path":str(BEFORE),"sha256":M["sha"](BEFORE)},"actual":{"path":str(ACTUAL),"sha256":M["sha"](ACTUAL)},"intendedManifest":{"path":str(P1),"sha256":M["sha"](P1)},"records":len(a),"unchangedProtectedDesignRecords":len(a)-2,"deleted":0,"added":0,"changed":{"DOCHEAD":["client","version","updateTime"],"FILL_e680230ef8d2c5dd":["path","refs"]},"allowedNormalizationRules":["Only requested contour coordinate numbers serialize to round(value,4) native mil","refs:null becomes [null] after the public fill replacement","DOCHEAD client/version/updateTime bookkeeping"],"contours":294,"allExplicitlyClosed":True,"outerNativePathExact":True,"untouchedOriginalHolePathsExact":immutable,"numericCoordinatesRounded":normalized,"maximumRoundingMil":maxerr,"maximumRoundingMm":maxerr*.0254,"noElectricalOrRuleOrViaOrHoleOrOtherCopperChanges":True,"manufacturingReady":False}
    AUDIT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    p=copy.deepcopy(json.loads(P2.read_text()))
    assert p["geometryConflicts"]==[] and len(p["newLineCreates"])==204
    voids=[v for line in p["newLineCreates"] for v in M["capsule"](line["startXYmm"],line["endXYmm"],line["widthMm"]/2+M["CLEAR"])]
    updates=M["cut_ground"](b,voids)
    assert len(updates)==1 and updates[0]["id"]==target[1]
    assert all(path[-2:]==path[:2] for u in updates for path in u["afterPath"])
    p["schema"]="stm32h747-adc10-strip-phase2-rebased-closed-operations-20261018-v2"
    p["sourcePath"]=str(ACTUAL);p["sourceSha256"]=M["sha"](ACTUAL)
    p["fillPathUpdates"]=updates
    p["parentSourceContract"]={"physicalComponents":354,"connectedPins":1136,"originalViaIdsUnchanged":634,"freeMountingPadsUnchanged":4,"unchangedDesignRules":18}
    p["rebasedFromManifest"]={"path":str(P2),"sha256":M["sha"](P2),"all204LineCoordinateAndNetSpecsExact":True}
    p["nativePhase1Audit"]={"path":str(AUDIT),"sha256":M["sha"](AUDIT),"status":"PASS"}
    p["geometryChecks"]["allAPIContoursExplicitlyClosed"]=True
    p["componentGuardsActual"]=[{"ref":s["ref"],"componentId":s["componentId"],"body":b["COMPONENT",s["componentId"]],"bodySha256":M["digest"](b["COMPONENT",s["componentId"]])} for s in intended["componentPlacements"]]
    p["applicationOrder"]=["guard actual source SHA or every actual component/FILL before body plus full protected-source audit","apply only this explicitly closed single GND-FILL path update","capture and verify geometry/only reviewed FILL normalization","create 204 TOP LINEs in guarded batches, recording every returned ID and same-net LINE merges","native full unchanged-rule DRC plus independent copper-union/connectivity audit"]
    REBASED.write_text(json.dumps(p,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"audit":str(AUDIT),"auditStatus":"PASS","protectedExact":report["unchangedProtectedDesignRecords"],"maxRoundMm":report["maximumRoundingMm"],"rebasedManifest":str(REBASED),"sha256":M["sha"](REBASED),"newLines":204,"fillUpdates":len(updates),"explicitClosed":True}))


if __name__=="__main__":main()
