from collections import Counter
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
AUDITS=ROOT/'audits'
def read(name):
    return json.loads((ROOT/name).read_text())
parts={p['ref']:p for p in read('inventory/components-437.json')}
passive=read('audits/final407-passive337-preserved.json')
sot=read('audits/final407-sot235-23-geometry.json')
standard=read('audits/final407-standard29-geometry.json')
headers=read('audits/final18-headers-calibrated407.json')
native=read('audits/model-metadata-calibrated407-reviewed.json')
drc=read('audits/native-drc-model-stage-calibrated407.json')
checkpoint=read('audits/checkpoint-scope-calibrated407-strict.json')
checkpoint_classified=read('audits/checkpoint-scope-calibrated407-exact-classified.json')
groups=[
    {'name':'passives337','plan':'passive-3d-apply-plan.json','count':337,'audit':'audits/final407-passive337-preserved.json','passed':passive['passed'],
     'faces_including_retained_board':passive['matched_baseline_faces_with_multiplicity'],'method':'Disjoint nonpassive70 vertex ranges removed first; exact remaining triangle-coordinate multiset equals prior verified337-plus-PCB baseline at1e-6mm rounding, including duplicate multiplicity.'},
    {'name':'sot235_23','plan':'sot23-5-3d-apply-plan.json','count':23,'audit':'audits/final407-sot235-23-geometry.json','passed':sot['passed'],
     'faces':sum(r['faces'] for r in sot['rows']),'method':'All23 native bodies and5physical leads per body; dimensions, centers, mounting plane,3-left/2-right rows and0.95mm pitch checked.'},
    {'name':'standards27','plan':'standard27-calibrated-apply-plan.json','count':27,'audit':'audits/final407-standard29-geometry.json','passed':all(r['passed'] for r in standard['standard27_unchanged_from_verified_export']),
     'faces':sum(r['face_count'] for r in standard['standard27_unchanged_from_verified_export']),'method':'Identical material/topology/vertex ordering plus maxvertex motion1.612e-6mm transfers prior fullXYZ/center/materialpiece/lead-ball pitch proof to final native export.'},
    {'name':'headers_sma18','plan':'headers-native-final-apply-plan-normalized.json','count':18,'audit':'audits/final18-headers-calibrated407.json','passed':headers['passed'],
     'faces':headers['selected_header_faces'],'method':'All16SMA neck/5legs and hole cross-sections; J1all14contacts/locators; J18all10pins/hole placement and THT vertical positioning checked separately.'},
    {'name':'switch_transformer2','plan':'switch-xfmr-calibrated-apply-plan.json','count':2,'audit':'audits/final407-standard29-geometry.json','passed':all(r['passed'] for r in standard['new_switch_transformer_verified']),
     'faces':sum(r['face_count'] for r in standard['new_switch_transformer_verified']),'method':'Actual final fullXYZ,center,16/4physical terminals,1.27/4.5mm pitch,andminZ0verified; generic package-equivalent visual models.'},
]
allrefs=[]
for group in groups:
    entries=read(group['plan'])['entries']
    refs=[e['ref'] for e in entries]
    assert len(refs)==group['count']
    group['refs']=refs
    group['plan_sha256']=hashlib.sha256((ROOT/group['plan']).read_bytes()).hexdigest()
    allrefs.extend(refs)
