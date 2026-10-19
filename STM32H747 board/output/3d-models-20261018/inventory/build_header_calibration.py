"""Write candidate native transforms from measured header default geometry.

This is a plan only. It performs no native API call or CAD write. A native
pilot OBJ must confirm the explicit transform normalization/rotation sign.
"""
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE.parent
MM_TO_MIL=1/.0254
parts={p['ref']:p for p in json.loads((HERE/'components-437.json').read_text(encoding='utf-8'))}
bindings=json.loads((OUT/'headers-sma-default-model-plan.json').read_text(encoding='utf-8'))['entries']
evidence_path=OUT/'audits/header-default-379-all18.json'
evidence=json.loads(evidence_path.read_text(encoding='utf-8'))
models=evidence['isolated_models']

def average(vs):
    vs=list(vs)
    return sum(vs)/len(vs)

def rotate(v,angle):
    a=math.radians(angle)
    return [math.cos(a)*v[0]-math.sin(a)*v[1],math.sin(a)*v[0]+math.cos(a)*v[1]]

def native(size,rot,offset):
    values=[*(v*MM_TO_MIL for v in size),rot,0,0,*(v*MM_TO_MIL for v in offset)]
    return ','.join(format(0 if abs(v)<1e-9 else v,'.10f').rstrip('0').rstrip('.') for v in values)

def section_pieces(ref,z,color):
    return [p for p in models[ref]['horizontal_sections_mm'][str(z)] if p['color']==color]

# Four square shell posts are geometrically distinct below the body.
sma_pieces=section_pieces('J16',.1,[1.,.87,.76])
sma_posts=[p for p in sma_pieces if abs(p['center_local_xy_mm'][0])>1]
assert len(sma_posts)==4
sx=average(p['center_local_xy_mm'][0] for p in sma_posts if p['center_local_xy_mm'][0]>0)-average(p['center_local_xy_mm'][0] for p in sma_posts if p['center_local_xy_mm'][0]<0)
sy=average(p['center_local_xy_mm'][1] for p in sorted(sma_posts,key=lambda p:p['center_local_xy_mm'][1])[2:])-average(p['center_local_xy_mm'][1] for p in sorted(sma_posts,key=lambda p:p['center_local_xy_mm'][1])[:2])
assert abs(sx-sy)<2e-7  # native tessellation float residual, not CAD tolerance
sma_scale=5.08/average([sx,sy])
sma_size=[v*sma_scale for v in models['J16']['size_xyz_mm']]
sma_pin_center=[average(p['center_local_xy_mm'][k] for p in sma_posts) for k in range(2)]
sma_pin_offset=[(sma_pin_center[k]-models['J16']['center_local_xy_mm'][k])*sma_scale for k in range(2)]
# The four metal post shoulders begin3.05mm above pin tips. Seating the case
# underside at3.4mm would bury the expanded shoulders0.35mm in the PCB. The
# transformed J16 pilot proved this at sections-.351/-.349mm. Use shoulders,
# leaving the case underside+.35mm and center insulator+.65mm above the PCB.
sma_mount=1.676493419*sma_scale

# Fourteen contacts have a 7-column 1.27mm pitch. The lowest metal plane
# (.920916... observed) seats on the PCB; locator pegs protrude below it.
j1_pieces=section_pieces('J1',1.0,[.75,.75,.75])
assert len(j1_pieces)==14
j1_columns=sorted(set(p['center_local_xy_mm'][0] for p in j1_pieces))
j1_pitch=(j1_columns[-1]-j1_columns[0])/6
j1_scale=1.27/j1_pitch
j1_size=[v*j1_scale for v in models['J1']['size_xyz_mm']]
j1_mount=.9209162361360256*j1_scale

