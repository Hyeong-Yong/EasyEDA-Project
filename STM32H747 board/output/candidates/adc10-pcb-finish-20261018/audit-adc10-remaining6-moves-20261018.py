"""Qualified modulo-angle/rigid-display proof for actual remaining6 move-only stage."""
import hashlib,json,math,runpy
from pathlib import Path
from shapely import affinity
from shapely.geometry import Point

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
PLAN=HERE/'bottom-buckets/remaining6-move-only-guarded-20261018.json'
PLAN_SHA='e41bcb02cd1b7bbf31f93c8c2b6c0ef89230c1da7835ffc5462eb8f9bff560b2'
BEFORE=ROOT/'output/validation/native-adc10-pcb-direct4_copper-20261018.epru'
SOURCE=ROOT/'output/validation/native-adc10-pcb-remaining6_move-20261018.epru'
SOURCE_SHA='af83b97cf7b775d834fc8339eb627beade225247ff077c2a234b3a50a4f808d4'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rotate(x,y,d):
    t=math.radians(d);return x*math.cos(t)-y*math.sin(t),x*math.sin(t)+y*math.cos(t)
def angle(v):return(v+180)%360-180


def main():
    assert sha(PLAN)==PLAN_SHA and sha(SOURCE)==SOURCE_SHA
    plan=json.loads(PLAN.read_text());assert sha(BEFORE)==plan['sourceSha256']
    before,_=M['M']['parse'](BEFORE);actual,_=M['M']['parse'](SOURCE)
    checks=[];errors=[];expected=dict(before);owned=set();moves=[]
    def check(ok,test,detail=None):
        r={'test':test,'passed':bool(ok)}
        if detail is not None:r['detail']=detail
        checks.append(r)
        if not ok:errors.append(r)
    libs=M['BM']['LM']['read_libs']();attrs={};padnets={}
    for(k,i),b in actual.items():
        if k=='ATTR':attrs.setdefault(b['parentId'],{})[b['key']]=b['value']
        elif k=='PAD_NET':
            _,cid,num,pid=json.loads(i);padnets[cid,str(num),pid]=b['padNet']
    for move in plan['componentMoves']:
        cid=move['primitiveId'];key='COMPONENT',cid;old=before[key];target=move['targetXYmil'];theta=move['axisAngleWorldDegrees']%360
        e=dict(old,x=round(target[0],4),y=round(target[1],4),angle=theta,layerId=move['targetLayerId'])
        check(old==move['beforeComponentBody'],'Exact old component guard '+move['ref'])
        check(actual[key]==e,'Exact XY4dp/layer/otherbody, -90→270 is exact modulo360 only '+move['ref'])
        expected[key]=e;owned.add(key);amodel=[]
        bottom=move['targetLayerId']==2
        for ak,b in before.items():
            if ak[0]!='ATTR'or b.get('parentId')!=cid:continue
            ae=dict(b)
            if b.get('x')is not None and b.get('y')is not None:
                x,y=rotate(b['x']-old['x'],b['y']-old['y'],-old['angle'])
                if bottom:y=-y
                dx,dy=rotate(x,y,theta);ae.update(x=round(target[0]+dx,4),y=round(target[1]+dy,4))
            arot=b['angle']+theta-old['angle'];ae['angle']=angle(180-arot if bottom else arot)
            if bottom and b.get('layerId')==3:ae['layerId']=4
            expected[ak]=ae;owned.add(ak)
            check(actual[ak]==ae,'Exact ownedATTR rigid localY-reflection/rotation/translation and layer:text-angle convention '+move['ref']+'.'+b['key'],
                  {'id':ak[1],'expected':ae,'actual':actual[ak]}if actual[ak]!=ae else{'id':ak[1]})
            amodel.append(ak[1])
        pins=[]
        for(pk,pid),p in libs['FOOTPRINT',attrs[cid]['Footprint']].items():
            if pk!='PAD':continue
            assert p['centerY']==0 and p['padAngle']==0
            s=affinity.scale(M['BM']['padshape'](p,actual[key]),MM,MM,origin=(0,0));num=str(p['num']);world=move['requiredWorldPadsMm'][num]
            err=s.centroid.distance(Point(world['xyMm']));bound=math.sqrt(2)*(.00005*MM+abs(abs(p['centerX'])*MM-.48))+1e-12
            check(padnets[cid,num,pid]==world['net']and err<=bound,'Exact native numbered pin/net world geometry within derived representation bound '+move['ref']+'.'+num,
                  {'actualXYmm':[s.centroid.x,s.centroid.y],'targetXYmm':world['xyMm'],'distanceErrorMm':err,'derivedXYEuclideanBoundMm':bound})
            pins.append({'num':num,'net':padnets[cid,num,pid],'actualXYmm':[s.centroid.x,s.centroid.y],'errorMm':err})
        moves.append({'ref':move['ref'],'componentId':cid,'actualAngle':theta,'targetLayerId':move['targetLayerId'],'ownedATTRIds':amodel,'pins':pins})
    check(before.keys()==actual.keys(),'Exact native membership, no copper/VIA/FILL/other record creation/deletion')
    diffs=[{'type':k[0],'id':k[1]}for k,b in expected.items()if k[0]!='DOCHEAD'and actual.get(k)!=b]
    check(not diffs,'Every body equals exact qualified6moves/ownedATTR model; all copper/direct4/originaldrills/rules/stack/pins exact',diffs)
    out=HERE/'adc10-remaining6-moves-modulo-angle-independent-audit-20261018.json'
    report={'schema':'stm32h747-remaining6-moves-qualified-independent-20261018-v1','passed':not errors,'sourcePath':str(SOURCE),'sourceSha256':SOURCE_SHA,
        'beforePath':str(BEFORE),'beforeSha256':sha(BEFORE),'manifestPath':str(PLAN),'manifestSha256':PLAN_SHA,
        'moves':moves,'protectedNativeBodyCount':sum(k not in owned and k[0]!='DOCHEAD'for k in before),'checks':checks,'errors':errors,
        'liveAPICalls':0,'nativeFilesWritten':0,'limits':['Move-only source proof. Remaining6 copper/antipads/drill additions are not applied by this report and DRC0 is not claimed.',
            'Only native exact angle equivalence -90==270 modulo360 and exact4decimal-mil coordinates qualified; no broad geometry-field exemptions.',
            'Bottom localY reflection and native text-angle/layer convention are tested on all owned attrs; all other fields exact.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
