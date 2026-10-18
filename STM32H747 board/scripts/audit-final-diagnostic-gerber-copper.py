#!/usr/bin/env python3
"""Bounded copper QA for the final diagnostic EasyEDA Gerber export.

This is intentionally narrower than a fabrication-data approval.  It proves
that all six expected copper members are present, that every authoritative
outer-layer component-pad centre has a centred copper flash, and that the two
conversion-sensitive pad families (J2--J17 SMA posts and U5/U7 thermal pads)
serialize with the intended per-layer flash pattern.

No EasyEDA API is called and no project document is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / "output/validation/STM32H747_DIAGNOSTIC_NOT_FOR_FAB.zip"
DEFAULT_DRILL_AUDIT = ROOT / "output/validation/native-final-diagnostic-gerber-drill-audit.json"
DEFAULT_CENTRE_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
DEFAULT_SPECIAL_PLAN = ROOT / "output/validation/u5-u7-special-pad-fix-plan.json"
DEFAULT_REPORT = ROOT / "output/validation/native-final-diagnostic-gerber-copper-audit.json"
PARSER_SCRIPT = ROOT / "scripts/extract_gerber_reconstruction.py"

COPPER_MEMBERS = {
    "F.Cu": "Gerber_TopLayer.GTL",
    "In1.Cu": "Gerber_InnerLayer1.G1",
    "In2.Cu": "Gerber_InnerLayer2.G2",
    "In3.Cu": "Gerber_InnerLayer3.G3",
    "In4.Cu": "Gerber_InnerLayer4.G4",
    "B.Cu": "Gerber_BottomLayer.GBL",
}
OUTER_LAYERS = {"F.Cu", "B.Cu"}
SMA_REFS = {f"J{number}" for number in range(2, 18)}
POSITION_TOLERANCE_MM = 0.002
SHAPE_TOLERANCE_MM = 0.006


class AuditError(RuntimeError):
    """A bounded export invariant was not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_parser():
    spec = importlib.util.spec_from_file_location("stm32_gerber_parser", PARSER_SCRIPT)
    if spec is None or spec.loader is None:
        raise AuditError("cannot load Gerber parser")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def flash_shape(layer: dict[str, Any], flash: dict[str, Any]) -> dict[str, Any]:
    aperture = layer["apertures"].get(str(flash.get("aperture"))) or {}
    return {
        "aperture": flash.get("aperture"),
        "template": aperture.get("template"),
        "params_mm": aperture.get("paramsMm") or [],
        "half_extent_mm": aperture.get("halfExtentMm") or [],
        "function": aperture.get("function"),
    }


def dark_flashes(layer: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        obj for obj in layer["objects"]
        if obj.get("kind") == "flash" and obj.get("polarity") == "dark"
    ]


def centred_flashes(
    layer: dict[str, Any], point: list[float], tolerance_mm: float = POSITION_TOLERANCE_MM
) -> list[dict[str, Any]]:
    rows = []
    for index, flash in enumerate(dark_flashes(layer)):
        distance = math.dist([float(v) for v in flash["atMm"]], point)
        if distance <= tolerance_mm:
            rows.append({
                "object_index": index,
                "at_mm": flash["atMm"],
                "position_error_mm": distance,
                **flash_shape(layer, flash),
            })
    return sorted(rows, key=lambda item: (item["position_error_mm"], str(item["aperture"])))


def source_to_candidate(point: list[float], transform: dict[str, Any]) -> list[float]:
    # The drill report maps candidate -> authoritative.  Invert its signed
    # permutation matrix so this audit uses the independently proven origin.
    matrix = transform["matrix"]
    offset = transform["candidateToAuthoritativeOffsetMm"]
    expected = [float(point[0]) - float(offset[0]), float(point[1]) - float(offset[1])]
    # Signed permutation matrices are orthogonal, so inverse == transpose.
    return [
        matrix[0][0] * expected[0] + matrix[1][0] * expected[1],
        matrix[0][1] * expected[0] + matrix[1][1] * expected[1],
    ]


