"""Offline bounded Inner3 ADC branches with all-six-layer-clear signal vias."""
import heapq
import json
import math
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
T=runpy.run_path(str(HERE/"plan-tap-vias.py"));M=T["M"]
globals().update({k:M[k] for k in ["ROOT","MM","CLR","WIDTH","GRID","W","H","SCALE","np","pc","capsule","circle","rectangle","offset","union","inter","paths_bbox","overlap","world_to_grid","grid_to_world","raster"]})


def local_route_seeds(six,ch,layer=17,need_via=False):
    net=ch["net"];vp=ch["nearestAdcEscapeVia"]["xyMm"]
    lines=[l for l in ch["existingAdcLines"] if l["layer"]==layer]
    key=lambda p:tuple(round(x,5) for x in p)
    graph={}
    for l in lines:
        a,z=key(l["startMm"]),key(l["endMm"]);dl=math.dist(a,z)
        graph.setdefault(a,[]).append((z,dl));graph.setdefault(z,[]).append((a,dl))
    if not graph:return []
    start=min(graph,key=lambda p:math.dist(p,vp));dists={start:math.dist(start,vp)};heap=[(dists[start],start)]
    while heap:
        d,a=heapq.heappop(heap)
        if d>dists[a]+1e-9:continue
        for z,dl in graph[a]:
            nd=d+dl
            if nd<dists.get(z,math.inf):dists[z]=nd;heapq.heappush(heap,(nd,z))
    out=[];seen=set()
    for l in lines:
        a,z=l["startMm"],l["endMm"];length=math.dist(a,z);steps=max(1,math.ceil(length/.04))
        for j in range(steps+1):
            t=j/steps;p=(a[0]+(z[0]-a[0])*t,a[1]+(z[1]-a[1])*t)
            if math.dist(p,vp)>8 or not(44.5<p[0]<62.5 and 74.5<p[1]<90.5):continue
            k=key(p)
            if k in seen:continue
            seen.add(k)
            if need_via and not six.viable(p,net):continue
            along=min(dists.get(key(a),math.inf)+length*t,dists.get(key(z),math.inf)+length*(1-t))
            out.append({"xyMm":p,"touchExistingLineId":l["id"],"touchExistingLineLayer":layer,"electricalDistanceFromEscapeMm":along,"needsFirstTapVia":need_via})
    return out


