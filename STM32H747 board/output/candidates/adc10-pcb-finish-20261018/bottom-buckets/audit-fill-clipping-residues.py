"""Locate and bound exact integer clipping residue, without changing outputs."""
import json
import math
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'build-local-fill-operations.py'))
def segdist(p,a,b):
    dx=b[0]-a[0];dy=b[1]-a[1]
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy))) if dx or dy else 0
    return math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
def near(p,paths):
    if any(M['pc'].PointInPolygon(p,q)!=0 for q in paths if M['pc'].Area(q)>0):
        # Correctly account for negative cut holes rather than assume interior.
        tiny=[[(p[0]-1,p[1]-1),(p[0]+1,p[1]-1),(p[0]+1,p[1]+1),(p[0]-1,p[1]+1)]]
        if M['inter'](tiny,paths):return 0
    return min(segdist(p,a,b) for q in paths for a,b in zip(q,q[1:]+q[:1]))/M['SCALE']

d=json.loads((HERE/'remaining6-rebased-layout-local-api-operations.json').read_text())
result=[]
for o in d['fillModifyOperations']:
    if not any(e.get('fillId')==o['primitiveId'] for e in d['errors']):continue
    raw=M['filled_rings'](o['beforeBody']['path'])
    new=M['filled_rings'](o['afterNativeBody']['path'])
    new.extend(p for cr in d['fillCreateOperations'] if cr['sourceFillId']==o['primitiveId'] for p in M['filled_rings'](cr['afterNativePaths']))
    cuts=[M['ip'](q) for q in o['newCutRingsXYmm']]
    removed=M['diff'](raw,new)
    residue=M['diff'](removed,cuts)
    guard=M['diff'](removed,M['offset'](cuts,.000002))
    sample=[]
    for p in residue+guard:
        pts=p+[(round((a[0]+b[0])/2),round((a[1]+b[1])/2)) for a,b in zip(p,p[1:]+p[:1])]
        sample.append({'bboxMm':M['paths_bbox']([p]),'areaMm2':abs(M['pc'].Area(p))/M['SCALE']**2,'maxSampleDistanceFromNominalCutMm':max(near(q,cuts) for q in pts),'maxSampleDistanceFromOldBoundaryMm':max(min(segdist(q,a,b) for ring in raw for a,b in zip(ring,ring[1:]+ring[:1]))/M['SCALE'] for q in pts),'vertices':M['fp'](p)})
    result.append({'fillId':o['primitiveId'],'net':o['net'],'layerId':o['layerId'],'outsideCutAreaMm2':M['area'](residue),'guardAreaMm2':M['area'](guard),'residualPolygons':sample})
print(json.dumps(result,indent=2))
