#!/usr/bin/env python3
"""Read-only export comparison after the approved CN1 square-cutout enlargement."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE_ZIP = ROOT / "output/validation/STM32H747_multilayer_copper_clearances_DIAGNOSTIC_NOT_FOR_FAB.zip"
FINAL_ZIP = ROOT / "output/validation/STM32H747_multilayer_drc_pass_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
BASELINE_SOURCE = ROOT / "output/validation/native-multilayer-copper_clearances-reopened.epru"
FINAL_SOURCE = ROOT / "output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru"
REPORT = ROOT / "output/validation/native-cn1-cutout-gerber-audit-20261016.json"
PARSER = ROOT / "scripts/extract_gerber_reconstruction.py"
EXPECTED_FINAL_ZIP_SHA256 = "9a9205244fcbcc592fbcb566f768f1ac6bbf494bb8f3c78c778452ffd018a2c1"
COPPER_MEMBERS = ["Gerber_TopLayer.GTL", "Gerber_InnerLayer1.G1", "Gerber_InnerLayer2.G2",
                  "Gerber_InnerLayer3.G3", "Gerber_InnerLayer4.G4", "Gerber_BottomLayer.GBL"]
DRILL_MEMBERS = ["Drill_PTH_Through.DRL", "Drill_NPTH_Through.DRL", "Drill_PTH_Through_Via.DRL"]
OUTLINE_MEMBER = "Gerber_BoardOutlineLayer.GKO"
CN1_POLY_IDS = {"5b55024cb3a23233", "6e8dd66b3e3db1b0", "e94386c2e1a58187", "f614cce4900c7115"}
MM_PER_MIL = 0.0254
TOLERANCE_MM = 0.00001


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


class MemoryGerber:
    def __init__(self, name, text):
        self.name = name
        self.text = text

    def read_text(self, **_):
        return self.text

    def open(self, mode):
        if mode != "rb":
            raise RuntimeError("read-only memory source")
        return io.BytesIO(self.text.encode())


def load_parser():
    spec = importlib.util.spec_from_file_location("cn1_export_gerber_parser", PARSER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_generation_timestamp(data, drill=False):
    text = data.decode("utf-8")
    pattern = (r"(?m)^;EasyEDA Pro Client v3\.2\.206, \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$"
               if drill else r"(?m)^G04 EasyEDA Pro v3\.2\.206, \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\*$")
    removed = re.findall(pattern, text)
    if len(removed) != 1:
        raise RuntimeError(f"expected exactly one generator timestamp, got {removed}")
    return re.sub(pattern, "GENERATION_TIMESTAMP_ONLY", text).encode(), removed


def parsed(data, name, parser):
    text = data.decode("utf-8")
    if re.search(r"%(?:LM|LR|LS|SR|IP)", text):
        raise RuntimeError(f"unsupported Gerber transform in {name}")
    if "%MOMM*%" not in text or "%FSLAX45Y45*%" not in text:
        raise RuntimeError(f"unexpected units/coordinate format in {name}")
    text = re.sub(r"(?m)^G54D(\d+)\*$", r"D\1*", text)
    return parser.parse_gerber(MemoryGerber(name, text), name)


def shape(aperture):
    return {key: aperture.get(key) for key in ("template", "paramsMm", "function")}


def resolved_object(obj, apertures, region_segment=False):
    result = {key: value for key, value in obj.items() if key not in {"aperture", "contours"}}
    if obj["kind"] == "region":
        result["contours"] = [[resolved_object(segment, apertures, True) for segment in contour]
                              for contour in obj["contours"]]
    elif not region_segment:
        result["aperture_shape"] = shape(apertures[obj["aperture"]])
    return result


def object_hashes(layer):
    return [digest(canonical(resolved_object(obj, layer["apertures"]))) for obj in layer["objects"]]


def macro_definitions(data):
    return re.findall(r"%AM.*?\*%", data.decode("utf-8"), re.DOTALL)


def used_aperture_summary(layer):
    used = {obj["aperture"] for obj in layer["objects"] if obj["kind"] != "region"}
    shapes = Counter(digest(canonical(shape(layer["apertures"][code]))) for code in used)
    return {"used_aperture_ids": sorted(used), "used_distinct_shape_count": len(shapes),
            "unused_definitions": {code: shape(aperture) for code, aperture in layer["apertures"].items()
                                   if code not in used}}


def gerber_identity(member, before_data, after_data, parser):
    before = parsed(before_data, member, parser)
    after = parsed(after_data, member, parser)
    a, b = object_hashes(before), object_hashes(after)
    normalized_a, stamps_a = normalize_generation_timestamp(before_data)
    normalized_b, stamps_b = normalize_generation_timestamp(after_data)
    macros_exact = macro_definitions(before_data) == macro_definitions(after_data)
    status = a == b and before["format"] == after["format"] and macros_exact
    return {
        "member": member,
        "status": "pass" if status else "fail",
        "raw_sha256_before": digest(before_data), "raw_sha256_after": digest(after_data),
        "timestamp_only_normalized_bytes_exact": normalized_a == normalized_b,
        "generator_timestamp_before": stamps_a[0], "generator_timestamp_after": stamps_b[0],
        "object_count_before": len(a), "object_count_after": len(b),
        "resolved_geometry_object_sequence_exact": a == b,
        "resolved_geometry_sha256_before": digest(canonical(a)),
        "resolved_geometry_sha256_after": digest(canonical(b)),
        "coordinate_format_exact": before["format"] == after["format"],
        "aperture_macro_definitions_exact": macros_exact,
        "aperture_summary_before": used_aperture_summary(before),
        "aperture_summary_after": used_aperture_summary(after),
        "object_counts": dict(Counter(obj["kind"] for obj in before["objects"])),
    }, before, after


def read_native_polys(path):
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        header, body = line.split("||", 1)
        header, body = json.loads(header), json.loads(body.rstrip("|"))
        if header["type"] == "POLY" and body.get("layerId") == 11:
            result[str(header["id"])] = body
    return result


def native_edge(body):
    path = body["path"]
    if len(path) != 5 or path[2] != "L":
        raise RuntimeError("CN1 native edge is not the expected straight line")
    return {"start_mm": [path[0] * MM_PER_MIL, path[1] * MM_PER_MIL],
            "end_mm": [path[3] * MM_PER_MIL, path[4] * MM_PER_MIL],
            "width_mm": body["width"] * MM_PER_MIL}


def match_native_edge(native, obj, apertures):
    if obj["kind"] != "line" or obj["polarity"] != "dark":
        return False
    dimensions = apertures[obj["aperture"]]
    if dimensions["template"] != "C" or abs(dimensions["paramsMm"][0] - native["width_mm"]) > TOLERANCE_MM:
        return False
    direct = max(math.dist(native["start_mm"], obj["startMm"]), math.dist(native["end_mm"], obj["endMm"]))
    reverse = max(math.dist(native["start_mm"], obj["endMm"]), math.dist(native["end_mm"], obj["startMm"]))
    return min(direct, reverse) <= TOLERANCE_MM


def rectangle(edges):
    points = [point for edge in edges for point in (edge["startMm"], edge["endMm"])]
    bounds = [min(point[0] for point in points), min(point[1] for point in points),
              max(point[0] for point in points), max(point[1] for point in points)]
    return {"bounds_mm": bounds, "size_mm": [bounds[2] - bounds[0], bounds[3] - bounds[1]],
            "centre_mm": [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]}


def outline_audit(before, after):
    native_before, native_after = read_native_polys(BASELINE_SOURCE), read_native_polys(FINAL_SOURCE)
    mappings = []
    old_indices, new_indices = set(), set()
    for record_id in sorted(CN1_POLY_IDS):
        old_edge, new_edge = native_edge(native_before[record_id]), native_edge(native_after[record_id])
        a = [index for index, obj in enumerate(before["objects"]) if match_native_edge(old_edge, obj, before["apertures"])]
        b = [index for index, obj in enumerate(after["objects"]) if match_native_edge(new_edge, obj, after["apertures"])]
        if len(a) != 1 or len(b) != 1:
            raise RuntimeError(f"ambiguous/missing exported CN1 edge {record_id}: {a}/{b}")
        old_indices.add(a[0])
        new_indices.add(b[0])
        mappings.append({"id": record_id, "before": old_edge, "after": new_edge,
                         "before_gerber_object_index": a[0], "after_gerber_object_index": b[0]})
    before_other = [resolved_object(obj, before["apertures"]) for index, obj in enumerate(before["objects"]) if index not in old_indices]
    after_other = [resolved_object(obj, after["apertures"]) for index, obj in enumerate(after["objects"]) if index not in new_indices]
    old_rect = rectangle([before["objects"][index] for index in sorted(old_indices)])
    new_rect = rectangle([after["objects"][index] for index in sorted(new_indices)])
    outer_rect = rectangle([obj for index, obj in enumerate(after["objects"]) if index not in new_indices])
    checks = {
        "exactly_four_cn1_export_edges_matched": len(old_indices) == len(new_indices) == 4,
        "old_cutout_1_80mm_square": all(abs(value - 1.8) <= TOLERANCE_MM for value in old_rect["size_mm"]),
        "new_cutout_1_92mm_square": all(abs(value - 1.92) <= TOLERANCE_MM for value in new_rect["size_mm"]),
        "cutout_centre_unchanged": math.dist(old_rect["centre_mm"], new_rect["centre_mm"]) <= TOLERANCE_MM,
        "all_other_exported_outline_geometry_exact": before_other == after_other,
        "outer_rectangle_100x154mm": all(abs(a - b) <= TOLERANCE_MM for a, b in zip(outer_rect["size_mm"], [100, 154])),
        "only_four_outline_objects_changed": len(before["objects"]) == len(after["objects"]) == 8,
    }
    return {"status": "pass" if all(checks.values()) else "fail", "checks": checks,
            "old_cutout": old_rect, "new_cutout": new_rect, "outer_rectangle": outer_rect,
            "cn1_edge_native_to_gerber_matches": mappings,
            "other_outline_object_count": len(after_other),
            "other_outline_geometry_sha256": digest(canonical(after_other))}


def main():
    if digest(FINAL_ZIP.read_bytes()) != EXPECTED_FINAL_ZIP_SHA256:
        raise RuntimeError("final diagnostic ZIP hash differs from the frozen root input")
    parser = load_parser()
    copper, drills = [], []
    with zipfile.ZipFile(BASELINE_ZIP) as old, zipfile.ZipFile(FINAL_ZIP) as new:
        same_members = set(old.namelist()) == set(new.namelist())
        for member in COPPER_MEMBERS:
            row, _, _ = gerber_identity(member, old.read(member), new.read(member), parser)
            copper.append(row)
        for member in DRILL_MEMBERS:
            a, b = old.read(member), new.read(member)
            norm_a, stamp_a = normalize_generation_timestamp(a, True)
            norm_b, stamp_b = normalize_generation_timestamp(b, True)
            drills.append({"member": member, "status": "pass" if norm_a == norm_b else "fail",
                           "raw_sha256_before": digest(a), "raw_sha256_after": digest(b),
                           "normalized_sha256_before": digest(norm_a), "normalized_sha256_after": digest(norm_b),
                           "timestamp_only_normalized_bytes_exact": norm_a == norm_b,
                           "removed_timestamp_before": stamp_a[0], "removed_timestamp_after": stamp_b[0]})
        outline_metadata, before_outline, after_outline = gerber_identity(OUTLINE_MEMBER, old.read(OUTLINE_MEMBER), new.read(OUTLINE_MEMBER), parser)
        outline = outline_audit(before_outline, after_outline)
    checks = {"same_archive_member_set": same_members,
              "six_copper_layers_resolved_geometry_sequences_exact": len(copper) == 6 and all(row["status"] == "pass" for row in copper),
              "all_three_drill_members_exact_after_timestamp_only_normalization": all(row["status"] == "pass" for row in drills),
              "only_approved_cn1_outline_geometry_changed": outline["status"] == "pass"}
    report = {
        "schema": "stm32h747-cn1-cutout-gerber-audit-20261016-v1",
        "status": "pass-diagnostic-not-manufacturing-approved" if all(checks.values()) else "fail",
        "manufacturing_approved": False,
        "inputs": {key: {"path": str(path.resolve()), "sha256": digest(path.read_bytes())}
                   for key, path in {"baseline_zip": BASELINE_ZIP, "final_zip": FINAL_ZIP,
                                     "baseline_native_pcb": BASELINE_SOURCE, "final_native_pcb": FINAL_SOURCE,
                                     "gerber_parser": PARSER, "audit_script": Path(__file__)}.items()},
        "checks": checks, "copper_layers": copper, "drill_members": drills,
        "outline": outline, "outline_serialization_metadata": outline_metadata,
        "normalization_policy": [
            "Only the one exact EasyEDA 3.2.206 generation-timestamp comment is replaced for raw-payload comparison.",
            "The existing Gerber parser accepts legacy G54D aperture selection after equivalent D selection normalization; all coordinates and aperture dimensions are preserved.",
            "Gerber semantic comparison resolves each used aperture ID to template/parameters/function. Region segments do not have physical stroke apertures. Unused aperture definitions are recorded but do not affect physical geometry.",
            "All aperture macro definition text, coordinate formats, object order, polarity, coordinates, arc direction/centres, flash positions and used shape dimensions must compare exactly. Unsupported transform/step-repeat commands cause failure.",
        ],
        "limitations": [
            "This is a bounded before/after export identity check, not full CAM DRC or manufacturing approval.",
            "Prior changed-copper and drill audits carry their original limitations; this audit proves that the six exported copper geometries and three drill payloads have not changed after the mechanical edit.",
            "The GKO centreline outlines are checked; cutter compensation, milling process tolerance, enclosure fit and final manufacturer review remain separate.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(REPORT.resolve()),
                      "sha256": digest(REPORT.read_bytes()), "checks": checks,
                      "outline": {key: outline[key] for key in ("old_cutout", "new_cutout", "outer_rectangle")}}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