def aperture_dimensions(row: dict[str, Any]) -> tuple[float, float] | None:
    template = str(row.get("template") or "")
    params = [float(value) for value in row.get("params_mm") or []]
    if template == "C" and params:
        return params[0], params[0]
    if template in {"R", "O"} and len(params) >= 2:
        return params[0], params[1]
    half_extent = [float(value) for value in row.get("half_extent_mm") or []]
    if len(half_extent) >= 2:
        return 2 * half_extent[0], 2 * half_extent[1]
    return None


def comparable_outer_shape(source_flash: dict[str, Any], candidate: dict[str, Any]) -> bool:
    expected = [float(value) for value in source_flash.get("params_mm") or []]
    actual = aperture_dimensions(candidate)
    shape = str(source_flash.get("shape") or "")
    if actual is None or not expected:
        return False
    if shape == "C":
        expected_dims = (expected[0], expected[0])
    elif shape in {"R", "O"} and len(expected) >= 2:
        expected_dims = (expected[0], expected[1])
    else:
        # Macro pads are compared by extracted half extents, not macro spelling.
        if shape == "RoundRect" and len(expected) >= 9:
            radius = abs(expected[0])
            xs = expected[1:9:2]
            ys = expected[2:9:2]
            expected_dims = (
                2 * (max(abs(value) for value in xs) + radius),
                2 * (max(abs(value) for value in ys) + radius),
            )
        elif shape.startswith("Outline") and len(expected) >= 3:
            coords = expected[:-1]
            expected_dims = (
                2 * max(abs(value) for value in coords[0::2]),
                2 * max(abs(value) for value in coords[1::2]),
            )
        else:
            return False
    direct = max(abs(actual[0] - expected_dims[0]), abs(actual[1] - expected_dims[1]))
    swapped = max(abs(actual[1] - expected_dims[0]), abs(actual[0] - expected_dims[1]))
    return min(direct, swapped) <= SHAPE_TOLERANCE_MM


