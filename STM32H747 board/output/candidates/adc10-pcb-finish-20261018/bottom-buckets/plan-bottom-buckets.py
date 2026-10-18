"""Offline-only bounded bottom bucket placement and routing search.

Emits analysis and a native-operation DATA manifest; never edits an EDA source.
All existing copper and drills are immutable except explicitly listed local
BOTTOM GND FILL hole unions needed around the added signal copper.
"""
import hashlib
import heapq
import json
import math
import runpy
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / ".tools/adc-geometry-deps"))
import pyclipper as pc
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OLD = runpy.run_path(str(ROOT / "scripts/draft-adc10-bucket-placement-readonly-20261017.py"))
READ = runpy.run_path(str(ROOT / "output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]
SOURCE = ROOT / "output/validation/native-adc10-pcb-baseline-20261018.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_pcb_route_20261018.epro2"
INV = ROOT / "output/analysis/adc10-pcb-eco-api-feasibility-20261017.json"
EXPECTED_SHA = "5a1fe43c0ce8e36ee89bcac512321e55610b83c3e890b429373878efb6825b9b"
MM = .0254
CLR = .1524
WIDTH = .12  # 4.7244 mil, above the actual unchanged 4.0157 mil TOP/BOTTOM minimum.
GRID = .02
SCALE = 1000000
BOUNDS = (44., 74., 63., 91.)
W = round((BOUNDS[2]-BOUNDS[0])/GRID)+1
H = round((BOUNDS[3]-BOUNDS[1])/GRID)+1
MARGIN = .006


def ip(points): return [(round(x*SCALE), round(y*SCALE)) for x,y in points]
def fp(points): return [(x/SCALE,y/SCALE) for x,y in points]
def bbox(points): return OLD["bbox"](points)
def overlap(a,b,pad=0): return OLD["bb_overlap"](a,b,pad)
def circle(p,r):
    n=max(32, math.ceil(math.pi/math.acos(max(-1,1-min(.0005/r,1)))))
    return ip([(p[0]+r*math.cos(i*math.tau/n),p[1]+r*math.sin(i*math.tau/n)) for i in range(n)])
def rectangle(p,axis,extra=0): return ip(OLD["rectangle"](p,axis,extra))
def offset(paths,d,closed=True):
    if not paths:return []
    o=pc.PyclipperOffset(2., .0005*SCALE)
    o.AddPaths(paths,pc.JT_ROUND,pc.ET_CLOSEDPOLYGON if closed else pc.ET_OPENROUND)
    return o.Execute(d*SCALE)
def union(paths):
    if not paths:return []
    c=pc.Pyclipper();c.AddPaths(paths,pc.PT_SUBJECT,True)
    return c.Execute(pc.CT_UNION,pc.PFT_NONZERO,pc.PFT_NONZERO)
def inter(a,b):
    if not a or not b:return []
    c=pc.Pyclipper();c.AddPaths(a,pc.PT_SUBJECT,True);c.AddPaths(b,pc.PT_CLIP,True)
    return c.Execute(pc.CT_INTERSECTION,pc.PFT_NONZERO,pc.PFT_NONZERO)
def diff(a,b,tree=False):
    c=pc.Pyclipper();c.AddPaths(a,pc.PT_SUBJECT,True)
    if b:c.AddPaths(b,pc.PT_CLIP,True)
    return (c.Execute2 if tree else c.Execute)(pc.CT_DIFFERENCE,pc.PFT_NONZERO,pc.PFT_NONZERO)
def filled_rings(paths):
    """Normalize complex polygon outer positive, holes negative for Clipper."""
    result=[]
    for i,p in enumerate(paths):
        if p[0]=="CIRCLE":q=circle((p[1]*MM,p[2]*MM),p[3]*MM)
        elif p[0]=="R":
            _,x,y,w,h,angle,*rest=p
            t=math.radians(angle);cx=x*MM;cy=y*MM
            q=ip([(cx+dx*MM*math.cos(t)-dy*MM*math.sin(t),cy+dx*MM*math.sin(t)+dy*MM*math.cos(t)) for dx,dy in [(0,0),(w,0),(w,h),(0,h)]])
        else:q=ip(OLD["ring_path"](p))
        if pc.Orientation(q)!=(i==0):q.reverse()
        result.append(q)
    return result
def capsule(points,r):return offset([ip(points)],r,False)
def world_to_grid(p): return (round((p[0]-BOUNDS[0])/GRID),round((p[1]-BOUNDS[1])/GRID))
def grid_to_world(x,y):return (round(BOUNDS[0]+x*GRID,8),round(BOUNDS[1]+y*GRID,8))
def raster(paths):
    im=Image.new("1",(W,H),0);d=ImageDraw.Draw(im)
    # Union first so separately drawn holes cannot erase another copper object.
    for p in paths:
        if pc.Area(p)<=0:continue
        d.polygon([((x/SCALE-BOUNDS[0])/GRID,(y/SCALE-BOUNDS[1])/GRID) for x,y in p],fill=1)
    for p in paths:
        if pc.Area(p)>=0:continue
        d.polygon([((x/SCALE-BOUNDS[0])/GRID,(y/SCALE-BOUNDS[1])/GRID) for x,y in p],fill=0)
    return np.asarray(im,dtype=np.uint8)
def positive(p):
    q=p[:]
    if not pc.Orientation(q):q.reverse()
    return q
def pad_clear_array(mask,hx,hy):
    """Conservative axis-aligned rectangle queries against clearance mask."""
    rx=math.ceil((hx+GRID*.6)/GRID);ry=math.ceil((hy+GRID*.6)/GRID)
    summed=np.pad(mask,((1,0),(1,0))).cumsum(0,dtype=np.int32).cumsum(1,dtype=np.int32)
    out=np.zeros_like(mask,dtype=bool)
    sums=summed[2*ry+1:,2*rx+1:]-summed[:-2*ry-1,2*rx+1:]-summed[2*ry+1:,:-2*rx-1]+summed[:-2*ry-1,:-2*rx-1]
    out[ry:H-ry,rx:W-rx]=sums==0
    return out
def paths_bbox(paths):return bbox([q for p in paths for q in fp(p)])
def point_in_solid(p,paths):return sum((1 if pc.Area(q)>0 else -1) for q in paths if pc.PointInPolygon((round(p[0]*SCALE),round(p[1]*SCALE)),q)!=0)>0


class Board:
    def __init__(self):
        self.rows=OLD["PARSE"](SOURCE)
        self.inv=json.loads(INV.read_text(encoding="utf8"))["channels"]
        self.attrs=defaultdict(dict)
        for (k,i),b in self.rows.items():
            if k=="ATTR":self.attrs[b["parentId"]][b["key"]]=b.get("value")
        self.refs={a["Designator"]:i for i,a in self.attrs.items() if "Designator" in a}
        self.obstacles=[];self.fills=[];self.vias=[];self.new=[];self.placed=[]
        self.legacy_bottom_envelopes=[]
        self.legacy_bottom_actual_bodies=[]
        self.route_power_fill_exceptions=set()
        self.allow_explicit_ground_return=False
        self.use_actual_passive_bodies=False
        self.counts=defaultdict(int)
        for (k,i),b in self.rows.items():
            n=b.get("netName","")
            if k=="VIA":
                p=(b["centerX"]*MM,b["centerY"]*MM);r=b["viaDiameter"]*MM/2
                if overlap((p[0]-r,p[1]-r,p[0]+r,p[1]+r),BOUNDS,1):
                    self.vias.append((i,n,p,r))
                    self.obstacles.append({"id":i,"kind":k,"net":n,"paths":[circle(p,r)],"via":True})
            elif k in ("LINE","ARC","CARC") and b["layerId"]==2:
                a=(b["startX"]*MM,b["startY"]*MM);z=(b["endX"]*MM,b["endY"]*MM)
                pts=OLD["arc"](a,z,b["angle"]) if k!="LINE" else [a,z]
                if overlap(bbox(pts),BOUNDS,1):self.obstacles.append({"id":i,"kind":k,"net":n,"paths":capsule(pts,b["width"]*MM/2)})
            elif k=="FILL" and b["layerId"]==2:
                paths=filled_rings(b["path"])
                if overlap(paths_bbox(paths),BOUNDS,1):
                    obj={"id":i,"kind":k,"net":n,"paths":offset(paths,b["width"]*MM/2),"sourcePaths":paths,"body":b}
                    if n=="GND":self.fills.append(obj)
                    else:self.obstacles.append(obj)
        # Through-hole and true bottom-side component pads from actual library.
        docs,_=READ(CHECKPOINT)
        padnets={}
        for (k,i),b in self.rows.items():
            if k=="PAD_NET":
                t=json.loads(i);padnets[t[1],str(t[2])]=b["padNet"]
        for (k,cid),c in self.rows.items():
            if k!="COMPONENT":continue
            fd=docs["FOOTPRINT",self.attrs[cid]["Footprint"]]
            envelope_points=[]
            theta=math.radians(c["angle"])
            def global_xy(x,y):return (c["x"]*MM+x*MM*math.cos(theta)-y*MM*math.sin(theta),c["y"]*MM+x*MM*math.sin(theta)+y*MM*math.cos(theta))
            for (pk,pid),(head,p) in fd.items():
                if pk in ("LINE","ARC") and (p.get("layerId")==4 and c["layerId"]==1 or p.get("layerId")==3 and c["layerId"]==2):
                    a=global_xy(p["startX"],p["startY"]);z=global_xy(p["endX"],p["endY"])
                    pts=OLD["arc"](a,z,p["angle"]) if pk=="ARC" else [a,z]
                    rr=p["width"]*MM/2
                    for x,y in pts:envelope_points.extend([(x-rr,y-rr),(x+rr,y+rr)])
            if envelope_points and overlap(bbox(envelope_points),BOUNDS,1):self.legacy_bottom_envelopes.append({"ref":self.attrs[cid].get("Designator"),"componentId":cid,"bboxMm":bbox(envelope_points),"basis":"Actual footprint BOTTOM_SILK line/arc envelope including stroke; conservative assembly/courtyard proxy"})
            bottom_lands=[p for (pk,pid),(head,p) in fd.items() if pk=="PAD" and (p.get("layerId")==2 and c["layerId"]==1 or p.get("layerId")==1 and c["layerId"]==2)]
            ref=self.attrs[cid].get("Designator","")
            if len(bottom_lands)==2 and ref.startswith(("C","R","FB")):
                p1,p2=[global_xy(p["centerX"],p["centerY"]) for p in bottom_lands]
                pitch=math.dist(p1,p2);cx,cy=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
                length,width=(1.6,.8) if pitch>1.35 else (1.0,.5)
                ax,ay=((p1[0]-p2[0])/pitch,(p1[1]-p2[1])/pitch)
                hx,hy=(abs(ax)*length/2+abs(ay)*width/2,abs(ay)*length/2+abs(ax)*width/2)
                box=(cx-hx,cy-hy,cx+hx,cy+hy)
                if overlap(box,BOUNDS,1):self.legacy_bottom_actual_bodies.append({"ref":ref,"componentId":cid,"bboxMm":box,"bodyLengthMm":length,"bodyWidthMm":width,"landPitchMm":pitch,"basis":"1005(0402) body1.0x0.5 mm for native~0.96/1.02 mm land pitch; 1608(0603) body1.6x0.8 mm for native1.55 mm pitch. Copper lands checked independently; imported Silk is not a factory courtyard."})
            for (pk,pid),(head,p) in fd.items():
                effective_layer=(3-p["layerId"]) if p.get("layerId") in (1,2) and c["layerId"]==2 else p.get("layerId")
                if pk!="PAD" or effective_layer not in (2,12):continue
                # All baseline components are TOP, so library layer 2 is literal
                # bottom; no uncalibrated instance reflection is used here.
                theta=math.radians(c["angle"])
                x,y=p["centerX"]*MM,p["centerY"]*MM
                gp=(c["x"]*MM+x*math.cos(theta)-y*math.sin(theta),c["y"]*MM+x*math.sin(theta)+y*math.cos(theta))
                shape=p["defaultPad"];hw=shape["width"]*MM/2;hh=shape["height"]*MM/2
                if not overlap((gp[0]-hw,gp[1]-hh,gp[0]+hw,gp[1]+hh),BOUNDS,1):continue
                angle=theta+math.radians(p.get("padAngle",0))
                if shape["padType"]=="ELLIPSE":
                    q=[(gp[0]+hw*math.cos(t)*math.cos(angle)-hh*math.sin(t)*math.sin(angle),gp[1]+hw*math.cos(t)*math.sin(angle)+hh*math.sin(t)*math.cos(angle)) for t in [j*math.tau/96 for j in range(96)]]
                else:
                    q=[(gp[0]+x*math.cos(angle)-y*math.sin(angle),gp[1]+x*math.sin(angle)+y*math.cos(angle)) for x,y in [(-hw,-hh),(hw,-hh),(hw,hh),(-hw,hh)]]
                self.obstacles.append({"id":cid+":"+pid,"kind":"COMPONENT_PAD","net":padnets.get((cid,str(p["num"])),""),"paths":[positive(ip(q))],"via":bool(p.get("hole"))})
                self.counts["localBottomOrThroughHoleComponentPads"]+=1
        self.ground_union=union([p for f in self.fills for p in f["paths"]])
        self.ground_mask=raster(self.ground_union).astype(bool)
        for o in self.obstacles:
            o["bbox"]=paths_bbox(o["paths"])
            o["clear"]=offset(o["paths"],CLR+MARGIN)
            o["viaClear"]=offset(o["paths"],.06+MARGIN) if o.get("via") else None
        print(json.dumps({"stage":"board_loaded","obstacles":len(self.obstacles),"fills":len(self.fills),"vias":len(self.vias),**self.counts}),flush=True)

    def copper_obstacles(self,net,pad=False):
        paths=[]
        for o in self.obstacles+self.new:
            if not pad and o["kind"]=="FILL" and o["net"] in self.route_power_fill_exceptions:continue
            if o["net"]==net:
                # All pads stay clear of every via, including own via, to avoid
                # unapproved via-in-pad; same-net clearance is .06 mm.
                if pad and o.get("via"):paths.extend(offset(o["paths"],.06+MARGIN))
                continue
            paths.extend(offset(o["paths"],CLR+MARGIN+(0 if pad else WIDTH/2)))
        return union(paths)

    def build_masks(self,net):
        blocked=raster(self.copper_obstacles(net))
        pm=raster(self.copper_obstacles(net,True))
        gm=raster(self.copper_obstacles("GND",True))
        pvalid=[pad_clear_array(pm,.28,.31),pad_clear_array(pm,.31,.28)]
        gvalid=[pad_clear_array(gm,.28,.31),pad_clear_array(gm,.31,.28)]
        return blocked,pvalid,gvalid

    def body_clear(self,box):
        old=self.legacy_bottom_actual_bodies if self.use_actual_passive_bodies else self.legacy_bottom_envelopes
        return not any(overlap(box,b,.10) for b in self.placed+[o["bboxMm"] for o in old])

    def search(self,ch,limit=8,tap_sources=None):
        net=ch["net"];vp=tuple(ch["nearestAdcEscapeVia"]["xyMm"])
        blocked,pvalid,gvalid=self.build_masks(net)
        print(json.dumps({"stage":"masks_ready","net":net}),flush=True)
        # Dijkstra from the actual escape via; an exact final geometric check
        # catches any raster aliasing and diagonal corner crossings.
        sx,sy=world_to_grid(vp)
        dist=np.full((H,W),np.inf,dtype=np.float32)
        prev=np.full((H,W),-1,dtype=np.int8)
        root_index=np.full((H,W),-1,dtype=np.int16)
        moves=[(1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(-1,-1),(1,-1)]
        heap=[]
        sources=tap_sources or [{"xyMm":vp,"escapeViaId":ch["nearestAdcEscapeVia"]["id"],"penaltyMm":0}]
        for si,source in enumerate(sources):
            sp=source["xyMm"];sx,sy=world_to_grid(sp)
            for y in range(sy-1,sy+2):
                for x in range(sx-1,sx+2):
                    if not (1<=x<W-1 and 1<=y<H-1) or blocked[y,x]:continue
                    gp=grid_to_world(x,y)
                    if self.route_hits([sp,gp],net):continue
                    dl=math.dist(sp,gp)+source.get("penaltyMm",0)
                    if dl>=dist[y,x]:continue
                    dist[y,x]=dl;prev[y,x]=8;root_index[y,x]=si;heapq.heappush(heap,(dl,x,y))
        candidates=[];visited=0
        while heap:
            d,x,y=heapq.heappop(heap)
            if d>dist[y,x]+1e-6:continue
            if d>limit:break
            if candidates and d>candidates[0][0]+.65:break
            visited+=1
            if d>.35 and d<limit and x%2==0 and y%2==0:
                p1=grid_to_world(x,y)
                for ai,(ax,ay) in enumerate([(1,0),(-1,0),(0,1),(0,-1)]):
                    orient=0 if ax else 1
                    if not pvalid[orient][y,x]:continue
                    gx=x-round(.96/GRID)*ax;gy=y-round(.96/GRID)*ay
                    if not(0<=gx<W and 0<=gy<H and gvalid[orient][gy,gx]):continue
                    p2=grid_to_world(gx,gy)
                    candidate_source=sources[int(root_index[y,x])]
                    if candidate_source.get("kind")=="NEW_ADC_TAP_VIA":
                        sr=candidate_source["diameterMm"]/2
                        hx,hy=(.28,.31) if ax else (.31,.28)
                        def rect_distance(point,center):return math.hypot(max(abs(point[0]-center[0])-hx,0),max(abs(point[1]-center[1])-hy,0))
                        if rect_distance(candidate_source["xyMm"],p1)<sr+.06+MARGIN:continue
                        if rect_distance(candidate_source["xyMm"],p2)<sr+CLR+MARGIN:continue
                    if not self.allow_explicit_ground_return and not self.ground_mask[gy,gx]:continue
                    # Require all four GND pad corners to be inside the same
                    # source GND copper union, not just its center.
                    corners=[world_to_grid(q) for q in fp(rectangle(p2,(ax,ay)))]
                    if not self.allow_explicit_ground_return and not all(0<=tx<W and 0<=ty<H and self.ground_mask[ty,tx] for tx,ty in corners):continue
                    center=((p1[0]+p2[0])/2,(p1[1]+p2[1])/2)
                    # pvalid body mask was applied at p1; check exact center.
                    hh=((.5,.25) if ax else (.25,.5)) if self.use_actual_passive_bodies else ((.95,.5) if ax else (.5,.95))
                    box=(center[0]-hh[0],center[1]-hh[1],center[0]+hh[0],center[1]+hh[1])
                    if not self.body_clear(box):continue
                    candidates.append((d+.08*math.dist(center,vp),x,y,(ax,ay),p1,p2,box))
            for di,(dx,dy) in enumerate(moves):
                nx,ny=x+dx,y+dy
                if not(1<=nx<W-1 and 1<=ny<H-1) or blocked[ny,nx]:continue
                if dx and dy and (blocked[y,nx] or blocked[ny,x]):continue
                nd=d+GRID*(math.sqrt(2) if dx and dy else 1)
                if nd<dist[ny,nx]-1e-6:
                    dist[ny,nx]=nd;prev[ny,nx]=di;heapq.heappush(heap,(nd,nx,ny))
                    root_index[ny,nx]=root_index[y,x]
        candidates.sort()
        print(json.dumps({"net":net,"visited":visited,"rawCandidates":len(candidates),"nearestD":candidates[0][0] if candidates else None}),flush=True)
        for _,x,y,axis,p1,p2,box in candidates[:1000]:
            if not self.allow_explicit_ground_return and not all(point_in_solid(q,self.ground_union) for q in fp(rectangle(p2,axis))):continue
            q=[];cx,cy=x,y
            while prev[cy,cx]!=8:
                q.append(grid_to_world(cx,cy));di=int(prev[cy,cx])
                if di<0:raise RuntimeError("broken Dijkstra parent")
                dx,dy=moves[di];cx-=dx;cy-=dy
            source=sources[int(root_index[cy,cx])]
            q.extend([grid_to_world(cx,cy),tuple(source["xyMm"])]);q.reverse()
            if source.get("kind")=="NEW_ADC_TAP_VIA":
                sr=source["diameterMm"]/2
                if inter([rectangle(p1,axis)],[circle(source["xyMm"],sr+.06+MARGIN)]):continue
                if inter([rectangle(p2,axis)],[circle(source["xyMm"],sr+CLR+MARGIN)]):continue
            q=self.simplify(q,net)
            if self.route_hits(q,net):continue
            # New signal copper must also clear its own GND pad. The endpoint
            # cannot loop around or through the other land of the capacitor.
            own_ground=offset([rectangle(p2,axis)],CLR+WIDTH/2+MARGIN)
            if inter(capsule(q,WIDTH/2),own_ground):continue
            if self.pad_hits(p1,axis,net) or self.pad_hits(p2,axis,"GND"):continue
            ground_connection=self.ground_connection(p2,axis,p1,q,net,source) if self.allow_explicit_ground_return else {"mode":"DIRECT_SOLID_GND_FILL_CONTACT"}
            if ground_connection is None:continue
            result={"ref":next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")),"net":net,"componentId":self.refs[next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C"))],"escapeViaId":ch["nearestAdcEscapeVia"]["id"],"escapeXYmm":vp,"selectedRoutingSource":source,"requiredWorldPads":{"1":{"net":net,"xyMm":p1},"2":{"net":"GND","xyMm":p2}},"centerXYmm":[(p1[0]+p2[0])/2,(p1[1]+p2[1])/2],"axisOfPositiveLocalX":axis,"targetLayer":"BOTTOM","signalRoute":{"layerId":2,"widthMm":WIDTH,"pointsMm":q,"lengthMm":sum(math.dist(a,b) for a,b in zip(q,q[1:]))},"groundConnection":ground_connection,"assemblyBoundingBoxMm":box,"searchStats":{"visitedCells":visited,"rawCandidates":len(candidates)}}
            if "pointsMm" in ground_connection:result["groundRoute"]={"layerId":2,"widthMm":WIDTH,"pointsMm":ground_connection["pointsMm"],"lengthMm":ground_connection["lengthMm"]}
            return result
        return {"ref":next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")),"net":net,"status":"NO_PLACEMENT_FOUND","visitedCells":visited,"rawCandidates":len(candidates)}

    def route_hits(self,points,net):
        copper=capsule(points,WIDTH/2)
        bb=paths_bbox(copper)
        for o in self.obstacles+self.new:
            if o["kind"]=="FILL" and o["net"] in self.route_power_fill_exceptions:continue
            if o["net"]==net or not overlap(bb,o["bbox"],CLR+MARGIN):continue
            if inter(copper,o["clear"]):return True
        return False
    def ground_connection(self,p2,axis,p1,signal,net,source):
        land=[rectangle(p2,axis)]
        contact=sum(pc.Area(p) for p in inter(land,self.ground_union))/(SCALE*SCALE)
        if contact>=.08:return {"mode":"ROBUST_LAND_OVERLAP_EXISTING_GND_SOLID","contactAreaMm2":contact,"lengthMm":0}
        obstacles=union([rectangle(p1,axis)]+capsule(signal,WIDTH/2)+([circle(source["xyMm"],source["diameterMm"]/2)] if source.get("kind")=="NEW_ADC_TAP_VIA" else []))
        forbidden=offset(obstacles,CLR+MARGIN)
        goals=[]
        for radius in (.20,.35,.50,.75,1.,1.4):
            for deg in range(0,360,30):
                t=math.radians(deg);p=(p2[0]+radius*math.cos(t),p2[1]+radius*math.sin(t))
                if not all(point_in_solid((p[0]+dx,p[1]+dy),self.ground_union) for dx,dy in [(0,0),(.08,0),(-.08,0),(0,.08),(0,-.08)]):continue
                goals.append((radius,p,"EXISTING_GND_SOLID"))
            if goals:break
        goals.extend((math.dist(p2,p),p,"VIA:"+i) for i,n,p,r in self.vias if n=="GND" and math.dist(p2,p)<3.0)
        for length,end,kind in sorted(goals):
            q=[p2,end]
            if self.route_hits(q,"GND") or inter(capsule(q,WIDTH/2),forbidden):continue
            return {"mode":"SHORT_NEW_GND_TRACE_TO_ANCHORED_EXISTING_COPPER","target":kind,"pointsMm":q,"widthMm":WIDTH,"lengthMm":length}
        return None
    def pad_hits(self,p,axis,net):
        land=[rectangle(p,axis)];bb=paths_bbox(land)
        for o in self.obstacles+self.new:
            extra=.06 if o["net"]==net and o.get("via") else CLR+MARGIN
            if o["net"]==net and not o.get("via"):continue
            if not overlap(bb,o["bbox"],extra):continue
            if inter(land,o["viaClear"] if o["net"]==net and o.get("via") else o["clear"]):return True
        return False
    def simplify(self,q,net):
        # Preserve full safe path but greedily remove raster staircases using
        # exact polygon collision tests (no invented or relaxed clearance).
        compressed=[q[0]]
        for i,p in enumerate(q[1:-1],1):
            a,b=q[i-1],q[i+1]
            if abs((p[0]-a[0])*(b[1]-p[1])-(p[1]-a[1])*(b[0]-p[0]))>1e-10:compressed.append(p)
        compressed.append(q[-1]);q=compressed
        out=[q[0]];i=0
        while i<len(q)-1:
            for j in range(len(q)-1,i,-1):
                if not self.route_hits([q[i],q[j]],net):break
            out.append(q[j]);i=j
        return out
    def accept(self,r):
        axis=r["axisOfPositiveLocalX"];p1=r["requiredWorldPads"]["1"]["xyMm"];p2=r["requiredWorldPads"]["2"]["xyMm"]
        for suffix,n,p in [("1",r["net"],p1),("2","GND",p2)]:self.new.append({"id":r["ref"]+":"+suffix,"kind":"NEW_CAP_PAD","net":n,"paths":[rectangle(p,axis)]})
        self.new.append({"id":r["ref"]+":ROUTE","kind":"NEW_LINE","net":r["net"],"paths":capsule(r["signalRoute"]["pointsMm"],WIDTH/2)})
        if "groundRoute" in r:self.new.append({"id":r["ref"]+":GND_ROUTE","kind":"NEW_LINE","net":"GND","paths":capsule(r["groundRoute"]["pointsMm"],r["groundRoute"]["widthMm"]/2)})
        for o in self.new:
            if "bbox" in o:continue
            o["bbox"]=paths_bbox(o["paths"]);o["clear"]=offset(o["paths"],CLR+MARGIN);o["viaClear"]=None
        self.placed.append(r["assemblyBoundingBoxMm"])


def render(board,results,path):
    scale=160;bb=(47.,77.,59.5,86.5)
    im=Image.new("RGB",(round((bb[2]-bb[0])*scale),round((bb[3]-bb[1])*scale)),"#0e1520")
    def xy(p):return ((p[0]-bb[0])*scale,(bb[3]-p[1])*scale)
    for o in board.fills+board.obstacles:
        col="#144b36" if o["net"]=="GND" else "#743064"
        mask=Image.new("1",im.size,0);d=ImageDraw.Draw(mask)
        for p in o["paths"]:
            if not overlap(bbox(fp(p)),bb):continue
            d.polygon([xy(q) for q in fp(p)],fill=pc.Area(p)>0)
        im.paste(Image.new("RGB",im.size,col),(0,0),mask)
    d=ImageDraw.Draw(im);font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",18)
    colors=["#ffeb6e","#76d5ff","#ffae71","#a0ffb0","#f699ff","#eeeeee","#b7c4ff","#ff7777","#73ede3","#d8ca72"]
    for r,c in zip(results,colors):
        if "signalRoute" not in r:continue
        d.line([xy(q) for q in r["signalRoute"]["pointsMm"]],fill=c,width=max(1,round(WIDTH*scale)))
        for pn,p in r["requiredWorldPads"].items():
            d.polygon([xy(q) for q in fp(rectangle(p["xyMm"],r["axisOfPositiveLocalX"]))],fill=c if pn=="1" else "#55ed9d",outline="white",width=2)
        d.text(xy(r["centerXYmm"]),r["ref"],font=font,fill=c)
    im.save(path)


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED_SHA
    board=Board()
    # Dense interior first; free exterior sites are reserved for outer balls.
    order=["ADC2_INP13","ADC2_INP12","ADC3_INP6","ADC3_INP7","ADC3_INP2","ADC1_INP16","ADC1_INP1","ADC1_INP0","ADC2_INP3","ADC3_INP8"]
    results=[]
    for n in order:
        ch=next(c for c in board.inv if c["net"]==n)
        r=board.search(ch)
        results.append(r)
        if "signalRoute" in r:board.accept(r)
        (HERE/"bottom-bucket-routing-progress.json").write_text(json.dumps({"sourceSha256":EXPECTED_SHA,"channels":results},indent=2)+"\n",encoding="utf8")
        render(board,results,HERE/"bottom-bucket-routing-progress.png")
    report={"schema":"adc10-bottom-bucket-routing-20261018-v1","readOnly":True,"nativeCallsPerformed":False,"sourcePath":str(SOURCE),"sourceSha256":EXPECTED_SHA,"clearanceMm":CLR,"traceWidthMm":WIDTH,"unchangedRuleMinimumWidthMm":4.0157*MM,"routeGridMm":GRID,"additionalAnalysisMarginMm":MARGIN,"channels":results,"obstacles":{"objects":len(board.obstacles),"localGroundFills":len(board.fills),**board.counts},"status":"OFFLINE_DATA_MANIFEST_REQUIRES_NATIVE_DRC","manufacturingReady":False,"next":"Generate local GND hole-union modifications and independently validate every route/pad pair, then native calibrated placement and strict DRC."}
    (HERE/"bottom-bucket-routing-manifest.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"solved":sum("signalRoute" in r for r in results),"total":len(results),"report":str(HERE/"bottom-bucket-routing-manifest.json")}),flush=True)


if __name__=="__main__":main()
