"""Offline 34-part placement manifest with literal copper/footprint-pad screening."""
import hashlib
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
G=runpy.run_path(str(ROOT/"scripts/draft-adc10-bucket-placement-readonly-20261017.py"))
SOURCE=ROOT/"output/validation/native-adc10-pcb-oriented-20261017.epru"
OUT=ROOT/"output/analysis/adc10-new34-placement-plan-20261017.json"
READ=runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]
MM=.0254
CLR=.1524


def rotate(p,ang):
    t=math.radians(ang)
    return (p[0]*math.cos(t)-p[1]*math.sin(t),p[0]*math.sin(t)+p[1]*math.cos(t))
def rect(p,w,h,angle=0):
    return [(p[0]+v[0],p[1]+v[1]) for v in (rotate(z,angle) for z in ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)))]
def inflate_axis(r,margin):
    x0,y0,x1,y1=G["bbox"](r)
    return [(x0-margin,y0-margin),(x1+margin,y0-margin),(x1+margin,y1+margin),(x0-margin,y1+margin)]


def main():
    rows=G["PARSE"](SOURCE)
    docs,_=READ(ROOT/"output/checkpoints/STM32H747_before_adc10_20261017.epro2")
    inv=json.loads((ROOT/"output/analysis/adc10-pcb-eco-api-feasibility-20261017.json").read_text())
    attrs=defaultdict(dict)
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
    refs={v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    pn=defaultdict(set)
    for (kind,rid),b in rows.items():
        if kind=="PAD_NET":
            h=json.loads(rid);pn[h[1],str(h[2])].add(b["padNet"])
    newrefs={f"U{x}" for x in range(9,20)}|{f"C{x}" for x in range(97,120)}
    old_pads=[]
    for (kind,cid),b in rows.items():
        if kind!="COMPONENT" or attrs[cid].get("Designator") in newrefs:continue
        for (pk,pid),(ph,pb) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            if pk!="PAD" or pb["layerId"] not in (1,12):continue
            pp=rotate((pb["centerX"]*MM,pb["centerY"]*MM),b["angle"])
            center=(b["x"]*MM+pp[0],b["y"]*MM+pp[1])
            if not (8<center[0]<30 and 8<center[1]<145):continue
            dp=pb["defaultPad"]
            if "width" not in dp or "height" not in dp:raise AssertionError((attrs[cid]["Designator"],dp))
            box=rect(center,dp["width"]*MM,dp["height"]*MM,b["angle"]+pb.get("padAngle",0))
            nets=pn[cid,str(pb["num"])]
            assert len(nets)==1
            old_pads.append((attrs[cid]["Designator"],str(pb["num"]),next(iter(nets)),box,G["bbox"](box)))
    vias=[(rid,b["netName"],(b["centerX"]*MM,b["centerY"]*MM),b["viaDiameter"]*MM/2) for (kind,rid),b in rows.items() if kind=="VIA" and 8<b["centerX"]*MM<30]
    traces=[];fills=[]
    for (kind,rid),b in rows.items():
        if kind in ("LINE","ARC") and b["layerId"]==1:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            pts=G["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            if G["bb_overlap"](G["bbox"](pts),(8,8,30,145),1):traces.extend((rid,b["netName"],p,q,b["width"]*MM/2,G["bbox"]([p,q])) for p,q in zip(pts,pts[1:]))
        if kind=="FILL" and b["layerId"]==1:
            rings=[G["ring_path"](path) for path in b["path"]]
            bb=G["bbox"](rings[0])
            if G["bb_overlap"](bb,(8,8,30,145),1):fills.append((rid,b["netName"],rings,bb,b["width"]*MM/2))
    planned=[]

    def propose(ref,center,angle,role):
        cid=refs[ref];b=rows["COMPONENT",cid];ft=attrs[cid]["Footprint"]
        assert b["x"]<0 or b["y"]<0
        pads=[];hard=[];cut=set()
        for (pk,pid),(ph,pb) in docs["FOOTPRINT",ft].items():
            if pk!="PAD":continue
            pp=rotate((pb["centerX"]*MM,pb["centerY"]*MM),angle)
            p=(center[0]+pp[0],center[1]+pp[1]);dp=pb["defaultPad"]
            box=rect(p,dp["width"]*MM,dp["height"]*MM,angle+pb.get("padAngle",0))
            inflated=inflate_axis(box,CLR);bounds=G["bbox"](inflated)
            nets=pn[cid,str(pb["num"])];assert len(nets)==1;net=next(iter(nets))
            for rid,n,v,vr in vias:
                distance=0 if G["inside"](v,box) else min(G["point_seg"](v,a,z) for a,z in G["ring_edges"](box))
                if distance<vr+(CLR if net!=n else .06):hard.append({"pad":pb["num"],"type":"VIA","id":rid,"net":n})
            for oref,onum,n,polygon,bb in old_pads:
                if n!=net and G["bb_overlap"](bounds,bb) and G["area_touches_polygon"](inflated,[polygon]):hard.append({"pad":pb["num"],"type":"OLD_PAD","ref":oref,"number":onum,"net":n})
            for rid,n,a,z,vr,bb in traces:
                if n!=net and G["bb_overlap"](bounds,bb,vr) and (G["inside"](a,inflated) or G["inside"](z,inflated) or any(G["seg_dist"](a,z,c,d)<vr for c,d in G["ring_edges"](inflated))):hard.append({"pad":pb["num"],"type":"LINE_ARC","id":rid,"net":n})
            for rid,n,rings,bb,fr in fills:
                if n==net or not G["bb_overlap"](bounds,bb,fr):continue
                if G["area_touches_polygon"](inflated,rings):
                    if n=="GND":cut.add(rid)
                    else:hard.append({"pad":pb["num"],"type":"FILL","id":rid,"net":n})
            for other in planned:
                for op in other["pads"]:
                    if net!=op["net"] and G["bb_overlap"](bounds,G["bbox"](op["rectangleXYmm"])) and G["area_touches_polygon"](inflated,[op["rectangleXYmm"]]):hard.append({"pad":pb["num"],"type":"NEW_PAD","ref":other["ref"],"number":op["number"],"net":op["net"]})
            pads.append({"number":str(pb["num"]),"net":net,"xyMm":p,"rectangleXYmm":box})
        result={"ref":ref,"componentId":cid,"uniqueId":b["attrs"]["Unique ID"],"role":role,"sourceBodyBefore":b,"footprintUuid":ft,"set":{"x":center[0]/MM,"y":center[1]/MM,"rotation":angle,"layer":1},"xyMm":center,"pads":pads,"hardCopperConflicts":hard,"requiresGroundFillCutbackIds":sorted(cut)}
        return result

    channels=inv["channels"]
    pre_refs=list(range(97,100))+list(range(106,113))
    dec_refs=list(range(100,103))+list(range(113,120))
    for i,ch in enumerate(channels):
        sma=next(p for p in ch["originalAnalogParts"] if p["ref"]==ch["smaRef"])
        sy=sma["xyMm"][1]
        # Move the whole repeated trio together if any fixed source copper
        # intrudes; only report a no-hard-conflict provisional trio.
        found=None
        for dy in (2.0,2.5,3.0,3.5,4.0):
            for ox in (18.8,19.3,19.8,20.3,20.8):
                group=[(f"U{10+i}",(ox,sy-dy),0,"OPA320 follower"),(f"C{pre_refs[i]}",(ox-3.0,sy-dy-1.1),90,"10nF PRE shunt"),(f"C{dec_refs[i]}",(ox+3.2,sy-dy+.95),180,"100nF local OPA supply")]
                temp=[]
                for args in group:
                    part=propose(*args)
                    temp.append(part)
                    planned.append(part)
                del planned[-3:]
                if not any(p["hardCopperConflicts"] for p in temp):found=temp;break
            if found:break
        if found:planned.extend(found)
        else:
            planned.extend(temp)
    for spec in (("U9",(23,77),0,"REF3325 2.5V bias source"),("C103",(21.3,79.1),0,"100nF REF input"),("C104",(20.9,75.5),90,"1uF REF output"),("C105",(25.4,74.4),90,"4.7uF REF output bulk")):
        planned.append(propose(*spec))
    assert len(planned)==34 and {p["ref"] for p in planned}==newrefs
    conflicts=[{"ref":p["ref"],"conflicts":p["hardCopperConflicts"]} for p in planned if p["hardCopperConflicts"]]
    report={"schema":"adc10-new34-placement-plan-20261017-v1","readOnly":True,"nativeCallsPerformed":False,"sourcePath":str(SOURCE),"sourceSha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"status":"CONDITIONAL_PLACEMENT_DRAFT" if not conflicts else "DRAFT_HAS_HARD_CONFLICTS","clearanceMm":CLR,"newPartCount":34,"hardConflicts":conflicts,"edits":planned,"copperObjectsChecked":{"existingAnalogStripFootprintPads":len(old_pads),"vias":len(vias),"topLineAndArcSegments":len(traces),"topFills":len(fills)},"conditions":["No non-ground copper or existing component pad conflict is permitted at the proposed new pads.","Every listed static GND FILL requires an explicit local pad clearance hole/cutback before routing is electrically valid; do not assume pour regeneration.","Existing via-in-pad was rejected including same-net vias; no unapproved via-in-pad process is introduced.","Only original copper and new-pad mutual clearance were screened. Complete courtyard/body/assembly, feedback/route clearance, local decoupling loop and native DRC still required.","This is a placement-only staging plan, not a completed routing design. Preserve original Unique IDs, nets, pad bindings and all unrelated source bodies."],"routingHints":{"feedback":"OPA pad1 OUT to pad4 IN- should be a short local dedicated trace; no jumpers/net-name-only connection.","bias":"REF block is central in Y. Use a deliberately wide quiet 2.5V tree/trunk with individual 6.8k branches; do not reuse old +3V3 feeders without isolation.","bucket":"Ten 2.2nF C80..C96 must move separately near bottom MCU escapes; these new strip placements do not substitute for them."},"manufacturingReady":False,"floatingActualZeroDetectorImplemented":False}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"status":report["status"],"parts":len(planned),"hardConflictRefs":[p["ref"] for p in conflicts],"groundFillCuts":len({x for p in planned for x in p["requiresGroundFillCutbackIds"]})}))


if __name__=="__main__":main()