# Generic socket pitch is determined by both repeated columns and row span.
# Row pitch is unaffected by the slightly bent/formed individual contacts.
j18_pieces=section_pieces('J18',.1,[.95,.76,.18])
assert len(j18_pieces)==10
j18_rows=sorted(set(p['center_local_xy_mm'][1] for p in j18_pieces))
assert len(j18_rows)==2
j18_pitch=j18_rows[1]-j18_rows[0]
j18_scale=2.54/j18_pitch
j18_size=[v*j18_scale for v in models['J18']['size_xyz_mm']]
j18_mount=3.0666267228998922*j18_scale

families={
 'SMA_RA_KWE901':{'observed_pin_pitch_xy_mm':[sx,sy],'physical_footprint_pitch_mm':5.08,'inverse_default_scale':sma_scale,'full_mesh_xyz_mm':sma_size,'normalized_bbox_to_pin_pattern_xy_mm':sma_pin_offset,'seating_z_from_normalized_min_mm':sma_mount,'case_underside_above_seating_mm':.35,'default_neck_vector_xy':[0,-1],'seated_mesh_min_z_mm':-sma_mount,'seated_mesh_max_z_mm':sma_size[2]-sma_mount,'proof':'Four distinct1x1mm square metal posts. Their expanded shoulders begin3.05mm above tip minimum; this is the seating plane. Native J16 pilotZ=-.351 gave1x1mm post sections;Z=-.349 gave1.46x1.46mm outer shoulder beyond1.5mm drill. Case underside3.4mm is NOT the seating plane. All16 meshes have2221 faces and identical complete bbox dimensions.'},
 'SAMTEC_FTSH107_14_SMD':{'observed_column_pitch_mm':j1_pitch,'physical_footprint_pitch_mm':1.27,'inverse_default_scale':j1_scale,'full_mesh_xyz_mm':j1_size,'normalized_bbox_to_pin_pattern_xy_mm':[0,0],'seating_z_from_normalized_min_mm':j1_mount,'seated_mesh_min_z_mm':-j1_mount,'seated_mesh_max_z_mm':j1_size[2]-j1_mount,'body_underside_above_contacts_mm':.4064,'proof':'14 SMT feet in7columns;1.27mm pitch restoration. Lowest metal faces are seated; lower black geometry comprises locator pegs. Independent historical STEP kernel gives locator-.8636, contact0, bodyfloor+.4064, top6.1214mm.'},
 'SOCKET_2X5_P254':{'observed_row_pitch_mm':j18_pitch,'physical_footprint_pitch_mm':2.54,'inverse_default_scale':j18_scale,'full_mesh_xyz_mm':j18_size,'normalized_bbox_to_pin_pattern_xy_mm':[0,0],'seating_z_from_normalized_min_mm':j18_mount,'seated_mesh_min_z_mm':-j18_mount,'seated_mesh_max_z_mm':j18_size[2]-j18_mount,'proof':'10 distinct metal pin sections,5columns and2rows. First dark plastic underside is used as generic seating plane; exactPPTC052LFBN-RC height is not established.'}
}
entries=[]
for binding in bindings:
    ref,family=binding['ref'],binding['family']
    if family=='SMA_RA_KWE901':
        number=int(ref[1:])
        # These angles are mathematical XY rotations, pending confirmation
        # that positive native rotZ has the same sign in exported PCB XY.
        rot=270 if 2<=number<=11 else 180 if number==16 else 90
        offsetxy=rotate([-sma_pin_offset[0],-sma_pin_offset[1]],rot)
        offset=[*offsetxy,-sma_mount]
        direction=[-1,0] if 2<=number<=11 else [0,1] if number==16 else [1,0]
        uncertainty=['Native explicit transform normalization and positive rotZ sign must be confirmed by a pilot export.']
    else:
        rot=0
        offset=[0,0,-families[family]['seating_z_from_normalized_min_mm']]
        direction=None
        uncertainty=['Pin1 visual marking is not independently verified;0deg and180deg both align the symmetric contact array.','Native explicit transform normalization must be confirmed by a pilot export.']
    size=families[family]['full_mesh_xyz_mm']
    entries.append({'ref':ref,'id':binding['id'],'footprintUuid':parts[ref]['footprint_uuid'],
        'family':family,'model':binding['uuid']+'|'+binding['libraryUuid'],'title':binding['title'],
        'transform':native(size,rot,offset),'transform_mm':{'full_mesh_xyz':size,'rotZXY_deg':[rot,0,0],'offset_xyz':offset},
        'desired_neck_vector_current_pcb_xy':direction,'relation':binding['relation']+'; not a mechanical/manufacturing certification',
        'executable':False,'awaiting_validation':uncertainty})
