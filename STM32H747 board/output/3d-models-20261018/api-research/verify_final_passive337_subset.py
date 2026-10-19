from collections import Counter
import hashlib
import json
from pathlib import Path
from inspect_standard_meshes import load,face_key

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
old=ROOT/'STM32H747_passives_337_STM32H747_passives_337'
new=ROOT/'STM32H747_calibrated407_STM32H747_calibrated407'
vertices,faces,_=load(old)
baseline=Counter(face_key(ids,vertices) for _,_,ids in faces)
old_face_count=len(faces)
del vertices,faces
vertices,faces,_=load(new)
source407=json.loads((HERE/'standard407-isolated-geometry.json').read_text())
stdrefs=[e['ref'] for e in json.loads((ROOT/'standard27-calibrated-apply-plan.json').read_text())['entries']]
model_ranges=[]
for ref in stdrefs+['TR1','SW1']:
    pieces=[p for p in source407['pieces'] if p['ref']==ref]
    model_ranges.append({'refs':[ref],'first':min(p['vertex_min'] for p in pieces),'last':max(p['vertex_max'] for p in pieces)})
header=json.loads((ROOT/'audits/final18-headers-calibrated407.json').read_text())
assert header['passed'] and header['header_vertex_union_matches_runtime_agent_topology_block']
model_ranges.append({'refs':['J1','J18']+[f'J{i}' for i in range(2,18)],'first':28863,'last':50615})
sot=json.loads((HERE/'final407-sot235-pieces.json').read_text())
for m in sot['full_models']:
    model_ranges.append({'refs':[m['ref']],'first':m['vertex_range'][0],'last':m['vertex_range'][1]})
owner={}
for index,r in enumerate(model_ranges):
    for i in range(r['first'],r['last']+1):
        assert i not in owner, ('overlapping known-model vertex range',r)
        owner[i]=index
matched=0
remaining_faces=0
known_model_faces=0
unexpected_remaining=0
for _,_,ids in faces:
    assigned={owner.get(i) for i in ids}
    assert len(assigned)==1, ('triangle crosses model range boundary',ids)
    if next(iter(assigned)) is not None:
        known_model_faces+=1
        continue
    remaining_faces+=1
    key=face_key(ids,vertices)
    if baseline[key]:
        baseline[key]-=1
        matched+=1
    else:
        unexpected_remaining+=1
missing=sum(baseline.values())
report={'schema':'stm32-final407-preserved-passive337-triangle-multiplicity-v1','passed':missing==0 and unexpected_remaining==0,'native_calls':0,
        'baseline':{'path':old.name,'sha256':hashlib.sha256(old.read_bytes()).hexdigest(),'face_count':old_face_count},
        'current':{'path':new.name,'sha256':hashlib.sha256(new.read_bytes()).hexdigest(),'face_count':len(faces)},
        'matched_baseline_faces_with_multiplicity':matched,'missing_baseline_faces':missing,'coordinate_rounding_mm':1e-6,
        'disjoint_known70_model_face_count':known_model_faces,'remaining_current_faces_after_known70_excluded':remaining_faces,
        'unexpected_remaining_faces':unexpected_remaining,'known_model_ranges':model_ranges,
        'prior_component_identity_and_side_coverage_audit':'audits/obj-passives337-spatial-reviewed.json',
        'limits':['This proves retention of baseline337models plus board triangles with multiplicity; model identity/side placement remains grounded in the prior337-instance spatial audit and current native binding metadata.',
                  'Five coincident resistor pairs are inherited. Their identical overlapping meshes do not independently identify individual reference names in OBJ.']}
(ROOT/'audits/final407-passive337-preserved.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
