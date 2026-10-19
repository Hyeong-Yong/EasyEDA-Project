"""Locally adjust the initial layout using EasyEDA's measured footprint envelopes."""
import itertools,json,math
from pathlib import Path
out=Path(__file__).resolve().parents[1]/'output/pcb-two-zone'
v=json.loads((out/'native-placement.json').read_text(encoding='utf8'))
orig=json.loads((out/'initial-placement.json').read_text(encoding='utf8'))
manual={'J1':(16,95),'J2':(95.85,87),'C22':(91,87),'U5':(52,87),'U6':(52,75),'U101':(35,27),
        'D3':(94,81,0),'D102':(94,25,0),'D101':(28,27),'R1':(21.6,85.8,0),'R2':(25,85.8,180),
        'C1':(20,88.6),'C5':(24,88.2,0),'C4':(27.7,83),'C3':(28,85.7),'R3':(27.7,79.8,180),'R4':(27.7,77.7,0),
        'C28':(47.05,89.5,180),'C29':(48.1,79,180),'R22':(43,82),'C27':(43,80),'R23':(46.4,82),
        'C15':(38.2,83,180),'C13':(40.8,91.7),'C14':(44.9,91.7),'C24':(57,91,180),'C16':(61,91),'C17':(65,91.5),
        'L1':(13.75,83.75),'Q1':(7.8,84,0),'C6':(9,80,270),'C7':(18.5,80,270),
        'D1':(26,90,270),'C9':(30,93),'C10':(36,93),'C1':(20.5,90.5),'C2':(27.7,81.85,180),'C3':(30.5,86.1),'C4':(27.7,84),
        'C5':(22.5,88.2),'L2':(33.25,80.75),'D2':(27,73.25,270)}
envelopes={}
for c in v['components']:
    n=c['designator'];b=c['bbox'];e=[b['minX']*.0254-c['x']*.0254,b['minY']*.0254-c['y']*.0254,b['maxX']*.0254-c['x']*.0254,b['maxY']*.0254-c['y']*.0254]
    angle=manual.get(n,(0,0,orig[n]['angle']))[2] if len(manual.get(n,()))==3 else orig[n]['angle']
    rot=math.radians(angle-c['angle']);pts=[(x*math.cos(rot)-y*math.sin(rot),x*math.sin(rot)+y*math.cos(rot)) for x,y in itertools.product([e[0],e[2]],[e[1],e[3]])]
    envelopes[n]=[min(x for x,y in pts),min(y for x,y in pts),max(x for x,y in pts),max(y for x,y in pts)]
def box(n,x,y):
    a,b,c,d=envelopes[n];return x+a,y+b,x+c,y+d
placed={};boxes={};changes=[]
def priority(n):
    power=['L1','L2','D1','D2','Q1','C6','C7','C8','C9','C10','C11','C12']
    controllers=['R1','R2','C1','R3','R4','C2','C4','C3','C5','C13','C14','C15','R22','R23','C27','C16','C17','C24','C28','C29']
    return (0 if n.startswith('J') else 1 if n.startswith(('U','K')) else 2 if n in power else 3 if n in controllers else 4 if n.startswith(('L','D','Q')) else 5 if n.startswith('C') else 6,power.index(n) if n in power else controllers.index(n) if n in controllers else n)
for name in sorted(orig,key=priority):
    p=orig[name];coords=manual.get(name,(p['xMm'],p['yMm']));x0,y0=coords[:2];angle=coords[2] if len(coords)==3 else p['angle']
    gap=.4
    def valid(x,y):
        a,b,c,d=box(name,x,y)
        if not name.startswith('J') and (a<1 or b<1 or c>99 or d>99):return False
        if p['zone']=='DAC8562' and b<52:return False
        if p['zone']=='DAC_MCU' and d>46.5:return False
        for q in boxes.values():
            if min(c,q[2]+gap)>max(a,q[0]-gap) and min(d,q[3]+gap)>max(b,q[1]-gap):return False
        for hx,hy in [(5,5),(95,5),(5,95),(95,95)]:
            dx=max(a-hx,0,hx-c);dy=max(b-hy,0,hy-d)
            if math.hypot(dx,dy)<3.8:return False
        return True
    candidates=[(x0,y0)]
    for radius in range(1,61 if name.startswith('D') else 37):
        r=radius*.25
        candidates.extend((x0+dx*.25,y0+dy*.25) for dx in range(-radius,radius+1) for dy in [-radius,radius])
        candidates.extend((x0+dx*.25,y0+dy*.25) for dx in [-radius,radius] for dy in range(-radius+1,radius))
    options=[(math.hypot(x-x0,y-y0),x,y) for x,y in candidates if valid(x,y)]
    if not options:raise ValueError('No safe local position for '+name)
    _,x,y=min(options)
    placed[name]={**p,'xMm':x,'yMm':y,'angle':angle};boxes[name]=box(name,x,y)
    if (x,y)!=(p['xMm'],p['yMm']):changes.append({'name':name,'before':[p['xMm'],p['yMm']],'after':[x,y],'shiftMm':math.hypot(x-p['xMm'],y-p['yMm'])})
(out/'refined-placement.json').write_text(json.dumps(placed,indent=2),encoding='utf8')
(out/'placement-adjustments.json').write_text(json.dumps(changes,indent=2),encoding='utf8')
print(json.dumps({'changed':len(changes),'maxShiftMm':max(c['shiftMm'] for c in changes),'remainingOverlaps':[],'largestShifts':sorted(changes,key=lambda x:x['shiftMm'],reverse=True)[:8]},indent=2))
