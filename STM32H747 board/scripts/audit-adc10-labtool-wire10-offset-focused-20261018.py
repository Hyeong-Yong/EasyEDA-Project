"""Read-only stopped-wire10 physical delta and two-diagonal clearance screen.

Exact rational witness inequalities establish non-equality; tessellated areas
are diagnostics only.  Geometry clearance uses conservative envelopes and is
not a replacement for the final unchanged-rule native DRC.
"""
import json, math, hashlib, runpy
from pathlib import Path
from fractions import Fraction as F
from decimal import Decimal, localcontext
from collections import Counter
from shapely.geometry import Point, Polygon, LineString, box
from shapely.affinity import rotate, translate, scale
from shapely.ops import unary_union

ROOT=Path(__file__).resolve().parents[1];HERE=ROOT/'output/candidates/adc10-labtool-20261018';MM=.0254
M=runpy.run_path(str(HERE/'independent-pcb-placement-proposal.py'))
P=runpy.run_path(str(ROOT/'scripts/audit-adc10-labtool-wire10-offset-physical-union-20261018.py'))
FG=runpy.run_path(str(HERE/'ground/plan-local-static-fill-clearance.py'))
FG['G']['arc'].__globals__['SAG']=.00001
ACT=P['ACT'];BASE=P['BASE'];MAN=P['MAN'];NET='ADC_OFFSET_0V97'
DEST=HERE/'audits/wire10-offset-focused-independent-v2.json'
Q=P['dist2_point_segment'];sha=P['sha'];ACTUAL_IDS=['e037cb9f75a626cf','06e4e9cdd77323ba']

def f(x):return x if isinstance(x,F) else F(str(x))
def sg(b):return tuple(b[k] for k in ('startX','startY','endX','endY'))
def segline(s):return LineString([(s[0]*MM,s[1]*MM),(s[2]*MM,s[3]*MM)])
def mmxy(p):return [float(v)*MM for v in p]
def witness(inside, outside):
    s=[f(v) for v in inside['segment']];dx,dy=s[2]-s[0],s[3]-s[1]
    with localcontext() as ctx:
        ctx.prec=100
        de=lambda n:Decimal(n.numerator)/Decimal(n.denominator)
        length=(de(dx*dx+dy*dy)).sqrt();nx,ny=-de(dy)/length,de(dx)/length
        eps=F(1,10**8)  # 0.00000001mil = 0.000254nm, not an audit tolerance.
        r=f(inside['width'])/2-eps
        for t in (F(1,2),F(1,3),F(2,3)):
            center=[s[0]+t*dx,s[1]+t*dy]
            for sign in (-1,1):
                p=[center[0]+sign*r*F(str(nx)),center[1]+sign*r*F(str(ny))]
                own=Q(p,inside['segment'])-f(inside['width'])**2/4
                gaps=[(Q(p,x['segment'])-f(x['width'])**2/4,x['id']) for x in outside]
                gap,nearest=min(gaps)
                if own<0 and gap>0:
                    return {'pointMil':[str(v) for v in p],'pointMm':mmxy(p),'strictInsideStroke':inside['id'],'insideSquaredRadiusSlackMil2':str(-own),'strictOutsideEveryOppositeSideOffsetLine':True,'minimumOutsideSquaredRadiusSlackMil2':str(gap),'nearestOppositeLine':nearest,'oppositeLineCount':len(outside),'normalPrecisionDecimalDigits':100,'radialInwardWitnessOffsetMil':str(eps),'_point':p}
    return None

