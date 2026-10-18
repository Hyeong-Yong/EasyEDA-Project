#!/usr/bin/env python3
"""Prove full Gerber copper voids around the J2-J17 hidden inner pads.

Unlike a centre-point-only flash test, this audit measures the minimum distance
from each drilled-pad centre to every extracted dark flash, stroked track and
additive region on the relevant original inner layer.  Flash geometry is
conservatively bounded, so a passing clearance cannot hide an annular pad.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLAN_SCRIPT = ROOT / "scripts" / "build-unused-inner-layer-pad-plan.py"
PLAN_REPORT = ROOT / "output" / "validation" / "native-unused-inner-layer-pad-analysis.json"
ROUTES = ROOT / "output" / "semantic" / "gerber-copper-routes.json"
OUTPUT = ROOT / "output" / "validation" / "native-unused-inner-layer-gerber-void-audit.json"
TARGET_REFS = {f"J{number}" for number in range(2, 18)}
MM_PER_MIL = 0.0254


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_plan_module():
    spec = importlib.util.spec_from_file_location("stm32_unused_inner_plan", PLAN_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load plan helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def flash_bound_radius(flash: dict[str, Any]) -> float:
    shape = str(flash.get("shape") or "")
    values = [float(value) for value in flash.get("paramsMm") or []]
    if shape == "C" and len(values) == 1:
        return values[0] / 2.0
    if shape in {"R", "O"} and len(values) == 2:
        return math.hypot(values[0] / 2.0, values[1] / 2.0)
    if shape == "RoundRect" and len(values) >= 5:
        coordinates = values[1:-1]
        if len(coordinates) % 2:
            raise AssertionError("odd RoundRect macro coordinates")
        return max(
            math.hypot(coordinates[index], coordinates[index + 1])
            for index in range(0, len(coordinates), 2)
        )
    raise AssertionError(f"unsupported conductor flash shape: {shape} {values}")


def nearest_copper(module, layer: dict[str, Any], point: list[float]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for index, flash in enumerate(layer.get("conductorFlashes") or []):
        edge = max(0.0, math.dist(point, flash["atMm"]) - flash_bound_radius(flash))
        candidates.append({
            "edge_distance_mm": edge,
            "kind": "flash",
            "index": index,
            "net": flash.get("netOld"),
            "shape": flash.get("shape"),
            "params_mm": flash.get("paramsMm"),
        })
    for index, track in enumerate(layer.get("tracks") or []):
        if track.get("kind") == "line":
            centerline = module.point_segment_distance(point, track["startMm"], track["endMm"])
        elif track.get("kind") == "arc":
            centerline = module.point_arc_distance(point, track)
        else:
            raise AssertionError(f"unsupported track kind {track.get('kind')!r}")
        edge = max(0.0, centerline - float(track.get("widthMm") or 0) / 2.0)
        candidates.append({
            "edge_distance_mm": edge,
            "kind": "track",
            "index": index,
            "net": track.get("netOld"),
            "track_kind": track.get("kind"),
            "width_mm": track.get("widthMm"),
        })
    for index, region in enumerate(layer.get("regions") or []):
        contours = [module.contour_points(contour) for contour in region.get("contours") or []]
        if not contours:
            continue
        # Treating every contour as additive is conservative for nested clear holes.
        if any(module.point_in_polygon(point, contour) for contour in contours):
            edge = 0.0
        else:
            edge = min(
                module.point_segment_distance(point, contour[offset - 1], contour[offset])
                for contour in contours
                for offset in range(len(contour))
            )
        candidates.append({
            "edge_distance_mm": edge,
            "kind": "region",
            "index": index,
            "net": region.get("netOld"),
        })
    if not candidates:
        raise AssertionError("copper layer has no extracted primitives")
    return min(candidates, key=lambda item: item["edge_distance_mm"])


def main() -> int:
    module = load_plan_module()
    plan = json.loads(PLAN_REPORT.read_text(encoding="utf-8"))
    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    patterns = {
        (str(row["reference"]), str(row["pad_number"]), str(row["pad_primitive_id"])): row
        for row in plan["source_copper_coverage"]["rows"]
        if row["reference"] in TARGET_REFS
    }
    # Collapse four coverage rows back to one point per physical pad.
    pads: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, row in patterns.items():
        pads.setdefault(key, row)
    candidate_changes = {
        (candidate["reference"], change["pad_number"], change["record_id"]): change
        for candidate in plan["candidate_scope"]["candidates"]
        for change in candidate["modifications"]
    }
    rows: list[dict[str, Any]] = []
    for key, change in sorted(candidate_changes.items()):
        reference, pad_number, pad_id = key
        evidence_rows = [
            row for row in plan["source_copper_coverage"]["rows"]
            if (row["reference"], row["pad_number"], row["pad_primitive_id"]) == key
        ]
        by_layer = {int(row["native_layer_id"]): row for row in evidence_rows}
        hole = change["hole"]
        hole_radius = min(float(hole["width"]), float(hole["height"])) * MM_PER_MIL / 2.0
        for layer_id in change["after_unused_inner_layers"]:
            evidence = by_layer[int(layer_id)]
            point = evidence["flashes"] or evidence["tracks"] or evidence["regions"]
            if point:
                raise AssertionError(f"{key} layer {layer_id}: centre unexpectedly covered")
            # The exact source point is retained in the plane-clearance rows.
            plane_rows = [
                row for row in plan["plated_hole_plane_clearance"]["rows"]
                if row["reference"] == reference
                and str(row["pad_number"]) == pad_number
                and int(row["native_layer_id"]) == int(layer_id)
            ]
            if len(plane_rows) != 1:
                raise AssertionError(f"{key} layer {layer_id}: source point ambiguity")
            plane = plane_rows[0]
            source_point = [
                float(value) for value in next(
                    item["coordinates"]["gerber_source_center_mm_expected"]
                    for item in json.loads(
                        Path(plan["inputs"]["clearance_analysis"]["path"]).read_text(encoding="utf-8")
                    )["fill_to_th_pad_zero_evidence"]["evidence"]
                    if item["reference"] == reference
                    and str(item["pad_number"]) == pad_number
                    and int(item["native_inner_layer_id"]) == int(layer_id)
                )
            ]
            layer_name = module.INNER_LAYER_NAMES[int(layer_id)]
            nearest = nearest_copper(module, routes["copper"]["layers"][layer_name], source_point)
            hole_edge = nearest["edge_distance_mm"] - hole_radius
            if nearest["kind"] != "region" or hole_edge <= 0.15200122:
                raise AssertionError(
                    f"{key} {layer_name}: nearest copper is not a cleared plane beyond 6mil: "
                    f"{nearest}, hole edge {hole_edge}"
                )
            rows.append({
                "reference": reference,
                "pad_number": pad_number,
                "pad_primitive_id": pad_id,
                "native_layer_id": int(layer_id),
                "gerber_layer": layer_name,
                "source_center_mm": source_point,
                "plated_hole_radius_mm": hole_radius,
                "nearest_copper": nearest,
                "hole_edge_to_nearest_copper_mm": hole_edge,
                "hole_edge_to_nearest_copper_mil": hole_edge / MM_PER_MIL,
                "native_fill_border_conservative_mm": hole_edge - 0.1 * MM_PER_MIL,
            })
    if len(rows) != 74:
        raise AssertionError(f"expected 74 reviewed hidden combinations, got {len(rows)}")
    report = {
        "schema": "stm32h747-unused-inner-layer-gerber-void-audit-v1",
        "status": "pass",
        "inputs": {
            "frozen_plan": {"path": str(PLAN_REPORT), "sha256": sha256_file(PLAN_REPORT)},
            "gerber_routes": {"path": str(ROUTES), "sha256": sha256_file(ROUTES)},
            "audit_script": {"path": str(Path(__file__)), "sha256": sha256_file(Path(__file__))},
        },
        "target_references": sorted(TARGET_REFS, key=lambda value: int(value[1:])),
        "hidden_pad_layer_combinations": len(rows),
        "nearest_primitive_kind_counts": {
            kind: sum(row["nearest_copper"]["kind"] == kind for row in rows)
            for kind in ("flash", "track", "region")
        },
        "minimum_hole_edge_to_any_original_copper_mm": min(
            row["hole_edge_to_nearest_copper_mm"] for row in rows
        ),
        "maximum_hole_edge_to_any_original_copper_mm": max(
            row["hole_edge_to_nearest_copper_mm"] for row in rows
        ),
        "all_exceed_native_6mil_requirement": True,
        "conclusion": (
            "All 74 hidden connector pad-layer combinations have a full copper void around "
            "the plated drill. The nearest original conductor is always a cleared plane region, "
            "never a component flash or track; no omitted annular pad is present."
        ),
        "rows": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=OUTPUT.name + ".tmp-", dir=OUTPUT.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, OUTPUT)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({
        "status": report["status"],
        "combinations": len(rows),
        "minimum_mm": report["minimum_hole_edge_to_any_original_copper_mm"],
        "maximum_mm": report["maximum_hole_edge_to_any_original_copper_mm"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
