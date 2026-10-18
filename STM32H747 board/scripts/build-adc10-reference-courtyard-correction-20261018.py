"""Bounded three-cap courtyard correction after the frozen 204-route batch."""
import copy
import json
import math
import runpy
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
G=M["G"];MM=M["MM"];HERE=M["HERE"]
READ=runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]
PLAN=HERE/"adc10-strip-phase2-rebased-closed-operations-20261018.json"
P1=ROOT/"output/validation/native-adc10-pcb-strip_fill_v3-20261018.epru"
TARGETS={"C103":(19.8,78.6),"C104":(19.8,75.5),"C105":(25.4,74.1)}
EPS=.000006


def turn(p,angle):
    t=math.radians(angle)
    return (p[0]*math.cos(t)-p[1]*math.sin(t),p[0]*math.sin(t)+p[1]*math.cos(t))
def rectangle(p,w,h,angle):
    return [(p[0]+q[0],p[1]+q[1]) for q in (turn(z,angle) for z in ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)))]
def project(p,a,b):
    v=G["sub"](b,a);return G["dot"](G["sub"](p,a),v)/G["dot"](v,v)
def collinear(a,b,c,d):
    length=math.dist(a,b)
    return max(abs(G["cross"](G["sub"](b,a),G["sub"](c,a))),abs(G["cross"](G["sub"](b,a),G["sub"](d,a))))/length<EPS
def merge(intervals):
    out=[]
    for a,b in sorted(intervals):
        if not out or a>out[-1][1]+1e-5:out.append([a,b])
        else:out[-1][1]=max(out[-1][1],b)
    return out


