"""Offline bounded TOPground-hole unions and literal proposedpad return audit."""
import argparse
import copy
import hashlib
import json
import runpy
from pathlib import Path
from shapely.geometry import Point, Polygon, box
from shapely.validation import explain_validity

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018/routing"
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
# Ten-nanometre integer clipping grid avoids a measurable sliver of apparent
# copperaddition when converted affectedhole coordinates are re-quantized.
M["ip"].__globals__["SCALE"]=100000000
G=M["G"];MM=.0254
SOURCE=ROOT/"output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru"


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--placement",type=Path,required=True)
    parser.add_argument("--routes",type=Path,required=True)
    parser.add_argument("--tag",required=True)
    args=parser.parse_args()
    rows=G["PARSE"](SOURCE)
    placement=json.loads(args.placement.read_text(encoding="utf8"))
    routes=json.loads(args.routes.read_text(encoding="utf8"))
    voids=[]
    for p in placement["edits"]:
        for pad in p["pads"]:
            if pad["net"]=="GND":continue
            x0,y0,x1,y1=pad["boundsMm"]
            voids.extend(M["expanded"](M["ip"]([(x0,y0),(x1,y0),(x1,y1),(x0,y1)]),.17))
    for line in routes["newLineCreates"]:
        if line["net"]!="GND" and line["layerId"]==1:voids.extend(M["capsule"](line["startXYmm"],line["endXYmm"],line["widthMm"]/2+.17))
    updates=M["cut_ground"](rows,voids)
    # The reused historical helper flips all result rings to native hole
    # orientation. A newly unioned ring-shaped void can therefore carry a
    # redundant nested ring. Never send such an invalid polygon to EasyEDA.
    # Remove only a fullycontained redundant hole, preserving every retained
    # native coordinate/arc. Union-of-holes geometry must stay exactly equal.
    for update in updates:
        path=update["afterPath"]
        hp=[Polygon(G["ring_path"](p)) for p in path[1:]]
        drop={i for i,p in enumerate(hp) if any(i!=j and q.covers(p) and (q.area>p.area+1e-12 or j<i) for j,q in enumerate(hp))}
        if drop:
            oldunion=M["union"]([M["positive"](M["ip"](G["ring_path"](p))) for p in path[1:]])
            after=[path[0]]+[p for i,p in enumerate(path[1:]) if i not in drop]
            newunion=M["union"]([M["positive"](M["ip"](G["ring_path"](p))) for p in after[1:]])
            assert M["area"](M["intersection"](oldunion,newunion))>=M["area"](oldunion)-1e-7
            assert abs(M["area"](oldunion)-M["area"](newunion))<1e-7
            update["redundantContainedHoleRingsRemoved"]=[{"afterPathIndex":i+1,"boundsMm":list(hp[i].bounds),"areaMm2":hp[i].area} for i in sorted(drop)]
            update["nestedHoleRemovalUnionAreaChangeMm2"]=abs(M["area"](oldunion)-M["area"](newunion))
            update["afterPath"]=after;update["afterPathSha256"]=M["digest"](after)
    byid={u["id"]:u for u in updates}
    fills=[];invalid=[]
    gndvias=[(rid,(b["centerX"]*MM,b["centerY"]*MM)) for (k,rid),b in rows.items() if k=="VIA" and b.get("netName")=="GND"]
    for (k,rid),b in rows.items():
        if k!="FILL" or b.get("layerId")!=1 or b.get("netName")!="GND":continue
        path=byid[rid]["afterPath"] if rid in byid else b["path"]
        rings=[G["ring_path"](p) for p in path]
        s=Polygon(rings[0],rings[1:])
        if not s.is_valid:invalid.append({"id":rid,"reason":explain_validity(s)});continue
        anchors=[vid for vid,p in gndvias if s.contains(Point(p))]
        fills.append((rid,s,anchors))
    ground=[]
    for p in placement["edits"]:
        for pad in p["pads"]:
            if pad["net"]!="GND":continue
            s=box(*pad["boundsMm"])
            matches=[]
            for fid,fs,anchors in fills:
                if not fs.intersects(s):continue
                overlap=fs.intersection(s).area
                if overlap>1e-6 and anchors:matches.append({"fillId":fid,"padCopperOverlapMm2":overlap,"overlapFraction":overlap/s.area,"oldGndViaAnchorIds":anchors})
            ground.append({"ref":p["ref"],"pin":pad["number"],"centerMm":pad["centerMm"],"returnProvenBySameValidSolidFill":bool(matches),"matches":matches})
    report={"schema":"adc10-labtool-bounded-top-ground-voids-20261018-v1","readOnly":True,"nativeCalls":0,"sourcePath":str(SOURCE),"sourceSha256":sha(SOURCE),"placementPath":str(args.placement),"placementSha256":sha(args.placement),"routesPath":str(args.routes),"routesSha256":sha(args.routes),"fillPathUpdates":updates,"allGroundOutersExact":all(u["outerPathExact"] for u in updates),"noTessellatedCopperAddition":all(u["copperAdditionAreaAgainstTessellatedInputMm2"]<1e-7 for u in updates),"voidClearanceMm":.17,"groundPadReturnAudit":ground,"unprovenGroundPads":[p for p in ground if not p["returnProvenBySameValidSolidFill"]],"invalidGroundPolygonsNotSilentlyRepaired":invalid,"existingViaChanges":0,"existingDrillChanges":0,"requiresNativeDRC":True,"manufacturingReady":False,"limitations":["TOPonly;newVIAsrequireseparateall6layerantipadvoids.","GroundreachusesliteraloverlapwithasinglevalidupdatednativeFILLhavingexistingGNDviaanchors;invalidpolygonsdonotproveconnectivity.","Overlappingpads/thermal/assemblyandfullnativeunroutedDRCremainrequired.","Thesevoidpathsarebasedontheexactcitedplacement/routes,notanylaterchangedvariant."]}
    target=HERE/f"top-ground-voids-{args.tag}.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(target),"fillUpdates":len(updates),"groundPads":len(ground),"unproven":len(report["unprovenGroundPads"]),"invalid":invalid,"outerExact":report["allGroundOutersExact"]}),flush=True)


if __name__=="__main__":main()
