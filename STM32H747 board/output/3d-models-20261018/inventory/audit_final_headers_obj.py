"""Read-only final18 native-header mesh coverage/registration proof."""
import argparse
from collections import Counter
import io
import json
import math
from pathlib import Path
import zipfile
from inspect_header_defaults import parse,signature,bbox,sections

HERE=Path(__file__).resolve().parent
OUT=HERE.parent
FACTOR=1/(39.37*.0254)  # empirically confirmed native OBJ placement conversion

def ranges(values):
    result=[]
    for v in sorted(values):
        if result and v==result[-1][1]+1:
            result[-1][1]=v
        else:
            result.append([v,v])
    return result

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--export',type=Path,required=True)
    ap.add_argument('--stage',required=True)
    args=ap.parse_args()
    source=args.export.resolve()
    assert source.is_relative_to(OUT.resolve())
    inventory={p['ref']:p for p in json.loads((HERE/'components-437.json').read_text())}
    footprints=json.loads((HERE/'footprints-288.json').read_text())
    plan=json.loads((OUT/'headers-native-final-apply-plan-normalized.json').read_text())
    old,oldmeta=parse(OUT/'STM32H747_headers_default_379_STM32H747_headers_default_379')
    before=Counter(signature(f) for f in old)
    del old
    faces,meta=parse(source)
    added=[]
    for index,f in enumerate(faces):
        key=signature(f)
        if before[key]:
            before[key]-=1
        else:
            added.append((index,f))
    del faces
    errors=[];models=[];selected_face_indices=set()
    for entry in plan['entries']:
        ref=entry['ref'];part=inventory[ref]
        assert part['rotation_deg']==0 and part['side']=='top'
        tr=[float(v) for v in entry['transform'].split(',')]
        size=[v*.0254 for v in tr[:3]];angle=math.radians(tr[3]);off=[v*.0254 for v in tr[6:]]
        span=[abs(math.cos(angle))*size[0]+abs(math.sin(angle))*size[1],abs(math.sin(angle))*size[0]+abs(math.cos(angle))*size[1],size[2]]
        xy=[part['x_mm'],part['y_mm']]
        expected=[off[0]-span[0]/2,off[1]-span[1]/2,off[2],off[0]+span[0]/2,off[1]+span[1]/2,off[2]+span[2]]
        world=[(expected[k]+(xy[k%3] if k%3<2 else 0))*FACTOR for k in range(6)]
        tol=.003  # diagnostic bbox attribution only, not CAD/manufacturing waiver
        chosen=[(i,f) for i,f in added if all(all(world[k]-tol<=p[k]<=world[k+3]+tol for k in range(3)) for p in f[1])]
        wanted=2618 if ref=='J1' else 5260 if ref=='J18' else 2221
        if len(chosen)!=wanted:
            errors.append({'ref':ref,'face_count':len(chosen),'expected':wanted})
        ids={i for i,f in chosen}
        if ids&selected_face_indices:
            errors.append({'ref':ref,'overlapping_face_attribution':len(ids&selected_face_indices)})
        selected_face_indices.update(ids)
        pts=[p for i,f in chosen for p in f[1]]
        if not pts:
            continue
        raw=bbox(pts)
        local=[raw[k]/FACTOR-(xy[k%3] if k%3<2 else 0) for k in range(6)]
        err=[local[k]-expected[k] for k in range(6)]
        if max(abs(e) for e in err)>.003:
            errors.append({'ref':ref,'bbox_registration_error_mm':err})
        z=.0001 if ref=='J1' else -.05
        color=[.75,.75,.75] if ref=='J1' else [.95,.76,.18] if ref=='J18' else [1.,.87,.76]
        cross=sections([f for i,f in chosen],z*FACTOR,[v*FACTOR for v in xy],keep_points=True)
        contacts=[p for p in cross if list(p['color'])==color]
        pads=footprints[part['footprint_uuid']]['pads_native_mil']
        tests=[]
        for piece in contacts:
            c=[v/FACTOR for v in piece['center_local_xy_mm']]
            candidates=[p for p in pads if p['num'] and (p.get('hole') or ref=='J1')]
            pad=min(candidates,key=lambda p:math.hypot(p['centerX']*.0254-c[0],p['centerY']*.0254-c[1]))
            px,py=pad['centerX']*.0254,pad['centerY']*.0254
            points=[[v/FACTOR for v in p] for p in piece['points_local_xy_mm']]
            if ref=='J1':
                w,h=pad['defaultPad']['width']*.0254,pad['defaultPad']['height']*.0254
                margin=min(min(p[0]-(px-w/2),px+w/2-p[0],p[1]-(py-h/2),py+h/2-p[1]) for p in points)
            else:
                radius=pad['hole']['width']*.0254/2
                margin=radius-max(math.hypot(p[0]-px,p[1]-py) for p in points)
            tests.append({'spatial_pad_number':pad['num'],'pad_center_mm':[px,py],'section_center_mm':c,'minimum_model_to_pad_or_hole_margin_mm':margin,'inside':margin>=0})
        expected_contacts=14 if ref=='J1' else 10 if ref=='J18' else 5
        if len(tests)!=expected_contacts or not all(t['inside'] for t in tests):
            errors.append({'ref':ref,'section_pieces':len(tests),'expected':expected_contacts,'failed_pieces':[t for t in tests if not t['inside']]})
        color_bounds=[]
        for c in {f[0] for i,f in chosen}:
            cb=bbox([p for i,f in chosen if f[0]==c for p in f[1]])
            color_bounds.append({'color':c,'zmin_corrected_mm':cb[2]/FACTOR,'zmax_corrected_mm':cb[5]/FACTOR})
        models.append({'ref':ref,'family':entry['family'],'face_count':len(chosen),'expected_face_count':wanted,
            'full_mesh_bbox_local_corrected_mm':local,'expected_full_bbox_local_mm':expected,'bbox_error_mm':err,
            'seated_contact_cross_section_Z_mm':z,'contact_or_pin_sections':tests,'material_z_bounds':color_bounds,
            'pin1_visual_mark_certified':False,'model_relation':entry['relation']})
    vertices=set()
    with zipfile.ZipFile(source) as archive:
        name=next(n for n in archive.namelist() if n.endswith('.obj'))
        face_index=0
        with archive.open(name) as raw:
            for line in io.TextIOWrapper(raw,encoding='utf-8'):
                if line.startswith('f '):
                    if face_index in selected_face_indices:
                        vertices.update(int(t.split('/')[0]) for t in line.split()[1:])
                    face_index+=1
    wanted_ids=set(range(28863,50616))
    if vertices!=wanted_ids:
        errors.append({'header_vertex_union_differs_expected_contiguous_block':{'extra_ranges':ranges(vertices-wanted_ids),'missing_ranges':ranges(wanted_ids-vertices)}})
    out={'schema':'stm32-final18-native-header-OBJ-QA-v1','passed':not errors,'export':meta,'baseline_default_export':oldmeta,
         'linked_header_models_verified':len(models),'selected_header_faces':len(selected_face_indices),'selected_vertex_ID_ranges':ranges(vertices),
         'expected_header_vertex_ID_range':[28863,50615],'header_vertex_union_matches_runtime_agent_topology_block':vertices==wanted_ids,
         'models':models,'errors':errors,'native_calls':0,
         'limits':['OBJ has no reference IDs; attribution combines exact prior-default face subtraction, isolated expected bbox and unchangedface topology counts.',
                   'Systematic OBJ unitconversion FACTOR='+str(FACTOR)+' is removed only for analytical dimension comparison; rawOBJ/CAD are untouched.',
                   '0.003mm bbox threshold is mesh-attribution diagnostic, not a CADgeometrypreservation or manufacturing clearance waiver.',
                   'Pin1visualmarks and manufacturermechanicaltolerances not certified; J18 is genericpitch-equivalent.','Local5unlinked parts are outside this18model proof.']}
    target=OUT/'audits'/f'final18-headers-{args.stage}.json'
    assert not target.exists()
    target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':not errors,'report':str(target),'models':len(models),'header_faces':len(selected_face_indices),'vertex_ranges':ranges(vertices),'errors':errors}))
    if errors:
        raise SystemExit(1)

if __name__=='__main__':
    main()
