#!/usr/bin/env python3
"""Recover Gerber geometry that EasyEDA 3.2 silently drops while decoding.

This is an offline source adapter.  It never calls the EasyEDA API or touches
the UI.  The durable, saved six-layer PCB getter source is the identity,
component, net, rule, and layer-stack authority.  The original canonical
Gerber-derived routed source is used only to recover primitive records that
the installed 3.2 PCB decoder omitted:

* sub-0.1 mil copper LINE records become same-ID, net-bearing FILL capsules;
* top-silkscreen LINE records become same-ID NORMAL POLY strokes;
* board-outline LINE records become same-ID BOARD_OUTLINE POLY strokes; and
* every polygonal FILL contour is explicitly closed with its first point.

All non-degenerate LINE tracks, all ARC tracks, all VIA records, and the
native-valid 17-record physical stack remain byte-semantic from the saved
getter base.  The output is a native import candidate, not a manufacturing
release: native netlist comparison and DRC are still mandatory.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_CANONICAL = ROOT / "output" / "native-pcb" / "native-pcb-routed.epru"
DEFAULT_BASE = ROOT / "output" / "validation" / "native-routed-staging-reopened.epru"
DEFAULT_OUTPUT = (
    ROOT / "output" / "native-pcb" / "native-pcb-routed-decoder-compatible.epru"
)
DEFAULT_REPORT = (
    ROOT / "output" / "native-pcb" /
    "native-pcb-routed-decoder-compatibility-manifest.json"
)
DEFAULT_SCHEMA_REPORT = (
    ROOT / "output" / "validation" /
    "native-pcb-routed-decoder-compatible-schema-report.json"
)
VALIDATOR = ROOT / "scripts" / "validate-native-source.py"

CANONICAL_SHA256 = "d7e9354a4e9e4cee37b9e7f63f13a1ade07fa4689abc6e94c01e633dffefbc08"
BASE_SHA256 = "a46264d0d947a566d8cbbc81b774f5516ee91d2891df8291f3578c21715842ca"
COPPER_LAYERS = frozenset({1, 2, 15, 16, 17, 18})
EXPECTED_MISSING_LINE_BY_LAYER = {1: 63, 2: 32, 3: 492, 11: 8, 17: 8}
EXPECTED_MISSING_FILL_BY_LAYER = {1: 61, 2: 44, 3: 12, 15: 18, 16: 20, 17: 53, 18: 18}
EXPECTED_CANONICAL_COUNTS = Counter({
    "LINE": 6027,
    "ARC": 2184,
    "FILL": 627,
    "VIA": 634,
    "PAD": 4,
    "COMPONENT": 330,
    "PAD_NET": 1176,
    "NET": 280,
    "LAYER": 64,
    "LAYER_PHYS": 13,
})
EXPECTED_BASE_COUNTS = Counter({
    "LINE": 5424,
    "ARC": 2184,
    "FILL": 401,
    "VIA": 634,
    "PAD": 4,
    "COMPONENT": 330,
    "PAD_NET": 1176,
    "NET": 280,
    "LAYER": 64,
    "LAYER_PHYS": 17,
})
EXPECTED_OUTPUT_COUNTS = Counter({
    "LINE": 5424,
    "ARC": 2184,
    "POLY": 500,
    "FILL": 730,
    "VIA": 634,
    "PAD": 4,
    "COMPONENT": 330,
    "PAD_NET": 1176,
    "NET": 280,
    "LAYER": 64,
    "LAYER_PHYS": 17,
})
PRIMITIVE_TYPES = frozenset({"LINE", "ARC", "FILL", "VIA", "POLY", "PAD"})
PROTECTED_TYPES = frozenset({
    "DOCHEAD", "META", "CANVAS", "ACTIVE_LAYER", "PREFERENCE",
    "COMPONENT", "PAD_NET", "NET", "ATTR", "RULE", "RULE_TEMPLATE",
    "LAYER", "LAYER_PHYS",
})


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


def safe_output_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must be below {OUTPUT_ROOT}; got {resolved}") from exc
    if not relative.parts:
        raise ValueError(f"{label} cannot be the output root")
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    target = safe_output_path(path, "output file")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            safe_output_path(temporary, "temporary output file").unlink()


def finite_number(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} is not finite: {value!r}")
    return result


def clean_number(value: float, digits: int = 12) -> int | float:
    result = round(finite_number(value, "generated coordinate"), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


@dataclass
class Record:
    header: dict[str, Any]
    body: dict[str, Any]
    line_number: int
    raw_line: str | None
    origin: str

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")

    @property
    def ticket(self) -> Any:
        return self.header.get("ticket")

    def serialized(self) -> str:
        if self.raw_line is not None:
            return self.raw_line
        return f"{compact(self.header)}||{compact(self.body)}|"

    def canonical(self) -> str:
        return compact([self.header, self.body])


def parse_source(path: Path, origin: str) -> list[Record]:
    records: list[Record] = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    final_nonempty = max((index for index, value in enumerate(lines, 1) if value.strip()), default=0)
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if "||" not in line:
            raise ValueError(f"{path}:{line_number}: missing native record separator")
        if not line.endswith("|"):
            if line_number != final_nonempty:
                raise ValueError(f"{path}:{line_number}: missing non-EOF record terminator")
            normalized = line + "|"
        else:
            normalized = line
        header_text, body_text = normalized[:-1].split("||", 1)
        header = json.loads(header_text)
        body = json.loads(body_text)
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise ValueError(f"{path}:{line_number}: header/body must be JSON objects")
        records.append(Record(header, body, line_number, normalized, origin))
    if not records:
        raise ValueError(f"native source is empty: {path}")
    docheads = [record for record in records if record.kind == "DOCHEAD"]
    if len(docheads) != 1 or docheads[0].body.get("docType") != "PCB":
        raise ValueError(f"expected exactly one PCB DOCHEAD: {path}")
    return records


def serialize_source(records: Iterable[Record]) -> str:
    # EasyEDA 3.2 getter framing: newline-separated records and no final pipe.
    text = "\n".join(record.serialized() for record in records)
    if not text.endswith("|"):
        raise AssertionError("serialized source must end with a record terminator before EOF trim")
    return text[:-1]


def count_types(records: Iterable[Record]) -> Counter[str]:
    return Counter(record.kind for record in records)


def id_map(records: Iterable[Record], label: str) -> dict[str, Record]:
    result: dict[str, Record] = {}
    for record in records:
        if not record.record_id:
            continue
        if record.record_id in result:
            raise ValueError(f"{label} duplicate record ID: {record.record_id}")
        result[record.record_id] = record
    return result


def digest_records(records: Iterable[Record]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.canonical().encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def subset_digest(records: Iterable[Record], kinds: set[str] | frozenset[str]) -> str:
    return digest_records(record for record in records if record.kind in kinds)


def layer_id(record: Record) -> int:
    value = record.body.get("layerId")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{record.kind} {record.record_id} has invalid layerId: {value!r}")
    return int(value)


def line_geometry(record: Record) -> tuple[float, float, float, float, float, float]:
    body = record.body
    sx = finite_number(body.get("startX"), f"{record.record_id}.startX")
    sy = finite_number(body.get("startY"), f"{record.record_id}.startY")
    ex = finite_number(body.get("endX"), f"{record.record_id}.endX")
    ey = finite_number(body.get("endY"), f"{record.record_id}.endY")
    width = finite_number(body.get("width"), f"{record.record_id}.width")
    if width <= 0:
        raise ValueError(f"LINE {record.record_id} has non-positive width: {width}")
    return sx, sy, ex, ey, width, math.hypot(ex - sx, ey - sy)


def line_to_poly(record: Record, poly_type: str) -> Record:
    sx, sy, ex, ey, width, distance = line_geometry(record)
    if distance <= 0:
        raise ValueError(f"non-copper LINE {record.record_id} has zero length")
    body = record.body
    expected_keys = {
        "partitionId", "groupId", "locked", "zIndex", "netName", "layerId",
        "startX", "startY", "endX", "endY", "width",
    }
    unexpected = sorted(set(body) - expected_keys)
    if unexpected:
        raise ValueError(f"LINE {record.record_id} has unhandled fields: {unexpected}")
    replacement_body = {
        "partitionId": body.get("partitionId"),
        "groupId": body.get("groupId"),
        "netName": body.get("netName"),
        "layerId": body.get("layerId"),
        "width": body.get("width"),
        "locked": body.get("locked"),
        "zIndex": body.get("zIndex"),
        "path": [body["startX"], body["startY"], "L", body["endX"], body["endY"]],
        "polyType": poly_type,
    }
    header = copy.deepcopy(record.header)
    header["type"] = "POLY"
    return Record(header, replacement_body, record.line_number, None, "recovered-poly")


def line_to_capsule_fill(record: Record) -> tuple[Record, dict[str, Any]]:
    sx, sy, ex, ey, width, distance = line_geometry(record)
    if not (0 < distance < 0.1):
        raise ValueError(
            f"copper LINE {record.record_id} is not an installed-decoder sub-0.1 mil "
            f"degenerate: length={distance!r}"
        )
    body = record.body
    net_name = body.get("netName")
    if not isinstance(net_name, str) or not net_name:
        raise ValueError(f"copper LINE {record.record_id} has no electrical net")
    expected_keys = {
        "partitionId", "groupId", "locked", "zIndex", "netName", "layerId",
        "startX", "startY", "endX", "endY", "width",
    }
    unexpected = sorted(set(body) - expected_keys)
    if unexpected:
        raise ValueError(f"LINE {record.record_id} has unhandled fields: {unexpected}")

    ux = (ex - sx) / distance
    uy = (ey - sy) / distance
    nx = -uy
    ny = ux
    radius = width / 2
    al = (clean_number(sx + nx * radius), clean_number(sy + ny * radius))
    bl = (clean_number(ex + nx * radius), clean_number(ey + ny * radius))
    br = (clean_number(ex - nx * radius), clean_number(ey - ny * radius))
    ar = (clean_number(sx - nx * radius), clean_number(sy - ny * radius))
    path = [
        al[0], al[1],
        "L", bl[0], bl[1],
        "ARC", -180, br[0], br[1],
        "L", ar[0], ar[1],
        "ARC", -180, al[0], al[1],
    ]
    # The chord quadrilateral is clockwise in the native Y-up coordinate system.
    chord_area2 = 0.0
    chord_points = [al, bl, br, ar]
    for current, following in zip(chord_points, chord_points[1:] + chord_points[:1]):
        chord_area2 += float(current[0]) * float(following[1])
        chord_area2 -= float(following[0]) * float(current[1])
    if not chord_area2 < 0:
        raise AssertionError(f"capsule {record.record_id} outer path is not clockwise")

    replacement_body = {
        "partitionId": body.get("partitionId"),
        "groupId": body.get("groupId"),
        "locked": body.get("locked"),
        "zIndex": body.get("zIndex"),
        "netName": net_name,
        "layerId": body.get("layerId"),
        "width": 0,
        "fillStyle": "SOLID",
        "path": [path],
        "isBridgingCopper": False,
        "networkList": [],
        "refs": [],
    }
    header = copy.deepcopy(record.header)
    header["type"] = "FILL"
    replacement = Record(header, replacement_body, record.line_number, None, "recovered-capsule")
    audit = {
        "id": record.record_id,
        "ticket": record.ticket,
        "layer_id": layer_id(record),
        "net_name": net_name,
        "source_length_mil": distance,
        "source_width_mil": width,
        "radius_mil": radius,
        "capsule_area_square_mil": 2 * radius * distance + math.pi * radius * radius,
        "clockwise_chord_area2": chord_area2,
        "path": path,
    }
    return replacement, audit


def is_circle_fill(record: Record) -> bool:
    paths = record.body.get("path")
    return (
        isinstance(paths, list)
        and len(paths) == 1
        and isinstance(paths[0], list)
        and len(paths[0]) >= 1
        and paths[0][0] in {"CIRCLE", "C"}
    )


def close_polygon_fill(record: Record) -> tuple[Record, dict[str, Any]]:
    if record.kind != "FILL" or is_circle_fill(record):
        raise ValueError(f"record is not a polygonal FILL: {record.record_id}")
    paths = record.body.get("path")
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], list):
        raise ValueError(f"FILL {record.record_id} must contain exactly one contour")
    path = copy.deepcopy(paths[0])
    if len(path) < 5 or not all(isinstance(path[index], (int, float)) for index in (0, 1, -2, -1)):
        raise ValueError(f"FILL {record.record_id} has an unsupported contour encoding")
    first = (finite_number(path[0], "fill first x"), finite_number(path[1], "fill first y"))
    last = (finite_number(path[-2], "fill last x"), finite_number(path[-1], "fill last y"))
    gap = math.hypot(last[0] - first[0], last[1] - first[1])
    if gap == 0:
        raise ValueError(f"FILL {record.record_id} was already explicitly closed")
    path.extend([path[0], path[1]])
    replacement_body = copy.deepcopy(record.body)
    replacement_body["path"] = [path]
    replacement = Record(
        copy.deepcopy(record.header), replacement_body, record.line_number, None,
        "explicitly-closed-fill",
    )
    return replacement, {
        "id": record.record_id,
        "ticket": record.ticket,
        "layer_id": layer_id(record),
        "net_name": record.body.get("netName"),
        "implicit_closure_gap_mil": gap,
        "explicit_first_last_equal": path[:2] == path[-2:],
    }


def geometry_payload(record: Record) -> dict[str, Any]:
    body = record.body
    common = {
        "type": record.kind,
        "id": record.record_id,
        "layerId": body.get("layerId"),
        "netName": body.get("netName"),
    }
    if record.kind == "LINE":
        common["width"] = body.get("width")
        common["geometry"] = [body.get(key) for key in ("startX", "startY", "endX", "endY")]
    elif record.kind == "ARC":
        common["width"] = body.get("width")
        common["geometry"] = [
            body.get(key) for key in
            ("startX", "startY", "endX", "endY", "centerX", "centerY", "angle")
        ]
    elif record.kind == "FILL":
        # The installed getter normalizes decoded Fill Region width 0 to 0.2
        # mil.  The closed region path is the copper-area geometry authority.
        common["geometry"] = body.get("path")
    elif record.kind == "POLY":
        common["width"] = body.get("width")
        common["geometry"] = body.get("path")
    elif record.kind == "VIA":
        common["geometry"] = [
            body.get(key) for key in
            ("centerX", "centerY", "diameter", "holeDiameter", "startLayer", "endLayer")
        ]
    return common


def geometry_values_equivalent(left: Any, right: Any, tolerance: float = 0.000051) -> bool:
    """Compare canonical 6-decimal geometry with the getter's 4-decimal writer.

    The installed writer rounds native-mil geometry to four decimal places.
    A 0.000051 mil bound is one half-unit in that last place plus floating
    arithmetic slack; it is not used to alter coordinates.
    """
    if (
        isinstance(left, (int, float)) and not isinstance(left, bool)
        and isinstance(right, (int, float)) and not isinstance(right, bool)
    ):
        return abs(float(left) - float(right)) <= tolerance
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            geometry_values_equivalent(a, b, tolerance) for a, b in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            geometry_values_equivalent(left[key], right[key], tolerance) for key in left
        )
    return left == right


def assert_count_subset(actual: Counter[str], expected: Counter[str], label: str) -> None:
    differences = {
        kind: {"actual": actual.get(kind, 0), "expected": count}
        for kind, count in expected.items()
        if actual.get(kind, 0) != count
    }
    if differences:
        raise ValueError(f"{label} record-count mismatch: {differences}")


def run_schema_report(source: Path, report: Path) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(source), "--report", str(report)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not report.is_file():
        raise ValueError(
            "installed-schema validator did not produce a report: "
            f"exit={result.returncode}, "
            f"stdout={result.stdout[-1200:]!r}, stderr={result.stderr[-1200:]!r}"
        )
    diagnostic = json.loads(report.read_text(encoding="utf-8-sig"))
    totals = diagnostic.get("totals") or {}
    if int(totals.get("parseErrors") or 0) or int(totals.get("unmappedRecords") or 0):
        raise ValueError(f"schema validator found parse/unmapped records: {totals}")
    return diagnostic


def schema_action_counts(report: dict[str, Any]) -> Counter[tuple[str, str, str, str]]:
    result: Counter[tuple[str, str, str, str]] = Counter()
    actions = report.get("actions") or {}
    for category in ("addFields", "removeFields", "changeFields"):
        for item in actions.get(category) or []:
            key = (
                category,
                str(item.get("docType") or ""),
                str(item.get("primitiveType") or ""),
                str(item.get("fieldPath") or ""),
            )
            result[key] += int(item.get("count") or 0)
    return result


def baseline_aware_schema_validation(
    output: Path, output_report_path: Path, base: Path
) -> dict[str, Any]:
    validation_dir = safe_output_path(ROOT / "output" / "validation", "validation directory")
    validation_dir.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix="native-routed-staging-base-", suffix=".schema-report.json",
        dir=validation_dir,
    )
    os.close(handle)
    base_report_path = Path(temporary_name)
    try:
        base_report = run_schema_report(base.resolve(), base_report_path)
        output_report = run_schema_report(output.resolve(), output_report_path)
    finally:
        if base_report_path.exists():
            safe_output_path(base_report_path, "temporary baseline report").unlink()
    base_actions = schema_action_counts(base_report)
    output_actions = schema_action_counts(output_report)
    new_actions = {
        "|".join(key): count - base_actions.get(key, 0)
        for key, count in output_actions.items()
        if count > base_actions.get(key, 0)
    }
    if new_actions:
        raise ValueError(
            f"decoder-compatible candidate introduces schema issues beyond its native base: {new_actions}"
        )
    resolved_actions = {
        "|".join(key): count - output_actions.get(key, 0)
        for key, count in base_actions.items()
        if count > output_actions.get(key, 0)
    }
    return {
        "valid": True,
        "validation_mode": "installed-schema-against-exact-native-getter-baseline",
        "validator_declared_valid": output_report.get("valid") is True,
        "output_totals": output_report.get("totals"),
        "baseline_totals": base_report.get("totals"),
        "new_schema_issue_fingerprints": 0,
        "resolved_baseline_issue_counts": resolved_actions,
        "documented_runtime_exceptions_are_reported_not_hidden": True,
    }


def build_candidate(
    canonical: list[Record], base: list[Record]
) -> tuple[list[Record], dict[str, Any]]:
    canonical_counts = count_types(canonical)
    base_counts = count_types(base)
    assert_count_subset(canonical_counts, EXPECTED_CANONICAL_COUNTS, "canonical")
    assert_count_subset(base_counts, EXPECTED_BASE_COUNTS, "saved getter base")
    canonical_by_id = id_map(canonical, "canonical")
    base_by_id = id_map(base, "base")

    canonical_routes = [record for record in canonical if record.kind in {"LINE", "ARC", "FILL", "VIA"}]
    canonical_route_by_id = id_map(canonical_routes, "canonical routes")
    base_route_ids = {
        record.record_id for record in base
        if record.kind in {"LINE", "ARC", "FILL", "VIA", "POLY"}
    }
    missing = [record for record in canonical_routes if record.record_id not in base_route_ids]
    missing_counts = count_types(missing)
    if missing_counts != Counter({"LINE": 603, "FILL": 226}):
        raise ValueError(f"unexpected missing primitive counts: {missing_counts}")

    missing_lines = [record for record in missing if record.kind == "LINE"]
    missing_fills = [record for record in missing if record.kind == "FILL"]
    line_layers = Counter(layer_id(record) for record in missing_lines)
    fill_layers = Counter(layer_id(record) for record in missing_fills)
    if dict(sorted(line_layers.items())) != EXPECTED_MISSING_LINE_BY_LAYER:
        raise ValueError(f"unexpected missing LINE layer inventory: {line_layers}")
    if dict(sorted(fill_layers.items())) != EXPECTED_MISSING_FILL_BY_LAYER:
        raise ValueError(f"unexpected missing FILL layer inventory: {fill_layers}")

    # Every ArcTrack and VIA survived byte-geometrically.  Every non-missing
    # LINE also survived byte-geometrically; only getter serialization fields
    # outside the geometry signature may differ.
    surviving_geometry_mismatches: list[dict[str, Any]] = []
    for source_record in canonical_routes:
        live_record = base_by_id.get(source_record.record_id)
        if live_record is None:
            continue
        if source_record.kind != live_record.kind:
            surviving_geometry_mismatches.append({
                "id": source_record.record_id,
                "source_type": source_record.kind,
                "base_type": live_record.kind,
                "reason": "type",
            })
            continue
        if not geometry_values_equivalent(
            geometry_payload(source_record), geometry_payload(live_record)
        ):
            # The sole polygon FILL survivor is allowed to have its endpoint
            # snapped closed by the decoder; it is normalized below from the
            # canonical contour.
            if source_record.kind != "FILL" or is_circle_fill(source_record):
                surviving_geometry_mismatches.append({
                    "id": source_record.record_id,
                    "source_type": source_record.kind,
                    "base_type": live_record.kind,
                    "reason": "geometry",
                })
    if surviving_geometry_mismatches:
        raise ValueError(
            "surviving canonical route geometry changed unexpectedly: "
            f"{surviving_geometry_mismatches[:12]}"
        )

    canonical_polygon_fills = [
        record for record in canonical if record.kind == "FILL" and not is_circle_fill(record)
    ]
    canonical_circle_fills = [
        record for record in canonical if record.kind == "FILL" and is_circle_fill(record)
    ]
    if len(canonical_polygon_fills) != 227 or len(canonical_circle_fills) != 400:
        raise ValueError(
            "canonical FILL representation changed: "
            f"polygon={len(canonical_polygon_fills)}, circle={len(canonical_circle_fills)}"
        )
    base_fill_ids = {record.record_id for record in base if record.kind == "FILL"}
    surviving_polygon_ids = {
        record.record_id for record in canonical_polygon_fills if record.record_id in base_fill_ids
    }
    if len(surviving_polygon_ids) != 1:
        raise ValueError(f"expected one decoder-surviving polygon FILL, got {surviving_polygon_ids}")

    replacements: dict[str, Record] = {}
    append_records: list[Record] = []
    line_poly_audit: list[dict[str, Any]] = []
    capsule_audit: list[dict[str, Any]] = []
    fill_closure_audit: list[dict[str, Any]] = []

    for record in missing_lines:
        record_layer = layer_id(record)
        if record_layer in COPPER_LAYERS:
            replacement, audit = line_to_capsule_fill(record)
            capsule_audit.append(audit)
        elif record_layer == 3:
            replacement = line_to_poly(record, "NORMAL")
            _, _, _, _, width, distance = line_geometry(record)
            line_poly_audit.append({
                "id": record.record_id,
                "ticket": record.ticket,
                "layer_id": record_layer,
                "poly_type": "NORMAL",
                "length_mil": distance,
                "width_mil": width,
            })
        elif record_layer == 11:
            replacement = line_to_poly(record, "BOARD_OUTLINE")
            _, _, _, _, width, distance = line_geometry(record)
            line_poly_audit.append({
                "id": record.record_id,
                "ticket": record.ticket,
                "layer_id": record_layer,
                "poly_type": "BOARD_OUTLINE",
                "length_mil": distance,
                "width_mil": width,
            })
        else:
            raise ValueError(f"unsupported missing LINE layer: {record_layer}")
        append_records.append(replacement)

    for record in canonical_polygon_fills:
        replacement, audit = close_polygon_fill(record)
        fill_closure_audit.append(audit)
        if record.record_id in base_by_id:
            replacements[record.record_id] = replacement
        else:
            append_records.append(replacement)

    if len(capsule_audit) != 103:
        raise AssertionError(f"expected 103 copper capsules, got {len(capsule_audit)}")
    if Counter(item["layer_id"] for item in line_poly_audit) != Counter({3: 492, 11: 8}):
        raise AssertionError("non-copper LINE-to-POLY inventory mismatch")
    if len(fill_closure_audit) != 227:
        raise AssertionError("polygon FILL closure inventory mismatch")
    gaps = [item["implicit_closure_gap_mil"] for item in fill_closure_audit]
    missing_gaps = [
        item["implicit_closure_gap_mil"]
        for item in fill_closure_audit
        if item["id"] not in surviving_polygon_ids
    ]
    survivor_gap = next(
        item["implicit_closure_gap_mil"]
        for item in fill_closure_audit
        if item["id"] in surviving_polygon_ids
    )
    if not survivor_gap < 0.1 or not min(missing_gaps) >= 0.1:
        raise AssertionError(
            "installed decoder 0.1 mil auto-close boundary no longer separates the FILLs: "
            f"survivor={survivor_gap}, missing_min={min(missing_gaps)}"
        )

    # Getter serialization re-tickets the accepted document densely.  Original
    # canonical tickets therefore collide with unrelated saved-base rows.  IDs
    # are the durable primitive identity; bind the one in-place replacement to
    # its saved ticket and allocate fresh unique tickets to recovered rows.
    for record_id, replacement in replacements.items():
        replacement.header["ticket"] = base_by_id[record_id].ticket
    numeric_base_tickets = [
        int(record.ticket) for record in base
        if isinstance(record.ticket, (int, float)) and not isinstance(record.ticket, bool)
    ]
    next_ticket = max(numeric_base_tickets, default=0) + 1
    for record in append_records:
        record.header["ticket"] = next_ticket
        next_ticket += 1
    output_ticket_by_id = {
        **{record_id: replacement.ticket for record_id, replacement in replacements.items()},
        **{record.record_id: record.ticket for record in append_records},
    }
    for audit_group in (capsule_audit, line_poly_audit, fill_closure_audit):
        for item in audit_group:
            if item["id"] in output_ticket_by_id:
                item["output_ticket"] = output_ticket_by_id[item["id"]]

    append_ids = {record.record_id for record in append_records}
    if len(append_ids) != len(append_records):
        raise AssertionError("generated append records contain duplicate IDs")
    if append_ids & set(base_by_id):
        raise AssertionError("generated append record collides with a saved-base ID")
    append_tickets = {record.ticket for record in append_records}
    base_tickets = {record.ticket for record in base if record.ticket is not None}
    if len(append_tickets) != len(append_records):
        raise AssertionError("generated append records contain duplicate tickets")
    if append_tickets & base_tickets:
        raise AssertionError("generated append record collides with a saved-base ticket")

    output: list[Record] = []
    for record in base:
        output.append(replacements.get(record.record_id, record))
    output.extend(append_records)

    output_by_id = id_map(output, "output")
    if set(output_by_id) != set(base_by_id) | append_ids:
        raise AssertionError("output record ID set differs from base plus exact recovered IDs")
    output_counts = count_types(output)
    assert_count_subset(output_counts, EXPECTED_OUTPUT_COUNTS, "output")

    protected_before = subset_digest(base, PROTECTED_TYPES)
    protected_after = subset_digest(output, PROTECTED_TYPES)
    if protected_before != protected_after:
        raise AssertionError("adapter changed protected identity/component/net/rule/layer records")
    if subset_digest(base, frozenset({"ARC"})) != subset_digest(output, frozenset({"ARC"})):
        raise AssertionError("adapter changed native ArcTrack records")
    if subset_digest(base, frozenset({"VIA"})) != subset_digest(output, frozenset({"VIA"})):
        raise AssertionError("adapter changed VIA records")
    if subset_digest(base, frozenset({"LINE"})) != subset_digest(output, frozenset({"LINE"})):
        raise AssertionError("adapter changed surviving non-degenerate LINE records")

    base_nets: set[str] = set()
    for record in base:
        if record.kind != "NET":
            continue
        try:
            parsed_id = json.loads(record.record_id)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NET has invalid JSON identity: {record.record_id}") from exc
        if not (
            isinstance(parsed_id, list) and len(parsed_id) == 2
            and parsed_id[0] == "NET" and isinstance(parsed_id[1], str)
        ):
            raise ValueError(f"NET has unsupported identity: {record.record_id}")
        base_nets.add(parsed_id[1])
    recovered_copper_nets = {
        str(record.body.get("netName") or "")
        for record in append_records if record.kind == "FILL" and layer_id(record) in COPPER_LAYERS
    }
    if "" in recovered_copper_nets or not recovered_copper_nets <= base_nets:
        raise AssertionError("recovered copper FILL uses a net absent from native NET records")

    report = {
        "schema": "stm32h747-native-pcb-decoder-compatibility-v1",
        "status": "static-candidate-awaiting-native-import-netlist-drc-and-export-verification",
        "manufacturing_ready": False,
        "installed_decoder_evidence": {
            "easyeda_executable_version": "3.2.206",
            "pcb_bundle": "pro-pcb/3.2.193.682ed44e/js/pcb.js",
            "line_finish_threshold": (
                "Q4.finish divides native mil coordinates by 10 and rejects tracks whose "
                "internal endpoint distance is <0.01 (raw length <0.1 mil)"
            ),
            "fill_closure_threshold": (
                "Od.parseShapeModel first tests exact closure at 1e-4 internal, then oVe "
                "auto-snaps multi-segment contours only when endpoint gap is <0.01 "
                "internal (raw gap <0.1 mil); otherwise Fill Region finish returns null"
            ),
        },
        "input_audit": {
            "canonical_counts": dict(sorted(canonical_counts.items())),
            "saved_getter_counts": dict(sorted(base_counts.items())),
            "missing_counts": dict(sorted(missing_counts.items())),
            "missing_line_by_layer": dict(sorted(line_layers.items())),
            "missing_fill_by_layer": dict(sorted(fill_layers.items())),
            "canonical_circle_fill_count": len(canonical_circle_fills),
            "canonical_polygon_fill_count": len(canonical_polygon_fills),
            "decoder_surviving_polygon_fill_ids": sorted(surviving_polygon_ids),
            "surviving_route_geometry_mismatches_excluding_decoder_snapped_fill": 0,
        },
        "transformations": {
            "copper_sub_0_1_mil_line_to_same_id_net_bearing_solid_fill_capsule": {
                "count": len(capsule_audit),
                "by_layer": dict(sorted(Counter(item["layer_id"] for item in capsule_audit).items())),
                "minimum_source_length_mil": min(item["source_length_mil"] for item in capsule_audit),
                "maximum_source_length_mil": max(item["source_length_mil"] for item in capsule_audit),
                "formal_track_semantics_retained": False,
                "physical_geometry": (
                    "exact analytic round-capped capsule: two tangent lines plus two -180 degree arcs"
                ),
                "electrical_geometry": "net-bearing copper Fill Region",
                "records": capsule_audit,
            },
            "non_copper_line_to_same_id_poly": {
                "count": len(line_poly_audit),
                "by_layer_and_poly_type": {
                    "3:NORMAL": 492,
                    "11:BOARD_OUTLINE": 8,
                },
                "records": line_poly_audit,
            },
            "polygon_fill_explicit_closure": {
                "count": len(fill_closure_audit),
                "decoder_dropped_recovered": len(missing_fills),
                "decoder_survivor_normalized": len(surviving_polygon_ids),
                "all_single_contour": True,
                "minimum_implicit_gap_mil": min(gaps),
                "maximum_implicit_gap_mil": max(gaps),
                "minimum_dropped_gap_mil": min(missing_gaps),
                "survivor_gap_mil": survivor_gap,
                "records": fill_closure_audit,
            },
        },
        "preservation": {
            "base_dochead_meta_canvas_components_pad_net_net_attr_rules_layers_semantic_sha256": protected_before,
            "protected_records_unchanged": True,
            "native_valid_layer_count": base_counts["LAYER"],
            "native_valid_layer_phys_count": base_counts["LAYER_PHYS"],
            "arc_track_count": base_counts["ARC"],
            "arc_track_semantic_sha256": subset_digest(base, frozenset({"ARC"})),
            "all_arc_tracks_unchanged": True,
            "via_count": base_counts["VIA"],
            "all_vias_unchanged": True,
            "surviving_line_count": base_counts["LINE"],
            "all_non_degenerate_line_tracks_unchanged": True,
            "native_rules_mutated": False,
        },
        "output_audit": {
            "counts": dict(sorted(output_counts.items())),
            "record_count": len(output),
            "unique_record_ids": len(output_by_id),
            "recovered_record_ids": sorted(append_ids),
            "recovered_record_count": len(append_ids),
            "pure_addition_count": len(append_records),
            "in_place_replacement_count": len(replacements),
            "recovered_ticket_range": [min(append_tickets), max(append_tickets)],
            "recovered_copper_net_count": len(recovered_copper_nets),
        },
        "rule_note": {
            "gerber_job_nominal_clearance_mm": 0.10,
            "gerber_job_minimum_line_width_mm": 0.15,
            "native_default_rule_records_preserved": True,
            "rule_configuration_required_before_manufacturing": True,
        },
        "required_post_import_gates": [
            "setDocumentSource must return accepted=true on a native six-layer PCB",
            "save/reopen getter must retain LINE5424 ARC2184 POLY500 FILL730 VIA634 PAD4",
            "native registry must retain COMPONENT330 and PAD_NET1176",
            "native non-empty net set must remain the exact latest 279-net set",
            "native netlist comparison must pass",
            "native DRC must pass with the intended 0.10 mm clearance and 0.15 mm minimum line-width rules configured",
            "Gerber/manufacturing export geometry must be compared with the source Gerber before release",
        ],
    }
    return output, report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--schema-report", type=Path, default=DEFAULT_SCHEMA_REPORT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        for path, label in ((args.canonical, "canonical"), (args.base, "base")):
            if not path.is_file():
                raise FileNotFoundError(f"{label} source is missing: {path}")
        canonical_sha = sha256_file(args.canonical)
        base_sha = sha256_file(args.base)
        if canonical_sha != CANONICAL_SHA256:
            raise ValueError(f"canonical SHA mismatch: {canonical_sha} != {CANONICAL_SHA256}")
        if base_sha != BASE_SHA256:
            raise ValueError(f"base SHA mismatch: {base_sha} != {BASE_SHA256}")
        canonical = parse_source(args.canonical, "canonical")
        base = parse_source(args.base, "saved-getter-base")
        output, report = build_candidate(canonical, base)
        output_text = serialize_source(output)
        output_sha = sha256_bytes(output_text.encode("utf-8"))
        report["inputs"] = {
            "canonical": {"path": str(args.canonical), "sha256": canonical_sha},
            "saved_six_layer_getter_base": {"path": str(args.base), "sha256": base_sha},
        }
        report["output"] = {
            "path": str(args.output),
            "sha256": output_sha,
            "bytes": len(output_text.encode("utf-8")),
            "trailing_pipe": False,
        }
        if args.dry_run:
            print(compact({
                "status": "dry-run-complete-no-files-written",
                "sha256": output_sha,
                "counts": report["output_audit"]["counts"],
            }))
            return 0

        args.output = safe_output_path(args.output, "native output")
        args.report = safe_output_path(args.report, "manifest")
        args.schema_report = safe_output_path(args.schema_report, "schema report")
        atomic_write_text(args.output, output_text)
        diagnostic = baseline_aware_schema_validation(
            args.output, args.schema_report, args.base
        )
        report["strict_installed_schema"] = {
            "path": str(args.schema_report),
            "sha256": sha256_file(args.schema_report),
            **diagnostic,
        }
        atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(compact({
            "status": report["status"],
            "sha256": output_sha,
            "counts": report["output_audit"]["counts"],
            "schema_valid": True,
            "manufacturing_ready": False,
        }))
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
