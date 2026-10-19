"""Read-only OBJ/STEP geometry audit; writes only new scoped audit artifacts."""
from pathlib import Path
from collections import Counter, defaultdict
import argparse
import hashlib
import json
import math
import struct
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "3d-models-20261018"
sys.path.insert(0, str(ROOT / ".tools" / "ocp-7.9.3.1.1"))
from OCP.STEPControl import STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.gp import gp_Pnt, gp_Pln, gp_Dir
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib


def file_info(path):
    return dict(path=str(path), bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def triangle_key(triangle):
    quantized = sorted(tuple(round(v * 1e6) for v in p) for p in triangle)
    return struct.pack("<9q", *(v for p in quantized for v in p))


def iter_triangles(path):
    vertices = [None]
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".obj")]
        if len(names) != 1:
            raise RuntimeError("Expected exactly one native OBJ member")
        with archive.open(names[0]) as stream:
            for raw in stream:
                if raw.startswith(b"v "):
                    vertices.append(tuple(map(float, raw.split()[1:4])))
                elif raw.startswith(b"f "):
                    indices = [int(v.split(b"/")[0]) for v in raw.split()[1:]]
                    if len(indices) != 3:
                        raise RuntimeError("Native OBJ face is not triangular")
                    yield tuple(vertices[i] if i > 0 else vertices[len(vertices)+i] for i in indices)


def bbox(points):
    lower = [min(p[i] for p in points) for i in range(3)]
    upper = [max(p[i] for p in points) for i in range(3)]
    return dict(min_mm=lower, max_mm=upper, span_mm=[upper[i]-lower[i] for i in range(3)])


def group_segments(segments):
    groups, adjacency, points = [], defaultdict(set), {}
    for a, b in segments:
        ka, kb = tuple(round(x, 5) for x in a), tuple(round(x, 5) for x in b)
        if ka == kb:
            continue
        adjacency[ka].add(kb)
        adjacency[kb].add(ka)
        points.setdefault(ka, []).append(a)
        points.setdefault(kb, []).append(b)
    while adjacency:
        start = next(iter(adjacency))
        pending, reached = [start], set()
        while pending:
            node = pending.pop()
            if node in reached:
                continue
            reached.add(node)
            pending.extend(adjacency.get(node, ()))
        samples = [p for node in reached for p in points[node]]
        bounds = bbox(samples)
        groups.append(dict(bbox=bounds, xy_center_mm=[(bounds["min_mm"][i]+bounds["max_mm"][i])/2 for i in range(2)]))
        for node in reached:
            adjacency.pop(node, None)
    return sorted(groups, key=lambda a: tuple(a["xy_center_mm"]))


def mesh_section(triangles, z):
    segments = []
    for triangle in triangles:
        intersections = []
        for i in range(3):
            a, b = triangle[i], triangle[(i+1) % 3]
            da, db = a[2]-z, b[2]-z
            if abs(da) < 1e-10:
                intersections.append(a)
            if da*db < 0:
                t = da/(da-db)
                intersections.append(tuple(a[j]+t*(b[j]-a[j]) for j in range(3)))
        unique = {tuple(round(v, 9) for v in p): p for p in intersections}
        if len(unique) == 2:
            segments.append(tuple(unique.values()))
    return group_segments(segments)


def kernel_section(shape, z):
    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), False)
    section.Build()
    if not section.IsDone():
        raise RuntimeError("OCCT section failed")
    ex, edges = TopExp_Explorer(section.Shape(), TopAbs_EDGE), []
    while ex.More():
        edge = TopoDS.Edge_s(ex.Current())
        a, b = TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)
        if not a.IsNull() and not b.IsNull():
            ap, bp = BRep_Tool.Pnt_s(a), BRep_Tool.Pnt_s(b)
            endpoints = {tuple(round(v,5) for v in [ap.X(),ap.Y(),ap.Z()]), tuple(round(v,5) for v in [bp.X(),bp.Y(),bp.Z()])}
            edges.append((edge,endpoints))
        ex.Next()
    groups = []
    while edges:
        seed, endpoints = edges.pop()
        members, changed = [seed], True
        while changed:
            changed = False
            for i in range(len(edges)-1,-1,-1):
                edge, other = edges[i]
                if endpoints.intersection(other):
                    members.append(edge)
                    endpoints.update(other)
                    edges.pop(i)
                    changed = True
        box = Bnd_Box()
        for edge in members:
            BRepBndLib.AddOptimal_s(edge,box,False,False)
        values = list(box.Get())
        groups.append(dict(bbox=dict(min_mm=values[:3],max_mm=values[3:],span_mm=[values[i+3]-values[i] for i in range(3)]),xy_center_mm=[(values[i]+values[i+3])/2 for i in range(2)]))
    return sorted(groups,key=lambda a:tuple(a['xy_center_mm']))


