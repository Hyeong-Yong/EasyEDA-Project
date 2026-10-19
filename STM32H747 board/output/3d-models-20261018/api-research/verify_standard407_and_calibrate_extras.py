from collections import Counter
import json
import math
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
current = json.loads((HERE/'standard407-isolated-geometry.json').read_text())
now = current['features']
before = json.loads((HERE/'standard405-material-features.json').read_text())
calibration = {e['ref']:e for e in json.loads((ROOT/'standard27-geometry-calibration.json').read_text())['evidence']}
plan = json.loads((ROOT/'standard27-calibrated-apply-plan.json').read_text())
inventory = {e['ref']:e for e in json.loads((ROOT/'inventory/components-437.json').read_text())}
footprints = json.loads((ROOT/'inventory/footprints-288.json').read_text())
canonical = {e['ref']:e for e in json.loads((ROOT/'component-3d-transform-candidates.json').read_text())['targets']}
rows = []
errors = []

def groups(values,tolerance=.04):
    result = []
    for value in sorted(values):
        if not result or value-result[-1][-1]>tolerance:
            result.append([value])
        else:
            result[-1].append(value)
    return [mean(g) for g in result]

def linear_pitch(values):
    vals = groups(values)
    xs = list(range(len(vals)))
    mx,my = mean(xs),mean(vals)
    slope = sum((x-mx)*(y-my) for x,y in zip(xs,vals))/sum((x-mx)**2 for x in xs)
    residual = max(abs(y-(my+slope*(x-mx))) for x,y in zip(xs,vals))
    return slope,vals,residual

def color_signature(color):
    return tuple((k,tuple(color[k])) for k in sorted(color))

def center(piece):
    box = piece['bbox_local_mm']
    return [(box[k]+box[k+3])/2 for k in range(3)]

