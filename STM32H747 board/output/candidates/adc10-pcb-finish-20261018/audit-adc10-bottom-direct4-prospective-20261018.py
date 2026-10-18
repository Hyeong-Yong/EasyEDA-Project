"""Independent Shapely literal-world-pad/GND proof of frozen direct4 plan only."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import runpy
from shapely import affinity
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
from shapely.validation import explain_validity

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
M=runpy.run_path(str(HERE/'audit-adc10-strip-dc-graph-ground-20261018.py'))
PLAN=HERE/'bottom-buckets/bottom-bucket-routing-manifest-local-api-operations.json'
PLAN_SHA='6162eb57e1a2a3a862e0e3cc2eb4310036cc2d8dab4af2bfea83d52f5108b93a'
MM=.0254


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(PLAN)==PLAN_SHA
    plan=json.loads(PLAN.read_text());source=Path(plan['sourcePath'])
    assert sha(source)==plan['sourceSha256']
    rows,_=M['M']['parse'](source);libs=M['BM']['LM']['read_libs']()
    checks=[];errors=[]
    def check(ok,test,detail=None):
        r={'test':test,'passed':bool(ok)}
        if detail is not None:r['detail']=detail
        checks.append(r)
        if not ok:errors.append(r)
    def solid(paths):
        rings=[[(x*MM,y*MM)for x,y in M['BM']['polyline'](p)]for p in paths]
        return Polygon(rings[0],rings[1:])
    def closed(p):
        pts=M['BM']['polyline'](p)
        return pts[0]==pts[-1]
    attrs=defaultdict(dict)
    for(kind,rid),b in rows.items():
        if kind=='ATTR':attrs[b['parentId']][b['key']]=b['value']
    padnets={}
    for(kind,rid),b in rows.items():
        if kind=='PAD_NET':
            _,cid,num,pid=json.loads(rid);padnets[cid,str(num),pid]=b['padNet']
    mods=plan['fillModifyOperations'];creates=plan['fillCreateOperations']
    check(len(mods)==1 and mods[0]['primitiveId']=='647c91cbbc161db2' and len(creates)==1,'Only one existing Bottom GND FILL modified and one retained GND lobe created')
    op=mods[0];before=solid(op['beforeBody']['path']);after=solid(op['afterPathsExplicitlyClosedForApi'])
    lobe=solid(creates[0]['afterPathsExplicitlyClosedForApi'])
    check(rows['FILL',op['primitiveId']]==op['beforeBody'],'Exact guarded original Bottom FILL body')
    check(all(closed(p)for x in mods+creates for p in x['afterPathsExplicitlyClosedForApi']),'All API polygon rings explicitly closed')
    check(before.is_valid and after.is_valid and lobe.is_valid,'Before/main/lobe Shapely polygons valid without repair',
          {'before':explain_validity(before),'after':explain_validity(after),'lobe':explain_validity(lobe)})
    check(after.intersection(lobe).area==0,'Retained main and lobe have no positive-area overlap')
    final=unary_union([after,lobe])
    added=final.difference(before);removed=before.difference(final)
    cuts=unary_union([Polygon(r)for r in op['newCutRingsXYmm']])
    # Clipper operates on a 1nm integer grid, whereas the guarded original
    # native boundary retains binary/full-precision float coordinates.
    # Any positive addition must be within that exact grid's half-diagonal
    # of the original boundary; never approve a general area tolerance.
    # Two explicit coordinate-rounding stages: original native vertices ->
    # 1nm integer grid, then calculated clip intersections -> same grid.
    grid_radius=math.sqrt(2)*1e-6
    outside_added=added.difference(before.boundary.buffer(grid_radius))
    outside_removed=removed.difference(unary_union([cuts.buffer(grid_radius),before.boundary.buffer(grid_radius)]))
    check(outside_added.area==0,'Any candidate added sliver lies only within typed two-stage1nm-grid rounding envelope of old boundary',
          {'addedAreaMm2':added.area,'outsideGridBoundaryEnvelopeMm2':outside_added.area,'gridHalfDiagonalMm':grid_radius})
    check(outside_removed.area==0,'All ground removal within listed signal keepouts plus explicit local shard cleanup or typed old-boundary two-stage1nm-grid envelope',
          {'removedAreaMm2':removed.area,'outsideAuthorizedRegionMm2':outside_removed.area})
    gndvia=[]
    for(kind,rid),b in rows.items():
        if kind=='VIA'and b['netName']=='GND':
            p=Point(b['centerX']*MM,b['centerY']*MM)
            annulus=p.buffer(b['viaDiameter']*MM/2,quad_segs=128).difference(p.buffer(b['holeDiameter']*MM/2,quad_segs=128))
            gndvia.append((rid,p,annulus,b))
    physical_ground=[after.buffer(op['beforeBody']['width']*MM/2),lobe.buffer(creates[0]['lineWidthMil']*MM/2)]
    used_unchanged_bottom=[];skipped_unchanged_bottom=[]
    for(kind,rid),b in rows.items():
        if kind!='FILL'or b.get('netName')!='GND'or b.get('layerId')!=2 or rid==op['primitiveId']:continue
        if not all(all(not isinstance(v,str)or v=='L'for v in p)for p in b['path']):
            skipped_unchanged_bottom.append({'id':rid,'reason':'Arc-containing original copper not needed/used as an anchor'});continue
        p=solid(b['path'])
        if p.is_valid:
            physical_ground.append(p.buffer(b['width']*MM/2));used_unchanged_bottom.append(rid)
        else:skipped_unchanged_bottom.append({'id':rid,'reason':'Original invalid compound polygon not repaired or used as an anchor'})
    literal_ground=unary_union(physical_ground)
    ground_components=[literal_ground]if literal_ground.geom_type=='Polygon'else list(literal_ground.geoms)
    # Parent-plane proof uses valid literal original In1/In3/In4 polygons only.
    # Existing unrelated invalid polygons are not repaired or used as anchors.
    parent=[];skipped=[]
    for(kind,rid),b in rows.items():
        if kind!='FILL'or b.get('netName')!='GND'or b.get('layerId')not in[15,17,18]:continue
        if not all(all(not isinstance(v,str)or v=='L'for v in p)for p in b['path']):continue
        p=solid(b['path'])
        if not p.is_valid:skipped.append(rid);continue
        anchors=[vid for vid,vp,va,vb in gndvia if p.intersection(va).area>1e-10]
        if len(anchors)>=2:parent.append((rid,b['layerId'],p,anchors))
    reports=[]
    for ch in plan['channels']:
        cid=ch['componentId'];foot=libs['FOOTPRINT',attrs[cid]['Footprint']]
        native={str(b['num']):(rid,b)for(kind,rid),b in foot.items()if kind=='PAD'}
        check(set(native)=={'1','2'},'Actual footprint exactly two pads '+ch['ref'])
        axis=ch['axisOfPositiveLocalX'];angle=math.degrees(math.atan2(axis[1],axis[0]));pads={}
        for num,world in ch['requiredWorldPads'].items():
            pid,pad=native[num];d=pad['defaultPad']
            check(padnets[cid,num,pid]==world['net'],'Actual numbered native pin net matches world-pad contract '+ch['ref']+'.'+num)
            check(d['padType']=='RECT' and d.get('radius',0)==0,'Exact rectangular native pad shape '+ch['ref']+'.'+num)
            w,h=d['width']*MM,d['height']*MM
            s=affinity.rotate(box(-w/2,-h/2,w/2,h/2),angle,origin=(0,0))
            pads[num]=affinity.translate(s,*world['xyMm'])
        gp=pads['2'];matching=[]
        for idx,poly in enumerate(ground_components):
            if not poly.covers(gp):continue
            anchors=[(rid,vp,ann,b)for rid,vp,ann,b in gndvia if poly.intersection(ann).area>1e-10]
            parent_reach=[]
            for rid,vp,ann,b in anchors:
                for fid,layer,ps,otheranchors in parent:
                    if ps.intersection(ann).area>1e-10:
                        parent_reach.append({'viaId':rid,'parentFILLId':fid,'layerId':layer,'parentExistingGNDviaCount':len(otheranchors),'parentAreaMm2':ps.area})
            matching.append({'groundSolidIndex':idx,'existingGNDViaIds':[x[0]for x in anchors],'unchangedParentPlaneReach':parent_reach})
        check(bool(matching) and any(x['existingGNDViaIds'] and x['unchangedParentPlaneReach']for x in matching),
              'Full exact native GND pad inside one literal retained solid, plated via reaches unchanged multi-anchor inner GND plane '+ch['ref'],matching)
        route=LineString(ch['signalRoute']['pointsMm']).buffer(ch['signalRoute']['widthMm']/2,quad_segs=128)
        vb=rows['VIA',ch['escapeViaId']]
        via=Point(vb['centerX']*MM,vb['centerY']*MM).buffer(vb['viaDiameter']*MM/2,quad_segs=128)
        check(vb['netName']==ch['net'] and route.intersection(via).area>1e-10 and route.intersection(pads['1']).area>1e-10,
              'Literal signal route joins expected protected ADC escape VIA and numbered pin1 '+ch['ref'])
        gndpen=op['beforeBody']['width']*MM/2
        gap=unary_union([route,pads['1']]).distance(final.buffer(gndpen))
        check(gap>=.1524,'Candidate signal pad/route to actual-stroked GND clearance >=.1524mm '+ch['ref'],gap)
        reports.append({'ref':ch['ref'],'net':ch['net'],'GNDReach':matching,'signalToFinalGNDGapMm':gap,
            'actualFootprintPadDimensionsMm':[native['1'][1]['defaultPad']['width']*MM,native['1'][1]['defaultPad']['height']*MM]})
    check(sha(PLAN)==PLAN_SHA,'Frozen manifest unchanged during audit')
    out=HERE/'adc10-bottom-direct4-prospective-independent-world-pad-ground-audit-20261018.json'
    report={'schema':'stm32h747-adc10-direct4-prospective-independent-20261018-v1','passed':not errors,
        'mode':'PROSPECTIVE_REQUIRED_WORLD_PADS_NOT_NATIVE_IMPLEMENTATION','manifestPath':str(PLAN),'manifestSha256':PLAN_SHA,
        'sourcePath':str(source),'sourceSha256':sha(source),'channels':reports,'addedGroundAreaMm2':added.area,
        'removedGroundAreaMm2':removed.area,'typedClipperGridHalfDiagonalMm':grid_radius,'skippedUnrelatedInvalidInnerFILLIds':skipped,
        'unchangedBottomGNDFILLIdsIncludedInLiteralUnion':used_unchanged_bottom,
        'unchangedBottomGNDFILLIdsNotNeededOrUsedAsAnchors':skipped_unchanged_bottom,
        'checks':checks,'errors':errors,'liveAPICalls':0,'nativeFilesWritten':0,
        'limits':['Bottom native angle/mirroring is deliberately NOT inferred here. Root must verify actual native numbered pin world coordinates after calibrated placement.',
            'This proof does not replace native full-board strict DRC, netlist or final CAM. No manufacturing approval.',
            'Full exact native footprint pad rectangles, literal same-plane GND solids, existing plated via annuli and unchanged multi-anchor inner GND planes are used; no label shortcut.',
            'Independent Shapely operations, not builder Clipper boolean results, prove ground continuity.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'failedTests':[x['test']for x in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
