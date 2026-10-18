"""Bounded public-API placement/routing plans; never writes an EDA source file."""
import copy
import hashlib
import json
import math
import runpy
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/".tools/adc-geometry-deps"))
import pyclipper as pc

G=runpy.run_path(str(ROOT/"scripts/draft-adc10-bucket-placement-readonly-20261017.py"))
G["arc"].__globals__["SAG"]=.0001
SOURCE=ROOT/"output/validation/native-adc10-pcb-baseline-20261018.epru"
ISOLATION=ROOT/"output/candidates/adc10-pcb-finish-20261018/adc10-copper-cut-execution-manifest-fresh-20261018.json"
OLD_PLAN=ROOT/"output/analysis/adc10-new34-placement-plan-20261017.json"
HERE=ROOT/"output/candidates/adc10-pcb-finish-20261018/strip"
MM=.0254
SCALE=1000000
CLEAR=.17


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def ip(points):return [(round(x*SCALE),round(y*SCALE)) for x,y in points]
def fp(points):return [(x/SCALE,y/SCALE) for x,y in points]
def positive(points):return points if pc.Area(points)>0 else list(reversed(points))
def union(paths):
    if not paths:return []
    c=pc.Pyclipper();c.PreserveCollinear=True
    c.AddPaths([positive(p) for p in paths],pc.PT_SUBJECT,True)
    return c.Execute(pc.CT_UNION,pc.PFT_NONZERO,pc.PFT_NONZERO)
def intersection(a,b):
    if not a or not b:return []
    c=pc.Pyclipper();c.AddPaths(a,pc.PT_SUBJECT,True);c.AddPaths(b,pc.PT_CLIP,True)
    return c.Execute(pc.CT_INTERSECTION,pc.PFT_NONZERO,pc.PFT_NONZERO)
def area(paths):return sum(abs(pc.Area(p)) for p in paths)/SCALE**2
def expanded(path,margin):
    p=pc.PyclipperOffset(2,.00005*SCALE);p.AddPath(positive(path),pc.JT_ROUND,pc.ET_CLOSEDPOLYGON)
    return p.Execute(margin*SCALE)
def capsule(a,b,radius):
    if math.dist(a,b)<1e-8:
        return [ip([(a[0]+radius*math.cos(t*math.tau/64),a[1]+radius*math.sin(t*math.tau/64)) for t in range(64)])]
    o=pc.PyclipperOffset(2,.00005*SCALE);o.AddPath(ip([a,b]),pc.JT_ROUND,pc.ET_OPENROUND)
    return o.Execute(radius*SCALE)
def native_path(points):
    points=fp(points)
    out=[points[0][0]/MM,points[0][1]/MM,"L"]
    for x,y in points[1:]:out.extend([x/MM,y/MM])
    out.extend(out[:2])
    return out
def bounds(paths):return G["bbox"]([p for path in paths for p in fp(path)])
def shapes_intersect(a,b):
    if not a or not b or not G["bb_overlap"](bounds(a),bounds(b)):return False
    return area(intersection(a,b))>1e-10


def cut_ground(rows,voids):
    """Union overlapping old holes/new voids; preserve untouched native paths."""
    voids=union(voids)
    output=[]
    for (kind,rid),body in rows.items():
        if kind!="FILL" or body.get("layerId")!=1 or body.get("netName")!="GND":continue
        path=body["path"]
        polys=[ip(G["ring_path"](r)) for r in path]
        relevant=intersection(voids,[positive(polys[0])])
        if not relevant:continue
        # Existing holes are filled regions for the Boolean hole union.
        affected=set();current=union(relevant)
        while True:
            more={i for i in range(1,len(path)) if i not in affected and shapes_intersect([positive(polys[i])],current)}
            if not more:break
            affected|=more
            current=union(current+[positive(polys[i]) for i in more])
        # A cut reaching the outer boundary needs a contour Boolean, not a hole
        # append. Reject instead of inventing an unreviewed outer-boundary edit.
        edges=[(a,b,G["bbox"]([a,b])) for a,b in G["ring_edges"](fp(polys[0]))]
        for hole in relevant:
            hbounds=G["bbox"](fp(hole))
            nearby=[(c,d,bb) for c,d,bb in edges if G["bb_overlap"](hbounds,bb)]
            for a,b in G["ring_edges"](fp(hole)):
                ab=G["bbox"]([a,b])
                assert not any(G["bb_overlap"](ab,bb) and G["seg_inter"](a,b,c,d) for c,d,bb in nearby), ("CUT_REACHES_OUTER",rid)
        # Unaffected native outer/hole arrays retain their original coordinates
        # and arc commands exactly. Affected hole arcs are tracked explicitly.
        after=[copy.deepcopy(path[0])]+[copy.deepcopy(r) for i,r in enumerate(path[1:],1) if i not in affected]
        added=[native_path(positive(h)) for h in current]
        after.extend(added)
        before_holes=union([positive(p) for p in polys[1:]])
        after_holes=union([positive(ip(G["ring_path"](r))) for r in after[1:]])
        c=pc.Pyclipper()
        if before_holes:c.AddPaths(before_holes,pc.PT_SUBJECT,True)
        if after_holes:c.AddPaths(after_holes,pc.PT_CLIP,True)
        old_void_lost=c.Execute(pc.CT_DIFFERENCE,pc.PFT_NONZERO,pc.PFT_NONZERO) if before_holes else []
        assert area(old_void_lost)<1e-7,("COPPER_ADDITION",rid,area(old_void_lost))
        old_arc_count=sum(sum(v=="ARC" for v in path[i]) for i in affected)
        output.append({"id":rid,"type":"FILL","sourceBodyBefore":body,"beforeBodySha256":digest(body),"beforePathSha256":digest(path),"afterPath":after,"afterPathSha256":digest(after),"allowedChangedFields":["path"],"outerPathExact":after[0]==path[0],"untouchedOriginalHoles":len(path)-1-len(affected),"affectedOriginalHoleIndexes":sorted(affected),"affectedOriginalArcCommands":old_arc_count,"newUnionHoleCount":len(current),"copperAdditionAreaAgainstTessellatedInputMm2":area(old_void_lost),"arcTessellationSagittaMm":.0001,"requiresNativeDRC":True})
    return output


