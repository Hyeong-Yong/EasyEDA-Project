#!/usr/bin/env python3
"""Verify the decoder-compatible routed PCB across native readbacks/checkpoint.

The audit is completely static.  It checks primitive identity and geometry,
the 103 recovered copper capsules, 227 explicitly closed regions, 500 recovered
POLY strokes, electrical records, rules, and package-level physical-stack
persistence without calling the EasyEDA API or UI.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_compatible_pcb_staging_20261014.epro2"
)
DEFAULT_ORIGINAL = ROOT / "output" / "native-pcb" / "native-pcb-routed.epru"
DEFAULT_CANDIDATE = (
    ROOT / "output" / "native-pcb" / "native-pcb-routed-decoder-compatible.epru"
)
DEFAULT_MANIFEST = (
    ROOT / "output" / "native-pcb" /
    "native-pcb-routed-decoder-compatibility-manifest.json"
)
DEFAULT_READBACK = (
    ROOT / "output" / "validation" / "native-staging-pcb-compatible-readback.epru"
)
DEFAULT_REOPENED = (
    ROOT / "output" / "validation" / "native-staging-pcb-compatible-reopened.epru"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" /
    "native-pcb-compatible-checkpoint-audit.json"
)
TARGET_UUID = "6da689cbfc28e476"
EXPECTED_COUNTS = Counter({
    "LINE": 5424,
    "ARC": 2184,
    "POLY": 500,
    "FILL": 730,
    "VIA": 634,
    "PAD": 4,
    "COMPONENT": 330,
    "ATTR": 990,
    "PAD_NET": 1176,
    "NET": 280,
})
GEOMETRY_TYPES = frozenset({"LINE", "ARC", "POLY", "FILL", "VIA", "PAD"})
ELECTRICAL_TYPES = frozenset({"COMPONENT", "ATTR", "PAD_NET", "NET"})
COPPER_LAYERS = frozenset({1, 2, 15, 16, 17, 18})
ROUNDING_TOLERANCE_MIL = 0.000051


def load_checkpoint_helpers() -> Any:
    path = ROOT / "scripts" / "audit-native-pcb-staging-checkpoint.py"
    name = "stm32h747_checkpoint_audit_helpers"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load checkpoint audit helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HELPERS = load_checkpoint_helpers()
Record = HELPERS.Record


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    if not relative.parts:
        raise ValueError("output cannot be the output root")
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def record_counts(records: Iterable[Any]) -> Counter[str]:
    return Counter(record.kind for record in records)


def id_map(records: Iterable[Any], label: str) -> dict[str, Any]:
    return HELPERS.id_map(records, label)


def type_id_set(records: Iterable[Any], kind: str) -> set[str]:
    return {record.record_id for record in records if record.kind == kind}


def typed_body_digest(records: Iterable[Any], kinds: set[str] | frozenset[str]) -> str:
    return HELPERS.typed_body_digest(records, kinds)


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite: {value!r}")
    return result


def numeric_close(left: Any, right: Any, tolerance: float = ROUNDING_TOLERANCE_MIL) -> bool:
    return abs(finite(left, "left number") - finite(right, "right number")) <= tolerance


def assert_core_fields_equal(source: Any, actual: Any) -> None:
    for field in ("layerId", "netName"):
        if source.body.get(field) != actual.body.get(field):
            raise AssertionError(
                f"{actual.kind} {actual.record_id} changed {field}: "
                f"{source.body.get(field)!r} != {actual.body.get(field)!r}"
            )


def point_pairs_from_simple_l_path(path: list[Any]) -> list[tuple[float, float]]:
    if not (
        len(path) >= 5 and isinstance(path[0], (int, float))
        and isinstance(path[1], (int, float)) and path[2] == "L"
    ):
        raise ValueError("unsupported simple L path")
    values = path[3:]
    if len(values) % 2 or not all(isinstance(value, (int, float)) for value in values):
        raise ValueError("simple L path contains non-coordinate tokens")
    return [(float(path[0]), float(path[1]))] + [
        (float(values[index]), float(values[index + 1]))
        for index in range(0, len(values), 2)
    ]


def remove_consecutive_duplicate_points(
    points: Iterable[tuple[float, float]]
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        if not result or point != result[-1]:
            result.append(point)
    return result


def rounded_points(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    return remove_consecutive_duplicate_points(
        (round(point[0], 4), round(point[1], 4)) for point in points
    )


def bbox(points: Iterable[tuple[float, float]]) -> tuple[float, float, float, float]:
    values = list(points)
    if not values:
        raise ValueError("cannot compute empty bounding box")
    xs = [point[0] for point in values]
    ys = [point[1] for point in values]
    return min(xs), min(ys), max(xs), max(ys)


def signed_area(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, points[1:] + points[:1])
    )


def point_to_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return distance(point, start)
    projection = (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dy
    ) / length2
    projection = max(0.0, min(1.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dy)
    return distance(point, nearest)


def monotonic_boundary_equivalence(
    source: Sequence[tuple[float, float]], target: Sequence[tuple[float, float]],
    tolerance: float = 0.00012,
) -> tuple[bool, float, int, int]:
    """Compare ordered polygon paths while allowing inserted collinear points."""
    if len(source) < 2 or len(target) < 2:
        return False, math.inf, 0, 0
    source_index = 0
    target_index = 0
    maximum_error = 0.0
    skipped_source = 0
    skipped_target = 0
    while source_index < len(source) and target_index < len(target):
        direct = distance(source[source_index], target[target_index])
        if direct <= tolerance:
            maximum_error = max(maximum_error, direct)
            source_index += 1
            target_index += 1
            continue
        if source_index > 0:
            target_on_source = point_to_segment_distance(
                target[target_index], source[source_index - 1], source[source_index]
            )
            if target_on_source <= tolerance:
                maximum_error = max(maximum_error, target_on_source)
                target_index += 1
                skipped_target += 1
                continue
        if target_index > 0:
            source_on_target = point_to_segment_distance(
                source[source_index], target[target_index - 1], target[target_index]
            )
            if source_on_target <= tolerance:
                maximum_error = max(maximum_error, source_on_target)
                source_index += 1
                skipped_source += 1
                continue
        return False, max(maximum_error, direct), skipped_source, skipped_target
    while source_index < len(source) and target_index >= 1:
        error = point_to_segment_distance(
            source[source_index], target[target_index - 2], target[target_index - 1]
        )
        if error > tolerance:
            return False, max(maximum_error, error), skipped_source, skipped_target
        maximum_error = max(maximum_error, error)
        source_index += 1
        skipped_source += 1
    while target_index < len(target) and source_index >= 1:
        error = point_to_segment_distance(
            target[target_index], source[source_index - 2], source[source_index - 1]
        )
        if error > tolerance:
            return False, max(maximum_error, error), skipped_source, skipped_target
        maximum_error = max(maximum_error, error)
        target_index += 1
        skipped_target += 1
    return source_index == len(source) and target_index == len(target), maximum_error, skipped_source, skipped_target


def parse_mixed_path(path: list[Any]) -> tuple[
    list[tuple[str, tuple[float, float], tuple[float, float], float | None]],
    tuple[float, float],
    tuple[float, float],
]:
    if len(path) < 2 or not all(isinstance(path[index], (int, float)) for index in (0, 1)):
        raise ValueError("mixed path lacks a numeric start")
    start = (float(path[0]), float(path[1]))
    current = start
    segments: list[tuple[str, tuple[float, float], tuple[float, float], float | None]] = []
    index = 2
    implicit_line = False
    while index < len(path):
        token = path[index]
        if token == "L":
            if index + 2 >= len(path):
                raise ValueError("truncated L segment")
            end = (float(path[index + 1]), float(path[index + 2]))
            segments.append(("L", current, end, None))
            current = end
            index += 3
            implicit_line = True
        elif token in {"ARC", "CARC"}:
            if index + 3 >= len(path):
                raise ValueError("truncated ARC segment")
            angle = float(path[index + 1])
            end = (float(path[index + 2]), float(path[index + 3]))
            segments.append((str(token), current, end, angle))
            current = end
            index += 4
            implicit_line = False
        elif isinstance(token, (int, float)) and implicit_line:
            if index + 1 >= len(path):
                raise ValueError("truncated implicit L segment")
            end = (float(token), float(path[index + 1]))
            segments.append(("L", current, end, None))
            current = end
            index += 2
        else:
            raise ValueError(f"unsupported path token: {token!r}")
    return segments, start, current


def midpoint(left: tuple[float, float], right: tuple[float, float]) -> tuple[float, float]:
    return (left[0] + right[0]) / 2, (left[1] + right[1]) / 2


def distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def validate_capsules(
    ids: set[str], original_map: dict[str, Any], targets: dict[str, tuple[str, dict[str, Any]]]
) -> dict[str, Any]:
    max_center_error = 0.0
    max_radius_error = 0.0
    max_closure_gap = 0.0
    line_segment_counts: Counter[int] = Counter()
    for record_id in ids:
        original = original_map[record_id]
        if original.kind != "LINE":
            raise AssertionError(f"capsule source is not LINE: {record_id}")
        body = original.body
        source_a = (float(body["startX"]), float(body["startY"]))
        source_b = (float(body["endX"]), float(body["endY"]))
        source_radius = float(body["width"]) / 2
        for target_label, target_map in targets.values():
            actual = target_map[record_id]
            if actual.kind != "FILL":
                raise AssertionError(f"{target_label}: capsule {record_id} is {actual.kind}")
            assert_core_fields_equal(original, actual)
            paths = actual.body.get("path")
            if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], list):
                raise AssertionError(f"{target_label}: capsule {record_id} path shape invalid")
            segments, start, end = parse_mixed_path(paths[0])
            arcs = [segment for segment in segments if segment[0] in {"ARC", "CARC"}]
            lines = [segment for segment in segments if segment[0] == "L"]
            if len(arcs) != 2 or any(segment[3] != -180 for segment in arcs):
                raise AssertionError(f"{target_label}: capsule {record_id} lost its two -180 arcs")
            if len(lines) not in {0, 1, 2}:
                raise AssertionError(f"{target_label}: capsule {record_id} line count={len(lines)}")
            line_segment_counts[len(lines)] += 1
            closure_gap = distance(start, end)
            max_closure_gap = max(max_closure_gap, closure_gap)
            if closure_gap > 1e-12:
                raise AssertionError(f"{target_label}: capsule {record_id} is open by {closure_gap}")
            arc_centers = [midpoint(segment[1], segment[2]) for segment in arcs]
            arc_radii = [distance(segment[1], segment[2]) / 2 for segment in arcs]
            direct = max(distance(arc_centers[0], source_a), distance(arc_centers[1], source_b))
            swapped = max(distance(arc_centers[0], source_b), distance(arc_centers[1], source_a))
            center_error = min(direct, swapped)
            radius_error = max(abs(radius - source_radius) for radius in arc_radii)
            max_center_error = max(max_center_error, center_error)
            max_radius_error = max(max_radius_error, radius_error)
            if center_error > 0.00012 or radius_error > 0.00012:
                raise AssertionError(
                    f"{target_label}: capsule {record_id} error center={center_error}, radius={radius_error}"
                )
    return {
        "count": len(ids),
        "target_evaluations": len(ids) * len(targets),
        "max_cap_center_error_mil": max_center_error,
        "max_cap_radius_error_mil": max_radius_error,
        "max_closure_gap_mil": max_closure_gap,
        "line_segment_count_distribution_across_targets": dict(sorted(line_segment_counts.items())),
        "rounding_bound_mil": 0.00012,
        "ids_all_retained": True,
        "net_and_layer_all_retained": True,
    }


def validate_polygon_fills(
    ids: set[str], candidate_map: dict[str, Any], targets: dict[str, tuple[str, dict[str, Any]]]
) -> dict[str, Any]:
    max_bbox_error = 0.0
    max_area_delta = 0.0
    max_relative_area_delta = 0.0
    rounded_sequence_equal_count = 0
    rounded_sequence_different_count = 0
    for record_id in ids:
        source = candidate_map[record_id]
        source_paths = source.body.get("path")
        if not isinstance(source_paths, list) or len(source_paths) != 1:
            raise AssertionError(f"candidate polygon FILL {record_id} path invalid")
        source_points = point_pairs_from_simple_l_path(source_paths[0])
        if source_points[0] != source_points[-1]:
            raise AssertionError(f"candidate polygon FILL {record_id} not explicitly closed")
        if signed_area(source_points[:-1]) >= 0:
            raise AssertionError(f"candidate polygon FILL {record_id} not clockwise")
        source_rounded = rounded_points(source_points)
        for target_label, target_map in targets.values():
            actual = target_map[record_id]
            if actual.kind != "FILL":
                raise AssertionError(f"{target_label}: polygon FILL {record_id} is {actual.kind}")
            assert_core_fields_equal(source, actual)
            paths = actual.body.get("path")
            if not isinstance(paths, list) or len(paths) != 1:
                raise AssertionError(f"{target_label}: polygon FILL {record_id} path invalid")
            points = point_pairs_from_simple_l_path(paths[0])
            if points[0] != points[-1]:
                raise AssertionError(f"{target_label}: polygon FILL {record_id} not closed")
            if signed_area(points[:-1]) >= 0:
                raise AssertionError(f"{target_label}: polygon FILL {record_id} winding changed")
            target_rounded = rounded_points(points)
            if source_rounded == target_rounded:
                rounded_sequence_equal_count += 1
            else:
                rounded_sequence_different_count += 1
            source_box = bbox(source_points)
            target_box = bbox(points)
            max_bbox_error = max(
                max_bbox_error,
                max(abs(left - right) for left, right in zip(source_box, target_box)),
            )
            source_area = signed_area(source_points[:-1])
            target_area = signed_area(points[:-1])
            area_delta = abs(source_area - target_area)
            max_area_delta = max(max_area_delta, area_delta)
            max_relative_area_delta = max(
                max_relative_area_delta,
                area_delta / max(abs(source_area), 1.0),
            )
    if max_bbox_error > 0.00011:
        raise AssertionError(f"polygon FILL bbox error exceeds native writer precision: {max_bbox_error}")
    if max_relative_area_delta > 0.00005:
        raise AssertionError(
            f"polygon FILL relative area error exceeds audit bound: {max_relative_area_delta}"
        )
    return {
        "count": len(ids),
        "target_evaluations": len(ids) * len(targets),
        "all_explicitly_closed": True,
        "all_clockwise": True,
        "rounded_point_sequence_equal_evaluations": rounded_sequence_equal_count,
        "writer_normalized_point_sequence_evaluations": rounded_sequence_different_count,
        "max_bbox_error_mil": max_bbox_error,
        "max_signed_area_delta_square_mil": max_area_delta,
        "max_relative_area_delta": max_relative_area_delta,
    }


def validate_polys(
    ids: set[str], candidate_map: dict[str, Any], targets: dict[str, tuple[str, dict[str, Any]]]
) -> dict[str, Any]:
    by_layer = Counter()
    target_poly_types: dict[str, Counter[tuple[int, str]]] = defaultdict(Counter)
    max_endpoint_error = 0.0
    max_width_error = 0.0
    for record_id in ids:
        source = candidate_map[record_id]
        if source.kind != "POLY":
            raise AssertionError(f"POLY source type changed: {record_id}")
        source_segments, source_start, source_end = parse_mixed_path(source.body["path"])
        if len(source_segments) != 1 or source_segments[0][0] != "L":
            raise AssertionError(f"candidate POLY {record_id} is not one open line")
        expected_poly_type = "BOARD_OUTLINE" if int(source.body["layerId"]) == 11 else "NORMAL"
        by_layer[int(source.body["layerId"])] += 1
        for target_label, target_map in targets.values():
            actual = target_map[record_id]
            if actual.kind != "POLY":
                raise AssertionError(f"{target_label}: POLY {record_id} is {actual.kind}")
            assert_core_fields_equal(source, actual)
            actual_poly_type = str(actual.body.get("polyType") or "")
            target_poly_types[target_label][
                (int(actual.body["layerId"]), actual_poly_type)
            ] += 1
            allowed_poly_types = (
                {"NORMAL", "BOARD_OUTLINE"}
                if int(source.body["layerId"]) == 11 else {expected_poly_type}
            )
            if actual_poly_type not in allowed_poly_types:
                raise AssertionError(
                    f"{target_label}: POLY {record_id} polyType={actual.body.get('polyType')}"
                )
            segments, start, end = parse_mixed_path(actual.body["path"])
            if len(segments) != 1 or segments[0][0] != "L":
                raise AssertionError(f"{target_label}: POLY {record_id} path changed")
            max_endpoint_error = max(
                max_endpoint_error, distance(source_start, start), distance(source_end, end)
            )
            max_width_error = max(
                max_width_error,
                abs(float(source.body["width"]) - float(actual.body["width"])),
            )
    if by_layer != Counter({3: 492, 11: 8}):
        raise AssertionError(f"POLY layer inventory changed: {by_layer}")
    if max_endpoint_error > 0.00008 or max_width_error > 0.000051:
        raise AssertionError(
            f"POLY rounding exceeds bound: endpoint={max_endpoint_error}, width={max_width_error}"
        )
    return {
        "count": len(ids),
        "by_layer": dict(sorted(by_layer.items())),
        "all_types_retained": True,
        "target_poly_type_counts": {
            label: {
                f"layer{layer}:{poly_type}": count
                for (layer, poly_type), count in sorted(counts.items())
            }
            for label, counts in sorted(target_poly_types.items())
        },
        "outline_note": (
            "The candidate uses BOARD_OUTLINE for the eight layer-11 segments. "
            "The installed decoder may normalize an open outline polygon to internal Line/" 
            "POLY NORMAL while retaining layerId 11 and exact geometry."
        ),
        "max_endpoint_error_mil": max_endpoint_error,
        "max_width_error_mil": max_width_error,
    }


def validate_tracks_vias(
    original_map: dict[str, Any], targets: dict[str, tuple[str, dict[str, Any]]],
    line_ids: set[str], arc_ids: set[str], via_ids: set[str]
) -> dict[str, Any]:
    fields = {
        "LINE": ("startX", "startY", "endX", "endY", "width"),
        "ARC": ("startX", "startY", "endX", "endY", "angle", "width"),
        "VIA": ("centerX", "centerY", "holeDiameter", "viaDiameter"),
    }
    ids_by_type = {"LINE": line_ids, "ARC": arc_ids, "VIA": via_ids}
    max_error = {kind: 0.0 for kind in ids_by_type}
    for kind, record_ids in ids_by_type.items():
        for record_id in record_ids:
            source = original_map[record_id]
            if source.kind != kind:
                raise AssertionError(f"original {record_id} expected {kind}, got {source.kind}")
            for target_label, target_map in targets.values():
                actual = target_map[record_id]
                if actual.kind != kind:
                    raise AssertionError(f"{target_label}: {record_id} expected {kind}, got {actual.kind}")
                assert_core_fields_equal(source, actual)
                for field in fields[kind]:
                    error = abs(float(source.body[field]) - float(actual.body[field]))
                    max_error[kind] = max(max_error[kind], error)
                    if error > ROUNDING_TOLERANCE_MIL:
                        raise AssertionError(
                            f"{target_label}: {kind} {record_id} {field} error={error}"
                        )
    return {
        "counts": {kind: len(ids) for kind, ids in ids_by_type.items()},
        "max_numeric_error_mil_or_degree": max_error,
        "all_ids_types_nets_layers_retained": True,
        "formal_arc_and_line_track_types_retained": True,
    }


def layer_id(record: Any) -> int | None:
    return HELPERS.layer_id(record)


def audit(args: argparse.Namespace) -> dict[str, Any]:
    paths = [
        args.checkpoint, args.original, args.candidate, args.manifest,
        args.readback, args.reopened,
    ]
    missing_files = [str(path) for path in paths if not path.is_file()]
    if missing_files:
        raise FileNotFoundError(missing_files)
    original = HELPERS.parse_source(args.original)
    candidate = HELPERS.parse_source(args.candidate)
    readback = HELPERS.parse_source(args.readback)
    reopened = HELPERS.parse_source(args.reopened)
    checkpoint, checkpoint_bytes, archive = HELPERS.isolate_checkpoint_block(
        args.checkpoint, args.target_uuid
    )
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    checkpoint_docheads = [record.body for record in checkpoint if record.kind == "DOCHEAD"]
    checkpoint_metas = [record.body for record in checkpoint if record.kind == "META"]
    if len(checkpoint_docheads) != 1 or checkpoint_docheads[0].get("docType") != "PCB":
        raise AssertionError("checkpoint target is not exactly one PCB document")
    if checkpoint_docheads[0].get("uuid") != args.target_uuid:
        raise AssertionError("checkpoint target DOCHEAD UUID differs from --target-uuid")
    if len(checkpoint_metas) != 1:
        raise AssertionError("checkpoint target does not contain exactly one META record")
    checkpoint_title = str(checkpoint_metas[0].get("title") or "")
    if args.expected_target_title is not None and checkpoint_title != args.expected_target_title:
        raise AssertionError(
            f"checkpoint target title={checkpoint_title!r}, "
            f"expected={args.expected_target_title!r}"
        )

    sources = {
        "candidate": candidate,
        "immediate_readback": readback,
        "reopened_readback": reopened,
        "checkpoint": checkpoint,
    }
    maps = {label: id_map(records, label) for label, records in sources.items()}
    original_map = id_map(original, "original")
    candidate_map = maps["candidate"]
    target_maps = {
        "readback": ("immediate_readback", maps["immediate_readback"]),
        "reopened": ("reopened_readback", maps["reopened_readback"]),
        "checkpoint": ("checkpoint", maps["checkpoint"]),
    }

    counts = {label: record_counts(records) for label, records in sources.items()}
    for label, source_counts in counts.items():
        mismatches = {
            kind: {"actual": source_counts[kind], "expected": expected}
            for kind, expected in EXPECTED_COUNTS.items()
            if source_counts[kind] != expected
        }
        if mismatches:
            raise AssertionError(f"{label} count mismatch: {mismatches}")

    for kind in GEOMETRY_TYPES | ELECTRICAL_TYPES:
        expected_ids = type_id_set(candidate, kind)
        for label, records in sources.items():
            if type_id_set(records, kind) != expected_ids:
                raise AssertionError(f"{label} {kind} ID set differs from candidate")

    original_primitive_ids = {
        record.record_id for record in original if record.kind in {"LINE", "ARC", "FILL", "VIA", "PAD"}
    }
    candidate_primitive_ids = {
        record.record_id for record in candidate if record.kind in GEOMETRY_TYPES
    }
    if original_primitive_ids != candidate_primitive_ids:
        raise AssertionError("decoder-compatible candidate changed the canonical primitive ID universe")

    transformations = manifest["transformations"]
    capsule_ids = {
        item["id"] for item in
        transformations["copper_sub_0_1_mil_line_to_same_id_net_bearing_solid_fill_capsule"]["records"]
    }
    poly_ids = {
        item["id"] for item in transformations["non_copper_line_to_same_id_poly"]["records"]
    }
    closure_ids = {
        item["id"] for item in transformations["polygon_fill_explicit_closure"]["records"]
    }
    if (len(capsule_ids), len(poly_ids), len(closure_ids)) != (103, 500, 227):
        raise AssertionError("manifest transformation ID inventory changed")
    if capsule_ids & poly_ids or capsule_ids & closure_ids or poly_ids & closure_ids:
        raise AssertionError("transformation ID categories overlap")
    candidate_fill_ids = type_id_set(candidate, "FILL")
    circle_fill_ids = {
        record.record_id for record in candidate
        if record.kind == "FILL"
        and isinstance(record.body.get("path"), list)
        and record.body["path"]
        and isinstance(record.body["path"][0], list)
        and record.body["path"][0]
        and record.body["path"][0][0] == "CIRCLE"
    }
    if len(circle_fill_ids) != 400 or candidate_fill_ids != capsule_ids | closure_ids | circle_fill_ids:
        raise AssertionError("candidate FILL partition is not 103 capsule + 227 polygon + 400 circle")

    surviving_line_ids = type_id_set(candidate, "LINE")
    arc_ids = type_id_set(candidate, "ARC")
    via_ids = type_id_set(candidate, "VIA")
    track_via = validate_tracks_vias(
        original_map, target_maps, surviving_line_ids, arc_ids, via_ids
    )
    capsules = validate_capsules(capsule_ids, original_map, target_maps)
    closures = validate_polygon_fills(closure_ids, candidate_map, target_maps)
    polys = validate_polys(poly_ids, candidate_map, target_maps)

    # CIRCLE fills retain center/radius/net/layer within getter precision.
    circle_max_error = 0.0
    for record_id in circle_fill_ids:
        source = candidate_map[record_id]
        source_circle = source.body["path"][0]
        for target_label, target_map in target_maps.values():
            actual = target_map[record_id]
            assert_core_fields_equal(source, actual)
            circle = actual.body.get("path", [[]])[0]
            if not isinstance(circle, list) or len(circle) != 4 or circle[0] != "CIRCLE":
                raise AssertionError(f"{target_label}: circle FILL {record_id} encoding changed")
            for left, right in zip(source_circle[1:], circle[1:]):
                circle_max_error = max(circle_max_error, abs(float(left) - float(right)))
    if circle_max_error > ROUNDING_TOLERANCE_MIL:
        raise AssertionError(f"circle FILL rounding exceeds bound: {circle_max_error}")

    # Electrical bodies are stable between both getters and the exported package.
    electrical_digests = {
        label: typed_body_digest(records, ELECTRICAL_TYPES)
        for label, records in sources.items() if label != "candidate"
    }
    if len(set(electrical_digests.values())) != 1:
        raise AssertionError(f"readback/checkpoint electrical bodies differ: {electrical_digests}")

    readback_layers = {layer_id(record): record for record in readback if record.kind == "LAYER"}
    reopened_layers = {layer_id(record): record for record in reopened if record.kind == "LAYER"}
    checkpoint_layers = {layer_id(record): record for record in checkpoint if record.kind == "LAYER"}
    readback_phys = {layer_id(record): record for record in readback if record.kind == "LAYER_PHYS"}
    reopened_phys = {layer_id(record): record for record in reopened if record.kind == "LAYER_PHYS"}
    checkpoint_phys = {layer_id(record): record for record in checkpoint if record.kind == "LAYER_PHYS"}
    if set(readback_layers) != set(reopened_layers) or set(readback_phys) != set(reopened_phys):
        raise AssertionError("immediate/reopened runtime layer inventories differ")
    logical_copper = [1, 15, 16, 17, 18, 2]
    checkpoint_logical_use = {
        layer: bool(checkpoint_layers[layer].body.get("use"))
        for layer in logical_copper
    }
    package_phys_ids = Counter(
        physical_id
        for ids in archive["package_layer_phys_by_doc"].values()
        for physical_id in ids
    )
    outside_stack_hits = (
        HELPERS.scan_stack_keys(archive["project2"], "$.project2")
        + HELPERS.scan_stack_keys(
            [record.body for record in checkpoint if record.kind == "META"], "$.target.META"
        )
        + HELPERS.scan_stack_keys(
            [record.body for record in checkpoint if record.kind == "CANVAS"], "$.target.CANVAS"
        )
    )
    rule_templates = [record.body for record in checkpoint if record.kind == "RULE_TEMPLATE"]
    auto_router = [
        record.body for record in checkpoint
        if record.kind == "RULE" and record.record_id == '["RULE","AUTO_ROUTER","Common"]'
    ]
    checkpoint_copper_by_layer_type: dict[int, Counter[str]] = defaultdict(Counter)
    for record in checkpoint:
        record_layer = layer_id(record)
        if record.kind in {"LINE", "ARC", "FILL", "VIA"} and record_layer in COPPER_LAYERS:
            checkpoint_copper_by_layer_type[int(record_layer)][record.kind] += 1

    portable_stack_retained = (
        set(checkpoint_layers) == set(readback_layers)
        and set(checkpoint_phys) == set(readback_phys)
    )

    # Body differences between the two getters and checkpoint are reported by
    # kind; geometry-specific gates above establish physical equivalence.
    body_difference_counts: dict[str, dict[str, int]] = {}
    reference_map = maps["immediate_readback"]
    for label in ("reopened_readback", "checkpoint"):
        actual_map = maps[label]
        differences = Counter(
            reference_map[record_id].kind
            for record_id in set(reference_map) & set(actual_map)
            if reference_map[record_id].body != actual_map[record_id].body
        )
        body_difference_counts[label] = dict(sorted(differences.items()))

    return {
        "schema": "stm32h747-native-pcb-compatible-checkpoint-audit-v1",
        "status": (
            "all-compatible-route-geometry-electrical-and-physical-stack-records-retained; "
            "manufacturing-rule-and-drc-gates-remain"
            if portable_stack_retained else
            "all-compatible-route-geometry-and-electrical-records-retained; "
            "portable-physical-stack-still-incomplete"
        ),
        "manufacturing_ready": False,
        "read_only": True,
        "inputs": {
            "checkpoint": {"path": str(args.checkpoint), "sha256": sha256_file(args.checkpoint)},
            "original_canonical": {"path": str(args.original), "sha256": sha256_file(args.original)},
            "compatible_candidate": {"path": str(args.candidate), "sha256": sha256_file(args.candidate)},
            "compatibility_manifest": {"path": str(args.manifest), "sha256": sha256_file(args.manifest)},
            "immediate_readback": {"path": str(args.readback), "sha256": sha256_file(args.readback)},
            "reopened_readback": {"path": str(args.reopened), "sha256": sha256_file(args.reopened)},
        },
        "checkpoint_target": {
            "uuid": args.target_uuid,
            "doc_type": checkpoint_docheads[0].get("docType"),
            "title": checkpoint_title,
            "meta_identity": {
                key: checkpoint_metas[0].get(key)
                for key in ("parent", "source", "board")
                if key in checkpoint_metas[0]
            },
            "dochead_occurrences": archive["target_dochead_occurrences"],
            "block_bytes": len(checkpoint_bytes),
            "block_sha256": sha256_bytes(checkpoint_bytes),
            "record_count": len(checkpoint),
            "counts": dict(sorted(counts["checkpoint"].items())),
            "inner_source_bytes": archive["inner_source_bytes"],
            "inner_source_sha256": archive["inner_source_sha256"],
        },
        "identity_and_counts": {
            "counts": {label: dict(sorted(value.items())) for label, value in counts.items()},
            "all_geometry_and_electrical_id_sets_equal_candidate": True,
            "candidate_primitive_id_set_exact_original_canonical": True,
            "body_difference_counts_vs_immediate_readback": body_difference_counts,
        },
        "geometry": {
            "nondegenerate_tracks_arcs_vias": track_via,
            "recovered_capsule_fills": capsules,
            "explicitly_closed_polygon_fills": closures,
            "recovered_polys": polys,
            "circle_fills": {
                "count": len(circle_fill_ids),
                "all_ids_types_nets_layers_retained": True,
                "max_center_or_radius_error_mil": circle_max_error,
            },
        },
        "electrical": {
            "component_count": counts["checkpoint"]["COMPONENT"],
            "attribute_count": counts["checkpoint"]["ATTR"],
            "pad_net_count": counts["checkpoint"]["PAD_NET"],
            "net_count_including_empty_scaffold": counts["checkpoint"]["NET"],
            "readback_reopened_checkpoint_body_digests": electrical_digests,
            "all_equal": True,
        },
        "physical_stack_and_rules": {
            "runtime_readback_layer_ids": sorted(readback_layers),
            "runtime_reopened_layer_ids": sorted(reopened_layers),
            "checkpoint_layer_ids": sorted(checkpoint_layers),
            "runtime_readback_layer_phys_ids": sorted(readback_phys),
            "runtime_reopened_layer_phys_ids": sorted(reopened_phys),
            "checkpoint_layer_phys_ids": sorted(checkpoint_phys),
            "checkpoint_missing_runtime_layer_ids": sorted(set(readback_layers) - set(checkpoint_layers)),
            "checkpoint_missing_runtime_layer_phys_ids": sorted(set(readback_phys) - set(checkpoint_phys)),
            "checkpoint_logical_copper_use": checkpoint_logical_use,
            "checkpoint_logical_six_copper_layers_enabled": all(checkpoint_logical_use.values()),
            "package_layer_phys_ids_by_doc_uuid": archive["package_layer_phys_by_doc"],
            "package_layer_phys_total": sum(package_phys_ids.values()),
            "package_layer_phys_id_counts": dict(sorted(package_phys_ids.items())),
            "stack_fields_outside_layer_records": outside_stack_hits,
            "runtime_readback_rule_selector_count": counts["immediate_readback"]["RULE_SELECTOR"],
            "runtime_reopened_rule_selector_count": counts["reopened_readback"]["RULE_SELECTOR"],
            "checkpoint_rule_selector_count": counts["checkpoint"]["RULE_SELECTOR"],
            "checkpoint_rule_templates": rule_templates,
            "checkpoint_auto_router_common": auto_router,
            "checkpoint_routed_copper_by_layer_and_type": {
                str(layer): dict(sorted(type_counts.items()))
                for layer, type_counts in sorted(checkpoint_copper_by_layer_type.items())
            },
            "portable_17_record_physical_stack_retained": (
                set(checkpoint_phys) == set(readback_phys)
            ),
            "finding": (
                "The portable checkpoint retains the complete runtime LAYER/LAYER_PHYS inventory. "
                "Manufacturing readiness still requires reviewed six-layer rules and DRC."
                if portable_stack_retained else
                "Runtime immediate/reopened getters retain 64 LAYER and 17 LAYER_PHYS records, "
                "but the portable checkpoint is missing logical or physical stack records."
            ),
        },
        "required_next_gates": ([
            "replace the two-layer rule template/autorouter layer list with reviewed six-layer rules",
            "run native netlist comparison and DRC",
            "compare final manufacturing export with the Gerber geometry reference",
        ] if portable_stack_retained else [
            "persist and re-export a package containing the complete 17-record physical stack",
            "replace the two-layer rule template/autorouter layer list with reviewed six-layer rules",
            "run native netlist comparison and DRC",
            "compare final manufacturing export with the Gerber geometry reference",
        ]),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--original", type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--readback", type=Path, default=DEFAULT_READBACK)
    parser.add_argument("--reopened", type=Path, default=DEFAULT_REOPENED)
    parser.add_argument(
        "--target-uuid", default=TARGET_UUID,
        help="PCB DOCHEAD UUID to isolate; pass the new UUID after final-board copy",
    )
    parser.add_argument(
        "--expected-target-title",
        help="optional exact META.title guard for a copied/final PCB",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(compact({
            "status": report["status"],
            "checkpoint_sha256": report["inputs"]["checkpoint"]["sha256"],
            "primitive_counts": {
                kind: report["checkpoint_target"]["counts"].get(kind, 0)
                for kind in ("LINE", "ARC", "POLY", "FILL", "VIA", "PAD")
            },
            "runtime_layer_phys": len(
                report["physical_stack_and_rules"]["runtime_reopened_layer_phys_ids"]
            ),
            "checkpoint_layer_phys": len(
                report["physical_stack_and_rules"]["checkpoint_layer_phys_ids"]
            ),
            "manufacturing_ready": False,
        }))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, AssertionError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