report={'schema':'stm32-native-header-calibration-candidates-v2','status':'PILOT_VALIDATION_REQUIRED_NOT_AUTORUN',
 'supersedes':'headers-native-calibration-candidates.json: itsSMA offZ=-3.4mm is invalid because expanded ground shoulders penetrate the board. CorrectedoffZ=-3.05mm.',
 'CAD_modified':False,'source_geometry':str(evidence_path),'source_geometry_sha256':hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
 'full_18_model_coverage_faces':{'SMA':16*2221,'J1':2618,'J18':5260,'total':43414,'old_faces_missing':0},
 'native_transform_assumption':'sizeXYZ_mil,rotZ_deg,rotX_deg,rotY_deg,offsetXYZ_mil; fullmesh centerXY/minZ normalization followed by R and offset. Pilot export must validate it.',
 'registration_math':'If p is desired pin-array center in normalized complete-bbox frame and zseat is mounting plane above minimum, offsetXY=-R*p, offsetZ=-zseat. All full mesh extents retained; no body-only bounding box or shrink applied.',
 'orientation_evidence':'Historical STEP rotation-columnZ outward vectors supplied by independent research agent: J2..J11 -X; J12,J13,J14,J15,J17 +X;J16 +Y. See source-models/canonical-reference-models/canonical-manifest.json historical_SMA_outward_vectors. Native KWE901 mesh differs from historical generic mesh, but its5.08 square terminal pattern and outward neck register equivalently.',
 'global_export_note':'Default OBJ XY centers have a systematic approximately2ppm scale relative to PCB coordinates. Registration is relative to each complete mesh bbox, cancelling that placement conversion; absolute OBJ shifts are not copied into transforms.',
 'families':families,'entries':entries,
 'limits':['3D metadata only; circuit connectivity and footprints are not altered.','J1 exact-name mesh has not had its pin1 mark independently verified. J18 is generic pitch-equivalent, not exact MPN geometry.','The plan is not executable until pilot normalization/rotation checks pass. These flags are deliberate, not a claim of all18 final bindings being approved.']}
target=OUT/'headers-native-calibration-candidates-v2.json'
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
summary=OUT/'headers-native-calibration-report-v2.txt'
assert not summary.exists()
summary.write_text('\n'.join(['Native18 header/SMA calibration candidate; no CAD changes.',
 'Coverage:43414 newfaces=16*2221 SMA+2618 J1+5260 J18; all old361 geometry faces reproduced exactly.',
 *[f'{name}: complete meshXYZmm={data["full_mesh_xyz_mm"]}; mountplane above normalized minZ={data["seating_z_from_normalized_min_mm"]}mm.' for name,data in families.items()],
 'SMA default neck -Y, pinarray+Y4.05 relativefullbboxcenter. Rotate neck to historical outward; offset=-R*p; Z=-3.05mm(shoulderseat). Caseunderside+.35mm.',
 'J1 SMTcontactseat=0; locatorends-.8636; bodyfloor+.4064;top6.1214. Pin1mark unresolved.',
 'J18 generic bodyseat=0, pinends about-3.0144; mountedheight8.47mm; actualMPNheight not certified.',
 'All candidates explicitly nonexecutable until nativepilot confirms transformnormalization and rotZsign.'])+'\n',encoding='utf-8')
print(json.dumps({'plan':str(target),'families':families,'entries':len(entries)}))
