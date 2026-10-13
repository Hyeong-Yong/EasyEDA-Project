"""Compare real PCB pad assignments and copper connectivity, not a cached netlist."""
import importlib.util,json,math,sys
from collections import defaultdict
from pathlib import Path
s=importlib.util.spec_from_file_location('m',Path(__file__).with_name('readability-model.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
sys.path.insert(0,str(m.ROOT/'.tools/pcb-python'))
from shapely.geometry import Point,LineString,Polygon,box
from shapely.affinity import rotate,translate,scale
from shapely.ops import unary_union
from shapely.strtree import STRtree
capture=json.loads((m.OUT/'pcb-native-review.json').read_text(encoding='utf8'))
doc=next(iter(m.io.documents(capture['source']).values()));aa=m.io.attrs(doc)
schematic=json.loads((m.OUT/'source-audit.json').read_text(encoding='utf8'))['pinNets']
padnets={}
for (t,i),(_,p) in doc['records'].items():
    if t=='PAD_NET':
        a=json.loads(i);padnets[(a[1],a[3])]=p['padNet']
def shape(p):
    a=p['defaultPad'];w,h=a['width'],a['height'];typ=a['padType']
    if typ=='ELLIPSE':g=scale(Point(0,0).buffer(1,quad_segs=24),w/2,h/2)
    elif typ=='RECT':g=box(-w/2,-h/2,w/2,h/2)
    elif typ in ['OVAL','ROUND']:g=box(-max(0,w-h)/2,-max(0,h-w)/2,max(0,w-h)/2,max(0,h-w)/2).buffer(min(w,h)/2,quad_segs=24)
    else:raise ValueError(typ)
    g=translate(g,p.get('padOffsetX',0),p.get('padOffsetY',0))
    return translate(rotate(g,p['padAngle'],origin=(0,0)),p['centerX'],p['centerY'])
nodes=[];padfail=[];padcount=0;lengths=defaultdict(float)
def add(net,layers,geom,pin=None):
    nodes.append({'net':net,'layers':layers,'geom':geom,'pin':pin})
for (t,i),(_,p) in doc['records'].items():
    if t!='COMPONENT':continue
    ref=aa.get(i,{}).get('Designator');fp=aa.get(i,{}).get('Footprint')
    if not ref or not fp:raise ValueError('Missing PCB part identity '+i)
    for (ft,fi),(_,pad) in m.LIB[fp]['records'].items():
        if ft!='PAD':continue
        q=dict(pad);r=math.radians(p['angle']);x,y=pad['centerX'],pad['centerY']
        q.update(centerX=p['x']+x*math.cos(r)-y*math.sin(r),centerY=p['y']+x*math.sin(r)+y*math.cos(r),padAngle=pad['padAngle']+p['angle'])
        net=padnets.get((i,fi),'');pin=ref+'.'+pad['num'];expected=schematic.get(pin,[])
        if ([net] if net else [])!=expected:padfail.append({'pin':pin,'schematic':expected,'pcb':net})
        padcount+=1
        if net:add(net,{1,2} if pad['layerId']==12 else {pad['layerId']},shape(q),pin)
for (t,i),(_,p) in doc['records'].items():
    net=p.get('netName');l=p.get('layerId')
    if t=='LINE' and l in [1,2] and net:
        pts=[(p['startX'],p['startY']),(p['endX'],p['endY'])]
        add(net,{l},LineString(pts).buffer(p['width']/2,quad_segs=8));lengths[net]+=math.dist(*pts)*.0254
    elif t=='VIA' and net:add(net,{1,2},Point(p['centerX'],p['centerY']).buffer(p['viaDiameter']/2,quad_segs=16))
    elif t=='FILL' and net and l in [1,2]:
        def contour(c):
            assert c[2]=='L',c[:4]
            v=c[:2]+c[3:];return list(zip(v[::2],v[1::2]))
        add(net,{l},Polygon(contour(p['path'][0]),[contour(c) for c in p['path'][1:]]))
roots=list(range(len(nodes)))
def root(i):
    while roots[i]!=i:roots[i]=roots[roots[i]];i=roots[i]
    return i
tree=STRtree([n['geom'] for n in nodes]);shorts=[]
for i,n in enumerate(nodes):
    for j in tree.query(n['geom'].buffer(.03)):
        j=int(j)
        if j<=i or not(n['layers']&nodes[j]['layers']):continue
        if n['geom'].distance(nodes[j]['geom'])>.03:continue
        if n['net']!=nodes[j]['net']:
            if n['geom'].intersects(nodes[j]['geom']):shorts.append([n['net'],nodes[j]['net'],n['pin'],nodes[j]['pin']])
        else:roots[root(j)]=root(i)
netgroups=defaultdict(lambda:defaultdict(list))
for i,n in enumerate(nodes):
    if n['pin']:netgroups[n['net']][root(i)].append(n['pin'])
disconnected={net:list(groups.values()) for net,groups in netgroups.items() if len(groups)>1}
before=json.loads((m.OUT/'before-pcb.json').read_text(encoding='utf8'))
unchanged=m.io.data_hash(next(iter(m.io.documents(before['source']).values())))==m.io.data_hash(doc)
bd=next(iter(m.io.documents(before['source']).values()));physical_changes=[]
for k in set(bd['records'])|set(doc['records']):
    a,b=bd['records'].get(k,(None,None))[1],doc['records'].get(k,(None,None))[1]
    if k[0]=='COMPONENT':a={k:v for k,v in a.items() if k!='attrs'};b={k:v for k,v in b.items() if k!='attrs'}
    if k[0] in ['COMPONENT','LINE','VIA','PAD','PAD_NET','FILL','POUR','POLY','REGION'] and a!=b:physical_changes.append(k)
result={'passed':not(padfail or shorts or disconnected),'physicalPadCount':padcount,'connectedPadCount':sum(bool(n['pin']) for n in nodes),'netCount':len(netgroups),'padNetDifferences':padfail,'copperShorts':shorts,'disconnectedNets':disconnected,'pcbUnchangedFromBeforeReadability':unchanged,'physicalGeometryChanges':physical_changes,'traceLengthMm':dict(sorted(lengths.items())),'method':'Footprints transformed from live project library; actual PAD_NET mapping; Cu track/pad/via/SOLID-fill physical intersections. Tolerance 0.03mil.'}
(m.OUT/'physical-pcb-audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('traceLengthMm','physicalGeometryChanges')},indent=2))
