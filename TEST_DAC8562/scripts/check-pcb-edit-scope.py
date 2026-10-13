"""Reject unintended placement or copper edits outside the reviewed Q3 area."""
import importlib.util,json,math,sys
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py')
io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
sys.path.insert(0,str(root/'.tools/pcb-python'))
from shapely.geometry import LineString,Point,Polygon,box
from shapely.ops import unary_union
read=lambda p:json.loads(p.read_text(encoding='utf8'))
before=next(iter(io.documents(read(root/'output/readability/before-pcb.json')['source']).values()))
after=next(iter(io.documents(read(root/'output/readability/pcb-native-review.json')['source']).values()))
allowed=box(26/.0254,52/.0254,34/.0254,62/.0254)
epsilon=.03 # mil; excludes insignificant native coordinate rounding
def geometry(doc):
    groups=defaultdict(list)
    def contour(c):
        assert c[2]=='L';v=c[:2]+c[3:];return list(zip(v[::2],v[1::2]))
    for (t,i),(_,p) in doc['records'].items():
        net=p.get('netName');layer=p.get('layerId')
        if t=='LINE' and layer in (1,2) and net:
            g=LineString([(p['startX'],p['startY']),(p['endX'],p['endY'])]).buffer(p['width']/2,quad_segs=8)
        elif t=='VIA' and net:
            g=Point(p['centerX'],p['centerY']).buffer(p['viaDiameter']/2,quad_segs=16);layer=12
        elif t=='FILL' and layer in (1,2) and net:
            g=Polygon(contour(p['path'][0]),[contour(c) for c in p['path'][1:]])
        else:continue
        groups[(net,layer)].append(g)
    return {k:unary_union(v) for k,v in groups.items()}
ba,aa=io.attrs(before),io.attrs(after)
positions=0
for (t,i),(_,p) in before['records'].items():
    if t!='COMPONENT':continue
    q=after['records'][(t,i)][1]
    assert ba[i]['Designator']==aa[i]['Designator']
    assert all(abs(p[k]-q[k])<epsilon for k in ('x','y','angle'))
    if ba[i].get('Footprint')!=aa[i].get('Footprint'):assert ba[i]['Designator']=='Q3'
    positions+=1
assert positions==154
for key in set(before['records'])|set(after['records']):
    if key[0]!='PAD_NET':continue
    a=before['records'].get(key,(None,None))[1];b=after['records'].get(key,(None,None))[1]
    if a!=b:assert json.loads(key[1])[1]=='1e58e2330359a121'
b,a=geometry(before),geometry(after);changes=[]
for k in set(b)|set(a):
    bg=b.get(k,Polygon());ag=a.get(k,Polygon())
    delta=ag.difference(bg.buffer(epsilon)).union(bg.difference(ag.buffer(epsilon)))
    if delta.area<1e-8:continue
    assert k[0] in ('VNEG12','GND'),('Unapproved net',k)
    assert delta.difference(allowed).area<1e-8,('Change outside Q3',k,delta.bounds)
    changes.append({'net':k[0],'layer':k[1],'changedCopperAreaMm2':delta.area*.0254**2})
result={'passed':True,'all154ComponentPositionsAndAnglesUnchanged':True,
        'onlyChangedFootprint':'Q3','changedPadMappingsOnlyQ3':True,
        'physicalTrackViaFillChangesConfinedMm':[26,52,34,62],
        'coordinateToleranceMil':epsilon,'physicalCopperChanges':changes}
(root/'output/final-review/pcb-edit-scope-audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