class InnerRouter:
    def __init__(self,six,layer=17):self.six=six;self.board=six.board;self.layer=layer
    def objects(self,net):
        return [o for o in self.six.obs+self.six.additional if self.layer in o["layers"] and o["net"]!=net and not(o["kind"]=="FILL" and o["net"] in T["POWER_FILL_EXCEPTION"])]
    def blocked(self,net):return raster(union([p for o in self.objects(net) for p in offset(o["paths"],CLR+.004+WIDTH/2)]))
    def via_blocked(self,net):
        paths=[]
        for o in self.six.obs+self.six.additional:
            if o["net"]==net or (o["kind"]=="FILL" and o["net"] in T["POWER_FILL_EXCEPTION"]):continue
            paths.extend(offset(o["paths"],CLR+T["VIA_MARGIN"]+T["VIA_DIAMETER"]/2))
        for o in self.board.new:
            if o["net"]!=net:paths.extend(offset(o["paths"],CLR+T["VIA_MARGIN"]+T["VIA_DIAMETER"]/2))
        for d in self.six.drills:paths.append(circle(d["xyMm"],d["radiusMm"]+T["HOLE_DIAMETER"]/2+T["HOLE_EDGE_CLEARANCE"]+T["VIA_MARGIN"]))
        return raster(union(paths))
    def route_hits(self,q,net):
        land=capsule(q,WIDTH/2);bb=paths_bbox(land)
        for o in self.objects(net):
            if overlap(bb,o["bbox"],CLR+.004) and inter(land,offset(o["paths"],CLR+.004)):return True
        return False
    def simplify(self,q,net):
        out=[q[0]];i=0
        while i<len(q)-1:
            for j in range(len(q)-1,i,-1):
                if not self.route_hits([q[i],q[j]],net):break
            out.append(q[j]);i=j
        return out
    def alternatives(self,ch):
        net=ch["net"];vp=ch["nearestAdcEscapeVia"]["xyMm"]
        if self.layer!=17:seeds=[{"xyMm":vp,"electricalDistanceFromEscapeMm":0,"touchExistingViaId":ch["nearestAdcEscapeVia"]["id"],"touchExistingLineId":None,"touchExistingLineLayer":self.layer}]
        else:
            seeds=local_route_seeds(self.six,ch,17)
            if not seeds:seeds=local_route_seeds(self.six,ch,2,True)
        if not seeds:return []
        print(json.dumps({"stage":"inner3_masks","net":net,"seedCount":len(seeds)}),flush=True)
        blocked=self.blocked(net);vb=self.via_blocked(net)
        dist=np.full((H,W),np.inf,dtype=np.float32);prev=np.full((H,W),-1,dtype=np.int8);root=np.full((H,W),-1,dtype=np.int16)
        moves=[(1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(-1,-1),(1,-1)];heap=[]
        for si,s in enumerate(seeds):
            sx,sy=world_to_grid(s["xyMm"])
            for y in range(sy-1,sy+2):
                for x in range(sx-1,sx+2):
                    if not(1<=x<W-1 and 1<=y<H-1) or blocked[y,x]:continue
                    p=grid_to_world(x,y)
                    if self.route_hits([s["xyMm"],p],net):continue
                    d=math.dist(p,s["xyMm"])+s["electricalDistanceFromEscapeMm"]*.12
                    if d<dist[y,x]:dist[y,x]=d;prev[y,x]=8;root[y,x]=si;heapq.heappush(heap,(d,x,y))
        raw=[];visited=0
        while heap:
            d,x,y=heapq.heappop(heap)
            if d>dist[y,x]+1e-6:continue
            if d>6.5:break
            visited+=1
            if x%2==0 and y%2==0 and not vb[y,x]:
                s=seeds[int(root[y,x])];p=grid_to_world(x,y)
                if math.dist(p,s["xyMm"])>.25 and math.dist(p,vp)<7:
                    raw.append((d+.04*math.dist(p,vp),x,y))
            for di,(dx,dy) in enumerate(moves):
                nx,ny=x+dx,y+dy
                if not(1<=nx<W-1 and 1<=ny<H-1) or blocked[ny,nx] or (dx and dy and (blocked[y,nx] or blocked[ny,x])):continue
                nd=d+GRID*(math.sqrt(2) if dx and dy else 1)
                if nd<dist[ny,nx]-1e-6:dist[ny,nx]=nd;prev[ny,nx]=di;root[ny,nx]=root[y,x];heapq.heappush(heap,(nd,nx,ny))
        print(json.dumps({"stage":"inner3_raw_done","net":net,"visited":visited,"rawViaSites":len(raw)}),flush=True)
        raw.sort();out=[];used_sites=[]
        for _,x,y in raw:
            p=grid_to_world(x,y)
            if any(math.dist(p,q)<.12 for q in used_sites):continue
            if not self.six.viable(p,net):continue
            q=[];cx,cy=x,y
            while prev[cy,cx]!=8:
                q.append(grid_to_world(cx,cy));di=int(prev[cy,cx]);dx,dy=moves[di];cx-=dx;cy-=dy
            s=seeds[int(root[cy,cx])]
            q.extend([grid_to_world(cx,cy),s["xyMm"]]);q.reverse();q=self.simplify(q,net)
            if self.route_hits(q,net):continue
            if s.get("needsFirstTapVia") and math.dist(p,s["xyMm"])<T["HOLE_DIAMETER"]+T["HOLE_EDGE_CLEARANCE"]+T["VIA_MARGIN"]:continue
            bl=sum(math.dist(a,z) for a,z in zip(q,q[1:]));along=s["electricalDistanceFromEscapeMm"]+bl
            record={"kind":"NEW_ADC_TAP_VIA","xyMm":p,"net":net,"diameterMm":T["VIA_DIAMETER"],"holeMm":T["HOLE_DIAMETER"],"layers":T["LAYERS"],"touchExistingLineId":s["touchExistingLineId"],"touchExistingViaId":s.get("touchExistingViaId"),"touchExistingLineLayer":s["touchExistingLineLayer"],"branchStartXYmm":s["xyMm"],"electricalDistanceFromEscapeMm":along,"branchLengthMm":bl,"innerBranchRoute":{"layerId":self.layer,"widthMm":WIDTH,"pointsMm":q,"lengthMm":bl},"penaltyMm":.10*along}
            if s.get("needsFirstTapVia"):record["firstTapVia"]={"xyMm":s["xyMm"],"net":net,"diameterMm":T["VIA_DIAMETER"],"holeMm":T["HOLE_DIAMETER"],"layers":T["LAYERS"],"touchExistingLineId":s["touchExistingLineId"],"touchExistingLineLayer":2}
            out.append(record);used_sites.append(p)
            if len(out)>=220:break
        print(json.dumps({"stage":"inner3_exact_done","net":net,"branchViaAlternatives":len(out)}),flush=True)
        (HERE/("branch-alternatives-layer"+str(self.layer)+"-"+net+".json")).write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
        return out


def main():
    b=M["Board"]();b.route_power_fill_exceptions=T["POWER_FILL_EXCEPTION"]
    six=T["AllLayers"](b);ir=InnerRouter(six)
    prior=json.loads((HERE/"bottom-bucket-routing-manifest.json").read_text());results=[]
    for r in prior["channels"]:
        if "signalRoute" not in r:continue
        p=r["centerXYmm"];ax=r["axisOfPositiveLocalX"];h=(.95,.5) if ax[0] else (.5,.95)
        r["assemblyBoundingBoxMm"]=[p[0]-h[0],p[1]-h[1],p[0]+h[0],p[1]+h[1]]
        assert b.body_clear(r["assemblyBoundingBoxMm"]),r["ref"]
        results.append(r);b.accept(r)
    # The very few free one-tap C93 sites are reserved before C94.
    order=["ADC3_INP2","ADC3_INP7","ADC2_INP12","ADC3_INP6","ADC1_INP16","ADC1_INP0"]
    for net in order:
        ch=next(c for c in b.inv if c["net"]==net)
        taps=ir.alternatives(ch)
        r=b.search(ch,limit=12,tap_sources=taps) if taps else {"ref":next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")),"net":net,"status":"NO_BOUNDED_BRANCH_ALTERNATIVE"}
        if "signalRoute" in r:
            s=r["selectedRoutingSource"];r["additionalSignalRoutes"]=[s["innerBranchRoute"]]
            r["newSignalVias"]=[s]+([s["firstTapVia"]] if "firstTapVia" in s else [])
            r["electricalEscapeToCapPathMm"]=s["electricalDistanceFromEscapeMm"]+r["signalRoute"]["lengthMm"]
            b.accept(r);six.accept(r)
            for route in r["additionalSignalRoutes"]:
                o={"id":"BRANCH:"+r["ref"],"kind":"NEW_LINE","net":net,"layers":[17],"paths":capsule(route["pointsMm"],WIDTH/2)};o["bbox"]=paths_bbox(o["paths"]);o["viaBlocked"]=offset(o["paths"],CLR+T["VIA_MARGIN"]);six.additional.append(o)
            if "firstTapVia" in s:
                first=s["firstTapVia"];dummy={"ref":r["ref"]+":FIRST","net":net,"selectedRoutingSource":{**first,"kind":"NEW_ADC_TAP_VIA"}};six.accept(dummy)
        results.append(r)
        report={"schema":"adc10-bottom-complete-branches-20261018-v1","sourceSha256":M["EXPECTED_SHA"],"channels":results,"legacyBottomAssemblyEnvelopes":b.legacy_bottom_envelopes,"allOriginalCopperAndDrillsUnchanged":True,"additionalDrills":sum(len(r.get("newSignalVias",[])) for r in results),"status":"OFFLINE_ONLY_PENDING_LOCAL_FILL_REPAIR_AND_NATIVE_DRC","manufacturingReady":False}
        (HERE/"bottom-bucket-branches-manifest.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
        M["render"](b,results,HERE/"bottom-bucket-branches-progress.png")
    print(json.dumps({"solved":sum("signalRoute" in r for r in results),"total":len(results),"additionalDrills":sum(len(r.get("newSignalVias",[])) for r in results)}),flush=True)


if __name__=="__main__":main()
