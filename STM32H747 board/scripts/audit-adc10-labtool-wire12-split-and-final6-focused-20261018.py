"""Read-only literal wire12 split and pending final6 Cu/drill clearance screen."""
import json,hashlib,runpy
from pathlib import Path
from collections import Counter
from shapely.geometry import Point,LineString,Polygon,box
from shapely.affinity import scale,rotate,translate
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018';MM=.0254
SOURCE=ROOT/'output/validation/native-adc10-pcb-labtool_copper_wire12-20261018.epru'
SHA='00f0707624248ec16b99ee47a638e63608764652c3ddeb12a1f4af890104910d'
MAN=H/'pcb-final-copper-v5-execution.json'
OUT=H/'audits/wire12-split-and-last6-focused-independent-v2.json'
M=runpy.run_path(str(H/'independent-pcb-placement-proposal.py'))
FG=runpy.run_path(str(H/'ground/plan-local-static-fill-clearance.py'));FG['G']['arc'].__globals__['SAG']=.00001
IDS=['67638d82c151ff5c','69b01f23e1e41d14','0fafc554d4913fb3','1d1d25791ed7a65e']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    assert sha(SOURCE)==SHA and not OUT.exists()
    rows=M['parse'](SOURCE);attrs=M['attrs_of'](rows);docs,_=M['READ'](M['CHECK']);pn={}
    for (k,rid),b in rows.items():
        if k=='PAD_NET':
            _,cid,num,pid=json.loads(rid);pn[cid,pid]=b.get('padNet','')
    obs=[];holes=[];invalid=[];counts=Counter()
    def add(kind,rid,net,s,r=0,qual='exact linear geometry'):
        obs.append({'kind':kind,'id':rid,'net':net or '', 'shape':s,'radius':r,'qualification':qual});counts[kind]+=1
    def padshape(p):
        d=p['defaultPad']
        if d.get('padType')=='POLYGON':return M['local_pad'](p),.0001
        w=d.get('width',d.get('diameter',0))*MM;ht=d.get('height',d.get('diameter',0))*MM
        return translate(rotate(box(-w/2,-ht/2,w/2,ht/2),p.get('padAngle',0),origin=(0,0)),p['centerX']*MM,p['centerY']*MM),0
    def hole(p):
        h=p['hole'];w=h.get('width',0)*MM;ht=h.get('height',w/MM)*MM
        if h.get('holeType')=='SLOT':s=box(-w/2,-ht/2,w/2,ht/2);r=0;qual='conservative rotated slot rectangle'
        else:s=Point(0,0);r=max(w,ht)/2;qual='exact round drill'
        return translate(rotate(s,p.get('relativeAngle',0),origin=(0,0)),p['centerX']*MM,p['centerY']*MM),r,qual
    for (kind,rid),b in rows.items():
        net=b.get('netName','')
        if kind=='VIA':
            s=Point(b['centerX']*MM,b['centerY']*MM);add(kind,rid,net,s,b['viaDiameter']*MM/2,'exact circle')
            holes.append({'id':'VIA:'+rid,'kind':'via_round','shape':s,'radius':b['holeDiameter']*MM/2,'qualification':'exact circle','net':net,'centerMil':[b['centerX'],b['centerY']]})
        elif kind=='COMPONENT':
            a=attrs[rid]
            def world(s):
                if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                return M['world'](s,(b['x']*MM,b['y']*MM),b['angle'])
            for (pk,pid),(_,p) in docs['FOOTPRINT',a['Footprint']].items():
                if pk!='PAD':continue
                pl=p['layerId'];pl=3-pl if b['layerId']==2 and pl in(1,2) else pl
                if pl in(1,12):
                    s,r=padshape(p);add('PAD',a['Designator']+':'+str(p['num'])+':'+pid,pn.get((rid,pid),''),world(s),r,'conservative full rectangle or native polygon with 0.0001mm reserve; every physical PAD retained')
                if max((p.get('hole') or {}).get('width',0),(p.get('hole') or {}).get('height',0))>0:
                    s,r,q=hole(p);holes.append({'id':a['Designator']+':'+pid,'kind':'component_hole','shape':world(s),'radius':r,'qualification':q})
        elif kind=='PAD':
            if b.get('layerId') in(1,12):
                s,r=padshape(b);add('FREEPAD',rid,net,s,r,'conservative pad envelope')
            if max((b.get('hole') or {}).get('width',0),(b.get('hole') or {}).get('height',0))>0:
                s,r,q=hole(b);holes.append({'id':'BOARD:'+rid,'kind':'board_hole','shape':s,'radius':r,'qualification':q})
        elif kind in('LINE','ARC') and b.get('layerId')==1:
            a,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
            s=LineString([a,z]) if kind=='LINE' else LineString(FG['G']['arc'](a,z,b['angle']))
            add(kind,rid,net,s,b['width']*MM/2+(0 if kind=='LINE' else .00001),'exact LINE capsule' if kind=='LINE' else 'arc polyline with 0.00001mm conservative reserve')
        elif kind=='FILL' and b.get('layerId')==1:
            s=FG['geom'](b['path'])
            if not s.is_valid:invalid.append({'id':rid,'boundsMm':list(s.bounds)});continue
            add(kind,rid,net,s,.0001,'native contour tessellation with 0.0001mm conservative reserve')
        elif kind=='POLY' and b.get('layerId')==1:
            add(kind,rid,net,LineString(FG['ring_points'](b['path'])),b.get('width',0)*MM/2+.0001,'poly stroke with conservative reserve')
    assert len(holes)==863,(len(holes),Counter(d['kind'] for d in holes))
    actual=[]
    for rid in IDS:
        b=rows['LINE',rid];assert b['netName']=='+5V_AFE' and b['layerId']==1
        actual.append({'id':rid,'net':b['netName'],'layerId':1,'widthMil':b['width'],'segmentMil':[b[k] for k in('startX','startY','endX','endY')],'role':'actual native wire12 q4 split'})
    manifest=json.loads(MAN.read_text());last=manifest['batches'][-1];assert last['stage']=='copper_wire13' and len(last['operations'])==6
    future=[{'id':p['key'],'net':p['net'],'layerId':p['layerId'],'widthMil':p['widthMil'],'segmentMil':p['startXYMil']+p['endXYMil'],'role':'future final6, not yet applied'} for p in last['operations']]
    assert all(p['layerId']==1 for p in actual+future)
    # Include all future six lines as physical obstacles for mutual cross-net
    # screening, even though actual source still stops at wire12.
    for p in future:
        s=p['segmentMil'];add('FUTURE_LINE',p['id'],p['net'],LineString([(s[0]*MM,s[1]*MM),(s[2]*MM,s[3]*MM)]),p['widthMil']*MM/2)
    result=[]
    for p in actual+future:
        s=p['segmentMil'];line=LineString([(s[0]*MM,s[1]*MM),(s[2]*MM,s[3]*MM)]);r=p['widthMil']*MM/2
        copper=[{'kind':o['kind'],'id':o['id'],'net':o['net'],'conservativeGapMm':line.distance(o['shape'])-r-o['radius'],'qualification':o['qualification']} for o in obs if o['net'].casefold()!=p['net'].casefold()];copper.sort(key=lambda q:q['conservativeGapMm'])
        drill=[{'id':d['id'],'kind':d['kind'],'conservativeGapMm':line.distance(d['shape'])-r-d['radius'],'qualification':d['qualification'],'sameNetViaExactNativeEndpoint':d['kind']=='via_round' and d.get('net','').casefold()==p['net'].casefold() and d.get('centerMil') in(s[:2],s[2:])} for d in holes];drill.sort(key=lambda q:q['conservativeGapMm'])
        iv=[{**d,'gapToBoundingBoxMm':line.distance(box(*d['boundsMm']))-r} for d in invalid];assert all(d['gapToBoundingBoxMm']>.1535 for d in iv),iv
        result.append({**p,'checkedForeignTopCopperCount':len(copper),'checkedPhysicalDrills':len(drill),'closestForeignCopper':copper[:5],'foreignCopperBelowNativeRule':[d for d in copper if d['conservativeGapMm']<.1524],'foreignCopperBelowOfflineGuard':[d for d in copper if d['conservativeGapMm']<.1535],'closestDrills':drill[:5],'intendedSameNetViaEndpointContacts':[d for d in drill if d['conservativeGapMm']<0 and d['sameNetViaExactNativeEndpoint']],'unexpectedDrillIntrusions':[d for d in drill if d['conservativeGapMm']<0 and not d['sameNetViaExactNativeEndpoint']],'closestNonEndpointDrill':next(d for d in drill if not d['sameNetViaExactNativeEndpoint']),'invalidFillsOnlyExcludedByFarBoundingBox':iv})
    report={'schema':'wire12-actual-split-and-pending-final6-readonly-physical-screen-v2','sourcePath':str(SOURCE),'sourceSha256':sha(SOURCE),'manifestSha256':sha(MAN),'actualSplitLinesScreened':4,'futureFinalLinesScreened':6,'topCopperActorCounts':dict(counts),'physicalDrills':len(holes),'nativeCopperGapRuleMm':.1524,'offlineGuardMm':.1535,'results':result,'nativeClearanceScreenPassed':all(not p['foreignCopperBelowNativeRule'] for p in result),'offlineGuardScreenPassed':all(not p['foreignCopperBelowOfflineGuard'] for p in result),'noUnexpectedTraceDrillIntrusions':all(not p['unexpectedDrillIntrusions'] for p in result),'nativeCalls':0,'frozenChanges':0,'physicalUnionExactlyEqual':False,'limitations':['Actual q4 splitter centre-line deltas are independently audited by the other agent; no exact same-Cu claim and no broad area/distance normalization are authorized here.','This is a conservative focused geometry screen, not complete native unchanged-rule DRC or whole final source connectivity.','Final six LINEs are offline only; future native capture must be re-audited.','A negative trace-to-drill gap is intended only where the same-net VIA has exactly the identical native coordinate as a LINE endpoint. This explicit electrical endpoint classification is not a spacing tolerance.']}
    OUT.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'report':str(OUT),'sha256':sha(OUT),'nativeClear':report['nativeClearanceScreenPassed'],'guardClear':report['offlineGuardScreenPassed'],'unexpectedDrillClear':report['noUnexpectedTraceDrillIntrusions'],'minimumCuMm':min(p['closestForeignCopper'][0]['conservativeGapMm'] for p in result),'minimumNonEndpointDrillMm':min(p['closestNonEndpointDrill']['conservativeGapMm'] for p in result),'intendedEndpointCount':sum(len(p['intendedSameNetViaEndpointContacts']) for p in result),'nativeFailures':[{k:p[k] for k in('id','foreignCopperBelowNativeRule')} for p in result if p['foreignCopperBelowNativeRule']]}))
if __name__=='__main__':main()
