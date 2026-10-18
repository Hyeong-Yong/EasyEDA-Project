"""Offline local FILL-hole union and public-API data operations for solved caps.

Preserves original outer command arrays and every untouched hole command array.
New/merged hole rings are explicitly closed, including API representations of
preserved rings. No EasyEDA source candidate is emitted or applied.
"""
import copy
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/"plan-bottom-buckets.py"))
globals().update({k:M[k] for k in ["ROOT","MM","CLR","WIDTH","SCALE","pc","fp","ip","capsule","circle","rectangle","filled_rings","paths_bbox","offset","union","inter","diff","positive","overlap"]})


def area(paths):return sum(pc.Area(p) for p in paths)/(SCALE*SCALE)
def sha(body):return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def native_ring(poly,hole=True,original_xy_map=None):
    # EasyEDA expects outer CW / hole CCW in Y-up. This function writes holes
    # CCW (positive) and explicitly closes them for the public API parser.
    p=poly[:]
    if pc.Orientation(p)!=hole:p.reverse()
    def xy(q):return original_xy_map[tuple(q)] if original_xy_map and tuple(q) in original_xy_map else [round(q[0]/SCALE/MM,8),round(q[1]/SCALE/MM,8)]
    out=[*xy(p[0]),"L"]
    for q in p[1:]+p[:1]:out.extend(xy(q))
    return out
def closed_native(p):
    if isinstance(p[0],str):return copy.deepcopy(p)
    q=copy.deepcopy(p)
    # Source-native rings may close implicitly. Append explicit final point
    # in the current mode; an ARC current mode requires switching back to L.
    if not(isinstance(q[-1],(int,float)) and isinstance(q[-2],(int,float)) and abs(q[-2]-q[0])<1e-9 and abs(q[-1]-q[1])<1e-9):q.extend(["L",q[0],q[1]])
    return q
def node_solid(p,node):
    ipt=(round(p[0]*SCALE),round(p[1]*SCALE))
    return pc.PointInPolygon(ipt,node.Contour)!=0 and not any(pc.PointInPolygon(ipt,c.Contour)!=0 for c in node.Childs if c.IsHole)
def solid_nodes(tree):
    result=[]
    def visit(node):
        for child in node.Childs:
            if not child.IsHole:result.append(child)
            visit(child)
    visit(tree)
    return result

def clipping_residue_proof(paths,reference_paths,max_error_mm=.000002):
    """Bound an entire residual polygon against one existing/cut edge.

    At a clipped intersection an integer vertex is rounded to the 1 nm grid.
    A very thin triangle can therefore remain along the original edge, even
    beyond the nominal cut bbox. For a fixed segment the distance is convex:
    bounding every polygon vertex bounds its entire convex hull, not just a
    few sampled points. This reports the actual nonzero residue explicitly.
    """
    def ds(p,a,b):
        dx=b[0]-a[0];dy=b[1]-a[1]
        t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)/SCALE
    edges=[(a,b) for q in reference_paths for a,b in zip(q,q[1:]+q[:1])]
    proof=[]
    for p in paths:
        bound=min(max(ds(q,a,b) for q in p) for a,b in edges)
        proof.append({"bboxMm":paths_bbox([p]),"areaMm2":abs(pc.Area(p))/SCALE**2,"wholePolygonDistanceBoundMm":bound,"permittedIntegerIntersectionEnvelopeMm":max_error_mm,"passed":bound<=max_error_mm})
    return proof


