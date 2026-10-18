"""Independent actual FILL geometry/source-scope proof; no API writes."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
from shapely.geometry import Polygon

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
PARSE=runpy.run_path(str(HERE/'audit-adc10-copper-cut-readback-20261018.py'))['parse']
BEFORE=ROOT/'output/validation/native-adc10-pcb-strip_place4-20261018.epru'
AFTER=ROOT/'output/validation/native-adc10-pcb-strip_fill_v3-20261018.epru'
PLAN=HERE/'strip/adc10-strip-phase1-explicit-closed-API-polygon-20261018.json'
PLAN_SHA='cb5554b84c2d4fcf2b4001a31951a97111e1296719ce2142627dc75ab21be932'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def rings(path):
    out=[]
    for part in path:
        assert all(not isinstance(v,str)or v=='L'for v in part)
        values=[v for v in part if not isinstance(v,str)]
        assert len(values)%2==0
        out.append([(values[i]*.0254,values[i+1]*.0254)for i in range(0,len(values),2)])
    return out


def geometry(path):
    r=rings(path)
    p=Polygon(r[0],r[1:])
    assert p.is_valid and not p.is_empty
    return p


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--allow-export-precision',action='store_true')
    parser.add_argument('--tag',default='')
    args=parser.parse_args()
    assert sha(PLAN)==PLAN_SHA
    plan=json.loads(PLAN.read_text())
    f=plan['fillPathUpdates'][0];key='FILL',f['id']
    before,bh=PARSE(BEFORE);after,ah=PARSE(AFTER)
    intended=geometry(f['afterPath']);actual=geometry(after[key]['path']);old=geometry(before[key]['path'])
    errors=[]
    if before.keys()!=after.keys():errors.append('Native primitive membership changed')
    non_target=[list(k)for k,b in before.items()if k[0]!='DOCHEAD'and k!=key and after.get(k)!=b]
    if non_target:errors.append('Protected non-target native bodies changed')
    fields=[k for k in before[key].keys()|after[key].keys()if before[key].get(k)!=after[key].get(k)]
    if set(fields)!={'path','refs'}or before[key]['refs']is not None or after[key]['refs']!=[None]:errors.append('Unexpected target FILL field normalization')
    if {k:v for k,v in before[key].items()if k not in ['path','refs']}!={k:v for k,v in after[key].items()if k not in ['path','refs']}:errors.append('Target FILL nonpath fields changed')
    xor=intended.symmetric_difference(actual).area;hd=intended.hausdorff_distance(actual)
    add=actual.difference(old).area;removed=old.difference(actual).area
    precision_qualified=False;quantized_xor=None;quantized_hd=None;max_coordinate_error=0.;numeric_count=0
    if args.allow_export_precision:
        intended_raw=[[v for v in p if not isinstance(v,str)]for p in f['afterPath']]
        actual_raw=[[v for v in p if not isinstance(v,str)]for p in after[key]['path']]
        precision_qualified=len(intended_raw)==len(actual_raw)and all(len(a)==len(b)for a,b in zip(intended_raw,actual_raw))
        if precision_qualified:
            for wanted,native in zip(intended_raw,actual_raw):
                for w,n in zip(wanted,native):
                    numeric_count+=1;max_coordinate_error=max(max_coordinate_error,abs(n-w)*.0254)
                    if n!=round(w,4):precision_qualified=False
        qpath=[[round(v,4)if isinstance(v,(int,float))else v for v in p]for p in f['afterPath']]
        q=geometry(qpath)
        quantized_xor=q.symmetric_difference(actual).area;quantized_hd=q.hausdorff_distance(actual)
        precision_qualified=precision_qualified and quantized_xor<1e-12 and quantized_hd<1e-12
    if (xor>1e-10 or hd>1e-10)and not precision_qualified:errors.append('Actual copper differs geometrically from reviewed exact polygon')
    if add>1e-10:errors.append('Unexpected copper addition')
    actual_rings=rings(after[key]['path']);intent_rings=rings(f['afterPath']);old_rings=rings(before[key]['path'])
    if actual_rings!=intent_rings and not precision_qualified:errors.append('Native contour numeric vertices/order differs from reviewed explicitly closed contours')
    if actual_rings[0]!=old_rings[0]:errors.append('Original outer numeric contour changed')
    report={'schema':'stm32h747-adc10-independent-strip-fill-v3-actual-geometry-audit-20261018-v1','passed':not errors,'errors':errors,
        'beforePath':str(BEFORE),'beforeSha256':sha(BEFORE),'sourcePath':str(AFTER),'sourceSha256':sha(AFTER),
        'manifestPath':str(PLAN),'manifestSha256':PLAN_SHA,'targetFILL':f['id'],'nativeRecordCount':len(after),
        'protectedNonTargetBodyDifferences':non_target,'protectedNonTargetBodyCount':len(before)-2,
        'targetChangedFields':fields,'refsNormalization':{'before':None,'after':[None]},
        'actualVersusReviewedSymmetricDifferenceAreaMm2':xor,'actualVersusReviewedHausdorffMm':hd,
        'actualCopperAdditionVersusOriginalAreaMm2':add,'actualCopperRemovedAreaMm2':removed,
        'oldContourCount':len(old_rings),'actualContourCount':len(actual_rings),
        'allReviewedNumericVerticesAndContourOrderExact':actual_rings==intent_rings,'originalOuterNumericContourExact':actual_rings[0]==old_rings[0],
        'typedCoordinateRepresentationQualification':{'passed':precision_qualified,'numericCoordinatesChecked':numeric_count,
            'everyActualCoordinateEqualsRoundReviewedMil4':precision_qualified,'maxAxisCoordinateErrorMm':max_coordinate_error,
            'actualVersusExactlyQuantizedApprovedPolygonXORAreaMm2':quantized_xor,
            'actualVersusExactlyQuantizedApprovedPolygonHausdorffMm':quantized_hd,
            'scope':'Only all numeric coordinates mapping exactly to4decimalmil, identical vertex/contour count/order. No other geometry tolerance or rule change.'},
        'publicAPISerializationNote':'Repeated L commands may be compressed, while every numeric vertex, order and explicit closure is exact. Native FILL refs normalizes null to [null] only on the one target record.',
        'limitations':['Static actual-source and approved geometry equivalence only, not final native DRC or fabrication approval.','This is pad-clearance FILL stage; new204routes and final routed-copper ground connectivity are audited separately.'],
        'liveAPICalls':0,'nativeFilesWritten':0}
    suffix='-'+args.tag if args.tag else''
    out=HERE/f'adc10-strip-fill-v3{suffix}-independent-geometry-audit-20261018.json'
    out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'sourceSha256':sha(AFTER),'xorMm2':xor,'copperAdditionMm2':add,'removedMm2':removed,'protectedBodies':len(before)-2,'errors':errors},indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':main()
