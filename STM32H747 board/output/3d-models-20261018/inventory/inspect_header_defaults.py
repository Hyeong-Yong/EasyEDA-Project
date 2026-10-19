"""Read-only analysis of 18 newly bound native default header/SMA meshes.

The OBJ contains no component labels. Unchanged geometry is removed by exact
coordinate/color face multiset comparison against the prior 361-model export.
Only evidence outputs below output/3d-models-20261018 are created.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
OLD = OUT / 'STM32H747_u3_default_pilot_361_STM32H747_u3_default_pilot_361'
NEW = OUT / 'STM32H747_headers_default_379_STM32H747_headers_default_379'

def bbox(points):
    return [min(p[k] for p in points) for k in range(3)] + [max(p[k] for p in points) for k in range(3)]

def parse(path):
    with zipfile.ZipFile(path) as z:
        obj = z.read(next(n for n in z.namelist() if n.endswith('.obj'))).decode()
        mtl = z.read(next(n for n in z.namelist() if n.endswith('.mtl'))).decode()
    colors = {}
    for line in mtl.splitlines():
        t = line.split()
        if t and t[0] == 'newmtl':
            material = t[1]
        elif t and t[0] == 'Kd':
            colors[material] = tuple(float(v) for v in t[1:4])
    vertices = [None]
    faces = []
    for line in obj.splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == 'v':
            vertices.append(tuple(float(v) for v in t[1:4]))
        elif t[0] == 'usemtl':
            material = t[1]
        elif t[0] == 'f':
            ids = tuple(int(s.split('/')[0]) for s in t[1:])
            faces.append((colors[material], tuple(vertices[j] for j in ids)))
    return faces, {'path': str(path), 'bytes': path.stat().st_size,
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'vertices': len(vertices)-1, 'faces': len(faces), 'colors': list(colors.values())}

def signature(face):
    color, points = face
    return (color, tuple(sorted(points)))

def extract(faces, x, y, radius):
    return [f for f in faces if all(abs(p[0]-x) <= radius and abs(p[1]-y) <= radius for p in f[1])]

def sections(faces, z, origin, keep_points=False):
    # Tessellation-only diagnostic, 10 nm point hashing joins adjacent triangle
    # section endpoints; it does not change any CAD coordinates or audit rules.
    parents, actual = {}, {}
    def key(p):
        q=tuple(round(v,8) for v in p)
        actual.setdefault(q,p)
        return q
    def find(a):
        parents.setdefault(a,a)
        if parents[a]!=a:
            parents[a]=find(parents[a])
        return parents[a]
    def merge(a,b):
        parents[find(b)]=find(a)
    for color,points in faces:
        if len(points)!=3:
            raise ValueError('Expected triangle faces')
        intersections=[]
        for i,p in enumerate(points):
            q=points[(i+1)%3]
            if (p[2]<z<q[2]) or (q[2]<z<p[2]):
                a=(z-p[2])/(q[2]-p[2])
                intersections.append((p[0]+a*(q[0]-p[0]),p[1]+a*(q[1]-p[1]),z))
        if len(intersections)==2:
            a,b=map(key,intersections)
            merge((color,a),(color,b))
    groups=defaultdict(list)
    for color,p in parents:
        groups[find((color,p))].append(actual[p])
    result=[]
    for (color,_),ps in groups.items():
        b=bbox(ps)
        piece={'color':color,'bbox_local_mm':[b[k]-(origin[k%3] if k%3<2 else 0) for k in range(6)],
               'center_local_xy_mm':[(b[k]+b[k+3])/2-origin[k] for k in range(2)],'points':len(ps)}
        if keep_points:
            piece['points_local_xy_mm']=[[p[k]-origin[k] for k in range(2)] for p in ps]
        result.append(piece)
    return sorted(result,key=lambda g:(g['color'],g['center_local_xy_mm']))

def inspect(faces, origin):
    # Connected components are based on exact coordinates, not OBJ vertex IDs;
    # native tessellation can duplicate vertices at smooth/material seams.
    parents = {}
    def find(a):
        parents.setdefault(a, a)
        if parents[a] != a:
            parents[a] = find(parents[a])
        return parents[a]
    def merge(a, b):
        parents[find(b)] = find(a)
    for color, points in faces:
        for p in points:
            merge((color, points[0]), (color, p))
    groups = defaultdict(list)
    for color, p in parents:
        groups[find((color,p))].append(p)
    pieces = []
    for (color,_), points in groups.items():
        b = bbox(points)
        pieces.append({'color':color,'bbox_world_mm':b,'bbox_local_mm':[b[k] - (origin[k%3] if k%3 < 2 else 0) for k in range(6)],
                       'center_world_mm':[(b[k]+b[k+3])/2 for k in range(3)], 'vertices':len(points)})
    points = [p for color, ps in faces for p in ps]
    b = bbox(points)
    mats = defaultdict(list)
    for color, ps in faces:
        mats[color].extend(ps)
    levels=Counter(round(p[2],9) for p in set(points))
    return {'faces':len(faces), 'bbox_world_mm':b,
            'bbox_local_mm':[b[k] - (origin[k%3] if k%3 < 2 else 0) for k in range(6)],
            'size_xyz_mm':[b[k+3]-b[k] for k in range(3)],
            'center_local_xy_mm':[(b[k]+b[k+3])/2-origin[k] for k in range(2)],
            'color_bboxes_world_mm':[{ 'color':c,'bbox':bbox(ps)} for c,ps in mats.items()],
            'connected_color_pieces':sorted(pieces,key=lambda p:(p['color'],p['center_world_mm'])),
            'dominant_vertex_z_planes_mm':levels.most_common(35),
            'horizontal_sections_mm':{str(z):sections(faces,z,origin) for z in [-1.,-.5,-.351,-.349,-.05,.05,.1,.5,.9,1.0,1.5,1.85,1.9,2.0,2.1,2.5,3.0,3.5,4.0]}}

def main():
    parts = {p['ref']:p for p in json.loads((HERE/'components-437.json').read_text(encoding='utf-8'))}
    old, oldmeta = parse(OLD)
    counts = Counter(signature(f) for f in old)
    del old
    new, newmeta = parse(NEW)
    added = []
    for face in new:
        sig = signature(face)
        if counts[sig]:
            counts[sig] -= 1
        else:
            added.append(face)
    removed = sum(counts.values())
    assert removed == 0, f'Unexpected old faces not reproduced exactly: {removed}'
    out = {'schema':'stm32-native-header-default-mesh-analysis-v1','before':oldmeta,'after':newmeta,
           'exact_color_coordinate_face_multiset_removed':removed, 'new_faces':len(added),
           'limitations':['Native OBJ contains no reference or source model IDs. Attribution uses exact unchanged-face subtraction and isolated geometric regions.',
                          'Missing native Transform can auto-fit size. Observed bbox is not yet intrinsic model size.'], 'isolated_models':{}}
    for ref,radius in [('J1',12),*[(f'J{i}',5) for i in range(2,18)],('J18',12)]:
        p=parts[ref]
        selected=extract(added,p['x_mm'],p['y_mm'],radius)
        out['isolated_models'][ref]={'source_position_xy_mm':[p['x_mm'],p['y_mm']],
                                     'selection_radius_mm':radius,**inspect(selected,[p['x_mm'],p['y_mm']])}
    assert sum(m['faces'] for m in out['isolated_models'].values())==len(added)
    assert all(out['isolated_models'][f'J{i}']['faces']==2221 for i in range(2,18))
    target=OUT/'audits/header-default-379-all18.json'
    assert not target.exists()
    target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(target),'new_faces':len(added),'removed':removed,
                      'models':{r:{k:m[k] for k in ['faces','bbox_local_mm','size_xyz_mm','center_local_xy_mm']} for r,m in out['isolated_models'].items()}}))

if __name__ == '__main__':
    main()
