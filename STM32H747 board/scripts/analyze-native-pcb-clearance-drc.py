#!/usr/bin/env python3
"""Analyze EasyEDA clearance DRC results against the Gerber job minimum."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_DRC = (
    ROOT / "output" / "validation" / "native-pcb-drc-0ac2a19168000d8e.json"
)
DEFAULT_SOURCE = (
    ROOT / "output" / "validation" / "native-final-pcb-associated-reopened.epru"
)
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_final_pcb_association_20261014.epro2"
)
DEFAULT_GERBER_FOOTPRINTS = (
    ROOT / "output" / "semantic" / "gerber-component-footprints.json"
)
DEFAULT_JOB = (
    ROOT / "보드 자료" / "MCU_BOARD_v19_260616_Gerber" /
    "MCU_BOARD_v19_260616-job.gbrjob"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" / "native-pcb-clearance-drc-final-analysis.json"
)
DISPLAY_MIL_PER_RAW_UNIT = 10.0
MM_PER_MIL = 0.0254
BOARD_SOURCE_MIN_X_MM = 147.46
BOARD_SOURCE_MIN_Y_MM = -218.96
NATIVE_INNER_LAYER_TO_GERBER = {
    15: "In1.Cu",
    16: "In2.Cu",
    17: "In3.Cu",
    18: "In4.Cu",
}


def load_helpers() -> Any:
    path = ROOT / "scripts" / "audit-native-pcb-staging-checkpoint.py"
    spec = importlib.util.spec_from_file_location("clearance_drc_native_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load native source helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPERS = load_helpers()


def load_project_helpers() -> Any:
    path = ROOT / "scripts" / "audit-pcb-replacement-safety.py"
    spec = importlib.util.spec_from_file_location("clearance_drc_project_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load checkpoint helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROJECT_HELPERS = load_project_helpers()
NET_RE = re.compile(r"^\((.*?)\):")
MIL_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*mil\s*$", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def safe_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def atomic_write_text(path: Path, value: str) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def iter_error_items(value: Any, hierarchy: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], dict[str, Any]]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield hierarchy, value
            return
        name = str(value.get("name") or "")
        next_hierarchy = hierarchy + ((name,) if name else ())
        for key, child in value.items():
            if key == "list":
                yield from iter_error_items(child, next_hierarchy)
    elif isinstance(value, list):
        for child in value:
            yield from iter_error_items(child, hierarchy)


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is non-finite: {value!r}")
    return result


def net_from_suffix(value: Any) -> str:
    text = str(value or "")
    match = NET_RE.match(text)
    return match.group(1) if match else ""


def net_relationship(nets: Sequence[str]) -> str:
    """Classify the two display-net labels without guessing missing labels."""
    if len(nets) != 2:
        raise ValueError(f"expected two nets, got {nets!r}")
    left, right = nets
    if left and right:
        return "same_nonempty" if left == right else "different_nonempty"
    if left or right:
        return "one_missing"
    return "both_missing"


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def summary_stats(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "p10": percentile(values, 0.10),
        "median": statistics.median(values) if values else None,
        "p90": percentile(values, 0.90),
        "max": max(values) if values else None,
    }


def counter_rows(counter: Counter[Any], limit: int | None = None) -> list[dict[str, Any]]:
    rows = [
        {"value": value, "count": count}
        for value, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    ]
    return rows if limit is None else rows[:limit]


def bin_label(distance_mm: float) -> str:
    if distance_mm < 0:
        return "negative"
    if distance_mm == 0:
        return "zero"
    bounds = (0.025, 0.050, 0.075, 0.100, 0.125, 0.152)
    lower = 0.0
    for upper in bounds:
        if distance_mm < upper:
            return f"({lower:.3f},{upper:.3f})"
        lower = upper
    return ">=0.152"


def parse_pad_net_id(record_id: str) -> tuple[str, str, str] | None:
    try:
        value = json.loads(record_id)
    except (TypeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or value[0] != "PAD_NET"
    ):
        return None
    return str(value[1]), str(value[2]), str(value[3])


def rotate_point(x: float, y: float, angle_degrees: float) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return x * cosine - y * sine, x * sine + y * cosine


def point_distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.hypot(float(left[0]) - float(right[0]), float(left[1]) - float(right[1]))


def build_th_pad_evidence(
    rows: list[dict[str, Any]],
    source_records: list[Any],
    checkpoint: Path,
    gerber_payload: dict[str, Any],
) -> dict[str, Any]:
    """Join zero-distance FILL/TH findings to native pads and Gerber flashes."""
    documents, _project2, _entries = PROJECT_HELPERS.parse_documents(checkpoint)
    footprint_documents = {
        document["uuid"]: document
        for document in documents
        if document["doc_type"] == "FOOTPRINT"
    }
    components = {
        record.record_id: record
        for record in source_records
        if record.kind == "COMPONENT"
    }
    attrs: dict[str, dict[str, Any]] = defaultdict(dict)
    for record in source_records:
        if record.kind != "ATTR":
            continue
        parent_id = str(record.body.get("parentId") or "")
        key = str(record.body.get("key") or "")
        if parent_id and key:
            attrs[parent_id][key] = record.body.get("value")
    pad_net_by_object_id: dict[str, dict[str, Any]] = {}
    for record in source_records:
        if record.kind != "PAD_NET":
            continue
        parsed = parse_pad_net_id(record.record_id)
        if parsed is None:
            continue
        component_id, pad_number, pad_primitive_id = parsed
        object_id = component_id + pad_primitive_id
        if object_id in pad_net_by_object_id:
            raise AssertionError(f"ambiguous composed PAD object id: {object_id}")
        pad_net_by_object_id[object_id] = {
            "component_id": component_id,
            "pad_number": pad_number,
            "pad_primitive_id": pad_primitive_id,
            "pad_net": str(record.body.get("padNet") or ""),
            "pad_net_record_id": record.record_id,
        }

    gerber_components = gerber_payload.get("components") or {}
    apertures_by_layer = gerber_payload.get("aperturesByLayer") or {}
    target_evidence_count = sum(
        row["object_pair"] == "Fill Region to TH Pad" and row["actual_mm"] <= 0
        for row in rows
    )
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in rows:
        if row["object_pair"] != "Fill Region to TH Pad" or row["actual_mm"] > 0:
            continue
        pad_indexes = [
            index
            for index, reported_type in enumerate(row["reported_types"])
            if reported_type == "TH Pad"
        ]
        if len(pad_indexes) != 1:
            raise AssertionError(f"TH Pad index ambiguity: {row['global_index']}")
        pad_index = pad_indexes[0]
        pad_object_id = row["object_ids"][pad_index]
        pad_net = pad_net_by_object_id.get(pad_object_id)
        if pad_net is None:
            unresolved.append({
                "global_index": row["global_index"],
                "pad_object_id": pad_object_id,
                "reason": "PAD_NET composed ID not found",
            })
            continue
        component_id = pad_net["component_id"]
        component = components.get(component_id)
        if component is None:
            unresolved.append({
                "global_index": row["global_index"],
                "pad_object_id": pad_object_id,
                "reason": "COMPONENT not found",
            })
            continue
        designator = str(attrs.get(component_id, {}).get("Designator") or "")
        footprint_uuid = str(attrs.get(component_id, {}).get("Footprint") or "")
        footprint = footprint_documents.get(footprint_uuid)
        if footprint is None:
            unresolved.append({
                "global_index": row["global_index"],
                "pad_object_id": pad_object_id,
                "reason": f"project FOOTPRINT not found: {footprint_uuid}",
            })
            continue
        footprint_pads = {
            record.record_id: record
            for record in footprint["records"]
            if record.kind == "PAD"
        }
        native_pad = footprint_pads.get(pad_net["pad_primitive_id"])
        if native_pad is None:
            unresolved.append({
                "global_index": row["global_index"],
                "pad_object_id": pad_object_id,
                "reason": f"footprint PAD not found: {pad_net['pad_primitive_id']}",
            })
            continue
        if str(native_pad.body.get("num") or "") != pad_net["pad_number"]:
            raise AssertionError(f"PAD number mismatch: {pad_object_id}")
        component_x = finite(component.body.get("x"), "component x")
        component_y = finite(component.body.get("y"), "component y")
        component_angle = finite(component.body.get("angle", 0), "component angle")
        local_x = finite(native_pad.body.get("centerX"), "pad centerX")
        local_y = finite(native_pad.body.get("centerY"), "pad centerY")
        rotated_x, rotated_y = rotate_point(local_x, local_y, component_angle)
        board_x_mil = component_x + rotated_x
        board_y_mil = component_y + rotated_y
        source_point_mm = [
            BOARD_SOURCE_MIN_X_MM + board_x_mil * MM_PER_MIL,
            BOARD_SOURCE_MIN_Y_MM + board_y_mil * MM_PER_MIL,
        ]
        gerber_component = gerber_components.get(designator) or {}
        gerber_pad = (gerber_component.get("pads") or {}).get(pad_net["pad_number"]) or {}
        outer_flashes = [
            flash
            for flash in (gerber_pad.get("flashes") or [])
            if isinstance(flash.get("atMm"), list) and len(flash["atMm"]) == 2
        ]
        nearest_outer = min(
            outer_flashes,
            key=lambda flash: point_distance(flash["atMm"], source_point_mm),
            default=None,
        )
        nearest_outer_distance = (
            point_distance(nearest_outer["atMm"], source_point_mm)
            if nearest_outer is not None else None
        )
        native_layer_id = int(row["layer_ids"][0])
        gerber_layer = NATIVE_INNER_LAYER_TO_GERBER.get(native_layer_id, "")
        gerber_inner_layer_scan: dict[str, Any] = {}
        for scan_layer_id, scan_layer_name in NATIVE_INNER_LAYER_TO_GERBER.items():
            layer_geometry = (gerber_component.get("layerGeometry") or {}).get(
                scan_layer_name, []
            )
            candidate_inner_flashes = [
                item
                for item in layer_geometry
                if item.get("kind") == "flash"
                and isinstance(item.get("atMm"), list)
                and len(item["atMm"]) == 2
            ]
            nearest = min(
                candidate_inner_flashes,
                key=lambda item: point_distance(item["atMm"], source_point_mm),
                default=None,
            )
            distance = (
                point_distance(nearest["atMm"], source_point_mm)
                if nearest is not None else None
            )
            present = distance is not None and distance <= 0.01
            aperture = None
            if present:
                aperture = apertures_by_layer.get(scan_layer_name, {}).get(
                    str(nearest.get("aperture") or "")
                )
            gerber_inner_layer_scan[str(scan_layer_id)] = {
                "gerber_layer": scan_layer_name,
                "flash_present_at_pad_center": present,
                "nearest_flash_distance_mm": distance,
                "flash": nearest if present else None,
                "aperture_definition": aperture,
            }
        selected_inner = gerber_inner_layer_scan[str(native_layer_id)]
        inner_flash_present = bool(selected_inner["flash_present_at_pad_center"])
        default_pad = native_pad.body.get("defaultPad") or {}
        unused_inner_layers = native_pad.body.get("unusedInnerLayers") or []
        hole = native_pad.body.get("hole") or {}
        footprint_meta = PROJECT_HELPERS.document_meta(footprint)
        evidence.append({
            "global_index": row["global_index"],
            "fill_id": row["fill_ids"][0] if row["fill_ids"] else "",
            "fill_net": row["nets"][0 if pad_index == 1 else 1],
            "pad_object_id": pad_object_id,
            "component_id": component_id,
            "reference": designator,
            "pad_number": pad_net["pad_number"],
            "pad_primitive_id": pad_net["pad_primitive_id"],
            "pad_net": pad_net["pad_net"],
            "footprint_uuid": footprint_uuid,
            "footprint_title": footprint_meta.get("title"),
            "component_layer_id": component.body.get("layerId"),
            "component_angle": component_angle,
            "native_inner_layer_id": native_layer_id,
            "gerber_inner_layer": gerber_layer,
            "native_pad": {
                "layer_id": native_pad.body.get("layerId"),
                "pad_type": native_pad.body.get("padType"),
                "plated": native_pad.body.get("plated"),
                "hole": hole,
                "default_pad": default_pad,
                "default_pad_size_mm": {
                    "width": (
                        finite(default_pad.get("width", 0), "default pad width")
                        * MM_PER_MIL
                    ),
                    "height": (
                        finite(default_pad.get("height", 0), "default pad height")
                        * MM_PER_MIL
                    ),
                },
                "special_pad": native_pad.body.get("specialPad"),
                "unused_inner_layers": unused_inner_layers,
            },
            "coordinates": {
                "native_local_center_mil": [local_x, local_y],
                "native_board_center_mil": [board_x_mil, board_y_mil],
                "gerber_source_center_mm_expected": source_point_mm,
                "nearest_outer_pad_flash_mm": (
                    nearest_outer.get("atMm") if nearest_outer else None
                ),
                "nearest_outer_pad_flash_distance_mm": nearest_outer_distance,
            },
            "gerber_outer_pad": {
                "shape": nearest_outer.get("shape") if nearest_outer else None,
                "params_mm": nearest_outer.get("paramsMm") if nearest_outer else None,
                "holes": nearest_outer.get("holes") if nearest_outer else None,
            },
            "gerber_inner_pad": {
                **selected_inner,
                "all_inner_layers": gerber_inner_layer_scan,
                "gerber_absent_native_layer_ids": [
                    int(layer_id)
                    for layer_id, scan in gerber_inner_layer_scan.items()
                    if not scan["flash_present_at_pad_center"]
                ],
                "gerber_present_native_layer_ids": [
                    int(layer_id)
                    for layer_id, scan in gerber_inner_layer_scan.items()
                    if scan["flash_present_at_pad_center"]
                ],
            },
            "cause_indicator": (
                "gerber_inner_flash_absent_but_native_th_pad_has_no_unused_inner_layer"
                if not inner_flash_present and not unused_inner_layers
                else "requires_geometry_review"
            ),
        })

    if unresolved:
        raise AssertionError(f"unresolved FILL/TH evidence rows: {unresolved[:5]}")
    if len(evidence) != target_evidence_count:
        raise AssertionError(
            f"FILL/TH nonpositive evidence count={len(evidence)}, "
            f"expected from current DRC={target_evidence_count}"
        )
    reference_groups = Counter(item["reference"] for item in evidence)
    pad_groups = Counter(
        (item["reference"], item["pad_number"], item["pad_primitive_id"])
        for item in evidence
    )
    pad_group_rows: list[dict[str, Any]] = []
    absent_layer_pattern_pad_counts: Counter[str] = Counter()
    absent_layer_pattern_error_counts: Counter[str] = Counter()
    evidence_by_pad: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        key = (item["reference"], item["pad_number"], item["pad_primitive_id"])
        evidence_by_pad[key].append(item)
    for key, values in sorted(evidence_by_pad.items()):
        example = values[0]
        absent_layers = example["gerber_inner_pad"]["gerber_absent_native_layer_ids"]
        present_layers = example["gerber_inner_pad"]["gerber_present_native_layer_ids"]
        pattern = compact(absent_layers)
        absent_layer_pattern_pad_counts[pattern] += 1
        absent_layer_pattern_error_counts[pattern] += len(values)
        pad_group_rows.append({
            "reference": key[0],
            "pad_number": key[1],
            "pad_primitive_id": key[2],
            "clearance_error_count": len(values),
            "error_native_layer_ids": sorted({
                int(value["native_inner_layer_id"]) for value in values
            }),
            "fill_nets": sorted({str(value["fill_net"]) for value in values}),
            "pad_net": example["pad_net"],
            "footprint_uuid": example["footprint_uuid"],
            "native_pad": example["native_pad"],
            "gerber_outer_pad": example["gerber_outer_pad"],
            "gerber_present_native_layer_ids": present_layers,
            "gerber_absent_native_layer_ids": absent_layers,
        })
    gerber_flash_presence = Counter(
        "present" if item["gerber_inner_pad"]["flash_present_at_pad_center"] else "absent"
        for item in evidence
    )
    cause_groups = Counter(item["cause_indicator"] for item in evidence)
    return {
        "count": len(evidence),
        "distinct_references": len(reference_groups),
        "distinct_reference_pad_ids": len(pad_groups),
        "reference_counts": counter_rows(reference_groups),
        "reference_pad_counts": [
            {
                "reference": key[0],
                "pad_number": key[1],
                "pad_primitive_id": key[2],
                "count": count,
            }
            for key, count in sorted(
                pad_groups.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "reference_pad_layer_patterns": pad_group_rows,
        "gerber_absent_inner_layer_pattern_distinct_pad_counts": counter_rows(
            absent_layer_pattern_pad_counts
        ),
        "gerber_absent_inner_layer_pattern_clearance_error_counts": counter_rows(
            absent_layer_pattern_error_counts
        ),
        "native_default_pad_types": counter_rows(Counter(
            str(item["native_pad"]["default_pad"].get("padType") or "")
            for item in evidence
        )),
        "native_hole_types": counter_rows(Counter(
            str(item["native_pad"]["hole"].get("holeType") or "")
            for item in evidence
        )),
        "native_unused_inner_layers": counter_rows(Counter(
            compact(item["native_pad"]["unused_inner_layers"])
            for item in evidence
        )),
        "gerber_inner_flash_at_pad_center": counter_rows(gerber_flash_presence),
        "cause_indicators": counter_rows(cause_groups),
        "outer_flash_match_distance_mm": summary_stats([
            float(item["coordinates"]["nearest_outer_pad_flash_distance_mm"])
            for item in evidence
            if item["coordinates"]["nearest_outer_pad_flash_distance_mm"] is not None
        ]),
        "evidence": evidence,
        "interpretation": (
            "This is a static representation comparison. An absent inner-layer Gerber pad "
            "flash plus an empty native unusedInnerLayers list is evidence that the imported "
            "through-hole default pad is instantiated on a layer where the archived Gerber "
            "did not emit that component-pad flash. It identifies a likely conversion cause; "
            "it is not permission to suppress DRC or alter the pad without layout review."
        ),
    }


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    for path in (
        args.drc,
        args.source,
        args.checkpoint,
        args.gerber_footprints,
        args.job,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    payload = json.loads(args.drc.read_text(encoding="utf-8-sig"))
    gerber_payload = json.loads(
        args.gerber_footprints.read_text(encoding="utf-8-sig")
    )
    job_payload = json.loads(args.job.read_text(encoding="utf-8-sig"))
    source_records = HELPERS.parse_source(args.source)
    source_by_id = {
        record.record_id: record for record in source_records if record.record_id
    }
    raw_items = list(iter_error_items(payload.get("details", [])))
    clearance_items = [
        (hierarchy, item) for hierarchy, item in raw_items
        if item.get("errorType") == "Clearance Error"
    ]
    rows: list[dict[str, Any]] = []
    display_distance_errors_mil: list[float] = []
    display_required_errors_mil: list[float] = []
    unresolved_ids = Counter()
    fill_widths = Counter()
    for hierarchy, item in clearance_items:
        err = item["explanation"]["errData"]
        actual_raw = finite(err.get("minDistance"), "minDistance")
        required_raw = finite(err.get("clearance"), "clearance")
        actual_mil = actual_raw * DISPLAY_MIL_PER_RAW_UNIT
        required_mil = required_raw * DISPLAY_MIL_PER_RAW_UNIT
        actual_mm = actual_mil * MM_PER_MIL
        required_mm = required_mil * MM_PER_MIL
        param = item.get("explanation", {}).get("param", {})
        displayed_actual = MIL_RE.match(str(param.get("minDistance") or ""))
        displayed_required = re.search(
            r"(-?\d+(?:\.\d+)?)\s*mil",
            str(param.get("shouldBe") or ""),
            re.IGNORECASE,
        )
        if displayed_actual:
            display_distance_errors_mil.append(
                abs(float(displayed_actual.group(1)) - actual_mil)
            )
        if displayed_required:
            display_required_errors_mil.append(
                abs(float(displayed_required.group(1)) - required_mil)
            )
        obj_ids = [str(err.get("obj1") or ""), str(err.get("obj2") or "")]
        obj_types = [str(err.get("obj1Type") or ""), str(err.get("obj2Type") or "")]
        suffixes = [str(err.get("obj1Suffix") or ""), str(err.get("obj2Suffix") or "")]
        nets = [net_from_suffix(suffix) for suffix in suffixes]
        resolved_types: list[str] = []
        fill_half_width_total_mil = 0.0
        fill_ids: list[str] = []
        for object_id, reported_type in zip(obj_ids, obj_types):
            record = source_by_id.get(object_id)
            if record is None:
                unresolved_ids[reported_type or "UNKNOWN"] += 1
                resolved_types.append("")
                continue
            resolved_types.append(record.kind)
            if record.kind == "FILL":
                width_mil = finite(record.body.get("width", 0), "FILL width")
                fill_widths[round(width_mil, 6)] += 1
                fill_half_width_total_mil += width_mil / 2.0
                fill_ids.append(object_id)
        corrected_for_fill_border_mm = (
            actual_mil + fill_half_width_total_mil
        ) * MM_PER_MIL
        rows.append({
            "global_index": str(err.get("globalIndex") or item.get("globalIndex") or ""),
            "hierarchy": list(hierarchy),
            "object_pair": str(item.get("errorObjType") or ""),
            "reported_types": obj_types,
            "resolved_native_types": resolved_types,
            "object_ids": obj_ids,
            "object_suffixes": suffixes,
            "nets": nets,
            "net_pair": " | ".join(sorted(nets)),
            "net_relationship": net_relationship(nets),
            "layer": str(item.get("layer") or ""),
            "layer_ids": list(err.get("layerIds") or []),
            "rule_name": str(item.get("ruleName") or err.get("name") or ""),
            "actual_raw": actual_raw,
            "actual_mil": actual_mil,
            "actual_mm": actual_mm,
            "required_raw": required_raw,
            "required_mil": required_mil,
            "required_mm": required_mm,
            "fill_ids": fill_ids,
            "fill_half_width_total_mil": fill_half_width_total_mil,
            "fill_border_corrected_mm_sensitivity": corrected_for_fill_border_mm,
        })

    if len(rows) != args.expected_clearance_count:
        raise AssertionError(
            f"clearance count={len(rows)}, expected={args.expected_clearance_count}"
        )
    actual_mm = [row["actual_mm"] for row in rows]
    positive = [value for value in actual_mm if value > 0]
    negative_count = sum(value < 0 for value in actual_mm)
    zero_count = sum(value == 0 for value in actual_mm)
    nonpositive_count = negative_count + zero_count
    positive_below_010 = sum(0 < value < args.gerber_min_clearance_mm for value in actual_mm)
    positive_010_to_0152 = sum(
        args.gerber_min_clearance_mm <= value < 0.152 for value in actual_mm
    )
    at_least_010 = sum(value >= args.gerber_min_clearance_mm for value in actual_mm)
    below_010 = sum(value < args.gerber_min_clearance_mm for value in actual_mm)
    positive_below_0152 = sum(0 < value < 0.152 for value in actual_mm)
    fill_rows = [row for row in rows if row["fill_ids"]]
    fill_flip_010 = [
        row for row in fill_rows
        if row["actual_mm"] < args.gerber_min_clearance_mm
        <= row["fill_border_corrected_mm_sensitivity"]
    ]

    fill_drc_rows_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fill_rows:
        for fill_id in row["fill_ids"]:
            fill_drc_rows_by_id[fill_id].append(row)
    fill_native_summaries = []
    for fill_id, values in sorted(
        fill_drc_rows_by_id.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        record = source_by_id[fill_id]
        paths = record.body.get("path")
        path_items = paths if isinstance(paths, list) else []
        command_counts = Counter(
            str(value)
            for path in path_items
            if isinstance(path, list)
            for value in path
            if isinstance(value, str)
        )
        fill_native_summaries.append({
            "id": fill_id,
            "net_name": str(record.body.get("netName") or ""),
            "layer_id": record.body.get("layerId"),
            "width_mil": record.body.get("width"),
            "fill_style": record.body.get("fillStyle"),
            "path_count": len(path_items),
            "path_command_counts": dict(sorted(command_counts.items())),
            "network_list": record.body.get("networkList"),
            "clearance_error_count": len(values),
            "nonpositive_count": sum(row["actual_mm"] <= 0 for row in values),
            "below_gerber_0_10mm": sum(
                row["actual_mm"] < args.gerber_min_clearance_mm for row in values
            ),
            "layers_reported": counter_rows(Counter(row["layer"] for row in values)),
            "opposing_net_relationships": counter_rows(
                Counter(row["net_relationship"] for row in values)
            ),
            "opposing_net_pairs": counter_rows(
                Counter(row["net_pair"] for row in values), 30
            ),
        })

    type_groups = Counter(row["object_pair"] for row in rows)
    native_type_groups = Counter(
        " to ".join(sorted(value or "UNRESOLVED" for value in row["resolved_native_types"]))
        for row in rows
    )
    layer_groups = Counter(row["layer"] for row in rows)
    rule_groups = Counter(row["rule_name"] for row in rows)
    required_groups = Counter(round(row["required_mm"], 6) for row in rows)
    actual_value_groups = Counter(round(row["actual_mm"], 6) for row in rows)
    distance_bins = Counter(bin_label(value) for value in actual_mm)
    net_pair_groups = Counter(row["net_pair"] for row in rows)
    net_relationship_groups = Counter(row["net_relationship"] for row in rows)
    unique_pair_layer = {
        (
            tuple(sorted(row["object_ids"])),
            tuple(row["layer_ids"]),
        )
        for row in rows
    }
    per_group = {}
    for group_name, key_getter in {
        "object_pair": lambda row: row["object_pair"],
        "native_type_pair": lambda row: " to ".join(
            sorted(value or "UNRESOLVED" for value in row["resolved_native_types"])
        ),
        "layer": lambda row: row["layer"],
        "rule": lambda row: row["rule_name"],
    }.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(key_getter(row))].append(row)
        per_group[group_name] = [
            {
                "value": key,
                "count": len(values),
                "nonpositive": sum(row["actual_mm"] <= 0 for row in values),
                "below_0_10mm": sum(
                    row["actual_mm"] < args.gerber_min_clearance_mm for row in values
                ),
                "at_least_0_10mm": sum(
                    row["actual_mm"] >= args.gerber_min_clearance_mm for row in values
                ),
                "actual_mm": summary_stats([row["actual_mm"] for row in values]),
            }
            for key, values in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        ]

    nonpositive_rows = [row for row in rows if row["actual_mm"] <= 0]
    positive_below_010_rows = [
        row
        for row in rows
        if 0 < row["actual_mm"] < args.gerber_min_clearance_mm
    ]
    gerber_boundary_rounding_rows = [
        row
        for row in positive_below_010_rows
        if abs(row["actual_mm"] - args.gerber_min_clearance_mm) <= 0.000001
    ]
    material_positive_below_010_rows = [
        row
        for row in positive_below_010_rows
        if row not in gerber_boundary_rounding_rows
    ]

    def diagnostic_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "global_index": row["global_index"],
            "object_pair": row["object_pair"],
            "reported_types": row["reported_types"],
            "resolved_native_types": row["resolved_native_types"],
            "object_ids": row["object_ids"],
            "object_suffixes": row["object_suffixes"],
            "nets": row["nets"],
            "net_relationship": row["net_relationship"],
            "layer": row["layer"],
            "layer_ids": row["layer_ids"],
            "rule_name": row["rule_name"],
            "actual_mm": row["actual_mm"],
            "required_mm": row["required_mm"],
            "fill_ids": row["fill_ids"],
            "fill_half_width_total_mil": row["fill_half_width_total_mil"],
        }

    threshold_details = {
        "nonpositive": [diagnostic_row(row) for row in nonpositive_rows],
        "positive_below_gerber_0_10mm": [
            diagnostic_row(row) for row in positive_below_010_rows
        ],
        "gerber_0_10mm_rounding_boundary_candidates": [
            diagnostic_row(row) for row in gerber_boundary_rounding_rows
        ],
        "material_positive_below_gerber_0_10mm": [
            diagnostic_row(row) for row in material_positive_below_010_rows
        ],
        "nonpositive_groups": {
            "net_relationship": counter_rows(
                Counter(row["net_relationship"] for row in nonpositive_rows)
            ),
            "net_pair": counter_rows(
                Counter(row["net_pair"] for row in nonpositive_rows)
            ),
            "object_pair": counter_rows(
                Counter(row["object_pair"] for row in nonpositive_rows)
            ),
            "layer": counter_rows(Counter(row["layer"] for row in nonpositive_rows)),
        },
        "positive_below_gerber_0_10mm_groups": {
            "net_relationship": counter_rows(
                Counter(row["net_relationship"] for row in positive_below_010_rows)
            ),
            "net_pair": counter_rows(
                Counter(row["net_pair"] for row in positive_below_010_rows)
            ),
            "object_pair": counter_rows(
                Counter(row["object_pair"] for row in positive_below_010_rows)
            ),
            "layer": counter_rows(
                Counter(row["layer"] for row in positive_below_010_rows)
            ),
        },
    }
    th_pad_evidence = build_th_pad_evidence(
        nonpositive_rows,
        source_records,
        args.checkpoint,
        gerber_payload,
    )

    return {
        "schema": "stm32h747-native-pcb-clearance-drc-analysis-v1",
        "status": "clearance-errors-classified-against-native-rules-and-gerber-0.10mm-reference",
        "read_only": True,
        "inputs": {
            "drc": {"path": str(args.drc), "sha256": sha256_file(args.drc)},
            "source": {"path": str(args.source), "sha256": sha256_file(args.source)},
            "checkpoint": {
                "path": str(args.checkpoint),
                "sha256": sha256_file(args.checkpoint),
            },
            "gerber_footprints": {
                "path": str(args.gerber_footprints),
                "sha256": sha256_file(args.gerber_footprints),
            },
            "gerber_job": {
                "path": str(args.job),
                "sha256": sha256_file(args.job),
            },
            "pcb_uuid_in_drc": payload.get("pcbUuid"),
            "rule_name": payload.get("ruleName"),
        },
        "unit_conversion": {
            "errData_raw_to_display_mil_factor": DISPLAY_MIL_PER_RAW_UNIT,
            "display_mil_to_mm_factor": MM_PER_MIL,
            "max_actual_display_rounding_error_mil": (
                max(display_distance_errors_mil) if display_distance_errors_mil else None
            ),
            "max_required_display_rounding_error_mil": (
                max(display_required_errors_mil) if display_required_errors_mil else None
            ),
            "evidence": (
                "errData minDistance/clearance multiplied by 10 matches the displayed mil text "
                "within its one-decimal/whole-mil presentation rounding."
            ),
        },
        "clearance": {
            "count": len(rows),
            "unique_object_pair_layer_count": len(unique_pair_layer),
            "negative_count": negative_count,
            "zero_count": zero_count,
            "nonpositive_overlap_or_short_candidate_count": nonpositive_count,
            "positive_count": len(positive),
            "positive_below_0_10mm": positive_below_010,
            "positive_below_0_10mm_rounding_boundary_candidate_count": (
                len(gerber_boundary_rounding_rows)
            ),
            "material_positive_below_0_10mm_count": (
                len(material_positive_below_010_rows)
            ),
            "positive_0_10_to_below_0_152mm": positive_010_to_0152,
            "positive_below_0_152mm": positive_below_0152,
            "below_gerber_0_10mm_including_nonpositive": below_010,
            "at_or_above_gerber_0_10mm_but_flagged_by_native_rule": at_least_010,
            "actual_mm_stats_all": summary_stats(actual_mm),
            "actual_mm_stats_positive": summary_stats(positive),
            "distance_bins_mm": dict(sorted(distance_bins.items())),
            "required_mm_distribution": counter_rows(required_groups),
            "most_common_actual_mm_values": counter_rows(actual_value_groups, 30),
        },
        "groups": {
            "reported_object_pair_counts": counter_rows(type_groups),
            "resolved_native_type_pair_counts": counter_rows(native_type_groups),
            "layer_counts": counter_rows(layer_groups),
            "rule_counts": counter_rows(rule_groups),
            "top_net_pairs": counter_rows(net_pair_groups, 50),
            "net_relationship_counts": counter_rows(net_relationship_groups),
            "detailed": per_group,
            "unresolved_object_ids_by_reported_type": dict(sorted(unresolved_ids.items())),
        },
        "threshold_details": threshold_details,
        "fill_to_th_pad_zero_evidence": th_pad_evidence,
        "fill_border_sensitivity": {
            "errors_touching_native_fill": len(fill_rows),
            "native_fill_width_mil_occurrences": counter_rows(fill_widths),
            "native_fill_summaries": fill_native_summaries,
            "model": (
                "Sensitivity only: add half of each participating native FILL width to the "
                "reported boundary distance. This does not prove the DRC kernel applied that "
                "border or replace geometric inspection."
            ),
            "gerber_0_10mm_fail_to_pass_if_fill_border_is_ignored": len(fill_flip_010),
            "affected_global_indices": [row["global_index"] for row in fill_flip_010],
        },
        "interpretation": {
            "gerber_job_min_clearance_mm": args.gerber_min_clearance_mm,
            "gerber_job_design_rules": job_payload.get("DesignRules"),
            "gerber_job_scope_note": (
                "The 0.10 mm split is a uniform diagnostic benchmark. The Gerber Job "
                "declares 0.10 mm for outer pad/track/region pairs and inner track/region "
                "pairs, but declares inner PadToPad and PadToTrack as 0.0 and does not "
                "declare inner PadToRegion. Missing or zero fields are not manufacturing "
                "approval for a physical different-net overlap."
            ),
            "nonpositive_values": (
                "Geometric overlap/zero-clearance short candidates; inspect first and do not "
                "treat as ordinary rule-margin violations."
            ),
            "native_only_margin_band": (
                "Rows at or above 0.10 mm but below their selected native rule are not Gerber-job "
                "0.10 mm violations, but remain native-profile DRC findings."
            ),
            "manufacturing_ready": False,
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drc", type=Path, default=DEFAULT_DRC)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--gerber-footprints", type=Path, default=DEFAULT_GERBER_FOOTPRINTS
    )
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--gerber-min-clearance-mm", type=float, default=0.10)
    parser.add_argument("--expected-clearance-count", type=int, default=2195)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = analyze(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        clearance = report["clearance"]
        print(json.dumps({
            "status": report["status"],
            "count": clearance["count"],
            "nonpositive": clearance["nonpositive_overlap_or_short_candidate_count"],
            "positive_below_0_10mm": clearance["positive_below_0_10mm"],
            "positive_0_10_to_below_0_152mm": (
                clearance["positive_0_10_to_below_0_152mm"]
            ),
            "at_or_above_0_10mm": (
                clearance["at_or_above_gerber_0_10mm_but_flagged_by_native_rule"]
            ),
            "fill_touched": report["fill_border_sensitivity"]["errors_touching_native_fill"],
            "fill_border_threshold_flips": (
                report["fill_border_sensitivity"]
                ["gerber_0_10mm_fail_to_pass_if_fill_border_is_ignored"]
            ),
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
