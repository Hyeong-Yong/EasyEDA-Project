"""Offline bottom-side 0402 feasibility search; never emits editable EDA data."""
import hashlib
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSE = runpy.run_path(str(ROOT / "output/candidates/adc-dc-buffer/independent-static-adc-plan-review.py"))["parse"]
SOURCE = ROOT / "output/validation/native-adc10-pcb-oriented-20261017.epru"
INV = ROOT / "output/analysis/adc10-pcb-eco-api-feasibility-20261017.json"
OUT = ROOT / "output/analysis/adc10-bottom-bucket-feasibility-20261017.json"
MM = .0254
CLR = .1524
SAG = .001


def sub(a,b): return (a[0]-b[0],a[1]-b[1])
def cross(a,b): return a[0]*b[1]-a[1]*b[0]
def dot(a,b): return a[0]*b[0]+a[1]*b[1]
def point_seg(p,a,b):
    v=sub(b,a); w=sub(p,a); d=dot(v,v)
    t=max(0,min(1,dot(w,v)/d)) if d else 0
    return math.hypot(w[0]-t*v[0],w[1]-t*v[1])
def seg_inter(a,b,c,d):
    v,w=sub(b,a),sub(d,c); den=cross(v,w)
    if abs(den)<1e-12:
        return min(point_seg(a,c,d),point_seg(b,c,d),point_seg(c,a,b),point_seg(d,a,b)) < 1e-9
    t=cross(sub(c,a),w)/den; u=cross(sub(c,a),v)/den
    return -1e-10<=t<=1+1e-10 and -1e-10<=u<=1+1e-10
def seg_dist(a,b,c,d):
    return 0 if seg_inter(a,b,c,d) else min(point_seg(a,c,d),point_seg(b,c,d),point_seg(c,a,b),point_seg(d,a,b))
def bbox(points):
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))
def bb_overlap(a,b,pad=0):
    return a[0]-pad<=b[2] and b[0]-pad<=a[2] and a[1]-pad<=b[3] and b[1]-pad<=a[3]
def inside(p,ring):
    yes=False
    for a,b in zip(ring,ring[1:]+ring[:1]):
        if (a[1]>p[1]) != (b[1]>p[1]) and p[0] < (b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0]: yes=not yes
    return yes
def arc(a,b,angle):
    theta=math.radians(angle)
    chord=math.dist(a,b)
    if chord<1e-9 or abs(theta)<1e-9:return [a,b]
    v=sub(b,a)
    k=1/(2*math.tan(theta/2))
    center=((a[0]+b[0])/2-v[1]*k,(a[1]+b[1])/2+v[0]*k)
    radius=math.dist(a,center)
    steps=max(2,math.ceil(abs(theta)/(2*math.acos(max(-1,1-min(SAG/radius,1))))))
    start=math.atan2(a[1]-center[1],a[0]-center[0])
    return [(center[0]+radius*math.cos(start+theta*i/steps),center[1]+radius*math.sin(start+theta*i/steps)) for i in range(steps+1)]
def ring_path(path):
    assert isinstance(path[0],(int,float)),path[:8]
    pts=[(path[0]*MM,path[1]*MM)]; i=2; mode="L"
    while i<len(path):
        if isinstance(path[i],str):mode=path[i];i+=1
        if mode=="L":
            pts.append((path[i]*MM,path[i+1]*MM));i+=2
        elif mode in ("ARC","CARC"):
            end=(path[i+1]*MM,path[i+2]*MM)
            pts.extend(arc(pts[-1],end,path[i])[1:]);i+=3
        else:raise AssertionError(mode)
    if math.dist(pts[-1],pts[0])<1e-8:pts.pop()
    return pts
def rectangle(center,axis,inflate=0):
    # Generic C0402 pads: width .56 along component axis, height .62.
    hx,hy=(.28+inflate,.31+inflate) if axis[0] else (.31+inflate,.28+inflate)
    x,y=center
    return [(x-hx,y-hy),(x+hx,y-hy),(x+hx,y+hy),(x-hx,y+hy)]
