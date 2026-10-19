"""Freeze 18 candidate transforms after independent native pilot inspection.

Creates evidence/plan only. Root is the sole native/UI operator.
"""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE.parent
candidate=json.loads((OUT/'headers-native-calibration-candidates-v2.json').read_text(encoding='utf-8'))
old_bad=json.loads((OUT/'audits/header-registered-j16-shoulder.json').read_text())
pilot=json.loads((OUT/'audits/header-registered-j12-right-shoulder.json').read_text())
j1=json.loads((OUT/'audits/j1-contact-registration-canonical-locators.json').read_text())
assert pilot['selected_new_faces']==2221
assert j1['all14_contact_bottom_sections_inside_actual14_pad_rectangles']
assert all(p['min_section_hole_radial_margin_mm']>0 for p in j1['locator_and_other_sections'])

def fmt(values):
    return ','.join(format(0 if abs(v)<1e-10 else v,'.10f').rstrip('0').rstrip('.') for v in values)

def xf(size,rot,off):
    return fmt([*(v/.0254 for v in size),rot,0,0,*(v/.0254 for v in off)])

entries=[]
for old in candidate['entries']:
    entry={k:v for k,v in old.items() if k not in ['awaiting_validation','transform','transform_mm','executable']}
    family=entry['family']
    if family=='SMA_RA_KWE901':
        size=[7.,15.1,12.8980158]
        rot=old['transform_mm']['rotZXY_deg'][0]
        off={90:[4.05,0,-3.05],270:[-4.05,0,-3.05],180:[0,4.05,-3.05]}[rot]
        verification='Native J12 pilot verified positive90neck+X, normalizedfullbboxframe, shoulder seatingZ0 with1mm posts belowPCB. Native J16 pilot independently verified180neck+Y but its supersededZ-3.4 caused buried shoulders; this plan corrects it to-3.05.'
        warning=['Exact manufacturer body/mechanical fit is not certified, despite matchingnative modelname.','Final18modelnativeOBJ inspection still required after application.']
    elif family=='SAMTEC_FTSH107_14_SMD':
        size=[8.89,5.842,6.985]
        rot=0
        off=[0,0,-.8636]
        verification='Native default mesh pitch1.27mm restored; all14contactbottom sections inside actual14SMT padrectangles with minimum0.1668004mm margin. Locator section radial margins inactualNPTH:0.0509054/0.0522612mm. Independent historicalkernel confirms contact0,bodyfloor+.4064,locator-.8636,top6.1214mm.'
        warning=['Modelpin1mark not independently established; rotation0 aligns fullsymmetric contact/locatorarray.','Not a tolerance/manufacturing certification. Finalexplicit nativeOBJ proof remains.']
    else:
        size=[12.7,5.08,11.4844028290336]
        rot=0
        off=[0,0,-3.01440270115641]
        verification='Ten native metalpinsections register to2.54mm5x2footprint. Bodyunderside seats at0; complete mesh andnegativepinends retained. Genericpins have slightlyasymmetric formed/tessellated contours.'
        warning=['Generic2x5P2.54socket not exactPPTC052LFBN-RC bodyheight.','Modelpin1mark not independently established; symmetricarray aligns at0or180.','Finalexplicit nativeOBJ proof remains.']
    entry.update({'transform':xf(size,rot,off),'transform_mm':{'full_mesh_xyz':size,'rotZXY_deg':[rot,0,0],'offset_xyz':off},
                  'executable':True,'scope':'3D metadata only; no footprints or electricalgeometry edits',
                  'registration_verification':verification,'remaining_visualization_limits':warning})
    entries.append(entry)

report={'schema':'stm32-header-native-final-apply-plan-v1','status':'READY_FOR_ROOT_METADATA_APPLICATION_AND_FINAL_EXPORT_QA',
 'supersedes':['headers-native-calibration-candidates.json (SMA wrongseatingZ)','headers-native-calibration-candidates-v2.json (pre90pilot)'],
 'entries':entries,'target_count':18,'dnp_or_testpoint_targets':0,
 'noCADwrite_by_this_script':True,'full_mesh_sizes_not_body_only':True,
 'rounding_note':'SMA7/15.1, J1 8.89/5.842/6.985 are geometry-restored canonical dimensions with submicron tessellation residual rounded to their nominal metric/inch multiples; no envelope/body shrink applied. SMAZ12.8980158 retains the actual rounded-vertex complete mesh extent, not assumed12.9.',
 'evidence':[{'path':str(OUT/name),'sha256':hashlib.sha256((OUT/name).read_bytes()).hexdigest()} for name in ['audits/header-default-379-all18.json','audits/header-registered-j16-shoulder.json','audits/header-registered-j12-right-shoulder.json','audits/j1-contact-registration-canonical-locators.json']],
 'limits':['Geometric model registration is not manufacturer mechanical-fit or fabrication approval.','J1/J18pin1visualmarksremainuncertified; electricalpinmapsarenotmodified.','OnlytheSMAfamilyhasexplicitnativepilotregistrationproofatthispoint;J1/J18needfinalexportQA.']}
target=OUT/'headers-native-final-apply-plan.json'
assert not target.exists()
target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
summary=OUT/'headers-native-final-calibration-report.txt'
assert not summary.exists()
summary.write_text('18-target native3Dmetadata apply plan; no CAD was modified by analysis.\n'
 'SMA16: completeXYZ7x15.1x12.8980158mm; seating shoulder at0,case+.35mm,tip-3.05mm.\n'
 'J2..J11 rot270/off(-4.05,0,-3.05); J12..J15/J17rot90/off(+4.05,0,-3.05);J16rot180/off(0,+4.05,-3.05).\n'
 'J1:completeXYZ8.89x5.842x6.985mm;rot0,off(0,0,-.8636).14contacts/2locators registered;pin1mark uncertified.\n'
 'J18:genericcompleteXYZ12.7x5.08x11.484402829mm;rot0,off(0,0,-3.014402701).2.54mmpattern;exactheight/pin1mark uncertified.\n'
 'ExplicitSMAJ12pilot confirms positive90neck+X/shoulderZ0; firstJ16Z-3.4pilot was deliberately corrected after shoulder interference discovered.\n'
 'No body-only bbox/shrink. Final18 nativeOBJ coverage/registration and fullCADmetadata audit still required after root applies.\n',encoding='utf-8')
print(json.dumps({'plan':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'targets':len(entries)}))