def choose_shape_match(source_flash: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    matching = [row for row in candidates if comparable_outer_shape(source_flash, row)]
    return matching[0] if matching else None


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gerber-zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--drill-audit", type=Path, default=DEFAULT_DRILL_AUDIT)
    parser.add_argument("--centre-audit", type=Path, default=DEFAULT_CENTRE_AUDIT)
    parser.add_argument("--special-plan", type=Path, default=DEFAULT_SPECIAL_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    paths = [args.gerber_zip, args.drill_audit, args.centre_audit, args.special_plan]
    if not all(path.is_file() for path in paths):
        raise AuditError("one or more required inputs do not exist")

    drill = json.loads(args.drill_audit.read_text(encoding="utf-8"))
    centres = json.loads(args.centre_audit.read_text(encoding="utf-8"))
    special = json.loads(args.special_plan.read_text(encoding="utf-8"))
    if not str(drill.get("status", "")).startswith("pass-"):
        raise AuditError("diagnostic drill transform has not passed")
    if not str(centres.get("status", "")).startswith("pass-"):
        raise AuditError("final component-centre audit has not passed")
    transform = drill["coordinateIdentity"]["transform"]
    module = load_parser()

    layers: dict[str, dict[str, Any]] = {}
    member_rows: list[dict[str, Any]] = []
    with zipfile.ZipFile(args.gerber_zip) as archive, tempfile.TemporaryDirectory() as temporary:
        names = set(archive.namelist())
        missing = sorted(set(COPPER_MEMBERS.values()) - names)
        if missing:
            raise AuditError(f"missing copper members: {missing}")
        temporary_path = Path(temporary)
        for layer_name, member in COPPER_MEMBERS.items():
            data = archive.read(member)
            extracted = temporary_path / member
            # EasyEDA 3.2 emits the equivalent legacy aperture-select form
            # ``G54Dnn*``.  The shared source parser accepts canonical ``Dnn*``;
            # normalize selection commands only (coordinates are untouched).
            decoded = data.decode("utf-8", errors="strict")
            normalized = re.sub(r"(?m)^G54D(\d+)\*$", r"D\1*", decoded)
            extracted.write_text(normalized, encoding="utf-8", newline="\n")
            parsed = module.parse_gerber(extracted, layer_name)
            layers[layer_name] = parsed
            counts = Counter(obj["kind"] for obj in parsed["objects"])
            polarity = Counter(obj.get("polarity") for obj in parsed["objects"])
            member_rows.append({
                "layer": layer_name,
                "member": member,
                "bytes": len(data),
                "sha256": sha256_bytes(data),
                "apertures": len(parsed["apertures"]),
                "object_counts": dict(sorted(counts.items())),
                "polarity_counts": dict(sorted(polarity.items(), key=lambda item: str(item[0]))),
                "dark_flash_count": len(dark_flashes(parsed)),
            })

    outer_rows: list[dict[str, Any]] = []
    for expected in centres["matched_component_copper_centres"]:
        for source_flash in expected["source_flashes"]:
            layer_name = str(source_flash["layer"])
            if layer_name not in OUTER_LAYERS:
                continue
            candidate_point = source_to_candidate(expected["source_center_mm"], transform)
            candidates = centred_flashes(layers[layer_name], candidate_point)
            shape_match = choose_shape_match(source_flash, candidates)
            match = candidates[0] if candidates else None
            outer_rows.append({
                "reference": expected["reference"],
                "number": expected["number"],
                "source_center_mm": expected["source_center_mm"],
                "candidate_center_mm": candidate_point,
                "layer": layer_name,
                "source_shape": source_flash,
                "centred_candidate_flash_count": len(candidates),
                "centred_candidate_flashes": candidates,
                "matched_candidate": match,
                "source_shape_dimension_match": shape_match is not None,
                "shape_matched_candidate": shape_match,
                "status": "pass" if match is not None else "missing-centred-flash",
            })
    outer_failures = [row for row in outer_rows if row["status"] != "pass"]

    sma_rows: list[dict[str, Any]] = []
    sma_centres = [
        row for row in centres["matched_component_copper_centres"]
        if row["reference"] in SMA_REFS and str(row["number"]) == "2"
    ]
    if len(sma_centres) != 64:
        raise AuditError(f"expected 64 SMA ground-post centres, got {len(sma_centres)}")
    expected_present = {"F.Cu", "In1.Cu", "In3.Cu", "In4.Cu", "B.Cu"}
    for expected in sma_centres:
        candidate_point = source_to_candidate(expected["source_center_mm"], transform)
        per_layer = {}
        for layer_name in COPPER_MEMBERS:
            candidates = centred_flashes(layers[layer_name], candidate_point)
            # SMA post copper uses a circular 2.5 mm pad in the source.  The
            # exporter may add a 0.00508 mm (0.2 mil) copper expansion.
            annuli = []
            for row in candidates:
                dims = aperture_dimensions(row)
                if row.get("template") == "C" and dims and abs(dims[0] - 2.5) <= SHAPE_TOLERANCE_MM:
                    annuli.append(row)
            per_layer[layer_name] = {
                "centred_flash_count": len(candidates),
                "centred_flashes": candidates,
                "matching_2_5mm_annulus_count": len(annuli),
                "matching_annuli": annuli,
            }
        passed = (
            all(per_layer[layer]["matching_2_5mm_annulus_count"] >= 1 for layer in expected_present)
            and per_layer["In2.Cu"]["matching_2_5mm_annulus_count"] == 0
        )
        sma_rows.append({
            "reference": expected["reference"],
            "number": expected["number"],
            "source_center_mm": expected["source_center_mm"],
            "candidate_center_mm": candidate_point,
            "per_layer": per_layer,
            "status": "pass" if passed else "layer-pattern-mismatch",
        })
    sma_failures = [row for row in sma_rows if row["status"] != "pass"]

    special_plan_by_ref = {row["reference"]: row for row in special["footprints"]}
    expected_special = {"U5": ("25", 2.5), "U7": ("33", 3.45)}
    thermal_rows: list[dict[str, Any]] = []
    for reference, (number, top_size) in expected_special.items():
        expected = next(
            row for row in centres["matched_component_copper_centres"]
            if row["reference"] == reference and str(row["number"]) == number
        )
        candidate_point = source_to_candidate(expected["source_center_mm"], transform)
        per_layer = {}
        for layer_name in COPPER_MEMBERS:
            candidates = centred_flashes(layers[layer_name], candidate_point)
            shape_matches = []
            for row in candidates:
                dims = aperture_dimensions(row)
                if dims is None:
                    continue
                if layer_name == "F.Cu":
                    if row.get("template") in {"R", "O", "RoundRect"} and max(
                        abs(dims[0] - top_size), abs(dims[1] - top_size)
                    ) <= SHAPE_TOLERANCE_MM:
                        shape_matches.append(row)
                elif row.get("template") == "C" and abs(dims[0] - 0.6) <= SHAPE_TOLERANCE_MM:
                    shape_matches.append(row)
            per_layer[layer_name] = {
                "centred_flash_count": len(candidates),
                "centred_flashes": candidates,
                "matching_special_shape_count": len(shape_matches),
                "matching_special_shapes": shape_matches,
            }
        passed = all(per_layer[layer]["matching_special_shape_count"] >= 1 for layer in COPPER_MEMBERS)
        thermal_rows.append({
            "reference": reference,
            "number": number,
            "source_center_mm": expected["source_center_mm"],
            "candidate_center_mm": candidate_point,
            "expected_top_shape_mm": [top_size, top_size],
            "expected_inner_and_bottom_diameter_mm": 0.6,
            "candidate_source_plan_sha256": special_plan_by_ref[reference][
                "authoritative_checkpoint_block_sha256"
            ],
            "per_layer": per_layer,
            "status": "pass" if passed else "special-shape-mismatch",
        })

    thermal_extra_rows: list[dict[str, Any]] = []
    extras = [
        row for row in centres["drill_derived_extra_footprint_pads"]
        if row["reference"] in {"U5", "U7"}
    ]
    if len(extras) != 8:
        raise AuditError(f"expected 8 U5/U7 thermal extra holes, got {len(extras)}")
    for expected in extras:
        # Native board mil is already board-local: convert directly to the
        # candidate Gerber's millimetre coordinates.
        candidate_point = [float(value) * 0.0254 for value in expected["board_center_mil"]]
        per_layer = {}
        for layer_name in COPPER_MEMBERS:
            candidates = centred_flashes(layers[layer_name], candidate_point)
            annuli = []
            for row in candidates:
                dims = aperture_dimensions(row)
                if row.get("template") == "C" and dims and abs(dims[0] - 0.6) <= SHAPE_TOLERANCE_MM:
                    annuli.append(row)
            per_layer[layer_name] = {
                "centred_flashes": candidates,
                "matching_0_6mm_annulus_count": len(annuli),
                "matching_annuli": annuli,
            }
        passed = all(per_layer[layer]["matching_0_6mm_annulus_count"] >= 1 for layer in COPPER_MEMBERS)
        thermal_extra_rows.append({
            "reference": expected["reference"],
            "number": expected["number"],
            "pad_id": expected["pad_id"],
            "candidate_center_mm": candidate_point,
            "per_layer": per_layer,
            "status": "pass" if passed else "thermal-annulus-mismatch",
        })

    failures = {
            "outer_component_pad_centres": len(outer_failures),
        "sma_layer_patterns": len(sma_failures),
        "u5_u7_special_shapes": sum(row["status"] != "pass" for row in thermal_rows),
        "u5_u7_extra_thermal_annuli": sum(
            row["status"] != "pass" for row in thermal_extra_rows
        ),
    }
    passed = not any(failures.values())
    report = {
        "schema": "stm32h747-final-diagnostic-gerber-copper-audit-v1",
        "status": "pass-diagnostic-not-manufacturing-approved" if passed else "fail",
        "manufacturing_approved": False,
        "scope": (
            "Six copper-member presence, authoritative outer component-pad centred flashes, "
            "J2-J17 per-layer post flash pattern, and U5/U7 thermal-pad special shapes only."
        ),
        "inputs": {
            "diagnostic_zip": {
                "path": str(args.gerber_zip.resolve()),
                "sha256": sha256_file(args.gerber_zip),
                "bytes": args.gerber_zip.stat().st_size,
            },
            "drill_transform_audit": {
                "path": str(args.drill_audit.resolve()),
                "sha256": sha256_file(args.drill_audit),
            },
            "component_centre_audit": {
                "path": str(args.centre_audit.resolve()),
                "sha256": sha256_file(args.centre_audit),
            },
            "u5_u7_special_pad_plan": {
                "path": str(args.special_plan.resolve()),
                "sha256": sha256_file(args.special_plan),
            },
            "parser": {"path": str(PARSER_SCRIPT), "sha256": sha256_file(PARSER_SCRIPT)},
            "audit_script": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__)),
            },
        },
        "tolerances_mm": {
            "flash_centre": POSITION_TOLERANCE_MM,
            "aperture_dimension": SHAPE_TOLERANCE_MM,
        },
        "coordinate_transform": transform,
        "copper_members": member_rows,
        "counts": {
            "copper_members": len(member_rows),
            "outer_component_pad_layer_centres": len(outer_rows),
            "outer_component_pad_layer_centres_matched": len(outer_rows) - len(outer_failures),
            "outer_component_pad_layer_centres_with_comparable_shape_dimensions": sum(
                row["source_shape_dimension_match"] for row in outer_rows
            ),
            "sma_ground_post_centres": len(sma_rows),
            "u5_u7_central_special_pads": len(thermal_rows),
            "u5_u7_extra_thermal_pths": len(thermal_extra_rows),
        },
        "failures": failures,
        "checks": {
            "all_six_copper_members_present_and_nonempty": len(member_rows) == 6 and all(
                row["bytes"] > 0 and sum(row["object_counts"].values()) > 0 for row in member_rows
            ),
            "all_authoritative_outer_component_pad_centres_have_centred_flash": not outer_failures,
            "all_64_sma_posts_present_on_f_in1_in3_in4_b_and_absent_as_pad_flash_on_in2": not sma_failures,
            "u5_u7_central_top_rect_and_inner_bottom_0_6mm_annuli_present": all(
                row["status"] == "pass" for row in thermal_rows
            ),
            "u5_u7_eight_extra_thermal_pths_have_0_6mm_annuli_on_all_six_layers": all(
                row["status"] == "pass" for row in thermal_extra_rows
            ),
        },
        "outer_component_pad_layer_centres": outer_rows,
        "sma_j2_j17_post_layer_patterns": sma_rows,
        "u5_u7_central_special_pad_shapes": thermal_rows,
        "u5_u7_extra_thermal_pth_shapes": thermal_extra_rows,
        "limitations": [
            "This diagnostic ZIP remains explicitly NOT_FOR_FAB and this report is not manufacturing approval.",
            "The audit checks centred flashes and named special-pad layer patterns; it is not a full polygon-by-polygon copper equivalence proof.",
            "General outer-pad macro spelling and dimensions are recorded diagnostically but are not used as a pass gate; exact shape gates are limited to the U5/U7 and SMA cases called out in scope.",
            "The In2 SMA assertion is specifically absence of a centred 2.5 mm component-pad flash, not absence of all surrounding plane copper.",
            "Clearance, connectivity, stackup, and drill identity are covered by separate frozen reports.",
        ],
    }
    if report["checks"]["all_six_copper_members_present_and_nonempty"] is False:
        report["status"] = "fail"
    write_json_atomic(args.report.resolve(), report)
    print(json.dumps({
        "status": report["status"],
        "report": str(args.report.resolve()),
        "counts": report["counts"],
        "failures": failures,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0 if report["status"].startswith("pass-") else 1


if __name__ == "__main__":
    raise SystemExit(main())
