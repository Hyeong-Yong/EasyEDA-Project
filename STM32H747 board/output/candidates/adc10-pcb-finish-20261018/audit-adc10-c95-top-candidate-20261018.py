"""Independent C95 TOP candidate copper/body/GND-return screen; no native calls."""
from collections import defaultdict
import hashlib,json,math,runpy
from pathlib import Path
from shapely import affinity
from shapely.geometry import Point,Polygon,LineString,box
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
PLAN=HERE/'strip/c95-layer18/c95-top-exterior-result.json'
PLAN_SHA='46e88e344d367897dc77b1b984f6b23faf17ce5b73c3b2f60a7adf1d0a7b9d32'
SOURCE=ROOT/'output/validation/native-adc10-pcb-direct4_copper-20261018.epru'
SOURCE_SHA='f4c4fd15b00355d60b78391249c64aff1dd99903597fdbf937ed5dbb48c9fc4a'
CU={1,2,15,16,17,18}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mmshape(s):return affinity.scale(s,MM,MM,origin=(0,0))
def polygon(ps):
    rs=[[(x*MM,y*MM)for x,y in M['BM']['polyline'](p)]for p in ps]
    return Polygon(rs[0],rs[1:])


def main():
    assert sha(PLAN)==PLAN_SHA and sha(SOURCE)==SOURCE_SHA
    data=json.loads(PLAN.read_text());ch=data['result'];rows,_=M['M']['parse'](SOURCE)
    libs=M['BM']['LM']['read_libs']();checks=[];errors=[]
    def check(ok,test,detail=None):
        v={'test':test,'passed':bool(ok)}
        if detail is not None:v['detail']=detail
        checks.append(v)
        if not ok:errors.append(v)
    attrs=defaultdict(dict);padnets={}
    for(k,i),b in rows.items():
        if k=='ATTR':attrs[b['parentId']][b['key']]=b['value']
        elif k=='PAD_NET':
            _,cid,num,pid=json.loads(i);padnets[cid,str(num),pid]=b['padNet']
    native={str(p['num']):(pid,p)for(k,pid),p in libs['FOOTPRINT',attrs[ch['componentId']]['Footprint']].items()if k=='PAD'}
    planned=[];pads={}
    for num,world in ch['requiredWorldPads'].items():
        pid,p=native[num];check(padnets[ch['componentId'],num,pid]==world['net'],'Existing C95 numbered pin net retained '+num)
        comp={'x':ch['centerXYmm'][0]/MM,'y':ch['centerXYmm'][1]/MM,'angle':ch['nativeRotationDegrees']}
        s=mmshape(M['BM']['padshape'](p,comp));pads[num]=s
        check(s.centroid.distance(Point(world['xyMm']))<1e-8,'Exact native C95 TOP pad geometry matches specified world pad '+num)
        planned.append({'id':'C95pad'+num,'net':world['net'],'layers':{1},'shape':s})
    for label,r,net in [('signal',ch['signalRoute'],ch['net']),('GNDreturn',ch['groundRoute'],'GND')]+[('inner'+str(i),r,ch['net'])for i,r in enumerate(ch['additionalSignalRoutes'])]:
        planned.append({'id':label,'net':net,'layers':{r['layerId']},'shape':LineString(r['pointsMm']).buffer(r['widthMm']/2,quad_segs=128)})
    nv=ch['newSignalVias'][0];via=Point(nv['xyMm']).buffer(nv['diameterMm']/2,quad_segs=128)
    planned.append({'id':'newSignalVIA','net':ch['net'],'layers':CU,'shape':via})
    actors=[];ground_annuli=[];existing_drills=[];envelopes=[]
    region=unary_union([a['shape']for a in planned]).envelope.buffer(1)
    for(k,i),b in rows.items():
        if k in['LINE','ARC','CARC']and b.get('layerId')in CU:
            s=mmshape(M['BM']['trackshape'](k,b))
            if s.intersects(region):actors.append({'id':k+':'+i,'net':b['netName'],'layers':{b['layerId']},'shape':s})
        elif k=='VIA':
            center=Point(b['centerX']*MM,b['centerY']*MM);s=center.buffer(b['viaDiameter']*MM/2,quad_segs=128)
            existing_drills.append((i,center,b['holeDiameter']*MM/2))
            if s.intersects(region):actors.append({'id':'VIA:'+i,'net':b['netName'],'layers':CU-set(b.get('unusedInnerLayers',[])),'shape':s})
            if b['netName']=='GND':ground_annuli.append((i,s.difference(center.buffer(b['holeDiameter']*MM/2,quad_segs=128))))
    for(k,cid),comp in rows.items():
        if k!='COMPONENT'or cid==ch['componentId']:continue
        foot=libs['FOOTPRINT',attrs[cid]['Footprint']];outlines=[]
        for(pk,pid),p in foot.items():
            if pk=='PAD':
                # Imported legacy footprints can contain native Bottom pads
                # inside a layer1 COMPONENT wrapper; retain the pad's layer.
                if p['layerId']==12:layers=CU
                elif comp['layerId']==1:layers={p['layerId']}
                elif p['layerId']in[1,2]:layers={3-p['layerId']}
                else:layers={p['layerId']}
                # Every current Bottom component is a symmetric 2pad cap with
                # localY=0; calibrated source geometry therefore suffices.
                if comp['layerId']==2:assert p['centerY']==0
                s=mmshape(M['BM']['padshape'](p,comp))
                if s.intersects(region):actors.append({'id':attrs[cid].get('Designator','?')+'.'+str(p['num']),'net':padnets[cid,str(p['num']),pid],'layers':layers,'shape':s})
            elif pk in['LINE','ARC']and p.get('layerId')in[3,9,48]and comp['layerId']==1:
                display=dict(p,width=(p.get('width')or p.get('lineWidth')or 0))
                s=M['BM']['trackshape'](pk,display);s=affinity.rotate(s,comp['angle'],origin=(0,0));s=affinity.translate(s,comp['x'],comp['y']);outlines.append(mmshape(s))
        if outlines:
            envelope=unary_union(outlines).envelope
            if envelope.intersects(region):envelopes.append((attrs[cid].get('Designator','?'),envelope))
    conflicts=[];nearest=[]
    for new in planned:
        relevant=[a for a in actors if a['net']!=new['net'] and a['layers']&new['layers']]
        distances=[(new['shape'].distance(a['shape']),a['id'],a['net'])for a in relevant]
        closest=min(distances)if distances else None
        nearest.append({'new':new['id'],'nearestSourceCopper':closest})
        for gap,rid,net in distances:
            if gap<.1524:conflicts.append({'new':new['id'],'old':rid,'oldNet':net,'gapMm':gap})
    for i,a in enumerate(planned):
        for b in planned[i+1:]:
            if a['net']!=b['net']and a['layers']&b['layers']:
                gap=a['shape'].distance(b['shape'])
                if gap<.1524:conflicts.append({'new':a['id'],'old':b['id'],'gapMm':gap})
    check(not conflicts,'All six-layer new VIA/pads/TOPsignal/TOPGND/inner18 copper clear of different-net non-FILL source and each other by .1524mm',conflicts)
    body=box(*ch['assemblyBoundingBoxMm']);body_dist=[{'ref':ref,'gapMm':body.distance(shape)}for ref,shape in envelopes]
    check(all(x['gapMm']>=.1 for x in body_dist),'C95 reserved TOP assembly envelope clear of all actual TOP silk/assembly/courtyard outline boxes by .10mm',body_dist)
    newhole=Point(nv['xyMm']);min_drill=min((newhole.distance(pt)-r-nv['holeMm']/2,rid)for rid,pt,r in existing_drills)
    check(min_drill[0]>=.25,'New .2mm physical drill clears every original plated drill by >=.25mm',{'gapMm':min_drill[0],'nearestOldVIAId':min_drill[1]})
    gv=rows['VIA',ch['groundRoute']['existingGroundViaId']]
    check(gv['netName']=='GND'and not gv.get('unusedInnerLayers'),'Explicit old return VIA is plated GND with all Cu layers retained')
    ann=dict(ground_annuli)[ch['groundRoute']['existingGroundViaId']]
    groundtrace=next(a['shape']for a in planned if a['id']=='GNDreturn')
    check(groundtrace.intersection(pads['2']).area>0 and groundtrace.intersection(ann).area>0,'Literal planned .30mm GND trace joins exact C95pin2 and protected old GNDvia annulus')
    parent=[]
    for(k,i),b in rows.items():
        if k!='FILL'or b.get('netName')!='GND'or b.get('layerId')not in[15,17,18]:continue
        if not all(all(not isinstance(v,str)or v=='L'for v in p)for p in b['path']):continue
        p=polygon(b['path'])
        if p.is_valid and p.intersection(ann).area>0:
            anchors=[rid for rid,aa in ground_annuli if p.intersection(aa).area>0]
            if len(anchors)>=2:parent.append({'id':i,'layerId':b['layerId'],'areaMm2':p.area,'existingGNDviaAnchors':len(anchors)})
    check(bool(parent),'Protected return via physically enters unchanged valid multi-anchor inner GND plane',parent)
    escape=rows['VIA',ch['escapeViaId']];ep=Point(escape['centerX']*MM,escape['centerY']*MM).buffer(escape['viaDiameter']*MM/2,quad_segs=128)
    inner=next(a['shape']for a in planned if a['id']=='inner0');top=next(a['shape']for a in planned if a['id']=='signal')
    check(escape['netName']==ch['net']and inner.intersection(ep).area>0 and inner.intersection(via).area>0 and top.intersection(via).area>0 and top.intersection(pads['1']).area>0,'Literal ADC escape→In18 branch→new plated VIA→TOP trace→pin1 continuity')
    out=HERE/'adc10-c95-top-candidate-independent-physical-audit-20261018.json'
    report={'schema':'stm32h747-c95-top-candidate-independent-20261018-v1','passed':not errors,'mode':'PROSPECTIVE_C95_NO_NATIVE_MUTATION',
        'sourcePath':str(SOURCE),'sourceSha256':SOURCE_SHA,'candidatePath':str(PLAN),'candidateSha256':PLAN_SHA,
        'newActors':len(planned),'nearestDifferentNetSourceCopper':nearest,'newDrillNearestOldDrillGapMm':min_drill[0],
        'groundViaParentPlaneReach':parent,'escapeToPin1ElectricalPathMm':ch['electricalEscapeToCapPathMm'],
        'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['Local GND/power FILL antipads and final GND graph AFTER cuts remain required; no exemption for routed signal copper/pads/vias.',
            'Current source includes actual direct4 pads/traces; original MCU/BGA escape copper and all old drills are read-only.',
            'TOP body screen uses actual native footprint layer3/9/48 outline bounding boxes as conservative assembly/courtyard proxies, not a manufacturer mechanical simulation.',
            'ARC strokes use <=.5degree segmentation. Native strict DRC, rule-specific via/drill check and final CAM are mandatory. No fabrication approval.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
