#!/usr/bin/env python3
"""Build a read-only-evidence plan for hiding unused inner-layer pad copper.

The input project/checkpoint and Gerber files are never modified.  The script
emits full-footprint native-source candidates for J2..J17 where the only body
change is ``PAD.unusedInnerLayers``.  It also proves the installed 3.2 runtime
semantics, scans all extracted Gerber copper primitives at each pad centre, and
measures the original plane-void clearance from the plated drill edge.

The candidates are deliberately *not* applied.  EasyEDA API/UI writes remain a
separate, guarded operation followed by native DRC and a checkpoint audit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
PROJECT_SOURCE_ENTRY = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_drl_slot_fix_20261014.epro2"
)
DEFAULT_PCB_SOURCE = (
    ROOT / "output" / "validation" /
    "native-final-pcb-after_drl_slot_fix-reopened.epru"
)
DEFAULT_CLEARANCE = (
    ROOT / "output" / "validation" /
    "native-pcb-clearance-drc-final-analysis.json"
)
DEFAULT_ROUTES = ROOT / "output" / "semantic" / "gerber-copper-routes.json"
DEFAULT_CANDIDATE_DIR = (
    ROOT / "output" / "native-libraries" /
    "unused-inner-layer-pad-candidates"
)
DEFAULT_REPORT = (
    ROOT / "output" / "validation" /
    "native-unused-inner-layer-pad-analysis.json"
)

INSTALL_ROOT = Path(
    r"C:\Program Files\easyeda-pro\resources\app\assets"
)
PCB_JS = INSTALL_ROOT / "pro-pcb" / "3.2.193.682ed44e" / "js" / "pcb.js"
DRC_JS = INSTALL_ROOT / "pro-pcb" / "3.2.193.682ed44e" / "js" / "drcWorker.js"
FORMAT_SCHEMA = (
    INSTALL_ROOT / "pro-api" / "0.3.50.ab46409c" / "assets" /
    "format-types.schema-ZEA4IXWZ.json"
)
PAD_FORMAT_DOC = ROOT / ".tools" / "easyeda-api" / "format" / "pcb" / "pad_via.md"
PAD_API_DOC = (
    ROOT / ".tools" / "easyeda-api" / "references" / "classes" /
    "IPCB_PrimitivePad.md"
)

TARGET_REFS = tuple(f"J{number}" for number in range(2, 18))
WITHHELD_REFS = ("U5", "U7")
INNER_LAYER_NAMES = {15: "In1.Cu", 16: "In2.Cu", 17: "In3.Cu", 18: "In4.Cu"}
MM_PER_MIL = 0.0254
MIL_PER_MM = 1.0 / MM_PER_MIL
HEX16 = re.compile(r"^[0-9a-f]{16}$")


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
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def atomic_write_bytes(path: Path, value: bytes) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(value)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


@dataclass(frozen=True)
class Record:
    header: dict[str, Any]
    body: dict[str, Any]
    raw: bytes

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")


@dataclass
class Document:
    uuid: str
    doc_type: str
    records: list[Record]


def parse_record(raw: bytes, label: str) -> Record:
    line = raw.rstrip(b"\r\n")
    normalized = line if line.endswith(b"|") else line + b"|"
    try:
        header_raw, body_raw = normalized[:-1].split(b"||", 1)
        header = json.loads(header_raw.decode("utf-8-sig"))
        body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: invalid native record") from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError(f"{label}: native header/body is not an object")
    return Record(header, body, raw)


def parse_source(path: Path) -> list[Record]:
    return [
        parse_record(raw, f"{path}:{index}")
        for index, raw in enumerate(path.read_bytes().splitlines(keepends=True), 1)
        if raw.strip()
    ]


def parse_documents(checkpoint: Path) -> list[Document]:
    documents: list[Document] = []
    current: Document | None = None
    with zipfile.ZipFile(checkpoint) as archive:
        with archive.open(PROJECT_SOURCE_ENTRY) as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                record = parse_record(raw, f"{PROJECT_SOURCE_ENTRY}:{line_number}")
                if record.kind == "DOCHEAD":
                    current = Document(
                        str(record.body.get("uuid") or ""),
                        str(record.body.get("docType") or ""),
                        [],
                    )
                    documents.append(current)
                if current is None:
                    raise ValueError(f"record before DOCHEAD at line {line_number}")
                current.records.append(record)
    return documents


def serialize_record(record: Record, body: dict[str, Any]) -> bytes:
    return f"{compact(record.header)}||{compact(body)}|\n".encode("utf-8")


def document_meta(document: Document) -> dict[str, Any]:
    metas = [record.body for record in document.records if record.kind == "META"]
    if len(metas) != 1:
        raise AssertionError(f"{document.uuid}: expected one META, found {len(metas)}")
    return metas[0]


def rotate_point(x: float, y: float, angle_degrees: float) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )


def distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.hypot(float(left[0]) - float(right[0]), float(left[1]) - float(right[1]))


def point_segment_distance(
    point: Sequence[float], start: Sequence[float], end: Sequence[float]
) -> float:
    px, py = map(float, point)
    ax, ay = map(float, start)
    bx, by = map(float, end)
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    ratio = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + ratio * dx), py - (ay + ratio * dy))


def angle_on_sweep(angle: float, start: float, end: float, clockwise: bool) -> bool:
    full = 2.0 * math.pi
    if clockwise:
        return ((start - angle) % full) <= ((start - end) % full) + 1e-12
    return ((angle - start) % full) <= ((end - start) % full) + 1e-12


def point_arc_distance(point: Sequence[float], item: dict[str, Any]) -> float:
    center = item["centerMm"]
    start = item["startMm"]
    end = item["endMm"]
    radius = distance(center, start)
    angle = math.atan2(float(point[1]) - center[1], float(point[0]) - center[0])
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    if angle_on_sweep(angle, start_angle, end_angle, bool(item.get("clockwise"))):
        return abs(distance(point, center) - radius)
    return min(distance(point, start), distance(point, end))


def contour_points(contour: list[dict[str, Any]]) -> list[list[float]]:
    if not contour:
        return []
    points = [list(map(float, contour[0]["startMm"]))]
    for index, segment in enumerate(contour):
        if segment.get("kind") != "line":
            raise AssertionError(f"region segment {index} is not a line")
        if distance(points[-1], segment["startMm"]) > 2e-6:
            raise AssertionError(f"region contour discontinuity at {index}")
        points.append(list(map(float, segment["endMm"])))
    return points


def point_in_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    x, y = map(float, point)
    inside = False
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        if point_segment_distance(point, previous, current) <= 1e-9:
            return True
        x1, y1 = map(float, current)
        x2, y2 = map(float, previous)
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def flash_envelope_radius(flash: dict[str, Any]) -> float:
    shape = str(flash.get("shape") or "")
    params = [float(value) for value in flash.get("paramsMm") or []]
    if shape == "C" and params:
        return params[0] / 2.0
    if shape in {"R", "O"} and len(params) >= 2:
        return math.hypot(params[0], params[1]) / 2.0
    if shape == "RoundRect" and len(params) >= 4:
        radius = abs(params[0])
        coordinates = params[1:-1]
        points = list(zip(coordinates[0::2], coordinates[1::2]))
        return max((math.hypot(x, y) for x, y in points), default=0.0) + radius
    raise AssertionError(f"unsupported Gerber flash shape: {shape} {params}")


def source_copper_coverage(
    routes: dict[str, Any], layer_name: str, point: Sequence[float]
) -> dict[str, Any]:
    layer = routes["copper"]["layers"][layer_name]
    flashes: list[dict[str, Any]] = []
    for index, flash in enumerate(layer.get("conductorFlashes") or []):
        center = flash.get("atMm")
        if center and distance(center, point) <= flash_envelope_radius(flash) + 1e-9:
            flashes.append({
                "index": index,
                "net": flash.get("netOld"),
                "shape": flash.get("shape"),
                "center_distance_mm": distance(center, point),
            })
    tracks: list[dict[str, Any]] = []
    for index, track in enumerate(layer.get("tracks") or []):
        kind = str(track.get("kind") or "")
        if kind == "line":
            centerline_distance = point_segment_distance(point, track["startMm"], track["endMm"])
        elif kind == "arc":
            centerline_distance = point_arc_distance(point, track)
        else:
            raise AssertionError(f"unsupported track kind {kind!r}")
        width = float(track.get("widthMm") or 0)
        if centerline_distance <= width / 2.0 + 1e-9:
            tracks.append({
                "index": index,
                "kind": kind,
                "net": track.get("netOld"),
                "centerline_distance_mm": centerline_distance,
                "width_mm": width,
            })
    regions: list[dict[str, Any]] = []
    for index, region in enumerate(layer.get("regions") or []):
        covered = any(
            point_in_polygon(point, contour_points(contour))
            for contour in region.get("contours") or []
        )
        if covered:
            regions.append({"index": index, "net": region.get("netOld")})
    return {
        "covered": bool(flashes or tracks or regions),
        "flashes": flashes,
        "tracks": tracks,
        "regions": regions,
    }


def path_points(path: Sequence[Any]) -> list[tuple[float, float]]:
    if len(path) < 5 or path[2] != "L":
        raise AssertionError("expected native straight-line FILL path")
    values = path[3:]
    if len(values) % 2:
        raise AssertionError("native FILL path has an odd coordinate count")
    return [(float(path[0]), float(path[1]))] + [
        (float(values[index]), float(values[index + 1]))
        for index in range(0, len(values), 2)
    ]


def point_bbox(points: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    values = list(points)
    return (
        min(float(point[0]) for point in values),
        min(float(point[1]) for point in values),
        max(float(point[0]) for point in values),
        max(float(point[1]) for point in values),
    )


def region_native_bbox(
    region: dict[str, Any], bounds: Sequence[float]
) -> tuple[float, float, float, float]:
    min_x, min_y = map(float, bounds[:2])
    points = [
        ((float(point[0]) - min_x) * MIL_PER_MM, (float(point[1]) - min_y) * MIL_PER_MM)
        for contour in region.get("contours") or []
        for segment in contour
        for point in (segment["startMm"], segment["endMm"])
    ]
    return point_bbox(points)


def match_fill_regions(
    fill_ids: set[str], source_by_id: dict[str, Record], routes: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    bounds = routes["coordinateTransform"]["boardBoundsSourceMm"]
    result: dict[str, dict[str, Any]] = {}
    for fill_id in sorted(fill_ids):
        fill = source_by_id[fill_id]
        paths = fill.body.get("path") or []
        if len(paths) != 1:
            raise AssertionError(f"{fill_id}: expected one FILL path")
        native_bbox = point_bbox(path_points(paths[0]))
        layer_id = int(fill.body["layerId"])
        layer_name = INNER_LAYER_NAMES[layer_id]
        choices: list[tuple[float, int, dict[str, Any]]] = []
        for index, region in enumerate(routes["copper"]["layers"][layer_name]["regions"]):
            candidate_bbox = region_native_bbox(region, bounds)
            delta = max(abs(left - right) for left, right in zip(native_bbox, candidate_bbox))
            choices.append((delta, index, region))
        choices.sort(key=lambda item: item[0])
        if not choices or choices[0][0] > 0.001:
            raise AssertionError(f"{fill_id}: no exact Gerber-region bbox match: {choices[:2]}")
        if len(choices) > 1 and abs(choices[1][0] - choices[0][0]) <= 0.001:
            raise AssertionError(f"{fill_id}: ambiguous Gerber-region bbox match")
        delta, index, region = choices[0]
        result[fill_id] = {
            "layer_name": layer_name,
            "region_index": index,
            "bbox_max_delta_mil": delta,
            "net_old": region.get("netOld"),
            "region": region,
        }
    return result


def code_evidence(path: Path, needles: dict[str, str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    matches: dict[str, Any] = {}
    for label, needle in needles.items():
        index = text.find(needle)
        if index < 0:
            raise AssertionError(f"installed runtime evidence missing: {path.name}:{label}")
        context = text[max(0, index - 160): index + len(needle) + 160]
        matches[label] = {
            "byte_index_utf8_text": index,
            "needle": needle,
            "context_sha256": sha256_bytes(context.encode()),
        }
    return {"path": str(path), "sha256": sha256_file(path), "matches": matches}


def line_numbers(path: Path, needles: dict[str, str]) -> dict[str, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    result: dict[str, int] = {}
    for label, needle in needles.items():
        matches = [index for index, line in enumerate(lines, 1) if needle in line]
        if len(matches) != 1:
            raise AssertionError(f"{path}:{label}: expected one line for {needle!r}, found {matches}")
        result[label] = matches[0]
    return result


def installed_semantics() -> dict[str, Any]:
    for path in (PCB_JS, DRC_JS, FORMAT_SCHEMA, PAD_FORMAT_DOC, PAD_API_DOC):
        if not path.is_file():
            raise FileNotFoundError(path)
    schema = json.loads(FORMAT_SCHEMA.read_text(encoding="utf-8"))
    pad_schema = schema["$defs"]["TPcbPad"]["allOf"][1]
    unused = pad_schema["properties"]["unusedInnerLayers"]
    required = pad_schema["required"]
    api_text = PAD_API_DOC.read_text(encoding="utf-8")
    return {
        "format_document": {
            "path": str(PAD_FORMAT_DOC),
            "sha256": sha256_file(PAD_FORMAT_DOC),
            "lines": line_numbers(PAD_FORMAT_DOC, {
                "special_pad_definition": "16. specialPad special pads",
                "unused_inner_layers_definition": "30. unusedInnerLayers hidden pad layers",
            }),
            "semantics": {
                "specialPad": "per-layer-range pad shape override",
                "unusedInnerLayers": "inner copper layers on which the pad is hidden",
            },
        },
        "installed_schema": {
            "path": str(FORMAT_SCHEMA),
            "sha256": sha256_file(FORMAT_SCHEMA),
            "json_path": "$defs.TPcbPad.allOf[1].properties.unusedInnerLayers",
            "type": unused.get("type"),
            "item_type": unused.get("items", {}).get("type"),
            "comment": unused.get("$comment"),
            "optional": "unusedInnerLayers" not in required,
            "separate_required_fields": [
                field for field in ("hole", "defaultPad", "specialPad", "plated")
                if field in required
            ],
        },
        "pcb_runtime": code_evidence(PCB_JS, {
            "serializer_preserves_array": 'case"unusedInnerLayers":return e.unusedInnerLayers',
            "decoder_defaults_to_empty_array": "this.unusedInnerLayers=W||[]",
            "layer_geometry_short_circuit": (
                "getMathGraphics(e=this.layerId,r=0){if(this.isEmpty||this.isUnuseLayer(e))return null;"
            ),
            "hole_geometry_is_separate_layer_12_or_47": (
                "else if(e==12||47===e){if(this.hole!=null)return this.hole.getShape"
            ),
            "used_copper_layers_exclude_array": (
                "for(let n of i)r.has(n)||e.push(n)"
            ),
        }),
        "drc_runtime": code_evidence(DRC_JS, {
            "hidden_pad_skips_inner_layer_shape_check": "if(t.isUnuseLayer(e.layerId))return;",
            "hole_clearance_uses_layer_12": (
                "(this._holeStatus==1||t instanceof rt)&&this.checkError2Result(e.layerId,12)"
            ),
            "pad_cache_uses_layer_geometry": (
                "getPadCache(e,t){let r=this.getCache2(e,t);if(r==null)"
            ),
        }),
        "public_primitive_api": {
            "path": str(PAD_API_DOC),
            "sha256": sha256_file(PAD_API_DOC),
            "unusedInnerLayers_exposed": "unusedInnerLayers" in api_text,
            "specialPad_setter_documented_no_effect_in_current_version": (
                "current version does not produce any effect" in api_text
                or "当前版本不产生任何效果" in api_text
            ),
            "conclusion": (
                "Use the native PAD body field in a full FOOTPRINT source; the current "
                "public primitive wrapper has no unusedInnerLayers setter. specialPad is "
                "not a substitute for hiding an inner layer."
            ),
        },
        "semantic_conclusion": {
            "hidden_inner_pad_copper": True,
            "plated_drill_hole_preserved": True,
            "outer_pad_shape_preserved_when_other_fields_unchanged": True,
            "drc_hole_clearance_remains_active": True,
        },
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.checkpoint, args.pcb_source, args.clearance, args.routes):
        if not path.is_file():
            raise FileNotFoundError(path)
    clearance = json.loads(args.clearance.read_text(encoding="utf-8"))
    routes = json.loads(args.routes.read_text(encoding="utf-8"))
    source_records = parse_source(args.pcb_source)
    source_by_id = {record.record_id: record for record in source_records}
    documents = parse_documents(args.checkpoint)
    document_by_uuid = {document.uuid: document for document in documents}
    if len(document_by_uuid) != len(documents):
        raise AssertionError("checkpoint contains duplicate document UUIDs")

    evidence = clearance["fill_to_th_pad_zero_evidence"]["evidence"]
    pad_patterns = clearance["fill_to_th_pad_zero_evidence"]["reference_pad_layer_patterns"]
    patterns_by_key = {
        (str(item["reference"]), str(item["pad_number"]), str(item["pad_primitive_id"])): item
        for item in pad_patterns
    }
    evidence_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        key = (str(item["reference"]), str(item["pad_number"]), str(item["pad_primitive_id"]))
        evidence_by_key[key].append(item)
    if set(patterns_by_key) != set(evidence_by_key):
        raise AssertionError("clearance evidence/pattern pad keys differ")

    all_pad_layer_coverage: list[dict[str, Any]] = []
    for key, pattern in sorted(patterns_by_key.items()):
        sample = evidence_by_key[key][0]
        point = sample["coordinates"]["gerber_source_center_mm_expected"]
        absent = set(map(int, pattern["gerber_absent_native_layer_ids"]))
        present = set(map(int, pattern["gerber_present_native_layer_ids"]))
        if absent | present != set(INNER_LAYER_NAMES) or absent & present:
            raise AssertionError(f"{key}: Gerber layer partition is not exact")
        for layer_id, layer_name in INNER_LAYER_NAMES.items():
            coverage = source_copper_coverage(routes, layer_name, point)
            expected = "absent" if layer_id in absent else "present"
            matches_expected = (
                (expected == "absent" and not coverage["covered"])
                or (expected == "present" and coverage["covered"])
            )
            if key[0] in TARGET_REFS and not matches_expected:
                raise AssertionError(
                    f"{key} {layer_name}: target connector Gerber coverage contradicts "
                    f"the expected {expected!r} state"
                )
            if key[0] not in TARGET_REFS + WITHHELD_REFS:
                raise AssertionError(f"{key}: unexpected reference in zero-clearance evidence")
            all_pad_layer_coverage.append({
                "reference": key[0],
                "pad_number": key[1],
                "pad_primitive_id": key[2],
                "native_layer_id": layer_id,
                "gerber_layer": layer_name,
                "expected": expected,
                "matches_component_flash_expectation": matches_expected,
                **coverage,
            })

    fill_ids = {str(item["fill_id"]) for item in evidence}
    region_matches = match_fill_regions(fill_ids, source_by_id, routes)
    required_by_error = {
        str(item["global_index"]): float(item["required_mm"])
        for item in clearance["threshold_details"]["nonpositive"]
    }
    plane_void_rows: list[dict[str, Any]] = []
    for item in evidence:
        match = region_matches[str(item["fill_id"])]
        region = match["region"]
        point = item["coordinates"]["gerber_source_center_mm_expected"]
        contours = [contour_points(value) for value in region.get("contours") or []]
        if any(point_in_polygon(point, contour) for contour in contours):
            raise AssertionError(f"{item['global_index']}: pad drill centre lies in source plane copper")
        center_to_boundary = min(
            point_segment_distance(point, contour[index - 1], contour[index])
            for contour in contours
            for index in range(len(contour))
        )
        hole = item["native_pad"]["hole"]
        if hole.get("holeType") != "ROUND":
            raise AssertionError(f"{item['global_index']}: expected ROUND plated drill")
        hole_radius = min(float(hole["width"]), float(hole["height"])) * MM_PER_MIL / 2.0
        fill_half_width = (
            float(source_by_id[str(item["fill_id"])].body.get("width") or 0)
            * MM_PER_MIL / 2.0
        )
        hole_edge_clearance = center_to_boundary - hole_radius
        conservative_clearance = hole_edge_clearance - fill_half_width
        required = required_by_error[str(item["global_index"])]
        if conservative_clearance <= required:
            raise AssertionError(
                f"{item['global_index']}: source hole-edge clearance {conservative_clearance} "
                f"does not exceed native requirement {required}"
            )
        plane_void_rows.append({
            "global_index": item["global_index"],
            "reference": item["reference"],
            "pad_number": item["pad_number"],
            "native_layer_id": item["native_inner_layer_id"],
            "gerber_layer": item["gerber_inner_layer"],
            "fill_id": item["fill_id"],
            "fill_net": item["fill_net"],
            "pad_net": item["pad_net"],
            "region_index": match["region_index"],
            "region_bbox_match_max_delta_mil": match["bbox_max_delta_mil"],
            "center_to_source_region_boundary_mm": center_to_boundary,
            "plated_hole_radius_mm": hole_radius,
            "hole_edge_to_source_region_boundary_mm": hole_edge_clearance,
            "native_fill_half_width_mm": fill_half_width,
            "conservative_hole_edge_clearance_mm": conservative_clearance,
            "native_drc_required_mm": required,
            "margin_over_native_requirement_mm": conservative_clearance - required,
        })

    candidate_dir = safe_output_path(args.candidate_dir)
    candidate_rows: list[dict[str, Any]] = []
    all_modified_records = 0
    for reference in TARGET_REFS:
        matches = [
            (key, value) for key, value in patterns_by_key.items() if key[0] == reference
        ]
        if len(matches) != 2:
            raise AssertionError(f"{reference}: expected two target pads, found {len(matches)}")
        footprint_uuids = {str(value["footprint_uuid"]) for _key, value in matches}
        if len(footprint_uuids) != 1:
            raise AssertionError(f"{reference}: footprint UUID ambiguity")
        footprint_uuid = next(iter(footprint_uuids))
        if not HEX16.fullmatch(footprint_uuid):
            raise AssertionError(f"{reference}: invalid footprint UUID {footprint_uuid}")
        document = document_by_uuid.get(footprint_uuid)
        if document is None or document.doc_type != "FOOTPRINT":
            raise AssertionError(f"{reference}: project FOOTPRINT {footprint_uuid} missing")
        pads = {record.record_id: record for record in document.records if record.kind == "PAD"}
        target_by_id = {
            key[2]: list(map(int, value["gerber_absent_native_layer_ids"]))
            for key, value in matches
        }
        output_parts: list[bytes] = []
        modifications: list[dict[str, Any]] = []
        for record in document.records:
            if record.kind != "PAD" or record.record_id not in target_by_id:
                output_parts.append(record.raw)
                continue
            before = record.body
            if before.get("unusedInnerLayers") not in ([], None):
                raise AssertionError(f"{reference}:{record.record_id}: expected empty unusedInnerLayers")
            if before.get("layerId") != 12 or before.get("plated") is not True:
                raise AssertionError(f"{reference}:{record.record_id}: not a plated multilayer pad")
            if not before.get("hole") or not before.get("defaultPad"):
                raise AssertionError(f"{reference}:{record.record_id}: missing hole/defaultPad")
            after = dict(before)
            after["unusedInnerLayers"] = target_by_id[record.record_id]
            changed_keys = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            if changed_keys != ["unusedInnerLayers"]:
                raise AssertionError(f"{reference}:{record.record_id}: unexpected changes {changed_keys}")
            output_parts.append(serialize_record(record, after))
            protected = (
                "layerId", "num", "centerX", "centerY", "padAngle", "hole",
                "defaultPad", "specialPad", "padOffsetX", "padOffsetY",
                "relativeAngle", "plated", "netName",
            )
            if any(before.get(key) != after.get(key) for key in protected):
                raise AssertionError(f"{reference}:{record.record_id}: protected PAD field changed")
            modifications.append({
                "record_id": record.record_id,
                "ticket": record.header.get("ticket"),
                "pad_number": before.get("num"),
                "before_unused_inner_layers": before.get("unusedInnerLayers") or [],
                "after_unused_inner_layers": after["unusedInnerLayers"],
                "plated": before.get("plated"),
                "hole": before.get("hole"),
                "default_pad": before.get("defaultPad"),
                "special_pad": before.get("specialPad"),
                "center_mil": [before.get("centerX"), before.get("centerY")],
            })
        if len(modifications) != 2 or set(target_by_id) - set(pads):
            raise AssertionError(f"{reference}: target PAD records incomplete")
        candidate = b"".join(output_parts)
        candidate_name = f"{reference}_{footprint_uuid}.epru"
        candidate_path = candidate_dir / candidate_name
        atomic_write_bytes(candidate_path, candidate)
        parsed_candidate = parse_source(candidate_path)
        if len(parsed_candidate) != len(document.records):
            raise AssertionError(f"{reference}: candidate record count changed")
        if [record.record_id for record in parsed_candidate] != [
            record.record_id for record in document.records
        ]:
            raise AssertionError(f"{reference}: candidate record order/IDs changed")
        meta = document_meta(document)
        candidate_rows.append({
            "reference": reference,
            "footprint_uuid": footprint_uuid,
            "title": meta.get("title"),
            "candidate_path": str(candidate_path.relative_to(ROOT)),
            "candidate_sha256": sha256_bytes(candidate),
            "record_count": len(document.records),
            "modified_record_count": len(modifications),
            "modifications": modifications,
        })
        all_modified_records += len(modifications)

    if len(candidate_rows) != 16 or all_modified_records != 32:
        raise AssertionError("candidate cardinality is not 16 footprints / 32 PAD records")
    absent_rows = [row for row in all_pad_layer_coverage if row["expected"] == "absent"]
    present_rows = [row for row in all_pad_layer_coverage if row["expected"] == "present"]
    target_error_count = sum(
        int(value["clearance_error_count"])
        for key, value in patterns_by_key.items()
        if key[0] in TARGET_REFS
    )
    withheld_error_count = sum(
        int(value["clearance_error_count"])
        for key, value in patterns_by_key.items()
        if key[0] in WITHHELD_REFS
    )
    if target_error_count != 74 or withheld_error_count != 2:
        raise AssertionError("expected 74 connector and 2 exposed-pad zero-clearance errors")

    plane_values = [row["conservative_hole_edge_clearance_mm"] for row in plane_void_rows]
    report = {
        "schema": "stm32h747-unused-inner-layer-pad-plan-v1",
        "status": "static-evidence-pass-candidates-not-applied",
        "read_only_inputs": True,
        "inputs": {
            "checkpoint": {"path": str(args.checkpoint), "sha256": sha256_file(args.checkpoint)},
            "pcb_source": {"path": str(args.pcb_source), "sha256": sha256_file(args.pcb_source)},
            "clearance_analysis": {"path": str(args.clearance), "sha256": sha256_file(args.clearance)},
            "gerber_copper_routes": {"path": str(args.routes), "sha256": sha256_file(args.routes)},
        },
        "installed_3_2_semantics": installed_semantics(),
        "source_copper_coverage": {
            "pad_count": len(patterns_by_key),
            "pad_layer_combinations": len(all_pad_layer_coverage),
            "gerber_absent_combinations": len(absent_rows),
            "gerber_absent_combinations_with_any_dark_copper_at_center": sum(
                1 for row in absent_rows if row["covered"]
            ),
            "gerber_present_combinations": len(present_rows),
            "gerber_present_combinations_with_dark_copper_at_center": sum(
                1 for row in present_rows if row["covered"]
            ),
            "method": (
                "All extracted dark conductor flashes, stroked line/arc tracks, and additive "
                "region contours were tested at each drill centre. Gerber copper represents "
                "a drilled PTH pad as solid copper at the centre; the Excellon drill is applied "
                "separately. Therefore no dark copper at the centre is stronger evidence than "
                "component-pad-flash absence alone."
            ),
            "rows": all_pad_layer_coverage,
        },
        "plated_hole_plane_clearance": {
            "count": len(plane_void_rows),
            "matched_fill_ids": {
                fill_id: {
                    key: value for key, value in match.items() if key != "region"
                }
                for fill_id, match in sorted(region_matches.items())
            },
            "minimum_hole_edge_clearance_mm": min(plane_values),
            "maximum_hole_edge_clearance_mm": max(plane_values),
            "minimum_hole_edge_clearance_mil": min(plane_values) * MIL_PER_MM,
            "maximum_hole_edge_clearance_mil": max(plane_values) * MIL_PER_MM,
            "native_drc_display_requirement": ">= 6mil",
            "native_drc_required_mm_values": sorted({
                round(row["native_drc_required_mm"], 9) for row in plane_void_rows
            }),
            "all_conservative_clearances_exceed_native_requirement": True,
            "rows": plane_void_rows,
        },
        "candidate_scope": {
            "target_references": list(TARGET_REFS),
            "target_footprints": len(candidate_rows),
            "target_pad_records": all_modified_records,
            "zero_clearance_errors_addressed_by_scope": target_error_count,
            "withheld_references": list(WITHHELD_REFS),
            "withheld_zero_clearance_errors": withheld_error_count,
            "withheld_reason": (
                "U5/U7 exposed-pad drilled features are not included. The comprehensive raw "
                "Gerber scan found a same-net GND circular flash at each centre on all four "
                "inner layers, contradicting the component-footprint absent-flash heuristic. "
                "Their inner annuli must therefore be preserved pending a separate review."
            ),
            "only_field_changed": "PAD.body.unusedInnerLayers",
            "protected_fields": [
                "hole", "plated", "defaultPad", "specialPad", "num", "netName",
                "centerX", "centerY", "padAngle", "padOffsetX", "padOffsetY",
                "relativeAngle",
            ],
            "candidates": candidate_rows,
        },
        "application_gates": [
            "Do not apply through the public primitive wrapper; it has no unusedInnerLayers setter.",
            "Use each full checkpoint-derived FOOTPRINT source and preserve every non-target record.",
            "Verify project/name guard and create a recoverable checkpoint before any library write.",
            "After applying, clear/reload footprint and PCB caches before judging instantiated pads.",
            "Export a new full checkpoint and prove only the 32 PAD arrays changed.",
            "Run native DRC: the 74 connector Fill Region-to-TH Pad zero-clearance errors should disappear, while hole clearance checks must remain active.",
            "Do not infer manufacturing approval; all remaining clearance/connection errors still block release.",
        ],
    }
    manifest_path = candidate_dir / "manifest.json"
    atomic_write_json(manifest_path, report)
    report["candidate_manifest"] = {
        "path": str(manifest_path.relative_to(ROOT)),
        "sha256": sha256_file(manifest_path),
    }
    atomic_write_json(args.report, report)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--pcb-source", type=Path, default=DEFAULT_PCB_SOURCE)
    parser.add_argument("--clearance", type=Path, default=DEFAULT_CLEARANCE)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    report = build(parse_args(argv))
    print(compact({
        "status": report["status"],
        "candidate_footprints": report["candidate_scope"]["target_footprints"],
        "candidate_pad_records": report["candidate_scope"]["target_pad_records"],
        "connector_zero_errors_addressed": report["candidate_scope"]["zero_clearance_errors_addressed_by_scope"],
        "minimum_hole_edge_clearance_mil": report["plated_hole_plane_clearance"]["minimum_hole_edge_clearance_mil"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
