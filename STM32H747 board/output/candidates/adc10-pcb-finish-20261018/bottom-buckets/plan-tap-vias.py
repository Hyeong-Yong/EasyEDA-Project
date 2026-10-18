"""Offline six-layer new ADC tap-via feasibility plus bottom bucket manifest."""
import hashlib
import heapq
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/"plan-bottom-buckets.py"))
globals().update({k:M[k] for k in ["ROOT","SOURCE","CHECKPOINT","READ","MM","CLR","WIDTH","GRID","SCALE","BOUNDS","ip","fp","pc","capsule","circle","rectangle","filled_rings","paths_bbox","offset","union","inter","diff","overlap","positive"]})
LAYERS=[1,2,15,16,17,18]
VIA_DIAMETER=.31
HOLE_DIAMETER=.20
HOLE_EDGE_CLEARANCE=.30
VIA_MARGIN=.001
POWER_FILL_EXCEPTION={"+3V3","NET-(U1D-VDDA)","NET-(U1D-VREF+)"}


class AllLayers:
    def __init__(self,board):
        self.board=board;self.obs=[];self.ground=[];self.drills=[];self.additional=[]
        rows=board.rows
        for (k,i),b in rows.items():
            n=b.get("netName","");layer=b.get("layerId")
            if k=="VIA":
                p=(b["centerX"]*MM,b["centerY"]*MM);r=b["viaDiameter"]*MM/2
                if not overlap((p[0]-r,p[1]-r,p[0]+r,p[1]+r),BOUNDS,1):continue
                obj={"id":i,"kind":k,"net":n,"layers":LAYERS,"paths":[circle(p,r)]}
                self.obs.append(obj);self.drills.append({"id":i,"xyMm":p,"radiusMm":b["holeDiameter"]*MM/2})
            elif k in ("LINE","ARC","CARC") and layer in LAYERS:
                a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
                pts=M["OLD"]["arc"](a,z,b["angle"]) if k!="LINE" else [a,z]
                if not overlap(M["bbox"](pts),BOUNDS,1):continue
                self.obs.append({"id":i,"kind":k,"net":n,"layers":[layer],"paths":capsule(pts,b["width"]*MM/2)})
            elif k=="FILL" and layer in LAYERS:
                raw=filled_rings(b["path"])
                if not overlap(paths_bbox(raw),BOUNDS,1):continue
                obj={"id":i,"kind":k,"net":n,"layers":[layer],"paths":offset(raw,b["width"]*MM/2),"sourcePaths":raw,"body":b}
                if n=="GND":self.ground.append(obj)
                else:self.obs.append(obj)
        docs,_=READ(CHECKPOINT)
        nets={}
        for (k,i),b in rows.items():
            if k=="PAD_NET":
                a=json.loads(i);nets[a[1],str(a[2])]=b["padNet"]
        for (k,cid),c in rows.items():
            if k!="COMPONENT":continue
            for (pk,pid),(head,p) in docs["FOOTPRINT",board.attrs[cid]["Footprint"]].items():
                if pk!="PAD" or p["layerId"] not in (1,2,12):continue
                actual_layer=(3-p["layerId"]) if p["layerId"] in (1,2) and c["layerId"]==2 else p["layerId"]
                theta=math.radians(c["angle"]);x,y=p["centerX"]*MM,p["centerY"]*MM
                gp=(c["x"]*MM+x*math.cos(theta)-y*math.sin(theta),c["y"]*MM+x*math.sin(theta)+y*math.cos(theta))
                sh=p["defaultPad"]
                if "width" not in sh:
                    raw=M["OLD"]["ring_path"](sh["path"])
                    q=[(c["x"]*MM+x*math.cos(theta)-y*math.sin(theta),c["y"]*MM+x*math.sin(theta)+y*math.cos(theta)) for x,y in raw]
                    if overlap(M["bbox"](q),BOUNDS,1):
                        self.obs.append({"id":cid+":"+pid,"kind":"COMPONENT_POLYGON_PAD","net":nets.get((cid,str(p["num"])),""),"layers":LAYERS if actual_layer==12 else [actual_layer],"paths":[positive(ip(q))]})
                    continue
                hw=sh["width"]*MM/2;hh=sh["height"]*MM/2
                if not overlap((gp[0]-hw,gp[1]-hh,gp[0]+hw,gp[1]+hh),BOUNDS,1):continue
                ang=theta+math.radians(p.get("padAngle",0))
                if sh["padType"]=="ELLIPSE":
                    q=[(gp[0]+hw*math.cos(t)*math.cos(ang)-hh*math.sin(t)*math.sin(ang),gp[1]+hw*math.cos(t)*math.sin(ang)+hh*math.sin(t)*math.cos(ang)) for t in [j*math.tau/96 for j in range(96)]]
                else:q=[(gp[0]+x*math.cos(ang)-y*math.sin(ang),gp[1]+x*math.sin(ang)+y*math.cos(ang)) for x,y in [(-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh)]]
                self.obs.append({"id":cid+":"+pid,"kind":"COMPONENT_PAD","net":nets.get((cid,str(p["num"])),""),"layers":LAYERS if actual_layer==12 else [actual_layer],"paths":[positive(ip(q))]})
                if p.get("hole"):
                    hole=p["hole"];hr=max(hole["width"],hole["height"])*MM/2
                    self.drills.append({"id":cid+":"+pid,"xyMm":gp,"radiusMm":hr})
        for o in self.obs:
            o["bbox"]=paths_bbox(o["paths"])
            o["viaBlocked"]=offset(o["paths"],CLR+VIA_MARGIN)
        print(json.dumps({"stage":"six_layer_loaded","objects":len(self.obs),"groundFills":len(self.ground),"localDrills":len(self.drills)}),flush=True)

    def viable(self,p,net):
        land=[circle(p,VIA_DIAMETER/2)];bb=paths_bbox(land)
        for drill in self.drills:
            if math.dist(p,drill["xyMm"])<HOLE_DIAMETER/2+drill["radiusMm"]+HOLE_EDGE_CLEARANCE+VIA_MARGIN:return False
        for o in self.obs+self.additional:
            if o["net"]==net or not overlap(bb,o["bbox"],CLR+VIA_MARGIN):continue
            # Explicitly authorized local new-via anti-pad exception. The
            # original power-plane outline/remote holes must remain unchanged.
            if o["kind"]=="FILL" and o["net"] in POWER_FILL_EXCEPTION:continue
            if inter(land,o["viaBlocked"]):return False
        for o in self.board.new:
            if o["net"]==net:continue
            if overlap(bb,o["bbox"],CLR+.008) and inter(land,o["clear"]):return False
        return True

    def taps(self,ch,layer=17):
        vp=tuple(ch["nearestAdcEscapeVia"]["xyMm"]);net=ch["net"]
        lines=[x for x in ch["existingAdcLines"] if x["layer"]==layer]
        # Existing local route graph, used to state actual electrical branch
        # distance from the original escape, not merely straight-line distance.
        key=lambda p:tuple(round(x,4) for x in p)
        graph=defaultdict(list)
        for l in lines:
            a,z=key(l["startMm"]),key(l["endMm"]);dl=math.dist(a,z)
            graph[a].append((z,dl));graph[z].append((a,dl))
        start=min(graph,key=lambda p:math.dist(p,vp)) if graph else None
        dists={start:math.dist(start,vp)} if start is not None else {}
        heap=[(dists[start],start)] if start is not None else []
        while heap:
            d,a=heapq.heappop(heap)
            if d>dists[a]+1e-9:continue
            for z,dl in graph[a]:
                nd=d+dl
                if nd<dists.get(z,math.inf):dists[z]=nd;heapq.heappush(heap,(nd,z))
        out=[];seen=set();tested=0
        for l in lines:
            a,z=l["startMm"],l["endMm"]
            if not overlap(M["bbox"]([a,z]),BOUNDS):continue
            length=math.dist(a,z);steps=max(1,math.ceil(length/.01))
            for j in range(steps+1):
                t=j/steps;p=(a[0]+(z[0]-a[0])*t,a[1]+(z[1]-a[1])*t)
                if not(BOUNDS[0]+.5<p[0]<BOUNDS[2]-.5 and BOUNDS[1]+.5<p[1]<BOUNDS[3]-.5) or math.dist(p,vp)>8:continue
                if key(p) in seen:continue
                seen.add(key(p));tested+=1
                if not self.viable(p,net):continue
                along=min(dists.get(key(a),math.inf)+length*t,dists.get(key(z),math.inf)+length*(1-t))
                out.append({"xyMm":p,"kind":"NEW_ADC_TAP_VIA","net":net,"diameterMm":VIA_DIAMETER,"holeMm":HOLE_DIAMETER,"layers":LAYERS,"touchExistingLineId":l["id"],"touchExistingLineLayer":layer,"electricalDistanceFromEscapeMm":along,"euclideanDistanceFromEscapeMm":math.dist(p,vp),"penaltyMm":.15*along})
        print(json.dumps({"net":net,"tapCandidatesTested":tested,"sixLayerFeasible":len(out)}),flush=True)
        return out

    def accept(self,r):
        s=r.get("selectedRoutingSource",{})
        if s.get("kind")!="NEW_ADC_TAP_VIA":return
        p=s["xyMm"];o={"id":"NEWVIA:"+r["ref"],"kind":"NEW_VIA","net":r["net"],"layers":LAYERS,"paths":[circle(p,VIA_DIAMETER/2)]}
        o["bbox"]=paths_bbox(o["paths"]);o["viaBlocked"]=offset(o["paths"],CLR+VIA_MARGIN);self.additional.append(o)
        self.drills.append({"id":o["id"],"xyMm":p,"radiusMm":HOLE_DIAMETER/2})
        bo={**o,"via":True,"clear":offset(o["paths"],CLR+M["MARGIN"]),"viaClear":offset(o["paths"],.06+M["MARGIN"])}
        self.board.new.append(bo)


