"""Prove existing 407 models and PCB triangles survive final 412 native export.

No CAD API, UI, original circuit or model-library writes. Triangle comparison uses
the exact parsed OBJ coordinate doubles, not rounded/spatial-nearest matches.
"""
from collections import Counter, defaultdict
import gc
import hashlib
import json
from pathlib import Path

from inspect_standard_meshes import bounds, load

ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / 'STM32H747_calibrated407_STM32H747_calibrated407'
NEW = ROOT / 'STM32H747_final412_STM32H747_final412'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_key(ids, vertices):
    return tuple(sorted(vertices[i] for i in ids))


def material_key(material):
    return tuple((key, tuple(value)) for key, value in sorted(material.items()))


def main():
    before_sha = sha(OLD)
    final_sha = sha(NEW)
    old_v, old_f, old_m = load(OLD)
    baseline_faces = len(old_f)
    baseline_vertices = len(old_v) - 1
    baseline = Counter(exact_key(ids, old_v) for _, _, ids in old_f)
    baseline_appearance = Counter((exact_key(ids, old_v), material_key(old_m[mat]))
                                  for mat, _, ids in old_f)
    del old_v, old_f, old_m
    gc.collect()
    vertices, faces, materials = load(NEW)
    added = []
    common = 0
    appearance_common = 0
    for face in faces:
        mat, _, ids = face
        key = exact_key(ids, vertices)
        if baseline[key]:
            baseline[key] -= 1
            common += 1
        else:
            added.append(face)
        app_key = (key, material_key(materials[mat]))
        if baseline_appearance[app_key]:
            baseline_appearance[app_key] -= 1
            appearance_common += 1
    removed_count = sum(baseline.values())
    appearance_missing = sum(baseline_appearance.values())
    del baseline, baseline_appearance
    gc.collect()

    # Components of only the newly added mesh; model identity is determined by
    # the independent local-five source-kernel registration audit, not by block.
    parent = {}
    def find(i):
        parent.setdefault(i, i)
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]
    def union(a, b):
        parent[find(b)] = find(a)
    for _, _, ids in added:
        for i in ids:
            union(ids[0], i)
    pieces = defaultdict(list)
    for face in added:
        pieces[find(face[2][0])].append(face)
    piece_rows = []
    for fs in pieces.values():
        ids = sorted({i for _, _, triangle in fs for i in triangle})
        box = bounds([vertices[i] for i in ids])
        piece_rows.append({'vertices':len(ids), 'faces':len(fs),
                           'vertex_min':ids[0], 'vertex_max':ids[-1],
                           'bbox_mm':box, 'size_xyz_mm':[box[k+3]-box[k] for k in range(3)]})
    piece_rows.sort(key=lambda row:row['vertex_min'])
    assert sha(OLD) == before_sha and sha(NEW) == final_sha, 'Export changed while inspected'
    passed = (removed_count == 0 and common == baseline_faces == 760928
              and len(faces) == common + len(added) and appearance_missing == 0)
    report = {
        'schema':'stm32-final412-prior407-native-triangle-preservation-v1',
        'passed':passed, 'native_calls':0,
        'baseline':{'path':OLD.name,'bytes':OLD.stat().st_size,'sha256':before_sha,
                    'vertices':baseline_vertices,'faces':baseline_faces,'linked_models':407},
        'export':{'path':NEW.name,'bytes':NEW.stat().st_size,'sha256':final_sha,
                  'vertices':len(vertices)-1,'faces':len(faces),'linked_models_expected':412},
        'comparison':{'coordinates':'exact Python float values parsed from OBJ decimals; no rounding or tolerance',
                      'triangle_vertex_order':'vertex permutation ignored; all three coordinates and triangle multiplicity retained',
                      'material':'exact parsed Ka/Kd/Ks/d properties; material names/block IDs may differ',
                      'prior_geometry_triangles_matched_with_multiplicity':common,
                      'missing_prior_geometry_triangles':removed_count,
                      'prior_geometry_and_appearance_triangles_matched_with_multiplicity':appearance_common,
                      'missing_prior_geometry_appearance_triangles':appearance_missing,
                      'added_triangles_not_in_prior407_multiset':len(added),
                      'complete_current_face_partition':len(faces)==common+len(added)},
        'prior_verified_audits_reused_by_exact_geometry_preservation':[
            'audits/final407-geometry-verification-index.json',
            'audits/final407-passive337-preserved.json',
            'audits/final407-sot235-23-geometry.json',
            'audits/final407-standard29-geometry.json',
            'audits/final18-headers-calibrated407.json'],
        'added_connected_pieces':piece_rows,
        'limits':[
            'This proves retention of all prior407-plus-PCB rendered triangles and material properties, not native CAD model identities by itself.',
            'Connected pieces and material blocks are not component identities. Independent local-five source-kernel geometry audit must account for all added triangles.',
            'Triangle winding, normal/texture-index ordering and unused vertices are outside this coordinate-triangle multiset comparison.',
            'Existing package-equivalent, pin-marking, manufacturer-height and clearance limitations transfer unchanged; no new mechanical certification.']}
    output = ROOT/'audits/final412-existing407-preserved.json'
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(output),'passed':passed,'common':common,'removed':removed_count,
                      'appearance_missing':appearance_missing,'added':len(added),
                      'current_faces':len(faces),'added_connected_pieces':len(piece_rows),
                      'sha256':final_sha},indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
