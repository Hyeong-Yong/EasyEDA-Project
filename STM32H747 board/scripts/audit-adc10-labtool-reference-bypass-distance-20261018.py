"""Read-only weighted trace-centreline audit, same-net layer transitions explicit."""
import json,hashlib,math,heapq,runpy,argparse
from pathlib import Path
from collections import defaultdict
from shapely.geometry import Point,LineString
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/candidates/adc10-labtool-20261018';HERE=BASE/'routing';FP=HERE/'frozen-combined-routing-v2.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    global FP
    ap=argparse.ArgumentParser();ap.add_argument('--routes',type=Path);ap.add_argument('--output',type=Path);args=ap.parse_args()
    if args.routes:FP=args.routes
    r=json.loads(FP.read_text(encoding='utf8'));p=json.loads(Path(r['placementPath']).read_text(encoding='utf8'));pads={(e['ref'],a['number']):a for e in p['edits'] for a in e['pads']}
    net='+5V_AFE';lines=[x for x in r['newLineCreates'] if x['net']==net];vias=[x for x in r['newViaCreates'] if x['net']==net];graph=defaultdict(list)
    def node(layer,xy):return layer,round(xy[0],6),round(xy[1],6)
    def edge(a,b,w):graph[a].append((b,w));graph[b].append((a,w))
    for layer in (1,2):
        merged=unary_union([LineString([x['startXYmm'],x['endXYmm']]) for x in lines if x['layerId']==layer]);parts=list(merged.geoms) if merged.geom_type=='MultiLineString' else [merged]
        for s in parts:
            # Split at every proposed VIA centre and pad endpoint. Shape union
            # already nodes trace crossings and overlapping collinear lines.
            cuts=[0,s.length]
            for xy in [x['xyMm'] for x in vias]+[a['centerMm'] for a in pads.values() if a['net']==net]:
                if s.distance(Point(xy))<.00003:cuts.append(s.project(Point(xy)))
            cuts=sorted(set(round(x,8) for x in cuts))
            for a,b in zip(cuts,cuts[1:]):
                if b-a<.000001:continue
                pa=s.interpolate(a);pb=s.interpolate(b);edge(node(layer,(pa.x,pa.y)),node(layer,(pb.x,pb.y)),b-a)
    for v in vias:edge(node(1,v['xyMm']),node(2,v['xyMm']),0)
    def shortest(a,b):
        start=node(1,pads[a]['centerMm']);target=node(1,pads[b]['centerMm']);dist={start:0};prev={};queue=[(0,start)]
        while queue:
            d,u=heapq.heappop(queue)
            if d>dist[u]+1e-7:continue
            if u==target:
                route=[u]
                while u in prev:u=prev[u];route.append(u)
                return d,list(reversed(route))
            for v,w in graph[u]:
                nd=d+w
                if nd<dist.get(v,math.inf)-1e-7:dist[v]=nd;prev[v]=u;heapq.heappush(queue,(nd,v))
        return None,[]
    out=[]
    for cap in ['C103','C160','C156','C157']+[f'C{120+3*i}' for i in range(10)]:
        length,path=shortest(('U9','2'),(cap,'1'));out.append({'capacitor':cap,'U9Pin2XYmm':pads['U9','2']['centerMm'],'capacitorPin1XYmm':pads[cap,'1']['centerMm'],'pinToPinEuclideanMm':math.dist(pads['U9','2']['centerMm'],pads[cap,'1']['centerMm']),'traceCentrelineShortestPathMm':length,'pathNodesLayerXYmm':path})
    out.sort(key=lambda x:x['traceCentrelineShortestPathMm'] if x['traceCentrelineShortestPathMm'] is not None else math.inf)
    report={'routingSha256':sha(FP),'sourceSha256':r['sourceSha256'],'readOnly':True,'nativeCalls':0,'geometryChanged':False,'net':net,'method':'Literal same-net trace centreline lengths with same-layer crossings noded; +5AFE VIA centres explicitly connect TOP/Bottom at zero vertical cost. No straight-line teleport between disconnected capacitor pads. Pad-internal distance and vertical VIA barrel length are omitted, so values using VIAs are lower bounds.','results':out,'interpretation':'Geometry-only decoupling lead-length qualification; this does not measure noise. Compare capacitor value, local Ground return, VIA transitions and supply sharing in addition to connectivity.','nativeDrcOrMeasuredNoiseProof':False}
    target=args.output or HERE/'reference-bypass-weighted-distance-v2.json';target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({'target':str(target),'sha256':sha(target),'distances':[{k:v for k,v in a.items() if k!='pathNodesLayerXYmm'} for a in out[:5]]}))
if __name__=='__main__':main()
