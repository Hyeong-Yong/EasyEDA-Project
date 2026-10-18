"""All ten physical RAW/PRE/DRV/ADC chains from actual native 6-layer copper."""
import argparse,hashlib,json,math,runpy
from collections import defaultdict
from pathlib import Path
from shapely import affinity
from shapely.geometry import Point,Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254;CU=[1,2,15,16,17,18]
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
POST=[('C80','T1','ADC1_INP0'),('C81','T2','ADC1_INP1'),('C82','N5','ADC1_INP16'),
      ('C86','R3','ADC2_INP3'),('C87','M3','ADC2_INP12'),('C88','M4','ADC2_INP13'),
      ('C93','L4','ADC3_INP2'),('C94','L3','ADC3_INP6'),('C95','K4','ADC3_INP7'),('C96','K2','ADC3_INP8')]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ring_points(path):
    pts=[(path[0]*MM,path[1]*MM)];i=2;mode='L'
    while i<len(path):
        if isinstance(path[i],str):mode=path[i];i+=1
        if mode=='L':pts.append((path[i]*MM,path[i+1]*MM));i+=2
        elif mode in['ARC','CARC']:
            angle=math.radians(path[i]);end=(path[i+1]*MM,path[i+2]*MM);i+=3;start=pts[-1]
            dx,dy=end[0]-start[0],end[1]-start[1];length=math.hypot(dx,dy)
            if not length or abs(angle)<1e-12:pts.append(end);continue
            h=length/2/math.tan(angle/2);cx=(start[0]+end[0])/2-dy/length*h;cy=(start[1]+end[1])/2+dx/length*h
            r=math.hypot(start[0]-cx,start[1]-cy);phase=math.atan2(start[1]-cy,start[0]-cx)
            n=max(2,math.ceil(abs(angle)/(2*math.acos(max(-1,1-min(1e-6/r,1))))))
            pts.extend((cx+r*math.cos(phase+angle*j/n),cy+r*math.sin(phase+angle*j/n))for j in range(1,n))
            pts.append(end)
        else:raise AssertionError('Unsupported native FILL command '+mode)
    return pts
def fill_polygon(paths):
    if isinstance(paths[0][0],str):
        assert len(paths)==1 and paths[0][0]=='CIRCLE'
        _,x,y,r=paths[0];return Point(x*MM,y*MM).buffer(r*MM,quad_segs=1024)
    rs=[ring_points(p)for p in paths]
    return Polygon(rs[0],rs[1:])
