"""Read-only logical groundreach, preserving every difference-result island.

Does NOT emit FILL paths or authorize copper deletion; independent native
preserving-split operations and strictDRC remain required.
"""
import json,hashlib,runpy
from pathlib import Path
from collections import defaultdict
from shapely.geometry import Point,Polygon,LineString,box
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018/routing"
M=runpy.run_path(str(HERE.parent/"independent-pcb-placement-proposal.py"))
G=M["G"];MM=.0254;LAYERS=(1,2,15,16,17,18)
SOURCE=ROOT/"output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru"
PLACEMENT=HERE.parent/"independent-pcb-placement-short-negative-variant-v2.json"
ROUTES=HERE/"frozen-local-ground-phase332-v2.json"


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    rows=M["parse"](SOURCE)
    placement=json.loads(PLACEMENT.read_text(encoding="utf8"))
    route=json.loads(ROUTES.read_text(encoding="utf8"))
    masks=defaultdict(list)
    common={"U9","U30","U31","U32","D20"}|{f"R{i}" for i in range(197,205)}|{f"C{i}" for i in range(150,161)}|{"C103","C104","C105"}
    for p in placement["edits"]:
        if p["ref"] in common:continue
        for pad in p["pads"]:
            if pad["net"]!="GND":masks[1].append(box(*pad["boundsMm"]).buffer(.17,resolution=24))
    for p in route["newLineCreates"]:
        if p["net"]!="GND":masks[p["layerId"]].append(LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2+.17,resolution=24))
    for p in route["newViaCreates"]:
        if p["net"]!="GND":
            for layer in LAYERS:masks[layer].append(Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2+.17,resolution=48))
    masks={layer:unary_union(mask) for layer,mask in masks.items()}
    oldgnd=[(rid,(b["centerX"]*MM,b["centerY"]*MM)) for (k,rid),b in rows.items() if k=="VIA" and b.get("netName")=="GND"]
    pieces=[];invalid=[]
    for (k,rid),b in rows.items():
        if k!="FILL" or b.get("layerId") not in LAYERS or b.get("netName")!="GND":continue
        if b["path"][0][0]=="CIRCLE":continue
        rings=[G["ring_path"](p) for p in b["path"]];before=Polygon(rings[0],rings[1:])
        if not before.is_valid:invalid.append(rid);continue
        after=before.difference(masks.get(b["layerId"],Polygon()))
        assert after.is_valid
        sub=list(after.geoms) if hasattr(after,"geoms") else [after]
        for n,s in enumerate(sub):
            if s.is_empty or s.geom_type!="Polygon":continue
            anchors=[vid for vid,p in oldgnd if s.covers(Point(p))]
            pieces.append({"key":f"{rid}:{n}","fillId":rid,"layerId":b["layerId"],"shape":s,"oldGroundViaAnchors":anchors})
    newgnd=[]
    for p in route["newViaCreates"]:
        if p["net"]!="GND":continue
        s=Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=48)
        contacts=[{"fillPiece":f["key"],"layerId":f["layerId"],"oldGroundViaAnchors":f["oldGroundViaAnchors"][:16],"overlapMm2":s.intersection(f["shape"]).area} for f in pieces if f["oldGroundViaAnchors"] and s.intersection(f["shape"]).area>1e-8]
        newgnd.append({"key":p["key"],"xyMm":p["xyMm"],"shape":s,"literalExistingGroundPlaneContacts":contacts,"anchored":bool(contacts)})
    # Top-connected graph includes all split fragments, even fragments without
    # an oldvia. A newGroundVIA can anchor such a fragment to an inner/bottom
    # connected groundplane. No island is dropped or merged across an airgap.
    nodes=[]
    for f in pieces:
        if f["layerId"]==1:nodes.append({"key":"FILL:"+f["key"],"shape":f["shape"],"anchored":bool(f["oldGroundViaAnchors"])})
    for p in newgnd:nodes.append({"key":"VIA:"+p["key"],"shape":p["shape"],"anchored":p["anchored"]})
    for p in route["newLineCreates"]:
        if p["net"]=="GND" and p["layerId"]==1:nodes.append({"key":p["key"],"shape":LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2,resolution=32),"anchored":False})
    # A simple union of actual contacting ground shapes is not an EDA rewrite.
    # Each target is traced through individual nodes to a physical oldanchor.
    links=defaultdict(list)
    for i,a in enumerate(nodes):
        for j in range(i):
            if a["shape"].distance(nodes[j]["shape"])<1e-7:links[i].append(j);links[j].append(i)
    targets=[]
    for p in placement["edits"]:
        if p["ref"] in common and p["ref"]!="R203":continue
        for pad in p["pads"]:
            if pad["net"]!="GND":continue
            s=box(*pad["boundsMm"]);starts=[i for i,n in enumerate(nodes) if s.distance(n["shape"])<1e-7]
            queue=list(starts);seen=set(starts);parent={i:None for i in starts};hit=None
            while queue:
                i=queue.pop(0)
                if nodes[i]["anchored"]:hit=i;break
                for j in links[i]:
                    if j not in seen:seen.add(j);queue.append(j);parent[j]=i
            path=[]
            while hit is not None:path.append(nodes[hit]["key"]);hit=parent[hit]
            targets.append({"ref":p["ref"],"pin":pad["number"],"xyMm":pad["centerMm"],"groundReturnProven":bool(path),"contactPath":list(reversed(path))})
    publicvias=[{k:v for k,v in p.items() if k!="shape"} for p in newgnd]
    report={"schema":"adc10-labtool-logical-ground-anchor-20261018-v1","readOnly":True,"nativeCalls":0,"noFillPathsEmitted":True,"sourceSha256":sha(SOURCE),"placementSha256":sha(PLACEMENT),"routesSha256":sha(ROUTES),"allLogicalDifferenceIslandsPreserved":True,"originalInvalidFillsNotInterpreted":invalid,"newGroundViaPhysicalPlaneAnchors":publicvias,"targetPads":targets,"unprovenGroundVias":[p for p in publicvias if not p["anchored"]],"unprovenTargetPads":[p for p in targets if not p["groundReturnProven"]],"targetScope":"40channel-groundpadsplusR203ground;othercommon26/27partsareseparatepoweragentphase","requiresNativePreservingSplitPathProofAndDRC":True,"manufacturingReady":False}
    target=HERE/"logical-ground-anchor-phase332-v2.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(target),"groundVias":len(publicvias),"unprovenVias":len(report["unprovenGroundVias"]),"targetPads":len(targets),"unprovenPads":len(report["unprovenTargetPads"])}),flush=True)


if __name__=="__main__":main()
