"""Independent actual direct4 source/route/FILL and literal return-path audit."""
from collections import Counter,defaultdict
import hashlib
import json
import math
from pathlib import Path
import runpy
from shapely import affinity
from shapely.geometry import Point,Polygon,LineString
from shapely.ops import unary_union
from shapely.validation import explain_validity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
PLAN=HERE/'bottom-buckets/bottom-bucket-routing-manifest-local-api-operations.json'
PLAN_SHA='6162eb57e1a2a3a862e0e3cc2eb4310036cc2d8dab4af2bfea83d52f5108b93a'
BASE=ROOT/'output/validation/native-adc10-pcb-direct4_move-20261018.epru'
BASE_SHA='4325076c10e2d6e7c1b923952fd3e4e3efd0a1f6ecfc74727dd7b7911af34631'
SOURCE=ROOT/'output/validation/native-adc10-pcb-direct4_copper-20261018.epru'
SOURCE_SHA='f4c4fd15b00355d60b78391249c64aff1dd99903597fdbf937ed5dbb48c9fc4a'
LOBE='23f25be226b43a88';FID='647c91cbbc161db2'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def q(v):
    if isinstance(v,list):return[q(x)for x in v]
    return round(v,4)if isinstance(v,(int,float))and not isinstance(v,bool)else v
def solid(ps):
    rings=[[(x*MM,y*MM)for x,y in M['BM']['polyline'](p)]for p in ps]
    return Polygon(rings[0],rings[1:])
def linekey(b):return(b['netName'],b['layerId'],b['startX'],b['startY'],b['endX'],b['endY'],b['width'])


