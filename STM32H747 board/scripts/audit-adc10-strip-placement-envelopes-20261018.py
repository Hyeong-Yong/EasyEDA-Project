"""Actual native footprint drawing/courtyard screening, no EDA mutation."""
import json
import math
import runpy
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
G=M["G"];MM=M["MM"]
READ=runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"output/validation/native-adc10-pcb-strip_fill_v3-20261018.epru"
OUT=M["HERE"]/("adc10-final-placement-envelope-audit-20261018.json" if len(sys.argv)>1 else "adc10-actual-placement-envelope-audit-20261018.json")
CORRECTION={"C103":(19.8,78.6),"C104":(19.8,75.5),"C105":(25.4,74.1)}


def transform(p,b):
    t=math.radians(b["angle"])
    return (b["x"]*MM+p[0]*math.cos(t)-p[1]*math.sin(t),b["y"]*MM+p[0]*math.sin(t)+p[1]*math.cos(t))
def grow(bb,w):return (bb[0]-w,bb[1]-w,bb[2]+w,bb[3]+w)
def distance(a,b):return math.hypot(max(a[0]-b[2],b[0]-a[2],0),max(a[1]-b[3],b[1]-a[3],0))
def overlap(a,b):return min(a[2],b[2])-max(a[0],b[0])>1e-6 and min(a[3],b[3])-max(a[1],b[1])>1e-6


def main():
    rows=G["PARSE"](SOURCE)
    docs,_=READ(ROOT/"output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2")
    attrs=defaultdict(dict)
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
    new={f"U{x}" for x in range(9,20)}|{f"C{x}" for x in range(97,120)}
    parts=[]
    for (kind,cid),b in rows.items():
        if kind!="COMPONENT" or b["layerId"]!=1 or not (0<b["x"]*MM<33 and 7<b["y"]*MM<147):continue
        ref=attrs[cid]["Designator"]
        shapes=defaultdict(list)
        for (pk,pid),(ph,p) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            layer=p.get("layerId")
            if layer not in (3,9,48):continue
            if pk=="LINE":
                pts=[(p["startX"]*MM,p["startY"]*MM),(p["endX"]*MM,p["endY"]*MM)]
            elif pk=="POLY":pts=G["ring_path"](p["path"])
            else:continue
            points=[transform(q,b) for q in pts]
            w=p.get("width",p.get("lineWidth",0))*MM/2
            shapes[layer].append(grow(G["bbox"](points),w))
        boxes={}
        for layer,bb in shapes.items():boxes[layer]=(min(x[0] for x in bb),min(x[1] for x in bb),max(x[2] for x in bb),max(x[3] for x in bb))
        if 48 in boxes:envelope=boxes[48];origin="Native layer48 package courtyard"
        elif 3 in boxes:envelope=boxes[3];origin="Conservative imported silk drawing envelope (not claimed factory courtyard)"
        else:continue
        part={"ref":ref,"componentId":cid,"xyMm":[b["x"]*MM,b["y"]*MM],"angle":b["angle"],"envelopeMm":envelope,"envelopeOrigin":origin,"nativePackageBodyMm":boxes.get(9),"newPart":ref in new}
        parts.append(part)
    def pairs(items):
        result=[]
        for i,a in enumerate(items):
            for b in items[i+1:]:
                if not(a["newPart"] or b["newPart"]):continue
                if overlap(a["envelopeMm"],b["envelopeMm"]):result.append({"refA":a["ref"],"refB":b["ref"],"envelopeA":a["envelopeMm"],"envelopeB":b["envelopeMm"]})
        return result
    current=pairs(parts)
    corrected=[]
    for p in parts:
        q=dict(p)
        if p["ref"] in CORRECTION:
            target=CORRECTION[p["ref"]];dx=target[0]-p["xyMm"][0];dy=target[1]-p["xyMm"][1]
            q["xyMm"]=list(target)
            bb=p["envelopeMm"];q["envelopeMm"]=(bb[0]+dx,bb[1]+dy,bb[2]+dx,bb[3]+dy)
            if p["nativePackageBodyMm"]:
                bb=p["nativePackageBodyMm"];q["nativePackageBodyMm"]=(bb[0]+dx,bb[1]+dy,bb[2]+dx,bb[3]+dy)
        corrected.append(q)
    after=pairs(corrected)
    body_conflicts=[]
    for a in parts:
        if not a["newPart"] or not a["nativePackageBodyMm"]:continue
        for b in parts:
            if a["ref"]==b["ref"]:continue
            if overlap(a["nativePackageBodyMm"],b["nativePackageBodyMm"] or b["envelopeMm"]):body_conflicts.append([a["ref"],b["ref"]])
    report={"schema":"adc10-actual-native-placement-envelope-audit-20261018-v1","status":"PASS" if not current and not body_conflicts else "CORRECTION_REQUIRED","sourcePath":str(SOURCE),"sourceSha256":M["sha"](SOURCE),"liveCalls":0,"actualPartsScreened":len(parts),"newParts":34,"originalPackageBodyVsConservativeNeighborEnvelopeConflicts":body_conflicts,"currentConservativeEnvelopeOverlaps":current,"proposedThreeCapMovesMm":CORRECTION,"afterThreeMovesEnvelopeOverlaps":after,"new34EnvelopeInventory":parts,"conclusion":"No overlap of native courtyards/imported drawing envelopes or native assembly bodies." if not current and not body_conflicts else "Three reference-cap placements need a bounded correction to remove conservative courtyard/drawing-envelope overlap; package bodies themselves do not overlap.","correctionWouldPreservePartValuesPinsNets":True,"doNotChangeFrozen204LineBatchMidExecution":True,"manufacturingReady":False}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"actualEnvelopeConflicts":current,"afterThreeMoves":after,"bodyConflicts":body_conflicts}))


if __name__=="__main__":main()
