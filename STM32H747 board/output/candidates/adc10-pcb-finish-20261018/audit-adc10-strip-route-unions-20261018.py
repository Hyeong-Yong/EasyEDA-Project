"""Cumulative actual route union audit, independent of native LINE IDs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import runpy
from shapely.geometry import LineString
from shapely.ops import unary_union

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PARSE=runpy.run_path(str(HERE/'audit-adc10-copper-cut-readback-20261018.py'))['parse']
MM=.0254


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def group(b):return b['layerId'],b['netName'].upper(),round(b['width'],8)


def copper(b):
    return LineString([(b['startX']*MM,b['startY']*MM),(b['endX']*MM,b['endY']*MM)]).buffer(b['width']*MM/2,quad_segs=64)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--count',required=True,type=int)
    p.add_argument('--manifest',required=True)
    p.add_argument('--manifest-sha',required=True)
    p.add_argument('--baseline',required=True)
    p.add_argument('--baseline-sha',required=True)
    p.add_argument('--source',required=True)
    p.add_argument('--prove-contained-bias-width-trim',action='store_true')
    args=p.parse_args()
    assert args.count in [40,80,120,160,200,204]
    manifest,base,source=map(lambda s:Path(s).resolve(),[args.manifest,args.baseline,args.source])
    assert sha(manifest)==args.manifest_sha and sha(base)==args.baseline_sha
    plan=json.loads(manifest.read_text());assert len(plan['newLineCreates'])==204
    before,bh=PARSE(base);after,ah=PARSE(source)
    ops=plan['newLineCreates'][:args.count]
    new_expected=[];max_quant=0.
    for o in ops:
        b={'layerId':o['layerId'],'netName':o['net'],'width':round(o['widthMil'],4),
           'startX':round(o['startXMil'],4),'startY':round(o['startYMil'],4),
           'endX':round(o['endXMil'],4),'endY':round(o['endYMil'],4)}
        assert b['layerId']==1 and b['width']>=6
        max_quant=max(max_quant,*[abs(b[field]-o[original])*MM for field,original in
            [('startX','startXMil'),('startY','startYMil'),('endX','endXMil'),('endY','endYMil')]])
        new_expected.append(b)
    changed_groups={group(b)for b in new_expected}
    old_lines={k:b for k,b in before.items()if k[0]=='LINE'}
    new_lines={k:b for k,b in after.items()if k[0]=='LINE'}
    expected_by_group=defaultdict(list);actual_by_group=defaultdict(list)
    for k,b in old_lines.items():expected_by_group[group(b)].append(b)
    for b in new_expected:expected_by_group[group(b)].append(b)
    for k,b in new_lines.items():actual_by_group[group(b)].append(b)
    errors=[];checks=[]
    def check(ok,name,detail=None):
        row={'test':name,'passed':bool(ok)}
        if detail is not None:row['detail']=detail
        checks.append(row)
        if not ok:errors.append(row)
    nonline_old={k:b for k,b in before.items()if k[0]not in ['LINE','DOCHEAD']}
    nonline_new={k:b for k,b in after.items()if k[0]not in ['LINE','DOCHEAD']}
    nld=[{'type':k[0],'id':k[1]}for k in nonline_old.keys()|nonline_new.keys()if nonline_old.get(k)!=nonline_new.get(k)]
    check(not nld,'All nonLINE primitive membership and bodies exactly unchanged',nld)
    surviving_diffs=[{'type':k[0],'id':k[1]}for k in old_lines.keys()&new_lines.keys()if old_lines[k]!=new_lines[k]]
    check(not surviving_diffs,'All surviving original LINE IDs retain exact complete bodies',surviving_diffs)
    deleted=old_lines.keys()-new_lines.keys();added=new_lines.keys()-old_lines.keys()
    bad_deleted=[{'id':k[1],'group':group(old_lines[k])}for k in deleted if group(old_lines[k])not in changed_groups]
    check(not bad_deleted,'Only LINE groups receiving planned prefix may merge away original IDs',bad_deleted)
    bad_new=[]
    for k in added:
        b=new_lines[k]
        if group(b)not in changed_groups or b.get('partitionId')!=''or b.get('groupId')!=0 or b.get('locked')is not False or b.get('zIndex')!=-1:
            bad_new.append({'id':k[1],'body':b})
    check(not bad_new,'Only approved prefix TOP net/width/default-property LINE records created',bad_new)
    union_report=[];width_transfer_proofs=[]
    for g in sorted(expected_by_group.keys()|actual_by_group.keys()):
        if g not in changed_groups:
            a={k:b for k,b in old_lines.items()if group(b)==g};b={k:v for k,v in new_lines.items()if group(v)==g}
            check(a==b,'Unaffected LINE group exact ID/body protection '+str(g))
            continue
        old=unary_union([copper(b)for b in expected_by_group[g]])
        actual=unary_union([copper(b)for b in actual_by_group[g]])
        xor=old.symmetric_difference(actual).area;hd=old.hausdorff_distance(actual)
        row={'layerId':g[0],'netUpper':g[1],'widthMil':g[2],
            'expectedLineContributions':len(expected_by_group[g]),'actualNativeLINEs':len(actual_by_group[g]),
            'symmetricDifferenceAreaMm2':xor,'hausdorffMm':hd}
        union_report.append(row)
        passed=xor<1e-7 and hd<1e-7
        if not passed and args.prove_contained_bias_width_trim and args.count==204 and g==(1,'ADC_BIAS_2V5',12.0):
            expected_net=unary_union([copper(b)for k,values in expected_by_group.items()if k[:2]==g[:2]for b in values])
            actual_net=unary_union([copper(b)for k,values in actual_by_group.items()if k[:2]==g[:2]for b in values])
            expected_other=unary_union([copper(b)for k,values in expected_by_group.items()if k[:2]==g[:2]and k!=g for b in values])
            actual_other=unary_union([copper(b)for k,values in actual_by_group.items()if k[:2]==g[:2]and k!=g for b in values])
            delta=old.symmetric_difference(actual)
            proof={'group':g,'perWidthDifferenceAreaMm2':xor,'perWidthDifferenceBoundsMm':list(delta.bounds),
                'netAllWidthsXORAreaMm2':expected_net.symmetric_difference(actual_net).area,
                'netAllWidthsHausdorffMm':expected_net.hausdorff_distance(actual_net),
                'perWidthDifferenceOutsideExpectedOtherWidthCopperMm2':delta.difference(expected_other).area,
                'perWidthDifferenceOutsideActualOtherWidthCopperMm2':delta.difference(actual_other).area,
                'classification':'Native trims narrow12mil same-net branch inside already existing wider15.748mil REF-trunk copper. Physical copper footprint is exactly conserved; no numerical tolerance is enlarged.'}
            passed=proof['netAllWidthsXORAreaMm2']<1e-12 and proof['netAllWidthsHausdorffMm']<1e-10 and proof['perWidthDifferenceOutsideExpectedOtherWidthCopperMm2']<1e-12 and proof['perWidthDifferenceOutsideActualOtherWidthCopperMm2']<1e-12
            width_transfer_proofs.append(proof)
            row['containedSameNetWidthTransferProof']=proof
        check(passed,'Native copper union equals before+4decimal-mil planned prefix '+str(g),row)
    attrs=defaultdict(dict)
    for(k,rid),b in after.items():
        if k=='ATTR':attrs[b['parentId']][b['key']]=b['value']
    refs={a['Designator']:cid for cid,a in attrs.items()if'Designator'in a};inverse={cid:ref for ref,cid in refs.items()}
    pins={}
    for(k,rid),b in after.items():
        if k!='PAD_NET'or not b.get('padNet'):continue
        _,cid,num,pid=json.loads(rid);key=inverse[cid],str(num)
        check(key not in pins or pins[key]==b['padNet'],'Physical duplicate numbered pads agree '+str(key));pins[key]=b['padNet']
    cp=ROOT/'output/candidates/adc10-dc-buffer-20261017/independent-adc10-expected-full-pin-contract-20261017.json'
    expected_pins={(v['ref'],str(v['number'])):v['net']for v in json.loads(cp.read_text())['expectedPins']}
    check(len(refs)==354 and len(pins)==1136 and pins==expected_pins,'Frozen354parts1136pins independent contract')
    suffix='-contained-width-proof'if args.prove_contained_bias_width_trim else''
    out=HERE/f'adc10-strip-route-lines-{args.count:03d}{suffix}-independent-union-audit-20261018.json'
    report={'schema':'stm32h747-adc10-cumulative-native-route-union-audit-20261018-v1','passed':not errors,'errors':errors,
        'plannedPrefixSegments':args.count,'manifestPath':str(manifest),'manifestSha256':sha(manifest),
        'baselinePath':str(base),'baselineSha256':sha(base),'sourcePath':str(source),'sourceSha256':sha(source),
        'beforeLINECount':len(old_lines),'actualLINECount':len(new_lines),'originalLINEIdsMergedAway':sorted(k[1]for k in deleted),
        'newNativeLINEIds':sorted(k[1]for k in added),'protectedNonLINECount':len(nonline_old),
        'maxPlannedCoordinateQuantizationMm':max_quant,'unionGroups':union_report,
        'nativeContainedSameNetWidthTransferProofs':width_transfer_proofs,
        'physicalParts':len(refs),'connectedPins':len(pins),'checks':checks,
        'geometryTolerance':{'expectedCoordinates':'Every planned endpoint rounded to4decimal mil before geometry comparison; original LINE coordinates unchanged',
            'maxUnionXORAreaMm2':1e-7,'maxHausdorffMm':1e-7,'meaning':'Numerical Boolean mesh tolerance only, smaller than native coordinate quantum; not a design-rule waiver'},
        'limitations':['Actual static copper geometry/record containment audit only, not complete signal graph or final native DRC.','Every unaffected old LINE ID/body and every nonLINE body stays exact. Deleted affected LINE IDs are allowed only when full net/layer/width copper union is conserved.','No API/native writes; no fabrication approval.'],
        'liveAPICalls':0,'nativeFilesWritten':0}
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'prefix':args.count,
        'unionGroups':len(union_report),'maxXORMm2':max((v['symmetricDifferenceAreaMm2']for v in union_report),default=0),
        'maxHausdorffMm':max((v['hausdorffMm']for v in union_report),default=0),
        'physicalParts':len(refs),'connectedPins':len(pins),'errorTests':[e['test']for e in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
