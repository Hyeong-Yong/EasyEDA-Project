"""Read-only differential isolation of applied 27 models and two new defaults."""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from inspect_standard_meshes import load, face_key, bounds

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OLD = ROOT/'STM32H747_standards_default_405_STM32H747_standards_default_405'
NEW = ROOT/'STM32H747_std27_j12_switch_xfmr_407_STM32H747_std27_j12_switch_xfmr_407'
inv = {p['ref']:p for p in json.loads((ROOT/'inventory/components-437.json').read_text())}
registry = json.loads((ROOT/'standard-model-candidate-registry.json').read_text())
targets = {p['ref']:p for p in registry['targets']}
for ref in ['TR1','SW1']+[f'J{i}' for i in range(2,18)]:
    targets[ref] = {'family':inv[ref]['package_group']}
old_v, old_f, _ = load(OLD)
baseline = Counter(face_key(ids,old_v) for _,_,ids in old_f)
del old_v, old_f
vertices, faces, materials = load(NEW)
added = []
common = 0
for f in faces:
    key = face_key(f[2],vertices)
    if baseline[key]:
        baseline[key] -= 1
        common += 1
    else:
        added.append(f)
removed = sum(baseline.values())
parent = {}
def find(a):
    parent.setdefault(a,a)
    if parent[a] != a:
        parent[a] = find(parent[a])
    return parent[a]
for _,_,ids in added:
    for i in ids:
        parent[find(i)] = find(ids[0])
by_piece = defaultdict(list)
for f in added:
    by_piece[find(f[2][0])].append(f)
piece_records = []
model_faces = defaultdict(list)
for piece_root,fs in by_piece.items():
    ids = sorted({i for _,_,ff in fs for i in ff})
    box = bounds([vertices[i] for i in ids])
    center = [(box[k]+box[k+3])/2 for k in range(3)]
    distance,ref = min((math.dist(center[:2],[inv[r]['x_mm'],inv[r]['y_mm']]),r) for r in targets)
    model_faces[ref].extend(fs)
    piece_records.append({'ref':ref,'vertex_min':ids[0],'vertex_max':ids[-1],'faces':len(fs),'bbox_mm':box,
                          'center_xyz_mm':center,'size_xyz_mm':[box[k+3]-box[k] for k in range(3)],'materials':dict(Counter(m for m,_,_ in fs))})
features = {}
for ref,fs in model_faces.items():
    p = inv[ref]
    angle = math.radians(p['rotation_deg'])
    def local(i):
        x,y,z = vertices[i]
        x -= p['x_mm']
        y -= p['y_mm']
        return (x*math.cos(angle)+y*math.sin(angle),-x*math.sin(angle)+y*math.cos(angle),z)
    ids = {i for _,_,ff in fs for i in ff}
    box = bounds([local(i) for i in ids])
    center = [(box[k]+box[k+3])/2 for k in range(3)]
    material_features = {}
    for mat in {m for m,_,_ in fs}:
        mf = [ff for m,_,ff in fs if m==mat]
        par = {}
        def mfind(i):
            par.setdefault(i,i)
            if par[i] != i:
                par[i] = mfind(par[i])
            return par[i]
        for ff in mf:
            for i in ff:
                par[mfind(i)] = mfind(ff[0])
        m_groups = defaultdict(set)
        counts = Counter()
        for ff in mf:
            k = mfind(ff[0])
            m_groups[k].update(ff)
            counts[k] += 1
        pieces = []
        for k,mids in m_groups.items():
            mb = bounds([local(i) for i in mids])
            pieces.append({'faces':counts[k],'vertices':len(mids),'bbox_local_mm':mb,
                           'center_from_model_bbox_mm':[(mb[j]+mb[j+3])/2-center[j] for j in range(3)],
                           'size_xyz_mm':[mb[j+3]-mb[j] for j in range(3)]})
        material_features[mat] = {'color':materials[mat],'bbox_local_mm':bounds([local(i) for ff in mf for i in ff]),'pieces':pieces}
    features[ref] = {'family':targets[ref]['family'],'face_count':len(fs),'bbox_component_local_mm':box,
                     'mesh_center_component_local_mm':center,'size_xyz_component_local_mm':[box[k+3]-box[k] for k in range(3)],
                     'materials':material_features}
report = {'source_export':NEW.name,'source_export_sha256':hashlib.sha256(NEW.read_bytes()).hexdigest(),
          'baseline':OLD.name,'common_faces':common,'removed_faces':removed,'added_faces':len(added),
          'pieces':sorted(piece_records,key=lambda p:p['vertex_min']),'features':features}
(HERE/'standard407-isolated-geometry.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'output':str(HERE/'standard407-isolated-geometry.json'),'common':common,'removed':removed,'added':len(added),
                  'refs':{r:{'faces':f['face_count'],'size':f['size_xyz_component_local_mm']} for r,f in features.items()}},indent=2))