assert len(allrefs)==len(set(allrefs))==407
assert all(not parts[r]['dnp'] and not r.startswith('TP') for r in allrefs)
assert set(allrefs)==set(native['applied_refs'])
face_sum=sum(g.get('faces',g.get('faces_including_retained_board')) for g in groups)
assert face_sum==headers['export']['faces']==760928
assert passive['remaining_current_faces_after_known70_excluded']==624707 and passive['disjoint_known70_model_face_count']==136221
sha=passive['current']['sha256']
assert sot['source_export_sha256']==standard['source_export_sha256']==headers['export']['sha256']==sha
physical=[r for r,p in parts.items() if not p['dnp'] and not r.startswith('TP')]
unlinked=sorted(set(physical)-set(allrefs))
report={
    'schema':'stm32-current407-native-geometry-verification-index-v1',
    'scope':'CURRENT_LINKED407_NATIVE_OBJ_GEOMETRY_ONLY_NOT_ALL412_PROJECT_COMPLETION',
    'geometry_passed':all(g['passed'] for g in groups), 'native_calls_by_index_builder':0,
    'export':{'path':'STM32H747_calibrated407_STM32H747_calibrated407','bytes':headers['export']['bytes'],'sha256':sha,'faces':face_sum},
    'board_components':437,'fitted_physical_targets':len(physical),'linked_models_geometry_verified':len(allrefs),
    'all_fitted412_ready':False,'remaining_unlinked_fitted_refs':unlinked,
    'excluded_dnp_refs':sorted(r for r,p in parts.items() if p['dnp']),'excluded_testpoint_refs':sorted(r for r in parts if r.startswith('TP')),
    'verified_side_counts':dict(Counter(parts[r]['side'] for r in allrefs)),
    'disjoint_complete_face_partition':{'passed':True,'known70_nonpassive_faces':136221,'retained337_plus_PCB_faces':624707,'total':face_sum,
        'missing_baseline_faces':passive['missing_baseline_faces'],'unexpected_remaining_faces':passive['unexpected_remaining_faces'],
        'cross_model_range_triangles':0,'proof':'Every final triangle lies wholly inside exactly one known70-model range or the remaining passive337-plus-PCB partition; remaining multiset equals baseline. Counts close exactly760928.'},
    'groups':groups,
    'separate_native_metadata_and_DRC_gates':{'native_binding_metadata_review_passed':native['passed'],'native_metadata_audit':'audits/model-metadata-calibrated407-reviewed.json',
        'native_DRC_passed':drc['passed'],'native_DRC_audit':'audits/native-drc-model-stage-calibrated407.json'},
    'separate_saved_checkpoint_strict_gate_at_index_build':{'passed':checkpoint['passed'],'audit':'audits/checkpoint-scope-calibrated407-strict.json',
        'not_covered_by_geometry_pass':True,'errors':checkpoint['errors'],'historical_unclassified_result_preserved':True},
    'separate_saved_checkpoint_exact_classified_gate':{'passed':checkpoint_classified['passed'],
        'audit':'audits/checkpoint-scope-calibrated407-exact-classified.json',
        'not_covered_by_geometry_pass':True,
        'scope':'Latest separate checkpoint review classifies only the exact inherited FILL/runtime representation, selector and two empty-NET defaults; original raw strict result remains preserved.',
        'checkpoint_sha256':checkpoint_classified['after']['sha256'],
        'non_PCB_raw_design_documents_unchanged_count':checkpoint_classified['non_PCB_raw_design_documents_unchanged_count'],
        'non_PCB_design_geometry_and_connections_unchanged':checkpoint_classified['non_PCB_design_geometry_and_connections_unchanged']},
    'limits':[
        '407of412fitted physical components have verified current native geometry. CN1,CN2,CN3,CN4,L1 remain unlinked; do not describe the entire board as fully populated.',
        'Geometry pass is not itself a saved-project checkpoint-scope pass. Latest separate exact-classified checkpoint review passed; the historical initial unclassified strict failure is retained as evidence and is not the current classified result.',
        'Models are package-equivalent visuals unless exact provenance separately establishes otherwise; no manufacturer mechanical clearance or exact MPN marking approval.',
        'Conservative manual pin/polarity QA remains on LED D2,D3,D4,D6,U3,D1,Q1 and header marking interpretations as recorded in individual audits.',
        'Inherited five coincident resistor pairs remain; OBJ cannot distinguish individual identical overlapping ref meshes without native metadata.',
        'Qualified system-library references are not proof that full source models are embedded in a portable saved project.'
    ]}
output=AUDITS/'final407-geometry-verification-index.json'
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'output':str(output),'geometry_passed':report['geometry_passed'],'verified_models':len(allrefs),'fitted_physical_targets':len(physical),
                  'unlinked':unlinked,'face_partition_total':face_sum,'checkpoint_strict_gate':checkpoint['passed']},indent=2))
