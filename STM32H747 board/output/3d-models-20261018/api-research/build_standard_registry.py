import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
choices = [
    ('0603_FERRITE', '44d717a022884e8a80ead7728bb0329d', 'Generic 1608 two-terminal magnetic-package candidate; not an exact Murata BLM18 model. Inspect mesh for ferrite-bead appearance before retaining.', 'visual_package_candidate_only'),
    ('0805_LED', 'c29cff0e46ad4ec698b672e6ab540619', 'Generic red LED0805 package, not exact WR148SR-W. Cathode mark and pin mapping require mesh inspection.', 'package_class_candidate'),
    ('CRYSTAL_3215_2PIN', '322660504eb3452fba8a1d5fb6a3cd9f', 'Generic SMD3215 two-pin crystal package, not exact NDK NX3215SA.', 'package_class_candidate'),
    ('OSCILLATOR_3225_4PIN', '963ffc640bca471d86f4230614807d79', 'Four-pad ECS TXO3225 family package; board uses ECS3225MV oscillator, not exact TXO part. Height and lid/terminal differences require inspection.', 'same_size_different_series_candidate'),
    ('DFN6_3X3_EP', '2351360292744dbc91885e7d69b823ec', 'DFN6 3x3 P0.95 package counterpart already selected by root; not exact ST1L05CPU33R MPN.', 'package_class_candidate'),
    ('QFN24_4X4_EP', '29c69a3747974ad89ca8d7477a9f3747', 'SQFN24 4x4 P0.50 package counterpart for LAN8742A-CZ-TR; exposed pad and pin1 require raw-mesh check.', 'package_class_candidate'),
    ('QFN32_5X5_EP', 'bd31547231e8451b98b8304566565548', 'QFN32 5x5 P0.50 package counterpart for USB3320C-EZK; exposed pad and pin1 require raw-mesh check.', 'package_class_candidate'),
    ('SMB_DO214AA', '1bbe644b2ecd467e97e82d069ce5a126', 'Generic SMB bidirectional package candidate for SMBJ6.5CA; BI token is model-name evidence only, not independent geometry verification.', 'package_class_candidate'),
    ('SOD323', '63730cd75e074609861c8d6cfe0f6507', 'Generic SOD323 package candidate for BAT54WS-E3-08. Board requires cathode pin1/anode pin2; model band direction remains unverified.', 'package_class_candidate'),
    ('SOD523', 'c9cd6b3de4464affa41bb10afbd29ee3', 'Generic SOD523 package counterpart for ESD8351XV2T1G; do not infer electrical polarity or marking from the generic model.', 'package_class_candidate'),
    ('SOIC16_150MIL', '3622ca242287487a9c2e38fcfcddad34', 'Generic 16-lead 150-mil SOIC, P1.27 LS6.0 candidate for CH340C. Avoid 14-pin/15-pin and exposed-pad search results.', 'package_class_candidate'),
    ('SOIC8_150MIL', '97bd43a9d3eb4c6e8f9c2731ad707392', 'Generic 8-lead narrow SOIC, P1.27 LS6.0 without EP token, shared by STS5PF30L and REF5025AID. Not exact MPN geometry.', 'package_class_candidate'),
    ('SOT223', '72b2852661134777881d1857feec3023', 'Three-lead plus tab, four-physical-pad SOT223 counterpart for LD1117S18TR; do not choose SOT223-5/6 or two-lead variants.', 'package_class_candidate'),
    ('SOT23_3', 'e225ba99af1f4d9384be1c241ef125ab', 'Generic three-lead SOT23 P1.90 package candidate for 9013M; actual lead-side/pin1 orientation requires mesh inspection.', 'package_class_candidate'),
    ('SOT23_6', '4f0b8a3103a94d818231c78af7ee5d6d', 'Generic six-lead SOT23 P0.95 body3.0x1.7 counterpart for USBLC6-2SC6 and USBLC6-4SC6; no five-lead substitution.', 'package_class_candidate'),
    ('TANTALUM_B_3528', '3374b87e848e42cdbf68b58df1ef103d', 'Generic 3528 H1.9 capacitor-package candidate previously metadata-confirmed by special-model research. Inspect tantalum molded body and positive-polarity stripe before retaining; not exact TPSB476M006R0250.', 'visual_package_candidate_only'),
    ('TFBGA265_14X14', 'e1878b6c003f47de9314929abaa1d61c', 'Generic TFBGA265 14x14 P0.80 counterpart; avoids claiming STM32H745/750/757-specific model as STM32H747. Ball omission map and A1 require raw-mesh validation.', 'package_class_candidate'),
    ('TFBGA90_13X8_SOURCE_AXES', 'a776beb50b5a4f47b88257987385b603', 'Generic TFBGA90 13x8, R15 C6 P0.80 TL counterpart for IS42S32160F-6BLI. Source axes differ from common library orientation; raw-mesh A1/axes check required.', 'package_class_candidate'),
]
catalog = {}
evidence_files = list(ROOT.glob('models-*.json')) + [HERE / 'models-standard-extra-search.json']
for path in evidence_files:
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data.get('results', data.get('result', {}).get('results', []))
    for row in rows:
        for model in row.get('models', []):
            value = catalog.setdefault(model['uuid'], {'model': model, 'evidence': []})
            value['evidence'].append({'file': str(path.relative_to(ROOT)).replace('\\', '/'), 'key': row.get('key')})