for entry in plan['entries']:
    ref = entry['ref']
    f, previous, ev = now[ref], before[ref], calibration[ref]
    tr = entry['transform_values_mil_degrees']
    theta = math.radians(tr[3])
    offset = [v*.0254 for v in tr[6:]]
    native = entry['full_mesh_xyz_mm']
    expected_size = [abs(math.cos(theta))*native[0]+abs(math.sin(theta))*native[1], abs(math.sin(theta))*native[0]+abs(math.cos(theta))*native[1], native[2]]
    size_error = [f['size_xyz_component_local_mm'][i]-expected_size[i] for i in range(3)]
    xy_error = math.dist(f['mesh_center_component_local_mm'][:2],offset[:2])
    minz_error = f['bbox_component_local_mm'][2]-offset[2]
    full_matches = []
    material_pairs = {}
    for oldmat,oldmf in previous['materials'].items():
        samecolor = [(newmat,mf) for newmat,mf in f['materials'].items() if color_signature(mf['color'])==color_signature(oldmf['color'])]
        if not samecolor:
            errors.append({'ref':ref,'missing_material_color':oldmat})
            continue
        newmat,newmf = min(samecolor,key=lambda t:abs(len(t[1]['pieces'])-len(oldmf['pieces'])))
        used = set()
        mapping = []
        for oldindex,oldpiece in enumerate(oldmf['pieces']):
            x,y,z = [v/ev['auto_fit_scale'] for v in oldpiece['center_from_model_bbox_mm']]
            expected = [x*math.cos(theta)-y*math.sin(theta)+offset[0],x*math.sin(theta)+y*math.cos(theta)+offset[1],z+native[2]/2+offset[2]]
            candidates = [(math.dist(center(piece),expected),index,piece) for index,piece in enumerate(newmf['pieces']) if index not in used and piece['faces']==oldpiece['faces'] and piece['vertices']==oldpiece['vertices']]
            if not candidates:
                errors.append({'ref':ref,'material':oldmat,'unmatched_old_piece':oldindex})
                continue
            dist,index,piece = min(candidates,key=lambda t:t[0])
            used.add(index)
            actual = center(piece)
            nx,ny = actual[0]-offset[0],actual[1]-offset[1]
            recovered = [nx*math.cos(theta)+ny*math.sin(theta),-nx*math.sin(theta)+ny*math.cos(theta),actual[2]-offset[2]]
            match = {'old_material':oldmat,'new_material':newmat,'old_piece':oldindex,'new_piece':index,'faces':oldpiece['faces'],
                     'center_error_mm':dist,'expected_center_component_local_mm':expected,'actual_center_component_local_mm':actual,
                     'recovered_native_center_mm':recovered}
            full_matches.append(match)
            mapping.append(match)
        material_pairs[oldmat] = mapping
    pitch_check = None
    bga_map_check = None
    family = entry['family']
    selectors = {'DFN6_3X3_EP':('mtl3',1,.95), 'QFN24_4X4_EP':('mtl24',1,.5), 'QFN32_5X5_EP':('mtl24',1,.5),
                 'TFBGA265_14X14':('mtl10',1,.8),'TFBGA90_13X8_SOURCE_AXES':('mtl10',1,.8),
                 'SOIC8_150MIL':('mtl29',0,1.27),'SOIC16_150MIL':('mtl32',1,1.27),
                 'SOT223':('mtl24',1,2.3),'SOT23_3':('mtl10',0,1.9),'SOT23_6':('mtl24',1,.95)}
    if family in selectors:
        mat,axis,nominal = selectors[family]
        matches = material_pairs.get(mat,[])
        selected = []
        for match in matches:
            oldpiece = previous['materials'][mat]['pieces'][match['old_piece']]
            c = oldpiece['center_from_model_bbox_mm']
            if family=='DFN6_3X3_EP' and oldpiece['faces']!=15:
                continue
            if family.startswith('TFBGA') and not (oldpiece['bbox_local_mm'][5]<previous['default_size_xyz_mm'][2]*.6 and max(oldpiece['size_xyz_mm'][:2])<.7):
                continue
            if family=='SOT223' and c[0]>=0:
                continue
            if family=='SOT23_3' and c[1]>=0:
                continue
            selected.append(match['recovered_native_center_mm'])
        if family in ['QFN24_4X4_EP','QFN32_5X5_EP']:
            maxx = max(p[0] for p in selected)
            vals = groups([p[axis] for p in selected if p[0]>maxx-.04])
            actual_pitch = median(b-a for a,b in zip(vals,vals[1:]))
            residual = max(abs(b-a-actual_pitch) for a,b in zip(vals,vals[1:]))
        else:
            actual_pitch,vals,residual = linear_pitch([p[axis] for p in selected])
        pitch_check = {'nominal_pitch_mm':nominal,'measured_applied_pitch_mm':actual_pitch,'error_mm':actual_pitch-nominal,
                       'row_levels_mm':vals,'row_fit_residual_mm':residual,'selected_terminal_or_ball_count':len(selected)}
        if family.startswith('TFBGA'):
            balls = []
            for match in material_pairs[mat]:
                oldpiece = previous['materials'][mat]['pieces'][match['old_piece']]
                if oldpiece['bbox_local_mm'][5]<previous['default_size_xyz_mm'][2]*.6 and max(oldpiece['size_xyz_mm'][:2])<.7:
                    balls.append(match['actual_center_component_local_mm'][:2])
            sourcepins = canonical[ref]['source_local_pin_centers_mm']
            distances = {pin:min(math.dist(pos,p) for p in balls) for pin,pos in sourcepins.items()}
            bga_map_check = {'actual_ball_count':len(balls),'source_pin_count':len(sourcepins),'maximum_nearest_ball_error_mm':max(distances.values()),
                             'mean_nearest_ball_error_mm':mean(distances.values()),'A1_error_mm':distances['A1'],
                             'note':'Actual mesh sphere bbox-center tessellation causes small individual ball-center variation; this is a visual registration comparison, not BGA manufacturing tolerancing.'}
    max_piece_error = max(m['center_error_mm'] for m in full_matches)
    passed = max(abs(v) for v in size_error)<.005 and xy_error<.005 and abs(minz_error)<.005 and max_piece_error<.005 and f['face_count']==previous['face_count']
    if pitch_check:
        passed = passed and abs(pitch_check['error_mm'])<.005
    if not passed:
        errors.append({'ref':ref,'size_error_mm':size_error,'center_error_mm':xy_error,'minz_error_mm':minz_error,'max_piece_error_mm':max_piece_error})
    rows.append({'ref':ref,'family':family,'passed':passed,'face_count':f['face_count'],'expected_face_count':previous['face_count'],
                 'actual_component_local_xyz_mm':f['size_xyz_component_local_mm'],'expected_component_local_xyz_mm':expected_size,'size_error_mm':size_error,
                 'actual_center_component_local_mm':f['mesh_center_component_local_mm'],'expected_offset_mm':offset,'center_error_xy_mm':xy_error,
                 'min_z_error_mm':minz_error,'all_material_piece_centers_matched':len(full_matches),'max_material_piece_center_error_mm':max_piece_error,
                 'lead_or_ball_pitch':pitch_check,'actual_bga_source_ball_map':bga_map_check,'manual_pin_or_polarity_QA_remains':entry['manual_QA_required'],'material_piece_correspondences':full_matches})