def main():
    source=HERE/(sys.argv[1] if len(sys.argv)>1 else "bottom-bucket-routing-manifest.json")
    data=json.loads(source.read_text());results=[r for r in data["channels"] if "signalRoute" in r]
    current=ROOT/"output/validation"/(sys.argv[2] if len(sys.argv)>2 else "native-adc10-pcb-ref_courtyard-20261018.epru")
    M["Board"].__init__.__globals__["SOURCE"]=current
    b=M["Board"]();bylayer={}
    # Collect each added signal pad/route and GND pad individually. GND lands
    # must not cut GND, while all new signal copper requires GND clearance.
    additions=[]
    for r in results:
        cap_layer=r["signalRoute"]["layerId"]
        for pn,pad in r["requiredWorldPads"].items():additions.append({"id":r["ref"]+":"+pn,"net":pad["net"],"layer":cap_layer,"paths":[rectangle(pad["xyMm"],r["axisOfPositiveLocalX"])]})
        additions.append({"id":r["ref"]+":ROUTE","net":r["net"],"layer":cap_layer,"paths":capsule(r["signalRoute"]["pointsMm"],r["signalRoute"]["widthMm"]/2)})
        if "groundRoute" in r:additions.append({"id":r["ref"]+":GND_ROUTE","net":"GND","layer":r["groundRoute"]["layerId"],"paths":capsule(r["groundRoute"]["pointsMm"],r["groundRoute"]["widthMm"]/2)})
        s=r.get("selectedRoutingSource",{})
        if s.get("kind")=="NEW_ADC_TAP_VIA":
            for layer in [1,2,15,16,17,18]:additions.append({"id":r["ref"]+":NEWVIA","net":r["net"],"layer":layer,"paths":[circle(s["xyMm"],s["diameterMm"]/2)]})
        for branch in r.get("additionalSignalRoutes",[]):additions.append({"id":r["ref"]+":BRANCH","net":r["net"],"layer":branch["layerId"],"paths":capsule(branch["pointsMm"],branch["widthMm"]/2)})
    fills=[]
    for (k,i),body in b.rows.items():
        if k!="FILL" or body["layerId"] not in [1,2,15,16,17,18]:continue
        if body["netName"] not in ["GND","+3V3","NET-(U1D-VDDA)","NET-(U1D-VREF+)"]:continue
        raw=filled_rings(body["path"]);bb=paths_bbox(raw)
        cuts=[];owners=[]
        for a in additions:
            if a["layer"]!=body["layerId"] or a["net"]==body["netName"] or not overlap(paths_bbox(a["paths"]),bb,CLR+.02):continue
            # Additional .008 mm polygon cut reserve includes old fill's pen
            # half-width, so its boundary stroke cannot intrude into clearance.
            c=offset(a["paths"],CLR+.008+body["width"]*MM/2)
            if inter(c,raw):cuts.extend(c);owners.append(a["id"])
        if cuts:fills.append((i,body,raw,union(cuts),sorted(set(owners))))
    ops=[];creates=[];errors=[];after_ground=[];fill_audits=[];orphan_cleanup=[]
    modified_ids={x[0] for x in fills}
    for fill in b.fills:
        if fill["id"] not in modified_ids:after_ground.extend(fill["paths"])
    after_ground.extend(p for a in additions if a["layer"]==2 and a["net"]=="GND" for p in a["paths"])
    for fid,body,raw,cuts,owners in fills:
        outer=positive(raw[0]);holes=[positive(h) for h in raw[1:]]
        original_map={}
        for path in body["path"]:
            if isinstance(path[0],str) or any(isinstance(x,str) and x!="L" for x in path):continue
            coords=[x for x in path if not isinstance(x,str)]
            original_map.update({(round(coords[j]*MM*SCALE),round(coords[j+1]*MM*SCALE)):[coords[j],coords[j+1]] for j in range(0,len(coords),2)})
        # Modifying an outer boundary requires a separately reviewed local
        # surgery. Do not silently flatten or rebuild this static FILL.
        beyond=diff(cuts,[outer])
        crosses_outer=abs(area(beyond))>1e-9
        oldholes=[];keep=[];merge_indices=[]
        for hi,h in enumerate(holes,1):
            if inter(offset([h],.000003),cuts):oldholes.append(h);merge_indices.append(hi)
            else:keep.append(hi)
        merged=union(oldholes+cuts)
        # A hole-mask union can enclose a new copper island. Serializing its
        # negative contour as one more native hole is invalid nested-hole
        # topology and incorrectly discards the island by accident. Only the
        # explicitly approved tiny, newly detached, local unanchored GND case
        # may be removed, and it becomes a named additional cut below.
        negative_mask_rings=[p for p in merged if not pc.Orientation(p)]
        for island in negative_mask_rings:
            island_positive=positive(island)
            aa=abs(pc.Area(island))/SCALE**2;nb=paths_bbox([island])
            anchors=[i for i,n,p,r in b.vias if n==body["netName"] and inter([circle(p,r)],[island_positive])]
            cap_ground=[a["id"] for a in additions if a["net"]==body["netName"] and a["layer"]==body["layerId"] and inter(a["paths"],[island_positive])]
            if body["netName"]!="GND" or anchors or cap_ground or aa>.60 or not overlap(nb,paths_bbox(cuts),.01):
                errors.append({"fillId":fid,"error":"ENCLOSED_COPPER_ISLAND_REQUIRES_SEPARATE_ANCHORED_FILL","areaMm2":aa,"bboxMm":nb,"viaAnchors":anchors,"newGroundAnchors":cap_ground})
                continue
            orphan_cleanup.append({"sourceFillId":fid,"layerId":body["layerId"],"net":body["netName"],"areaMm2":aa,"bboxMm":nb,"existingViaAnchors":[],"newCapGroundAnchors":[],"detachedOnlyByListedCuts":True,"reason":"newly enclosed negative hole-mask ring, no original via-annulus or new GND-copper contact","exactCleanupMaskXYmm":fp(island_positive)})
            cuts=union(cuts+[island_positive])
        if negative_mask_rings:merged=union(oldholes+cuts)
        outer_exact=True
        if crosses_outer:
            # Local boundary cut: this baseline outer consists solely of exact
            # LINE commands. Clipper may replace only edges intersected by the
            # listed cut. Reuse native floats for every unchanged old vertex;
            # all remote source geometry is proven identical below.
            if any(isinstance(x,str) and x!="L" for x in body["path"][0]):
                errors.append({"fillId":fid,"error":"OUTER_ARC_LOCAL_SURGERY_NOT_IMPLEMENTED"});continue
            coords=[x for x in body["path"][0] if not isinstance(x,str)]
            clipped_tree=diff(raw,cuts,True)
            nodes=sorted(clipped_tree.Childs,key=lambda n:abs(pc.Area(n.Contour)),reverse=True)
            retained=[]
            for ni,nd in enumerate(nodes):
                anchors=[i for i,n,p,r in b.vias if n==body["netName"] and node_solid(p,nd)]
                cap_ground=[a["id"] for a in additions if body["netName"]=="GND" and a["net"]=="GND" and a["layer"]==body["layerId"] and inter(a["paths"],[positive(nd.Contour)]+[list(reversed(positive(h.Contour))) for h in nd.Childs if h.IsHole])]
                aa=abs(pc.Area(nd.Contour))/(SCALE*SCALE);nb=paths_bbox([nd.Contour])
                if ni>0 and not anchors and not cap_ground:
                    # Explicit root approval: discard only newly detached local
                    # unanchored shards. This cannot remove old/remote islands.
                    local_bb=paths_bbox(cuts)
                    if aa>.60 or not overlap(nb,local_bb,.01):errors.append({"fillId":fid,"error":"UNANCHORED_FRAGMENT_NOT_LOCAL_TINY","areaMm2":aa,"bboxMm":nb});continue
                    cuts=union(cuts+[positive(nd.Contour)])
                    orphan_cleanup.append({"sourceFillId":fid,"layerId":body["layerId"],"net":body["netName"],"areaMm2":aa,"bboxMm":nb,"existingViaAnchors":[],"newCapGroundAnchors":[],"detachedOnlyByListedCuts":True,"exactCleanupMaskXYmm":fp(nd.Contour)})
                    continue
                retained.append((nd,anchors,cap_ground))
            if not retained:errors.append({"fillId":fid,"error":"NO_RETAINED_SOLID"});continue
            outer_node=retained[0][0]
            for li,(nd,anchors,cap_ground) in enumerate(retained[1:],1):
                paths=[native_ring(nd.Contour,False,original_map)]+[native_ring(h.Contour,True,original_map) for h in nd.Childs if h.IsHole]
                closed_lobe=[closed_native(p) for p in paths]
                creates.append({"operation":"pcb_PrimitiveFill.create","semanticId":fid+":retained-lobe:"+str(li),"sourceFillId":fid,"layerId":body["layerId"],"net":body["netName"],"fillMode":"SOLID","lineWidthMil":body["width"],"primitiveLock":body.get("locked",False),"afterPathsExplicitlyClosedForApi":closed_lobe,"afterNativePaths":paths,"existingSameNetViaIds":anchors,"capGroundRefs":cap_ground,"areaMm2":abs(pc.Area(nd.Contour))/(SCALE*SCALE)})
                if body["netName"]=="GND" and body["layerId"]==2:after_ground.extend(offset(filled_rings(paths),body["width"]*MM/2))
            newpaths=[native_ring(outer_node.Contour,False,original_map)]
            remaining_holes=[n.Contour for n in outer_node.Childs if n.IsHole]
            for h in remaining_holes:
                old_match=None
                for hi in keep:
                    if paths_bbox([h])!=paths_bbox([holes[hi-1]]):continue
                    if not diff([positive(h)],[holes[hi-1]]) and not diff([holes[hi-1]],[positive(h)]):old_match=hi;break
                newpaths.append(copy.deepcopy(body["path"][old_match]) if old_match is not None else native_ring(h,True,original_map))
            outer_exact=False
        else:newpaths=[copy.deepcopy(body["path"][0])]+[copy.deepcopy(body["path"][i]) for i in keep]+[native_ring(h,True,original_map) for h in merged]
        # Existing raw command arrays untouched except the affected hole set.
        newraw=filled_rings(newpaths)
        allnewraw=newraw+[p for cr in creates if cr["sourceFillId"]==fid for p in filled_rings(cr["afterNativePaths"])]
        addcopper=diff(allnewraw,raw)
        removecopper=diff(raw,allnewraw)
        outside=diff(removecopper,cuts)
        outside_clip_guard=diff(removecopper,offset(cuts,.000002))
        residue_proof=clipping_residue_proof(outside_clip_guard,raw+cuts)
        before_tree=diff(raw,[],True);after_tree=diff(allnewraw,[],True)
        connected_before=len(before_tree.Childs);connected_after=len(after_tree.Childs)
        if area(addcopper)>1e-8 or not all(p["passed"] for p in residue_proof):errors.append({"fillId":fid,"error":"GEOMETRY_OUTSIDE_AUTHORIZED_CUT_OR_ADDED_COPPER","addedMm2":area(addcopper),"outsideCutMm2":area(outside),"outside2nmCutOnlyEnvelopeMm2":area(outside_clip_guard),"integerIntersectionResidueProof":residue_proof})
        if connected_after>connected_before and body["netName"]!="GND":errors.append({"fillId":fid,"error":"POWER_PLANE_DISCONNECTED","connectedBefore":connected_before,"connectedAfter":connected_after})
        closed=[closed_native(p) for p in newpaths]
        afterbody=copy.deepcopy(body);afterbody["path"]=newpaths
        api_body=copy.deepcopy(body);api_body["path"]=closed
        op={"operation":"pcb_PrimitiveFill.modify","primitiveId":fid,"net":body["netName"],"layerId":body["layerId"],"beforeBodySha256":sha(body),"beforePathSha256":sha(body["path"]),"beforeBody":body,"afterNativeBody":afterbody,"afterPathsExplicitlyClosedForApi":closed,"afterBodyClosedSha256":sha(api_body),"cutOwners":owners,"cutBoundingBoxMm":paths_bbox(cuts),"newCutRingsXYmm":[fp(q) for q in cuts],"preservedOriginalOuterCommandArray":outer_exact,"preservedNonlocalOuterVertexCoordinates":True,"preservedOriginalHoleIndices":keep,"mergedOriginalHoleIndices":merge_indices}
        ops.append(op)
        fill_audits.append({"fillId":fid,"net":body["netName"],"layerId":body["layerId"],"originalHoles":len(holes),"preservedHoles":len(keep),"mergedOriginalHoles":len(merge_indices),"newUnionHoles":len(merged),"removedCopperMm2":area(removecopper),"addedCopperMm2":area(addcopper),"removedOutsideAuthorizedCutMm2":area(outside),"removedOutside2nmCutOnlyEnvelopeMm2":area(outside_clip_guard),"integerIntersectionResidueProof":residue_proof,"integerClippingEnvelopeMm":.000002,"connectedBefore":connected_before,"connectedAfter":connected_after,"outerCommandArrayExact":outer_exact,"nonlocalOuterVertexCoordinatesExact":True})
        if body["netName"]=="GND" and body["layerId"]==2:after_ground.extend(offset(newraw,body["width"]*MM/2))
    # Each GND land must have a continuous, literal final solid GND path to an
    # original existing GND via, not only overlap a visually green fragment.
    tree=diff(union(after_ground),[],True);ground_nodes=solid_nodes(tree)
    gnds=[(i,p) for i,n,p,r in b.vias if n=="GND"]
    ground_audit=[]
    for r in results:
        if r["signalRoute"]["layerId"]!=2:continue
        gp=r["requiredWorldPads"]["2"]["xyMm"]
        islands=[n for n in ground_nodes if node_solid(gp,n)]
        ties=[]
        for n in islands:ties.extend(i for i,p in gnds if node_solid(p,n))
        corners=fp(rectangle(gp,r["axisOfPositiveLocalX"]))
        corners_ok=any(all(node_solid(p,n) for p in corners) for n in islands)
        row={"ref":r["ref"],"groundPadCenterXYmm":gp,"allFourCornersInSameFinalGndIsland":corners_ok,"sameIslandExistingGroundViaIds":sorted(set(ties)),"passed":corners_ok and bool(ties)}
        ground_audit.append(row)
        if not row["passed"]:errors.append({"ref":r["ref"],"error":"FINAL_GROUND_ISLAND_TIE_NOT_PROVEN"})
    out={"schema":"adc-bottom-bucket-local-api-operations-20261018-v1","readOnly":True,"nativeCallsPerformed":False,"sourcePath":str(current),"sourceSha256":hashlib.sha256(current.read_bytes()).hexdigest(),"layoutAnalysisOriginalSourceSha256":data["sourceSha256"],"inputManifest":str(source),"solvedCapCount":len(results),"channels":results,"fillModifyOperations":ops,"fillCreateOperations":creates,"localNewOrphanFragmentCleanup":orphan_cleanup,"fillGeometryAudit":fill_audits,"finalGroundContinuityAudit":ground_audit,"additionalDrills":sum(r.get("selectedRoutingSource",{}).get("kind")=="NEW_ADC_TAP_VIA" for r in results),"passedOfflineFillAndGroundAudit":not errors,"errors":errors,"applicationApproved":False,"manufacturingReady":False,"applicationGates":["Validate exact original FILL path/body hashes against fresh live source; merge other authorized TOP edits rather than overwrite them.","Calibrate BOTTOM placement/angle via native pads; verify requiredWorldPads before traces.","Create every proposed polygon with explicitly closed rings before modify: a validation failure in the beta API can delete the previous fill.","Perform native strict DRC and netlist, saved/reopened source preservation and all-six-layer CAM audit. No manufacturer-ready claim from this offline geometry analysis."]}
    name=source.stem+"-local-api-operations.json"
    (HERE/name).write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(HERE/name),"caps":len(results),"fillOps":len(ops),"passed":not errors,"errors":errors}),flush=True)


if __name__=="__main__":main()