plan_path = ROOT / 'component-3d-transform-candidates.json'
plan = json.loads(plan_path.read_text(encoding='utf-8'))
inventory = json.loads((ROOT / 'inventory/components-437.json').read_text(encoding='utf-8'))
inventory_by_ref = {item['ref']: item for item in inventory}
metadata_path = HERE / 'models-standard-selected-metadata.json'
metadata = {}
if metadata_path.exists():
    data = json.loads(metadata_path.read_text(encoding='utf-8'))
    metadata = {row['uuid']: row.get('model') for row in data.get('result', {}).get('results', []) if row.get('uuid')}
families = []
targets = []
for family, uuid, reason, status in choices:
    item = catalog[uuid]
    model = item['model']
    title = (metadata.get(uuid) or model)['name']
    refs = []
    for source in plan['targets']:
        if source['model_candidate']['family'] != family:
            continue
        native = inventory_by_ref[source['ref']]
        if native['dnp']:
            continue
        refs.append(source['ref'])
        registration = source['registration']
        targets.append({
            'ref': source['ref'], 'component_id': source['component_id'], 'footprint_uuid': source['footprint_uuid'],
            'part_number': source['part_number'], 'family': family, 'model_uuid': uuid,
            'model_library_uuid': model['libraryUuid'], 'model_title': title,
            'bind_value': uuid + '|' + model['libraryUuid'], 'dnp': False,
            'canonical_registration': {key: registration[key] for key in ['local_rotation_z_deg', 'local_offset_mm', 'basis', 'side', 'component_rotation_deg']},
            'model_mesh_bbox_mm': None, 'model_mesh_default_axis_correction_deg': None,
            'native_size_xyz_mil': None, 'final_transform': None,
        })
    families.append({
        'family': family, 'refs': refs, 'status': status,
        'recommended_uuid': uuid, 'model_title': title, 'library_uuid': model['libraryUuid'],
        'search_metadata': model, 'search_evidence': item['evidence'],
        'readback_metadata': metadata.get(uuid),
        'metadata_get_confirmed': bool(metadata.get(uuid) and metadata[uuid]['uuid'] == uuid),
        'matching_basis': reason, 'exact_mpn_equivalence_claimed': False,
        'model_mesh_bbox_mm': None, 'native_size_xyz_mil': None, 'geometry_registration_verified': False,
    })
report = {
    'schema': 'stm32-remaining-standard-3d-model-registry-v1',
    'status': 'PROPOSED_MODELS_FOR_RAW_NATIVE_MESH_INSPECTION_NOT_FINAL_TRANSFORMS',
    'scope': 'Read-only library search/metadata and local evidence analysis; no board writes, imports, library updates or UI operations.',
    'model_search_method': 'eda.lib_3DModel.search(key, undefined, undefined, 30, 1)',
    'model_get_method': 'eda.lib_3DModel.get(uuid)',
    'model_get_evidence': 'api-research/models-standard-selected-metadata.json',
    'project_guard': {'project': 'STM32H747_MCU_BOARD_v19', 'window_id': 'c020406e-b1fa-42b2-83be-6df87769a738', 'client': 'scripts/easyeda-safe-client.mjs'},
    'candidate_plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
    'family_count': len(families), 'target_count': len(targets),
    'excluded_dnp_refs': [item['ref'] for item in inventory if item['dnp']],
    'sizing_policy': 'Do not derive native full-mesh XYZ sizes from names/body dimensions. UUID+title-only native pilot export, then inspect exact raw mesh XYZ, terminals, pin1 and mounting plane. All size/transform fields here intentionally null.',
    'bga_orientation_proposal': 'Source A1=(-X,-Y), numeric columns+Y and letter rows+X. If native TL mesh has A1=(-X,+Y), numeric+X, letters-Y, rotZ+90 is proposed. This is conditional, not geometry verification.',
    'rejected_candidate': {'uuid': '5c2f7145caaf447aaed38d08d694cdc0', 'name': 'ind-smd_l2.7-w2.4_blm18pg121s11', 'reason': 'Name/body dimensions conflict with 0603/1608 target; BLM18 substring is not sufficient.'},
    'families': families, 'targets': targets,
}
output = ROOT / 'standard-model-candidate-registry.json'
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(HERE / 'standard-selected-model-uuids.json').write_text(json.dumps([uuid for _, uuid, _, _ in choices], indent=2) + '\n', encoding='utf-8')
print(json.dumps({'output': str(output), 'family_count': len(families), 'target_count': len(targets), 'metadata_confirmed': sum(x['metadata_get_confirmed'] for x in families)}, indent=2))
