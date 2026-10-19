"""Compare native OBJ exports in the isolated U3 region; read-only CAD use."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
parts = json.loads((HERE / "components-437.json").read_text(encoding="utf-8"))
u3 = next(x for x in parts if x["ref"] == "U3")
x, y = u3["x_mm"], u3["y_mm"]


def bb(points):
    return [min(p[k] for p in points) for k in range(3)] + [max(p[k] for p in points) for k in range(3)]


def inspect(filename):
    path = OUT / filename
    with zipfile.ZipFile(path) as z:
        source = z.read(next(n for n in z.namelist() if n.endswith(".obj"))).decode()
    vertices = [None]
    blocks, candidates = [], []
    for line in source.splitlines():
        t = line.split()
        if not t:
            continue
        if t[0] == "v":
            vertices.append(tuple(float(v) for v in t[1:4]))
        elif t[0] == "usemtl":
            blocks.append({"material": t[1], "vertices": set()})
        elif t[0] == "f":
            ids = [int(s.split("/")[0]) for s in t[1:]]
            blocks[-1]["vertices"].update(ids)
            pts = [vertices[i] for i in ids]
            if all(abs(p[0] - x) < 1.85 and abs(p[1] - y) < 1.85 and -.01 <= p[2] < 2 for p in pts):
                candidates.append((len(blocks) - 1, ids))
    boards = set()
    for i, b in enumerate(blocks):
        box = bb([vertices[j] for j in b["vertices"]])
        if box[3] - box[0] > 50 and box[4] - box[1] > 50:
            boards.add(i)
    assert len(boards) == 1
    selected = [(i, ids) for i, ids in candidates if i not in boards]
    if not selected:
        return {"export": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nonboard_faces_in_U3_region": 0}
    positions = [vertices[j] for i, ids in selected for j in ids]
    box = bb(positions)
    mats = defaultdict(list)
    for i, ids in selected:
        mats[blocks[i]["material"]].extend(vertices[j] for j in ids)
    # White lead metal is mtl3 in this particular native export. The reference
    # labels are not embedded in OBJ, so row identification is spatial geometry.
    parent = {}
    def find(a):
        parent.setdefault(a, a)
        if parent[a] != a:
            parent[a] = find(parent[a])
        return parent[a]
    def merge(a, b):
        parent[find(b)] = find(a)
    for i, ids in selected:
        if blocks[i]["material"] != "mtl3":
            continue
        for j in ids:
            merge(ids[0], j)
    connected = defaultdict(list)
    for j in parent:
        connected[find(j)].append(vertices[j])
    pads = []
    for pts in connected.values():
        boxp = bb(pts)
        pads.append({"bbox_mm": boxp, "center_xy_mm": [(boxp[0] + boxp[3]) / 2, (boxp[1] + boxp[4]) / 2]})
    return {"export": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nonboard_faces_in_U3_region": len(selected),
            "bbox_mm": box, "size_xyz_mm": [box[k+3] - box[k] for k in range(3)],
            "center_xyz_mm": [(box[k] + box[k+3]) / 2 for k in range(3)],
            "center_offset_from_U3_xy_mm": [(box[0] + box[3]) / 2 - x, (box[1] + box[4]) / 2 - y],
            "material_bboxes_mm": {m: bb(p) for m, p in mats.items()}, "metal_connected_pieces": pads}


old = inspect("STM32H747_passives_337_STM32H747_passives_337")
new = inspect("STM32H747_u3_default_pilot_361_STM32H747_u3_default_pilot_361")
assert old["nonboard_faces_in_U3_region"] == 0 and new["nonboard_faces_in_U3_region"] > 0
report = {"schema": "stm32-u3-native-default-mesh-pilot-v1", "default_model_renders_when_transform_omitted": True,
          "model_uuid_from_root_binding": "2351360292744dbc91885e7d69b823ec", "source_U3_position_mm": [x, y],
          "isolated_spatial_window_mm": [x-1.85, y-1.85, x+1.85, y+1.85], "before": old, "after": new,
          "limitations": ["OBJ omits source model UUID and reference labels; pilot binding metadata is supplied by the root's native call.",
                          "The default DFN mesh is rendered, but its center is shifted about -0.25mm in X and full mesh size is about3.1x3.1x1.033mm. Rendering is not final pad registration approval.",
                          "U3 region was chosen to exclude nearby passives; board faces were removed via the single board-wide material block.",
                          "Adjacent models sharing a material can be merged into one usemtl block. A block is not a component; per-face spatial extraction is required for this pilot."]}
target = OUT / "audits/u3-default-mesh-pilot.json"
assert not target.exists()
target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"renders": True, "report": str(target), "after": new}))
