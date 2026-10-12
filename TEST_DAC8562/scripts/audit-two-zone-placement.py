import itertools,json
from pathlib import Path
out=Path(__file__).resolve().parents[1]/'output/pcb-two-zone'
v=json.loads((out/'native-placement.json').read_text(encoding='utf8'))
expected=json.loads((out/'expected-pads.json').read_text(encoding='utf8'))
pos=json.loads((out/'placement.json').read_text(encoding='utf8'))
pads={p['id']:p for p in v['pads']};issues=[]
for p in expected:
    key=p['component']+p['id'];n=pads.get(key)
    if not n or n['net']!=p['net'] or abs(n['x']-p['centerX'])>1e-4 or abs(n['y']-p['centerY'])>1e-4:
        issues.append({'pin':p['designator']+'.'+p['num'],'expected':{k:p[k] for k in ['net','centerX','centerY']},'native':n})
placement=[]
for c in v['components']:
    e=pos.get(c['designator'])
    if not e or abs(c['x']*.0254-e['xMm'])>1e-4 or abs(c['y']*.0254-e['yMm'])>1e-4 or abs((c['angle']-e['angle']+180)%360-180)>1e-4:placement.append(c)
overlaps=[]
for a,b in itertools.combinations(v['components'],2):
    x,y=a['bbox'],b['bbox']
    if not x or not y: continue
    dx=min(x['maxX'],y['maxX'])-max(x['minX'],y['minX']);dy=min(x['maxY'],y['maxY'])-max(x['minY'],y['minY'])
    if dx>0 and dy>0:overlaps.append({'parts':[a['designator'],b['designator']],'overlapMm':[dx*.0254,dy*.0254]})
result={'components':len(v['components']),'pads':len(v['pads']),'padMismatch':issues,'placementMismatch':placement,'bboxOverlaps':overlaps}
(out/'placement-audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({**result,'bboxOverlaps':overlaps[:10],'overlapCount':len(overlaps)},indent=2))