def main():
    assert not DEST.exists(),'Append-only diagnostic history'
    assert sha(ACT)=='6786a3df2a3795793219d85858560e421afb8ac9515b52ef4012c9360c24736e'
    actual=M['parse'](ACT);base=M['parse'](BASE);attrs=M['attrs_of'](actual)
    expected=[{'id':rid,'segment':sg(b),'width':b['width']} for (kind,rid),b in base.items() if kind=='LINE' and b.get('netName')==NET and b.get('layerId')==1]
    count=0
    for batch in json.loads(MAN.read_text())['batches']:
        for o in batch['operations']:
            if o['action']=='line':
                count+=1
                if o['net']==NET and o['layerId']==1:expected.append({'id':o['key'],'segment':o['startXYMil']+o['endXYMil'],'width':o['widthMil']})
        if batch['stage']=='copper_wire10':break
    assert count==440
    observed=[{'id':rid,'segment':sg(b),'width':b['width']} for (kind,rid),b in actual.items() if kind=='LINE' and b.get('netName')==NET and b.get('layerId')==1]
    delta_actual=[p for p in observed if p['id'] in ACTUAL_IDS];assert len(delta_actual)==2
    delta_expected=next(p for p in expected if p['id']=='LABTOOL_LOCAL_0412')
    wa=next((w for p in delta_actual if (w:=witness(p,expected))),None)
    wm=witness(delta_expected,observed);assert wa and wm,'Exact strict non-equality witnesses required'
    area_diagnostics=[]
    for res in (64,256,1024):
        e=unary_union([LineString([p['segment'][:2],p['segment'][2:]]).buffer(p['width']/2,quad_segs=res) for p in expected])
        a=unary_union([LineString([p['segment'][:2],p['segment'][2:]]).buffer(p['width']/2,quad_segs=res) for p in observed])
        area_diagnostics.append({'quadSegments':res,'addedMm2':a.difference(e).area*MM*MM,'removedMm2':e.difference(a).area*MM*MM})
        print(json.dumps({'phase':'areaDiagnostic','value':area_diagnostics[-1]}),flush=True)
    docs,_=M['READ'](M['CHECK']);pn={}
    for (k,rid),b in actual.items():
        if k=='PAD_NET':
            _,cid,num,pid=json.loads(rid);pn[cid,pid]=b.get('padNet','')
    obstacles=[];drills=[];same_net_nonlines=[];invalid=[];unsupported=[];counts=Counter()
    # Distances to raw centre-lines minus trace radius are exact for LINEs and
    # VIA circles; curved/native polygons receive explicit conservative reserve.
    def add(kind,rid,net,shape,rad=0,qualification='exact linear geometry'):
        counts[kind]+=1
        if (net or '').casefold()==NET.casefold():same_net_nonlines.append((kind,rid,shape,rad));return
        obstacles.append({'kind':kind,'id':rid,'net':net,'shape':shape,'radius':rad,'qualification':qualification})
    def hole_shape(b):
        h=b['hole'];w=h.get('width',0)*MM;ht=h.get('height',w/MM)*MM
        if h.get('holeType')=='SLOT':
            # Axis-aligned rectangular envelope conservatively includes slot.
            s=box(-w/2,-ht/2,w/2,ht/2);rad=0;qual='conservative rotated slot rectangle'
        else:
            s=Point(0,0);rad=max(w,ht)/2;qual='exact round drill'
        s=translate(rotate(s,b.get('relativeAngle',0),origin=(0,0)),b['centerX']*MM,b['centerY']*MM)
        return s,rad,qual
    for (kind,rid),b in actual.items():
        net=b.get('netName','')
        if kind=='VIA':
            p=Point(b['centerX']*MM,b['centerY']*MM);add('VIA',rid,net,p,b['viaDiameter']*MM/2,'exact circle')
            drills.append({'id':'VIA:'+rid,'kind':'via_round','shape':p,'radius':b['holeDiameter']*MM/2,'qualification':'exact circle'})
        elif kind=='COMPONENT':
            cb=attrs[rid];doc=docs['FOOTPRINT',cb['Footprint']]
            def to_world(s):
                if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                return M['world'](s,(b['x']*MM,b['y']*MM),b['angle'])
            for (pk,pid),(_,pad) in doc.items():
                if pk!='PAD':continue
                pl=pad['layerId'];pl=3-pl if b['layerId']==2 and pl in (1,2) else pl
                if pl in (1,12):
                    # M.local_pad includes full native polygon; for nonpolygon
                    # width/height it intentionally encloses rounded/oval pads.
                    d=pad['defaultPad']
                    if d.get('padType')=='POLYGON':s=M['local_pad'](pad);reserve=.0001
                    else:
                        w=d.get('width',d.get('diameter',0))*MM;ht=d.get('height',d.get('diameter',0))*MM
                        s=translate(rotate(box(-w/2,-ht/2,w/2,ht/2),pad.get('padAngle',0),origin=(0,0)),pad['centerX']*MM,pad['centerY']*MM);reserve=0
                    s=to_world(s);add('PAD',cb['Designator']+':'+str(pad['num'])+':'+pid,pn.get((rid,pid),''),s,reserve,'conservative full pad rectangle or native polygon with 0.0001mm reserve; duplicate physical pads retained')
                if max((pad.get('hole') or {}).get('width',0),(pad.get('hole') or {}).get('height',0))>0:
                    s,rad,qual=hole_shape(pad);drills.append({'id':cb['Designator']+':'+pid,'kind':'component_hole','shape':to_world(s),'radius':rad,'qualification':qual})
        elif kind=='PAD':
            if b.get('layerId') in (1,12):add('FREEPAD',rid,net,M['local_pad'](b),0,'conservative pad rectangle or exact polygon')
            if max((b.get('hole') or {}).get('width',0),(b.get('hole') or {}).get('height',0))>0:
                s,rad,qual=hole_shape(b);drills.append({'id':'BOARD:'+rid,'kind':'board_hole','shape':s,'radius':rad,'qualification':qual})
        elif kind in ('LINE','ARC') and b.get('layerId')==1:
            p,z=(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)
            if kind=='LINE':s=LineString([p,z]);reserve=0
            else:s=LineString(FG['G']['arc'](p,z,b['angle']));reserve=.00001
            if net.casefold()!=NET.casefold():add(kind,rid,net,s,b['width']*MM/2+reserve,'exact LINE capsule' if kind=='LINE' else 'arc polyline with 0.00001mm conservative radial reserve')
        elif kind=='FILL' and b.get('layerId')==1:
            s=FG['geom'](b['path'])
            if not s.is_valid:
                invalid.append({'kind':kind,'id':rid,'boundsMm':list(s.bounds),'shape':s});continue
            # ring_points CIRCLE uses at most 0.0001mm sagitta.  This reserve
            # also covers linearized contour arcs and cannot enlarge clearance.
            add(kind,rid,net,s,.0001,'native contour tessellation; 0.0001mm conservative radial reserve')
        elif kind=='POLY' and b.get('layerId')==1:
            pts=FG['ring_points'](b['path']);s=LineString(pts)
            add(kind,rid,net,s,b.get('width',0)*MM/2+.00001,'native poly stroke; 0.00001mm reserve')
    assert len(drills)==863,(len(drills),Counter(d['kind'] for d in drills))
    results=[]
    for p in delta_actual:
        center=segline(p['segment']);radius=p['width']*MM/2
        gaps=[]
        for o in obstacles:gaps.append({'kind':o['kind'],'id':o['id'],'net':o['net'],'conservativeCopperGapMm':center.distance(o['shape'])-radius-o['radius'],'qualification':o['qualification']})
        gaps.sort(key=lambda d:d['conservativeCopperGapMm'])
        holes=[{'id':d['id'],'kind':d['kind'],'conservativeTraceToDrillGapMm':center.distance(d['shape'])-radius-d['radius'],'qualification':d['qualification']} for d in drills];holes.sort(key=lambda d:d['conservativeTraceToDrillGapMm'])
        invalid_near=[{'id':d['id'],'boundsMm':d['boundsMm'],'gapToBoundsMm':center.distance(box(*d['boundsMm']))-radius} for d in invalid];assert all(d['gapToBoundsMm']>.1535 for d in invalid_near),invalid_near
        results.append({'nativeId':p['id'],'segmentMil':p['segment'],'allForeignTopCopperActorsChecked':len(obstacles),'allPhysicalDrillsChecked':len(drills),'copperRuleMm':.1524,'offlineGuardMm':.1535,'closestForeignCopper':gaps[:12],'foreignCopperBelowNativeRule':[d for d in gaps if d['conservativeCopperGapMm']<.1524],'foreignCopperBelowOfflineGuard':[d for d in gaps if d['conservativeCopperGapMm']<.1535],'closestDrills':holes[:10],'drillIntrusions':[d for d in holes if d['conservativeTraceToDrillGapMm']<0],'drillGapBelowNativeCopperRuleForDiagnosticOnly':[d for d in holes if d['conservativeTraceToDrillGapMm']<.1524],'invalidFillsExcludedOnlyByFarBoundingBoxes':invalid_near})
    # Lines have strict rational witnesses. Ensure these selected points are
    # also far outside every other observed same-net pad/via/plane actor; such
    # actors are unchanged and cannot conceal these local slivers.
    for w in (wa,wm):
        point=Point(mmxy(w.pop('_point')));q=[{'kind':k,'id':rid,'conservativeDistanceMm':point.distance(s)-rad} for k,rid,s,rad in same_net_nonlines];q.sort(key=lambda d:d['conservativeDistanceMm']);w['otherSameNetActorCount']=len(q);w['closestOtherSameNetActors']=q[:5];w['outsideOtherSameNetActorsWithLargePositiveMargin']=all(x['conservativeDistanceMm']>.001 for x in q);assert w['outsideOtherSameNetActorsWithLargePositiveMargin']
    report={'schema':'wire10-offset-physical-delta-focused-readonly-v1','sourcePath':str(ACT),'sourceSha256':sha(ACT),'baselineSha256':sha(BASE),'executionManifestSha256':sha(MAN),'appliedPlannedLineCount':count,'newLineCreates':0,'nativeCalls':0,'frozenPlanEdits':0,'physicalCopperExactlyEqual':False,'strictRationalAddedCopperWitness':wa,'strictRationalMissingCopperWitness':wm,'approximateAreaConvergenceDiagnosticOnly':area_diagnostics,'actualTwoDiagonalFocusedClearance':results,'physicalDrillsChecked':len(drills),'copperActorKindCounts':dict(counts),'invalidTopFillsCount':len(invalid),'unsupportedTopCopperKinds':unsupported,'foreignCopperNativeClearanceScreenPassed':all(not r['foreignCopperBelowNativeRule'] for r in results),'foreignCopperOfflineGuardScreenPassed':all(not r['foreignCopperBelowOfflineGuard'] for r in results),'noTraceToDrillIntrusion':all(not r['drillIntrusions'] for r in results),'decision':'STOP unchanged. This records a real nonzero serializer kink, not exact copper equivalence. Only parent may authorize a narrowly specified junction-normalization contract. Final whole native DRC remains mandatory.'}
    DEST.write_text(json.dumps(report,indent=2,default=str)+'\n');print(json.dumps({'report':str(DEST),'sha256':sha(DEST),'physicalEqual':False,'nativeCopperClear':report['foreignCopperNativeClearanceScreenPassed'],'guardCopperClear':report['foreignCopperOfflineGuardScreenPassed'],'drillIntrusionFree':report['noTraceToDrillIntrusion'],'nearestCopper':[r['closestForeignCopper'][0] for r in results],'nearestHole':[r['closestDrills'][0] for r in results]}))
if __name__=='__main__':main()
