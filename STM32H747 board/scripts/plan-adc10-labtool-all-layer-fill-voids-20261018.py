"""SUPERSEDED: historical mask-diagnostic only, never apply its FILL paths.

The preserving-split library helper is authoritative. Contained-ring removal
below does not prove island preservation; this script must not be re-executed.
"""
import argparse
import copy
import hashlib
import json
import runpy
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString, box
from shapely.validation import explain_validity

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018/routing"
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
M["ip"].__globals__["SCALE"]=100000000
G=M["G"];MM=.0254
LAYERS=(1,2,15,16,17,18)
SOURCE=ROOT/"output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru"


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def normalized_holes(update):
    path=update["afterPath"];hp=[Polygon(G["ring_path"](p)) for p in path[1:]]
    drop={i for i,p in enumerate(hp) if any(i!=j and q.covers(p) and (q.area>p.area+1e-12 or j<i) for j,q in enumerate(hp))}
    if not drop:return
    oldunion=M["union"]([M["positive"](M["ip"](G["ring_path"](p))) for p in path[1:]])
    after=[path[0]]+[p for i,p in enumerate(path[1:]) if i not in drop]
    newunion=M["union"]([M["positive"](M["ip"](G["ring_path"](p))) for p in after[1:]])
    assert M["area"](M["intersection"](oldunion,newunion))>=M["area"](oldunion)-1e-7
    assert abs(M["area"](oldunion)-M["area"](newunion))<1e-7
    update["redundantContainedHoleRingsRemoved"]=[{"afterPathIndex":i+1,"boundsMm":list(hp[i].bounds),"areaMm2":hp[i].area} for i in sorted(drop)]
    update["nestedHoleRemovalUnionAreaChangeMm2"]=abs(M["area"](oldunion)-M["area"](newunion))
    update["afterPath"]=after;update["afterPathSha256"]=M["digest"](after)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--placement",type=Path,required=True)
    parser.add_argument("--routes",type=Path,required=True)
    parser.add_argument("--tag",required=True)
    parser.add_argument("--channels-only-pads",action="store_true")
    args=parser.parse_args()
    rows=G["PARSE"](SOURCE)
    placement=json.loads(args.placement.read_text(encoding="utf8"))
    routes=json.loads(args.routes.read_text(encoding="utf8"))
    elements=[]
    for p in placement["edits"]:
        if args.channels_only_pads and p["ref"] in {"U9","U30","U31","U32","D20"}|{f"R{i}" for i in range(197,205)}|{f"C{i}" for i in range(150,161)}|{"C103","C104","C105"}:continue
        for pad in p["pads"]:
            x0,y0,x1,y1=pad["boundsMm"]
            poly=M["ip"]([(x0,y0),(x1,y0),(x1,y1),(x0,y1)])
            elements.append({"key":"PAD:"+p["ref"]+":"+pad["number"],"net":pad["net"],"layers":(1,),"paths":M["expanded"](poly,.17)})
    for p in routes["newLineCreates"]:
        elements.append({"key":p["key"],"net":p["net"],"layers":(p["layerId"],),"paths":M["capsule"](p["startXYmm"],p["endXYmm"],p["widthMm"]/2+.17)})
    for p in routes.get("newViaCreates",[]):
        elements.append({"key":"VIA:"+p["key"],"net":p["net"],"layers":LAYERS,"paths":M["capsule"](p["xyMm"],p["xyMm"],p["viaDiameterMm"]/2+.17)})
    for e in elements:e["bounds"]=M["bounds"](e["paths"])
    updates=[];errors=[]
    for (k,rid),body in rows.items():
        if k!="FILL" or body.get("layerId") not in LAYERS:continue
        layer=body["layerId"];net=body.get("netName","")
        possible=[e for e in elements if layer in e["layers"] and (e["net"] or "").casefold()!=net.casefold()]
        if not possible:continue
        path=body["path"]
        if path[0][0]=="CIRCLE":
            cp=path[0];fs=Point(cp[1]*MM,cp[2]*MM).buffer(cp[3]*MM,resolution=64)
            affected=[e for e in possible if G["bb_overlap"](e["bounds"],fs.bounds)]
            if affected:errors.append({"id":rid,"layerId":layer,"reason":"CIRCLE_FILL_REQUIRES_SEPARATE_EXPLICIT_REVIEW","possibleElements":[e["key"] for e in affected]})
            continue
        ring=G["ring_path"](path[0]);fb=G["bbox"](ring)
        relevant=[e for e in possible if G["bb_overlap"](e["bounds"],fb)]
        if not relevant:continue
        voids=[p for e in relevant for p in e["paths"]]
        fake=copy.deepcopy(body);fake.update({"netName":"GND","layerId":1})
        try:
            found=M["cut_ground"]({("FILL",rid):fake},voids)
            if not found:continue
            assert len(found)==1
            update=found[0]
            update["sourceBodyBefore"]=body;update["beforeBodySha256"]=M["digest"](body)
            update["layerId"]=layer;update["netName"]=net
            update["reasonElementKeys"]=[e["key"] for e in relevant]
            normalized_holes(update)
            rings=[G["ring_path"](p) for p in update["afterPath"]]
            shape=Polygon(rings[0],rings[1:])
            update["afterPolygonValid"]=shape.is_valid
            if not shape.is_valid:errors.append({"id":rid,"layerId":layer,"reason":explain_validity(shape)})
            updates.append(update)
        except (AssertionError,ValueError) as ex:
            errors.append({"id":rid,"layerId":layer,"reason":str(ex)})
    report={"schema":"adc10-labtool-all6-local-fill-voids-20261018-v1","status":"GUARDED_OFFLINE_PATH_PLAN" if not errors else "ERRORS_DO_NOT_APPLY","sourcePath":str(SOURCE),"sourceSha256":sha(SOURCE),"placementPath":str(args.placement),"placementSha256":sha(args.placement),"routePath":str(args.routes),"routeSha256":sha(args.routes),"readOnly":True,"nativeCalls":0,"fillPathUpdates":updates,"errors":errors,"allModifiedOutersExact":all(u["outerPathExact"] for u in updates),"copperAddedAgainstTessellatedOldMm2":sum(u["copperAdditionAreaAgainstTessellatedInputMm2"] for u in updates),"clearanceMm":.17,"integerClippingGridMm":1e-8,"arcSagittaMm":.0001,"newViaCount":len(routes.get("newViaCreates",[])),"newViaAntipadsAll6LayersCovered":True,"existingViaChanges":0,"existingDrillChanges":0,"newDrillCount":len(routes.get("newViaCreates",[])),"channelsOnlyPadVoids":args.channels_only_pads,"requiresNativeDRC":True,"manufacturingReady":False,"limitations":["NewVIAsandtracesmustmatchthecitedsourcegeometryandlockedplacementexactly.","Allretainednativepathcoordinates/arcsarekept;onlylistedintersectingholesarelocallyunioned. Noentiregroundrefill.","UnderlyingoriginalinvalidFILLsarenotgenerallyrepaired. Anyinvalidmodifiedpolygonisanexplicitblockingerror.","GroundpadreturnstillrequiresconnectiontovalidGNDcopperoradedicatedgroundVIAtoliteralGNDplane;antipadsarenotaconnectivityclaim."]}
    target=HERE/f"all6-local-fill-voids-{args.tag}.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(target),"fillUpdates":len(updates),"errors":errors,"byLayer":{str(layer):sum(u["layerId"]==layer for u in updates) for layer in LAYERS},"newVias":len(routes.get("newViaCreates",[]))}),flush=True)


if __name__=="__main__":raise SystemExit("SUPERSEDED_DO_NOT_APPLY: negative ground islands were lost; use output/candidates/adc10-labtool-20261018/ground/plan-local-static-fill-clearance.py")
