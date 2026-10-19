"""Generate visual-package calibration proposals; never calls native CAD."""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
features = json.loads((HERE / 'standard405-material-features.json').read_text())
registry = json.loads((ROOT / 'standard-model-candidate-registry.json').read_text())
plan = {p['ref']:p for p in json.loads((ROOT / 'component-3d-transform-candidates.json').read_text())['targets']}

def groups(values, tolerance=.04):
    result = []
    for value in sorted(values):
        if not result or value - result[-1][-1] > tolerance:
            result.append([value])
        else:
            result[-1].append(value)
    return [mean(g) for g in result]

def linear_pitch(values):
    vals = groups(values)
    xs = list(range(len(vals)))
    mx, my = mean(xs), mean(vals)
    slope = sum((x-mx)*(y-my) for x,y in zip(xs,vals))/sum((x-mx)**2 for x in xs)
    residual = max(abs(y-(my+slope*(x-mx))) for x,y in zip(xs,vals))
    return slope, vals, residual

def pcs(ref, material):
    return features[ref]['materials'][material]['pieces']

def biggest(ref, material):
    return max(pcs(ref, material), key=lambda p:p['faces'])

def body_anchor(ref, material, axis, nominal, reason):
    body = next(p for p in pcs(ref,material) if p['faces']==188) if features[ref]['family']=='0805_LED' else biggest(ref, material)
    measured = body['size_xyz_mm'][axis]
    return measured/nominal, {'method':'visual_package_body_material_extent', 'material':material, 'body_piece_faces':body['faces'], 'axis':axis,
                             'measured_default_extent_mm':measured, 'nominal_package_extent_mm':nominal, 'basis':reason,
                             'manufacturer_exact':False, 'clearance_certification':False}

corrections = {'0603_FERRITE':0, '0805_LED':0, 'CRYSTAL_3215_2PIN':0, 'OSCILLATOR_3225_4PIN':0,
               'DFN6_3X3_EP':0, 'QFN24_4X4_EP':0, 'QFN32_5X5_EP':0, 'SMB_DO214AA':0,
               'SOD323':0, 'SOD523':0, 'SOIC16_150MIL':0, 'SOIC8_150MIL':270, 'SOT223':0,
               'SOT23_3':270, 'SOT23_6':0, 'TANTALUM_B_3528':0, 'TFBGA265_14X14':90, 'TFBGA90_13X8_SOURCE_AXES':90}