def main():
    assert sha(PLAN)==PLAN_SHA and sha(BASE)==BASE_SHA and sha(SOURCE)==SOURCE_SHA
    plan=json.loads(PLAN.read_text());before,_=M['M']['parse'](BASE);rows,_=M['M']['parse'](SOURCE)
    checks=[];errors=[]
    def check(ok,test,detail=None):
        item={'test':test,'passed':bool(ok)}
        if detail is not None:item['detail']=detail
        checks.append(item)
        if not ok:errors.append(item)
    protected={k:b for k,b in before.items()if k!=('FILL',FID)and k[0]!='DOCHEAD'}
    check(all(rows.get(k)==b for k,b in protected.items()),'All original bodies exact after copper stage including calibrated4CAPs/TOPground/VIAs/drills/rules/pins/stack',{'count':len(protected)})
    newkeys=rows.keys()-before.keys();missing=before.keys()-rows.keys()
    check(not missing and Counter(k[0]for k in newkeys)==Counter({'LINE':7,'FILL':1})and('FILL',LOBE)in newkeys,'Exactly7newLINEs and1anchoredGNDlobe; no deletions',{'added':sorted(newkeys),'missing':sorted(missing)})
    fb,fa=before['FILL',FID],rows['FILL',FID]
    check({k:v for k,v in fb.items()if k not in['path','refs']}=={k:v for k,v in fa.items()if k not in['path','refs']}
          and fb.get('refs')is None and fa.get('refs')==[None],'Only targetFILLpath and exact None→[None] refs normalization')
    main_actual=solid(fa['path']);main_expected=solid(q(plan['fillModifyOperations'][0]['afterPathsExplicitlyClosedForApi']))
    lobe_actual=solid(rows['FILL',LOBE]['path']);lobe_expected=solid(q(plan['fillCreateOperations'][0]['afterPathsExplicitlyClosedForApi']))
    geometry=[]
    for name,a,e in [('main',main_actual,main_expected),('retained-lobe',lobe_actual,lobe_expected)]:
        check(a.is_valid and e.is_valid,'Actual/expected '+name+' polygon valid without repair',{'actual':explain_validity(a),'expected':explain_validity(e)})
        xor=a.symmetric_difference(e).area;hd=a.hausdorff_distance(e)
        check(xor==0 and hd==0,'Exact polygon geometry after requested4decimal-mil serialization '+name,{'XORmm2':xor,'HausdorffMm':hd})
        geometry.append({'solid':name,'XORmm2':xor,'HausdorffMm':hd})
    lf=rows['FILL',LOBE]
    check({k:v for k,v in lf.items()if k!='path'}=={'partitionId':'','groupId':0,'netName':'GND','layerId':2,'width':.2,'fillStyle':'SOLID','locked':False,'zIndex':-1,'isBridgingCopper':False,'networkList':[],'refs':[None]},'New retained lobe exact expected net/layer/width/default fields')
    expected_lines=[]
    for ch in plan['channels']:
        points=ch['signalRoute']['pointsMm']
        for a,b in zip(points,points[1:]):
            expected_lines.append((ch['net'],2,round(a[0]/MM,4),round(a[1]/MM,4),round(b[0]/MM,4),round(b[1]/MM,4),round(ch['signalRoute']['widthMm']/MM,4)))
    actual_lines=[rows[k]for k in newkeys if k[0]=='LINE']
    check(Counter(map(linekey,actual_lines))==Counter(expected_lines),'All7newLINEexact geometry/net/layer/width multiset at4decimal-mil output')
    defaults={'partitionId':'','groupId':0,'locked':False,'zIndex':-1}
    check(all(all(b.get(k)==v for k,v in defaults.items())and set(b)==set(defaults)|{'netName','layerId','startX','startY','endX','endY','width'}for b in actual_lines),'All7newLINEother fields exact native defaults')
    attrs=defaultdict(dict)
    for(kind,rid),b in rows.items():
        if kind=='ATTR':attrs[b['parentId']][b['key']]=b['value']
    libs=M['BM']['LM']['read_libs']();padnets={}
    for(kind,rid),b in rows.items():
        if kind=='PAD_NET':
            _,cid,num,pid=json.loads(rid);padnets[cid,str(num),pid]=b['padNet']
    gndvia=[]
    for(kind,rid),b in rows.items():
        if kind=='VIA'and b['netName']=='GND':
            center=Point(b['centerX']*MM,b['centerY']*MM)
            ann=center.buffer(b['viaDiameter']*MM/2,quad_segs=128).difference(center.buffer(b['holeDiameter']*MM/2,quad_segs=128))
            gndvia.append((rid,ann,b))
    ground=[];parent=[];excluded=[]
    for(kind,rid),b in rows.items():
        if kind!='FILL'or b.get('netName')!='GND'or b.get('layerId')not in[2,15,17,18]:continue
        if not all(all(not isinstance(x,str)or x=='L'for x in p)for p in b['path']):excluded.append(rid);continue
        p=solid(b['path'])
        if not p.is_valid:excluded.append(rid);continue
        if b['layerId']==2:ground.append(p.buffer(b['width']*MM/2))
        else:
            anchor=[vid for vid,ann,vb in gndvia if p.intersection(ann).area>1e-10]
            if len(anchor)>=2:parent.append((rid,b['layerId'],p,len(anchor)))
    g=unary_union(ground);gcomponents=[g]if g.geom_type=='Polygon'else list(g.geoms)
    channel_reports=[];max_pinerror=0
    for ch in plan['channels']:
        cid=ch['componentId'];comp=rows['COMPONENT',cid];check(comp['layerId']==2,'Actual BOTTOM placement '+ch['ref'])
        expected_angle={'C88':180,'C81':0,'C86':180,'C96':90}[ch['ref']]
        check(comp['angle']==expected_angle,'Calibrated actual Bottom angle '+ch['ref'])
        native={str(b['num']):(rid,b)for(kind,rid),b in libs['FOOTPRINT',attrs[cid]['Footprint']].items()if kind=='PAD'}
        pads={};pinreports=[]
        for num,world in ch['requiredWorldPads'].items():
            pid,p=native[num]
            # This two-pad footprint has local centerY=0 and symmetric RECTs.
            # Thus calibrated Bottom Y reflection leaves its pad geometry
            # invariant before rotation; never infer a generic X reflection.
            check(p['centerY']==0 and p['padAngle']==0 and p['defaultPad']['padType']=='RECT'and p['defaultPad'].get('radius',0)==0,'Bottom mirror-invariant exact native cap pad assumptions '+ch['ref']+'.'+num)
            s=affinity.scale(M['BM']['padshape'](p,comp),xfact=MM,yfact=MM,origin=(0,0));pads[num]=s
            xy=[s.centroid.x,s.centroid.y];error=max(abs(xy[i]-world['xyMm'][i])for i in[0,1]);max_pinerror=max(max_pinerror,error)
            bound=.00005*MM+abs(abs(p['centerX'])*MM-.48)+1e-12
            check(error<=bound and padnets[cid,num,pid]==world['net'],'Actual source numbered padXY/net equals target within exact component-output and native-pad-spacing representation '+ch['ref']+'.'+num,{'actualXYmm':xy,'expectedXYmm':world['xyMm'],'maxAxisErrorMm':error,'derivedRepresentationBoundMm':bound})
            pinreports.append({'number':num,'net':padnets[cid,num,pid],'actualXYmm':xy,'maxAxisErrorMm':error})
        reach=[]
        for idx,solid_ground in enumerate(gcomponents):
            if not solid_ground.covers(pads['2']):continue
            anchors=[(vid,ann,vb)for vid,ann,vb in gndvia if solid_ground.intersection(ann).area>1e-10]
            parents=[]
            for vid,ann,vb in anchors:
                for fid,layer,poly,count in parent:
                    if poly.intersection(ann).area>1e-10:parents.append({'viaId':vid,'parentFILLId':fid,'layerId':layer,'parentGNDViaCount':count})
            if parents:reach.append({'bottomGroundComponentIndex':idx,'existingGNDViaIds':[a[0]for a in anchors],'unchangedInnerPlaneReach':parents})
        check(bool(reach),'Actual full pad2 rectangle reaches continuous literal Bottom GND / existing plated annulus / unchanged multi-anchor inner GND '+ch['ref'])
        ts=[M['BM']['trackshape']('LINE',b)for b in actual_lines if b['netName']==ch['net']]
        track=affinity.scale(unary_union(ts),xfact=MM,yfact=MM,origin=(0,0))
        vb=rows['VIA',ch['escapeViaId']];via=Point(vb['centerX']*MM,vb['centerY']*MM).buffer(vb['viaDiameter']*MM/2,quad_segs=128)
        check(track.intersection(pads['1']).area>1e-10 and track.intersection(via).area>1e-10 and vb['netName']==ch['net'],'Actual signal copper physically joins pin1 and original ADC escape via '+ch['ref'])
        gap=unary_union([track,pads['1']]).distance(g)
        check(gap>=.1524,'Actual signal pad+trace clear of stroked actual BottomGND by .1524mm '+ch['ref'],gap)
        channel_reports.append({'ref':ch['ref'],'net':ch['net'],'actualNativePins':pinreports,'literalGNDReach':reach,'signalToGNDGapMm':gap})
    out=HERE/'adc10-bottom-direct4-actual-independent-copper-ground-audit-20261018.json'
    report={'schema':'stm32h747-direct4-actual-independent-copper-ground-20261018-v1','passed':not errors,'mode':'ACTUAL_NATIVE_DIRECT4_COPPER',
        'sourcePath':str(SOURCE),'sourceSha256':SOURCE_SHA,'beforePath':str(BASE),'beforeSha256':BASE_SHA,'planPath':str(PLAN),'planSha256':PLAN_SHA,
        'protectedNativeBodyCount':len(protected),'polygonGeometry':geometry,'channels':channel_reports,'maxActualPinTargetErrorMm':max_pinerror,
        'unrelatedArcOrInvalidOriginalFILLIdsExcludedAsAnchors':excluded,'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['Literal native copper/pad/annulus and unchanged inner-ground connectivity proof, not a label shortcut.',
            'Only this symmetric local-Y-zero two-pad footprint uses mirror-invariant source geometry; no generic Bottom-X reflection assumption.',
            'Exact4decimal-mil coordinate representation and native pad spacing establish nanometre bounds, not a generic3um acceptance.',
            'Strict full-board native DRC, final netlist, saved/reopened preservation and CAM remain required. No manufacturing approval.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors],'maxActualPinTargetErrorMm':max_pinerror},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