def main():
    source=Path(sys.argv[1])
    rows=G["PARSE"](source);pre=G["PARSE"](P1)
    plan=json.loads(PLAN.read_text())
    assert plan["geometryConflicts"]==[] and len(plan["newLineCreates"])==204
    oldkeys={f"ADC18_STRIP_{x:03}" for x in (196,197,198,199,201,204)}
    obsolete=[x for x in plan["newLineCreates"] if x["key"] in oldkeys]
    assert len(obsolete)==6
    coverage=defaultdict(list);deletes=[];preserve=[]
    for (kind,rid),b in rows.items():
        if kind!="LINE" or b.get("layerId")!=1:continue
        a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
        intervals=[]
        for old in obsolete:
            c,d=tuple(old["startXYmm"]),tuple(old["endXYmm"])
            if b["netName"].casefold()!=old["net"].casefold() or abs(b["width"]*MM-old["widthMm"])>EPS:continue
            if not collinear(a,z,c,d):continue
            u,v=sorted((project(c,a,z),project(d,a,z)))
            lo,hi=max(0,u),min(1,v)
            if (hi-lo)*math.dist(a,z)<EPS:continue
            intervals.append((lo,hi))
            cov=sorted((project(a,c,d),project(z,c,d)))
            coverage[old["key"]].append((max(0,cov[0]),min(1,cov[1])))
        if not intervals:continue
        assert (kind,rid) not in pre,("REFUSE_TO_TOUCH_PRE_PHASE2_LINE",rid)
        cuts=merge(intervals)
        deletes.append({"type":"LINE","id":rid,"beforeBody":b,"beforeBodySha256":M["digest"](b),"reason":"Only obsolete new phase2 reference-cap leaf traces; original pre-phase2 routing protected"})
        cursor=0
        for lo,hi in cuts+[[1,1]]:
            if (lo-cursor)*math.dist(a,z)>EPS:
                p=(a[0]+(z[0]-a[0])*cursor,a[1]+(z[1]-a[1])*cursor)
                q=(a[0]+(z[0]-a[0])*lo,a[1]+(z[1]-a[1])*lo)
                preserve.append((b["netName"],p,q,b["width"]*MM,"Retain unaffected portion of a merged new phase2 trace"))
            cursor=max(cursor,hi)
    for old in obsolete:
        cov=merge(coverage[old["key"]])
        assert len(cov)==1 and cov[0][0]<1e-5 and cov[0][1]>1-1e-5,("MISSING_FULL_204_ROUTE_BATCH",old["key"],cov)
    for d in deletes:del rows["LINE",d["id"]]
    attrs=defaultdict(dict);nets={}
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
        if kind=="PAD_NET":
            q=json.loads(rid);nets[q[1],str(q[2])]=b["padNet"]
    refs={a["Designator"]:cid for cid,a in attrs.items() if "Designator" in a}
    docs,_=READ(ROOT/"output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2")
    changes=[];newpads={}
    for ref,xy in TARGETS.items():
        cid=refs[ref];before=rows["COMPONENT",cid];after=copy.deepcopy(before)
        after["x"]=xy[0]/MM;after["y"]=xy[1]/MM
        changes.append({"ref":ref,"componentId":cid,"beforeBody":before,"beforeBodySha256":M["digest"](before),"afterBody":after,"allowedChangedFields":["x","y"]})
        rows["COMPONENT",cid]=after
    def pads_for(ref):
        cid=refs[ref];b=rows["COMPONENT",cid];result={}
        for (kind,rid),(h,p) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            if kind!="PAD":continue
            q=turn((p["centerX"]*MM,p["centerY"]*MM),b["angle"])
            xy=(b["x"]*MM+q[0],b["y"]*MM+q[1]);dp=p["defaultPad"]
            result[str(p["num"])]={"net":nets[cid,str(p["num"])],"xyMm":xy,"rectangle":rectangle(xy,dp["width"]*MM,dp["height"]*MM,b["angle"]+p.get("padAngle",0))}
        return result
    for ref in TARGETS:newpads[ref]=pads_for(ref)
    rp=pads_for("U9");ci=newpads["C103"];co=newpads["C104"];cb=newpads["C105"]
    traces=[]
    def path(net,points,width,role):
        for a,b in zip(points,points[1:]):
            traces.append({"key":f"ADC18_REF_FIX_{len(traces)+1:03}","net":net,"layer":"TOP","layerId":1,"startXYmm":a,"endXYmm":b,"widthMm":width,"startXMil":a[0]/MM,"startYMil":a[1]/MM,"endXMil":b[0]/MM,"endYMil":b[1]/MM,"widthMil":width/MM,"role":role,"primitiveLock":False})
    for net,a,b,w,role in preserve:path(net,[a,b],w,role)
    rail_start=next(t["startXYmm"] for t in obsolete if t["key"]=="ADC18_STRIP_196")
    path("+3V3",[rail_start,(23.5,79.0),(22.7,79.0),(22.7,78.6),(19.8,78.6),ci["1"]["xyMm"]],.3048,"Relocated C1031uF input bypass supply route")
    path("+3V3",[ci["1"]["xyMm"],rp["1"]["xyMm"]],.3048,"Relocated C103 to REF IN")
    old201=next(t for t in obsolete if t["key"]=="ADC18_STRIP_201")
    path("ADC_BIAS_2V5",[old201["startXYmm"],co["1"]["xyMm"]],.3048,"Relocated C1044.7uF nearest REF output bypass")
    old204=next(t for t in obsolete if t["key"]=="ADC18_STRIP_204")
    path("ADC_BIAS_2V5",[old204["startXYmm"],cb["1"]["xyMm"]],.4,"Relocated C105100nF output bypass")
    obstacles=[]
    def obstacle(label,net,shapes):
        if shapes and G["bb_overlap"](M["bounds"](shapes),(18,73,25,83),1):obstacles.append((label,net,shapes,M["bounds"](shapes)))
    for ref,cid in refs.items():
        b=rows.get(("COMPONENT",cid))
        if not b or not (17<b["x"]*MM<27 and 71<b["y"]*MM<85):continue
        for num,p in pads_for(ref).items():obstacle("PAD:"+ref+":"+num,p["net"],[M["ip"](p["rectangle"])])
    for (kind,rid),b in rows.items():
        net=b.get("netName","")
        if kind=="VIA":
            q=(b["centerX"]*MM,b["centerY"]*MM)
            obstacle("VIA:"+rid,net,M["capsule"](q,q,b["viaDiameter"]*MM/2))
        elif kind in ("LINE","ARC") and b.get("layerId")==1:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            pts=G["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            if not G["bb_overlap"](G["bbox"](pts),(18,73,25,83),1):continue
            obstacle(kind+":"+rid,net,M["union"]([p for c,d in zip(pts,pts[1:]) for p in M["capsule"](c,d,b["width"]*MM/2)]))
        elif kind=="FILL" and b.get("layerId")==1 and net!="GND":obstacle("FILL:"+rid,net,[M["ip"](G["ring_path"](p)) for p in b["path"]])
    conflicts=[];newcopper=[]
    for t in traces:
        safe=M["capsule"](t["startXYmm"],t["endXYmm"],t["widthMm"]/2+.1524)
        bb=M["bounds"](safe)
        for label,net,shapes,ob in obstacles:
            if net.casefold()!=t["net"].casefold() and G["bb_overlap"](bb,ob) and M["shapes_intersect"](safe,shapes):conflicts.append({"line":t["key"],"obstacle":label,"net":net})
        for net,shape,key in newcopper:
            if net.casefold()!=t["net"].casefold() and M["shapes_intersect"](safe,shape):conflicts.append({"line":t["key"],"obstacle":key,"net":net})
        newcopper.append((t["net"],M["capsule"](t["startXYmm"],t["endXYmm"],t["widthMm"]/2),t["key"]))
    voids=[p for t in traces for p in M["capsule"](t["startXYmm"],t["endXYmm"],t["widthMm"]/2+.17)]
    for ref,pads in newpads.items():
        for p in pads.values():
            if p["net"]!="GND":voids.extend(M["expanded"](M["ip"](p["rectangle"]),.17))
    updates=M["cut_ground"](rows,voids)
    assert len(updates)==1
    assert all(p[-2:]==p[:2] for u in updates for p in u["afterPath"])
    report={"schema":"adc10-ref-three-cap-courtyard-correction-20261018-v1","status":"READY_FOR_REVIEW" if not conflicts else "HAS_CLEARANCE_CONFLICTS_DO_NOT_APPLY","sourcePath":str(source),"sourceSha256":M["sha"](source),"liveCalls":0,"wholePCBSetSource":False,"componentMoves":changes,"newPadWorldGeometry":newpads,"deleteOnlyNewPhase2Lines":deletes,"obsoletePlannedPhase2TraceKeys":sorted(oldkeys),"retainedMergedTraceFragments":len(preserve),"newLineCreates":traces,"fillPathUpdates":updates,"clearanceConflicts":conflicts,"courtyardProofPath":str(HERE/"adc10-actual-placement-envelope-audit-20261018.json"),"APIPathsExplicitlyClosed":True,"valuesPinsNetsUnchanged":True,"prePhase2LINEandAllOtherOriginalCopperProtected":True,"allExistingVIAandFreePADBodiesProtected":True,"operationOrder":["guard full current source and every target component/newLINE/FILL body","delete only enumerated obsolete newphase2LINE records","move only C103,C104,C105 preserving all attributes/nets/angles","apply explicitly closed local GND-FILL path update","create retained fragments and new cap routes","native DRC + independent protected-source and same-net copper-union audit"],"manufacturingReady":False}
    out=HERE/"adc10-reference-courtyard-correction-20261018.json"
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"manifest":str(out),"sha256":M["sha"](out),"move":len(changes),"deleteNewLines":len(deletes),"createLines":len(traces),"retainedFragments":len(preserve),"conflicts":conflicts}))


if __name__=="__main__":main()