def main():
    assert sha(SOURCE)=="5a1fe43c0ce8e36ee89bcac512321e55610b83c3e890b429373878efb6825b9b"
    rows=G["PARSE"](SOURCE)
    old=G["PARSE"](ROOT/"output/validation/native-adc10-pcb-oriented_reopened-20261017.epru")
    diff=[k for k in rows.keys()&old.keys() if rows[k]!=old[k]]
    assert set(rows)==set(old) and diff==[("DOCHEAD",None)]
    isolation=json.loads(ISOLATION.read_text())
    assert isolation["sourceSha256"]==sha(SOURCE) and isolation["passedPreflightGuards"]
    plan=json.loads(OLD_PLAN.read_text())
    placements=[];pads=[]
    for p in plan["edits"]:
        cid=p["componentId"];before=rows["COMPONENT",cid]
        assert before["attrs"]["Unique ID"]==p["uniqueId"]
        after=copy.deepcopy(before);after.update({"x":p["set"]["x"],"y":p["set"]["y"],"angle":p["set"]["rotation"],"layerId":1})
        placements.append({"ref":p["ref"],"componentId":cid,"uniqueId":p["uniqueId"],"beforeBodySha256":digest(before),"beforeBody":before,"afterBody":after,"allowedChangedFields":["x","y","angle"],"expectedWorldPads":p["pads"],"method":"get/toAsync/setState_X/setState_Y/setState_Rotation/done"})
        for pad in p["pads"]:pads.append({**pad,"ref":p["ref"]})
    assert len(placements)==34
    voids=[]
    for pad in pads:
        if pad["net"]!="GND":voids.extend(expanded(ip(pad["rectangleXYmm"]),CLEAR))
    # R164 translates only .05 mm. Clear its two non-ground pads at final sites.
    for anchor in isolation["newRouteAnchors"]:
        if anchor["biasResistor"]!="R164":continue
        for pname in ("biasPad1PRE","biasPad2Quiet2V5"):
            x,y=anchor[pname]["xyMmYUp"]
            rect=[(x-.32,y-.27),(x+.32,y-.27),(x+.32,y+.27),(x-.32,y+.27)]
            voids.extend(expanded(ip(rect),CLEAR))
    updates=cut_ground(rows,voids)
    assert len(updates)==1 and updates[0]["id"]=="e680230ef8d2c5dd"
    # Stage one is intentionally isolated so the parent can place/check the
    # new physical pads while subsequent route manifests are reviewed.
    report={"schema":"stm32h747-adc10-strip-phase1-public-operations-20261018-v1","sourcePath":str(SOURCE),"sourceSha256":sha(SOURCE),"projectNameRequired":"STM32H747_MCU_BOARD_v19","PCBRequired":"0ac2a19168000d8e","readOnlyBuilder":True,"liveCalls":0,"wholePCBSetSource":False,"requiresIsolationManifestAppliedFirst":str(ISOLATION),"frozenSchematic":{"parts":354,"connectedPins":1136,"openZeroDetector":False},"operationOrder":["guard every source component and FILL body","apply parent-reviewed copper isolation and R164 move","apply 34 placements","set only listed FILL complex-polygon path","capture source and run full unchanged-rule native DRC"],"componentPlacements":placements,"fillPathUpdates":updates,"newLineCreates":[],"clearanceOffsetMm":CLEAR,"geometryChecks":{"fresh18VsSaved17OnlyDOCHEAD":True,"all34PadCoordinatesFromVerifiedRuntimeFootprints":True,"nativeOuterGroundBoundaryExact":all(u["outerPathExact"] for u in updates),"originalGroundHolesModified":sum(len(u["affectedOriginalHoleIndexes"]) for u in updates),"originalGroundArcsInModifiedHoles":sum(u["affectedOriginalArcCommands"] for u in updates),"noTessellatedCopperAdded":True,"fullRoutingCompleted":False},"api":{"fill":"pcb_PrimitiveFill.get(id) → toAsync() → setState_ComplexPolygon(pcb_MathPolygon.createComplexPolygon(afterPath)) → await done()","line":"pcb_PrimitiveLine.create(net,EPCB_LayerId.TOP,startXMil,startYMil,endXMil,endYMil,widthMil,false)"},"safety":{"VIAChanges":0,"freePADChanges":0,"nonGNDExistingCopperChanges":0,"rulesChanged":0,"layersChanged":0,"J18Changed":0,"manufacturingReady":False},"afterApplyRequirement":"Reject any design-body delta not among parent isolation/R164, these 34 COMPONENT placements/owned ATTR transforms, and this single FILL path. Native DRC is mandatory before proceeding."}
    HERE.mkdir(parents=True,exist_ok=True)
    target=HERE/"adc10-strip-phase1-placement-pad-clearance-20261018.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"manifest":str(target),"placements":len(placements),"fillUpdates":len(updates),"oldHolesModified":report["geometryChecks"]["originalGroundHolesModified"],"oldArcsAffected":report["geometryChecks"]["originalGroundArcsInModifiedHoles"]}))


if __name__=="__main__":main()
