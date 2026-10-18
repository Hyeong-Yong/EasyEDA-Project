#!/usr/bin/env python3
"""Read-only, bounded changed-copper QA of the multilayer diagnostic Gerber ZIP."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parents[1]
MM_PER_MIL = 0.0254
MEMBERS = {
    1: "Gerber_TopLayer.GTL",
    15: "Gerber_InnerLayer1.G1",
    16: "Gerber_InnerLayer2.G2",
    17: "Gerber_InnerLayer3.G3",
    18: "Gerber_InnerLayer4.G4",
    2: "Gerber_BottomLayer.GBL",
}
DEFAULT_SOURCE = ROOT / "output/validation/native-multilayer-copper_clearances-reopened.epru"
DEFAULT_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_multilayer_copper_clearances_20261015.epro2"
DEFAULT_ZIP = ROOT / "output/validation/STM32H747_multilayer_copper_clearances_DIAGNOSTIC_NOT_FOR_FAB.zip"
DEFAULT_REPORT = ROOT / "output/validation/native-multilayer-gerber-changed-copper-audit.json"
TARGET_FILLS = ("41fd0322eb2cc785", "d408b11385040441", "9a405bd52ff5d175",
                "8e56a14144c76f68", "eced2cdfc1e1f2e6")
SOURCE_BASELINE = ROOT / "output/validation/native-multilayer-before.epru"
U4_COMPONENT_ID = "3de4fa6d5f5df65c"
SELECTED_PAD_CLEARANCE_MM = 5.9843 * MM_PER_MIL
FLASH_POSITION_TOLERANCE_MM = 0.00002
TRACK_POSITION_TOLERANCE_MM = 0.00002


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_records(lines):
    result = []
    for raw in lines:
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        if not text.strip():
            continue
        header, body = text.strip().split("||", 1)
        result.append((json.loads(header), json.loads(body.rstrip("|"))))
    return result


def read_u4_pads(path):
    result = []
    current = None
    with zipfile.ZipFile(path) as archive:
        with archive.open("STM32H747_MCU_BOARD_v19.epru") as stream:
            for raw in stream:
                text = raw.decode("utf-8-sig").strip()
                if not text:
                    continue
                header, body = text.split("||", 1)
                header, body = json.loads(header), json.loads(body.rstrip("|"))
                if header.get("type") == "DOCHEAD":
                    current = body.get("uuid")
                elif current == "a3627e2915fe61c1" and header.get("type") == "PAD":
                    result.append((header, body))
    return result


def parse_layers(path, parser):
    layers = {}
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temporary:
        for layer_id, member in MEMBERS.items():
            data = archive.read(member)
            normalized = re.sub(r"(?m)^G54D(\d+)\*$", r"D\1*", data.decode("utf-8"))
            extracted = Path(temporary) / member
            extracted.write_text(normalized, encoding="utf-8", newline="\n")
            layer = parser.parse_gerber(extracted, str(layer_id))
            layer["original_sha256"] = hashlib.sha256(data).hexdigest()
            layers[layer_id] = layer
    return layers


def segment_points(segment):
    start, end = segment["startMm"], segment["endMm"]
    if segment["kind"] == "line":
        return [tuple(start), tuple(end)]
    center = segment["centerMm"]
    radius = math.dist(start, center)
    a = math.atan2(start[1] - center[1], start[0] - center[0])
    b = math.atan2(end[1] - center[1], end[0] - center[0])
    clockwise = segment["clockwise"]
    sweep = -((a - b) % (2 * math.pi)) if clockwise else (b - a) % (2 * math.pi)
    if abs(sweep) < 1e-12:
        sweep = -2 * math.pi if clockwise else 2 * math.pi
    steps = max(4, math.ceil(abs(sweep) / 0.005))
    return [
        (center[0] + radius * math.cos(a + sweep * i / steps),
         center[1] + radius * math.sin(a + sweep * i / steps))
        for i in range(steps + 1)
    ]


def region_geometry(region):
    result = GeometryCollection()
    for contour in region["contours"]:
        points = []
        for segment in contour:
            points.extend(segment_points(segment)[:-1])
        polygon = Polygon(points)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        result = result.symmetric_difference(polygon)
    return result


def parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [part for group in geometry.geoms for part in parts(group)]


def geometry_stats(geometry):
    polygons = parts(geometry)
    return {
        "area_mm2": geometry.area,
        "bounds_mm": list(geometry.bounds),
        "polygon_parts": len(polygons),
        "interior_holes": sum(len(polygon.interiors) for polygon in polygons),
        "valid": geometry.is_valid,
    }


def circle_flashes(layer, point, expected_diameter):
    rows = []
    for index, obj in enumerate(layer["objects"]):
        if obj["kind"] != "flash" or obj["polarity"] != "dark":
            continue
        ap = layer["apertures"][obj["aperture"]]
        if ap["template"] != "C" or abs(ap["paramsMm"][0] - expected_diameter) > 0.00001:
            continue
        position_error = math.dist(point, obj["atMm"])
        if position_error <= FLASH_POSITION_TOLERANCE_MM:
            rows.append({"object_index": index, "aperture": obj["aperture"],
                         "at_mm": obj["atMm"], "diameter_mm": ap["paramsMm"][0],
                         "position_error_mm": position_error})
    return rows


def matching_track(layer, body):
    start = [body["startX"] * MM_PER_MIL, body["startY"] * MM_PER_MIL]
    end = [body["endX"] * MM_PER_MIL, body["endY"] * MM_PER_MIL]
    candidates = []
    for index, obj in enumerate(layer["objects"]):
        if obj["kind"] != "line" or obj["polarity"] != "dark":
            continue
        direct = max(math.dist(start, obj["startMm"]), math.dist(end, obj["endMm"]))
        reverse = max(math.dist(start, obj["endMm"]), math.dist(end, obj["startMm"]))
        if min(direct, reverse) <= TRACK_POSITION_TOLERANCE_MM:
            ap = layer["apertures"][obj["aperture"]]
            if ap["template"] != "C":
                continue
            candidates.append({"object_index": index, "aperture": obj["aperture"],
                               "start_mm": obj["startMm"], "end_mm": obj["endMm"],
                               "width_mm": ap["paramsMm"][0],
                               "endpoint_error_mm": min(direct, reverse)})
    if not candidates:
        return None
    expected_width = body["width"] * MM_PER_MIL
    return min(candidates, key=lambda row: abs(row["width_mm"] - expected_width))


def u4_and_via_audit(native, baseline, args, layers):
    component = native[("COMPONENT", U4_COMPONENT_ID)]
    if component["angle"] != 0 or component["layerId"] != 1:
        raise RuntimeError("U4 assumed source placement no longer valid")
    bindings = {}
    for (kind, record_id), body in native.items():
        if kind != "PAD_NET":
            continue
        identity = json.loads(record_id)
        if identity[1] == U4_COMPONENT_ID:
            bindings[identity[3]] = body["padNet"]
    pad_rows = []
    for header, body in read_u4_pads(args.checkpoint):
        point = [(component["x"] + body["centerX"]) * MM_PER_MIL,
                 (component["y"] + body["centerY"]) * MM_PER_MIL]
        matches = circle_flashes(layers[1], point, 0.36)
        pad_rows.append({"id": header["id"], "number": body["num"], "net": bindings[header["id"]],
                         "native_centre_mm": point,
                         "native_diameter_mm": body["defaultPad"]["width"] * MM_PER_MIL,
                         "gerber_matches": matches, "status": "pass" if matches else "fail"})
    via_rows = []
    for (kind, record_id), body in native.items():
        if kind != "VIA" or body == baseline[(kind, record_id)]:
            continue
        point = [body["centerX"] * MM_PER_MIL, body["centerY"] * MM_PER_MIL]
        matches = {str(layer): circle_flashes(data, point, 0.31) for layer, data in layers.items()}
        before = baseline[(kind, record_id)]
        via_rows.append({"id": record_id, "net": body["netName"], "native_centre_mm": point,
                         "native_diameter_mm": body["viaDiameter"] * MM_PER_MIL,
                         "native_drill_mm": body["holeDiameter"] * MM_PER_MIL,
                         "centres_and_drill_unchanged": all(body[key] == before[key]
                             for key in ("centerX", "centerY", "holeDiameter")),
                         "six_layer_flash_matches": matches,
                         "status": "pass" if all(matches.values()) else "fail"})
    changed_tracks = []
    top_tracks = []
    for (kind, record_id), body in native.items():
        if kind != "LINE":
            continue
        is_changed = body != baseline.get((kind, record_id))
        if not is_changed and body["layerId"] != 1:
            continue
        if body["layerId"] not in layers:
            continue
        if body["layerId"] == 1:
            bounds = (min(body["startX"], body["endX"]) * MM_PER_MIL,
                      min(body["startY"], body["endY"]) * MM_PER_MIL,
                      max(body["startX"], body["endX"]) * MM_PER_MIL,
                      max(body["startY"], body["endY"]) * MM_PER_MIL)
            local = bounds[0] < 55 and bounds[2] > 38 and bounds[1] < 123 and bounds[3] > 106
        else:
            local = False
        if not is_changed and not local:
            continue
        match = matching_track(layers[body["layerId"]], body)
        row = {"id": record_id, "net": body["netName"], "layer_id": body["layerId"],
               "native_width_mm": body["width"] * MM_PER_MIL,
               "gerber_match": match,
               "status": "pass" if match and abs(match["width_mm"] - body["width"] * MM_PER_MIL) < 0.00001 else "fail"}
        if is_changed:
            changed_tracks.append(row)
        if local:
            top_tracks.append(row)
    gap_rows = []
    for pad in pad_rows:
        if not pad["net"] or not pad["gerber_matches"]:
            continue
        flash = pad["gerber_matches"][0]
        point = Point(flash["at_mm"])
        nearest = []
        for track in top_tracks:
            if not track["gerber_match"] or not track["net"] or track["net"] == pad["net"]:
                continue
            match = track["gerber_match"]
            clearance = point.distance(LineString([match["start_mm"], match["end_mm"]])) - (flash["diameter_mm"] + match["width_mm"]) / 2
            nearest.append({"track_id": track["id"], "track_net": track["net"],
                            "gerber_width_mm": match["width_mm"], "clearance_mm": clearance})
        nearest.sort(key=lambda row: row["clearance_mm"])
        gap_rows.append({"pad_id": pad["id"], "number": pad["number"], "net": pad["net"],
                         "nearest_different_net_tracks": nearest[:2],
                         "status": "pass" if nearest and nearest[0]["clearance_mm"] >= SELECTED_PAD_CLEARANCE_MM else "fail"})
    return {
        "u4_lands": {"expected": 90, "matched": sum(row["status"] == "pass" for row in pad_rows), "rows": pad_rows},
        "changed_vias": {"expected": 188, "matched": sum(row["status"] == "pass" for row in via_rows),
                         "layer_flash_checks": sum(len(row["six_layer_flash_matches"]) for row in via_rows), "rows": via_rows},
        "changed_tracks": {"count": len(changed_tracks), "matched": sum(row["status"] == "pass" for row in changed_tracks),
                           "rows": changed_tracks},
        "u4_exported_pad_track_clearance": {"selected_rule_mm": SELECTED_PAD_CLEARANCE_MM,
            "nearby_top_native_lines_matched": len(top_tracks),
            "minimum_clearance_mm": min(row["nearest_different_net_tracks"][0]["clearance_mm"] for row in gap_rows),
            "connected_pad_count": sum(bool(row["net"]) for row in pad_rows),
            "all_connected_pad_nearest_track_checks_pass": len(gap_rows) == sum(bool(row["net"]) for row in pad_rows) and all(row["status"] == "pass" for row in gap_rows),
            "rows": gap_rows},
    }


def fill_audit(fill_id, body, layers, fill_helper):
    print(f"Auditing source FILL {fill_id} ({len(body['path'])} contours)", flush=True)
    rings = [Polygon([(x * MM_PER_MIL, y * MM_PER_MIL)
                       for x, y in fill_helper.native_path_points(path)]) for path in body["path"]]
    if any(not ring.is_valid for ring in rings):
        raise RuntimeError(f"invalid source ring in {fill_id}")
    parent = {}
    for index, ring in enumerate(rings):
        candidates = [j for j, candidate in enumerate(rings)
                      if candidate.area > ring.area and candidate.covers(ring.representative_point())]
        parent[index] = min(candidates, key=lambda j: rings[j].area) if candidates else None
    depths = {}
    for index in range(len(rings)):
        current, depth = parent[index], 0
        while current is not None:
            depth += 1
            current = parent[current]
        depths[index] = depth
    native = unary_union([
        Polygon(ring.exterior.coords, [child.exterior.coords for j, child in enumerate(rings)
                                      if parent[j] == index])
        for index, ring in enumerate(rings) if depths[index] % 2 == 0
    ])
    print(f"Source FILL {fill_id}: {geometry_stats(native)}", flush=True)
    layer = layers[body["layerId"]]
    approximate_rows = []
    for index, obj in enumerate(layer["objects"]):
        if obj["kind"] != "region" or obj["polarity"] != "dark":
            continue
        points = [point for contour in obj["contours"] for segment in contour
                  for point in (segment["startMm"], segment["endMm"])]
        bounds = (min(point[0] for point in points), min(point[1] for point in points),
                  max(point[0] for point in points), max(point[1] for point in points))
        approximate_rows.append((bounds, index, obj))
    chosen = {}
    for part in parts(native):
        bounds, index, obj = min(approximate_rows,
            key=lambda row: max(abs(a - b) for a, b in zip(row[0], part.bounds)))
        chosen[index] = (bounds, index, obj)
    region_rows = []
    for bounds, index, obj in chosen.values():
        print(f"Interpreting Gerber region {index}: {sum(len(c) for c in obj['contours'])} edges", flush=True)
        geometry = region_geometry(obj)
        print(f"Gerber region {index}: {geometry_stats(geometry)}", flush=True)
        if not geometry.is_empty and geometry.intersects(native):
            region_rows.append((index, obj, geometry, geometry.symmetric_difference(native).area))
    geometry = unary_union([row[2] for row in region_rows])
    difference = geometry.symmetric_difference(native).area
    native_holes = [Polygon(ring) for part in parts(native) for ring in part.interiors]
    gerber_holes = [Polygon(ring) for part in parts(geometry) for ring in part.interiors]
    hole_rows = []
    for hole_index, hole in enumerate(native_holes):
        candidates = [(i, candidate) for i, candidate in enumerate(gerber_holes)
                      if candidate.covers(hole.representative_point())]
        if len(candidates) == 1:
            candidate_index, candidate = candidates[0]
            hole_rows.append({"native_hole_index": hole_index, "gerber_hole_index": candidate_index,
                              "native_area_mm2": hole.area, "gerber_area_mm2": candidate.area,
                              "bounds_max_error_mm": max(abs(a - b) for a, b in zip(hole.bounds, candidate.bounds)),
                              "symmetric_difference_area_mm2": hole.symmetric_difference(candidate).area,
                              "status": "pass"})
        else:
            hole_rows.append({"native_hole_index": hole_index, "candidate_count": len(candidates), "status": "fail"})
    row = {
        "id": fill_id,
        "net": body["netName"],
        "layer_id": body["layerId"],
        "member": MEMBERS[body["layerId"]],
        "native_contours": len(body["path"]),
        "native_geometry": geometry_stats(native),
        "matched_gerber_object_indices": [row[0] for row in region_rows],
        "gerber_region_contour_counts": [len(row[1]["contours"]) for row in region_rows],
        "gerber_geometry": geometry_stats(geometry),
        "symmetric_difference_area_mm2": difference,
        "native_boundary_outside_gerber_boundary_0_00002mm_tube_length_mm": native.boundary.difference(geometry.boundary.buffer(0.00002)).length,
        "candidate_intersecting_regions": len(region_rows),
        "component_bounds_max_error_mm": max(min(max(abs(a - b) for a, b in zip(row[0], part.bounds))
                                                for row in approximate_rows) for part in parts(native)),
        "hole_identity_checks": {"native_holes": len(native_holes), "gerber_holes": len(gerber_holes),
            "matched_native_holes": sum(row["status"] == "pass" for row in hole_rows),
            "unique_matched_gerber_holes": len({row["gerber_hole_index"] for row in hole_rows if row["status"] == "pass"}),
            "rows": hole_rows},
    }
    return row, geometry


def d30_fill_clearance_audit(native, layers, fill_results, fill_helper):
    d30 = []
    for (kind, record_id), body in native.items():
        if kind != "LINE" or body["layerId"] != 1 or body["netName"] != "D30":
            continue
        match = matching_track(layers[1], body)
        if match is None:
            raise RuntimeError(f"D30 LINE {record_id} missing exact Gerber counterpart")
        d30.append((record_id, body, match))
    measurements = []
    for row, geometry in fill_results:
        if row["id"] not in {"8e56a14144c76f68", "eced2cdfc1e1f2e6"}:
            continue
        body = native[("FILL", row["id"])]
        source_geometry, _ = fill_helper.fill_path_geometry(body)
        source_geometry = affinity.scale(source_geometry, xfact=MM_PER_MIL, yfact=MM_PER_MIL, origin=(0, 0))
        clearances = []
        for record_id, line, match in d30:
            actual_line = LineString([match["start_mm"], match["end_mm"]])
            native_line = LineString([(line["startX"] * MM_PER_MIL, line["startY"] * MM_PER_MIL),
                                      (line["endX"] * MM_PER_MIL, line["endY"] * MM_PER_MIL)])
            exported_gap = geometry.distance(actual_line) - match["width_mm"] / 2
            source_gap = source_geometry.distance(native_line) - line["width"] * MM_PER_MIL / 2
            conservative_source_gap = source_gap - body["width"] * MM_PER_MIL / 2
            clearances.append({"track_id": record_id, "track_width_mm": match["width_mm"],
                               "exported_clearance_mm": exported_gap,
                               "source_contour_clearance_mm": source_gap,
                               "source_clearance_including_half_fill_stroke_mm": conservative_source_gap})
        clearances.sort(key=lambda value: value["exported_clearance_mm"])
        measurements.append({"fill_id": row["id"], "gerber_object_indices": row["matched_gerber_object_indices"],
                             "minimum_exported_clearance_mm": clearances[0]["exported_clearance_mm"],
                             "minimum_conservative_source_clearance_mm": min(value["source_clearance_including_half_fill_stroke_mm"] for value in clearances),
                             "minimum_exported_surplus_mm": clearances[0]["exported_clearance_mm"] - SELECTED_PAD_CLEARANCE_MM,
                             "nearest_d30_lines": clearances[:3],
                             "status": "pass" if clearances[0]["exported_clearance_mm"] >= SELECTED_PAD_CLEARANCE_MM else "fail"})
    return {"selected_rule_mm": SELECTED_PAD_CLEARANCE_MM, "top_d30_lines_checked": len(d30),
            "all_d30_lines_have_exact_gerber_counterpart": True, "rows": measurements,
            "status": "pass" if len(measurements) == 2 and all(row["status"] == "pass" for row in measurements) else "fail"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--gerber-zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    gerber_parser = load_module("stm_changed_copper_gerber", "extract_gerber_reconstruction.py")
    fill_helper = load_module("stm_changed_copper_fill", "plan-multilayer-fill-clearance.py")
    native_rows = read_records(args.source.read_text(encoding="utf-8-sig").splitlines())
    native = {(header["type"], str(header.get("id"))): body for header, body in native_rows}
    baseline = {(header["type"], str(header.get("id"))): body for header, body in read_records(SOURCE_BASELINE.read_text(encoding="utf-8-sig").splitlines())}
    layers = parse_layers(args.gerber_zip, gerber_parser)
    changed = u4_and_via_audit(native, baseline, args, layers)
    print(json.dumps({key: {k: v for k, v in value.items() if k != "rows"} for key, value in changed.items()}, ensure_ascii=False), flush=True)
    fill_results = [fill_audit(fill_id, native[("FILL", fill_id)], layers, fill_helper) for fill_id in TARGET_FILLS]
    d30 = d30_fill_clearance_audit(native, layers, fill_results, fill_helper)
    fill_checks = []
    for row, geometry in fill_results:
        holes = row["hole_identity_checks"]
        same_topology = (row["native_geometry"]["polygon_parts"] == row["gerber_geometry"]["polygon_parts"]
                         and holes["native_holes"] == holes["gerber_holes"] == holes["matched_native_holes"] == holes["unique_matched_gerber_holes"])
        fill_checks.append({"id": row["id"], "polygon_parts_and_hole_identity_preserved": same_topology,
                            "component_bounds_within_0_00001mm": row["component_bounds_max_error_mm"] <= 0.00001})
    checks = {
        "u4_all_90_lands_exact_0_36mm_aperture": changed["u4_lands"]["matched"] == 90,
        "all_188_via_6_layer_centres_and_0_31mm_apertures": len(changed["changed_vias"]["rows"]) == changed["changed_vias"]["matched"] == 188,
        "changed_via_drills_and_centres_unchanged_in_native_source": all(row["centres_and_drill_unchanged"] for row in changed["changed_vias"]["rows"]),
        "all_185_changed_native_lines_match_exported_endpoints_and_width": changed["changed_tracks"]["count"] == changed["changed_tracks"]["matched"] == 185,
        "u4_bounded_pad_track_exported_clearance_passes_selected_rule": changed["u4_exported_pad_track_clearance"]["all_connected_pad_nearest_track_checks_pass"],
        "five_representative_fill_part_and_hole_topologies_preserved": all(row["polygon_parts_and_hole_identity_preserved"] for row in fill_checks),
        "five_representative_fill_component_bounds_preserved_to_10nm": all(row["component_bounds_within_0_00001mm"] for row in fill_checks),
        "two_additional_fill_to_d30_exported_clearances_pass_selected_rule": d30["status"] == "pass",
    }
    report = {
        "schema": "stm32h747-multilayer-gerber-changed-copper-audit-v1",
        "status": "pass-diagnostic-not-manufacturing-approved" if all(checks.values()) else "fail",
        "manufacturing_approved": False,
        "inputs": {
            "source": {"path": str(args.source.resolve()), "sha256": sha256(args.source)},
            "checkpoint": {"path": str(args.checkpoint.resolve()), "sha256": sha256(args.checkpoint)},
            "gerber_zip": {"path": str(args.gerber_zip.resolve()), "sha256": sha256(args.gerber_zip)},
            "baseline_source": {"path": str(SOURCE_BASELINE.resolve()), "sha256": sha256(SOURCE_BASELINE)},
            "audit_script": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
            "gerber_parser": {"path": str(ROOT / "scripts/extract_gerber_reconstruction.py"),
                              "sha256": sha256(ROOT / "scripts/extract_gerber_reconstruction.py")},
        },
        "layers": [{"id": key, "member": MEMBERS[key], "sha256": layer["original_sha256"],
                    "objects": dict(Counter(obj["kind"] for obj in layer["objects"]))}
                   for key, layer in layers.items()],
        **changed,
        "multi_contour_fill_exports": [row for row, geometry in fill_results],
        "fill_topology_checks": fill_checks,
        "additional_two_fill_d30_clearance": d30,
        "checks": checks,
        "tolerances_mm": {"flash_position": FLASH_POSITION_TOLERANCE_MM,
                          "line_endpoint": TRACK_POSITION_TOLERANCE_MM, "aperture_dimension": 0.00001},
        "scope": "Actual exported aperture/centres for U4 90 lands and 188 changed vias on six Cu, all 185 changed LINE endpoints/widths, bounded U4 Top pad-track clearance, five selected FILL part/hole topologies and two selected FILL-D30 clearances.",
        "limitations": [
            "Diagnostic export only: not manufacturing approval, and the four unresolved CN1 mechanical-outline clearances remain outside this copper audit.",
            "Topology equivalence was checked for five selected FILLs, not all 730 FILLs or every possible Gerber object interaction.",
            "The 41fd large plane is serialized as a weakly-simple single contour with cut-in bridges. Its topology and all 358 hole identities survive, but its polygon is not bit-for-bit identical to the native contours: symmetric-difference area is recorded rather than waived as exact copper equivalence.",
            "The U4 clearance check covers 85 net-bearing lands versus nearby Top LINEs (442 native lines), not complete CAM DRC of every pad, arc, plane and via interaction; the remaining five U4 lands have blank/NC net identity.",
            "Via drill diameters are unchanged in the native source; physical Excellon drill identity is independently audited by the root task.",
            "No stackup impedance simulation, SI/PI analysis, solderability approval, assembly tolerance analysis or manufacturer CAM review was performed by this audit.",
        ],
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(args.report.resolve()),
                      "checks": checks, "d30": d30}, ensure_ascii=False, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
