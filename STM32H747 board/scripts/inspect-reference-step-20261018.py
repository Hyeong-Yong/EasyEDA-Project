"""Read-only AP214 assembly audit; never loads CAD applications or modifies input.

Reported boxes are vertex sample bounds, NOT certified analytic BRep bounds.
Curved extrema between topological vertices can exceed these bounds.
"""
import collections
import hashlib
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "보드 자료" / "MCU_BOARD.step"
DEST = ROOT / "output" / "3d-models-20261018" / "reference-step-audit.json"
blob = SOURCE.read_bytes()
src = blob.decode("utf-8")
entities = {int(m[1]): m[2].strip() for m in re.finditer(r"#(\d+)\s*=\s*(.*?);", src, re.S)}

def refs(e):
    return [int(v) for v in re.findall(r"#(\d+)", e)]

def strings(e):
    return [v.replace("''", "'") for v in re.findall(r"'((?:[^']|'')*)'", e)]

def vector(n):
    body = entities[n]
    return [float(v) for v in re.search(r",\s*\(([^()]*)\)\s*\)$", body)[1].split(",")]

def cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

def norm(v):
    d = math.sqrt(sum(x*x for x in v))
    return [x/d for x in v]

def frame(n):
    r = refs(entities[n])
    origin = vector(r[0])
    z = norm(vector(r[1])) if len(r) > 1 else [0, 0, 1]
    x0 = vector(r[2]) if len(r) > 2 else [1, 0, 0]
    proj = sum(a*b for a, b in zip(x0, z))
    x = norm([a-proj*b for a, b in zip(x0, z)])
    y = cross(z, x)
    return [[x[i], y[i], z[i], origin[i]] for i in range(3)] + [[0, 0, 0, 1]]

IDENTITY = [[int(i == j) for j in range(4)] for i in range(4)]

def multiply(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]

def invert_rigid(a):
    r = [[a[j][i] for j in range(3)] for i in range(3)]
    return [r[i] + [-sum(r[i][k]*a[k][3] for k in range(3))] for i in range(3)] + [[0, 0, 0, 1]]

def transformed(t, v):
    return [sum(t[i][k]*v[k] for k in range(3)) + t[i][3] for i in range(3)]

products = {n: strings(e)[0] for n, e in entities.items() if e.startswith("PRODUCT(")}
pd_names = {}
for n, e in entities.items():
    if e.startswith("PRODUCT_DEFINITION("):
        formation = refs(e)[0]
        pd_names[n] = products[refs(entities[formation])[0]]

pd_shape = {}
for n, e in entities.items():
    if e.startswith("SHAPE_DEFINITION_REPRESENTATION("):
        pds, shape = refs(e)
        pd = refs(entities[pds])[0]
        pd_shape[pd] = shape

occurrences = {}
children = collections.defaultdict(list)
for n, e in entities.items():
    if e.startswith("NEXT_ASSEMBLY_USAGE_OCCURRENCE("):
        parent, child = refs(e)
        occurrence = dict(id=n, ref=strings(e)[1], parent_pd=parent, child_pd=child,
                          product=pd_names[child], transform=IDENTITY)
        occurrences[n] = occurrence
        children[parent].append(occurrence)

for n, e in entities.items():
    if e.startswith("CONTEXT_DEPENDENT_SHAPE_REPRESENTATION("):
        rr, pds = refs(e)
        occ = refs(entities[pds])[0]
        trans = int(re.search(r"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION\(#(\d+)\)", entities[rr])[1])
        a, b = refs(entities[trans])
        occurrences[occ]["transform"] = multiply(frame(b), invert_rigid(frame(a)))
        occurrences[occ]["transform_entity"] = trans
        occurrences[occ]["source_frame_entity"] = a
        occurrences[occ]["target_frame_entity"] = b

def closure(start):
    visited, todo = set(), [start]
    while todo:
        n = todo.pop()
        if n in visited:
            continue
        visited.add(n)
        todo.extend(refs(entities[n]))
    return visited

def own_vertices(pd):
    found = closure(pd_shape[pd])
    vertex_ids = [n for n in found if entities[n].startswith("VERTEX_POINT(")]
    return [vector(refs(entities[n])[0]) for n in vertex_ids], sum(entities[n].startswith("MANIFOLD_SOLID_BREP(") for n in found)

own_cache = {pd: own_vertices(pd) for pd in pd_names}

def assembly_vertices(pd, transform=IDENTITY):
    points = [transformed(transform, v) for v in own_cache[pd][0]]
    solids = own_cache[pd][1]
    for occurrence in children[pd]:
        nested, count = assembly_vertices(occurrence["child_pd"], multiply(transform, occurrence["transform"]))
        points.extend(nested)
        solids += count
    return points, solids

def bounds(points):
    if not points:
        return None
    lo = [min(v[i] for v in points) for i in range(3)]
    hi = [max(v[i] for v in points) for i in range(3)]
    return dict(min_mm=lo, max_mm=hi, span_mm=[b-a for a, b in zip(lo, hi)])

root_pd = next(pd for pd, name in pd_names.items() if name == "MCU_BOARD 1")
catalog = []
for pd, name in pd_names.items():
    pts, count = assembly_vertices(pd) if pd != root_pd else ([], 0)
    catalog.append(dict(product=name, product_definition_entity=pd,
                        shape_representation_entity=pd_shape[pd], nested_products=[o["product"] for o in children[pd]],
                        direct_occurrence_refs=[o["ref"] for o in occurrences.values() if o["child_pd"] == pd],
                        solid_occurrences=count, vertex_sample_count=len(pts),
                        local_vertex_sample_bounds=bounds(pts)))

top = []
for occurrence in children[root_pd]:
    points, solids = assembly_vertices(occurrence["child_pd"], occurrence["transform"])
    top.append(dict(occurrence, solid_occurrences=solids, world_vertex_sample_bounds=bounds(points)))

result = dict(source=str(SOURCE), source_bytes=len(blob), source_sha256=hashlib.sha256(blob).hexdigest(),
              header=src[:src.index("DATA;")], entities=len(entities), products=len(products),
              assembly_occurrences=len(occurrences), top_level_occurrence_count=len(top),
              conclusions=["Historical STEP contains individual named component products and a separate PCB product.",
                           "This audit does not reuse or modify the historical PCB or any original geometry.",
                           "Product names prove historical model labels, not present-day manufacturer equivalence.",
                           "Vertex sample bounds are not certified full analytic BRep bounding boxes.",
                           "Transforms map each child product's local coordinate frame into its parent frame in millimetres."],
              product_catalog=catalog, top_level_occurrences=top)
DEST.parent.mkdir(parents=True, exist_ok=True)
DEST.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: result[k] for k in ["source_sha256", "entities", "products", "assembly_occurrences", "top_level_occurrence_count"]}))
for item in top:
    if re.fullmatch(r"(?:CN[1-4]|J1|J18|TR1|SW1|L1|C41|J16)", item["ref"]):
        cat = next(c for c in catalog if c["product_definition_entity"] == item["child_pd"])
        print(json.dumps(dict(ref=item["ref"], product=item["product"], solids=item["solid_occurrences"],
                             local_vertex_sample_bounds=cat["local_vertex_sample_bounds"],
                             transform=item["transform"]), ensure_ascii=False))
