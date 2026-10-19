"""Offline exact old-copper isolation and candidate local ADC routing review.

Never imports an EDA connection or modifies native source/checkpoints.
"""
import copy
import hashlib
import json
import math
import runpy
import heapq
import argparse
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from shapely.geometry import Point, Polygon, LineString, box
from shapely.affinity import rotate, translate
from shapely.ops import unary_union
from shapely import intersects_xy
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "output/candidates/adc10-labtool-20261018/routing"
SOURCE = ROOT / "output/validation/native-adc10-pcb-labtool_before-20261018.epru"
PLACEMENT = HERE.parent / "independent-pcb-placement-proposal.json"
PLAN = HERE.parent / "schematic-plan.json"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2"
M = runpy.run_path(str(ROOT / "scripts/build-adc10-strip-operations-20261018.py"))
G = M["G"]
READ = runpy.run_path(str(ROOT / "output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]
MM = .0254
CLR = .1535


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def turn(p, angle):
    t=math.radians(angle)
    return (p[0]*math.cos(t)-p[1]*math.sin(t),p[0]*math.sin(t)+p[1]*math.cos(t))
def rect(center,w,h,angle=0):
    return [(center[0]+v[0],center[1]+v[1]) for v in (turn(p,angle) for p in ((-w/2,-h/2),(w/2,-h/2),(w/2,h/2),(-w/2,h/2)))]


def local_routes(original,attrs,refs,netpads,isolation,placement_path=None,tag="initial",ports_path=None,common_top_path=None,extra_copper_paths=None):
    """Plan TOP-only row wiring. Failed routes remain literal failures."""
    placement_path=placement_path or PLACEMENT
    placement=json.loads(placement_path.read_text(encoding="utf8"))
    plan=json.loads(PLAN.read_text(encoding="utf8"))
    contract=plan["allPinContracts"]
    pp={p["ref"]:p for p in placement["edits"]}
    docs,_=READ(CHECKPOINT)
    rows=copy.deepcopy(original)
    for op in isolation["operations"]:
        key=op["type"],op["id"]
        assert rows[key]==op["beforeBody"]
        if op["action"]=="delete":del rows[key]
        else:rows[key]=copy.deepcopy(op["afterBody"])
    pads={}
    obstacles=[]
    invalid=[]
    def add(key,net,shape,layer=1):
        if not shape.is_empty:obstacles.append({"key":key,"net":(net or "").casefold(),"shape":shape,"layerId":layer})
    for (kind,cid),b in rows.items():
        if kind!="COMPONENT":continue
        ref=attrs[cid]["Designator"]
        if ref in pp:continue
        for (k,pid),(ph,p) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            if k!="PAD" or p.get("layerId") not in (1,12):continue
            if b["layerId"]!=1 and p.get("layerId")!=12:continue
            d=p["defaultPad"]
            if d.get("padType")=="POLYGON":shape=Polygon(G["ring_path"](d["path"]))
            else:
                if "width" in d:shape=box(-d["width"]*MM/2,-d["height"]*MM/2,d["width"]*MM/2,d["height"]*MM/2)
                else:shape=Point(0,0).buffer(d["diameter"]*MM/2,resolution=24)
                shape=translate(rotate(shape,p.get("padAngle",0),origin=(0,0)),p["centerX"]*MM,p["centerY"]*MM)
            shape=translate(rotate(shape,b["angle"],origin=(0,0)),b["x"]*MM,b["y"]*MM)
            pn=str(p["num"])
            net=contract.get(ref,{}).get(pn,netpads.get((cid,pn),""))
            pads.setdefault(ref,{})[pn]={"xy":(shape.centroid.x,shape.centroid.y),"net":net,"shape":shape}
            add(f"PAD:{ref}:{pn}",net,shape)
    for ref,p in pp.items():
        for pad in p["pads"]:
            num=pad["number"];shape=box(*pad["boundsMm"]);net=contract[ref].get(num)
            pads.setdefault(ref,{})[num]={"xy":tuple(pad["centerMm"]),"net":net,"shape":shape}
            add(f"PAD:{ref}:{num}",net,shape)
    gndfills=[]
    for (kind,rid),b in rows.items():
        net=b.get("netName","")
        if kind=="VIA":add("VIA:"+rid,net,Point(b["centerX"]*MM,b["centerY"]*MM).buffer(b["viaDiameter"]*MM/2,resolution=24))
        elif kind in ("LINE","ARC") and b.get("layerId")==1:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            points=G["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            add(kind+":"+rid,net,LineString(points).buffer(b["width"]*MM/2,resolution=8))
        elif kind=="FILL" and b.get("layerId")==1:
            rings=[G["ring_path"](r) for r in b["path"]];shape=Polygon(rings[0],rings[1:])
            if not shape.is_valid:
                invalid.append({"id":rid,"net":net})
                if net!="GND":add("INVALID_FILL_ENVELOPE:"+rid,net,shape.envelope)
                continue
            if net=="GND":gndfills.append((rid,shape))
            else:add("FILL:"+rid,net,shape)
        elif kind=="POLY" and b.get("layerId")==1:
            points=G["ring_path"](b["path"])
            add("POLY:"+rid,net,LineString(points).buffer(b["width"]*MM/2,resolution=8))
    ports=json.loads(ports_path.read_text(encoding="utf8"))["viasProposed"] if ports_path else []
    for port in ports:
        point=tuple(port["xyMm"]);shape=Point(point).buffer(port["viaDiameterMm"]/2,resolution=32)
        pads[port["key"]]={"1":{"xy":point,"net":port["net"],"shape":shape}}
        add("NEWVIA:"+port["key"],port["net"],shape)
    if common_top_path:
        common_top=json.loads(common_top_path.read_text(encoding="utf8"))
        for line in common_top["newLineCreates"]:add(line["key"],line["net"],LineString([line["startXYmm"],line["endXYmm"]]).buffer(line["widthMm"]/2,resolution=16))
    for ep in extra_copper_paths or []:
        external=json.loads(ep.read_text(encoding="utf8"))
        for line in external.get("newLineCreates",[]):
            if line["layerId"]==1:add(line["key"],line["net"],LineString([line["startXYmm"],line["endXYmm"]]).buffer(line["widthMm"]/2,resolution=16))
        for via in external.get("newViaCreates",[]):add(via["key"],via["net"],Point(via["xyMm"]).buffer(via["viaDiameterMm"]/2,resolution=32))
    newlines=[];fails=[];success=[]
    grid=.05;width=.2032
    def route(net,a,z,bounds,role):
        netfold=net.casefold()
        region=box(*bounds).buffer(.8)
        nearby=[o for o in obstacles if o["net"]!=netfold and o["shape"].intersects(region)]
        inflated=[o["shape"].buffer(CLR+width/2+.003,resolution=16) for o in nearby]
        blocked=unary_union(inflated)
        literal_conflicts=[]
        for p,tag in ((a,"start"),(z,"goal")):
            for o in nearby:
                if Point(p).distance(o["shape"]) < CLR+width/2:
                    literal_conflicts.append({"endpoint":tag,"obstacle":o["key"],"obstacleNet":o["net"]})
        if literal_conflicts:return None,{"reason":"ENDPOINT_CLEARANCE_CONFLICT","conflicts":literal_conflicts}
        if not LineString([a,z]).intersects(blocked):return [a,z],None
        x0,y0,x1,y1=bounds
        nx=int((x1-x0)/grid)+1;ny=int((y1-y0)/grid)+1
        xs=x0+np.arange(nx)*grid;ys=y0+np.arange(ny)*grid
        xx,yy=np.meshgrid(xs,ys)
        # A blocked-cell reserve guarantees diagonals never scrape a polygon
        # between point samples; final literal-segment test is independent.
        mask=intersects_xy(blocked.buffer(grid*.708,resolution=4),xx.ravel(),yy.ravel()).reshape((ny,nx))
        def neighbors(p):
            ix=round((p[0]-x0)/grid);iy=round((p[1]-y0)/grid)
            choices=[]
            for dy in range(-7,8):
                for dx in range(-7,8):
                    x,y=ix+dx,iy+dy
                    if not (0<=x<nx and 0<=y<ny) or mask[y,x]:continue
                    q=(float(xs[x]),float(ys[y]))
                    if not LineString([p,q]).intersects(blocked):choices.append((math.dist(p,q),(x,y)))
            return [v for d,v in sorted(choices)[:12]]
        starts=neighbors(a);goals=set(neighbors(z))
        if not starts or not goals:return None,{"reason":"NO_UNBLOCKED_GRID_ENTRY","startEntries":len(starts),"goalEntries":len(goals)}
        costs={v:math.dist(a,(xs[v[0]],ys[v[1]])) for v in starts};parents={v:None for v in starts};queue=[]
        for v,c in costs.items():heapq.heappush(queue,(c+math.dist((xs[v[0]],ys[v[1]]),z),c,v))
        dirs=[(dx,dy,math.hypot(dx,dy)*grid) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1))]
        hit=None;visited=0
        while queue:
            _,cost,v=heapq.heappop(queue)
            if cost>costs[v]+1e-10:continue
            if v in goals:hit=v;break
            visited+=1
            for dx,dy,extra in dirs:
                q=v[0]+dx,v[1]+dy
                if not (0<=q[0]<nx and 0<=q[1]<ny) or mask[q[1],q[0]]:continue
                nc=cost+extra
                if nc>=costs.get(q,math.inf):continue
                costs[q]=nc;parents[q]=v
                heapq.heappush(queue,(nc+math.dist((xs[q[0]],ys[q[1]]),z),nc,q))
        if hit is None:return None,{"reason":"NO_TOP_GRID_PATH","visited":visited,"obstacles":len(nearby)}
        chain=[]
        while hit is not None:chain.append((float(xs[hit[0]]),float(ys[hit[1]])));hit=parents[hit]
        pts=[a]+list(reversed(chain))+[z]
        # Greedy exact line-of-sight simplification; each final segment is
        # independently screened against literal inflated copper, not raster.
        sm=[pts[0]];idx=0
        while idx<len(pts)-1:
            end=len(pts)-1
            while end>idx+1 and LineString([pts[idx],pts[end]]).intersects(blocked):end-=1
            if LineString([pts[idx],pts[end]]).intersects(blocked):return None,{"reason":"EXACT_SEGMENT_FAILED"}
            sm.append(pts[end]);idx=end
        return sm,None
    def connect(net,terminals,bounds,role):
        terminals=[tuple(pads[r][pn]["xy"]) for r,pn in terminals]
        connected=[terminals.pop(0)]
        while terminals:
            distance,a,z=min((math.dist(a,z),a,z) for a in connected for z in terminals)
            path,error=route(net,a,z,bounds,role)
            if error:
                fails.append({"net":net,"role":role,"fromXYmm":a,"toXYmm":z,**error});terminals.remove(z);continue
            keys=[]
            for p,q in zip(path,path[1:]):
                if math.dist(p,q)<1e-8:continue
                key=f"LABTOOL_LOCAL_{len(newlines)+1:04}"
                newlines.append({"key":key,"net":net,"layerId":1,"startXYmm":p,"endXYmm":q,"widthMm":width,"role":role})
                add(key,net,LineString([p,q]).buffer(width/2,resolution=8));keys.append(key)
            success.append({"net":net,"role":role,"lengthMm":sum(math.dist(a,b) for a,b in zip(path,path[1:])),"lineKeys":keys})
            connected.extend(path[1:]);terminals.remove(z)
    pres=[97,98,99,106,107,108,109,110,111,112]
    for i,ch in enumerate(isolation["channels"]):
        row=ch["rowYmm"];j=i+2;b=((8.25 if tag=="initial" else (5.5 if ports else 6.3)),row-8.0,27.1,row+4.0)
        follower=f"U{20+i}";final=f"U{10+i}"
        definitions=[
            (ch["newBuffer"],[(follower,"1"),(follower,"4"),(ch["sumInputResistor"],"1")],"Follower shortfeedback and4k feed"),
            ("-3V_AFE",[(follower,"2"),(f"C{121+3*i}","1")],"Negative local follower bypass"),
            (ch["newFilter"],[(ch["inputResistor"],"2"),(f"C{pres[i]}","1"),(follower,"3")],"SMA lowpass to bipolar follower+"),
            (ch["newSum"],[(final,"4"),(ch["sumInputResistor"],"2"),(f"R{187+i}","1"),(f"C{122+3*i}","1")],"Final inverting summing node"),
            (ch["newDRV"],[(final,"1"),(f"R{187+i}","2"),(f"C{122+3*i}","2")],"FeedbackR/C to finalOUT; existing47R output stub preserved"),
            (ch["newRaw"],[(ch["inputResistor"],"1"),(f"R{177+i}","2")],"Groundreferenced SMA pulldown signal side"),
            ("+5V_AFE",[(follower,"5"),(f"C{120+3*i}","1")],"Positive local follower bypass"),
        ]
        for net,terminals,role in definitions:
            missing=[r for r,pn in terminals if r not in pads]
            if missing:fails.append({"net":net,"role":role,"reason":"PLACEMENT_MISSING","refs":missing});continue
            connect(net,terminals,b,role)
        print(json.dumps({"phase":"local-row","sma":ch["sma"],"lines":len(newlines),"unrouted":len(fails)}),flush=True)
    row_line_count=len(newlines)
    if ports:
        for i,ch in enumerate(isolation["channels"]):
            row=ch["rowYmm"];b=(5.5,row-8.0,27.1,row+4.0)
            connect("GND",[(f"C{121+3*i}","2"),(f"GND_NEGATIVE_BYPASS_J{i+2}","1")],b,"DedicatedshortnegativebypassGNDreturnto6layerVIA")
            connect("+5V_AFE",[(f"C{120+3*i}","1"),(f"AFE_PLUS_PORT_J{i+2}","1")],b,"ChannelpositivebypasstoBottomsupplyport")
            connect("-3V_AFE",[(f"C{121+3*i}","1"),(f"AFE_MINUS_PORT_J{i+2}","1")],b,"ChannelnegativebypasstoBottomsupplyport")
        connect("GND",[("C132","2"),("GND_POSITIVE_BYPASS_J6","1")],(12.5,78.5,16.5,82.5),"DedicatedJ6positivebypassGNDreturnto6layerVIA")
        connect("GND",[("R203","1"),("GND_OFFSET_DIVIDER","1")],(24.5,66.0,29.0,70.0),"DedicatedoffsetdividerGNDreturnto6layerVIA")
        print(json.dumps({"phase":"dedicatedGroundAndSupplyPorts","lines":len(newlines),"unrouted":len(fails)}),flush=True)
    local_supply_line_count=len(newlines)
    if ports and common_top_path:
        connect("+5V_AFE",[("PLUS_AFE_COMMON_PORT","1"),("AFE_PLUS_PORT_J11","1")],(5.5,6.5,47.5,89.5),"SharedpositiveTOPbridge toBottomchannelrail")
        connect("+5V_AFE",[("PLUS_AFE_COMMON_PORT","1"),("REF_PLUS_PORT","1")],(17.0,22.0,47.5,89.5),"SharedpositiveTOPfeed toreferenceRIGHTlanding")
        connect("+5V_AFE",[("REF_PLUS_PORT","1"),("C160","1"),("U32","5"),("U9","2"),("C103","1")],(17.1,59.5,32.5,89.5),"ReferenceRIGHTlandinglocalpositivebypasses")
        if "MINUS_AFE_LEFT_ENTRY_PORT" in pads:connect("-3V_AFE",[("MINUS_AFE_COMMON_PORT","1"),("MINUS_AFE_LEFT_ENTRY_PORT","1")],(5.5,6.5,47.5,89.5),"SharednegativeTOPbridge toextraportoutsideinputpocket")
        print(json.dumps({"phase":"sharedSupplyTOPbridges","lines":len(newlines),"unrouted":len(fails)}),flush=True)
    # Existing topoffsetbus is a protected same-net obstacle to the local
    # signals above. Search literal branches after those routes without moving
    # any protected route or silently using an unconnected plane.
    for i,ch in enumerate(isolation["channels"]):
        row=ch["rowYmm"]
        anchor=(25.7,row+4.35) if i==4 else (26.5,60.35 if i==5 else row+4.35)
        fake=f"OFFSET_BUS_{i}"
        pads[fake]={"1":{"xy":anchor,"net":"ADC_OFFSET_0V97","shape":Point(anchor).buffer(.3)}}
        if ports and i in (4,5):continue
        connect("ADC_OFFSET_0V97",[(f"U{10+i}","3"),(fake,"1")],(8.25,min(row-8.0,anchor[1]-.5),31.1,row+5.0),"Quiet offsetbus branch to finalOPA320+")
    print(json.dumps({"phase":"offsetbranches","lines":len(newlines),"unrouted":len(fails)}),flush=True)
    if ports:
        if "OFFSET_J6_PLUS_PORT" in pads:connect("ADC_OFFSET_0V97",[("U14","3"),("OFFSET_J6_PLUS_PORT","1")],(15.5,78.5,20.0,83.0),"J6quietoffsetBottombridgeport")
        connect("ADC_OFFSET_0V97",[("U15","3"),("OFFSET_J7_PLUS_PORT","1")],(15.5,64.5,20.0,68.5),"J7quietoffsetBottombridgeport")
        for terminals,role in (
            ([("R204","2"),("OFFSET_OUTPUT_PORT","1")],"IsolatedoffsetoutputtoBottombridgeport"),
            ([("C159","1"),("OFFSET_BUCKET_PORT","1")],"OffsetbuckettoBottombridgeport"),
            ([("OFFSET_BUS_4","1"),("OFFSET_UPPER_BUS_PORT","1")],"RetainedTOPupperbusBottombridgeport"),
            ([("OFFSET_BUS_5","1"),("OFFSET_LOWER_BUS_PORT","1")],"RetainedTOPlowerbusBottombridgeport"),
        ):connect("ADC_OFFSET_0V97",terminals,(16.0,59.5,32.5,89.5),role)
        connect("ADC_OFFSET_0V97",[("C159","1"),("OFFSET_BUS_4","1")],(23.0,80.5,32.5,89.5),"OffsetbucketTOPjointoupperconnectedbus")
    reference_defs=[
        ("AFE_OFFSET_BUFFER",[("U32","1"),("U32","4"),("R204","1")],"Offsetreference buffer shortfeedback"),
        ("AFE_REF_NR",[("U9","5"),("C105","1")],"REF5025noise-reductionbypass"),
        ("AFE_REF_ESR",[("R201","1"),("C104","1")],"REF5025ESR-controlledoutputbypass"),
        ("AFE_REF_2V5",[("U9","6"),("R201","2"),("R202","1")],"Precisionreferenceoutputdividerandbypass"),
        *(([("AFE_OFFSET_FILTER",[("U32","3"),("R203","2"),("OFFSET_FILTER_LEFT_PORT","1")],"Low-noiseoffsetbufferinputleftBottomport"),("AFE_OFFSET_FILTER",[("R202","2"),("C158","1"),("OFFSET_FILTER_RIGHT_PORT","1")],"Low-noisedividerLPFrightBottomport")]) if "OFFSET_FILTER_LEFT_PORT" in pads else [("AFE_OFFSET_FILTER",[("U32","3"),("C158","1"),("R202","2"),("R203","2")],"Low-noisedividerLPF tooffsetbuffer")]),
        *(([]) if ports else [("ADC_OFFSET_0V97",[("R204","2"),("C159","1"),("OFFSET_BUS_4","1"),("OFFSET_BUS_5","1")],"IsolatedoffsetoutputtoTOPtrunk; centraljog")]),
        *(([]) if common_top_path else [("+5V_AFE",[("U9","2"),("C103","1"),("U32","5"),("C160","1")],"Referenceislandlocalpositivepower")]),
    ]
    for net,terminals,role in reference_defs:
        missing=[r for r,pn in terminals if r not in pads]
        if missing:fails.append({"net":net,"role":role,"reason":"PLACEMENT_MISSING","refs":missing});continue
        connect(net,terminals,(17.1,59.5,32.5,89.5),role)
    print(json.dumps({"phase":"referenceisland","lines":len(newlines),"unrouted":len(fails)}),flush=True)
    conflicts=[]
    for line in newlines:
        shape=LineString([line["startXYmm"],line["endXYmm"]]).buffer(line["widthMm"]/2+CLR,resolution=8)
        for o in obstacles:
            if o["key"]==line["key"] or o["net"]==line["net"].casefold():continue
            if shape.intersects(o["shape"]):conflicts.append({"lineKey":line["key"],"net":line["net"],"obstacle":o["key"],"obstacleNet":o["net"]})
    report={"schema":"adc10-labtool-local-top-route-draft-20261018-v1","status":"INCOMPLETE_OFFLINE_DRAFT_NOT_APPLICABLE_AS_FINISHED_BOARD","sourceSha256":sha(SOURCE),"placementPath":str(placement_path),"placementSha256":sha(placement_path),"isolationManifestSha256":sha(HERE/"exact-old-copper-isolation-manifest.json"),"nativeCalls":0,"newLineCreates":newlines,"routedConnections":success,"unroutedConnections":fails,"exactLiteralCopperConflicts":conflicts,"clearanceMm":CLR,"gridStepMm":grid,"traceWidthMm":width,"invalidOriginalFills":invalid,"plannedVias":len(ports),"newViaCreates":ports,"portsPath":str(ports_path) if ports_path else None,"portsSha256":sha(ports_path) if ports_path else None,"rowCoreLineCount":row_line_count,"localGroundAndSupplyLineCount":local_supply_line_count,"preservedExistingVias":640,"remaining":["Offset bus branches to allOPA320+","Shared+5V_AFE/-3V_AFE trunks","Commonpump/LDO/referenceislandrouting","EveryGNDpadreturn verification and localstaticgroundvoidcut","NativeDRC and fullnetlist/sourcepreservation audit"],"manufacturingReady":False}
    target=HERE/("local-row-routing-draft.json" if tag=="initial" else f"local-row-routing-{tag}-draft.json")
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(target),"lines":len(newlines),"unrouted":len(fails),"conflicts":len(conflicts)}),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--placement",type=Path,default=PLACEMENT)
    parser.add_argument("--tag",default="initial")
    parser.add_argument("--ports",type=Path)
    parser.add_argument("--common-top",type=Path)
    parser.add_argument("--extra-copper",type=Path,action="append",default=[])
    args=parser.parse_args()
    assert sha(SOURCE)=="b540cccce8f7918785bd1bd021df1614419fe9290a9642e82aba02455ef540db"
    rows=G["PARSE"](SOURCE)
    attrs=defaultdict(dict)
    for (kind,rid),b in rows.items():
        if kind=="ATTR":attrs[b["parentId"]][b["key"]]=b.get("value")
    refs={v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    netpads={}
    for (kind,rid),b in rows.items():
        if kind=="PAD_NET":
            p=json.loads(rid);netpads[p[1],str(p[2])]=b["padNet"]
    nets=defaultdict(list)
    for key,b in rows.items():
        if b.get("netName"):nets[b["netName"]].append(key)
    netkeys_by_fold={n.casefold():keys for n,keys in nets.items()}
    summaries={}
    for n,keys in nets.items():
        if n.startswith("ADC"):
            summaries[n]={"counts":dict(Counter(k for k,i in keys)),"primitives":[{"type":k,"id":i,"body":rows[k,i]} for k,i in keys]}
    adc_refs=[f"J{i}" for i in range(2,12)]+[f"U{i}" for i in range(9,20)]+[f"R{i}" for i in range(137,173) if f"R{i}" in refs]+[f"C{i}" for i in range(97,120) if f"C{i}" in refs]
    components={r:{"id":refs[r],"body":rows["COMPONENT",refs[r]],"attrs":attrs[refs[r]],"pins":{p:n for (c,p),n in netpads.items() if c==refs[r]}} for r in adc_refs}
    HERE.mkdir(parents=True,exist_ok=True)
    (HERE/"baseline-copper-inventory.json").write_text(json.dumps({"sourceSha256":sha(SOURCE),"nets":summaries,"components":components},indent=2)+"\n",encoding="utf8")
    operations=[]
    def operation(key,action,newnet,reason):
        b=rows[key]
        after=copy.deepcopy(b)
        if newnet:after["netName"]=newnet
        operations.append({"type":key[0],"id":key[1],"action":action,"beforeBody":b,"beforeBodySha256":digest(b),"afterBody":after if action=="rename_net" else None,"allowedChangedFields":["netName"] if action=="rename_net" else [],"reason":reason})
    channels=[]
    rin=[137,138,139,149,150,151,161,162,163,164]
    ins=[140,142,144,152,154,156,165,167,169,171]
    outs=[141,143,145,153,155,157,166,168,170,172]
    for i in range(10):
        sma=f"J{i+2}"; oldraw=components[sma]["pins"]["1"]
        pre=components[f"R{ins[i]}"]["pins"]["2"]
        drv=components[f"R{outs[i]}"]["pins"]["1"]
        newraw=f"ADC_{sma}_RAW"; newdrv=f"ADC_{sma}_DRV"
        assert {k for k,rid in nets[pre]}=={"LINE"} and len(nets[pre])==6
        assert {k for k,rid in nets[drv]}=={"LINE"} and len(nets[drv])==5
        # Literal source follower loop is three lines starting at OUT, crossing
        # beneath the body and terminating at IN-. The two separate OUT->47R
        # lines remain valid when only the net name changes.
        feedback=[];kept=[]
        for key in nets[pre]:operation(key,"delete",None,"Old PRE joins raw input LPF, moved4k bias resistor, moved10nF and OPA320+; these nodes are now different nets.")
        for key in nets[drv]:
            b=rows[key]; x1,x2=b["startX"]*MM,b["endX"]*MM
            if min(x1,x2)>=17.49:
                feedback.append(key);operation(key,"delete",None,"REMOVE OLD UNITY FEEDBACK: retaining it shorts the new2.8k//10nF feedback and forces follower operation.")
            else:
                kept.append(key);operation(key,"rename_net",newdrv,"Same physical OPA320OUT and47R input endpoints; preserve existing output-to-series copper.")
        assert len(feedback)==3 and len(kept)==2
        rawkeys=netkeys_by_fold.get(oldraw.casefold(),[])
        assert len(rawkeys)==1 and rawkeys[0][0]=="LINE",(sma,oldraw,rawkeys)
        for key in rawkeys:
            assert key[0] in {"LINE","ARC","FILL","VIA","POLY"},key
            assert key[0]!="VIA","Unexpected raw via ownership requires separate drill-preservation review"
            operation(key,"rename_net",newraw,"Same SMA signal pin and existing3.32k input-resistor pin; only raw net is renamed by schematic.")
        channels.append({"sma":sma,"rowYmm":140-14*i,"oldRaw":oldraw,"newRaw":newraw,"oldPRE":pre,"newFilter":f"ADC_{sma}_FILTER","newBuffer":f"ADC_{sma}_BUF","newSum":f"ADC_{sma}_SUM","oldDRV":drv,"newDRV":newdrv,"removeUnityFeedbackIds":[k[1] for k in feedback],"keepOutputTo47RIds":[k[1] for k in kept],"keepADCPostNet":components[f"R{outs[i]}"]["pins"]["2"],"inputResistor":f"R{ins[i]}","postResistor":f"R{outs[i]}","sumInputResistor":f"R{rin[i]}"})
    bias_connected=[{"ref":r,"pin":p} for r,b in components.items() for p,n in b["pins"].items() if n=="ADC_BIAS_2V5"]
    assert len(bias_connected)==13 and {v["ref"] for v in bias_connected}=={f"R{x}" for x in rin}|{"U9","C104","C105"}
    trunk=[]
    for key in nets["ADC_BIAS_2V5"]:
        b=rows[key]
        assert key[0]=="LINE" and b["layerId"]==1
        if b["width"]*MM>.59:
            assert min(b["startX"],b["endX"])*MM>25.69
            ymin,ymax=sorted((b["startY"]*MM,b["endY"]*MM))
            if ymin<81.5 and ymax>67.5:
                operation(key,"delete",None,"Central widebus overlaps newSOIC8REF5025NC/output pads and offsetfollower; delete crossingsegments before replacement with separatelyclearanceverifiedjog.")
            else:
                trunk.append(key)
                operation(key,"rename_net","ADC_OFFSET_0V97","Preserve only isolated widecentralbus outside newreferenceisland; allformerREF/biasresistor/capacitor branchesremovedseparately.")
        else:operation(key,"delete",None,"Old positive-bias tap or old reference bypass branch; no longer matches new pin contracts.")
    old_reference_supply_stubs=["8f2d79e61b91a9c3","bdbacbd270c676c0","894fec9d56a4bbbf","0074ee2853c5f528","8bed767bd15efcb1","c38941e71664641b"]
    for rid in old_reference_supply_stubs:
        b=rows["LINE",rid]
        assert b["netName"]=="+3V3" and b["layerId"]==1
        assert 19.79<=min(b["startX"],b["endX"])*MM<=23.51
        assert 77.82<=min(b["startY"],b["endY"])*MM<=82.21
        operation(("LINE",rid),"delete",None,"Only formerU9/C103 reference+3V3 branch beyond retainedOPA320localfeedtee(23.5,82.2); newREF5025 uses+5V_AFE and these oldpinsareNC/moved. Preserve adjacentOPA320supplytee/trunk.")
    manifest={"schema":"adc10-labtool-exact-copper-isolation-20261018-v1","status":"OFFLINE_GUARDED_PLAN_REQUIRES_PARENT_NATIVE_REBASE_AND_DRC","sourcePath":str(SOURCE),"sourceSha256":sha(SOURCE),"readOnly":True,"nativeCalls":0,"wholeSourceReplace":False,"operations":operations,"channels":channels,"oldBiasPinOwnership":bias_connected,"preservedOffsetTrunkIds":[i for k,i in trunk],"counts":{"delete":sum(x["action"]=="delete" for x in operations),"rename":sum(x["action"]=="rename_net" for x in operations),"byType":dict(Counter(x["type"] for x in operations))},"protected":{"originalVias":sum(k=="VIA" for k,r in rows),"oldViasModifiedOrDeleted":0,"ADCPostNetsModified":False,"rulesChanged":False,"layersChanged":False,"J18Changed":False,"outlineChanged":False},"requiredBeforeApply":["Capture actual post-ECO source; rebase IDs/net names only when exact geometry/pin ownership matches baseline.","Confirm all new/native pad-net contracts before keeping output stubs and the wideoffset trunk.","Preflight original640VIA bodies and all untouched records byte/body exact.","Delete all three old unity-feedback lines per channel before any new feedback routing.","Do not treat isolated preserved trunk as connected until new common offset and all OPA320+ branches are routed and connectivity verified."],"notIncluded":["Ground/+3V3 orphan stubs at relocated C97..C112 and old reference are not automatically deleted; review exactlocalshapeif they conflict.","New routes, vias, staticGNDvoids and nativeDRC are separate later phases."],"manufacturingReady":False}
    (HERE/"exact-old-copper-isolation-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf8")
    eco_path=ROOT/"output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru"
    if eco_path.exists():
        eco=G["PARSE"](eco_path)
        mismatch=[{"type":op["type"],"id":op["id"],"oldBody":op["beforeBody"],"actualBody":eco.get((op["type"],op["id"]))} for op in operations if eco.get((op["type"],op["id"]))!=op["beforeBody"]]
        ecovia={k:b for k,b in eco.items() if k[0]=="VIA"};oldvia={k:b for k,b in rows.items() if k[0]=="VIA"}
        rebased=copy.deepcopy(manifest)
        rebased.update({"sourcePath":str(eco_path),"sourceSha256":sha(eco_path),"baselineSourceSha256":sha(SOURCE),"exactAll173CopperBodiesUnchangedByECO":not mismatch,"original640ViaBodiesExact":ecovia==oldvia,"rebaseMismatches":mismatch,"applicationApproved":not mismatch and ecovia==oldvia})
        (HERE/"exact-old-copper-isolation-post-eco-manifest.json").write_text(json.dumps(rebased,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"manifest":str(HERE/"exact-old-copper-isolation-manifest.json"),"counts":manifest["counts"],"retainedOffsetTrunk":len(trunk),"channels":len(channels)}))
    local_routes(rows,attrs,refs,netpads,manifest,args.placement,args.tag,args.ports,args.common_top,args.extra_copper)


if __name__=="__main__": main()
