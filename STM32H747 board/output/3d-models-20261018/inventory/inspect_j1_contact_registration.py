"""Check canonical native J1 contact/locator registration, no CAD writes."""
import json
import math
from pathlib import Path
from inspect_header_defaults import parse, sections

HERE=Path(__file__).resolve().parent
OUT=HERE.parent
report=json.loads((OUT/'audits/header-default-379-all18.json').read_text())
m=report['isolated_models']['J1']
plan=json.loads((OUT/'headers-native-calibration-candidates-v2.json').read_text())
family=plan['families']['SAMTEC_FTSH107_14_SMD']
scale=family['inverse_default_scale']
origin=m['source_position_xy_mm']
cx,cy=m['center_local_xy_mm']
zseat=family['seating_z_from_normalized_min_mm']/scale
faces,meta=parse(OUT/'STM32H747_headers_default_379_STM32H747_headers_default_379')
selected=[f for f in faces if all(abs(p[0]-origin[0])<5.1 and abs(p[1]-origin[1])<3.3 and -.01<p[2]<7.5 for p in f[1])]
cross=sections(selected,zseat+1e-4,origin,keep_points=True)
physical=[]
for p in cross:
    b=p['bbox_local_mm']
    b=[(b[0]-cx)*scale,(b[1]-cy)*scale,(b[3]-cx)*scale,(b[4]-cy)*scale]
    points=[[(q[0]-cx)*scale,(q[1]-cy)*scale] for q in p['points_local_xy_mm']]
    item={'color':list(p['color']),'bbox_xy_mm':b,'center_xy_mm':[(b[0]+b[2])/2,(b[1]+b[3])/2]}
    if item['color']==[.25,.25,.25]:
        hx=-3.175 if item['center_xy_mm'][0]<0 else 3.175
        maxradius=max(math.hypot(q[0]-hx,q[1]) for q in points)
        item.update({'NPTH_center_xy_mm':[hx,0],'NPTH_radius_mm':.51000025,
                     'max_section_vertex_radius_from_hole_mm':maxradius,'min_section_hole_radial_margin_mm':.51000025-maxradius})
    physical.append(item)
footprints=json.loads((HERE/'footprints-288.json').read_text())
pads=footprints['44621f0fae033d38']['pads_native_mil']
contacts=[p for p in physical if p['color']==[.75,.75,.75]]
assert len(contacts)==14
results=[]
for p in contacts:
    pad=min((q for q in pads if q['num']),key=lambda q:abs(q['centerX']*.0254-p['center_xy_mm'][0])+abs(q['centerY']*.0254-p['center_xy_mm'][1]))
    px,py=pad['centerX']*.0254,pad['centerY']*.0254
    w,h=pad['defaultPad']['width']*.0254,pad['defaultPad']['height']*.0254
    pb=[px-w/2,py-h/2,px+w/2,py+h/2]
    b=p['bbox_xy_mm']
    margins=[b[0]-pb[0],b[1]-pb[1],pb[2]-b[2],pb[3]-b[3]]
    results.append({'physical_pad_number':pad['num'],'contact_bbox_xy_mm':b,'pad_bbox_xy_mm':pb,
                    'signed_rectangular_margin_mm':margins,'contact_inside_pad':min(margins)>=0})
assert len({p['physical_pad_number'] for p in results})==14
out={'schema':'stm32-j1-canonical-contact-registration-v1','export':meta,
     'transform_frame':'Complete mesh normalized centerXY, noXYoffset, scale from1.27mm column pitch, contactbottomZseat, angle0.',
     'all14_contact_bottom_sections_inside_actual14_pad_rectangles':all(p['contact_inside_pad'] for p in results),
     'contacts':results,'locator_and_other_sections': [p for p in physical if p['color']!=[.75,.75,.75]],
     'limitations':['J1model pin1 visual mark is unverified; pad numbers identify spatial matching only, not model-internal pin numbering.',
                    'Pin/contact model registration is not a manufacturing clearance/tolerance certification.','Locator full circular-hole clearance is not proven by rectangular section bboxes alone.']}
target=OUT/'audits/j1-contact-registration-canonical-locators.json'
assert not target.exists()
target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'report':str(target),'all14_inside_pad':out['all14_contact_bottom_sections_inside_actual14_pad_rectangles'],
                  'min_contact_margin_mm':min(v for p in results for v in p['signed_rectangular_margin_mm']),
                  'locator_sections':out['locator_and_other_sections']}))
