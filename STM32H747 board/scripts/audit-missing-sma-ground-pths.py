"""Prove and enumerate the 48 omitted J2..J17 SMA ground-post PTH pads.

The Gerber model groups four physical ground posts under logical pad number 2.
The original library generator selected only one flash per logical pad number,
so three plated holes per connector were omitted.  This static audit emits the
four physical pad-2 children for every SMA connector, identifies the one that
already exists, and derives ``unusedInnerLayers`` independently at each post
from the raw six-layer copper reconstruction.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_thermal_pth_restore_20261014.epro2"
PCB_SOURCE = ROOT / "output/validation/native-final-pcb-after_thermal_pth_restore-reopened.epru"
GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
ROUTES = ROOT / "output/semantic/gerber-copper-routes.json"
LIBRARY = ROOT / "output/native-libraries/manifest.json"
REPORT = ROOT / "output/validation/native-missing-sma-ground-pth-audit.json"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"

TARGETS = tuple(f"J{number}" for number in range(2, 18))
INNER_LAYERS = {15: "In1.Cu", 16: "In2.Cu", 17: "In3.Cu", 18: "In4.Cu"}
MM_TO_MIL = 1000.0 / 25.4
COORD_TOLERANCE_MM = 0.000001
COORD_TOLERANCE_MIL = 0.0002


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value: Any, digits: int = 7) -> int | float:
    result = round(float(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    return math.dist([float(left[0]), float(left[1])], [float(right[0]), float(right[1])])


def parse_record(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header, body = raw.split("||", 1)
    return json.loads(header), json.loads(body[:-1] if body.endswith("|") else body)


def checkpoint_footprints() -> dict[str, list[tuple[dict[str, Any], dict[str, Any]]]]:
    with zipfile.ZipFile(CHECKPOINT) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    current: str | None = None
    for raw in lines:
        header, body = parse_record(raw)
        if header.get("type") == "DOCHEAD":
            current = str(body.get("uuid")) if body.get("docType") == "FOOTPRINT" else None
            if current:
                result[current] = [(header, body)]
        elif current:
            result[current].append((header, body))
    return result


def pcb_reference_map() -> dict[str, dict[str, str]]:
    records = [parse_record(raw) for raw in PCB_SOURCE.read_text(encoding="utf-8-sig").splitlines()]
    attrs: dict[str, dict[str, str]] = defaultdict(dict)
    for header, body in records:
        if header.get("type") != "ATTR":
            continue
        value = body.get("value")
        if value is None:
            value = body.get("blockValue")
        attrs[str(body.get("parentId"))][str(body.get("key"))] = str(value or "")
    result: dict[str, dict[str, str]] = {}
    for header, _body in records:
        if header.get("type") != "COMPONENT":
            continue
        component_id = str(header.get("id"))
        row = attrs.get(component_id, {})
        reference = row.get("Designator", "")
        if reference:
            result[reference] = {
                "component_id": component_id,
                "footprint_uuid": row.get("Footprint", ""),
            }
    return result


def coverage_module():
    path = ROOT / "scripts/build-unused-inner-layer-pad-plan.py"
    spec = importlib.util.spec_from_file_location("unused_inner_layer_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load coverage helper {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def unique_outer_flashes(pad: dict[str, Any]) -> list[dict[str, Any]]:
    flashes = [
        item for item in pad.get("flashes", [])
        if item.get("layer") in {"F.Cu", "B.Cu"}
    ]
    by_position: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    for flash in flashes:
        key = (round(float(flash["atMm"][0]), 6), round(float(flash["atMm"][1]), 6))
        by_position[key].append(flash)
    result: list[dict[str, Any]] = []
    for key, rows in sorted(by_position.items()):
        if {str(row.get("layer")) for row in rows} != {"F.Cu", "B.Cu"}:
            raise AssertionError(f"pad2 {key}: missing F/B flash pair")
        for row in rows:
            if (
                row.get("shape") != "C"
                or [float(value) for value in row.get("paramsMm", [])] != [2.5]
                or row.get("apertureFunction") != "ComponentPad"
                or row.get("polarity") != "dark"
            ):
                raise AssertionError(f"pad2 {key}: unexpected outer copper {row!r}")
            holes = row.get("holes") or []
            if len(holes) != 1 or holes[0].get("diameterMm") != 1.5:
                raise AssertionError(f"pad2 {key}: unexpected attached drill evidence")
        result.append({"at_mm": list(key), "outer_flashes": rows})
    if len(result) != 4:
        raise AssertionError(f"logical pad2 has {len(result)} physical positions, expected 4")
    return result


def main() -> int:
    for path in (CHECKPOINT, PCB_SOURCE, GERBER, ROUTES, LIBRARY):
        if not path.is_file():
            raise FileNotFoundError(path)
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    library = json.loads(LIBRARY.read_text(encoding="utf-8"))
    footprints = checkpoint_footprints()
    pcb_map = pcb_reference_map()
    coverage = coverage_module()
    pth = next(item for item in gerber["drills"] if "PTH.drl" in item["file"])
    t12_holes = [
        item for item in pth["holes"]
        if item.get("kind") != "slot"
        and item.get("tool") == "T12"
        and item.get("function") == "Plated,PTH,ComponentDrill"
        and item.get("plated") is True
        and float(item.get("diameterMm")) == 1.5
    ]
    if len(t12_holes) != 80:
        raise AssertionError(f"expected 80 T12 SMA component holes, found {len(t12_holes)}")

    reports: list[dict[str, Any]] = []
    all_positions: list[tuple[float, float]] = []
    missing_rows: list[dict[str, Any]] = []
    for reference in TARGETS:
        component = gerber["components"][reference]
        pad2 = component["pads"]["2"]
        source_footprint = library["footprints"][reference]
        anchor = [float(value) for value in source_footprint["anchor_mm"]]
        imported_uuid = pcb_map[reference]["footprint_uuid"]
        native_rows = footprints[imported_uuid]
        native_pad2 = [
            (header, body) for header, body in native_rows
            if header.get("type") == "PAD" and str(body.get("num") or "") == "2"
        ]
        if len(native_pad2) != 1:
            raise AssertionError(f"{reference}: expected current one physical pad2, found {len(native_pad2)}")
        existing_header, existing_body = native_pad2[0]
        physical: list[dict[str, Any]] = []
        existing_matches = 0
        for item in unique_outer_flashes(pad2):
            at = item["at_mm"]
            matching_holes = [hole for hole in t12_holes if distance(hole["atMm"], at) <= COORD_TOLERANCE_MM]
            if len(matching_holes) != 1:
                raise AssertionError(f"{reference} {at}: expected one T12 drill")
            local = [
                clean((at[0] - anchor[0]) * MM_TO_MIL),
                clean((at[1] - anchor[1]) * MM_TO_MIL),
            ]
            is_existing = (
                distance(local, [existing_body.get("centerX"), existing_body.get("centerY")])
                <= COORD_TOLERANCE_MIL
            )
            existing_matches += int(is_existing)
            layer_rows: list[dict[str, Any]] = []
            unused: list[int] = []
            for layer_id, layer_name in INNER_LAYERS.items():
                evidence = coverage.source_copper_coverage(routes, layer_name, at)
                if not evidence["covered"]:
                    unused.append(layer_id)
                layer_rows.append({
                    "layer_id": layer_id,
                    "layer_name": layer_name,
                    **evidence,
                })
            row = {
                "reference": reference,
                "pad_number": "2",
                "source_at_mm": at,
                "footprint_anchor_mm": anchor,
                "footprint_local_center_mil_y_up": local,
                "existing_native_pad": is_existing,
                "existing_native_record_id": str(existing_header.get("id")) if is_existing else None,
                "net": "GND",
                "layer_id": 12,
                "plated": True,
                "hole": {"holeType": "ROUND", "width": 59.055118, "height": 59.055118},
                "default_pad": {"padType": "ELLIPSE", "width": 98.425197, "height": 98.425197},
                "unused_inner_layers": unused,
                "inner_layer_copper_evidence": layer_rows,
                "drill": matching_holes[0],
                "outer_flashes": item["outer_flashes"],
            }
            physical.append(row)
            all_positions.append((at[0], at[1]))
            if not is_existing:
                missing_rows.append(row)
        if existing_matches != 1:
            raise AssertionError(f"{reference}: current pad2 matches {existing_matches} physical posts")
        existing_expected = next(item for item in physical if item["existing_native_pad"])
        current_unused = [int(value) for value in (existing_body.get("unusedInnerLayers") or [])]
        if current_unused != existing_expected["unused_inner_layers"]:
            raise AssertionError(
                f"{reference}: existing pad2 unusedInnerLayers {current_unused} "
                f"!= per-position Gerber evidence {existing_expected['unused_inner_layers']}"
            )
        reports.append({
            "reference": reference,
            "component_id": pcb_map[reference]["component_id"],
            "footprint_uuid": imported_uuid,
            "current_pad2_record_id": str(existing_header.get("id")),
            "current_pad2_unused_inner_layers": current_unused,
            "physical_pad2_count": len(physical),
            "missing_physical_pad2_count": sum(not item["existing_native_pad"] for item in physical),
            "physical_pad2": physical,
        })

    if len(all_positions) != len(set(all_positions)) or len(all_positions) != 64:
        raise AssertionError("SMA ground-post source positions are not 64 unique coordinates")
    if len(missing_rows) != 48:
        raise AssertionError(f"expected 48 omitted ground posts, found {len(missing_rows)}")
    pattern_counts = Counter(tuple(row["unused_inner_layers"]) for row in missing_rows)
    report = {
        "status": "fail-final-manufacturing-gate-48-sma-pths-omitted",
        "purpose": "Exact physical enumeration and per-position copper-layer evidence for J2-J17 SMA pad2",
        "inputs": {
            "checkpoint": {"path": str(CHECKPOINT.relative_to(ROOT)), "sha256": sha256(CHECKPOINT)},
            "pcb_source": {"path": str(PCB_SOURCE.relative_to(ROOT)), "sha256": sha256(PCB_SOURCE)},
            "gerber_manifest": {"path": str(GERBER.relative_to(ROOT)), "sha256": sha256(GERBER)},
            "route_manifest": {"path": str(ROUTES.relative_to(ROOT)), "sha256": sha256(ROUTES)},
            "library_manifest": {"path": str(LIBRARY.relative_to(ROOT)), "sha256": sha256(LIBRARY)},
        },
        "source_contract": {
            "references": list(TARGETS),
            "logical_pad_number": "2",
            "net": "GND",
            "physical_posts_per_reference": 4,
            "hole_diameter_mm": 1.5,
            "copper_diameter_mm": 2.5,
            "plated": True,
            "multilayer_native_layer_id": 12,
        },
        "totals": {
            "authoritative_t12_component_holes": len(t12_holes),
            "sma_references": len(reports),
            "physical_sma_holes": 80,
            "physical_pad1_holes": 16,
            "physical_pad2_ground_posts": len(all_positions),
            "existing_native_pad2_posts": len(all_positions) - len(missing_rows),
            "omitted_native_pad2_posts": len(missing_rows),
            "expected_round_component_pths_before_thermal_repair": 125,
            "native_round_component_pths_before_thermal_repair": 77,
            "thermal_pths_restored_separately": 8,
            "remaining_round_component_pth_deficit": 48,
        },
        "missing_unused_inner_layer_patterns": [
            {"unused_inner_layers": list(pattern), "count": count}
            for pattern, count in sorted(pattern_counts.items())
        ],
        "footprints": reports,
        "missing_pad_records": missing_rows,
        "checks": {
            "all_80_t12_component_drills_accounted_as_16_times_5": True,
            "all_64_pad2_positions_have_exact_f_b_2_5mm_component_pad_flashes": True,
            "each_pad2_position_has_one_1_5mm_plated_component_drill": True,
            "only_one_of_four_pad2_positions_exists_per_native_footprint": True,
            "exact_missing_count_is_48": True,
            "unused_inner_layers_derived_independently_for_each_physical_post": True,
            "existing_pad2_masks_equal_per_position_gerber_evidence": True,
        },
        "required_fix": {
            "model": "three additional duplicate-number plated multilayer PAD children per J2-J17 footprint",
            "pad_number": "2",
            "net_after_pcb_binding": "GND",
            "preserve": ["1.5mm plated drill", "2.5mm outer copper", "world coordinate", "component ownership"],
            "per_child_field": "unusedInnerLayers from missing_pad_records[].unused_inner_layers",
            "post_fix_gate": [
                "native component round PTH count 133",
                "all 133 one-to-one match authoritative Excellon component round hits",
                "PAD_NET children exist for all 48 new PAD IDs and bind to GND",
                "DRC Connection Error remains zero",
                "diagnostic native drill export contains 767 round PTH + 13 plated slots + 13 NPTH",
            ],
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT.relative_to(ROOT)),
        "sha256": sha256(REPORT),
        "totals": report["totals"],
        "missing_unused_inner_layer_patterns": report["missing_unused_inner_layer_patterns"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
