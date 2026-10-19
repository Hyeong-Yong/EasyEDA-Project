import hashlib
import json
from pathlib import Path
from inspect_standard_meshes import load, NEW

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
vertices, faces, _ = load(NEW)
pilot = json.loads((ROOT/'audits/u3-default-mesh-pilot.json').read_text())
cx,cy = pilot['after']['center_xyz_mm'][:2]
ids = set()
for material,block,face in faces:
    if material=='mtl3' and all(abs(vertices[i][0]-cx)<1 and abs(vertices[i][1]-cy)<1.4 and abs(vertices[i][2])<.001 for i in face):
        ids.update(face)
points = sorted(set(tuple(vertices[i][k]-(cx if k==0 else cy if k==1 else 0) for k in range(3)) for i in ids))
scale = (pilot['after']['metal_connected_pieces'][0]['center_xy_mm'][1]-pilot['after']['metal_connected_pieces'][1]['center_xy_mm'][1])/.95
report = {'schema':'stm32-u3-exposed-pad-chamfer-geometry-v1', 'native_calls':0,
          'export':NEW.name, 'export_sha256':hashlib.sha256(NEW.read_bytes()).hexdigest(),
          'measurement_method':'Material mtl3 faces on z=0 within isolated central exposed-pad window, excluding six perimeter terminals by |x-center|<1mm.',
          'model_center_world_xy_mm':[cx,cy], 'auto_scale_from_known_0_95_pitch':scale,
          'raw_centered_exposed_pad_vertices_mm':points,
          'intrinsic_centered_exposed_pad_vertices_mm':[[v/scale for v in p] for p in points],
          'vertex_count':len(points), 'chamfered_corner':'negative X, positive Y',
          'interpretation':'An EP corner chamfer corroborates the selected generic DFN pin1 corner at (-X,+Y), matching source canonical. This is a geometric corner inference, not exact-ST1L05 drawing certification.'}
assert len(points)==5
(ROOT/'audits/u3-exposed-pad-chamfer.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
