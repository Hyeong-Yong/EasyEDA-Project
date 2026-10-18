"""Guarded offline six-cap move-only data; no live editor calls."""
import hashlib
import json
import math
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-pcb-finish-20261018/bottom-buckets"
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
SOURCE=ROOT/"output/validation/native-adc10-pcb-direct4_copper-20261018.epru"
LAYOUT=HERE/"remaining6-rebased-layout.json"
OUT=HERE/"remaining6-move-only-guarded-20261018.json"


def main():
    assert M["sha"](SOURCE)=="f4c4fd15b00355d60b78391249c64aff1dd99903597fdbf937ed5dbb48c9fc4a"
    layout=json.loads(LAYOUT.read_text())
    assert layout["sourceSha256"]==M["sha"](SOURCE)
    rows=M["G"]["PARSE"](SOURCE)
    channels=layout["channels"]
    assert {r["ref"] for r in channels}=={"C80","C82","C87","C93","C94","C95"}
    moves=[]
    for r in channels:
        before=rows["COMPONENT",r["componentId"]]
        axis=r["axisOfPositiveLocalX"]
        angle=round(math.degrees(math.atan2(axis[1],axis[0])))%360
        layer=1 if r["targetLayer"]=="TOP" else 2
        moves.append({"ref":r["ref"],"primitiveId":r["componentId"],"beforeComponentBody":before,"beforeComponentBodySha256":M["digest"](before),"targetLayerId":layer,"targetXYmil":[v/M["MM"] for v in r["centerXYmm"]],"axisAngleWorldDegrees":angle,"requiredWorldPadsMm":r["requiredWorldPads"],"assemblyBoundingBoxMm":r["assemblyBoundingBoxMm"],"electricalEscapeToCapPathMm":r["electricalEscapeToCapPathMm"]})
    report={"schema":"adc10-remaining-six-cap-move-only-20261018-v1","status":"READY_FOR_GUARDED_MOVE_ONLY_NATIVE_REVIEW","sourcePath":str(SOURCE),"sourceSha256":M["sha"](SOURCE),"layoutPath":str(LAYOUT),"layoutSha256":M["sha"](LAYOUT),"componentMoves":moves,"lineCreates":[],"viaCreates":[],"fillModifyOperations":[],"fillCreateOperations":[],"nativeCalls":0,"beforeSourcePhysicalComponents":354,"connectedPinsUnchanged":1136,"allExistingCopperAndOriginalDrillsMustRemainExactDuringThisStage":True,"postMoveRequired":"Capture source. Only six COMPONENT x/y/angle/layerId and owned ATTR display transforms may change. Confirm all twelve native world pin coordinates/net names before any copper operations. This move-only state is not expected to pass DRC until the separately reviewed cuts/routing are applied.","bottomRotationCalibration":"Actual native C88 BOTTOM angle180 placed PIN1 left and PIN2 right; observed world local+X follows native angle, no guessed X reflection.","C80C82PhysicalPairProof":{"bothAxisMinusY":True,"centerDeltaXmm":.92,"package1005XwidthMm":.5,"bodyGapMm":.42,"nativePadXwidthMm":.62,"padGapMm":.30,"importedSilkProxyOverlapMm":.08,"noDRCChecksSuppressed":True},"manufacturingReady":False}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"manifest":str(OUT),"sha256":M["sha"](OUT),"moves":len(moves),"refs":[r["ref"] for r in moves]}))


if __name__=="__main__":main()
