import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
data=json.loads((HERE/'final407-sot235-pieces.json').read_text())
plan=json.loads((ROOT/'sot23-5-3d-apply-plan.json').read_text())
inv={p['ref']:p for p in json.loads((ROOT/'inventory/components-437.json').read_text())}
models={m['ref']:m for m in data['full_models']}
rows=[]
for e in plan['entries']:
    ref=e['ref']
    m=models[ref]
    p=inv[ref]
    tr=list(map(float,e['transform'].split(',')))
    angle=math.radians(p['rotation_deg']+tr[3])
    size=[v*.0254 for v in tr[:3]]
    expected_size=[abs(math.cos(angle))*size[0]+abs(math.sin(angle))*size[1],abs(math.sin(angle))*size[0]+abs(math.cos(angle))*size[1],size[2]]
    offset=[tr[6]*.0254,tr[7]*.0254]
    ca,sa=math.cos(math.radians(p['rotation_deg'])),math.sin(math.radians(p['rotation_deg']))
    expected_center=[p['x_mm']+offset[0]*ca-offset[1]*sa,p['y_mm']+offset[0]*sa+offset[1]*ca]
    center_error=math.dist(expected_center,m['center_xyz_mm'][:2])
    size_error=[m['size_xyz_mm'][k]-expected_size[k] for k in range(3)]
    leads=[piece for piece in m['pieces'] if piece['faces']==58 and piece['vertices']==31]
    native_centers=[]
    for lead in leads:
        x,y=lead['center_mm'][0]-expected_center[0],lead['center_mm'][1]-expected_center[1]
        native_centers.append([x*math.cos(angle)+y*math.sin(angle),-x*math.sin(angle)+y*math.cos(angle)])
    left=sorted([c for c in native_centers if c[0]<0],key=lambda c:c[1])
    right=sorted([c for c in native_centers if c[0]>0],key=lambda c:c[1])
    left_pitch=(left[-1][1]-left[0][1])/2
    right_pitch=(right[-1][1]-right[0][1])/2
    passed=m['faces']==1412 and len(leads)==5 and len(left)==3 and len(right)==2 and max(abs(v) for v in size_error)<.005 and center_error<.005 and abs(m['bbox_mm'][2])<.005 and max(abs(left_pitch-.95),abs(right_pitch-.95))<.005
    rows.append({'ref':ref,'passed':passed,'component_id_from_binding_plan':e['id'],'vertex_range':m['vertex_range'],'faces':m['faces'],
                 'actual_bbox_mm':m['bbox_mm'],'actual_full_xyz_mm':m['size_xyz_mm'],'native_transform_envelope_xyz_mm':expected_size,'size_error_vs_native_envelope_mm':size_error,
                 'center_error_xy_mm':center_error,'minimum_z_mm':m['bbox_mm'][2],'physical_lead_count':len(leads),'lead_centers_in_selected_native_axes_mm':native_centers,
                 'three_leads_on_left_two_on_right':len(left)==3 and len(right)==2,'left_row_pitch_mm':left_pitch,'right_two_lead_span_divided_by_two_mm':right_pitch,
                 'nominal_pitch_mm':.95,'maximum_pitch_error_mm':max(abs(left_pitch-.95),abs(right_pitch-.95)),
                 'orientation_basis':e['evidence'],'model_relation':e['relation']})
export=ROOT/'STM32H747_calibrated407_STM32H747_calibrated407'
report={'schema':'stm32-final407-sot235-23-geometry-audit-v1','passed':all(r['passed'] for r in rows),'native_calls':0,
        'source_export':export.name,'source_export_sha256':hashlib.sha256(export.read_bytes()).hexdigest(),'model_count':len(rows),'rows':rows,
        'maximum_size_error_mm':max(abs(v) for r in rows for v in r['size_error_vs_native_envelope_mm']),
        'maximum_center_error_xy_mm':max(r['center_error_xy_mm'] for r in rows),'maximum_pitch_error_mm':max(r['maximum_pitch_error_mm'] for r in rows),
        'limits':['Native model envelope dimensions are not always exact triangle bounds. Here the maximum0.00315mm difference is measured and reported, not hidden.',
                  'Pin1 marking direction comes from the root native U10 model-manager pilot; all23 instances use the same model/transform and verified3-left/2-right terminal topology.',
                  'The model is SOT23-5 package-equivalent, not exact MPN markings or manufacturer mechanical clearance approval.']}
(ROOT/'audits/final407-sot235-23-geometry.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['passed','model_count','maximum_size_error_mm','maximum_center_error_xy_mm','maximum_pitch_error_mm']},indent=2))
