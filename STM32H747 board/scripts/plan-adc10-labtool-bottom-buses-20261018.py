"""Offline BOTTOMsupply/offset/feed route draft, preserving existing copper."""
import json,hashlib,math,heapq,runpy,argparse
from pathlib import Path
from collections import defaultdict
import numpy as np
from shapely.geometry import Point,LineString,Polygon,box
from shapely.affinity import scale
from shapely.ops import unary_union
from shapely import intersects_xy
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018/routing"
M=runpy.run_path(str(HERE.parent/"independent-pcb-placement-proposal.py"))
G=M["G"];MM=.0254;CLR=.17
SOURCE=ROOT/"output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru"
PORTS=HERE/"six-layer-via-port-candidates-commonpower-v4.json"
CHECK=M["CHECK"]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    global CLR
    ap=argparse.ArgumentParser();ap.add_argument("--layer",type=int,default=2);ap.add_argument("--negative-only",action="store_true");ap.add_argument("--ports",type=Path,default=PORTS);ap.add_argument("--query",type=Path);ap.add_argument("--tag",default="query");ap.add_argument("--extra-copper",type=Path,action="append",default=[]);ap.add_argument("--placement",type=Path);ap.add_argument("--clearance",type=float,default=.17);ap.add_argument("--grid",type=float,default=.10);args=ap.parse_args();layer=args.layer;CLR=args.clearance
    assert CLR>=.1535 and args.grid>=.025
    assert layer in (1,2,15,16,17,18)
    rows=M["parse"](SOURCE);attrs=M["attrs_of"](rows);docs,_=M["READ"](CHECK)
    proposed={p['ref']:p for p in json.loads(args.placement.read_text(encoding='utf8'))['edits']} if args.placement else {}
    ports=json.loads(args.ports.read_text(encoding="utf8"));assert not ports["failedPorts"]
    padnets={}
    for (k,r),b in rows.items():
        if k=="PAD_NET":p=json.loads(r);padnets[p[1],str(p[2])]=b["padNet"]
    obstacles=[];groundfills=[];invalid=[]
    def add(key,net,s):obstacles.append({"key":key,"net":(net or "").casefold(),"shape":s})
    source=None
    for (k,rid),b in rows.items():
        if k=="COMPONENT":
            if b["layerId"]!=2 and attrs[rid].get("Designator") not in {"CN1"}:
                # SMDtopneverappearsontheBottom; THpadsstilldo.
                pass
            for (pk,pi),(ph,p) in docs["FOOTPRINT",attrs[rid]["Footprint"]].items():
                if pk!="PAD" or ((b["layerId"]!=layer or layer not in (1,2)) and p["layerId"]!=12):continue
                s=M["local_pad"](p)
                if b["layerId"]==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                pp=proposed.get(attrs[rid].get('Designator'))
                s=M["world"](s,pp['xyMm'] if pp else (b["x"]*MM,b["y"]*MM),pp['angle'] if pp else b["angle"])
                net=padnets.get((rid,str(p["num"])),"")
                ref=attrs[rid]["Designator"]
                add("PAD:"+ref+":"+str(p["num"]),net,s)
                if ref=="CN1" and str(p["num"])=="1":source=(s.centroid.x,s.centroid.y);assert net=="+5V"
        elif k=="VIA":add("VIA:"+rid,b["netName"],Point(b["centerX"]*MM,b["centerY"]*MM).buffer(b["viaDiameter"]*MM/2,resolution=32))
        elif k in ("LINE","ARC") and b.get("layerId") in (layer,11):
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            pts=G["arc"](a,z,b["angle"]) if k=="ARC" else [a,z]
            add(k+":"+rid,b.get("netName") if b["layerId"]==layer else "MECHANICAL_OUTLINE",LineString(pts).buffer(b.get("width",0)*MM/2+(.131 if b["layerId"]==11 else 0),resolution=12))
        elif k=="POLY" and b.get("layerId")==layer:add(k+":"+rid,b.get("netName"),LineString(G["ring_path"](b["path"])).buffer(b["width"]*MM/2,resolution=12))
        elif k=="PAD" and b.get("hole"):
            hole=b["hole"];w=hole.get("width",0)*MM;h=hole.get("height",0)*MM
            if max(w,h)>0:add("MECHANICAL_HOLE:"+rid,"MECHANICAL_HOLE",M["world"](box(-w/2,-h/2,w/2,h/2),(b["centerX"]*MM,b["centerY"]*MM),b.get("padAngle",0)).buffer(.131,resolution=16))
        elif k=="FILL" and b.get("layerId")==layer:
            if b["path"][0][0]=="CIRCLE":
                p=b["path"][0];s=Point(p[1]*MM,p[2]*MM).buffer(p[3]*MM,resolution=64)
            else:
                rings=[G["ring_path"](p) for p in b["path"]];s=Polygon(rings[0],rings[1:])
            if not s.is_valid:invalid.append(rid);continue
            if b.get("netName")=="GND":groundfills.append((rid,s))
            else:add(k+":"+rid,b.get("netName"),s)
    assert source
    byport={p["key"]:p for p in ports["viasProposed"]}
    for p in ports["viasProposed"]:add("NEWVIA:"+p["key"],p["net"],Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=32))
    raw_path=HERE/"independent-raw5-bilayer-route-v2-shortvia.json"
    raw=json.loads(raw_path.read_text(encoding="utf8"))
    for p in raw["newLineCreates"]:
        if p["layerId"]==layer:add(p["key"],p["net"],LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2,resolution=16))
    for p in raw["newViaCreates"]:add(p["key"],p["net"],Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=32))
    for ep in args.extra_copper:
        er=json.loads(ep.read_text(encoding="utf8"))
        for p in er.get("newLineCreates",[]):
            if p["layerId"]==layer:add(p["key"],p["net"],LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2,resolution=16))
        for p in er.get("newViaCreates",[]):add(p["key"],p["net"],Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=32))
    lines=[];connections=[];failed=[]
    def path(net,a,z,width,bounds):
        region=box(*bounds).buffer(1)
        obs=[o for o in obstacles if o["net"]!=net.casefold() and o["shape"].intersects(region)]
        blocked=unary_union([o["shape"].buffer(CLR+width/2+.003,resolution=16) for o in obs])
        if Point(a).intersects(blocked) or Point(z).intersects(blocked):return None,{"reason":"ENDPOINT_CONFLICT","conflicts":[o["key"] for o in obs if Point(a).distance(o["shape"])<CLR+width/2 or Point(z).distance(o["shape"])<CLR+width/2]}
        if not LineString([a,z]).intersects(blocked):return [a,z],None
        grid=args.grid;x0,y0,x1,y1=bounds;nx=round((x1-x0)/grid)+1;ny=round((y1-y0)/grid)+1
        xs=x0+np.arange(nx)*grid;ys=y0+np.arange(ny)*grid;xx,yy=np.meshgrid(xs,ys)
        mask=intersects_xy(blocked.buffer(grid*.708,resolution=4),xx.ravel(),yy.ravel()).reshape((ny,nx))
        def enter(p):
            ix=round((p[0]-x0)/grid);iy=round((p[1]-y0)/grid);out=[]
            for dx in range(-6,7):
                for dy in range(-6,7):
                    x,y=ix+dx,iy+dy
                    if 0<=x<nx and 0<=y<ny and not mask[y,x]:
                        q=(float(xs[x]),float(ys[y]))
                        if not LineString([p,q]).intersects(blocked):out.append((math.dist(p,q),(x,y)))
            return [v for d,v in sorted(out)[:12]]
        starts=enter(a);goals=set(enter(z))
        if not starts or not goals:return None,{"reason":"NO_GRID_ENTRY"}
        costs={v:math.dist(a,(xs[v[0]],ys[v[1]])) for v in starts};prev={v:None for v in starts};queue=[]
        for v,c in costs.items():heapq.heappush(queue,(c+math.dist((xs[v[0]],ys[v[1]]),z),c,v))
        dirs=[(x,y,math.hypot(x,y)*grid) for x,y in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1))]
        hit=None;visits=0
        while queue:
            _,cost,v=heapq.heappop(queue)
            if cost>costs[v]+1e-10:continue
            if v in goals:hit=v;break
            visits+=1
            for dx,dy,d in dirs:
                q=v[0]+dx,v[1]+dy
                if not(0<=q[0]<nx and 0<=q[1]<ny) or mask[q[1],q[0]]:continue
                nc=cost+d
                if nc>=costs.get(q,math.inf):continue
                costs[q]=nc;prev[q]=v;heapq.heappush(queue,(nc+math.dist((xs[q[0]],ys[q[1]]),z),nc,q))
        if hit is None:return None,{"reason":"NO_BOTTOM_PATH","visited":visits}
        chain=[]
        while hit is not None:chain.append((float(xs[hit[0]]),float(ys[hit[1]])));hit=prev[hit]
        pts=[a]+list(reversed(chain))+[z];out=[a];i=0
        while i<len(pts)-1:
            j=len(pts)-1
            while j>i+1 and LineString([pts[i],pts[j]]).intersects(blocked):j-=1
            if LineString([pts[i],pts[j]]).intersects(blocked):return None,{"reason":"EXACT_SEGMENT_FAILURE"}
            out.append(pts[j]);i=j
        return out,None
    def group(net,terminals,width,bounds,role):
        connected=[tuple(terminals[0])];remaining=[tuple(v) for v in terminals[1:]]
        while remaining:
            d,a,z=min((math.dist(a,z),a,z) for a in connected for z in remaining)
            pts,err=path(net,a,z,width,bounds)
            if err:failed.append({"net":net,"fromXYmm":a,"toXYmm":z,"role":role,**err});remaining.remove(z);continue
            keys=[]
            for a,b in zip(pts,pts[1:]):
                if math.dist(a,b)<1e-8:continue
                key=f"LABTOOL_{args.tag.upper()}_{len(lines)+1:04}" if args.query else f"LABTOOL_BOTTOM_{len(lines)+1:04}"
                lines.append({"key":key,"net":net,"layerId":layer,"widthMm":width,"startXYmm":a,"endXYmm":b,"role":role})
                add(key,net,LineString([a,b]).buffer(width/2,resolution=16));keys.append(key)
            connections.append({"net":net,"role":role,"lineKeys":keys,"lengthMm":sum(math.dist(a,b) for a,b in zip(pts,pts[1:]))})
            connected.extend(pts[1:]);remaining.remove(z)
        print(json.dumps({"phase":role,"lines":len(lines),"failed":len(failed)}),flush=True)
    if args.query:
        for q in json.loads(args.query.read_text(encoding="utf8"))["queries"]:group(q["net"],q["terminalsXYmm"],q.get("widthMm",.2032),q["boundsMm"],q["role"])
    elif args.negative_only:
        group("-3V_AFE",[byport[k]["xyMm"] for k in ["MINUS_AFE_COMMON_PORT","AFE_MINUS_PORT_J9"]],.25,(8.4,8.2,43.5,43.5),"FilterednegativeDCfeedonexistinginnerSIGNALlayer")
    else:
        group("+5V_AFE",[byport[k]["xyMm"] for k in [f"AFE_PLUS_PORT_J{i}" for i in range(11,1,-1)]],.25,(8.4,8.2,43.5,143.5),"FilteredpositiveBottomchanneltrunk;sourcefeedseparateTOPbridge")
        group("-3V_AFE",[byport[k]["xyMm"] for k in [f"AFE_MINUS_PORT_J{i}" for i in range(11,1,-1)]],.25,(8.4,8.2,43.5,143.5),"FilterednegativeBottomchanneltrunk;sourcefeedseparateTOPbridge")
        group("-3V_AFE",[byport[k]["xyMm"] for k in ["MINUS_AFE_LEFT_ENTRY_PORT","AFE_MINUS_PORT_J10"]],.25,(8.4,19.5,15.0,26.0),"NegativeextrasourceporttoBottomchanneltrunk")
        group("AFE_OFFSET_FILTER",[byport[k]["xyMm"] for k in ["OFFSET_FILTER_LEFT_PORT","OFFSET_FILTER_RIGHT_PORT"]],.2032,(16.5,63.0,33.5,73.5),"ShortshieldedBottomoffsetdividerLPFbridge")
        group("ADC_OFFSET_0V97",[byport[k]["xyMm"] for k in ["OFFSET_OUTPUT_PORT","OFFSET_J7_PLUS_PORT","OFFSET_J6_PLUS_PORT","OFFSET_LOWER_BUS_PORT","OFFSET_UPPER_BUS_PORT"]],.25,(15.5,59.5,33.5,89.5),"QuietoffsetcentralBottombridge;bucketjoinsupperbusonTOP")
    conflicts=[]
    for p in lines:
        probe=LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2+CLR,resolution=16)
        for o in obstacles:
            if o["key"]!=p["key"] and o["net"]!=p["net"].casefold() and probe.intersects(o["shape"]):conflicts.append({"lineKey":p["key"],"net":p["net"],"obstacle":o["key"],"obstacleNet":o["net"]})
    report={"schema":"adc10-labtool-bottom-bus-draft-20261018-v1","sourceSha256":sha(SOURCE),"portsPath":str(PORTS),"portsSha256":sha(PORTS),"readOnly":True,"nativeCalls":0,"newLineCreates":lines,"connections":connections,"failedConnections":failed,"literalCopperConflicts":conflicts,"existingRawSource":{"ref":"CN1","pin":"1","net":"+5V","xyMm":source},"existingInvalidBottomFillsNotSilentlyRepaired":invalid,"requiresLocalGroundFillVoids":True,"clearanceMm":CLR,"existingViaChanges":0,"existingDrillChanges":0,"manufacturingReady":False,"limitations":["NoGND FILLpathwrites;authoritativepreserving-splithelpermustsubtracteachtracewith.17mmclearance.","AllnewVIAantipadsandTOPstubconnectivityareseparaterequiredphases.","FullnativeDRC/sourceauditmustfollow,includingpreservingall799existingdrills/6layers/18rules."]}
    target=HERE/(f"query-{args.tag}-layer{layer}.json" if args.query else (f"inner{layer}-negative-feed-v4-draft.json" if args.negative_only else "bottom-rails-offset-v5-finalcandidate.json"))
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(target),"lines":len(lines),"failed":len(failed),"conflicts":len(conflicts)}),flush=True)


if __name__=="__main__":main()
