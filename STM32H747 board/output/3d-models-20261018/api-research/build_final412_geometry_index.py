"""Combine independently audited native 412-model populated-view evidence.

This is an analysis-only index; it cannot convert a viewer-placement pass into
manufacturer fit certification or prove a checkpoint embeds external assets.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT.parent.parent
AUDITS = ROOT/'audits'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(relative):
    return json.loads((ROOT/relative).read_text(encoding='utf-8'))


def evidence(relative, data=None):
    row = {'path':relative,'sha256':digest(ROOT/relative)}
    if data is not None and 'passed' in data:
        row['passed'] = data['passed']
    return row


def source_file(data):
    path = Path(data['path'])
    if not path.is_absolute():
        path = BOARD/path
    assert digest(path) == data['sha256'], str(path)
    return {'path':data['path'],'sha256':data['sha256'],'bytes':path.stat().st_size}


def main():
    parts = {p['ref']:p for p in read('inventory/components-437.json')}
    previous = read('audits/final407-geometry-verification-index.json')
    preservation = read('audits/final412-existing407-preserved.json')
    local5 = read('audits/local5-native-final412-registration.json')
    native = read('audits/model-metadata-final412-reviewed-case-reuse.json')
    checkpoint = read('audits/checkpoint-scope-final412-exact-classified.json')
    drc = read('audits/native-drc-model-stage-final412.json')
    local_plan = read('local5-session-model-plan.json')

    assert previous['geometry_passed'] and previous['linked_models_geometry_verified'] == 407
    assert preservation['passed'] and preservation['comparison']['missing_prior_geometry_triangles'] == 0
    assert preservation['comparison']['missing_prior_geometry_appearance_triangles'] == 0
    assert local5['viewer_placement_passed'] is True
    assert local5['exact_mechanical_fidelity_proven'] is False
    assert local5['mechanical_fit_certified'] is False
    assert native['passed'] and checkpoint['passed'] and drc['passed']
    assert native['applied_model_count'] == checkpoint['model_count'] == 412
    assert checkpoint['unlinked_fitted_refs'] == []
    assert checkpoint['non_PCB_design_geometry_and_connections_unchanged'] is True

    current_sha = preservation['export']['sha256']
    assert local5['current']['sha256'] == current_sha
    assert digest(ROOT/preservation['export']['path']) == current_sha
    assert preservation['baseline']['sha256'] == previous['export']['sha256']
    assert native['source']['sha256'] == checkpoint['native_source']['sha256']
    source = source_file(native['source'])
    saved = source_file(checkpoint['after'])
    captures = []
    for side in ('top','bottom'):
        relative = f'output/validation/STM32H747_assembly_412_{side}_native_capture_20261018.jpg'
        path = BOARD/relative
        assert path.is_file(), str(path)
        captures.append({'side':side,'path':relative,'bytes':path.stat().st_size,'sha256':digest(path),
                         'source':'Root captured the displayed native 412-model 3D viewer; index records provenance, not pixel-based mechanical metrology.'})

    previous_refs = [ref for group in previous['groups'] for ref in group['refs']]
    new_refs = [entry['ref'] for entry in local_plan['entries']]
    assert len(set(previous_refs)) == len(previous_refs) == 407
    assert set(new_refs) == {'CN1','CN2','CN3','CN4','L1'}
    assert set(local5['component_models']) == set(new_refs)
    assert not set(previous_refs).intersection(new_refs)
    allrefs = previous_refs + new_refs
    physical = sorted(ref for ref,p in parts.items() if not p['dnp'] and not ref.startswith('TP'))
    assert sorted(allrefs) == physical == sorted(native['applied_refs'])
    assert len(allrefs) == len(set(allrefs)) == 412

    added = sum(row['added_triangles'] for row in local5['component_models'].values())
    assert added == preservation['comparison']['added_triangles_not_in_prior407_multiset'] == 7120
    assert local5['unmatched_added_faces'] == 0
    assert preservation['export']['faces'] == 760928 + added == 768048
    groups = []
    for old in previous['groups']:
        group = dict(old)
        group['current412_preservation'] = 'Exact parsed-coordinate and material triangle multiset, including multiplicity; no rounding/tolerance.'
        groups.append(group)
    groups.append({'name':'project_local5','count':5,'refs':new_refs,
                   'plan':'local5-session-model-plan.json',
                   'plan_sha256':digest(ROOT/'local5-session-model-plan.json'),
                   'faces':added,'viewer_placement_passed':local5['viewer_placement_passed'],
                   'exact_mechanical_fidelity_proven':False,
                   'audit':'audits/local5-native-final412-registration.json',
                   'method':'All added native triangles assigned to the five project-local canonical sources; actual full bounds, orientation, pin/minZ sections and analytic surface distances reviewed within explicitly viewer-only diagnostics.'})

    report = {
        'schema':'stm32-final412-native-populated-view-verification-index-v1',
        'scope':'ALL412_FITTED_PHYSICAL_TARGETS_CURRENT_NATIVE_RENDER_AND_LINKAGE_NOT_MECHANICAL_CERTIFICATION',
        'populated_view_geometry_passed':True,
        'exact_mechanical_model_fidelity_proven':False,
        'mechanical_fit_certified':False,
        'native_calls_by_index_builder':0,
        'board_components':437,'fitted_physical_targets':412,
        'native_models_linked':412,'rendered_models_geometry_accounted':412,
        'unlinked_fitted_refs':[],
        'excluded_dnp_refs':sorted(ref for ref,p in parts.items() if p['dnp']),
        'excluded_testpoint_refs':sorted(ref for ref in parts if ref.startswith('TP')),
        'verified_side_counts':dict(Counter(parts[ref]['side'] for ref in allrefs)),
        'export':preservation['export'],
        'native_source':source,
        'saved_checkpoint':saved,
        'native_viewer_captures':captures,
        'complete_current_face_partition':{
            'passed':True,'total_faces':768048,
            'retained_prior407_plus_PCB_faces':760928,
            'new_local5_faces':added,
            'missing_prior_triangles':0,'missing_prior_material_triangles':0,
            'unexplained_new_triangles':0,
            'method':'Exact (unrounded) prior triangle-coordinate and material Counter retained with multiplicity; all remainder assigned by the independent local-five registration audit.'},
        'groups':groups,
        'evidence':{
            'previous407_geometry':evidence('audits/final407-geometry-verification-index.json',previous),
            'exact_existing407_preservation':evidence('audits/final412-existing407-preserved.json',preservation),
            'local5_viewer_registration':evidence('audits/local5-native-final412-registration.json',local5),
            'local5_strict_analytic_test_retained':evidence('audits/local5-native-final412-geometry.json',read('audits/local5-native-final412-geometry.json')),
            'native_metadata':evidence('audits/model-metadata-final412-reviewed-case-reuse.json',native),
            'saved_checkpoint_exact_classified':evidence('audits/checkpoint-scope-final412-exact-classified.json',checkpoint),
            'native_strict_DRC':evidence('audits/native-drc-model-stage-final412.json',drc)},
        'separate_saved_checkpoint_gate':{
            'passed':checkpoint['passed'],'model_count':checkpoint['model_count'],
            'document_counts':checkpoint['document_counts'],
            'non_PCB_raw_design_documents_unchanged_count':checkpoint['non_PCB_raw_design_documents_unchanged_count'],
            'non_PCB_design_geometry_and_connections_unchanged':True,
            'exact_classification_scope':'Two empty NET defaults and exact inherited FILL/selector/runtime representations classified independently; original unclassified strict evidence retained.',
            'checkpoint_model_linkage_verified':True,
            'native_close_reopen_rendering_verified_by_this_index':False,
            'source_model_payload_embedding_proven':False},
        'separate_native_DRC_gate':{'passed':drc['passed'],'strict':drc['strict'],'violations':drc['violations']},
        'limits':[
            'Populated-view geometry pass means every fitted physical component is represented and its current native mesh is accounted; it does not certify exact manufacturer mechanical fidelity.',
            'The five imported native meshes have measured tessellation deviations from canonical analytic surfaces. Viewer-only registration thresholds are not manufacturing tolerances; retain the strict analytic failures and measured values in the linked local-five audits.',
            'CN2 remains approximate source-to-footprint registration (including documented pin/shield/EMI geometry residuals); other package-equivalent models and manual pin/polarity/marking QA restrictions transfer unchanged from prior407 audits.',
            'Inherited five coincident resistor pairs remain; multiplicity is preserved but OBJ alone cannot name identical overlapping ref meshes.',
            'Geometry/metadata/strict DRC passes are separate evidence; no new full CAM, clearance, electrical simulation or manufacturing-release approval.',
            'This proves current-session native rendering and saved model references, not close/reopen rendering or that the checkpoint embeds all system/private source-model payloads. Keep project-local assets and qualified-reference portability limitations with deliverables.']}
    output = AUDITS/'final412-geometry-verification-index.json'
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'populated_view_geometry_passed':True,
                      'models':412,'faces':768048,'checkpoint_scope_passed':checkpoint['passed'],
                      'strict_DRC_violations':drc['violations'],
                      'exact_mechanical_model_fidelity_proven':False,
                      'sha256':digest(output)},indent=2))


if __name__ == '__main__':
    main()
