"""Read-only native OBJ differential and connected-geometry analysis."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OLD = ROOT / 'STM32H747_headers_default_379_STM32H747_headers_default_379'
NEW = ROOT / 'STM32H747_standards_default_405_STM32H747_standards_default_405'

def bounds(points):
    return [min(p[k] for p in points) for k in range(3)] + [max(p[k] for p in points) for k in range(3)]

def load(path):
    with zipfile.ZipFile(path) as z:
        obj = z.read(next(n for n in z.namelist() if n.endswith('.obj'))).decode()
        mtl = z.read(next(n for n in z.namelist() if n.endswith('.mtl'))).decode()
    materials = {}
    current = None
    for line in mtl.splitlines():
        t = line.split()
        if t and t[0] == 'newmtl':
            current = t[1]
            materials[current] = {}
        elif t and current and t[0] in ['Kd', 'Ka', 'Ks', 'd']:
            materials[current][t[0]] = list(map(float, t[1:]))
    vertices = [None]
    faces = []
    mat = None
    block = -1
    for line in obj.splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == 'v':
            vertices.append(tuple(map(float, t[1:4])))
        elif t[0] == 'usemtl':
            mat = t[1]
            block += 1
        elif t[0] == 'f':
            ids = tuple(int(s.split('/')[0]) for s in t[1:])
            faces.append((mat, block, ids))
    return vertices, faces, materials

def face_key(ids, vertices):
    return tuple(sorted(tuple(round(v, 6) for v in vertices[i]) for i in ids))

def main():
    old_v, old_f, old_materials = load(OLD)
    baseline = Counter(face_key(ids, old_v) for _, _, ids in old_f)
    del old_v, old_f
    vertices, faces, materials = load(NEW)
    added = []
    common = 0
    for face in faces:
        key = face_key(face[2], vertices)
        if baseline[key]:
            baseline[key] -= 1
            common += 1
        else:
            added.append(face)
    removed_count = sum(baseline.values())
    parent = {}
    def find(a):
        parent.setdefault(a, a)
        if parent[a] != a:
            parent[a] = find(parent[a])
        return parent[a]
    def merge(a, b):
        parent[find(b)] = find(a)
    for mat, block, ids in added:
        for i in ids:
            merge(ids[0], i)
    group_faces = defaultdict(list)
    for face in added:
        group_faces[find(face[2][0])].append(face)
    components = {p['ref']: p for p in json.loads((ROOT / 'inventory/components-437.json').read_text(encoding='utf-8'))}
    registry = json.loads((ROOT / 'standard-model-candidate-registry.json').read_text(encoding='utf-8'))
    targets = {p['ref']: p for p in registry['targets']}
    pieces = []
    for fs in group_faces.values():
        ids = sorted({i for _, _, faceids in fs for i in faceids})
        box = bounds([vertices[i] for i in ids])
        center = [(box[k] + box[k+3])/2 for k in range(3)]
        distances = sorted((math.dist(center[:2], [components[r]['x_mm'], components[r]['y_mm']]), r) for r in targets)
        pieces.append({'vertex_min': ids[0], 'vertex_max': ids[-1], 'vertices': len(ids), 'faces': len(fs),
                       'materials': dict(Counter(mat for mat, _, _ in fs)), 'blocks': sorted({b for _, b, _ in fs}),
                       'bbox_mm': box, 'size_xyz_mm': [box[k+3]-box[k] for k in range(3)], 'center_xyz_mm': center,
                       'nearest_ref': distances[0][1], 'nearest_distance_mm': distances[0][0]})
    pieces.sort(key=lambda p:p['vertex_min'])
    face_refs = {}
    for piece in pieces:
        for fs in group_faces.values():
            if min(i for _, _, ids in fs for i in ids) == piece['vertex_min']:
                face_refs[find(fs[0][2][0])] = piece['nearest_ref']
                break
    model_faces = defaultdict(list)
    for face in added:
        model_faces[face_refs[find(face[2][0])]].append(face)
    u3 = components['U3']
    for face in faces:
        if face[0] == 'mtl1':
            continue
        if all(abs(vertices[i][0]-u3['x_mm']) < 1.85 and abs(vertices[i][1]-u3['y_mm']) < 1.85 and -.01 <= vertices[i][2] < 2 for i in face[2]):
            model_faces['U3'].append(face)
    features = {}
    for ref, fs in model_faces.items():
        component = components[ref]
        a = math.radians(component['rotation_deg'])
        def local(i):
            x,y,z = vertices[i]
            x -= component['x_mm']
            y -= component['y_mm']
            return (x*math.cos(a)+y*math.sin(a), -x*math.sin(a)+y*math.cos(a), z)
        ids = {i for _,_,faceids in fs for i in faceids}
        box = bounds([local(i) for i in ids])
        center = [(box[k]+box[k+3])/2 for k in range(3)]
        material_features = {}
        for mat in {m for m,_,_ in fs}:
            mf = [(b,faceids) for m,b,faceids in fs if m == mat]
            par = {}
            def mf_find(i):
                par.setdefault(i,i)
                if par[i] != i:
                    par[i] = mf_find(par[i])
                return par[i]
            for _, faceids in mf:
                for i in faceids:
                    par[mf_find(i)] = mf_find(faceids[0])
            m_groups = defaultdict(set)
            m_face_count = Counter()
            for _,faceids in mf:
                k = mf_find(faceids[0])
                m_groups[k].update(faceids)
                m_face_count[k] += 1
            comps = []
            for k, mids in m_groups.items():
                mb = bounds([local(i) for i in mids])
                comps.append({'faces': m_face_count[k], 'vertices':len(mids), 'bbox_local_mm':mb,
                              'center_from_model_bbox_mm':[(mb[j]+mb[j+3])/2-center[j] for j in range(3)],
                              'size_xyz_mm':[mb[j+3]-mb[j] for j in range(3)]})
            material_features[mat] = {'color': materials[mat], 'bbox_local_mm':bounds([local(i) for _,idsm in mf for i in idsm]), 'pieces':comps}
        features[ref] = {'family':targets[ref]['family'], 'face_count':len(fs), 'bbox_component_local_mm':box,
                         'auto_center_component_local_mm':center, 'default_size_xyz_mm':[box[k+3]-box[k] for k in range(3)],
                         'source_component_rotation_deg':component['rotation_deg'], 'materials':material_features}
    report = {'schema': 'stm32-standard405-native-obj-differential-v1',
              'baseline': {'path': OLD.name, 'sha256': hashlib.sha256(OLD.read_bytes()).hexdigest()},
              'export': {'path': NEW.name, 'sha256': hashlib.sha256(NEW.read_bytes()).hexdigest()},
              'common_face_count': common, 'removed_face_count': removed_count, 'added_face_count': len(added),
              'materials': materials, 'pieces': pieces,
              'limitations': ['Connected geometry pieces and material blocks are not component identities. Nearest refs are diagnostic only, not final assignments.',
                              'Face differences use coordinate triples rounded to 1e-6 mm and multiplicity; unchanged prior 379-model geometry should have zero removed faces.',
                              'U3 was already present in the baseline and must be separately included from its pilot evidence.']}
    output = HERE / 'standard405-differential-pieces.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    (HERE / 'standard405-material-features.json').write_text(json.dumps(features, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'common_faces':common, 'removed_faces':removed_count, 'added_faces':len(added), 'pieces':len(pieces),
                      'large_pieces':[{k:p[k] for k in ['vertex_min','vertex_max','faces','materials','bbox_mm','nearest_ref']} for p in pieces if p['faces'] > 90]}, indent=2))

if __name__ == '__main__':
    main()
