"""Offline, tightly bounded four-corner mounting-hole/plane-void candidate.

Does not call EasyEDA or modify a native project.  Existing corner voids are
rounded, perimeter-connected notches, not separate circle contours.  Restoring
the exact missing native notch before cutting a new circle avoids leaving
microscopic crescents from replacing the old shape with an ideal circle.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from pathlib import Path

from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_multilayer_drc_pass_20261016.epro2"
OUT = ROOT / "output/candidates/corner-holes-inward"
MM = 0.0254
RADIUS_MM = 3.6005
LOCAL_HALFSPAN_MM = 4.0
GRID_MIL = 0.0001
QUANT_TOL_MIL = 0.00015
AREA_TOL_MIL2 = 0.25
HOLES = (
    ("3169127ef956834e", (4.0, 4.0), (5.0, 5.0)),
    ("a5552d25aa4796c7", (4.0, 150.0), (5.0, 149.0)),
    ("e02b2dd3db20ee49", (96.0, 4.0), (95.0, 5.0)),
    ("26b28bb992d2c564", (96.0, 150.0), (95.0, 149.0)),
)
FILLS = {
    "e680230ef8d2c5dd": 1,
    "f9e70adc3ac35fbd": 15,
    "41fd0322eb2cc785": 16,
    "b99d5f8f2cae6046": 17,
    "ef12098577a13cc7": 18,
    "2fb535085249015d": 2,
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def helper():
    spec = importlib.util.spec_from_file_location(
        "corner_fill_helper", ROOT / "scripts/plan-multilayer-fill-clearance.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def record(m, line):
    h, b = line.split("||", 1)
    b = b.removesuffix("|")
    return m.NativeRecord(json.loads(h), json.loads(b) if b else {})


def load_pads(m, rows):
    attrs = m.component_attributes(rows)
    components = {r.record_id: r for r in rows if r.kind == "COMPONENT"}
    footprints = {}
    current = None
    with zipfile.ZipFile(CHECKPOINT) as archive:
        for line in archive.read("STM32H747_MCU_BOARD_v19.epru").decode("utf-8-sig").splitlines():
            if line.startswith('{"type":"DOCHEAD"}'):
                r = record(m, line)
                current = r.body["uuid"] if r.body.get("docType") == "FOOTPRINT" else None
                if current:
                    footprints[current] = {}
            elif current and line.startswith('{"type":"PAD"'):
                r = record(m, line)
                footprints[current][r.record_id] = r
    pads = {}
    for r in rows:
        if r.kind != "PAD_NET":
            continue
        cid, num, local = m.parse_pad_net_id(r.record_id)
        fid = attrs[cid]["Footprint"]
        pad = footprints[fid][local]
        require(str(pad.body.get("num", "")) == num, "Footprint pad number mismatch")
        oid = cid + local
        pads[oid] = {
            "object_id": oid, "component_id": cid,
            "reference": attrs[cid].get("Designator", ""), "footprint_uuid": fid,
            "number": num, "local_id": local, "net_name": r.body.get("padNet", ""),
            "pad_body": pad.body, "component_body": components[cid].body,
        }
    return pads


def circle(center_mm):
    return Point(center_mm[0] / MM, center_mm[1] / MM).buffer(RADIUS_MM / MM, quad_segs=128)


def serialize_ring(coords, originals=None):
    originals = originals or {}
    points = []
    for x, y in coords:
        key = (round(x, 8), round(y, 8))
        pt = originals.get(key, (round(x, 4), round(y, 4)))
        if not points or points[-1] != pt:
            points.append(pt)
    if points[0] != points[-1]:
        points.append(points[0])
    require(len(points) >= 4, "Degenerate output ring")
    return [points[0][0], points[0][1], "L", *[v for p in points[1:] for v in p]]


def main():
    m = helper()
    raw = SOURCE.read_bytes()
    rows = [record(m, s) for s in raw.decode("utf-8-sig").splitlines() if s]
    index = {r.record_id: r for r in rows if r.record_id}
    require(rows[0].body.get("uuid") == "0ac2a19168000d8e", "Wrong PCB")
    pads = load_pads(m, rows)
    source_copper = m.build_copper_objects(rows, pads, {})
    pad_changes = []
    for oid, old, new in HOLES:
        r = index[oid]
        require(r.kind == "PAD" and not r.body["plated"], "Target is not free NPTH")
        require(abs(r.body["hole"]["width"] * MM - 3.2) < 0.000005, "Drill diameter changed")
        require(math.dist((r.body["centerX"] * MM, r.body["centerY"] * MM), old) < 0.000005, "Old hole centre mismatch")
        after = copy.deepcopy(r.body)
        after["centerX"], after["centerY"] = (round(v / MM, 4) for v in new)
        require({k: v for k, v in after.items() if k not in ("centerX", "centerY")} ==
                {k: v for k, v in r.body.items() if k not in ("centerX", "centerY")}, "Non-position PAD edit")
        pad_changes.append({"id": oid, "type": "PAD", "before": r.body, "after": after,
                            "old_center_mm": old, "new_center_mm": new})

    fill_changes, fill_reports, replacements = [], [], {}
    for fid, layer in FILLS.items():
        r = index[fid]
        require(r.kind == "FILL" and r.body["layerId"] == layer, "Target FILL mismatch")
        outer_pts = m.native_path_points(r.body["path"][0])
        outer = Polygon(outer_pts)
        require(outer.is_valid, "Original outer contour invalid")
        bounds = outer.bounds
        board_rect = box(*bounds)
        require(max(abs(v * MM - t) for v, t in zip(bounds, (.50049938, .50049938, 99.49950128, 153.49949996))) < .000005,
                "Unexpected original plane-edge bounds")
        old_regions, new_disks, corner_reports, windows = [], [], [], []
        for _, old, new in HOLES:
            centre = Point(old[0] / MM, old[1] / MM)
            distance = outer.distance(centre) * MM
            if distance > 5.0:
                require(layer == 16 and old == (96.0, 4.0), "Unexpected absent plane corner")
                corner_reports.append({"old_center_mm": old, "skipped": True,
                                       "reason": "This plane is already absent near this corner",
                                       "distance_to_plane_mm": distance})
                continue
            require(3.59 < distance < 3.61, "Unexpected corner keepout radius")
            window = box((old[0] - LOCAL_HALFSPAN_MM) / MM,
                         (old[1] - LOCAL_HALFSPAN_MM) / MM,
                         (old[0] + LOCAL_HALFSPAN_MM) / MM,
                         (old[1] + LOCAL_HALFSPAN_MM) / MM)
            missing = board_rect.intersection(window).difference(outer)
            require(not missing.is_empty and missing.area * MM * MM > 20, "Native corner notch missing")
            # The exact missing region must not touch the local window boundary;
            # otherwise the window clipped a larger non-corner feature.
            require(missing.distance(window.boundary) * MM > .005,
                    f"Local window clips another feature: {fid} {old} bounds={tuple(v * MM for v in missing.bounds)} area={missing.area * MM * MM}")
            old_regions.append(missing)
            new_disks.append(circle(new))
            windows.append(window)
            corner_reports.append({"old_center_mm": old, "new_center_mm": new,
                                   "old_exact_notch_area_mm2": missing.area * MM * MM,
                                   "old_exact_notch_bounds_mm": [v * MM for v in missing.bounds],
                                   "old_minimum_circle_radius_mm": distance,
                                   "old_notch_to_local_window_mm": missing.distance(window.boundary) * MM,
                                   "new_circle_radius_mm": RADIUS_MM})
        restored = outer.union(unary_union(old_regions))
        require(isinstance(restored, Polygon) and not restored.interiors, "Restoration changed outer topology unexpectedly")
        sign = 1 if m.signed_ring_area(outer_pts) > 0 else -1
        restored = orient(restored, sign=sign)
        original_points = {(round(x, 8), round(y, 8)): (x, y) for x, y in outer_pts}
        outer_path = serialize_ring(restored.exterior.coords, original_points)
        circles = [serialize_ring(orient(d, sign=-sign).exterior.coords) for d in new_disks]
        after = copy.deepcopy(r.body)
        # Preserve every other old contour, in its exact original order, then
        # append the new, opposite-polarity circular hole contours.
        after["path"] = [outer_path, *copy.deepcopy(r.body["path"][1:]), *circles]
        require(after["path"][1:len(r.body["path"])] == r.body["path"][1:], "Old non-corner contours changed")
        old_geom = m.fill_path_geometry(r.body)[0]
        new_geom = m.fill_path_geometry(after)[0]
        old_region = unary_union(old_regions)
        disks = unary_union(new_disks)
        intended = old_geom.union(old_region).difference(disks)
        require(new_geom.is_valid, "Candidate FILL invalid")
        serialization_error = intended.symmetric_difference(new_geom).area
        require(serialization_error < AREA_TOL_MIL2, f"Serialization mismatch {serialization_error}")
        added = new_geom.difference(old_geom)
        removed = old_geom.difference(new_geom)
        allowed = old_region.union(disks).buffer(QUANT_TOL_MIL)
        escaped = old_geom.symmetric_difference(new_geom).difference(allowed).area
        require(escaped < 0.000001, f"Copper delta escaped corner regions: {escaped}")
        local_union = unary_union(windows)
        old_unaffected = {p for p in outer_pts if not local_union.buffer(QUANT_TOL_MIL).covers(Point(p))}
        new_points = set(m.native_path_points(outer_path))
        missing_originals = old_unaffected - new_points
        require(not missing_originals, f"Non-corner coordinates lost: {len(missing_originals)}")
        same_body = dict(after); same_body.pop("path")
        old_body = dict(r.body); old_body.pop("path")
        require(same_body == old_body, "Non-path FILL edit")
        # Added copper is the only way this bounded move could reduce an
        # inter-net clearance.  Compare it with EVERY other-net copper object.
        comparisons, nearest = 0, None
        for (other_layer, net), objects in source_copper.items():
            if other_layer != layer or net.upper() == str(r.body["netName"]).upper():
                continue
            for obj in objects:
                clearance = added.distance(obj["geometry"]) * MM
                comparisons += 1
                result = {"clearance_mm": clearance, "id": obj["id"], "kind": obj["kind"], "net": net}
                if nearest is None or clearance < nearest["clearance_mm"]:
                    nearest = result
                require(clearance > .16, f"Added corner copper approaches other net {result}")
        replacements[fid] = new_geom
        fill_changes.append({"id": fid, "type": "FILL", "before": r.body, "after": after})
        fill_reports.append({"id": fid, "layer_id": layer, "net": r.body["netName"],
                             "corners": corner_reports, "before_contours": len(r.body["path"]),
                             "after_contours": len(after["path"]), "new_corner_holes": len(circles),
                             "other_old_contours_exact": True, "noncorner_vertices_exact": len(old_unaffected),
                             "missing_noncorner_vertices": 0, "only_path_changed": True,
                             "added_area_mm2": added.area * MM * MM, "removed_area_mm2": removed.area * MM * MM,
                             "delta_outside_allowed_region_mil2": escaped,
                             "serialization_error_mil2": serialization_error,
                             "all_other_net_objects_compared": comparisons,
                             "minimum_added_copper_other_net_clearance": nearest,
                             "new_void_board_edge_gap_nominal_mm": 5.0 - RADIUS_MM})
        print(f"Verified {fid} layer {layer}: {len(circles)} corner holes", flush=True)

    candidate_copper = m.build_copper_objects(rows, pads, replacements)
    hole_reports = []
    for change in pad_changes:
        body = change["after"]
        pt = Point(body["centerX"], body["centerY"])
        radius = body["hole"]["width"] / 2
        nearest = None
        for (layer, net), objects in candidate_copper.items():
            for obj in objects:
                clearance = (pt.distance(obj["geometry"]) - radius) * MM
                result = {"clearance_mm": clearance, "layer": layer, "net": net,
                          "id": obj["id"], "kind": obj["kind"]}
                if nearest is None or clearance < nearest["clearance_mm"]:
                    nearest = result
        require(nearest["clearance_mm"] > 1.99, "Moved hole lacks expected copper clearance")
        edge = min(body["centerX"] * MM, 100 - body["centerX"] * MM,
                   body["centerY"] * MM, 154 - body["centerY"] * MM) - radius * MM
        hole_reports.append({"id": change["id"], "center_mm": [body["centerX"] * MM, body["centerY"] * MM],
                             "diameter_mm": radius * MM * 2, "hole_edge_to_board_mm": edge,
                             "minimum_hole_edge_to_copper": nearest})
    physical_drills = sum(r.kind == "VIA" for r in rows) + sum(
        float((p["pad_body"].get("hole") or {}).get("width", 0)) > 0 for p in pads.values()) + len(pad_changes)
    require(physical_drills == 793, f"Unexpected drill count {physical_drills}")
    changed_ids = set(FILLS) | {h[0] for h in HOLES}
    untouched = [canonical([r.header, r.body]) for r in rows if r.record_id not in changed_ids]
    report = {"status": "PASS_OFFLINE_CANDIDATE_REQUIRES_NATIVE_DRC",
              "source_sha256": digest(raw), "checkpoint_sha256": digest(CHECKPOINT.read_bytes()),
              "pad_changes": 4, "fill_changes": 6, "new_corner_voids": 23,
              "all_other_records_exact_count": len(untouched),
              "all_other_records_canonical_sha256": digest(b"\n".join(untouched)),
              "all_other_fill_records_exact_count": sum(r.kind == "FILL" and r.record_id not in FILLS for r in rows),
              "physical_drills_before": physical_drills, "physical_drills_after": physical_drills,
              "drill_diameters_and_other_789_drills_unchanged": True,
              "native_drc_run": False, "native_project_modified": False,
              "refinement": "Restore exact native connected rounded old notch including missing corner triangle inside an 8x8 mm corner box; not an ideal old circle",
              "fills": fill_reports, "holes": hole_reports}
    plan = {"schema": "stm32h747-corner-hole-inward-plan-v1", "pcb_uuid": "0ac2a19168000d8e",
            "source": str(SOURCE.relative_to(ROOT)), "source_sha256": digest(raw),
            "checkpoint": str(CHECKPOINT.relative_to(ROOT)), "checkpoint_sha256": report["checkpoint_sha256"],
            "scope": "Four free NPTH x/y only plus exact corner-only outer-path restoration and 23 new plane holes",
            "requires_native_drc": True, "pad_changes": pad_changes, "fill_changes": fill_changes,
            "report": report}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("plan.json", plan), ("report.json", report)):
        path = OUT / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(name, path.stat().st_size, digest(path.read_bytes()), flush=True)


if __name__ == "__main__":
    main()
