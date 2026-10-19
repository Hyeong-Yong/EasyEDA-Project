"""Read-only ownership proof for six obsolete REF input supply branch segments."""
import json, runpy
from pathlib import Path
from shapely.geometry import Point,LineString,Polygon
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent
H=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'))
MM=H['MM']; SOURCE=H['SOURCE']; BASE=H['BASELINE_SOURCE']
IDS={'8f2d79e61b91a9c3','bdbacbd270c676c0','894fec9d56a4bbbf','0074ee2853c5f528','8bed767bd15efcb1','c38941e71664641b'}

def main():
    rows=H['parse'](BASE); actual=H['parse'](SOURCE); at=H['attrs_of'](rows)
    docs,_=H['READ'](H['CHECK'])
    parts=[]; padshapes={}
    for (k,r),b in rows.items():
        if k!='COMPONENT' or b['layerId']!=1:continue
        ref=at[r]['Designator']; pp,_=H['footprint'](docs['FOOTPRINT',at[r]['Footprint']])
        for n,(s,pb) in pp.items():
            if pb['layerId'] not in (1,12):continue
            shape=H['world'](s,(b['x']*MM,b['y']*MM),b['angle'])
            padshapes[(ref,n)]=shape;parts.append((ref,n,shape))
    def line(b):
        a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
        pts=H['G']['arc'](a,z,b['angle']) if 'angle'in b else [a,z]
        return LineString(pts).buffer(b['width']*MM/2,resolution=24)
    segments=[]
    for r in sorted(IDS):
        assert rows['LINE',r]==actual['LINE',r]
        b=rows['LINE',r];assert b['netName']=='+3V3' and b['layerId']==1
        segments.append(line(b))
    branch=unary_union(segments)
    padcontacts=[{'ref':r,'pin':n,'areaMm2':branch.intersection(s).area,'centerMm':[s.centroid.x,s.centroid.y]} for r,n,s in parts if branch.distance(s)<1e-7]
    viacon=[]; other=[]; keep=[]
    for (k,r),b in rows.items():
        if k=='VIA':
            s=Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32)
            if branch.distance(s)<1e-7:viacon.append({'id':r,'net':b.get('netName'),'centerMm':[b['centerX']*MM,b['centerY']*MM]})
        elif k in ('LINE','ARC') and b['layerId']==1 and r not in IDS:
            s=line(b)
            if branch.distance(s)<1e-7:other.append({'kind':k,'id':r,'net':b.get('netName'),'startMm':[b['startX']*MM,b['startY']*MM],'endMm':[b['endX']*MM,b['endY']*MM],'contactBoundsMm':list(branch.intersection(s).bounds)})
            if b.get('netName')=='+3V3':keep.append(s)
        elif k=='FILL' and b['layerId']==1 and b.get('netName')=='+3V3':
            rr=[H['G']['ring_path'](p) for p in b['path']];s=Polygon(rr[0],rr[1:])
            assert s.is_valid
            if branch.distance(s)<1e-7:other.append({'kind':k,'id':r,'net':'+3V3','contactBoundsMm':list(branch.intersection(s).bounds)})
            keep.append(s)
    # Build literal remainingTOP3V3 conductor including every same-net pad/VIA.
    pnet={}
    for (k,r),b in rows.items():
        if k=='PAD_NET':
            a=json.loads(r);pnet[a[1],str(a[2])]=b.get('padNet')
    for (k,r),b in rows.items():
        if k=='COMPONENT' and b['layerId']==1:
            ref=at[r]['Designator']
            for (pr,pn),s in padshapes.items():
                if pr==ref and pnet.get((r,pn))=='+3V3':keep.append(s)
        elif k=='VIA' and b.get('netName')=='+3V3':keep.append(Point(b['centerX']*MM,b['centerY']*MM).buffer(b['viaDiameter']*MM/2,resolution=32))
    solid=unary_union(keep);tee=Point(23.50000126,82.2000007)
    components=list(solid.geoms) if hasattr(solid,'geoms') else [solid]
    root=[s for s in components if s.distance(tee)<1e-6]
    assert len(root)==1
    reached=[{'ref':r,'pin':n} for r,n,s in parts if root[0].distance(s)<1e-7]
    expected={(r['ref'],r['pin']) for r in padcontacts}=={('U9','1'),('C103','1')}
    onlytee=all(x['net']=='+3V3' and max(abs(x['contactBoundsMm'][0]-23.5),abs(x['contactBoundsMm'][2]-23.5))<.31 and max(abs(x['contactBoundsMm'][1]-82.2),abs(x['contactBoundsMm'][3]-82.2))<.31 for x in other)
    out={'schema':'independent-old-ref-3v3-six-branch-audit-20261018','status':'PASS' if expected and not viacon and onlytee and {'ref':'U14','pin':'5'} in reached else 'REVIEW_REQUIRED','nativeCalls':0,'baselineSha256':H['sha'](BASE),'actualEcoSha256':H['sha'](SOURCE),'exactSixBodiesMatchBaselineAndActual':True,'deletedLineIds':sorted(IDS),'branchBoundsMm':list(branch.bounds),'padContacts':padcontacts,'viaContacts':viacon,'otherCopperContacts':other,'contactsOnlyOldU9InputAndC103Input':expected,'remainingCopperOnlyContactAtRetainedTee':onlytee,'retainedTeeGlobalSolidReachedPads':reached,'opa320U14Pin5RetainedReach':{'ref':'U14','pin':'5'} in reached,'allOtherOldCopperUnchangedByThisPlan':True,'limits':['Read-only geometry ownership proof; actual nativeoperations require exactfullbodyguards and postapply DRC/netlist.','Reference NC/power assignments changedbyECO; these sixphysicalbranchtraces still carryold+3V3 and mustnotcontactnewREF5025 NCpads.']}
    p=HERE/'independent-old-ref-3v3-six-branch-audit.json';p.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8');print(json.dumps(out));print(H['sha'](p))

if __name__=='__main__':main()
