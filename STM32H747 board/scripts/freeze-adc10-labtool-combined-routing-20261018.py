"""Compile and independently screen the frozen offline routing modules; native writes forbidden."""
import json,hashlib,math,runpy,copy,argparse
from pathlib import Path
from collections import defaultdict,Counter
from shapely.geometry import Point,LineString,Polygon,box
from shapely.affinity import scale
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/candidates/adc10-labtool-20261018'
HERE=BASE/'routing'
SOURCE=ROOT/'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru'
PLACEMENT=BASE/'independent-pcb-placement-short-negative-commonpower-v5b-ref-flipped-proposal.json'
M=runpy.run_path(str(BASE/'independent-pcb-placement-proposal.py'));G=M['G'];MM=.0254
LAYERS=(1,2,15,16,17,18)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(p.read_text(encoding='utf8'))
def main():
    global SOURCE,PLACEMENT
    ap=argparse.ArgumentParser();ap.add_argument('--input-module',type=Path);ap.add_argument('--source',type=Path);ap.add_argument('--placement',type=Path);ap.add_argument('--audit-output',type=Path);args=ap.parse_args()
    if not args.input_module:
        assert sha(SOURCE)=='568ca754e9ff92d9df6cf5f96e3384811f9ad6038404410ce7ca4c843d80296b'
        assert sha(PLACEMENT)=='7121af6778ac0a04d674d8ac355122fb613cd4028201dd7ad18e6dae606387fe'
    names=['local-row-routing-shared-ref-flipped-v7-draft.json','bottom-rails-offset-v4-draft.json','query-negative-inner15-final-v2-layer15.json','commonpower-top-local-v5-short-fly-review.json','independent-raw5-bilayer-route-v2-shortvia.json','independent-optional-pump-three-ground-vias-v3.json','query-reference-power-final-v1-layer1.json']
    modules=[load(HERE/n) for n in names];lines=[];vias=[]
    for n,m in zip(names,modules):
        for p in m['newLineCreates']:
            p=copy.deepcopy(p)
            if n=='query-negative-inner15-final-v2-layer15.json':p['key']=f'NEG_INNER15_{len([x for x in lines if x["layerId"]==15])+1:03}'
            p['sourceModule']=n;lines.append(p)
        if n in (names[0],names[4],names[5]):vias.extend(copy.deepcopy(m.get('newViaCreates',[])))
    ref=load(HERE/'six-layer-via-port-candidates-reference-power-rail-y72-v1.json');assert not ref['failedPorts'];vias.extend(copy.deepcopy(ref['viasProposed']))
    stitch=copy.deepcopy(load(BASE/'ground/bottom70-ground-stitch-candidates-v4-module-screen.json')['candidates'][0]);assert stitch['xyMm']==[31.3,79.1];stitch['key']='BOTTOM70_GND_LOBE_STITCH';vias.append(stitch)
    assert len(lines)==513 and len(vias)==50,(len(lines),len(vias))
    incoming=None
    if args.input_module:
        assert args.source and args.placement and args.audit_output
        incoming=load(args.input_module);lines=incoming['newLineCreates'];vias=incoming['newViaCreates'];SOURCE=args.source.resolve();PLACEMENT=args.placement.resolve()
        assert sha(SOURCE)==incoming['sourceSha256'] and sha(PLACEMENT)==incoming['placementSha256']
    assert len({p['key'] for p in lines+vias})==len(lines+vias)
    assert len({tuple(p['xyMm']) for p in vias})==len(vias)
    rows=M['parse'](SOURCE);attrs=M['attrs_of'](rows);docs,_=M['READ'](M['CHECK'])
    padnets={}
    for (k,r),b in rows.items():
        if k=='PAD_NET':p=json.loads(r);padnets[p[1],str(p[2])]=b['padNet']
    copper=[];fills=[];pads=[];drills=[];npths=[]
    def add(key,net,s,layers,pad=None,new=False):
        copper.append({'key':key,'net':(net or '').casefold(),'shape':s,'layers':tuple(layers),'pad':pad,'new':new})
    for (k,r),b in rows.items():
        if k=='COMPONENT':
            refname=attrs[r]['Designator'];xy=b['x']*MM,b['y']*MM
            for (pk,pi),(ph,p) in docs['FOOTPRINT',attrs[r]['Footprint']].items():
                if pk!='PAD':continue
                net=padnets.get((r,str(p['num'])),'');s=M['local_pad'](p)
                if b['layerId']==2:s=scale(s,xfact=1,yfact=-1,origin=(0,0))
                s=M['world'](s,xy,b['angle']);ls=LAYERS if p['layerId']==12 else (b['layerId'],)
                add('PAD:'+refname+':'+str(p['num'])+':'+str(pi),net,s,ls,pad=(refname,str(p['num'])));pads.append((refname,str(p['num']),s))
                h=p.get('hole') or {};w=h.get('width',0)*MM;hh=h.get('height',0)*MM
                if max(w,hh)>0:
                    hs=M['world'](box(-w/2,-hh/2,w/2,hh/2),(p['centerX']*MM,p['centerY']*MM),p.get('padAngle',0))
                    if b['layerId']==2:hs=scale(hs,xfact=1,yfact=-1,origin=(0,0))
                    drills.append(('DRILL:'+refname+':'+str(p['num'])+':'+str(pi),M['world'](hs,xy,b['angle'])))
        elif k=='VIA':
            p=Point(b['centerX']*MM,b['centerY']*MM);add('VIA:'+r,b['netName'],p.buffer(b['viaDiameter']*MM/2,resolution=32),LAYERS);drills.append(('DRILL:VIA:'+r,p.buffer(b['holeDiameter']*MM/2,resolution=32)))
        elif k in ('LINE','ARC') and b.get('layerId') in LAYERS:
            a=(b['startX']*MM,b['startY']*MM);z=(b['endX']*MM,b['endY']*MM);pts=G['arc'](a,z,b['angle']) if k=='ARC' else [a,z]
            add(k+':'+r,b.get('netName'),LineString(pts).buffer(b['width']*MM/2,resolution=16),(b['layerId'],))
        elif k=='POLY' and b.get('layerId') in LAYERS:add(k+':'+r,b.get('netName'),LineString(G['ring_path'](b['path'])).buffer(b['width']*MM/2,resolution=16),(b['layerId'],))
        elif k=='PAD' and b.get('hole'):
            h=b['hole'];w=h.get('width',0)*MM;hh=h.get('height',0)*MM
            if max(w,hh)>0:
                hs=M['world'](box(-w/2,-hh/2,w/2,hh/2),(b['centerX']*MM,b['centerY']*MM),b.get('padAngle',0));drills.append(('DRILL:FREEPAD:'+r,hs));npths.append((r,hs))
        elif k=='FILL' and b.get('layerId') in LAYERS:
            if b['path'][0][0]=='CIRCLE':p=b['path'][0];s=Point(p[1]*MM,p[2]*MM).buffer(p[3]*MM,resolution=64)
            else:rings=[G['ring_path'](p) for p in b['path']];s=Polygon(rings[0],rings[1:])
            fills.append({'key':'FILL:'+r,'net':b.get('netName','').casefold(),'shape':s,'layers':(b['layerId'],),'pad':None,'new':False})
    assert len(drills)==799,len(drills)
    for p in lines:add(p['key'],p['net'],LineString([p['startXYmm'],p['endXYmm']]).buffer(p['widthMm']/2,resolution=16),(p['layerId'],),new=True)
    for p in vias:add(p['key'],p['net'],Point(p['xyMm']).buffer(p['viaDiameterMm']/2,resolution=32),LAYERS,new=True)
    tree=STRtree([o['shape'] for o in copper]);conflicts=[];seen=set()
    for p in copper:
        if not p['new']:continue
        searchclr=.17 if p['key'] in {v['key'] for v in vias} else .1535
        clr=searchclr
        for oi in tree.query(p['shape'].buffer(clr+.000001,resolution=16)):
            o=copper[int(oi)]
            if p['key']==o['key'] or p['net']==o['net'] or not(set(p['layers'])&set(o['layers'])):continue
            pair=tuple(sorted((p['key'],o['key'])))
            if pair in seen:continue
            d=p['shape'].distance(o['shape'])
            required=.1535 if o['new'] else clr
            if d<required-1e-7:conflicts.append({'item':p['key'],'other':o['key'],'layers':list(set(p['layers'])&set(o['layers'])),'net':p['net'],'otherNet':o['net'],'copperEdgeGapMm':d,'requiredMm':required});seen.add(pair)
        for key,hs in npths:
            if p['shape'].distance(hs)<.28:conflicts.append({'item':p['key'],'other':'NPTH:'+key,'copperToHoleGapMm':p['shape'].distance(hs),'requiredMm':.28})
    drillfails=[];viapadfails=[];alldrills=list(drills)
    for p in vias:
        hs=Point(p['xyMm']).buffer(p['holeDiameterMm']/2,resolution=32);cs=Point(p['xyMm']).buffer(p['viaDiameterMm']/2,resolution=32)
        for k,h in alldrills:
            d=hs.distance(h)
            if d<.3009:drillfails.append({'via':p['key'],'other':k,'holeEdgeGapMm':d})
        for r,pn,s in pads:
            if cs.distance(s)<.0599:viapadfails.append({'via':p['key'],'pad':r+':'+pn,'copperGapMm':cs.distance(s)})
        alldrills.append((p['key'],hs))
    # Physical same-net connectivity with literal intersections. Ground is
    # intentionally delegated to the preserving-split all-layer mask auditor.
    bynet=defaultdict(list)
    for p in copper:
        if p['net']:bynet[p['net']].append(p)
    for p in fills:
        if p['net'] not in ('gnd','+3v3') and p['shape'].is_valid:bynet[p['net']].append(p)
    contracts=load(BASE/'schematic-plan.json')['allPinContracts'];targetnets={n.casefold() for p in contracts.values() for n in p.values() if n and n.casefold() not in ('gnd','+3v3')}
    graphs=[];graphfails=[]
    for net in sorted(targetnets):
        objects=bynet.get(net,[]);parent=list(range(len(objects)))
        def find(i):
            while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
            return i
        def union(a,b):parent[find(a)]=find(b)
        nt=STRtree([p['shape'] for p in objects])
        for i,p in enumerate(objects):
            for j in nt.query(p['shape'].buffer(0.00002)):
                j=int(j)
                if j>i and set(p['layers'])&set(objects[j]['layers']) and p['shape'].distance(objects[j]['shape'])<.00002:union(i,j)
        endpoints=[(i,p) for i,p in enumerate(objects) if p['pad']]
        comps=defaultdict(list)
        for i,p in endpoints:comps[find(i)].append(p['pad'][0]+'.'+p['pad'][1])
        entry={'net':net,'allActualPadCount':len(endpoints),'padComponentCount':len(comps),'padComponents':[sorted(set(v)) for v in comps.values()]}
        graphs.append(entry)
        if len(comps)>1:graphfails.append(entry)
    report={'schema':'adc10-labtool-frozen-combined-routing-v1','sourcePath':str(SOURCE),'sourceSha256':sha(SOURCE),'placementPath':str(PLACEMENT),'placementSha256':sha(PLACEMENT),'readOnly':True,'nativeCalls':0,'status':'OFFLINE_PHYSICAL_SCREEN_COMPLETE_REQUIRES_PRESERVING_FILL_MASK_AND_NATIVE_DRC','frozenModules':[{'path':str(HERE/n),'sha256':sha(HERE/n)} for n in names]+[{'path':str(HERE/'six-layer-via-port-candidates-reference-power-rail-y72-v1.json'),'sha256':sha(HERE/'six-layer-via-port-candidates-reference-power-rail-y72-v1.json')},{'path':str(BASE/'ground/bottom70-ground-stitch-candidates-v4-module-screen.json'),'sha256':sha(BASE/'ground/bottom70-ground-stitch-candidates-v4-module-screen.json')}],'newLineCreates':lines,'newViaCreates':vias,'counts':{'lines':len(lines),'linesByLayer':dict(Counter(p['layerId'] for p in lines)),'newVias':len(vias),'originalVias':640,'originalPhysicalDrills':799,'expectedTotalVias':690,'expectedTotalPhysicalDrills':849},'unroutedConnections':graphfails,'exactLiteralCopperConflicts':conflicts,'newDrillClearanceConflicts':drillfails,'viaInPadConflicts':viapadfails,'physicalNetGraphsExcludingGroundAnd3V3':graphs,'nativeManufacturingReady':False,'requires':['Authoritative preserving-split static FILL masks for all six layers, local approved outer notches only.','All 345 physical GND pads and every new GND via connected to anchored ground after the final masks.','18 rules, six layers, every original 640 VIA and 799 drill unchanged.','Native strict DRC and entire schematic/PCB netlist audit before manufacturing.'],'inner15Authorization':{'onlyLineKeys':[p['key'] for p in lines if p['layerId']==15],'sourceModuleSha256':'a6b6089d01ad1db05d9398011056b3fbde37fcabd810735a21ae84df0efc64ca','noOtherInnerRoutesApproved':True},'replacementForUnroutedV7PowerEdge':'COMMON -> TOP channel rail bridge -> BOTTOM +5AFE trunk -> new REFERENCE_POWER_RAIL_PORT(15.5,72) -> TOP C103.1 -> existing local reference +5AFE tree.'}
    report['schema']='adc10-labtool-frozen-combined-routing-v2'
    report['inner15Authorization']['sourceModuleSha256']=sha(HERE/'query-negative-inner15-final-v2-layer15.json')
    report['strictSpacingQualification']={'newTraceToNewViaCopperMinimumMm':.15710333262252119,'selectedStrictRuleCopperGapMm':.1524,'offlineRequiredMm':.1535,'viaSearchReserveToProtectedOriginalCopperMm':.17,'note':'The .17mm search reserve is not a native rule. The unchanged 18 native rules require .1524mm copper gaps; new trace-via gaps were screened at .1535mm. No native rule was relaxed.'}
    if incoming:
        report.update({k:copy.deepcopy(v) for k,v in incoming.items() if k not in ('exactLiteralCopperConflicts','newDrillClearanceConflicts','viaInPadConflicts','unroutedConnections','physicalNetGraphsExcludingGroundAnd3V3')})
        report['counts']={'lines':len(lines),'linesByLayer':dict(Counter(p['layerId'] for p in lines)),'newVias':len(vias),'originalVias':640,'originalPhysicalDrills':799,'expectedTotalVias':640+len(vias),'expectedTotalPhysicalDrills':799+len(vias)}
        report['status']='OFFLINE_SCREEN_PASS_REQUIRES_AUTHORITATIVE_GROUND_MASK_AND_NATIVE_DRC' if not(conflicts or drillfails or viapadfails or graphfails) else 'FAIL_DO_NOT_APPLY'
    target=args.audit_output or HERE/'frozen-combined-routing-v2.json';target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'target':str(target),'sha256':sha(target),'lines':len(lines),'vias':len(vias),'copperConflicts':len(conflicts),'drillConflicts':len(drillfails),'viaPadConflicts':len(viapadfails),'unconnectedNets':len(graphfails)}))
    if conflicts or drillfails or viapadfails or graphfails:raise SystemExit(2)
if __name__=='__main__':main()