orientation = {
 '0603_FERRITE':'Measured terminal pair lies along native X. Nonpolar two-terminal package.',
 '0805_LED':'Native X is terminal axis; negative-X end has asymmetric/chamfer marker geometry. Cathode-to-pin1 interpretation remains manual QA.',
 'CRYSTAL_3215_2PIN':'Measured terminal pair lies along native X. Passive two-pin crystal does not require polarity.',
 'OSCILLATOR_3225_4PIN':'Native four corner terminals and top pin1 dot are at (-X,-Y); this matches the source-plan oscillator canonical marker.',
 'DFN6_3X3_EP':'Six terminal centers form left/right X rows, three Y pitches each. Five-vertex EP polygon is chamfered at (-X,+Y), corroborating the source canonical pin1 corner. No isolated top dot; exact-part interpretation remains conservative manual QA.',
 'QFN24_4X4_EP':'Native top circular marking at (-X,+Y), four rows of six terminals. Matches source canonical pin1 left-row +Y.',
 'QFN32_5X5_EP':'Native top circular marking at (-X,+Y), four rows of eight terminals. Matches source canonical pin1 left-row +Y.',
 'SMB_DO214AA':'Native terminal axis X; bidirectional package candidate, so no electrical polarity orientation is claimed.',
 'SOD323':'Native silver top band at negative X; source explicitly specifies K1 at negative X. Band-to-K1 direction matches after source registration.',
 'SOD523':'Native top band at positive X; geometry axis matches canonical terminal axis, but actual ESD device band/polarity is unverified. Manual QA required.',
 'SOIC16_150MIL':'Native lead rows are X-left/right and TL circular pin1 mark is at (-X,+Y); no extra canonical correction.',
 'SOIC8_150MIL':'Native lead rows are Y-bottom/top, four pins along X; circular BL marker is (-X,-Y). RotZ270 maps it to canonical left-row +Y.',
 'SOT223':'Native three small leads on left X row, tab on right, and top pin1 mark at (-X,+Y); matches canonical.',
 'SOT23_3':'Native two small leads are on negative Y and single lead on positive Y. RotZ270 maps the pair to left row. Individual pin1/2 identity is not encoded unambiguously; manual QA.',
 'SOT23_6':'Native six terminal centers form X-left/right rows with top pin1 marking at (-X,+Y); matches canonical.',
 'TANTALUM_B_3528':'Measured molded salmon body, two end terminals, and contrasting positive-end stripe at native negative X; source capacitor pin1 is positive and canonical at -X.',
 'TFBGA265_14X14':'Native top circular A1 marker at (-X,+Y). RotZ90 maps it to source A1(-X,-Y), numbers+Y, letters+X. Ball-map comparison recorded.',
 'TFBGA90_13X8_SOURCE_AXES':'Native full body X8/Y13 and top A1 circular marker(-X,+Y). RotZ90 yields source body X13/Y8 and A1(-X,-Y). Ball-map comparison recorded.',
}
manual_families = {'0805_LED','DFN6_3X3_EP','SOD523','SOT23_3'}
evidence = []
entries = []
for target in registry['targets']:
    ref, family = target['ref'], target['family']
    f = features[ref]
    metal_centers = []
    if family == 'DFN6_3X3_EP':
        terminals = [p for p in pcs(ref,'mtl3') if p['faces']==15]
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][1] for p in terminals])
        nominal = .95
    elif family in ['QFN24_4X4_EP','QFN32_5X5_EP']:
        terminals = pcs(ref,'mtl24')
        xmax = max(p['center_from_model_bbox_mm'][0] for p in terminals)
        row = [p for p in terminals if p['center_from_model_bbox_mm'][0] > xmax-.04]
        vals = groups([p['center_from_model_bbox_mm'][1] for p in row])
        measured = median(b-a for a,b in zip(vals,vals[1:]))
        residual = max(abs((b-a)-measured) for a,b in zip(vals,vals[1:]))
        nominal = .5
    elif family in ['TFBGA265_14X14','TFBGA90_13X8_SOURCE_AXES']:
        terminals = [p for p in pcs(ref,'mtl10') if p['bbox_local_mm'][5] < f['default_size_xyz_mm'][2]*.6 and max(p['size_xyz_mm'][:2]) < .7]
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][1] for p in terminals])
        nominal = .8
        metal_centers = [p['center_from_model_bbox_mm'][:2] for p in terminals]
    elif family == 'SOIC8_150MIL':
        terminals = pcs(ref,'mtl29')
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][0] for p in terminals])
        nominal = 1.27
    elif family == 'SOIC16_150MIL':
        terminals = pcs(ref,'mtl32')
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][1] for p in terminals])
        nominal = 1.27
    elif family == 'SOT223':
        terminals = [p for p in pcs(ref,'mtl24') if p['center_from_model_bbox_mm'][0] < 0]
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][1] for p in terminals])
        nominal = 2.3
    elif family == 'SOT23_3':
        terminals = [p for p in pcs(ref,'mtl10') if p['center_from_model_bbox_mm'][1] < 0]
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][0] for p in terminals])
        nominal = 1.9
    elif family == 'SOT23_6':
        terminals = pcs(ref,'mtl24')
        measured, vals, residual = linear_pitch([p['center_from_model_bbox_mm'][1] for p in terminals])
        nominal = .95
    else:
        body_cases = {'0603_FERRITE':('mtl13',0,1.6,'Nominal1608 magnetic body; terminal full envelope is measured separately.'),
                      '0805_LED':('mtl10',0,2.0,'Nominal0805/2012 LED body long axis; inferred short axis is reported, not forced.'),
                      'CRYSTAL_3215_2PIN':('mtl37',0,3.2,'Nominal3215 crystal body long axis.'),
                      'OSCILLATOR_3225_4PIN':('mtl34',0,3.2,'Nominal3225 oscillator body long axis; alternate TXO series model remains generic.'),
                      'SMB_DO214AA':('mtl15',0,4.3,'NominalSMB molded body long axis; full lead envelope is not forced to body4.3.'),
                      'SOD323':('mtl39',0,1.7,'NominalVishay SOD323 molded body long axis; derived full lead size is retained.'),
                      'SOD523':('mtl8',0,1.2,'NominalSOD523 molded body long axis; derived full lead size is retained.'),
                      'TANTALUM_B_3528':('mtl4',0,3.5,'NominalcaseB3528 molded body long axis; metal extends beyond the body.')}
        mat, axis, value, reason = body_cases[family]
        scale, anchor = body_anchor(ref,mat,axis,value,reason)
    if family not in ['0603_FERRITE','0805_LED','CRYSTAL_3215_2PIN','OSCILLATOR_3225_4PIN','SMB_DO214AA','SOD323','SOD523','TANTALUM_B_3528']:
        scale = measured/nominal
        anchor = {'method':'measured_terminal_or_ball_pitch', 'nominal_pitch_mm':nominal, 'default_measured_pitch_mm':measured,
                  'default_row_coordinate_levels_mm':vals, 'max_row_fit_or_pitch_residual_mm':residual, 'terminal_piece_count':len(terminals)}
    assert scale > 0
    intrinsic = [v/scale for v in f['default_size_xyz_mm']]
    registration = target['canonical_registration']
    rotation = (registration['local_rotation_z_deg']+corrections[family])%360
    offset = registration['local_offset_mm']
    transform_values = [v/.0254 for v in intrinsic] + [rotation,0,0] + [v/.0254 for v in offset]
    transform = ','.join(format(v,'.12g') for v in transform_values)
    bga_map = None
    if metal_centers:
        angle = math.radians(rotation)
        rendered = [[(x*math.cos(angle)-y*math.sin(angle))/scale+offset[0], (x*math.sin(angle)+y*math.cos(angle))/scale+offset[1]] for x,y in metal_centers]
        source = plan[ref]['source_local_pin_centers_mm']
        errors = {pin:min(math.dist(pos,p) for p in rendered) for pin,pos in source.items()}
        bga_map = {'ball_count':len(rendered), 'source_pin_count':len(source), 'nearest_ball_max_error_mm':max(errors.values()),
                   'nearest_ball_mean_error_mm':mean(errors.values()), 'A1_error_mm':errors.get('A1'), 'all_source_pin_errors_mm':errors}
    evidence.append({'ref':ref,'family':family,'model_uuid':target['model_uuid'],'source_auto_default_full_xyz_mm':f['default_size_xyz_mm'],
                     'source_auto_default_bbox_component_local_mm':f['bbox_component_local_mm'], 'source_auto_center_offset_mm':f['auto_center_component_local_mm'],
                     'auto_fit_scale':scale,'calibration_anchor':anchor,'intrinsic_full_mesh_xyz_mm':intrinsic,
                     'model_native_to_source_canonical_rotZ_deg':corrections[family], 'final_relative_rotZ_deg':rotation,
                     'final_relative_offset_mm':offset, 'mounting_plane':'Mesh minimum Z=0; top-side SMD, native explicit transform reanchors minZ to board surface.',
                     'orientation_evidence':orientation[family], 'pin1_or_polarity_manual_QA_required':family in manual_families,
                     'extra_orientation_evidence':'audits/u3-exposed-pad-chamfer.json' if ref=='U3' else None,
                     'bga_source_ball_map_check':bga_map,'confidence':'pitch_calibrated_visual_package' if anchor['method']=='measured_terminal_or_ball_pitch' else 'nominal_body_calibrated_visual_package_uncertified',
                     'manufacturer_exact':False,'manufacturing_clearance_approved':False})
    entries.append({'ref':ref,'id':target['component_id'],'family':family,'model':target['bind_value'],'title':target['model_title'],
                    'transform':transform,'transformMIL':transform,'transform_values_mil_degrees':transform_values,
                    'full_mesh_xyz_mm':intrinsic,'confidence':evidence[-1]['confidence'],'manual_QA_required':family in manual_families})

