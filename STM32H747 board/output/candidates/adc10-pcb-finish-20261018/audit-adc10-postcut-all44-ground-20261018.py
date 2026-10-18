"""Prospective/actual 6-layer literal GND graph to MCU VSS, no label shortcuts."""
import argparse,hashlib,json,runpy
from collections import defaultdict
from pathlib import Path
from shapely import affinity
from shapely.geometry import Point,Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];MM=.0254;CU=[1,2,15,16,17,18]
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
CAPS=['C80','C81','C82','C86','C87','C88','C93','C94','C95','C96']
AFE=[(s[4],'2')for s in M['SPECS']]+[(s[5],'2')for s in M['SPECS']]+[(s[6],'2')for s in M['SPECS']]+[('U9','3'),('C103','2'),('C104','2'),('C105','2')]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def quant(v):
    if isinstance(v,list):return[quant(x)for x in v]
    return round(v,4)if isinstance(v,(int,float))and not isinstance(v,bool)else v
def solid(ps):
    rs=[[(x*MM,y*MM)for x,y in M['BM']['polyline'](p)]for p in ps]
    return Polygon(rs[0],rs[1:])
class UF:
    def __init__(self):self.p={}
    def find(self,x):
        self.p.setdefault(x,x)
        if self.p[x]!=x:self.p[x]=self.find(self.p[x])
        return self.p[x]
    def join(self,a,b):self.p[self.find(a)]=self.find(b)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--manifest',required=True);ap.add_argument('--manifest-sha',required=True)
    ap.add_argument('--source');ap.add_argument('--actual',action='store_true');ap.add_argument('--tag',default='prospective')
    args=ap.parse_args();mp=Path(args.manifest).resolve();assert sha(mp)==args.manifest_sha
    plan=json.loads(mp.read_text());source=Path(args.source or plan['sourcePath']).resolve()
    rows,_=M['M']['parse'](source);attrs=defaultdict(dict);pnet={};checks=[];errors=[];uf=UF()
    def check(ok,test,detail=None):
        x={'test':test,'passed':bool(ok)}
        if detail is not None:x['detail']=detail
        checks.append(x)
        if not ok:errors.append(x)
    for(k,i),b in rows.items():
        if k=='ATTR':attrs[b['parentId']][b['key']]=b['value']
        elif k=='PAD_NET':
            _,cid,num,pid=json.loads(i);pnet[cid,str(num),pid]=b['padNet']
    refs={a['Designator']:cid for cid,a in attrs.items()if'Designator'in a};libs=M['BM']['LM']['read_libs']()
    replacements={x['primitiveId']:x for x in plan['fillModifyOperations']}if not args.actual else{}
    target_ids={x['primitiveId']for x in plan['fillModifyOperations']}
    if args.actual:
        guarded_base,_=M['M']['parse'](Path(plan['sourcePath']))
        target_ids|={i for(k,i)in rows.keys()-guarded_base.keys()if k=='FILL'}
    actors={l:[]for l in CU};excluded=[];target_validity=[]
    print('Build literal guarded source and quantized final target polygons',flush=True)
    if not args.actual:
        for op in plan['fillModifyOperations']+plan['fillCreateOperations']:
            fid=op.get('primitiveId',op.get('semanticId'))
            ps=quant(op['afterPathsExplicitlyClosedForApi']);p=solid(ps)
            rings=[M['BM']['polyline'](r)for r in ps]
            closed=all(r[0]==r[-1]for r in rings)
            check(closed and p.is_valid and not p.is_empty,'All-net quantized target polygon valid/nonempty/explicitly closed '+fid,
                  {'net':op['net'],'layer':op['layerId'],'validity':explain_validity(p),'closed':closed})
            target_validity.append({'id':fid,'net':op['net'],'layerId':op['layerId'],'valid':p.is_valid,'closed':closed})
            if 'primitiveId'in op:check(rows['FILL',op['primitiveId']]==op['beforeBody'],'Exact all-net plane target beforebody '+fid)
    for(k,i),b in rows.items():
        if k=='FILL'and b.get('netName')=='GND'and b.get('layerId')in CU:
            ps=b['path'];target=i in target_ids
            if i in replacements:
                op=replacements[i];check(b==op['beforeBody'],'Exact current targetFILL beforebody '+i)
                ps=quant(op['afterPathsExplicitlyClosedForApi'])
            if not all(all(not isinstance(v,str)or v=='L'for v in p)for p in ps):
                excluded.append({'id':i,'layer':b['layerId'],'reason':'Original ARC paths not needed as conservative graph anchors'});continue
            p=solid(ps)
            if target:check(p.is_valid,'Quantized reviewed target GND polygon valid without repair '+i,explain_validity(p))
            if not p.is_valid:
                excluded.append({'id':i,'layer':b['layerId'],'reason':'Invalid original compound polygon excluded, no repair'});continue
            actors[b['layerId']].append(p.buffer(b['width']*MM/2))
        elif k in['LINE','ARC','CARC']and b.get('netName')=='GND'and b.get('layerId')in CU:
            actors[b['layerId']].append(affinity.scale(M['BM']['trackshape'](k,b),MM,MM,origin=(0,0)))
    if not args.actual:
        for op in plan['fillCreateOperations']:
            if op['net']!='GND':continue
            p=solid(quant(op['afterPathsExplicitlyClosedForApi']));check(p.is_valid,'Quantized new retained GND lobe valid without repair '+op['semanticId'],explain_validity(p))
            if p.is_valid:actors[op['layerId']].append(p.buffer(op['lineWidthMil']*MM/2))
        for op in plan.get('lineCreates',[]):
            if op['net']!='GND':continue
            b={'startX':round(op['startXYmil'][0],4),'startY':round(op['startXYmil'][1],4),
               'endX':round(op['endXYmil'][0],4),'endY':round(op['endXYmil'][1],4),'width':round(op['widthMil'],4)}
            actors[op['layerId']].append(affinity.scale(M['BM']['trackshape']('LINE',b),MM,MM,origin=(0,0)))
    pads={};pads_layer={}
    for ref,cid in refs.items():
        comp=rows['COMPONENT',cid];foot=libs['FOOTPRINT',attrs[cid]['Footprint']]
        for(pk,pid),p in foot.items():
            if pk!='PAD'or pnet.get((cid,str(p['num']),pid))!='GND':continue
            # Retain original physical pad layer even for a legacy layer1
            # COMPONENT that contains native Bottom pads.
            layers=CU if p['layerId']==12 else[p['layerId']if comp['layerId']==1 else(3-p['layerId']if p['layerId']in[1,2]else p['layerId'])]
            if comp['layerId']==2:assert p['centerY']==0,'Current Bottom new cap footprints must be mirror invariant'
            s=affinity.scale(M['BM']['padshape'](p,comp),MM,MM,origin=(0,0));key=ref,str(p['num'])
            if key in pads:pads[key]=unary_union([pads[key],s]);pads_layer[key]|=set(layers)
            else:pads[key]=s;pads_layer[key]=set(layers)
            for l in layers:
                if l in actors:actors[l].append(s)
    vias=[]
    for(k,i),b in rows.items():
        if k!='VIA'or b.get('netName')!='GND':continue
        center=Point(b['centerX']*MM,b['centerY']*MM)
        ann=center.buffer(b['viaDiameter']*MM/2,quad_segs=96).difference(center.buffer(b['holeDiameter']*MM/2,quad_segs=96))
        layers=set(CU)-set(b.get('unusedInnerLayers',[]));vias.append((i,ann,layers))
        for l in layers:actors[l].append(ann)
    components={};trees={}
    for l in CU:
        print('Union layer',l,'actors',len(actors[l]),flush=True)
        g=unary_union(actors[l]);cs=[g]if g.geom_type=='Polygon'else list(g.geoms);components[l]=cs;trees[l]=STRtree(cs)
    via_members={}
    for vid,ann,layers in vias:
        members=[]
        for l in layers:
            for idx in trees[l].query(ann):
                if components[l][idx].intersection(ann).area>1e-10:
                    uf.join(('via',vid),(l,int(idx)));members.append([l,int(idx)])
        via_members[vid]=members
    anchor=('U1','A17');check(anchor in pads,'Actual MCU VSS A17 numbered GND pad present')
    def members(pin):
        result=[]
        for l in pads_layer[pin]:
            for idx in trees[l].query(pads[pin]):
                if components[l][idx].intersection(pads[pin]).area>1e-10:result.append((l,int(idx)))
        return result
    anchor_members=members(anchor);anchor_roots={uf.find(x)for x in anchor_members}
    check(bool(anchor_members),'MCU VSS A17 lies in literal copper graph component',anchor_members)
    check(uf.find(('via','3b7988d562c902b4'))in anchor_roots,'Original MCU A17 fanout line/plated via physically anchors VSS')
    reportpins=[]
    for ref,num in [(x,'2')for x in CAPS]+AFE:
        pin=ref,num;check(pin in pads,'Expected actual GND pin present '+ref+'.'+num)
        mm=members(pin);roots={uf.find(x)for x in mm};ties=sorted(vid for vid,ann,ll in vias if uf.find(('via',vid))in roots)
        passed=bool(roots&anchor_roots)and bool(ties)
        check(passed,'Postcut literal six-layer copper/plated barrel graph reaches MCU VSS '+ref+'.'+num,
              {'surfaceComponents':mm,'sameGraphExistingGNDViaCount':len(ties)})
        reportpins.append({'ref':ref,'number':num,'surfaceComponents':mm,'reachesMCUVssA17':passed,'sameGraphExistingGNDViaIds':ties})
    check(len(reportpins)==44,'All10 ADCcaps plus34AFE ground pins tested')
    cleanup_reports=[];invalid_neighbor_candidates=[]
    for si,shard in enumerate(plan.get('localNewOrphanFragmentCleanup',[])):
        if 'exactCleanupMaskXYmm'not in shard:
            check(False,'Cleanup exact mask present '+str(si));continue
        mask=Polygon(shard['exactCleanupMaskXYmm']);l=shard['layerId']
        check(mask.is_valid,'Cleanup exact mask valid '+str(si),explain_validity(mask))
        leftover=[]
        for idx in trees[l].query(mask):
            p=components[l][idx];area=p.intersection(mask).area
            if area<=0:continue
            key=l,int(idx);anchored=uf.find(key)in anchor_roots
            leftover.append({'surfaceComponent':list(key),'overlapAreaMm2':area,'reachesMCUVss':anchored})
        check(all(x['reachesMCUVss']for x in leftover),'No floating literal GND copper survives inside listed cleanup mask '+str(si),leftover)
        neighbors=[]
        for(k,rid),b in rows.items():
            if k!='FILL'or b.get('netName')!='GND'or b.get('layerId')!=l or rid==shard['sourceFillId']:continue
            if not all(all(not isinstance(v,str)or v=='L'for v in p)for p in b['path']):continue
            original=solid(b['path'])
            if not original.envelope.intersects(mask):continue
            if not original.is_valid:
                invalid_neighbor_candidates.append({'maskIndex':si,'neighborId':rid,'reason':'Unrelated original invalid polygon retained/excluded; no automatic repair'});continue
            original=original.buffer(b['width']*MM/2)
            if original.intersection(mask).area<=0:continue
            ps=quant(replacements[rid]['afterPathsExplicitlyClosedForApi'])if rid in replacements else b['path']
            finalneighbor=solid(ps).buffer(b['width']*MM/2)
            memberships=[]
            for idx in trees[l].query(finalneighbor):
                area=components[l][idx].intersection(finalneighbor).area
                if area<=1e-10:continue
                memberships.append({'surfaceComponent':[l,int(idx)],'overlapAreaMm2':area,'reachesMCUVss':uf.find((l,int(idx)))in anchor_roots})
            ok=bool(memberships)and all(x['reachesMCUVss']for x in memberships)
            check(ok,'Cleanup-overlapping same-layer neighbor FILL still physically MCU-VSS anchored '+str(si)+':'+rid,memberships)
            neighbors.append({'id':rid,'sourceOverlapAreaMm2':original.intersection(mask).area,'finalMemberships':memberships,'passed':ok})
        cleanup_reports.append({'index':si,'sourceFillId':shard['sourceFillId'],'layerId':l,'maskAreaMm2':mask.area,
            'survivingCopperComponentsInsideMask':leftover,'overlappingOtherOriginalGNDFILLs':neighbors})
    for ref in ['C80','C81','C82','C86','C87','C88','C93','C94','C95','C96']:
        check(refs[ref]in attrs,'Actual ADC cap designator preserved '+ref)
    check(sha(mp)==args.manifest_sha,'Frozen manifest unchanged during graph audit')
    out=HERE/f'adc10-postcut-all44-ground-{args.tag}-independent-audit-20261018.json'
    result={'schema':'stm32h747-adc10-postcut-all44-literal-ground-independent-20261018-v1','passed':not errors,
        'mode':'ACTUAL_NATIVE_FINAL_COPPER'if args.actual else'PROSPECTIVE_QUANTIZED_MANIFEST_PLUS_ACTUAL_COMPONENT_PLACEMENTS',
        'sourcePath':str(source),'sourceSha256':sha(source),'manifestPath':str(mp),'manifestSha256':args.manifest_sha,
        'MCUAnchor':anchor,'MCUAnchorCopperComponents':anchor_members,'all44GroundPins':reportpins,
        'sixLayerGroundComponents':{str(l):len(v)for l,v in components.items()},'existingGNDViaCount':len(vias),
        'allNetQuantizedTargetPolygonTopology':target_validity,
        'cleanupRegionAndNeighborGroundProof':cleanup_reports,'unrelatedInvalidPotentialNeighborFILLsExcludedWithoutRepair':invalid_neighbor_candidates,
        'excludedUnrelatedOriginalFILLs':excluded,'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['Literal source geometry, exact footprint pads, six-layer surface copper unions and existing plated annuli/barrel links. No NET-label connectivity shortcuts.',
            'Unrelated original ARC/invalid FILLs excluded conservatively, never repaired; all reviewed GND target polygons must be valid after exact4decimal-mil API representation.',
            'Prospective mode is not an implementation claim. Final native strict DRC/all pin-net contracts/save-reopen/CAM remain mandatory. No fabrication approval.',
            'This graph proves a DC copper path, not analog crosstalk/ground impedance or minimum copper-neck manufacturing adequacy.']}
    out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors],'groundPins':len(reportpins)},indent=2),flush=True)
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
