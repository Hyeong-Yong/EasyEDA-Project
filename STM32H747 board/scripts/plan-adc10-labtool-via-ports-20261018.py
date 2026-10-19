"""Offline six-layer VIA/drill clearance search; no native/API/source writes."""
import argparse
import copy
import hashlib
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path
from shapely.geometry import Point, LineString, Polygon, box
from shapely.affinity import scale
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018/routing"
M=runpy.run_path(str(HERE.parent/"independent-pcb-placement-proposal.py"))
G=M["G"]; MM=.0254
SOURCE=ROOT/"output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru"
CHECK=ROOT/"output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2"
LAYERS=(1,2,15,16,17,18)
CLR=.17
VIA_D=.45
HOLE_D=.20
HOLE_GAP=.301


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--placement",type=Path,default=HERE.parent/"independent-pcb-placement-proposal.json")
    parser.add_argument("--routes",type=Path,default=HERE/"frozen-row310-initial-placement-route-draft.json")
    parser.add_argument("--tag",default="initial310")
    parser.add_argument("--with-ground",action="store_true")
    parser.add_argument("--common-power",action="store_true")
    parser.add_argument("--shared-filter-and-negative-ports",action="store_true")
    parser.add_argument("--extra-copper",type=Path,action="append",default=[])
    parser.add_argument("--query-ports",type=Path,help="Additional-only named VIA candidates; defaults disabled.")
    parser.add_argument("--fixed-ports",type=Path,help="Immutable existing proposed VIA ports to protect.")
    args=parser.parse_args()
    rows=M["parse"](SOURCE);attrs=M["attrs_of"](rows)
    placement=json.loads(args.placement.read_text(encoding="utf8"))
    routes=json.loads(args.routes.read_text(encoding="utf8"))
    plan=json.loads((HERE.parent/"schematic-plan.json").read_text(encoding="utf8"))
    isolation=json.loads((HERE/"exact-old-copper-isolation-post-eco-manifest.json").read_text(encoding="utf8"))
    for op in isolation["operations"]:
        key=op["type"],op["id"]
        assert rows[key]==op["beforeBody"]
        if op["action"]=="delete":del rows[key]
        else:rows[key]=op["afterBody"]
    pp={p["ref"]:p for p in placement["edits"]}
    contract=plan["allPinContracts"]
    docs,_=M["READ"](CHECK)
    netpads={}
    for (kind,rid),b in rows.items():
        if kind=="PAD_NET":
            p=json.loads(rid);netpads[p[1],str(p[2])]=b["padNet"]
    copper=[];fills=[];drills=[];allpads=[];smacourts=[]
    def obs(key,net,shape,layers):
        copper.append({"key":key,"net":(net or "").casefold(),"shape":shape,"layers":tuple(layers)})
    for (kind,cid),b in rows.items():
        if kind=="COMPONENT":
            ref=attrs[cid]["Designator"]
            if ref in pp:continue
            xy=b["x"]*MM,b["y"]*MM
            if ref in {f"J{i}" for i in range(2,12)}:
                _,court=M["footprint"](docs["FOOTPRINT",attrs[cid]["Footprint"]])
                smacourts.append((ref,M["world"](court,xy,b["angle"])))
            for (pk,pid),(ph,pb) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
                if pk!="PAD":continue
                pn=str(pb["num"]);s=M["local_pad"](pb)
                if b["layerId"]==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                s=M["world"](s,xy,b["angle"])
                layers=LAYERS if pb["layerId"]==12 else (b["layerId"],)
                net=contract.get(ref,{}).get(pn,netpads.get((cid,pn),""))
                if any(l in LAYERS for l in layers):obs("PAD:"+ref+":"+pn,net,s,layers);allpads.append(("PAD:"+ref+":"+pn,s))
                hole=pb.get("hole") or {};w=hole.get("width",0)*MM;h=hole.get("height",0)*MM
                if w>0 or h>0:
                    # Conservative envelope for slots, exact axis-aligned circle
                    # for rounds; no drill can be closer than the strict gap.
                    hs=box(-w/2,-h/2,w/2,h/2)
                    hs=M["world"](hs,(pb["centerX"]*MM,pb["centerY"]*MM),pb.get("padAngle",0))
                    if b["layerId"]==2:hs=scale(hs,xfact=1,yfact=-1,origin=(0,0))
                    hs=M["world"](hs,xy,b["angle"])
                    drills.append(("DRILL:"+ref+":"+pn,hs))
        elif kind=="VIA":
            p=Point(b["centerX"]*MM,b["centerY"]*MM)
            obs("VIA:"+cid,b["netName"],p.buffer(b["viaDiameter"]*MM/2,resolution=32),LAYERS)
            drills.append(("DRILL:VIA:"+cid,p.buffer(b["holeDiameter"]*MM/2,resolution=32)))
        elif kind=="PAD":
            hole=b.get("hole") or {};w=hole.get("width",0)*MM;h=hole.get("height",0)*MM
            if w>0 or h>0:
                hs=M["world"](box(-w/2,-h/2,w/2,h/2),(b["centerX"]*MM,b["centerY"]*MM),b.get("padAngle",0))
                drills.append(("DRILL:FREEPAD:"+cid,hs))
        elif kind in ("LINE","ARC") and b.get("layerId") in LAYERS:
            a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
            pts=G["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
            obs(kind+":"+cid,b.get("netName"),LineString(pts).buffer(b["width"]*MM/2,resolution=8),(b["layerId"],))
        elif kind=="POLY" and b.get("layerId") in LAYERS:
            obs(kind+":"+cid,b.get("netName"),LineString(G["ring_path"](b["path"])).buffer(b["width"]*MM/2,resolution=8),(b["layerId"],))
        elif kind=="FILL" and b.get("layerId") in LAYERS:
            if b["path"][0][0]=="CIRCLE":
                cp=b["path"][0];fs=Point(cp[1]*MM,cp[2]*MM).buffer(cp[3]*MM,resolution=64)
            else:
                rings=[G["ring_path"](p) for p in b["path"]]
                fs=Polygon(rings[0],rings[1:])
            fills.append({"id":cid,"net":b.get("netName",""),"layerId":b["layerId"],"shape":fs,"valid":fs.is_valid,"body":b})
    for p in pp.values():
        for pad in p["pads"]:
            s=box(*pad["boundsMm"]);key="PAD:"+p["ref"]+":"+pad["number"]
            obs(key,pad["net"],s,(1,));allpads.append((key,s))
    for p in routes["newLineCreates"]:
        obs(p["key"],p["net"],LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2,resolution=8),(p["layerId"],))
    for ep in args.extra_copper:
        external=json.loads(ep.read_text(encoding="utf8"))
        for p in external.get("newLineCreates",[]):obs(p["key"],p["net"],LineString([p["startXYmm"],p["endXYmm"]]).buffer(p["widthMm"]/2,resolution=16),(p["layerId"],))
        for p in external.get("newViaCreates",[]):obs(p["key"],p["net"],Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=32),LAYERS)
    assert len(drills)==799,("Physicaldrillcount",len(drills))
    fixed=[]
    if args.fixed_ports:
        fixed=json.loads(args.fixed_ports.read_text(encoding="utf8"))["viasProposed"]
        for p in fixed:obs("FIXED:"+p["key"],p["net"],Point(p["xyMm"]).buffer(p["viaDiameterMm"]/2,resolution=32),LAYERS)
    for ep in args.extra_copper:
        for p in json.loads(ep.read_text(encoding="utf8")).get("newViaCreates",[]):
            fixed.append(p)
    tree=STRtree([o["shape"] for o in copper]);dtree=STRtree([s for k,s in drills]);ptree=STRtree([s for k,s in allpads])
    viaout=[];fail=[];newdrills=[]
    newdrills.extend(Point(p["xyMm"]).buffer(p.get("holeDiameterMm",.20)/2,resolution=32) for p in fixed)
    def evaluate(net,xy,reroute_filter=False):
        p=Point(xy);s=p.buffer(VIA_D/2,resolution=32);probe=s.buffer(CLR,resolution=16)
        if reroute_filter and any(s.distance(court)<.15 for ref,court in smacourts):return None
        for idx in tree.query(probe):
            o=copper[int(idx)]
            if reroute_filter and o["key"].startswith("LABTOOL_LOCAL_") and o["net"].endswith("_filter"):continue
            if o["net"]!=net.casefold() and probe.intersects(o["shape"]):return None
        # Even same-net SMTpad must not overlap/abut a via hole (no via-in-pad).
        for idx in ptree.query(s.buffer(.06)):
            k,pad=allpads[int(idx)]
            if s.distance(pad)<.06:return None
        h=p.buffer(HOLE_D/2,resolution=32);hp=h.buffer(HOLE_GAP,resolution=16)
        if any(hp.intersects(drills[int(i)][1]) for i in dtree.query(hp)):return None
        if any(h.distance(old)<HOLE_GAP for old in newdrills):return None
        if any(s.distance(Point(v["xyMm"]).buffer(VIA_D/2))<CLR for v in viaout if v["net"]!=net):return None
        cuts=[]
        for f in fills:
            if f["net"].casefold()==net.casefold():continue
            if not probe.intersects(f["shape"].envelope):continue
            # Invalid sourcefillisneverrepairedbythissearch;potentialoverlap
            # isreportedconservativelyandrequiresparentexplicitpathreview.
            if not f["valid"] or probe.intersects(f["shape"]):cuts.append({"id":f["id"],"layerId":f["layerId"],"net":f["net"],"originalPolygonValid":f["valid"]})
        return cuts
    def choose(label,net,preferred,region,reroute_filter=False):
        x0,y0,x1,y1=region
        candidates=[(round(x0+.1*i,4),round(y0+.1*j,4)) for i in range(round((x1-x0)/.1)+1) for j in range(round((y1-y0)/.1)+1)]
        candidates.sort(key=lambda p:math.dist(p,preferred))
        for p in [preferred]+candidates:
            cuts=evaluate(net,p,reroute_filter)
            if cuts is None:continue
            item={"key":label,"net":net,"xyMm":p,"viaDiameterMm":VIA_D,"holeDiameterMm":HOLE_D,"allLayers":LAYERS,"requiresLocalFillAntipadCuts":cuts,"oldNonFillCopperClearanceMm":CLR,"holeToOld799DrillsEdgeGapMm":HOLE_GAP,"viaInPadForbidden":True,"requiresFilterReroutingAroundReservedGroundVia":reroute_filter}
            vd=Point(p).buffer(HOLE_D/2,resolution=32)
            item["minimumOldDrillEdgeGapMm"]=min(vd.distance(s) for key,s in drills)
            item["minimumFourMountingNPTHDrillEdgeGapMm"]=min(vd.distance(s) for key,s in drills if key.startswith("DRILL:FREEPAD:"))
            item["minimumSMAConservativeCourtToViaCopperGapMm"]=min(Point(p).buffer(VIA_D/2,resolution=32).distance(s) for key,s in smacourts)
            viaout.append(item);newdrills.append(Point(p).buffer(HOLE_D/2,resolution=32));return item
        fail.append({"key":label,"net":net,"preferredXYmm":preferred,"regionMm":region,"reason":"NO_ALL6_NONFILL_CU_AND799DRILL_CLEARANCE_PORT"})
        return None
    for i in range(0 if args.query_ports else 10):
        row=140-14*i
        choose(f"AFE_PLUS_PORT_J{i+2}","+5V_AFE",(15.5,row-1.6),(14.8,row-2.5,16.5,row-.7))
        choose(f"AFE_MINUS_PORT_J{i+2}","-3V_AFE",(9.0,row-4.5),(8.8,row-5.8,10.2,row-3.0))
    for label,net,p,region in (
        ("OFFSET_OUTPUT_PORT","ADC_OFFSET_0V97",(25.2,67.5),(23.7,66.7,26.0,69.0)),
        ("OFFSET_UPPER_BUS_PORT","ADC_OFFSET_0V97",(26.5,87.0),(25.3,83.9,28.0,87.6)),
        ("OFFSET_LOWER_BUS_PORT","ADC_OFFSET_0V97",(26.5,61.2),(25.5,60.0,27.5,62.5)),
        ("OFFSET_BUCKET_PORT","ADC_OFFSET_0V97",(30.2,83.55),(29.0,82.6,31.0,84.4)),
        ("REF_PLUS_PORT","+5V_AFE",(29.5,72.7),(27.5,70.8,30.7,74.0)),
        ("OFFSET_J7_PLUS_PORT","ADC_OFFSET_0V97",(17.0,66.6),(16.2,65.7,18.0,67.4)),
        ("OFFSET_J6_PLUS_PORT","ADC_OFFSET_0V97",(16.6,80.5),(16.1,79.8,17.0,81.1)),
    ):
        if not args.query_ports:choose(label,net,p,region)
    if args.with_ground and not args.query_ports:
        for i in range(10):
            row=140-14*i
            choose(f"GND_NEGATIVE_BYPASS_J{i+2}","GND",(6.4,row-5.2),(5.8,row-5.7,6.6,row-4.8),True)
        choose("GND_POSITIVE_BYPASS_J6","GND",(14.2,80.15),(13.2,79.9,15.0,80.4))
        choose("GND_OFFSET_DIVIDER","GND",(26.3,67.4),(25.7,66.8,27.0,67.7))
    if args.common_power and not args.query_ports:
        for label,net,p,region in (
            ("RAW5_R197_PORT","+5V",(28.8,34.2),(27.0,32.8,31.0,36.0)),
            ("RAW5_R200_PORT","+5V",(27.6,22.0),(26.5,21.7,29.0,23.0)),
            ("PLUS_AFE_COMMON_PORT","+5V_AFE",(31.0,24.5),(29.8,24.0,33.5,25.4)),
            ("MINUS_AFE_COMMON_PORT","-3V_AFE",(40.3,31.7),(39.5,31.3,43.0,33.0)),
        ):choose(label,net,p,region)
    if args.shared_filter_and_negative_ports and not args.query_ports:
        for label,net,p,region in (
            ("OFFSET_FILTER_LEFT_PORT","AFE_OFFSET_FILTER",(23.4,69.6),(22.5,68.8,24.0,70.6)),
            ("OFFSET_FILTER_RIGHT_PORT","AFE_OFFSET_FILTER",(30.95,66.1),(30.0,65.7,31.8,66.3)),
            ("MINUS_AFE_LEFT_ENTRY_PORT","-3V_AFE",(13.1,22.4),(12.0,21.5,14.0,22.9)),
        ):choose(label,net,p,region)
    if args.query_ports:
        for q in json.loads(args.query_ports.read_text(encoding="utf8"))["ports"]:choose(q["key"],q["net"],q["preferredXYmm"],q["regionMm"])
    old_sources=[{"key":o["key"],"net":o["net"],"xyMm":[o["shape"].centroid.x,o["shape"].centroid.y],"boundsMm":list(o["shape"].bounds),"layers":o["layers"]} for o in copper if o["net"]=="+5v" and o["key"].startswith("PAD:") and all(l in o["layers"] for l in LAYERS)]
    report={"schema":"adc10-labtool-sixlayer-via-port-search-20261018-v1","sourceSha256":sha(SOURCE),"placementPath":str(args.placement),"placementSha256":sha(args.placement),"routePath":str(args.routes),"routeSha256":sha(args.routes),"readOnly":True,"nativeCalls":0,"status":"VIA_PORTS_ONLY_NOT_CONNECTED_ROUTING","existingPhysicalDrillsChecked":len(drills),"existingViasPreserved":640,"viasProposed":viaout,"failedPorts":fail,"existingRaw5VPTHPadSources":old_sources,"viaDiameterMm":VIA_D,"holeDiameterMm":HOLE_D,"nonFillClearanceMm":CLR,"drillEdgeGapMm":HOLE_GAP,"limitations":["EachnewVIArequiresliteralstaticFILLantipadsonEVERYlistedlayerbeforeapplying;thisreportdoesnotyetcontainBooleanpathupdates.","PortsarenotyetconnectedtoSMTpadsorBottomrailtrunks;TOP/BOTTOMstubsandtrunkmutualclearanceareseparatelaterwork.","All799oldholesand640VIAsarekeptunchanged. Drillslotswereconservativelyscreenedbyrotatedrectangle.","ThisisnotnativeDRCnorverificationofcompletedpower/offsetconnectivity."],"manufacturingReady":False}
    target=HERE/f"six-layer-via-port-candidates-{args.tag}.json"
    target.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"target":str(target),"ports":len(viaout),"failed":len(fail),"drills":len(drills)}))


if __name__=="__main__":main()