report = {'schema':'stm32-standard27-native-mesh-calibration-v1',
          'status':'VISUAL_PACKAGE_APPLY_CANDIDATE_NOT_APPLIED', 'native_calls':0, 'target_count':len(entries),
          'source_export':'STM32H747_standards_default_405_STM32H747_standards_default_405',
          'source_export_sha256':hashlib.sha256((ROOT/'STM32H747_standards_default_405_STM32H747_standards_default_405').read_bytes()).hexdigest(),
          'geometry_differential_evidence':'api-research/standard405-differential-pieces.json',
          'material_feature_evidence':'api-research/standard405-material-features.json', 'evidence':evidence,
          'limits':['Generic package-equivalent visualization only; not exact manufacturer geometry or mechanical/clearance certification.',
                    'Explicit XYZ are measured full mesh envelopes calibrated by known electrical pitch, or root-authorized nominal body-material axes for visual-only packages. Leaded full envelopes are never replaced by body dimensions.',
                    'Pin1/polarity unresolved cases are explicitly flagged for manual QA, not claimed verified.',
                    'An explicit-transform native re-export and per-reference spatial/pad-side audit must confirm the resulting renderer scaling, center, board-side and pin registration before final acceptance.']}
(ROOT/'standard27-geometry-calibration.json').write_text(json.dumps(report,indent=2)+'\n')
(ROOT/'standard27-calibrated-apply-plan.json').write_text(json.dumps({'status':report['status'],'expectedCount':437,'entries':entries,'limits':report['limits']},indent=2)+'\n')
print(json.dumps({'entries':len(entries),'audit':str(ROOT/'standard27-geometry-calibration.json'), 'plan':str(ROOT/'standard27-calibrated-apply-plan.json'),
                  'families':[{k:e[k] for k in ['ref','family','intrinsic_full_mesh_xyz_mm','final_relative_rotZ_deg','pin1_or_polarity_manual_QA_required']} for e in evidence]},indent=2))
