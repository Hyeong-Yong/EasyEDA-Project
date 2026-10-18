"""Literal independent same-layer copper anchor screen for one new shard."""
import hashlib
import json
import runpy
import sys
from pathlib import Path
from shapely.geometry import Polygon,LineString,Point
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-pcb-finish-20261018"
V=runpy.run_path(str(ROOT/"scripts/audit-adc10-remaining6-fill-validity-20261018.py"))
PARSE=V["OLD"]["PARSE"]
SOURCE=ROOT/"output/validation/native-adc10-pcb-direct4_copper-20261018.epru"
PLAN=HERE/"bottom-buckets/remaining6-rebased-layout-local-api-operations.json"


def main():
    after_plan=Path(sys.argv[1]) if len(sys.argv)>1 else PLAN
    data=json.loads(after_plan.read_text())
    target=next((o for o in data["fillModifyOperations"] if o["primitiveId"]=="b99d5f8f2cae6046"),{"primitiveId":"b99d5f8f2cae6046"})
    # Prefer the frozen independently identified contour even if the child
    # already corrected the operation file while this read-only audit starts.
    cleanup_data=json.loads(PLAN.read_text())
    cleanup=next(r for r in cleanup_data["localNewOrphanFragmentCleanup"] if r["sourceFillId"]==target["primitiveId"])
    island=Polygon(cleanup["exactCleanupMaskXYmm"])
    assert abs(island.area-cleanup["areaMm2"])<1e-9
    rows=PARSE(SOURCE)
    contacts=[];invalid=[]
    before_fills=[];after_fills=[]
    replacement={o["primitiveId"]:o for o in data["fillModifyOperations"]}
    for (kind,rid),b in rows.items():
        if b.get("layerId")!=17 or b.get("netName")!="GND" or rid==target["primitiveId"]:
            continue
        shape=None
        if kind=="FILL":
            shape=Polygon(V["ring"](b["path"][0]),[V["ring"](p) for p in b["path"][1:]])
            if not shape.is_valid:
                if shape.envelope.intersects(island.envelope):invalid.append(rid)
                continue
            shape=shape.buffer(b["width"]*.0254/2)
        elif kind in ("LINE","ARC"):
            a=(b["startX"]*.0254,b["startY"]*.0254)
            z=(b["endX"]*.0254,b["endY"]*.0254)
            pts=V["OLD"]["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            shape=LineString(pts).buffer(b["width"]*.0254/2)
        if shape is not None and shape.intersects(island):
            contacts.append({"type":kind,"id":rid,"intersectionAreaMm2":shape.intersection(island).area})
    # The overlapping neighbor may already be connected to the remote main
    # plane. Test its real post-cut same-layer copper component, not labels.
    for (kind,rid),b in rows.items():
        if kind!="FILL" or b.get("layerId")!=17 or b.get("netName")!="GND":continue
        p=Polygon(V["ring"](b["path"][0]),[V["ring"](p) for p in b["path"][1:]])
        if not p.is_valid:invalid.append(rid);continue
        before_fills.append(p.buffer(b["width"]*.0254/2))
        paths=replacement[rid]["afterPathsExplicitlyClosedForApi"] if rid in replacement else b["path"]
        p=Polygon(V["ring"](paths[0]),[V["ring"](p) for p in paths[1:]])
        assert p.is_valid
        after_fills.append(p.buffer(b["width"]*.0254/2))
    before_union=unary_union(before_fills);after_union=unary_union(after_fills)
    neighbor_rows=[]
    via_shapes=[]
    for (kind,rid),b in rows.items():
        if kind=="VIA" and b.get("netName")=="GND":
            shape=Point(b["centerX"]*.0254,b["centerY"]*.0254).buffer(b["viaDiameter"]*.0254/2)
            via_shapes.append((rid,shape))
            if shape.intersects(island):contacts.append({"type":kind,"id":rid,"intersectionAreaMm2":shape.intersection(island).area})
    def pieces(shape):return [shape] if shape.geom_type=="Polygon" else list(shape.geoms)
    for c in contacts:
        if c["type"]!="FILL":continue
        b=rows["FILL",c["id"]]
        raw=Polygon(V["ring"](b["path"][0]),[V["ring"](p) for p in b["path"][1:]]).buffer(b["width"]*.0254/2)
        anchors={}
        for label,shape in [("before",before_union),("after",after_union)]:
            joined=[p for p in pieces(shape) if p.intersection(raw).area>1e-10]
            anchors[label]=sorted({rid for rid,v in via_shapes if any(p.intersection(v).area>1e-10 for p in joined)})
        neighbor_rows.append({"fillId":c["id"],"unchangedOriginalBody":c["id"] not in replacement,"sameLayerBeforeExistingGroundViaIds":anchors["before"],"sameLayerAfterExistingGroundViaIds":anchors["after"],"noViaAnchorLost":set(anchors["before"])<=set(anchors["after"]),"stillViaAnchored":bool(anchors["after"])})
    safe=all(r["unchangedOriginalBody"] and r["noViaAnchorLost"] and r["stillViaAnchored"] for r in neighbor_rows)
    report={"schema":"adc10-inner17-shard-literal-neighbor-anchor-screen-20261018-v3","status":"PASS_UNCHANGED_NEIGHBOR_ALL_PRIOR_VIA_ANCHORS_PRESERVED" if safe else "NEEDS_REVIEW","sourcePath":str(SOURCE),"sourceSha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"candidatePath":str(after_plan),"candidateSha256":hashlib.sha256(after_plan.read_bytes()).hexdigest(),"targetFillId":target["primitiveId"],"islandAreaMm2":island.area,"islandBoundsMm":list(island.bounds),"otherSameLayerGroundFillLineArcContacts":contacts,"excludedUnrelatedInvalidOriginalGroundFills":invalid,"neighborBeforeAfterViaAnchorProof":neighbor_rows,"geometryRepaired":False,"nativeCalls":0,"scope":"Every other original valid layer17 GND FILL including its pen width, original GND LINE/ARC and all original plated GND VIA copper. Invalid original FILLs are excluded as conservative anchors, never repaired. No inner-layer SMD or free mounting PAD exists in this locality."}
    tag="-c95-farvia" if "farvia" in after_plan.name else ("-c95-neck" if after_plan!=PLAN else "")
    out=HERE/("strip/adc10-inner17-local-shard-independent-anchor-audit"+tag+"-20261018.json")
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"status":report["status"],"contacts":contacts,"invalid":invalid}))


if __name__=="__main__":main()