verification = {'schema':'stm32-standard27-applied-geometry-verification-v1','passed':not errors,'native_calls':0,
                'source_export':current['source_export'],'source_export_sha256':current['source_export_sha256'],
                'target_count':len(rows),'verified_count':sum(r['passed'] for r in rows),'tolerance_mm':.005,
                'maximum_size_error_mm':max(abs(v) for r in rows for v in r['size_error_mm']),
                'maximum_center_error_xy_mm':max(r['center_error_xy_mm'] for r in rows),
                'maximum_material_piece_center_error_mm':max(r['max_material_piece_center_error_mm'] for r in rows),
                'rows':rows,'errors':errors,'limits':['Triangle geometry/renderer transform verification, not mechanical or manufacturer-equivalence approval.',
                 'Previously flagged generic model pin1/polarity interpretation remains manual QA; this audit verifies that all observed material pieces were transformed as planned.',
                 'Changed SMA geometry is excluded and owned by the separate inventory audit.']}
(ROOT/'audits/standard27-applied407-verified.json').write_text(json.dumps(verification,indent=2)+'\n')

extra_evidence = []
extra_entries = []
extra_config = {
    'TR1':{'uuid':'d691814482f84b87ab195e8d38090ed5','title':'XFMR-SMD_H1102N','material':'mtl25','faces':26,'axis':0,'pitch':1.27,'rot':270,
           'basis':'Sixteen lead pieces, eight in each native Y row, known1.27mm pitch along X. Top circular pin1 marking is native(-X,-Y); rot270 maps it to source left row+Y. H1102N is a package-equivalent visual surrogate, not exact KMS-1102NL.'},
    'SW1':{'uuid':'73b3a84ae74e462f8f90e36cc5fd3e32','title':'SW-SMD_4P-L6.0-W6.0-P4.50-LS8.6_TS014-TBW1FH7.5','material':'mtl16','faces':34,'axis':1,'pitch':4.5,'rot':0,
           'basis':'Four physical metal leads, native left/right X ends and Y-pair span4.5mm, matching source pad-row orientation and Y spacing. Source pad centers are X+/-4.25,Y+/-2.25; metal-piece centers need not coincide with enlarged copper-pad centers. Symmetric nonpolar switch body; internal contact common-pair semantics not encoded by the mesh. Different TS014 switch family is a visual surrogate, not exact GT-TC089B-H075-L1.'},
}
for ref,cfg in extra_config.items():
    f = now[ref]
    leads = [p for p in f['materials'][cfg['material']]['pieces'] if p['faces']==cfg['faces']]
    coordinates = [p['center_from_model_bbox_mm'][cfg['axis']] for p in leads]
    measured,levels,residual = linear_pitch(coordinates)
    scale = measured/cfg['pitch']
    size = [v/scale for v in f['size_xyz_component_local_mm']]
    angle = math.radians(cfg['rot'])
    native_terminal_midpoint = [mean(p['center_from_model_bbox_mm'][i] for p in leads)/scale for i in range(2)]
    nx,ny = native_terminal_midpoint
    rotated_midpoint = [nx*math.cos(angle)-ny*math.sin(angle),nx*math.sin(angle)+ny*math.cos(angle)]
    offset = [0 if abs(v)<1e-10 else v for v in [-rotated_midpoint[0],-rotated_midpoint[1],0]]
    tr = [v/.0254 for v in size]+[cfg['rot'],0,0]+[v/.0254 for v in offset]
    text = ','.join(format(v,'.12g') for v in tr)
    source_pads = footprints[inventory[ref]['footprint_uuid']]['pads_native_mil']
    source_rects = []
    for p in source_pads:
        cx,cy = p['centerX']*.0254,p['centerY']*.0254
        w,h = p['defaultPad']['width']*.0254,p['defaultPad']['height']*.0254
        source_rects.append({'num':p['num'],'bbox_mm':[cx-w/2,cy-h/2,cx+w/2,cy+h/2],'center_mm':[cx,cy]})
    projected_checks = []
    model_center = f['mesh_center_component_local_mm']
    for p in leads:
        b = p['bbox_local_mm']
        corners = [[(x-model_center[0])/scale,(y-model_center[1])/scale] for x,y in [(b[0],b[1]),(b[0],b[4]),(b[3],b[1]),(b[3],b[4])]]
        rotated = [[x*math.cos(angle)-y*math.sin(angle)+offset[0],x*math.sin(angle)+y*math.cos(angle)+offset[1]] for x,y in corners]
        rb = [min(p[0] for p in rotated),min(p[1] for p in rotated),max(p[0] for p in rotated),max(p[1] for p in rotated)]
        rc = [(rb[0]+rb[2])/2,(rb[1]+rb[3])/2]
        pad = min(source_rects,key=lambda p:math.dist(rc,p['center_mm']))
        pb = pad['bbox_mm']
        overlap = [min(rb[2],pb[2])-max(rb[0],pb[0]),min(rb[3],pb[3])-max(rb[1],pb[1])]
        projected_checks.append({'source_pad_num':pad['num'],'projected_metal_piece_bbox_mm':rb,'source_pad_bbox_mm':pb,
                                  'bbox_overlap_xy_mm':overlap,'positive_projected_overlap':all(v>0 for v in overlap)})
    entry = {'ref':ref,'id':inventory[ref]['component_id'],'model':cfg['uuid']+'|0819f05c4eef4c71ace90d822a990e87','title':cfg['title'],
             'transform':text,'transformMIL':text,'full_mesh_xyz_mm':size,'confidence':'pitch_calibrated_package_equivalent_visual_only',
             'manufacturer_exact':False,'mechanical_clearance_approved':False}
    extra_entries.append(entry)
    extra_evidence.append({'ref':ref,'source_default_full_mesh_xyz_mm':f['size_xyz_component_local_mm'],'source_auto_center_component_local_mm':f['mesh_center_component_local_mm'],
                           'terminal_piece_count':len(leads),'terminal_material':cfg['material'],'known_pitch_mm':cfg['pitch'],'measured_default_pitch_mm':measured,
                           'default_row_levels_mm':levels,'max_row_fit_residual_mm':residual,'auto_fit_scale':scale,'intrinsic_full_mesh_xyz_mm':size,
                           'final_relative_rotZ_deg':cfg['rot'],'final_relative_offset_mm':offset,
                           'native_terminal_midpoint_from_fullbbox_mm':native_terminal_midpoint,
                           'offset_basis':'Align measured mean of physical terminal centers to the source physical-pad centroid(0,0); remove tiny fullbbox asymmetry from lettering/mesh.',
                           'mounting_plane':'Full mesh minZ=0 is the SMD contact plane.',
                           'orientation_and_equivalence_basis':cfg['basis'],'source_feature_evidence':'api-research/standard407-isolated-geometry.json',
                           'projected_terminal_bbox_pad_checks':projected_checks,
                           'projected_pad_check_limit':'Projected entire metal-piece bounding boxes only; this does not establish full solder-contact-area overlap or manufacturing clearance.',
                           'manual_QA':'Exact MPN enclosure, markings, height and manufacturer mechanical fit are unverified; only package-equivalent visual preview is intended.'})
(ROOT/'switch-xfmr-calibrated-apply-plan.json').write_text(json.dumps({'status':'VISUAL_PACKAGE_APPLY_CANDIDATE_NOT_APPLIED','expectedCount':437,'entries':extra_entries},indent=2)+'\n')
(ROOT/'switch-xfmr-geometry-calibration.json').write_text(json.dumps({'schema':'stm32-switch-xfmr-native-mesh-calibration-v1','native_calls':0,
    'source_export':current['source_export'],'source_export_sha256':current['source_export_sha256'],'evidence':extra_evidence},indent=2)+'\n')
print(json.dumps({'standard27_passed':verification['passed'],'verified_count':verification['verified_count'],
                   'max_size_error_mm':verification['maximum_size_error_mm'],'max_center_error_mm':verification['maximum_center_error_xy_mm'],
                   'max_piece_center_error_mm':verification['maximum_material_piece_center_error_mm'],'errors':errors,
                   'extra_entries':extra_entries,'extra_evidence':extra_evidence},indent=2))
