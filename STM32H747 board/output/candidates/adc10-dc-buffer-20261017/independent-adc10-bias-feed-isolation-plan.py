"""Offline plan only: exact ten local +3V3 bias-feed isolation boundaries.

Does not modify any candidate/native/PCB source. Shape tests are bounded local
planning diagnostics, not a replacement for native DRC or final CAM clearance.
"""
import hashlib
import json
import math
import runpy
from collections import Counter,defaultdict
from pathlib import Path
from shapely import affinity
from shapely.geometry import Point,LineString,Polygon,box

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=ROOT/'output/validation/native-adc10-pcb-oriented-20261017.epru'
LM=runpy.run_path(str(HERE/'independent-adc10-pcb-footprint-pad-audit.py'))
M=LM['M']
MM=.0254
REFS=['R137','R138','R139','R149','R150','R151','R161','R162','R163','R164']


def bodysha(b):
    return hashlib.sha256(json.dumps(b,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def polyline(tokens):
    assert all(not isinstance(v,str) or v=='L' for v in tokens),set(v for v in tokens if isinstance(v,str))
    nums=[v for v in tokens if not isinstance(v,str)]
    assert len(nums)%2==0
    return list(zip(nums[::2],nums[1::2]))


def trackshape(kind,b):
    a=(b['startX'],b['startY']);z=(b['endX'],b['endY'])
    if kind=='LINE':points=[a,z]
    else:
        theta=math.radians(b['angle'])
        dx,dy=z[0]-a[0],z[1]-a[1]
        length=math.hypot(dx,dy)
        if abs(theta)<1e-12:points=[a,z]
        else:
            h=(length/2)/math.tan(theta/2)
            cx,cy=(a[0]+z[0])/2-dy/length*h,(a[1]+z[1])/2+dx/length*h
            r=math.hypot(a[0]-cx,a[1]-cy)
            start=math.atan2(a[1]-cy,a[0]-cx)
            n=max(2,math.ceil(abs(b['angle'])/.5))
            points=[(cx+r*math.cos(start+theta*i/n),cy+r*math.sin(start+theta*i/n)) for i in range(n+1)]
    return LineString(points).buffer(b['width']/2,quad_segs=32)


def padshape(p,c):
    s=p['defaultPad'];typ=s['padType']
    if typ=='RECT':
        w,h,r=s['width'],s['height'],s.get('radius',0)
        shape=box(-w/2+r,-h/2+r,w/2-r,h/2-r).buffer(r,quad_segs=32) if r else box(-w/2,-h/2,w/2,h/2)
    elif typ in {'ELLIPSE','ROUND'}:
        shape=affinity.scale(Point(0,0).buffer(1,quad_segs=64),s['width']/2,s['height']/2)
    elif typ in {'POLYGON','POLY'}:shape=Polygon(polyline(s['path']))
    else:raise ValueError(typ)
    shape=affinity.rotate(shape,p.get('padAngle',0),origin=(0,0))
    shape=affinity.translate(shape,p['centerX'],p['centerY'])
    # Only top-side and multi-layer pad shapes enter local top-copper tests.
    shape=affinity.rotate(shape,c['angle'],origin=(0,0))
    return affinity.translate(shape,c['x'],c['y'])


def main():
    sha,parse,attrs_for=M['sha'],M['parse'],M['attrs_for']
    rows=parse(SOURCE);a,refs=attrs_for(rows);lib=LM['read_libs']()
    errors,checks=[],[]
    def check(ok,name,detail=None):
        q={'test':name,'passed':bool(ok)}
        if detail is not None:q['detail']=detail
        checks.append(q)
        if not ok:errors.append(q)
    pn={}
    for (k,i),b in rows.items():
        if k=='PAD_NET':
            _,cid,num,pid=json.loads(i);pn[cid,str(num),pid]=b['padNet']
    pads=[]
    for ref,cid in refs.items():
        c=rows['COMPONENT',cid]
        for (k,pid),p in lib['FOOTPRINT',a[cid]['Footprint']].items():
            if k!='PAD':continue
            if p['layerId']!=12 and c['layerId']!=1:continue
            if p['layerId'] not in [1,12]:continue
            pads.append({'ref':ref,'num':str(p['num']),'pid':pid,'net':pn[cid,str(p['num']),pid], 'shape':padshape(p,c),'body':p,'component':c})
    # All root routed copper, independent of NET strings, enters contact checks.
    tracks=[]
    for (k,rid),b in rows.items():
        if k in {'LINE','ARC','CARC'} and b.get('layerId') in {1,2,15,16,17,18}:
            tracks.append({'key':(k,rid),'body':b,'shape':trackshape(k,b)})
    vias=[{'key':(k,rid),'body':b,'shape':Point(b['centerX'],b['centerY']).buffer(b['viaDiameter']/2,quad_segs=128)} for (k,rid),b in rows.items() if k=='VIA']
    plane=[(rid,b) for (k,rid),b in rows.items() if k=='FILL' and b.get('netName')=='+3V3' and b.get('layerId')==16 and len(b['path'])>100]
    check(len(plane)==1,'single native +3V3 In2 large FILL identified')
    planeid,planeb=plane[0]
    rings=[polyline(p) for p in planeb['path']]
    planegeom=Polygon(rings[0],rings[1:])
    plane_valid=planegeom.is_valid
    if not plane_valid:planegeom=planegeom.buffer(0)
    reports=[];cutkeys=set();candidateviakeys=set();warnings=[]
    for ref in REFS:
        cid=refs[ref];c=rows['COMPONENT',cid]
        check(c['angle']==90 and c['layerId']==1,ref+' intended top90deg orientation')
        p=next(p for p in pads if p['ref']==ref and p['num']=='2')
        pre=next(p for p in pads if p['ref']==ref and p['num']=='1')
        check(p['net']=='ADC_BIAS_2V5' and '_PRE' in pre['net'],ref+' actual numbered bias/pre pad identity')
        touches=[t for t in tracks if t['body']['layerId']==1 and t['body'].get('netName')=='+3V3' and t['shape'].distance(p['shape'])<1e-5]
        check(len(touches)==1,ref+' exactly one +3V3 feed touches bias copper', [t['key'] for t in touches])
        t=touches[0];k=t['key'];b=t['body']
        check(k[0]=='LINE',ref+' feed has no local arc')
        center=p['shape'].centroid
        ends=[(b['startX'],b['startY']),(b['endX'],b['endY'])]
        distances=[center.distance(Point(pt)) for pt in ends]
        pi=0 if distances[0]<distances[1] else 1
        check(distances[pi]*MM<1e-5,ref+' LINE starts exactly at actual bias pad center',distances[pi]*MM)
        endpoint=ends[1-pi]
        vv=[v for v in vias if math.dist(endpoint,(v['body']['centerX'],v['body']['centerY']))<.001]
        check(len(vv)==1,ref+' single VIA termination', [v['key'] for v in vv])
        v=vv[0];vb=v['body'];vk=v['key']
        check(vb['netName']=='+3V3',ref+' VIA remains global +3V3')
        all_via_route_contacts=[q for q in tracks if q['shape'].distance(v['shape'])<1e-5]
        all_feed_route_contacts=[q for q in tracks if q['body']['layerId']==1 and q['key']!=k and q['shape'].distance(t['shape'])<1e-5]
        all_feed_pad_contacts=[{'ref':q['ref'],'num':q['num'],'net':q['net']} for q in pads if q['shape'].distance(t['shape'])<1e-5]
        all_feed_via_contacts=[q['key'] for q in vias if q['shape'].distance(t['shape'])<1e-5]
        check([q['key'] for q in all_via_route_contacts]==[k],ref+' VIA has only this one routed copper attachment across6Cu', [q['key'] for q in all_via_route_contacts])
        check(not all_feed_route_contacts,ref+' feed has no shared/interior routed-copper junction', [q['key'] for q in all_feed_route_contacts])
        check(all_feed_pad_contacts==[{'ref':ref,'num':'2','net':'ADC_BIAS_2V5'}],ref+' feed touches only the intended resistor pad',all_feed_pad_contacts)
        check(all_feed_via_contacts==[vk],ref+' feed touches only its dedicated power VIA',all_feed_via_contacts)
        point=Point(vb['centerX'],vb['centerY'])
        check(planegeom.covers(point),ref+' old VIA is inside native+3V3 In2 copper plane')
        surviving_power_tracks=[q for q in tracks if q['key']!=k and q['body']['layerId']==1 and q['body'].get('netName')=='+3V3']
        surviving_power_vias=[q for q in vias if q['body'].get('netName')=='+3V3']
        remaining=[{'key':q['key'],'gapMm':p['shape'].distance(q['shape'])*MM} for q in surviving_power_tracks+surviving_power_vias]
        closest=min(remaining,key=lambda x:x['gapMm'])
        check(closest['gapMm']>1e-6,ref+' one LINE deletion geometrically disconnects all remaining3V3 surface routes',closest)
        gap=p['shape'].distance(v['shape'])*MM
        failgap=gap<.1524-1e-6
        if failgap:
            warnings.append({'ref':ref,'viaKey':vk,'gapMm':gap,'minimumRuleMm':.1524,'requiredAction':'Delete or relocate this dedicated3V3 via (or explicitly adjust component geometry) before claiming clearance. Do not rename via to bias without six-layer plane clearances/refill/nativeDRC.'})
        cutkeys.add(k);candidateviakeys.add(vk)
        reports.append({'ref':ref,'componentId':cid,'biasPadNumber':'2','biasPadCenterMmYUp':[center.x*MM,center.y*MM],
          'prePadNumber':'1','preNet':pre['net'],'padCenterDistanceMm':math.dist(ends[0],ends[1])*MM,
          'feedLineKey':k,'feedLineNet':b['netName'],'feedLineBody':b,'feedLineBodySha256':bodysha(b),'feedLinePathMmYUp':[[x*MM,y*MM] for x,y in ends],
          'feedArcKeys':[],'dedicatedViaKey':vk,'dedicatedViaBody':vb,'dedicatedViaBodySha256':bodysha(vb),
          'viaCenterMmYUp':[vb['centerX']*MM,vb['centerY']*MM],'viaCopperDiameterMm':vb['viaDiameter']*MM,'viaHoleDiameterMm':vb['holeDiameter']*MM,
          'viaOnlyRoutedAttachmentKeys':[q['key'] for q in all_via_route_contacts],'viaInside3V3PlaneFill':planeid,
          'lineOtherSurfaceTrackContacts':[q['key'] for q in all_feed_route_contacts],'linePadContacts':all_feed_pad_contacts,
          'smallestElectricalIsolationOperation':{'deleteRecordKeys':[k],'retainGlobal3V3Via':vk,'renameExistingLineOrViaAllowed':False},
          'retainedViaToBiasPadCopperGapMm':gap,'retainedViaGapMeets01524mm':not failgap,'nearestRemaining3V3CopperAfterSingleLineCut':closest})
    check(len(cutkeys)==10 and len(candidateviakeys)==10,'ten independent single-LINE branches and ten distinct VIA boundaries')
    global3v3={k:b for k,b in rows.items() if b.get('netName')=='+3V3' and k[0] in {'LINE','ARC','CARC','VIA','FILL','POLY','POUR'}}
    protected=[{'key':k,'bodySha256':bodysha(b)} for k,b in sorted(global3v3.items()) if k not in cutkeys]
    minimal_plan={k:b for k,b in rows.items() if k not in cutkeys}
    check(all(minimal_plan[k]==rows[k] for k in rows if k not in cutkeys),'in-memory minimal plan all non-target original record bodies literal exact')
    out=HERE/'independent-adc10-bias-feed-isolation-plan-20261017.json'
    report={'schema':'adc10-independent-local3v3-bias-feed-isolation-20261017-v1','passed':not errors,'planningOnly':True,
      'sourcePath':str(SOURCE),'sourceSha256':sha(SOURCE),'libraryCheckpointPath':str(LM['CP']),'libraryCheckpointSha256':sha(LM['CP']),
      'electricalMinimalCutKeys':sorted(cutkeys),'electricalMinimalCutCount':10,'feedArcKeys':[],
      'dedicatedExisting3V3ViaBoundaryKeys':sorted(candidateviakeys),'clearanceWarnings':warnings,
      'clearanceCleanMinimalCut':not warnings,'channels':reports,'checks':checks,'errors':errors,
      'protectedUnrelatedGlobal3V3CopperCount':len(protected),'protectedUnrelatedGlobal3V3CopperBodyGuards':protected,
      'allNonTargetRecordBodiesProtectedCount':len(rows)-len(cutkeys),'inMemoryOnlyPlanNativeFilesWritten':0,'liveApiCalls':0,'pcbMutated':False,
      'geometryMethod':'Actual runtime footprint RECT/ELLIPSE/POLYGON pads transformed to top-copper Y-up; native LINE/ARC route width buffer, all-layer VIA disks, actual +3V3 In2 FILL contour containment. ARC stroking0.5deg segments; rounded buffers finite mesh. Local contact comparisons tolerance0.00001mil; exact line/via and resistor straight-edge gaps analytical to numericalprecision.',
      'planeDiagnostic':{'fillId':planeid,'contours':len(rings),'rawPolygonValid':plane_valid,'invalidPolygonRepairUsedForContainmentOnly':not plane_valid},
      'limitations':['No actual deletion, rename, component move, library mutation or native API operation performed.','A10-LINE deletion isolates bias pads electrically but is not clearance-clean at R164 until its dedicated power VIA is removed/relocated or geometry adjusted.','Do not simply rename any feed or its VIA: these VIAs contact existing global+3V3 In2 plane and require real physical rework/plane clearance.','Global power planes, MCU fanout and all non-target records are protected; no need to edit them for these ten feed cuts.','This bounded plan does not reroute bias supply, validate PRE bypass removal, place new ICs, refill planes, replace native DRC, or approve fabrication.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'sourceSha256':sha(SOURCE),'cuts':len(cutkeys),'warnings':warnings,'errors':errors},indent=2))
    if errors:raise ValueError('Bias-feed isolation planning audit failed')


if __name__=='__main__':main()
