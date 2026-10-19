"""Verify final407 preserves already-verified standards and calibrates TR/SW."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from inspect_standard_meshes import load, bounds

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OLD = ROOT/'STM32H747_std27_j12_switch_xfmr_407_STM32H747_std27_j12_switch_xfmr_407'
NEW = ROOT/'STM32H747_calibrated407_STM32H747_calibrated407'
old_vertices,old_faces,old_materials = load(OLD)
vertices,faces,materials = load(NEW)

def color_signature(value):
    return tuple((k,tuple(value[k])) for k in sorted(value))

topology_equal = len(old_vertices)==len(vertices) and len(old_faces)==len(faces)
if topology_equal:
    topology_equal = all(a[2]==b[2] and color_signature(old_materials[a[0]])==color_signature(materials[b[0]]) for a,b in zip(old_faces,faces))
assert topology_equal, 'Native mesh topology or vertex ordering changed; range membership cannot be reused'
source407 = json.loads((HERE/'standard407-isolated-geometry.json').read_text())
source27 = json.loads((ROOT/'audits/standard27-applied407-verified.json').read_text())
standard_plan = json.loads((ROOT/'standard27-calibrated-apply-plan.json').read_text())
extra_plan = json.loads((ROOT/'switch-xfmr-calibrated-apply-plan.json').read_text())
inv = {p['ref']:p for p in json.loads((ROOT/'inventory/components-437.json').read_text())}
byref = defaultdict(list)
for piece in source407['pieces']:
    byref[piece['ref']].append(piece)
ranges = {ref:(min(p['vertex_min'] for p in ps),max(p['vertex_max'] for p in ps)) for ref,ps in byref.items()}
motion_tolerance = 1e-5
changed_ids = [i for i in range(1,len(vertices)) if math.dist(vertices[i],old_vertices[i])>motion_tolerance]
changed_runs = []
for i in changed_ids:
    if not changed_runs or i-changed_runs[-1][-1]>8:
        changed_runs.append([i])
    else:
        changed_runs[-1].append(i)
changed_summaries = []
for ids in changed_runs:
    box = bounds([old_vertices[i] for i in ids])
    c = [(box[k]+box[k+3])/2 for k in range(3)]
    d,ref = min((math.dist(c[:2],[inv[r]['x_mm'],inv[r]['y_mm']]),r) for r in ['J1','J18']+[f'J{i}' for i in range(2,18)]+['TR1','SW1'])
    changed_summaries.append({'min_vertex':ids[0],'max_vertex':ids[-1],'changed_vertex_count':len(ids),'old_bbox_mm':box,'nearest_expected_change_ref':ref,'distance_mm':d})
standard_rows = []
for entry in standard_plan['entries']:
    ref = entry['ref']
    lo,hi = ranges[ref]
    fs = [f for f in faces if all(lo<=i<=hi for i in f[2])]
    used = {i for _,_,ids in fs for i in ids}
    error = max(math.dist(vertices[i],old_vertices[i]) for i in used)
    expected_count = source407['features'][ref]['face_count']
    passed = len(fs)==expected_count and error<motion_tolerance
    assert passed, (ref,len(fs),expected_count,error)
    prior = next(p for p in source27['rows'] if p['ref']==ref)
    standard_rows.append({'ref':ref,'face_count':len(fs),'max_vertex_motion_from_verified407_mm':error,'passed':passed,
                          'prior_geometry_verification':'audits/standard27-applied407-verified.json','prior_pitch':prior['lead_or_ball_pitch'],
                          'prior_bga_registration':prior['actual_bga_source_ball_map'],'manual_pin_or_polarity_QA_remains':prior['manual_pin_or_polarity_QA_remains']})
extra_rows = []
extra_anchors = {'TR1':{'material':'mtl25','piece_faces':26,'axis':0,'pitch':1.27},'SW1':{'material':'mtl16','piece_faces':34,'axis':1,'pitch':4.5}}
for entry in extra_plan['entries']:
    ref = entry['ref']
    lo,hi = ranges[ref]
    current_fs = [f for f in faces if all(lo<=i<=hi for i in f[2])]
    old_fs = [f for f in old_faces if all(lo<=i<=hi for i in f[2])]
    ids = {i for _,_,ff in current_fs for i in ff}
    box = bounds([vertices[i] for i in ids])
    source = inv[ref]
    local_box = [box[0]-source['x_mm'],box[1]-source['y_mm'],box[2],box[3]-source['x_mm'],box[4]-source['y_mm'],box[5]]
    actual_size = [box[k+3]-box[k] for k in range(3)]
    actual_center = [(local_box[k]+local_box[k+3])/2 for k in range(3)]
    tr = list(map(float,entry['transform'].split(',')))
    theta = math.radians(tr[3])
    expected_native = entry['full_mesh_xyz_mm']
    expected_size = [abs(math.cos(theta))*expected_native[0]+abs(math.sin(theta))*expected_native[1],abs(math.sin(theta))*expected_native[0]+abs(math.cos(theta))*expected_native[1],expected_native[2]]
    offset = [v*.0254 for v in tr[6:]]
    size_error = [actual_size[k]-expected_size[k] for k in range(3)]
    center_error = math.dist(actual_center[:2],offset[:2])
    old_mf = source407['features'][ref]['materials']
    cfg = extra_anchors[ref]
    signature = color_signature(old_mf[cfg['material']]['color'])
    metal_fs = [f for f in current_fs if color_signature(materials[f[0]])==signature]
    par = {}
    def find(i):
        par.setdefault(i,i)
        if par[i]!=i:
            par[i]=find(par[i])
        return par[i]
    for _,_,ff in metal_fs:
        for i in ff:
            par[find(i)] = find(ff[0])
    mfs = defaultdict(list)
    for f in metal_fs:
        mfs[find(f[2][0])].append(f)
    leads = []
    for fs in mfs.values():
        if len(fs)!=cfg['piece_faces']:
            continue
        vi = {i for _,_,ff in fs for i in ff}
        b = bounds([vertices[i] for i in vi])
        c = [(b[k]+b[k+3])/2 for k in range(3)]
        x,y = c[0]-source['x_mm']-offset[0],c[1]-source['y_mm']-offset[1]
        recovered = [x*math.cos(theta)+y*math.sin(theta),-x*math.sin(theta)+y*math.cos(theta)]
        leads.append({'bbox_world_mm':b,'center_component_local_mm':[c[0]-source['x_mm'],c[1]-source['y_mm'],c[2]],'recovered_native_xy_mm':recovered})
    vals = []
    for value in sorted(p['recovered_native_xy_mm'][cfg['axis']] for p in leads):
        if not vals or value-vals[-1][-1]>.04:
            vals.append([value])
        else:
            vals[-1].append(value)
    levels = [mean(v) for v in vals]
    xs = list(range(len(levels)))
    mx,my = mean(xs),mean(levels)
    pitch = sum((x-mx)*(y-my) for x,y in zip(xs,levels))/sum((x-mx)**2 for x in xs)
    expected_leads = 16 if ref=='TR1' else 4
    passed = max(abs(v) for v in size_error)<.005 and center_error<.005 and abs(local_box[2]-offset[2])<.005 and abs(pitch-cfg['pitch'])<.005 and len(leads)==expected_leads and len(current_fs)==source407['features'][ref]['face_count']
    extra_rows.append({'ref':ref,'passed':passed,'face_count':len(current_fs),'actual_world_bbox_mm':box,'actual_full_xyz_world_mm':actual_size,
                       'expected_full_xyz_world_mm':expected_size,'size_error_mm':size_error,'actual_center_component_local_mm':actual_center,
                       'expected_offset_mm':offset,'center_error_xy_mm':center_error,'minimum_z_mm':local_box[2],
                       'physical_terminal_count':len(leads),'nominal_pitch_mm':cfg['pitch'],'actual_pitch_mm':pitch,'pitch_error_mm':pitch-cfg['pitch'],
                       'physical_terminals':leads,'manufacturer_exact':False,'mechanical_clearance_approved':False})
report = {'schema':'stm32-final-calibrated407-standard29-geometry-audit-v1','native_calls':0,'passed':all(p['passed'] for p in standard_rows+extra_rows),
          'source_export':NEW.name,'source_export_sha256':hashlib.sha256(NEW.read_bytes()).hexdigest(),
          'baseline_export':OLD.name,'baseline_export_sha256':hashlib.sha256(OLD.read_bytes()).hexdigest(),
          'topology_and_vertex_order_identical':topology_equal,'vertex_count':len(vertices)-1,'face_count':len(faces),
          'unchanged_geometry_transfer_tolerance_mm':motion_tolerance,
          'standard27_unchanged_from_verified_export':standard_rows,'new_switch_transformer_verified':extra_rows,
          'changed_vertex_count':len(changed_ids),'changed_vertex_runs_diagnostic':changed_summaries,
          'limits':['Header/SMA18 geometry is audited independently by the inventory agent; this file proves29 other calibrated models.',
                    'All remaining package models are generic visualizations unless another exact-model provenance says otherwise; no manufacturing-clearance approval.',
                    'Unchanged geometry transfer relies on identical native vertex index topology plus zero measured vertex motion, not component labels absent from OBJ.']}
(ROOT/'audits/final407-standard29-geometry.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'topology_equal':topology_equal,'unchanged_standards':len(standard_rows),'extras':extra_rows,
                  'changed_runs':changed_summaries},indent=2))