class UF:
    def __init__(self):self.p={}
    def find(self,k):
        self.p.setdefault(k,k)
        if self.p[k]!=k:self.p[k]=self.find(self.p[k])
        return self.p[k]
    def join(self,a,b):self.p[self.find(a)]=self.find(b)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',required=True);ap.add_argument('--tag',default='final')
    args=ap.parse_args();source=Path(args.source).resolve();source_sha=sha(source)
    rows,_=M['M']['parse'](source);attrs=defaultdict(dict);pn={};checks=[];errors=[];uf=UF()
    def check(ok,test,detail=None):
        r={'test':test,'passed':bool(ok)}
        if detail is not None:r['detail']=detail
        checks.append(r)
        if not ok:errors.append(r)
    for(k,i),b in rows.items():
        if k=='ATTR':attrs[b['parentId']][b['key']]=b['value']
        elif k=='PAD_NET':
            _,cid,num,pid=json.loads(i);pn[cid,str(num),pid]=b['padNet']
    refs={a['Designator']:cid for cid,a in attrs.items()if'Designator'in a};by_pin={}
    for(cid,num,pid),net in pn.items():
        if net:
            ref=attrs[cid]['Designator'];key=ref,num
            check(key not in by_pin or by_pin[key]==net,'Repeated numbered pads agree '+ref+'.'+num)
            by_pin[key]=net
    nets={by_pin[s[0],'1']for s in M['SPECS']}|{s[7]for s in M['SPECS']}|{s[8]for s in M['SPECS']}|{x[2]for x in POST}
    folded={n.casefold():n for n in nets};assert len(folded)==len(nets),'No ambiguous case-only target pin nets permitted'
    aliases=set();actors=defaultdict(list);pads={};pad_layers=defaultdict(set);libs=M['BM']['LM']['read_libs']();vias=[];pth=[]
    for(k,i),b in rows.items():
        rawnet=b.get('netName','');net=folded.get(rawnet.casefold())
        if net not in nets:continue
        if rawnet!=net:aliases.add((rawnet,net))
        if k in['LINE','ARC','CARC']and b.get('layerId')in CU:
            actors[net,b['layerId']].append(affinity.scale(M['BM']['trackshape'](k,b),MM,MM,origin=(0,0)))
        elif k=='FILL'and b.get('layerId')in CU:
            p=fill_polygon(b['path'])
            check(p.is_valid,'Signal FILL valid without repair '+i)
            if p.is_valid:actors[net,b['layerId']].append(p.buffer(b['width']*MM/2))
        elif k=='VIA':
            cp=Point(b['centerX']*MM,b['centerY']*MM)
            ann=cp.buffer(b['viaDiameter']*MM/2,quad_segs=96).difference(cp.buffer(b['holeDiameter']*MM/2,quad_segs=96))
            ll=set(CU)-set(b.get('unusedInnerLayers',[]));vias.append((net,i,ann,ll))
            for l in ll:actors[net,l].append(ann)
    for ref,cid in refs.items():
        c=rows['COMPONENT',cid]
        for(pk,pid),p in libs['FOOTPRINT',attrs[cid]['Footprint']].items():
            if pk!='PAD':continue
            num=str(p['num']);net=pn[cid,num,pid]
            if net not in nets:continue
            if c['layerId']==2:assert p['centerY']==0,'Moved Bottom cap local pad invariant required'
            ll=sorted(set(CU)-set(p.get('unusedInnerLayers',[])))if p['layerId']==12 else[p['layerId']if c['layerId']==1 else(3-p['layerId']if p['layerId']in[1,2]else p['layerId'])]
            s=affinity.scale(M['BM']['padshape'](p,c),MM,MM,origin=(0,0));key=ref,num
            pads[key]=unary_union([pads[key],s])if key in pads else s;pad_layers[key]|=set(ll)
            for l in ll:
                if l in CU:actors[net,l].append(s)
            if p['layerId']==12 and p.get('plated')is True and p.get('hole'):pth.append((net,cid,pid,s,ll))
    comps={};trees={}
    for key,shapes in actors.items():
        u=unary_union(shapes);cc=[u]if u.geom_type=='Polygon'else list(u.geoms);comps[key]=cc;trees[key]=STRtree(cc)
    for net,vid,ann,ll in vias:
        for l in ll:
            for idx in trees[net,l].query(ann):
                if comps[net,l][idx].intersection(ann).area>1e-10:uf.join((net,'via',vid),(net,l,int(idx)))
    for net,cid,pid,pad,ll in pth:
        for l in ll:
            for idx in trees[net,l].query(pad):
                if comps[net,l][idx].intersection(pad).area>1e-10:uf.join((net,'plated-component-pad',cid,pid),(net,l,int(idx)))
    def members(pin,expected_net):
        check(by_pin.get(pin)==expected_net,'Expected actual pin-net '+str(pin),{'actual':by_pin.get(pin),'expected':expected_net})
        result=[]
        for l in pad_layers[pin]:
            key=expected_net,l
            if key not in trees:continue
            for idx in trees[key].query(pads[pin]):
                if comps[key][idx].intersection(pads[pin]).area>1e-10:result.append((expected_net,l,int(idx)))
        return result
    reports=[]
    for spec,post in zip(M['SPECS'],POST):
        sma,rb,rin,series,opa,cpre,cdec,pre,drv=spec;cpost,ball,adcnet=post;raw=by_pin[sma,'1']
        groups=[('RAW',raw,[(sma,'1'),(rin,'1')]),('PRE',pre,[(rin,'2'),(rb,'1'),(cpre,'1'),(opa,'3')]),
                ('DRV',drv,[(opa,'1'),(opa,'4'),(series,'1')]),('ADC_POST',adcnet,[(series,'2'),('U1',ball),(cpost,'1')])]
        stages=[]
        for stage,net,pp in groups:
            membership=[members(p,net)for p in pp];roots=[{uf.find(k)for k in group}for group in membership]
            common=set.intersection(*roots)
            check(bool(common),'Literal 6-layer copper/plated-barrel continuity '+sma+':'+stage,
                  {'pins':pp,'surfaceComponents':membership,'commonRoots':[list(k)for k in common]})
            stages.append({'stage':stage,'net':net,'pins':pp,'commonCopperRoots':[list(k)for k in common],'passed':bool(common)})
        reports.append({'SMA':sma,'MCU':{'ref':'U1','ball':ball,'net':adcnet},'postCap':cpost,'stages':stages})
    check(sha(source)==source_sha,'Native source unchanged during independent audit')
    out=HERE/f'adc10-{args.tag}-literal-signal-chains-independent-audit-20261018.json'
    report={'schema':'stm32h747-adc10-actual-six-layer-signal-chain-independent-20261018-v1','passed':not errors,
        'sourcePath':str(source),'sourceSha256':source_sha,'actualNetsAnalyzed':len(nets),'channels':reports,
        'nativeRouteCaseAliasesToUnambiguousPinNetNames':sorted(aliases),
        'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['Actual copper pad/LINE/ARC/FILL unions and plated-barrel contacts; no same-label shortcut. RAW/PRE/DRV/ADC stages remain separated by intended components.',
            'This is connectivity, not a cross-net-clearance or analog-bandwidth proof. Native strict DRC, netlist identity and final CAM remain separate requirements.',
            'Imported root copper uppercases legacy NET-(Jx-IN) names while PAD_NET retains Net-(Jx-In); only unambiguous casefold aliases are grouped, with all original strings recorded/preserved.',
            'Existing ARC tracks use <=.5degree segmentation; native FILL arcs have <=1nm sagitta and circles4096segments. Every signal FILL must be valid with no topology repair. No fabrication approval.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors],'channels':len(reports)},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
