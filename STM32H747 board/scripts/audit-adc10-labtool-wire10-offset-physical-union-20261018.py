"""Read-only exact-support delta and analytic stroke containment at stopped wire10."""
import json,hashlib,runpy,math
from pathlib import Path
from collections import defaultdict
from fractions import Fraction as F
from shapely.geometry import LineString
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1];H=ROOT/'output/candidates/adc10-labtool-20261018';OUT=H/'audits';M=runpy.run_path(str(H/'independent-pcb-placement-proposal.py'));A=runpy.run_path(str(ROOT/'scripts/audit-adc10-labtool-copper-readback-20261018.py'));MM=.0254
BASE=ROOT/'output/validation/native-adc10-pcb-labtool_107_placed_v6_saved-20261018.epru';ACT=ROOT/'output/validation/native-adc10-pcb-labtool_copper_wire10-20261018.epru';MAN=H/'pcb-final-copper-v5-execution.json'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def seg(b):return tuple(b[k] for k in ('startX','startY','endX','endY'))
def support(s):return A['canonical_segments']([s])[0][0]
def dist2_point_segment(p,s):
    x,y=map(lambda x:F(str(x)),p);a,b,c,d=map(lambda x:F(str(x)),s);dx,dy=c-a,d-b;t=(x-a)*dx+(y-b)*dy;den=dx*dx+dy*dy
    if t<=0:return (x-a)**2+(y-b)**2
    if t>=den:return (x-c)**2+(y-d)**2
    return ((x-a)*dy-(y-b)*dx)**2/den
def main():
    assert sha(ACT)=='6786a3df2a3795793219d85858560e421afb8ac9515b52ef4012c9360c24736e'
    old=M['parse'](BASE);actual=M['parse'](ACT);manifest=json.loads(MAN.read_text());expected=[];added=[]
    for (k,r),b in old.items():
        if k=='LINE' and b.get('netName')=='ADC_OFFSET_0V97' and b.get('layerId')==1:expected.append({'id':r,'width':b['width'],'segment':seg(b),'source':'baseline'})
    count=0
    for batch in manifest['batches']:
        for o in batch['operations']:
            if o['action']=='line':
                count+=1
                if o['net']=='ADC_OFFSET_0V97' and o['layerId']==1:expected.append({'id':o['key'],'width':o['widthMil'],'segment':tuple(o['startXYMil']+o['endXYMil']),'source':'planned'})
        if batch['stage']=='copper_wire10':break
    assert count==440,count
    observed=[{'id':r,'width':b['width'],'segment':seg(b),'source':'actual'} for (k,r),b in actual.items() if k=='LINE' and b.get('netName')=='ADC_OFFSET_0V97' and b.get('layerId')==1]
    eg=defaultdict(list);ag=defaultdict(list)
    for p in expected:
        if p['width']==8:eg[support(p['segment'])].append(p)
    for p in observed:
        if p['width']==8:ag[support(p['segment'])].append(p)
    different=[]
    for k in eg.keys()|ag.keys():
        e=[p['segment'] for p in eg[k]];a=[p['segment'] for p in ag[k]]
        if A['canonical_segments'](e)!=A['canonical_segments'](a):different.append(k)
    ep=[p for k in different for p in eg[k]];ap=[p for k in different for p in ag[k]]
    wider=[p for p in expected if p['width']>8]
    containment=[]
    for side,items in [('expected',ep),('actual',ap)]:
        for p in items:
            witnesses=[]
            for w in wider:
                radius=(F(str(w['width']))-F(str(p['width'])))/2
                ds=[dist2_point_segment(p['segment'][:2],w['segment']),dist2_point_segment(p['segment'][2:],w['segment'])]
                if max(ds)<=radius*radius:witnesses.append({'widerId':w['id'],'widerWidthMil':w['width'],'widerSegmentMil':w['segment'],'radiusDifferenceMil':float(radius),'endpointSquaredDistancesMil2':[str(v) for v in ds],'radiusDifferenceSquaredMil2':str(radius*radius),'strictRationalInequalityHolds':max(ds)<radius*radius})
            containment.append({'side':side,'id':p['id'],'widthMil':p['width'],'segmentMil':p['segment'],'segmentMm':[v*MM for v in p['segment']],'fullyContainedInOneUnchangedWideStroke':bool(witnesses),'witnesses':witnesses})
    # Diagnostic tessellation is NOT the proof: analytic rational endpoint
    # distance in a convex round-cap wide stroke is authoritative when present.
    def shape(items):return unary_union([LineString([p['segment'][:2],p['segment'][2:]]).buffer(p['width']/2,resolution=64) for p in items])
    es,aa=shape(expected),shape(observed);report={'sourceSha256':sha(ACT),'baselineSha256':sha(BASE),'executionManifestSha256':sha(MAN),'nativeCalls':0,'expectedPlannedLinesApplied':count,'expectedOffsetSegments':len(expected),'actualOffsetSegments':len(observed),'different8milSupportCount':len(different),'differentExpectedSegments':ep,'differentActualSegments':ap,'analyticContainment':containment,'allDifferingStrokesRedundantWithinUnchangedWiderStroke':bool(containment) and all(p['fullyContainedInOneUnchangedWideStroke'] for p in containment),'diagnosticTessellationOnly':{'bufferResolution':64,'addedCopperAreaMm2':aa.difference(es).area*MM*MM,'removedCopperAreaMm2':es.difference(aa).area*MM*MM,'symmetricDifferenceAreaMm2':es.symmetric_difference(aa).area*MM*MM},'interpretation':'No broad distance/area tolerance is authorized. Analytic containment, when true for both expected and actual differing strokes, proves their differences are invisible in the union with the exact unchanged wider stroke. Otherwise this report is diagnostic only and the native stage remains stopped.'}
    target=OUT/'wire10-offset-physical-union-independent.json';assert not target.exists();target.write_text(json.dumps(report,indent=2,default=str)+'\n');print(json.dumps({'report':str(target),'sha256':sha(target),'expectedDelta':ep,'actualDelta':ap,'allContained':report['allDifferingStrokesRedundantWithinUnchangedWiderStroke'],'diagnosticArea':report['diagnosticTessellationOnly']}))
if __name__=='__main__':main()
