"""Offline new-strip traces and exact local ground-hole union operations."""
import copy
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/build-adc10-strip-operations-20261018.py"))
pc=M["pc"];G=M["G"];MM=M["MM"];S=M["SCALE"]
HERE=M["HERE"]
SOURCE=M["SOURCE"]
STAGE1=HERE/"adc10-strip-phase1-explicit-closed-API-polygon-20261018.json"
READ=runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]


def turn(p,angle):
    t=math.radians(angle)
    return (p[0]*math.cos(t)-p[1]*math.sin(t),p[0]*math.sin(t)+p[1]*math.cos(t))
def rectangle(p,w,h,angle):
    return [(p[0]+v[0],p[1]+v[1]) for v in (turn(q,angle) for q in ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)))]


def main():
    baseline=G["PARSE"](SOURCE);rows=copy.deepcopy(baseline)
    isolation=json.loads(M["ISOLATION"].read_text())
    phase1=json.loads(STAGE1.read_text())
    for op in isolation["existingCopperOperations"]:
        key=op["type"],op["id"]
        assert rows[key]==op["beforeBody"]
        if op["action"]=="delete":del rows[key]
        else:rows[key]=copy.deepcopy(op["afterBody"])
    rc=isolation["R164Correction"]
    rows["COMPONENT",rc["id"]]=copy.deepcopy(rc["afterBody"])
    for p in phase1["componentPlacements"]:rows["COMPONENT",p["componentId"]]=copy.deepcopy(p["afterBody"])
    for f in phase1["fillPathUpdates"]:rows["FILL",f["id"]]["path"]=copy.deepcopy(f["afterPath"])
    attrs=defaultdict(dict)
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
    refs={v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    pads={p["ref"]:{v["number"]:v for v in p["expectedWorldPads"]} for p in phase1["componentPlacements"]}
    traces=[]
    def path(net,points,width,role):
        for a,b in zip(points,points[1:]):
            a,b=tuple(a),tuple(b)
            if math.dist(a,b)<1e-7:continue
            traces.append({"key":f"ADC18_STRIP_{len(traces)+1:03}","net":net,"layer":"TOP","layerId":1,"startXYmm":a,"endXYmm":b,"widthMm":width,"startXMil":a[0]/MM,"startYMil":a[1]/MM,"endXMil":b[0]/MM,"endYMil":b[1]/MM,"widthMil":width/MM,"role":role,"primitiveLock":False})
    bias_ys=[]
    for idx,a in enumerate(isolation["newRouteAnchors"]):
        pre,drv=a["newPRE"],a["newDRV"]
        op=pads[a["buffer"]]
        sy=a["existingPREAnchorMmYUp"][1]
        anchor=tuple(a["existingPREAnchorMmYUp"])
        rbpre=tuple(a["biasPad1PRE"]["xyMmYUp"])
        rbbias=tuple(a["biasPad2Quiet2V5"]["xyMmYUp"])
        series=tuple(a["seriesInput"]["xyMmYUp"])
        cpre=pads[f"C{([97,98,99]+list(range(106,113)))[idx]}"]
        cdec=pads[f"C{([100,101,102]+list(range(113,120)))[idx]}"]
        path(pre,[anchor,(rbpre[0],sy),rbpre],.2032,"Rin PRE anchor to bias resistor PRE pad")
        path(pre,[anchor,(anchor[0],cpre["1"]["xyMm"][1]),cpre["1"]["xyMm"],op["3"]["xyMm"]],.2032,"DC-coupled PRE to10nF and OPA IN+")
        out=op["1"]["xyMm"];minus=op["4"]["xyMm"]
        path(drv,[out,(18.8,out[1]),(18.8,minus[1]),minus],.2032,"short local OPA voltage-follower feedback")
        path(drv,[out,(series[0],out[1]),series],.2032,"OPA OUT to original47R input; ADC post route retained")
        # Each existing +3V3 via remains on its original inner supply network.
        local_vias=[(rid,b) for (kind,rid),b in rows.items() if kind=="VIA" and b.get("netName")=="+3V3" and abs(b["centerX"]*MM-13.85)<.02 and abs(b["centerY"]*MM-sy-2.975)<.5]
        assert len(local_vias)==1,(a["sma"],local_vias)
        via_id,via=local_vias[0];vp=(via["centerX"]*MM,via["centerY"]*MM)
        top=vp[1]+.65
        dp=cdec["1"]["xyMm"]
        path("+3V3",[vp,(vp[0],top),(23.5,top),(23.5,sy-1.8),(dp[0],sy-1.8),dp],.3048,"dedicated original supply via to local100nF")
        path("+3V3",[dp,op["5"]["xyMm"]],.3048,"100nF to OPA V+ short local feed")
        by=sy+(6.0 if idx==5 else 4.35);bias_ys.append(by)
        path("ADC_BIAS_2V5",[rbbias,(12.7,rbbias[1]),(12.7,by),(26.5,by)],.3048,"quiet2.5V branch to6.8k bias resistor")
    path("ADC_BIAS_2V5",[(26.5,min(bias_ys)),(26.5,87.8),(25.7,87.8),(25.7,93.3),(26.5,93.3),(26.5,max(bias_ys))],.6,"central-reference quiet-bias wide trunk; local jog avoids preserved digital vias")
    ref=pads["U9"];ci=pads["C103"];co=pads["C104"];cb=pads["C105"]
    # Feed the central REF input from the neighboring buffered-channel local
    # rail; the route approaches from above without crossing IN- or REF ground.
    path("+3V3",[(23.5,isolation["newRouteAnchors"][4]["existingPREAnchorMmYUp"][1]-1.8),(23.5,78.7),(ci["1"]["xyMm"][0],78.7),ci["1"]["xyMm"]],.3048,"local3.3V tree to REF1uF input bypass")
    path("+3V3",[ci["1"]["xyMm"],ref["1"]["xyMm"]],.3048,"REF input1uF to IN")
    rp=ref["2"]["xyMm"]
    path("ADC_BIAS_2V5",[rp,(rp[0],co["1"]["xyMm"][1]),co["1"]["xyMm"]],.3048,"REF output4.7uF nearest bypass")
    path("ADC_BIAS_2V5",[rp,(rp[0],76.25),(26.5,76.25)],.4,"REF output to central quiet-bias trunk")
    path("ADC_BIAS_2V5",[(cb["1"]["xyMm"][0],76.25),cb["1"]["xyMm"]],.4,"REF output100nF shunt")
    print(json.dumps({"phase":"routes-generated","lines":len(traces)}),flush=True)

    # Build literal obstacles after only the reviewed parent isolation and
    # placement virtual deltas. Global pads/copper outside the strip remain
    # read-only and are never regenerated by this script.
    docs,_=READ(ROOT/"output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2")
    pn={}
    for (kind,rid),b in rows.items():
        if kind=="PAD_NET":
            h=json.loads(rid);pn[h[1],str(h[2])]=b["padNet"]
    obstacles=[]
    def obstacle(key,net,shapes):
        if shapes and G["bb_overlap"](M["bounds"](shapes),(9,8,29,146),.5):obstacles.append((key,net,shapes,M["bounds"](shapes)))
    allpads=[]
    for (kind,cid),b in rows.items():
        if kind!="COMPONENT":continue
        if not (8<b["x"]*MM<31 and 7<b["y"]*MM<147):continue
        for (pk,pid),(ph,p) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            if pk!="PAD" or p.get("layerId") not in (1,12):continue
            q=turn((p["centerX"]*MM,p["centerY"]*MM),b["angle"])
            center=(b["x"]*MM+q[0],b["y"]*MM+q[1]);d=p["defaultPad"]
            assert "width" in d and "height" in d,(attrs[cid]["Designator"],d)
            # Rectangular envelopes conservatively include ellipse/rounded pads.
            poly=M["ip"](rectangle(center,d["width"]*MM,d["height"]*MM,b["angle"]+p.get("padAngle",0)))
            net=pn.get((cid,str(p["num"])),"")
            label="PAD:"+attrs[cid]["Designator"]+":"+str(p["num"])
            obstacle(label,net,[poly]);allpads.append((label,net,[poly]))
    for (kind,rid),b in rows.items():
        net=b.get("netName","")
        if kind=="VIA":
            p=(b["centerX"]*MM,b["centerY"]*MM)
            obstacle("VIA:"+rid,net,M["capsule"](p,p,b["viaDiameter"]*MM/2))
        elif kind in ("LINE","ARC") and b.get("layerId")==1:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            points=G["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            obstacle(kind+":"+rid,net,M["union"]([p for x,y in zip(points,points[1:]) for p in M["capsule"](x,y,b["width"]*MM/2)]))
        elif kind=="FILL" and b.get("layerId")==1 and net!="GND":
            polys=[M["ip"](G["ring_path"](r)) for r in b["path"]]
            # Respect the native clockwise outer / counterclockwise holes.
            obstacle("FILL:"+rid,net,polys)
        elif kind=="POLY" and b.get("layerId")==1:
            points=G["ring_path"](b["path"])
            obstacle("POLY:"+rid,net,M["union"]([p for x,y in zip(points,points[1:]) for p in M["capsule"](x,y,b["width"]*MM/2)]))
    print(json.dumps({"phase":"source-obstacles-built","obstacles":len(obstacles)}),flush=True)
    conflicts=[];line_shapes=[]
    for i,line in enumerate(traces):
        shapes=M["capsule"](line["startXYmm"],line["endXYmm"],line["widthMm"]/2+.1524)
        bb=M["bounds"](shapes)
        for label,net,polys,ob in obstacles:
            if net.casefold()!=line["net"].casefold() and G["bb_overlap"](bb,ob) and M["shapes_intersect"](shapes,polys):
                conflicts.append({"lineKey":line["key"],"lineNet":line["net"],"role":line["role"],"obstacle":label,"obstacleNet":net})
        for j,other in enumerate(traces[:i]):
            if other["net"].casefold()==line["net"].casefold():continue
            if M["shapes_intersect"](shapes,line_shapes[j]):conflicts.append({"lineKey":line["key"],"lineNet":line["net"],"obstacle":other["key"],"obstacleNet":other["net"],"role":line["role"]})
        line_shapes.append(M["capsule"](line["startXYmm"],line["endXYmm"],line["widthMm"]/2))
    print(json.dumps({"phase":"trace-clearance-screened","conflicts":len(conflicts)}),flush=True)
    voids=[p for line in traces for p in M["capsule"](line["startXYmm"],line["endXYmm"],line["widthMm"]/2+M["CLEAR"])]
    updates=M["cut_ground"](rows,voids)
    report={"schema":"stm32h747-adc10-strip-phase2-route-operations-20261018-v1","sourcePath":str(SOURCE),"sourceSha256":M["sha"](SOURCE),"requiresPhase1Manifest":str(STAGE1),"phase1ManifestSha256":M["sha"](STAGE1),"requiresParentIsolationManifest":str(M["ISOLATION"]),"readOnlyBuilder":True,"liveCalls":0,"wholePCBSetSource":False,"status":"READY_FOR_PARENT_NATIVE_REVIEW" if not conflicts else "HAS_EXPLICIT_GEOMETRY_CONFLICTS_DO_NOT_APPLY","newLineCreates":traces,"fillPathUpdates":updates,"geometryConflicts":conflicts,"geometryChecks":{"existingCopperObstacles":len(obstacles),"newTraceCount":len(traces),"allDifferentNetNewTracesChecked":True,"allNewTracesVersusExistingPadsCopperViasChecked":True,"clearanceMm":.1524,"groundVoidOffsetMm":M["CLEAR"],"groundOuterExact":all(u["outerPathExact"] for u in updates),"oldArcCommandsInChangedGroundHoles":sum(u["affectedOriginalArcCommands"] for u in updates)},"applicationOrder":["guard actual post-isolation and phase1 bodies or rebase exact geometry after native ID normalization","update only listed ground-FILL path via public API","create only listed TOP LINEs via public API; record every returned primitive ID","capture actual source and full native DRC","independent graph/connectivity and protected-source audit before saved checkpoint"],"protection":{"existingVIAChanges":0,"existingPADChanges":0,"existingNonGNDcopperChanges":0,"existingRuleChanges":0,"layerChanges":0,"J18Changes":0,"ADCpostLongRoutingChanges":0},"manufacturingReady":False}
    target=HERE/"adc10-strip-phase2-routes-ground-clearance-20261018.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"manifest":str(target),"newLines":len(traces),"conflicts":len(conflicts),"firstConflicts":conflicts[:10],"fillUpdates":len(updates),"changedOldHoleArcs":report["geometryChecks"]["oldArcCommandsInChangedGroundHoles"]}))


if __name__=="__main__":main()