def triangle_area(a, b, c):
    u, v = [b[i]-a[i] for i in range(3)], [c[i]-a[i] for i in range(3)]
    cross = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    return math.sqrt(sum(x*x for x in cross))/2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", default="STM32H747_final412_STM32H747_final412")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--viewer-registration", action="store_true")
    args = parser.parse_args()
    current = OUT / args.current
    baseline = OUT / "STM32H747_calibrated407_STM32H747_calibrated407"
    if not current.is_file():
        raise RuntimeError("Native export is not present; do not infer completion")
    manifest_path = ROOT / "native-project" / "model-library" / "STM32H747_3D_asset_manifest_20261018.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {a["ref"]: a for a in manifest["entries"] if not a["optional"] and (not args.pilot or a["ref"] == "CN1")}
    remaining = Counter(triangle_key(t) for t in iter_triangles(baseline))
    base_count = sum(remaining.values())
    triangles, unmatched, face_count, matched = defaultdict(list), [], 0, 0
    for triangle in iter_triangles(current):
        face_count += 1
        key = triangle_key(triangle)
        if remaining[key]:
            remaining[key] -= 1
            matched += 1
            continue
        center = [sum(p[i] for p in triangle)/3 for i in range(3)]
        found = []
        for ref, a in expected.items():
            origin = a["currentComponentOriginMm"]+[0]
            limits = a["canonicalBoundsMm"]
            if all(limits["min_mm"][i]+origin[i]-.003 <= center[i] <= limits["max_mm"][i]+origin[i]+.003 for i in range(3)):
                found.append(ref)
        if len(found) != 1:
            unmatched.append(triangle)
        else:
            triangles[found[0]].append(triangle)
    missing = sum(remaining.values())
    del remaining
    report = dict(schema="stm32-local5-native-canonical-geometry-v1", native_calls=0,
                  baseline=file_info(baseline), current=file_info(current),
                  asset_manifest=file_info(manifest_path), baseline_faces=base_count,
                  current_faces=face_count, matched_baseline_faces=matched,
                  missing_baseline_faces=missing, unmatched_added_faces=len(unmatched),
                  coordinate_rounding_mm=1e-6, component_models={},
                  interpretation="Geometric registration/model rendering verification, not manufacturing fit certification, electrical QA or persistence proof.")
    all_ok = missing == 0 and not unmatched and len(triangles) == len(expected)
    for ref, asset in expected.items():
        actual_triangles = triangles[ref]
        points = sorted({p for t in actual_triangles for p in t})
        if not points:
            raise RuntimeError("No rendered added triangles for " + ref)
        actual_bbox = bbox(points)
        origin = asset["currentComponentOriginMm"]+[0]
        expected_bbox = {side:[asset["canonicalBoundsMm"][side][i]+origin[i] for i in range(3)] for side in ["min_mm","max_mm"]}
        bbox_error = max(abs(actual_bbox[side][i]-expected_bbox[side][i]) for side in expected_bbox for i in range(3))
        local = [tuple(p[i]-origin[i] for i in range(3)) for p in points]
        local_triangles = [tuple(tuple(p[i]-origin[i] for i in range(3)) for p in t) for t in actual_triangles]
        step = Path(asset["flatAssetAbsolutePath"])
        if file_info(step)["sha256"] != asset["sha256"]:
            raise RuntimeError("Canonical STEP provenance mismatch")
        reader = STEPControl_Reader()
        if reader.ReadFile(str(step)) != IFSelect_RetDone or not reader.TransferRoots():
            raise RuntimeError("Cannot read preserved canonical STEP")
        shape = reader.OneShape()
        sample_indices = list(range(len(local))) if args.viewer_registration else sorted({round(i*(len(local)-1)/min(300,len(local)-1)) for i in range(min(300,len(local)-1)+1)})
        distances = []
        for index in sample_indices:
            point = BRepBuilderAPI_MakeVertex(gp_Pnt(*local[index])).Vertex()
            distance = BRepExtrema_DistShapeShape(point, shape)
            distance.Perform()
            if not distance.IsDone():
                raise RuntimeError("OCCT point-to-source distance failed")
            distances.append(distance.Value())
        z = .05 if ref == "L1" else -.5
        actual_sections, source_sections = mesh_section(local_triangles, z), kernel_section(shape, z)
        section_errors = []
        available = list(source_sections)
        for section in actual_sections:
            if not available:
                section_errors.append(1e9)
                continue
            nearest = min(available, key=lambda q: math.dist(q["xy_center_mm"],section["xy_center_mm"]))
            section_errors.append(math.dist(nearest["xy_center_mm"],section["xy_center_mm"]))
            available.remove(nearest)
        section_ok = len(actual_sections) == len(source_sections) and bool(section_errors) and max(section_errors)<.01
        actual_union = bbox([p for section in actual_sections for p in [section['bbox']['min_mm'],section['bbox']['max_mm']]])
        source_union = bbox([p for section in source_sections for p in [section['bbox']['min_mm'],section['bbox']['max_mm']]])
        section_union_error = max(abs(actual_union[side][i]-source_union[side][i]) for side in ['min_mm','max_mm'] for i in range(2))
        seat_triangles = [t for t in local_triangles if max(p[2] for p in t)-min(p[2] for p in t)<.0001 and abs(sum(p[2] for p in t)/3)<.001]
        seat_area = sum(triangle_area(*t) for t in seat_triangles)
        seat_z_range = [min(p[2] for t in seat_triangles for p in t),max(p[2] for t in seat_triangles for p in t)] if seat_triangles else None
        strict_ok = bbox_error < .02 and max(distances) < .002 and section_ok and bool(seat_triangles)
        viewer_sections_ok = section_union_error < .05 and (ref == 'L1' or (len(actual_sections) == len(source_sections) and max(section_errors)<.05))
        pin_min_z_error = abs(actual_bbox['min_mm'][2]-asset['canonicalMinZmm'])
        viewer_ok = bbox_error < .03 and max(distances) < .1 and viewer_sections_ok and pin_min_z_error < .001
        ok = viewer_ok if args.viewer_registration else strict_ok
        all_ok &= ok
        report["component_models"][ref] = dict(passed=ok, exact_analytic_fidelity_passed=strict_ok,
            exact_mechanical_fidelity_proven=False, mechanical_fit_certified=False,
            viewer_registration_passed=viewer_ok, viewer_placement_passed=viewer_ok, component_id=asset["componentId"],
            added_triangles=len(actual_triangles), unique_vertices=len(points), source_step=file_info(step),
            actual_board_bbox_mm=actual_bbox, expected_board_bbox_mm=expected_bbox,
            maximum_bbox_extreme_error_mm=bbox_error, source_surface_sample_count=len(distances),
            source_surface_max_point_distance_mm=max(distances),
            section_z_mm=z, native_section_groups=actual_sections, canonical_section_groups=source_sections,
            maximum_section_center_error_mm=max(section_errors) if section_errors and len(actual_sections)==len(source_sections) else None,
            maximum_section_union_bbox_error_mm=section_union_error,
            section_groups_match=section_ok, seat_z_range_mm=seat_z_range, seat_triangle_area_mm2=seat_area,
            pin_min_z_error_mm=pin_min_z_error,
            native_tessellation_limit="Native STEP renderer simplifies/perturbs small surfaces and does not preserve analytic surface or seating-plane fidelity. Distances are measured native vertex-to-source-surface deviations, not a bidirectional complete Hausdorff bound.",
            canonical_expected_port_outward=({"CN1":"+X","CN2":"+X","CN3":"+X","CN4":"+Y"}.get(ref,"not applicable")),
            outward_evidence="Per-reference canonical rigid transform verified by matching non-symmetric pin sections, native full bounds and analytic surface points; no additional rotation applied.",
            relation=asset["relation"], limitations=asset["limitations"])
        print(json.dumps({"ref":ref,"passed":ok,"added_triangles":len(actual_triangles),"bbox_error_mm":bbox_error,"surface_max_mm":max(distances),"sections":len(actual_sections),"source_sections":len(source_sections),"section_error_mm":max(section_errors) if section_errors else None,"seat_z_range_mm":seat_z_range}),flush=True)
    report["passed"] = bool(all_ok)
    if args.viewer_registration:
        report['criterion'] = 'VIEWER_REGISTRATION_ONLY_NOT_EXACT_MECHANICAL_FIDELITY'
        report['viewer_placement_passed'] = bool(all_ok)
        report['exact_mechanical_fidelity_proven'] = False
        report['mechanical_fit_certified'] = False
        report['explicit_viewer_thresholds_mm'] = dict(full_bbox_extreme=.03,native_vertex_to_analytic_surface=.1,pin_section_center_and_union=.05,pin_minZ=.001)
        report['threshold_interpretation'] = 'These deliberately declared visual-assembly tolerances detect unit/pose/registration errors. They are not manufacturing tolerances and do not override the separately failed strict analytic fidelity checks.'
        report['exact_analytic_fidelity_passed'] = all(a['exact_analytic_fidelity_passed'] for a in report['component_models'].values())
    output = OUT / "audits" / ("local-cn1-native-pilot408-geometry.json" if args.pilot else ("local5-native-final412-registration.json" if args.viewer_registration else "local5-native-final412-geometry.json"))
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"report":str(output),"missing_baseline_faces":missing,"unmatched_added_faces":len(unmatched),"current_sha256":report["current"]["sha256"]}),flush=True)
    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
