"""One-part placement contract for the parent-approved C95 routing option."""
import json
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
SOURCE=ROOT/"output/validation/native-adc10-pcb-remaining6_move-20261018.epru"
OUT=ROOT/"output/candidates/adc10-pcb-finish-20261018/bottom-buckets/c95-rotation0-move-only-guard-20261018.json"


def main():
    assert M["sha"](SOURCE)=="af83b97cf7b775d834fc8339eb627beade225247ff077c2a234b3a50a4f808d4"
    rows=M["G"]["PARSE"](SOURCE)
    cid=next(b["parentId"] for (k,i),b in rows.items() if k=="ATTR" and b.get("key")=="Designator" and b.get("value")=="C95")
    before=rows["COMPONENT",cid]
    assert before["layerId"]==1 and before["angle"]==180
    move={"ref":"C95","primitiveId":cid,"beforeComponentBody":before,"beforeComponentBodySha256":M["digest"](before),"targetLayerId":1,"targetXYmil":[before["x"],before["y"]],"axisAngleWorldDegrees":0,"requiredWorldPadsMm":{"1":{"net":"ADC3_INP7","xyMm":[54.48,77.3]},"2":{"net":"GND","xyMm":[53.52,77.3]}},"assemblyBoundingBoxMm":[53.05,76.8,54.95,77.8],"allowedChangedComponentFields":["angle"]}
    report={"schema":"adc10-c95-approved-rotation0-move-only-20261018-v1","status":"GUARDED_MOVE_ONLY_PENDING_FAR_VIA_COPPER_PROOF","sourcePath":str(SOURCE),"sourceSha256":M["sha"](SOURCE),"componentMoves":[move],"lineCreates":[],"viaCreates":[],"fillModifyOperations":[],"fillCreateOperations":[],"nativeCalls":0,"reason":"Parent approved rotating C95 only at unchanged54,77.3mm center so a far-x55.36,78.44 signal via can avoid the original layer17 GND neck. Signal and GND routing are unapplied and must be regenerated/verified separately.","operationGates":["Far-via option passes all-six-layer copper/drill/body and original-neighbor GND-anchor preservation proof.","Change only C95 angle180->0. All other component fields, copper, original drills and rules must remain exact; owned ATTR display rigid transforms may follow native behavior.","Verify actual native PIN1ADC3_INP7right54.48,77.3 and PIN2GNDleft53.52,77.3 before applying final revised-copper contract."],"manufacturingReady":False}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"path":str(OUT),"sha256":M["sha"](OUT),"componentId":cid,"changes":"C95angle180->0 ONLY"}))


if __name__=="__main__":main()
