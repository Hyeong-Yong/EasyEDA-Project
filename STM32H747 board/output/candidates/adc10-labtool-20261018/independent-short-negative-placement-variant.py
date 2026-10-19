"""Offline twenty-cap variant; never alters the frozen107-placement proposal."""
from __future__ import annotations
import copy
import json
import runpy
from pathlib import Path
from collections import defaultdict
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
H = runpy.run_path(str(HERE / 'independent-pcb-placement-proposal.py'))
ROOT, MM, CLR = H['ROOT'], H['MM'], H['CLR']
SOURCE = H['SOURCE']
FROZEN = HERE / 'independent-pcb-placement-rebased-eco-proposal.json'
OUT = HERE / 'independent-pcb-placement-short-negative-variant-v2.json'
REPORT = HERE / 'independent-short-negative-placement-screen-v2.json'

def main():
    assert H['sha'](FROZEN) == '40ef99b3dbb429a848bbe9235a335d98718fa482fb8643aa4b9b22cd26735e93'
    frozen = json.loads(FROZEN.read_text(encoding='utf8'))
    rows = H['parse'](SOURCE)
    attrs = H['attrs_of'](rows)
    docs, _ = H['READ'](H['CHECK'])
    edits = {p['ref']: p for p in frozen['edits']}
    pre = [97,98,99,106,107,108,109,110,111,112]
    moving = {f'C{x}' for x in pre} | {f'C{121+3*i}' for i in range(10)}
    fps = {r:H['footprint'](docs['FOOTPRINT',p['footprintUuid']]) for r,p in edits.items()}
    isolation = json.loads((HERE / 'routing/exact-old-copper-isolation-post-eco-manifest.json').read_text(encoding='utf8'))
    deleted = {(o['type'],o['id']) for o in isolation['operations'] if o['action']=='delete'}
    obstacles=[]; courts=[]; fills=[]; deleted_shapes=[]
    def add(k,r,n,s):
        if not s.is_empty: obstacles.append((k,r,n,s))
    for (k,r),b in rows.items():
        if k=='COMPONENT' and b['layerId']==1:
            ref=attrs[r].get('Designator')
            if ref in edits: continue
            pp,env=H['footprint'](docs['FOOTPRINT',attrs[r]['Footprint']])
            xy=(b['x']*MM,b['y']*MM)
            courts.append((ref,H['world'](env,xy,b['angle'])))
            for n,(s,pb) in pp.items():
                if pb['layerId'] in (1,12): add('PAD',r+':'+n,'',H['world'](s,xy,b['angle']))
        elif k=='VIA': add(k,r,b.get('netName'),Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32))
        elif k in ('LINE','ARC') and b['layerId']==1:
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
            pts=H['G']['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
            shape=LineString(pts).buffer(b['width']*MM/2,resolution=12)
            if (k,r) in deleted: deleted_shapes.append((k,r,shape))
            else: add(k,r,b.get('netName'),shape)
        elif k=='FILL' and b['layerId']==1:
            rings=[H['G']['ring_path'](p) for p in b['path']]
            shape=Polygon(rings[0],rings[1:])
            if shape.is_valid:
                fills.append((r,b.get('netName'),shape))
                if b.get('netName') not in ('GND','ADC_BIAS_2V5'): add(k,r,b.get('netName'),shape)
    for ref,p in edits.items():
        if ref in moving: continue
        pp,env=fps[ref]
        courts.append((ref,H['world'](env,p['xyMm'],p['angle'])))
        for n,(s,pb) in pp.items(): add('NEW_PAD',ref+':'+n,next(x['net'] for x in p['pads'] if x['number']==n),H['world'](s,p['xyMm'],p['angle']))
    oshapes=[x[3] for x in obstacles]; ot=STRtree(oshapes)
    cshapes=[x[1] for x in courts]; ct=STRtree(cshapes)
    chosen=[]; attempts=[]
    def evaluate(ref,xy,angle):
        pp,env=fps[ref]; env=H['world'](env,xy,angle)
        if not box(.4,.4,99.6,153.6).contains(env): return None,{'why':'board'}
        hit=[courts[int(i)][0] for i in ct.query(env) if env.intersects(cshapes[int(i)])]
        hit += [p['ref'] for p in chosen if env.intersects(p['_court'])]
        if hit:return None,{'why':'court','hits':hit}
        pads=[]; ground=set(); rework=set(); nearest=[]
        for n,(s,pb) in pp.items():
            s=H['world'](s,xy,angle); net=next(x['net'] for x in edits[ref]['pads'] if x['number']==n)
            q=s.buffer(CLR,join_style=2)
            hits=[(obstacles[int(i)][0],obstacles[int(i)][1],obstacles[int(i)][2],s.distance(oshapes[int(i)])) for i in ot.query(q) if q.intersects(oshapes[int(i)]) and net!=obstacles[int(i)][2]]
            hits += [('VARIANT_PAD',p['ref'],pn,s.distance(ps)) for p in chosen for pn,ps,pnet in p['_pads'] if net!=pnet and q.intersects(ps)]
            if hits:return None,{'why':'copper','pad':n,'net':net,'hits':hits}
            for fid,fnet,fs in fills:
                if fnet=='GND' and q.intersects(fs):ground.add(fid)
                elif fnet=='ADC_BIAS_2V5' and q.intersects(fs):rework.add(('FILL',fid))
            for dk,dr,ds in deleted_shapes:
                if q.intersects(ds):rework.add((dk,dr))
            pads.append((n,s,net))
        p=copy.deepcopy(edits[ref]); p.update(xyMm=list(xy),angle=angle,set={'x':xy[0]/MM,'y':xy[1]/MM,'rotation':angle,'layer':1},pads=[{'number':n,'net':net,'centerMm':[s.centroid.x,s.centroid.y],'boundsMm':list(s.bounds)} for n,s,net in pads],conservativeCourtBoundsMm=list(env.bounds),requiresLocalTopGroundVoidIds=sorted(ground),requiresOldAFEGeometryRework=sorted([list(k) for k in rework]))
        p['_court']=env;p['_pads']=pads
        return p,None
    # Joint search keeps all remaining87 parts exact. First try the documented
    # left/below pocket, then tight alternatives. Every row is screened separately.
    for i in range(10):
        row=140-14*i; nr=f'C{121+3*i}'; pr=f'C{pre[i]}'
        found=False; failures=[]
        negxy=[(7.9,row-5.4)]+[(round(x,2),round(row-y,2)) for x in (7.7,7.8,7.9,8.0,8.1,8.2,8.3,8.4,8.5,8.6,8.7,8.8,8.9) for y in (5.2,5.3,5.4,5.5,5.6,5.7,5.8,5.9,6.0)]
        prexy=[(10.2,row-7.5)]+[(round(x,2),round(row-y,2)) for x in (9.4,9.6,9.8,10,10.2,10.4,10.6,10.8,11) for y in (7.0,7.2,7.4,7.5,7.6,7.8,8.0)]
        for nxy in negxy:
            for na in (0,90,180,270):
                pn,err=evaluate(nr,nxy,na)
                if not pn:
                    if len(failures)<10:failures.append({'ref':nr,'xy':nxy,'angle':na,**err})
                    continue
                ncenter=next(p['centerMm'] for p in pn['pads'] if p['net']=='-3V_AFE')
                vn=(9.9,row-3.5)
                direct=((ncenter[0]-vn[0])**2+(ncenter[1]-vn[1])**2)**.5
                if direct>2.8:continue
                chosen.append(pn)
                for pxy in prexy:
                    for pa in (0,90,180,270):
                        pc,er=evaluate(pr,pxy,pa)
                        if pc:
                            chosen.append(pc); found=True
                            attempts.append({'channel':i+1,'rowMm':row,'negativeRef':nr,'preRef':pr,'negativeCapSignalPadMm':ncenter,'opaNegativePadMm':list(vn),'directDistanceMm':direct,'routeLengthNotYetProven':True,'negativeXyMm':list(nxy),'negativeAngle':na,'preXyMm':list(pxy),'preAngle':pa})
                            break
                    if found:break
                if found:break
                chosen.pop()
            if found:break
        assert found, {'row':row,'failures':failures}
    out=copy.deepcopy(frozen)
    changed={p['ref']:{k:v for k,v in p.items() if not k.startswith('_')} for p in chosen}
    out['edits']=[changed.get(p['ref'],p) for p in frozen['edits']]
    out['schema']='adc10-labtool-independent-pcb-placement-short-negative-variant-20261018-v2'
    out['status']='OFFLINE_SHORT_NEGATIVE_CAP_VARIANT_AWAITING_EXACT_ROUTER_AND_GND_PROOF'
    out['frozenParentPath']=str(FROZEN);out['frozenParentSha256']=H['sha'](FROZEN)
    out['variantOnlyChangedRefs']=sorted(changed)
    out['v2MetadataQualification']='20capcoordinates/pads/courts EXACT v1; only their per-entry oldCuintersectioninventory recomputed from authoritative179-opisolation. V1 remains untouched.'
    out['shortNegativeScreen']=attempts
    out['conditions'].append('This separatevariant movesonly10negative100nF and10input10nFcapacitors. <3mmactualnegativeleadisNOTyetproved; routermustverifyexactworldpadrouteandlocalGNDreturn, allprotectedVIAsremainunchanged.')
    OUT.write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    v1=json.loads((HERE/'independent-pcb-placement-short-negative-variant-v1.json').read_text(encoding='utf8'))
    v1geom=all(all(p[k]==q[k] for k in ('xyMm','angle','set','pads','conservativeCourtBoundsMm')) for p,q in zip(v1['edits'],out['edits']))
    assert v1geom
    report={'schema':'independent-short-negative-placement-screen-v2','status':'PLACEMENT_SCREEN_PASS_ROUTE_AND_RETURN_PENDING','nativeCalls':0,'sourceSha256':H['sha'](SOURCE),'frozenParentSha256':H['sha'](FROZEN),'variantSha256':H['sha'](OUT),'modifiedRefCount':len(changed),'unchangedEdits':sum(p==next(q for q in out['edits'] if q['ref']==p['ref']) for p in frozen['edits']),'geometryExactV1':v1geom,'obstacles':len(obstacles),'courts':len(courts),'clearanceMm':CLR,'channels':attempts,'physicalGroundReturnProven':False,'routeLengthUnder3MmProven':False}
    REPORT.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps({'path':str(OUT),'sha256':H['sha'](OUT),'report':str(REPORT),'channels':attempts},ensure_ascii=False))

if __name__=='__main__':main()
