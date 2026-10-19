from collections import defaultdict, Counter
import json
import math
from pathlib import Path
from inspect_standard_meshes import load,bounds

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
vertices,faces,materials=load(ROOT/'STM32H747_calibrated407_STM32H747_calibrated407')
plan=json.loads((ROOT/'sot23-5-3d-apply-plan.json').read_text())
inv={p['ref']:p for p in json.loads((ROOT/'inventory/components-437.json').read_text())}
refs=[e['ref'] for e in plan['entries']]
parent={}
def find(i):
    parent.setdefault(i,i)
    if parent[i]!=i:
        parent[i]=find(parent[i])
    return parent[i]
for _,_,ids in faces:
    for i in ids:
        parent[find(i)]=find(ids[0])
pieces=defaultdict(list)
for f in faces:
    pieces[find(f[2][0])].append(f)
candidates=[]
for fs in pieces.values():
    if not 90<=len(fs)<=3000:
        continue
    ids=sorted({i for _,_,ff in fs for i in ff})
    box=bounds([vertices[i] for i in ids])
    if box[2]<-.01 or box[5]>2 or box[3]-box[0]>4 or box[4]-box[1]>4:
        continue
    center=[(box[k]+box[k+3])/2 for k in range(3)]
    dist,ref=min((math.dist(center[:2],[inv[r]['x_mm'],inv[r]['y_mm']]),r) for r in refs)
    if dist<2:
        candidates.append({'nearest_ref':ref,'distance':dist,'vertex_min':ids[0],'vertex_max':ids[-1],'faces':len(fs),'bbox_mm':box,
                           'center_mm':center,'size_mm':[box[k+3]-box[k] for k in range(3)],'materials':dict(Counter(m for m,_,_ in fs))})
data={'candidates':sorted(candidates,key=lambda p:p['vertex_min']),'materials':materials}
full_models=[]
for entry in plan['entries']:
    ref=entry['ref']
    body=next(p for p in candidates if p['nearest_ref']==ref and p['faces']==1122)
    lo,hi=body['vertex_min'],body['vertex_min']+717
    fs=[f for f in faces if all(lo<=i<=hi for i in f[2])]
    ids={i for _,_,ff in fs for i in ff}
    box=bounds([vertices[i] for i in ids])
    subpieces=[]
    for pfs in pieces.values():
        first=pfs[0][2][0]
        if not lo<=first<=hi:
            continue
        pids={i for _,_,ff in pfs for i in ff}
        assert all(lo<=i<=hi for i in pids)
        pb=bounds([vertices[i] for i in pids])
        subpieces.append({'faces':len(pfs),'vertices':len(pids),'bbox_mm':pb,'center_mm':[(pb[k]+pb[k+3])/2 for k in range(3)],'materials':dict(Counter(m for m,_,_ in pfs))})
    full_models.append({'ref':ref,'vertex_range':[lo,hi],'faces':len(fs),'bbox_mm':box,'size_xyz_mm':[box[k+3]-box[k] for k in range(3)],
                        'center_xyz_mm':[(box[k]+box[k+3])/2 for k in range(3)],'pieces':subpieces})
data['full_models']=full_models
(HERE/'final407-sot235-pieces.json').write_text(json.dumps(data,indent=2)+'\n')
print(json.dumps(full_models[0],indent=2))