def main():
    b=M["Board"]();b.route_power_fill_exceptions=POWER_FILL_EXCEPTION;six=AllLayers(b)
    prior=json.loads((HERE/"bottom-bucket-routing-manifest.json").read_text())
    results=[]
    for r in prior["channels"]:
        if "signalRoute" in r:
            results.append(r);b.accept(r)
    failures=[r["net"] for r in prior["channels"] if "signalRoute" not in r]
    # Tap from original inner route for the six remaining filters.
    for net in failures:
        ch=next(c for c in b.inv if c["net"]==net)
        taps=six.taps(ch)
        if not taps and net=="ADC1_INP0":
            # Its near-MCU existing route is BOTTOM, not Inner3. This pass only
            # checks available BOTTOM tap points; a bridge is separate work.
            taps=six.taps(ch,2)
        r=b.search(ch,limit=12,tap_sources=taps) if taps else {"ref":next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")),"net":net,"status":"NO_SIX_LAYER_TAP_FOUND"}
        results.append(r)
        if "signalRoute" in r:b.accept(r);six.accept(r)
        (HERE/"bottom-bucket-tap-progress.json").write_text(json.dumps({"sourceSha256":M["EXPECTED_SHA"],"channels":results},indent=2)+"\n",encoding="utf8")
        M["render"](b,results,HERE/"bottom-bucket-tap-progress.png")
    report={"schema":"adc10-bottom-bucket-tap-routing-20261018-v1","readOnly":True,"nativeCallsPerformed":False,"sourcePath":str(SOURCE),"sourceSha256":M["EXPECTED_SHA"],"clearanceMm":CLR,"traceWidthMm":WIDTH,"viaDiameterMm":VIA_DIAMETER,"viaHoleMm":HOLE_DIAMETER,"minimumHoleEdgeClearanceMm":HOLE_EDGE_CLEARANCE,"additionalDrills":len(six.additional),"original634ViasAnd793DrillsUntouched":True,"channels":results,"status":"OFFLINE_DATA_MANIFEST_REQUIRES_GND_CUT_UNION_AND_NATIVE_DRC","manufacturingReady":False}
    (HERE/"bottom-bucket-tap-manifest.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"solved":sum("signalRoute" in r for r in results),"total":len(results),"newVias":len(six.additional)}),flush=True)


if __name__=="__main__":main()