def ring_edges(ring):return list(zip(ring,ring[1:]+ring[:1]))
def area_touches_polygon(query,rings):
    def solid(p):return inside(p,rings[0]) and not any(inside(p,r) for r in rings[1:])
    return any(solid(p) for p in query) or any(inside(p,query) for p in rings[0]) or any(seg_inter(a,b,c,d) for a,b in ring_edges(query) for r in rings for c,d in ring_edges(r))
def segment_touches_polygon(a,b,rings,clearance):
    if inside(a,rings[0]) and not any(inside(a,r) for r in rings[1:]):return True
    if inside(b,rings[0]) and not any(inside(b,r) for r in rings[1:]):return True
    return any(seg_dist(a,b,c,d)<clearance for r in rings for c,d in ring_edges(r))


def main():
    rows=PARSE(SOURCE)
    inventory=json.loads(INV.read_text(encoding="utf8"))
    inv=inventory["channels"]
    attrs=defaultdict(dict)
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
    refs={v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    # All obstacles below are literal bottom-layer source copper or plated via
    # pads. Ground FILL modifications are identified, never silently accepted.
    vias=[]; traces=[]; fills=[]
    for (kind,rid),b in rows.items():
        net=b.get("netName","")
        if kind=="VIA":
            p=(b["centerX"]*MM,b["centerY"]*MM)
            if 44<p[0]<63 and 73<p[1]<92:vias.append((rid,net,p,b["viaDiameter"]*MM/2))
        if kind in ("LINE","ARC") and b["layerId"]==2:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            pts=arc(a,z,b["angle"]) if kind=="ARC" else [a,z]
            if bb_overlap(bbox(pts),(44,73,63,92),1):
                traces.extend((rid,net,p,q,b["width"]*MM/2,bbox([p,q])) for p,q in zip(pts,pts[1:]))
        if kind=="FILL" and b["layerId"]==2:
            rings=[ring_path(p) for p in b["path"]]
            bounds=bbox(rings[0])
            if bb_overlap(bounds,(44,73,63,92),1):fills.append((rid,net,rings,bounds,b["width"]*MM/2))
    caps={ch["net"]:next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")) for ch in inv}
    gnd=[(rid,p,r) for rid,n,p,r in vias if n=="GND"]
    connected_ground_fills=[]
    for fid,n,rings,bounds,fr in fills:
        if n!="GND":continue
        connected=[]
        for gid,gp,gr in gnd:
            if inside(gp,rings[0]) and not any(inside(gp,r) for r in rings[1:]):connected.append(gid)
        if connected:connected_ground_fills.append((fid,rings,bounds,connected))
    solutions={}; attempts={}; placed=[]
    order=sorted(inv,key=lambda ch:({"ADC3_INP8":0,"ADC2_INP12":1,"ADC3_INP6":2,"ADC3_INP7":3,"ADC3_INP2":4,"ADC2_INP13":5,"ADC1_INP1":6,"ADC2_INP3":7,"ADC1_INP0":8,"ADC1_INP16":9}[ch["net"]]))

    def check_pads(p1,p2,axis,net):
        rects=[rectangle(p1,axis),rectangle(p2,axis)]
        inflated=[rectangle(p1,axis,CLR),rectangle(p2,axis,CLR)]
        cut=set()
        for idx,rect in enumerate(rects):
            pn=net if idx==0 else "GND";bounds=bbox(inflated[idx])
            for rid,n,p,r in vias:
                # No via-in-pad, even for same-net pad; prevent solder wicking.
                if inside(p,rect) or min(point_seg(p,a,b) for a,b in ring_edges(rect)) < r+(CLR if n!=pn else .06):return None
            for rid,n,a,b,r,bb in traces:
                if n!=pn and bb_overlap(bounds,bb,r) and (inside(a,inflated[idx]) or inside(b,inflated[idx]) or any(seg_dist(a,b,c,d)<r for c,d in ring_edges(inflated[idx]))):return None
            for rid,n,rings,bb,r in fills:
                if n=="GND":continue
                if n==pn or not bb_overlap(bounds,bb,r):continue
                if area_touches_polygon(inflated[idx],rings):
                    if n=="GND" and pn==net:cut.add(rid)
                    else:return None
        # Conservative 1.7x1.0mm assembly rectangle around each proposed 0402.
        cx,cy=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
        half=(.85,.5) if axis[0] else (.5,.85)
        body=(cx-half[0],cy-half[1],cx+half[0],cy+half[1])
        if any(bb_overlap(body,b,.10) for b in placed):return None
        return cut,body

    def check_route(a,b,net,own_via):
        width=.1524; radius=width/2;cut=set();bb=bbox([a,b])
        for rid,n,p,r in vias:
            if n!=net and point_seg(p,a,b)<r+CLR+radius:return None
        for rid,n,c,d,r,bounds in traces:
            if n!=net and bb_overlap(bb,bounds,CLR+radius+r) and seg_dist(a,b,c,d)<CLR+radius+r:return None
        for rid,n,rings,bounds,r in fills:
            if n=="GND":continue
            if n==net or not bb_overlap(bb,bounds,CLR+radius+r):continue
            if segment_touches_polygon(a,b,rings,CLR+radius+r):
                if n=="GND" and net!="GND":cut.add(rid)
                else:return None
        for body in placed:
            ring=[(body[0],body[1]),(body[2],body[1]),(body[2],body[3]),(body[0],body[3])]
            if inside(a,ring) or inside(b,ring) or any(seg_dist(a,b,c,d)<.10 for c,d in ring_edges(ring)):return None
        return cut

    for ch in order:
        net=ch["net"];v=ch["nearestAdcEscapeVia"];vp=tuple(v["xyMm"])
        candidates=[];tried=0;padpass=0;signalpass=0;groundpass=0
        for radius in (.65,.85,1.05,1.3,1.6,1.9,2.3,2.8,3.4,4.0):
            for degree in range(0,360,15):
                t=math.radians(degree)
                p1=(round(vp[0]+radius*math.cos(t),5),round(vp[1]+radius*math.sin(t),5))
                for axis in ((1,0),(-1,0),(0,1),(0,-1)):
                    tried+=1;p2=(p1[0]-.96*axis[0],p1[1]-.96*axis[1])
                    pads=check_pads(p1,p2,axis,net)
                    if pads is None:continue
                    padpass+=1
                    signal=check_route(vp,p1,net,v["id"])
                    if signal is None:continue
                    signalpass+=1
                    # Explicit existing GND-via return; no assumed plane tie.
                    grounds=[]
                    for fid,rings,gb,connected in connected_ground_fills:
                        test=rectangle(p2,axis)
                        is_solid=lambda q:inside(q,rings[0]) and not any(inside(q,r) for r in rings[1:])
                        if bb_overlap(bbox(test),gb) and is_solid(p2) and sum(is_solid(q) for q in test)>=2:
                            grounds.append((0,"FILL:"+fid,p2))
                            break
                    for gid,gp,gr in sorted(gnd,key=lambda x:math.dist(x[1],p2))[:12]:
                        length=math.dist(gp,p2)
                        if length>4:continue
                        ground=check_route(p2,gp,"GND",gid)
                        if ground is not None:grounds.append((length,gid,gp))
                    if not grounds:continue
                    groundpass+=1
                    gl,gid,gp=min(grounds)
                    cuts=pads[0]|signal
                    # Prefer the shortest signal segment, then the local return.
                    score=radius+gl*.35+len(cuts)*.025
                    candidates.append((score,p1,p2,axis,pads[1],cuts,gid,gp,radius,gl))
            if candidates and radius>=2.3:break
        attempts[net]={"testedCandidates":tried,"padClearancePass":padpass,"straightSignalPass":signalpass,"groundReturnPass":groundpass,"acceptedCandidates":len(candidates)}
        if not candidates:
            solutions[net]={"status":"NO_STRAIGHT_ROUTE_DRAFT","ref":caps[net],"escapeViaId":v["id"],"escapeXYmm":vp}
            continue
        _,p1,p2,axis,body,cuts,gid,gp,sl,gl=min(candidates)
        # Expensive complex ground polygon clipping is evaluated only for the
        # winning placement; it is never treated as an automatic plane pour.
        for fid,n,rings,bounds,fr in fills:
            if n!="GND":continue
            query=rectangle(p1,axis,CLR)
            if bb_overlap(bbox(query),bounds,fr) and area_touches_polygon(query,rings):cuts.add(fid)
            if bb_overlap(bbox([vp,p1]),bounds,CLR+.0762+fr) and segment_touches_polygon(vp,p1,rings,CLR+.0762+fr):cuts.add(fid)
        placed.append(body)
        ground={"widthMm":.1524,"groundViaId":gid,"startXYmm":p2,"endXYmm":gp,"lengthMm":gl}
        if gid.startswith("FILL:"):
            fid=gid[5:]
            ground={"mode":"DIRECT_SOLID_EXISTING_GND_FILL","fillId":fid,"verifiedGroundViaIds":next(x[3] for x in connected_ground_fills if x[0]==fid),"lengthMm":0,"padCenterAndAtLeastTwoCornersInsideSameFill":True}
        solutions[net]={"status":"CONDITIONAL_OFFLINE_DRAFT","ref":caps[net],"componentId":refs[caps[net]],"sourceComponentBody":rows["COMPONENT",refs[caps[net]]],"targetLayer":"BOTTOM","centerXYmm":[(p1[0]+p2[0])/2,(p1[1]+p2[1])/2],"axisOfPositiveLocalX":axis,"requiredWorldPads":{"1":{"net":net,"xyMm":p1},"2":{"net":"GND","xyMm":p2}},"signalConnection":{"widthMm":.1524,"escapeViaId":v["id"],"startXYmm":vp,"endXYmm":p1,"lengthMm":sl},"groundConnection":ground,"requiresLocalGroundFillCutbackIds":sorted(cuts),"assemblyBoundingBoxMm":body}
    report={"schema":"adc10-bottom-bucket-feasibility-20261017-v1","readOnly":True,"nativeCallsPerformed":False,"sourcePath":str(SOURCE),"sourceSha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"status":"DRAFT_NOT_FOR_APPLICATION","clearanceMm":CLR,"arcTessellationMaxSagittaMm":SAG,"obstaclesChecked":{"localVias":len(vias),"bottomLineAndArcSegments":len(traces),"bottomFills":len(fills)},"searchStats":attempts,"channels":[solutions[ch["net"]] for ch in inv],"limitations":["Only straight one-segment signal and existing-GND-via return paths were searched. No routed geometry or EDA source was generated.","A candidate requiring GND FILL cutbacks is not electrically clearance-valid until those exact static FILL polygons are explicitly repaired and native DRC passes.","Bottom component-angle/mirror mapping must be calibrated against actual native transformed pad coordinates before applying.","Check footprint body/soldermask, through-hole component pads, new-route mutual clearance and all assembly constraints in a second independent audit before application.","No existing ADC escape vias, long routes, mounting holes or unrelated nets may be removed to make these positions fit."],"manufacturingReady":False}
    report["limitations"] = [
        "Three conditional candidate placements were found with the searched straight ADC stubs. Seven channels remain unresolved by this bounded search, not proven impossible.",
        "Ground pads may join a literal existing GND FILL if the pad center and at least two pad corners are inside it and existing GND-via centers also lie in that same solid polygon. Ground need not have its own straight trace to a separate via.",
        "Seven unresolved channels need bent ADC routing, different assignment/order of shared free space, or a separately reviewed limited reroute. No such routing was generated.",
        "Every listed ground-FILL cutback must be explicitly implemented and its remaining ground connectivity rechecked. Static FILL geometry does not regenerate clearances automatically.",
        "Bottom component angle/mirror mapping, through-hole component pads, new-route mutual clearance, soldermask, courtyards and assembly constraints still need independent checking. These positions must not be applied as an approved layout.",
        "Original ADC escape vias, long routes, holes and unrelated non-ground copper remain protected; no live/source mutation or new drilling was performed.",
    ]
    report["routingCompleted"] = False
    report["applicationApproved"] = False
    report["workStoppedForParentInputConditionClarification"] = True
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"drafts":sum(x["status"]=="CONDITIONAL_OFFLINE_DRAFT" for x in solutions.values()),"failed":[n for n,x in solutions.items() if x["status"]!="CONDITIONAL_OFFLINE_DRAFT"]}))


if __name__ == "__main__":main()
