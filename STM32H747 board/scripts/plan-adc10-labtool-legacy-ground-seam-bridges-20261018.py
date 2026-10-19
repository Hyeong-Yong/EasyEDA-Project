"""Offline candidate-only LINE bridges for four native unexpected GND errors."""
import json,runpy,hashlib,math
from pathlib import Path
from collections import Counter
from shapely.geometry import Point,LineString,box
from shapely.affinity import scale,rotate,translate
from shapely.ops import nearest_points
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018';MM=.0254
SRC=ROOT/'output/validation/native-adc10-pcb-labtool_copper_wire13-20261018.epru'
OUT=H/'routing/frozen-legacy-ground-four-line-corrective-addendum-v1.json'
M=runpy.run_path(str(H/'independent-pcb-placement-proposal.py'));FG=runpy.run_path(str(H/'ground/plan-local-static-fill-clearance.py'));FG['G']['arc'].__globals__['SAG']=.00001
FILLS=['70d49360e5e3892f','1d12bb8046962a4c','1e87af6d1a83be6a'];VIA='e0f0dcd1975e7708';CLR=.1535;W=.2032;LAYERS=(1,2,15,16,17,18)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def roundmm(p):return tuple(round(v/MM,4)*MM for v in p)
def main():
    assert not OUT.exists();assert sha(SRC)=='74d29fb7f5d3579cbf12ef085f26059cad63b86aff5a3dcf8dff8a0cfaf92bfb';rows=M['parse'](SRC);attrs=M['attrs_of'](rows);docs,_=M['READ'](M['CHECK']);pn={};obs=[];ground=[];holes=[];invalid=[]
    for(k,r),b in rows.items():
        if k=='PAD_NET':
            _,cid,num,pid=json.loads(r);pn[cid,pid]=b.get('padNet','')
    def add(kind,rid,net,layer,s,r=0):
        p={'kind':kind,'id':rid,'net':net or '', 'layerId':layer,'shape':s,'radius':r}
        (ground if net=='GND' else obs).append(p)
    def drill(p):
        h=p['hole'];w=h.get('width',0)*MM;ht=h.get('height',w/MM)*MM
        if h.get('holeType')=='SLOT':s=box(-w/2,-ht/2,w/2,ht/2);r=0;qualification='conservative rotated slot rectangle'
        else:s=Point(0,0);r=max(w,ht)/2;qualification='exact round drill'
        return translate(rotate(s,p.get('relativeAngle',0),origin=(0,0)),p['centerX']*MM,p['centerY']*MM),r,qualification
    for(k,rid),b in rows.items():
        n=b.get('netName','')
        if k=='FILL' and b.get('layerId') in LAYERS:
            s=FG['geom'](b['path'])
            if not s.is_valid:invalid.append({'id':rid,'layerId':b['layerId'],'boundsMm':s.bounds});continue
            add(k,rid,n,b['layerId'],s,.0001 if n!='GND' else 0)
        elif k in('LINE','ARC') and b.get('layerId') in LAYERS:
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM);s=LineString([a,z]) if k=='LINE' else LineString(FG['G']['arc'](a,z,b['angle']))
            add(k,rid,n,b['layerId'],s,b['width']*MM/2+(0 if k=='LINE' else .00001))
        elif k=='VIA':
            s=Point(b['centerX']*MM,b['centerY']*MM)
            for l in LAYERS:
                if l not in b.get('unusedInnerLayers',[]):add(k,rid,n,l,s,b['viaDiameter']*MM/2)
            holes.append({'id':rid,'shape':s,'radius':b['holeDiameter']*MM/2,'net':n,'centerMil':[b['centerX'],b['centerY']]})
        elif k=='COMPONENT':
            a=attrs[rid]
            def world(s):
                if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                return M['world'](s,(b['x']*MM,b['y']*MM),b['angle'])
            for(pk,pid),(_,p) in docs['FOOTPRINT',a['Footprint']].items():
                if pk!='PAD':continue
                if max((p.get('hole') or {}).get('width',0),(p.get('hole') or {}).get('height',0))>0:
                    s,r,q=drill(p);holes.append({'id':a['Designator']+':'+pid,'shape':world(s),'radius':r,'net':pn.get((rid,pid),''),'qualification':q})
                pl=p['layerId'];pl=3-pl if b['layerId']==2 and pl in(1,2) else pl
                if pl not in(1,2,12):continue
                d=p['defaultPad']
                if d.get('padType')=='POLYGON':s=M['local_pad'](p);r=.0001
                else:
                    w=d.get('width',d.get('diameter',0))*MM;ht=d.get('height',d.get('diameter',0))*MM
                    s=translate(rotate(box(-w/2,-ht/2,w/2,ht/2),p.get('padAngle',0),origin=(0,0)),p['centerX']*MM,p['centerY']*MM);r=0
                for l in(LAYERS if pl==12 else(pl,)):add('PAD',a['Designator']+':'+str(p['num'])+':'+pid,pn.get((rid,pid),''),l,world(s),r)
        elif k=='PAD' and max((b.get('hole') or {}).get('width',0),(b.get('hole') or {}).get('height',0))>0:
            s,r,q=drill(b);holes.append({'id':'BOARD:'+rid,'shape':s,'radius':r,'net':n,'qualification':q})
    assert len(holes)==863,len(holes)
    candidates=[];no=[]
    targets=[next(p for p in ground if p['kind']=='FILL' and p['id']==rid) for rid in FILLS]
    # The old unanchored via is independently bridged on TOP if a safe nearby
    # known-unflagged GND actor exists.  Same-net exact endpoint is intentional.
    vb=rows['VIA',VIA];targets.append({'kind':'VIA','id':VIA,'net':'GND','layerId':1,'shape':Point(vb['centerX']*MM,vb['centerY']*MM),'radius':vb['viaDiameter']*MM/2})
    for target in targets:
        shape=target['shape'];layer=target['layerId'];pool=[p for p in ground if p['layerId']==layer and p['id'] not in FILLS+[VIA] and p['kind'] in('FILL','VIA','PAD','LINE')]
        pool.sort(key=lambda p:shape.distance(p['shape'])-target['radius']-p['radius']);attempts=[]
        for other in pool[:80]:
            if shape.distance(other['shape'])>2:continue
            # Use inward cores so serialized endpoints overlap substantial raw
            # polygons, not merely their legacy 0.2mil border pen or tiny seam.
            a=shape.buffer(-.075) if target['kind']=='FILL' else shape
            if a.is_empty:a=shape.representative_point()
            b=other['shape'].buffer(-.075) if other['kind']=='FILL' else other['shape']
            if b.is_empty:b=other['shape'].representative_point()
            pa,pb=nearest_points(a,b)
            shifts=[(0,0)]
            if target['kind']==other['kind']=='FILL':
                shifts += [(i*.025,0) for i in range(-12,13) if i] + [(0,i*.025) for i in range(-12,13) if i]
            for sx,sy in shifts:
                start,end=roundmm((pa.x+sx,pa.y+sy)),roundmm((pb.x+sx,pb.y+sy));line=LineString([start,end])
                if line.length<.000001:continue
                if not shape.buffer(target['radius']).covers(Point(start)) or not other['shape'].buffer(other['radius']).covers(Point(end)):continue
                gaps=[(line.distance(o['shape'])-W/2-o['radius'],o) for o in obs if o['layerId']==layer];gap,nearest=min(gaps,key=lambda t:t[0])
                badinvalid=[v for v in invalid if v['layerId']==layer and line.distance(box(*v['boundsMm']))-W/2<CLR]
                # Endpoint inside raw FILL is mandatory; border-pen contact is
                # not used to qualify this explicit addendum.
                overlap_a=shape.buffer(target['radius']).intersection(line.buffer(W/2)).area
                overlap_b=other['shape'].buffer(other['radius']).intersection(line.buffer(W/2)).area
                q={'key':'LEGACY_GND_SEAM_BRIDGE_'+str(len(candidates)+1),'targetKind':target['kind'],'targetId':target['id'],'targetLayer':layer,'anchoredCandidateKind':other['kind'],'anchoredCandidateId':other['id'],'net':'GND','layerId':layer,'widthMm':W,'widthMil':8,'startXYmm':start,'endXYmm':end,'startXYMil':[round(v/MM,4) for v in start],'endXYMil':[round(v/MM,4) for v in end],'lengthMm':line.length,'rawTargetCopperOverlapMm2':overlap_a,'rawAnchorCopperOverlapMm2':overlap_b,'foreignCopperMinimumConservativeGapMm':gap,'nearestForeignActor':{k:nearest[k] for k in('kind','id','net','layerId')},'invalidFillNear':badinvalid,'anchorNativeUnflaggedNotYetIndependentGraphProven':True,'passed':gap>=CLR and overlap_a>0 and overlap_b>0 and not badinvalid}
                attempts.append(q)
        feasible=sorted([q for q in attempts if q['passed']],key=lambda q:(round(q['lengthMm'],5),-q['foreignCopperMinimumConservativeGapMm']))
        if feasible:candidates.append(feasible[0])
        else:no.append({'targetId':target['id'],'attempts':attempts[:10]})
        print(json.dumps({'target':target['id'],'feasible':len(feasible),'best':feasible[0] if feasible else None}),flush=True)
    assert len(candidates)==4 and not no
    expected=[([1777.9528,4316.252],[1777.9528,4318.8976]),([1818.88,4322.1576],[1818.88,4316.2516]),([2078.8013,3116.24],[2078.8013,3110.334]),([2112.2047,3121.063],[2112.2047,3110.3344])]
    for c,(start,end) in zip(candidates,expected):
        assert c['startXYMil']==start and c['endXYMil']==end,'Do not silently change the separately reviewed candidate geometry'
        line=LineString([c['startXYmm'],c['endXYmm']]);ends=[c['startXYMil'],c['endXYMil']]
        ds=[{'id':d['id'],'gapMm':line.distance(d['shape'])-W/2-d['radius'],'intentionalSameNetExactViaEndpoint':d.get('net')=='GND' and d.get('centerMil') in ends,'qualification':d.get('qualification','exact round via drill')} for d in holes];ds.sort(key=lambda d:d['gapMm'])
        c['physicalDrillCountChecked']=len(ds);c['closestDrills']=ds[:5];c['unexpectedDrillIntrusions']=[d for d in ds if d['gapMm']<0 and not d['intentionalSameNetExactViaEndpoint']]
        c['noUnexpectedDrillIntrusions']=not c['unexpectedDrillIntrusions'];c['passed']=c['passed'] and c['noUnexpectedDrillIntrusions']
        c['coplanarForeignActorCountChecked']=sum(p['layerId']==c['layerId'] for p in obs)
    assert all(c['passed'] for c in candidates),'Unsafe selected bridge must not freeze'
    # New lines are mutually far apart; record literal cross-net interaction
    # policy: every addition is GND and thus has no cross-net pair of its own.
    lines=[{k:c[k] for k in('key','net','layerId','widthMm','widthMil','startXYmm','endXYmm','startXYMil','endXYMil')} for c in candidates]
    route=H/'routing/frozen-combined-routing-v5.json';anchor=H/'ground/wire12-partial-direct-actual-ground-without-fill-pen.json'
    guards=[]
    for c in candidates:
        for kind,rid in((c['targetKind'],c['targetId']),(c['anchoredCandidateKind'],c['anchoredCandidateId'])):
            body=rows[kind,rid];guards.append({'kind':kind,'id':rid,'bodySha256':hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'beforeBody':body})
    report={'schema':'legacy-ground-native-seam-frozen-four-line-corrective-addendum-v1','sourcePath':str(SRC),'sourceSha256':sha(SRC),'frozenParentRoutePath':str(route),'frozenParentRouteSha256':sha(route),'independentNominalGroundAuditPath':str(anchor),'independentNominalGroundAuditSha256':sha(anchor),'status':'FROZEN_EXACT_FOUR_LINE_ADDENDUM_FOR_ROOT_REVIEW','nativeCalls':0,'frozenV5Changes':0,'fillChanges':0,'viaChanges':0,'ruleChanges':0,'holeChanges':0,'oldCopperChanges':0,'newLineCount':len(lines),'newLineCreates':lines,'newViaCreates':[],'existingCopperOperations':[],'existingBeforeGuards':guards,'physicalDrillsScreenedPerLine':len(holes),'copperLayersInventoried':list(LAYERS),'foreignCopperActorsByLayer':dict(Counter(p['layerId'] for p in obs)),'groundActorsByLayer':dict(Counter(p['layerId'] for p in ground)),'coplanarForeignScreenAllPassed':all(c['foreignCopperMinimumConservativeGapMm']>=CLR for c in candidates),'allDrillScreensPassed':all(c['noUnexpectedDrillIntrusions'] for c in candidates),'selectedCandidateLines':candidates,'unresolvedTargets':no,'manufacturingReady':False,'limitations':['Ground owner must append exactly these four LINEs to actual-wire13 nominal no-FILL-pen graph and independently confirm all31 lobes /345 GND loads /228 actual GND vias.','Foreign Cu inventory covers six layers; electrical clearance screening is strictly coplanar for each LINE. No new via or interlayer conductor is introduced, and all863 through drills are screened for every line.','Final exact native readback union and unchanged18-rule DRC required after root applies only these four additions.','No other Inner17 routing authorized; this addendum changes no original Cu/rules/layers/holes/FILLs/VIAs.','No broad tolerance or width-pen graph equivalence is used for endpoints; both ends have positive raw copper overlap.']}
    OUT.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'report':str(OUT),'sha256':sha(OUT),'candidates':len(candidates),'unresolved':len(no)}))
if __name__=='__main__':main()
