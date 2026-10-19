"""Place component references in nearby clear silkscreen space without moving copper."""
import importlib.util,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/pcb-two-zone'
spec=importlib.util.spec_from_file_location('cio',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
source=(out/'routed-source.txt').read_text(encoding='utf8');doc=next(iter(io.documents(source).values()))
v=json.loads((out/'native-placement.json').read_text(encoding='utf8'))
components={c['id']:c for c in v['components']};occupied=[]
def collide(b,q,gap=.12):return min(b[2],q[2]+gap)>max(b[0],q[0]-gap) and min(b[3],q[3]+gap)>max(b[1],q[1]-gap)
bodies={cid:tuple(c['bbox'][k]*.0254 for k in ['minX','minY','maxX','maxY']) for cid,c in components.items()}
for (typ,pid),(_,p) in doc['records'].items():
    if typ!='STRING':continue
    if p['text']=='DAC OUT A':p.update(x=82/.0254,y=91.5/.0254)
    if p['text']=='DAC OUT B':p.update(x=82/.0254,y=69/.0254)
    if p['text']=='MCU OUT A':p.update(x=90.5/.0254,y=40/.0254)
    x,y=p['x']*.0254,p['y']*.0254;h=p['fontSize']*.0254
    occupied.append((x,y,x+len(p['text'])*h*.63,y+h))
holes=[(5,5),(95,5),(5,95),(95,95)]
changes=[];unplaced=[]
labels=[(pid,p) for (typ,pid),(_,p) in doc['records'].items() if typ=='ATTR' and p.get('key')=='Designator' and p.get('valueVisible')]
for pid,p in sorted(labels,key=lambda item:(not str(item[1]['value']).startswith(('J','U','K')),str(item[1]['value']))):
    c=components[p['parentId']];b=bodies[c['id']];x,y=c['x']*.0254,c['y']*.0254
    h=.762;w=len(p['value'])*h*.63+.15
    candidates=[(x-w/2,b[3]+.25),(x-w/2,b[1]-.25-h),(b[0]-.25-w,y-h/2),(b[2]+.25,y-h/2)]
    for r in [.5,1,1.5,2,2.5,3,4,5]:
        for dx,dy in [(0,1),(0,-1),(-1,0),(1,0),(-1,1),(1,1),(-1,-1),(1,-1)]:candidates.append((x+dx*r-w/2,y+dy*r-h/2))
    valid=[]
    for tx,ty in candidates:
        q=(tx,ty,tx+w,ty+h)
        if q[0]<.8 or q[1]<.8 or q[2]>99.2 or q[3]>99.2:continue
        if any(collide(q,z) for z in bodies.values()) or any(collide(q,z,.10) for z in occupied):continue
        if any(math.hypot(max(q[0]-hx,0,hx-q[2]),max(q[1]-hy,0,hy-q[3]))<3.6 for hx,hy in holes):continue
        valid.append((math.hypot(tx+w/2-x,ty+h/2-y),tx,ty,q))
    if not valid:unplaced.append(p['value']);continue
    dist,tx,ty,q=min(valid);occupied.append(q);p.update(x=tx/.0254,y=ty/.0254,fontSize=30,strokeWidth=5,angle=0)
    changes.append({'name':p['value'],'xMm':tx,'yMm':ty,'distanceMm':dist})
(out/'draft-final-source.txt').write_text(io.source_of(doc),encoding='utf8',newline='\n')
(out/'silkscreen-placement.json').write_text(json.dumps({'placed':changes,'unplaced':unplaced},indent=2),encoding='utf8')
print(json.dumps({'labelsPlaced':len(changes),'unplaced':unplaced,'maxDistanceMm':max(x['distanceMm'] for x in changes)},indent=2))
