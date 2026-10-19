"""Offline eight-part commonpower loop refinement; all prior files preserved."""
import copy,json,runpy
from pathlib import Path
from shapely.geometry import Point,LineString,Polygon,box
from shapely.strtree import STRtree
HERE=Path(__file__).resolve().parent
H=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'));MM=H['MM'];CLR=H['CLR']
BASE=HERE/'independent-pcb-placement-short-negative-variant-v2.json'
OUT=HERE/'independent-pcb-placement-short-negative-commonpower-v3-proposal.json'
CHANGES={'U30':((31.0,29.8),0),'U31':((38.0,29.8),0),'C150':((27.7,29.8),90),'R197':((27.7,33.6),270),'C151':((31.0,26.8),180),'C152':((34.7,29.8),90),'C153':((41.5,30.0),90),'D20':((30.8,33.2),180)}

def main():
    assert H['sha'](BASE)=='6c28f76d936bfb004411455abab9127ba88e4004ce3ed5aae2defc66b8fed51f'
    p=json.loads(BASE.read_text(encoding='utf8'));rows=H['parse'](H['SOURCE']);at=H['attrs_of'](rows);docs,_=H['READ'](H['CHECK'])
    ii=json.loads((HERE/'routing/exact-old-copper-isolation-post-eco-manifest.json').read_text(encoding='utf8'));deleted={(o['type'],o['id']) for o in ii['operations'] if o['action']=='delete'}
    moving={x['componentId'] for x in p['edits']};courts=[];obs=[];gnd=[]
    def add(k,r,n,s):obs.append((k,r,n,s))
    for (k,r),b in rows.items():
        if k=='COMPONENT' and b['layerId']==1 and r not in moving:
            pp,e=H['footprint'](docs['FOOTPRINT',at[r]['Footprint']]);xy=[b['x']*MM,b['y']*MM]
            courts.append((at[r]['Designator'],H['world'](e,xy,b['angle'])))
            for n,(s,pb) in pp.items():
                if pb['layerId'] in (1,12):add('PAD',r+':'+n,'',H['world'](s,xy,b['angle']))
        elif k=='VIA':add(k,r,b.get('netName'),Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32))
        elif k in ('LINE','ARC') and b['layerId']==1 and (k,r) not in deleted:
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM);pts=H['G']['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
            add(k,r,b.get('netName'),LineString(pts).buffer(b['width']*MM/2,resolution=16))
        elif k=='FILL' and b['layerId']==1:
            rr=[H['G']['ring_path'](q) for q in b['path']];s=Polygon(rr[0],rr[1:])
            if s.is_valid:
                if b.get('netName')=='GND':gnd.append((r,s))
                elif b.get('netName')!='ADC_BIAS_2V5':add(k,r,b.get('netName'),s)
    cooked=[]
    for q in p['edits']:
        q=copy.deepcopy(q);pp,e=H['footprint'](docs['FOOTPRINT',q['footprintUuid']])
        if q['ref'] in CHANGES:
            xy,a=CHANGES[q['ref']];q.update(xyMm=list(xy),angle=a,set={'x':xy[0]/MM,'y':xy[1]/MM,'rotation':a,'layer':1})
            q['pads']=[{'number':n,'net':next(z['net'] for z in q['pads'] if z['number']==n),'centerMm':[H['world'](s,xy,a).centroid.x,H['world'](s,xy,a).centroid.y],'boundsMm':list(H['world'](s,xy,a).bounds)} for n,(s,pb) in pp.items()]
            q['conservativeCourtBoundsMm']=list(H['world'](e,xy,a).bounds)
            q['requiresOldAFEGeometryRework']=[]
            q['requiresLocalTopGroundVoidIds']=sorted({fid for n,(s,pb) in pp.items() for fid,fs in gnd if H['world'](s,xy,a).buffer(CLR).intersects(fs)})
        cooked.append(q)
        courts.append((q['ref'],H['world'](e,q['xyMm'],q['angle'])))
        for n,(s,pb) in pp.items():add('PLACED_PAD',q['ref']+':'+n,next(z['net'] for z in q['pads'] if z['number']==n),H['world'](s,q['xyMm'],q['angle']))
    violations=[];courtviol=[];details=[]
    for q in cooked:
        if q['ref'] not in CHANGES:continue
        env=box(*q['conservativeCourtBoundsMm'])
        for ref,s in courts:
            if ref!=q['ref'] and env.intersects(s):courtviol.append({'ref':q['ref'],'other':ref,'areaMm2':env.intersection(s).area})
        for pad in q['pads']:
            s=box(*pad['boundsMm'])
            for k,r,n,z in obs:
                if k=='PLACED_PAD' and r.startswith(q['ref']+':'):continue
                if n!=pad['net'] and s.distance(z)<CLR:violations.append({'ref':q['ref'],'pin':pad['number'],'net':pad['net'],'other':[k,r,n],'distanceMm':s.distance(z)})
        details.append({'ref':q['ref'],'xyMm':q['xyMm'],'angle':q['angle'],'pads':q['pads']})
    assert not violations and not courtviol,{'copper':violations,'court':courtviol}
    assert sum(a!=b for a,b in zip(p['edits'],cooked))==len(CHANGES)
    p.update(edits=cooked,schema='adc10-labtool-placement-shortnegative-commonpower-v3-proposal',status='OFFLINE_8PART_COMMONPOWER_REFINEMENT_AWAITING_ROOT_AND_ROUTE_REVIEW',v3ParentPath=str(BASE),v3ParentSha256=H['sha'](BASE),v3OnlyChangedRefs=sorted(CHANGES),v3Checks={'literalCopperConflicts':violations,'courtyardConflicts':courtviol,'other99EditsExactV2':True,'nativeCalls':0,'details':details})
    OUT.write_text(json.dumps(p,indent=2,ensure_ascii=False)+'\n',encoding='utf8');print(json.dumps({'path':str(OUT),'sha256':H['sha'](OUT),'details':details}))

if __name__=='__main__':main()
