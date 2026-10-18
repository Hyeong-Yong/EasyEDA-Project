#!/usr/bin/env python3
"""Build reviewable, FILL-only clearance candidates for the native PCB.

This program is deliberately offline.  It never opens EasyEDA and never edits
the native project.  Its output is consumed by the guarded public-API runner
owned by the root task.  The native JLCPCB multilayer rules are inputs, not
parameters to relax.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import tempfile
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from shapely import affinity, orient_polygons, set_precision
    from shapely.geometry import (
        GeometryCollection,
        LineString,
        MultiPolygon,
        Point,
        Polygon,
        box,
    )
    from shapely.ops import transform, unary_union
    from shapely.strtree import STRtree
    from shapely.validation import explain_validity, make_valid
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    raise SystemExit(
        "Shapely is required. Use only STM32H747 board/.tools/geometry-venv "
        "(pinned Shapely 2.1.2); do not install into a shared runtime."
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output" / "candidates" / "multilayer-fill-clearance").resolve()
DEFAULT_SOURCE = ROOT / "output/validation/native-multilayer-via031_track013-reopened.epru"
DEFAULT_DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-via031_track013.json"
DEFAULT_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_final_reconstruction_20261015.epro2"
DEFAULT_PLAN = OUTPUT_ROOT / "multilayer-fill-clearance-plan.json"
DEFAULT_REPORT = OUTPUT_ROOT / "multilayer-fill-clearance-report.json"
DEFAULT_PILOT_PLAN = OUTPUT_ROOT / "multilayer-fill-clearance-pilot.json"
DEFAULT_REMAINING_PLAN = OUTPUT_ROOT / "multilayer-fill-clearance-remaining-plan.json"
DEFAULT_REMAINING_REPORT = OUTPUT_ROOT / "multilayer-fill-clearance-remaining-report.json"
DEFAULT_MULTICONTOUR_PILOT = OUTPUT_ROOT / "multilayer-fill-clearance-multicontour-pilot.json"
DEFAULT_AFTER_MULTICONTOUR_PLAN = OUTPUT_ROOT / "multilayer-fill-clearance-after-multicontour-plan.json"
CHECKPOINT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
PILOT_FILL_ID = "378b6a6933052c9a"
PROTECTED_FILL_IDS = frozenset({"402bcf974fe2c3d7"})

EXPECTED_PCB_UUID = "0ac2a19168000d8e"
EXPECTED_CLEARANCE_ERRORS = 2119
EXPECTED_FILL_CLEARANCE_ROWS = 1762
EXPECTED_FILL_COUNT = 730
EXPECTED_RULE_COUNT = 18
MM_PER_MIL = 0.0254
DISPLAY_MIL_PER_RAW_UNIT = 10.0
DEFAULT_SAFETY_MARGIN_MM = 0.005
DEFAULT_SAFETY_MARGIN_MIL = DEFAULT_SAFETY_MARGIN_MM / MM_PER_MIL
GRID_MIL = 0.0001
ARC_SAGITTA_MIL = 0.001
BUFFER_QUAD_SEGS = 64
DIRECT_TYPES = {"Track", "Via", "Fill Region"}
COPPER_LAYERS = (1, 15, 16, 17, 18, 2)
MINIMUM_TRACK_WIDTH_MM = 0.10199878
CONTACT_TOLERANCE_MIL = 0.003


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeRecord:
    header: dict[str, Any]
    body: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")


@dataclass(frozen=True)
class ClearanceRow:
    global_index: str
    object_pair: str
    object_ids: tuple[str, str]
    object_types: tuple[str, str]
    nets: tuple[str, str]
    layer_ids: tuple[int, ...]
    actual_mil: float
    required_mil: float
    raw: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def atomic_write_json(path: Path, payload: Any) -> None:
    target = path.resolve()
    try:
        target.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise PlanError(f"output must remain below {OUTPUT_ROOT}: {target}") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def finite(value: Any, label: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise PlanError(f"{label} is not finite: {value!r}")
    return result


def parse_native_source(path: Path) -> list[NativeRecord]:
    records: list[NativeRecord] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            header_text, body_text = raw.split("||", 1)
            if body_text.endswith("|"):
                body_text = body_text[:-1]
            header = json.loads(header_text)
            body = json.loads(body_text)
        except Exception as exc:
            raise PlanError(f"invalid native row {path}:{line_number}: {exc}") from exc
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise PlanError(f"native row is not object/object: {path}:{line_number}")
        records.append(NativeRecord(header, body))
    return records


def parse_pad_net_id(record_id: str) -> tuple[str, str, str] | None:
    try:
        value = json.loads(record_id)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list) or len(value) != 4 or value[0] != "PAD_NET":
        return None
    return str(value[1]), str(value[2]), str(value[3])


def checkpoint_documents(path: Path) -> tuple[dict[str, list[NativeRecord]], dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(CHECKPOINT_MEMBER).decode("utf-8-sig")
    documents: dict[str, list[NativeRecord]] = {}
    document_types: dict[str, str] = {}
    current_uuid = ""
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            header_text, body_text = line.split("||", 1)
            if body_text.endswith("|"):
                body_text = body_text[:-1]
            header = json.loads(header_text)
            body = json.loads(body_text)
        except Exception as exc:
            raise PlanError(f"invalid checkpoint row {line_number}: {exc}") from exc
        record = NativeRecord(header, body)
        if record.kind == "DOCHEAD":
            current_uuid = str(body.get("uuid") or "")
            if not current_uuid or current_uuid in documents:
                raise PlanError(f"invalid/duplicate checkpoint document {current_uuid!r}")
            documents[current_uuid] = [record]
            document_types[current_uuid] = str(body.get("docType") or "")
        elif current_uuid:
            documents[current_uuid].append(record)
    return documents, document_types


def component_attributes(records: Sequence[NativeRecord]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for record in records:
        if record.kind != "ATTR":
            continue
        parent = str(record.body.get("parentId") or "")
        key = str(record.body.get("key") or "")
        value = record.body.get("value")
        if value is None:
            value = record.body.get("blockValue")
        if parent and key:
            result[parent][key] = "" if value is None else str(value)
    return result


def rotate_xy(x: float, y: float, angle_degrees: float) -> tuple[float, float]:
    angle = math.radians(angle_degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    return x * cosine - y * sine, x * sine + y * cosine


def transform_local_geometry(value: Any, x: float, y: float, angle_degrees: float) -> Any:
    result = affinity.rotate(value, angle_degrees, origin=(0, 0), use_radians=False)
    return affinity.translate(result, xoff=x, yoff=y)


def parametric_pad_shape(definition: dict[str, Any]) -> Any:
    pad_type = str(definition.get("padType") or "")
    width = finite(definition.get("width"), "pad width")
    height = finite(definition.get("height", width), "pad height")
    if width <= 0 or height <= 0:
        raise PlanError(f"nonpositive pad shape {pad_type} {width} x {height}")
    if pad_type == "ELLIPSE":
        return affinity.scale(
            Point(0, 0).buffer(1.0, quad_segs=BUFFER_QUAD_SEGS),
            xfact=width / 2.0,
            yfact=height / 2.0,
            origin=(0, 0),
        )
    if pad_type == "OVAL":
        return rounded_rectangle(width, height, min(width, height) / 2.0)
    if pad_type == "RECT":
        return rounded_rectangle(width, height, finite(definition.get("radius", 0), "pad radius"))
    raise PlanError(f"unsupported parametric pad type {pad_type!r}")


def pad_definition_for_layer(body: dict[str, Any], layer_id: int) -> dict[str, Any] | None:
    pad_layer = int(body.get("layerId", -1))
    if pad_layer == 12:
        if layer_id in {int(value) for value in (body.get("unusedInnerLayers") or [])}:
            return None
    elif pad_layer != layer_id:
        return None
    special = body.get("specialPad") or []
    if special:
        desired = (1, 1) if layer_id == 1 else (2, 2) if layer_id == 2 else (1, 2)
        match = next(
            (
                row.get("pad")
                for row in special
                if (int(row.get("startLayer", -1)), int(row.get("endLayer", -1))) == desired
            ),
            None,
        )
        if match is not None:
            return dict(match)
    definition = body.get("defaultPad")
    return dict(definition) if isinstance(definition, dict) else None


def pad_copper_geometry(
    pad_body: dict[str, Any], component_body: dict[str, Any], layer_id: int
) -> Any:
    definition = pad_definition_for_layer(pad_body, layer_id)
    if definition is None:
        return GeometryCollection()
    pad_type = str(definition.get("padType") or "")
    component_angle = finite(component_body.get("angle", 0), "component angle")
    component_x = finite(component_body.get("x"), "component x")
    component_y = finite(component_body.get("y"), "component y")
    if pad_type == "POLYGON":
        path = definition.get("path")
        if not isinstance(path, list):
            raise PlanError("POLYGON pad has no path")
        local = normalize_polygonal(Polygon(native_path_points(path)))
        return transform_local_geometry(local, component_x, component_y, component_angle)
    local = parametric_pad_shape(definition)
    pad_angle = finite(pad_body.get("padAngle", 0), "pad angle")
    offset_x = finite(pad_body.get("padOffsetX", 0) or 0, "pad offset x")
    offset_y = finite(pad_body.get("padOffsetY", 0) or 0, "pad offset y")
    rotated_offset = rotate_xy(offset_x, offset_y, pad_angle)
    center_x = finite(pad_body.get("centerX"), "pad centerX") + rotated_offset[0]
    center_y = finite(pad_body.get("centerY"), "pad centerY") + rotated_offset[1]
    local = transform_local_geometry(local, center_x, center_y, pad_angle)
    return transform_local_geometry(local, component_x, component_y, component_angle)


def pad_hole_geometry(pad_body: dict[str, Any], component_body: dict[str, Any]) -> Any:
    hole = pad_body.get("hole")
    if not isinstance(hole, dict):
        return GeometryCollection()
    hole_type = str(hole.get("holeType") or "")
    width = finite(hole.get("width"), "hole width")
    height = finite(hole.get("height", width), "hole height")
    if hole_type == "ROUND":
        local = affinity.scale(
            Point(0, 0).buffer(1.0, quad_segs=BUFFER_QUAD_SEGS),
            xfact=width / 2.0,
            yfact=height / 2.0,
            origin=(0, 0),
        )
    elif hole_type == "SLOT":
        radius = height / 2.0
        half_line = max(0.0, (width - height) / 2.0)
        local = LineString([(-half_line, 0), (half_line, 0)]).buffer(
            radius, cap_style=1, join_style=1, quad_segs=BUFFER_QUAD_SEGS
        )
        local = affinity.rotate(
            local,
            finite(pad_body.get("relativeAngle", 0) or 0, "hole relative angle"),
            origin=(0, 0),
        )
    else:
        raise PlanError(f"unsupported hole type {hole_type!r}")
    center_x = finite(pad_body.get("centerX"), "hole centerX")
    center_y = finite(pad_body.get("centerY"), "hole centerY")
    pad_angle = finite(pad_body.get("padAngle", 0), "pad angle")
    local = transform_local_geometry(local, center_x, center_y, pad_angle)
    return transform_local_geometry(
        local,
        finite(component_body.get("x"), "component x"),
        finite(component_body.get("y"), "component y"),
        finite(component_body.get("angle", 0), "component angle"),
    )


def build_pad_instances(
    records: Sequence[NativeRecord], checkpoint: Path
) -> dict[str, dict[str, Any]]:
    documents, document_types = checkpoint_documents(checkpoint)
    footprints = {
        uuid: rows for uuid, rows in documents.items() if document_types.get(uuid) == "FOOTPRINT"
    }
    components = {record.record_id: record for record in records if record.kind == "COMPONENT"}
    attributes = component_attributes(records)
    footprint_pads: dict[str, dict[str, NativeRecord]] = {}
    for uuid, rows in footprints.items():
        footprint_pads[uuid] = {
            record.record_id: record for record in rows if record.kind == "PAD"
        }
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.kind != "PAD_NET":
            continue
        identity = parse_pad_net_id(record.record_id)
        if identity is None:
            raise PlanError(f"invalid PAD_NET id {record.record_id!r}")
        component_id, number, local_id = identity
        component = components.get(component_id)
        if component is None:
            raise PlanError(f"PAD_NET component absent: {record.record_id}")
        footprint_uuid = attributes.get(component_id, {}).get("Footprint", "")
        pad = footprint_pads.get(footprint_uuid, {}).get(local_id)
        if pad is None:
            raise PlanError(f"PAD_NET footprint child absent: {record.record_id}")
        if str(pad.body.get("num") or "") != number:
            raise PlanError(f"PAD number mismatch: {record.record_id}")
        object_id = component_id + local_id
        if object_id in result:
            raise PlanError(f"duplicate composite PAD id {object_id}")
        result[object_id] = {
            "object_id": object_id,
            "component_id": component_id,
            "reference": attributes.get(component_id, {}).get("Designator", ""),
            "footprint_uuid": footprint_uuid,
            "number": number,
            "local_id": local_id,
            "net_name": str(record.body.get("padNet") or ""),
            "pad_body": pad.body,
            "component_body": component.body,
        }
    return result


def iter_drc_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield value
            return
        if "list" in value:
            yield from iter_drc_items(value["list"])
    elif isinstance(value, list):
        for child in value:
            yield from iter_drc_items(child)


def net_from_suffix(value: Any) -> str:
    text = str(value or "")
    if not text.startswith("(") or ")" not in text:
        return ""
    return text[1:text.index(")")]


def read_clearance_rows(path: Path) -> tuple[dict[str, Any], list[ClearanceRow]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows: list[ClearanceRow] = []
    for item in iter_drc_items(payload.get("details", [])):
        if item.get("errorType") != "Clearance Error":
            continue
        err = item["explanation"]["errData"]
        rows.append(
            ClearanceRow(
                global_index=str(err.get("globalIndex") or item.get("globalIndex") or ""),
                object_pair=str(item.get("errorObjType") or ""),
                object_ids=(str(err.get("obj1") or ""), str(err.get("obj2") or "")),
                object_types=(str(err.get("obj1Type") or ""), str(err.get("obj2Type") or "")),
                nets=(net_from_suffix(err.get("obj1Suffix")), net_from_suffix(err.get("obj2Suffix"))),
                layer_ids=tuple(int(value) for value in (err.get("layerIds") or [])),
                actual_mil=finite(err.get("minDistance"), "minDistance") * DISPLAY_MIL_PER_RAW_UNIT,
                required_mil=finite(err.get("clearance"), "clearance") * DISPLAY_MIL_PER_RAW_UNIT,
                raw=item,
            )
        )
    return payload, rows


def clean_number(value: float, digits: int = 4) -> int | float:
    result = round(float(value), digits)
    if abs(result) < 0.5 * 10 ** (-digits):
        return 0
    return int(result) if result.is_integer() else result


def signed_ring_area(points: Sequence[tuple[float, float]]) -> float:
    return sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, points[1:])
    ) / 2.0


def arc_points(
    start: tuple[float, float],
    end: tuple[float, float],
    sweep_degrees: float,
) -> list[tuple[float, float]]:
    theta = math.radians(sweep_degrees)
    chord_x = end[0] - start[0]
    chord_y = end[1] - start[1]
    chord = math.hypot(chord_x, chord_y)
    if chord <= 1e-12 or abs(theta) <= 1e-12:
        return [end]
    sine = math.sin(abs(theta) / 2.0)
    if abs(sine) <= 1e-14:
        return [end]
    radius = chord / (2.0 * sine)
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    tangent = math.tan(theta / 2.0)
    offset = 0.0 if abs(tangent) <= 1e-14 else chord / (2.0 * tangent)
    left_x, left_y = -chord_y / chord, chord_x / chord
    center = (midpoint[0] + left_x * offset, midpoint[1] + left_y * offset)
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    if radius <= ARC_SAGITTA_MIL:
        segments = max(2, math.ceil(abs(sweep_degrees) / 5.0))
    else:
        maximum_angle = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - ARC_SAGITTA_MIL / radius)))
        segments = max(2, math.ceil(abs(theta) / max(maximum_angle, math.radians(0.25))))
    return [
        (
            center[0] + radius * math.cos(start_angle + theta * step / segments),
            center[1] + radius * math.sin(start_angle + theta * step / segments),
        )
        for step in range(1, segments + 1)
    ]


def native_path_points(path: Sequence[Any]) -> list[tuple[float, float]]:
    if len(path) < 3 or not isinstance(path[0], (int, float)) or not isinstance(path[1], (int, float)):
        raise PlanError(f"unsupported polygon path head: {path[:4]!r}")
    points = [(finite(path[0], "path x"), finite(path[1], "path y"))]
    index = 2
    line_mode = False
    while index < len(path):
        token = path[index]
        if token == "L":
            line_mode = True
            index += 1
            if index + 1 >= len(path):
                raise PlanError("truncated L path")
            points.append((finite(path[index], "L x"), finite(path[index + 1], "L y")))
            index += 2
        elif token in {"ARC", "CARC"}:
            line_mode = False
            if index + 3 >= len(path):
                raise PlanError("truncated ARC path")
            sweep = finite(path[index + 1], "ARC sweep")
            endpoint = (finite(path[index + 2], "ARC x"), finite(path[index + 3], "ARC y"))
            points.extend(arc_points(points[-1], endpoint, sweep))
            index += 4
        elif isinstance(token, (int, float)) and line_mode:
            if index + 1 >= len(path):
                raise PlanError("truncated compact L path")
            points.append((finite(token, "compact L x"), finite(path[index + 1], "compact L y")))
            index += 2
        else:
            raise PlanError(f"unsupported polygon token {token!r} at index {index}")
    if points[0] != points[-1]:
        points.append(points[0])
    return points


def polygon_parts(value: Any) -> list[Polygon]:
    if value is None or value.is_empty:
        return []
    if isinstance(value, Polygon):
        return [value]
    if isinstance(value, MultiPolygon):
        return list(value.geoms)
    if isinstance(value, GeometryCollection) or hasattr(value, "geoms"):
        result: list[Polygon] = []
        for child in value.geoms:
            result.extend(polygon_parts(child))
        return result
    return []


def normalize_polygonal(value: Any) -> Any:
    parts = polygon_parts(make_valid(value))
    if not parts:
        return GeometryCollection()
    return unary_union(parts)


def fill_path_geometry(body: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    paths = body.get("path")
    if not isinstance(paths, list) or not paths:
        raise PlanError("FILL has no path")
    geometry: Any = GeometryCollection()
    diagnostics: list[dict[str, Any]] = []
    for path_index, path in enumerate(paths):
        if not isinstance(path, list):
            raise PlanError("FILL path is not an array")
        if path and path[0] in {"CIRCLE", "C"}:
            candidate = Point(finite(path[1], "circle x"), finite(path[2], "circle y")).buffer(
                finite(path[3], "circle radius"), quad_segs=BUFFER_QUAD_SEGS
            )
            validity = "Valid Geometry"
        elif path and path[0] == "R":
            candidate = rounded_rectangle(
                finite(path[3], "rect width"),
                finite(path[4], "rect height"),
                finite(path[6], "rect radius"),
            )
            candidate = affinity.rotate(candidate, finite(path[5], "rect angle"), origin=(0, 0))
            candidate = affinity.translate(candidate, finite(path[1], "rect x"), finite(path[2], "rect y"))
            validity = "Valid Geometry"
        else:
            points = native_path_points(path)
            raw_polygon = Polygon(points)
            validity = explain_validity(raw_polygon)
            candidate = normalize_polygonal(raw_polygon)
        if candidate.is_empty:
            raise PlanError(f"FILL contour {path_index} has no polygonal area")
        geometry = candidate if geometry.is_empty else geometry.symmetric_difference(candidate)
        diagnostics.append({
            "index": path_index,
            "validity": validity,
            "polygonal_area_mil2": candidate.area,
        })
    return normalize_polygonal(geometry), diagnostics


def rounded_rectangle(width: float, height: float, radius: float) -> Any:
    width = finite(width, "width")
    height = finite(height, "height")
    radius = max(0.0, min(finite(radius, "radius"), min(width, height) / 2.0))
    if width <= 0 or height <= 0:
        raise PlanError(f"nonpositive rectangle {width} x {height}")
    if radius <= 0:
        return box(-width / 2.0, -height / 2.0, width / 2.0, height / 2.0)
    if width >= height:
        core = LineString([(-width / 2.0 + radius, 0), (width / 2.0 - radius, 0)])
    else:
        core = LineString([(0, -height / 2.0 + radius), (0, height / 2.0 - radius)])
    return core.buffer(radius, cap_style=1, join_style=1, quad_segs=BUFFER_QUAD_SEGS)


def direct_object_geometry(record: NativeRecord) -> Any:
    body = record.body
    if record.kind == "LINE":
        centerline = LineString([
            (finite(body.get("startX"), "line startX"), finite(body.get("startY"), "line startY")),
            (finite(body.get("endX"), "line endX"), finite(body.get("endY"), "line endY")),
        ])
        return centerline.buffer(
            finite(body.get("width"), "line width") / 2.0,
            cap_style=1,
            join_style=1,
            quad_segs=BUFFER_QUAD_SEGS,
        )
    if record.kind == "ARC":
        start = (finite(body.get("startX"), "arc startX"), finite(body.get("startY"), "arc startY"))
        end = (finite(body.get("endX"), "arc endX"), finite(body.get("endY"), "arc endY"))
        points = [start, *arc_points(start, end, finite(body.get("angle"), "arc angle"))]
        return LineString(points).buffer(
            finite(body.get("width"), "arc width") / 2.0,
            cap_style=1,
            join_style=1,
            quad_segs=BUFFER_QUAD_SEGS,
        )
    if record.kind == "VIA":
        return Point(
            finite(body.get("centerX"), "via centerX"),
            finite(body.get("centerY"), "via centerY"),
        ).buffer(finite(body.get("viaDiameter"), "via diameter") / 2.0, quad_segs=BUFFER_QUAD_SEGS)
    if record.kind == "FILL":
        return fill_path_geometry(body)[0]
    raise PlanError(f"no direct geometry for {record.kind}:{record.record_id}")


def via_present_on_layer(body: dict[str, Any], layer_id: int) -> bool:
    return layer_id in COPPER_LAYERS and layer_id not in {
        int(value) for value in (body.get("unusedInnerLayers") or [])
    }


def opponent_geometry(
    object_id: str,
    object_type: str,
    layer_id: int,
    records_by_id: dict[str, NativeRecord],
    pads_by_id: dict[str, dict[str, Any]],
) -> tuple[Any, dict[str, Any]]:
    record = records_by_id.get(object_id)
    if object_type in {"Track", "Via", "Fill Region"}:
        if record is None:
            raise PlanError(f"missing native opponent {object_type}:{object_id}")
        if object_type == "Track" and record.kind not in {"LINE", "ARC"}:
            raise PlanError(f"Track {object_id} resolves to {record.kind}")
        if object_type == "Via" and record.kind != "VIA":
            raise PlanError(f"Via {object_id} resolves to {record.kind}")
        if object_type == "Fill Region" and record.kind != "FILL":
            raise PlanError(f"Fill Region {object_id} resolves to {record.kind}")
        geometry = direct_object_geometry(record)
        if record.kind in {"LINE", "ARC", "FILL"} and int(record.body.get("layerId", -1)) != layer_id:
            raise PlanError(f"{record.kind} {object_id} is not on DRC layer {layer_id}")
        if record.kind == "VIA" and not via_present_on_layer(record.body, layer_id):
            raise PlanError(f"VIA {object_id} is hidden on DRC layer {layer_id}")
        return geometry, {
            "id": object_id,
            "kind": record.kind,
            "net_name": str(record.body.get("netName") or ""),
            "layer_id": record.body.get("layerId"),
        }
    pad = pads_by_id.get(object_id)
    if pad is None:
        raise PlanError(f"missing PAD opponent {object_type}:{object_id}")
    if object_type == "Hole":
        geometry = pad_hole_geometry(pad["pad_body"], pad["component_body"])
    elif object_type in {"SMD Pad", "TH Pad"}:
        geometry = pad_copper_geometry(pad["pad_body"], pad["component_body"], layer_id)
    else:
        raise PlanError(f"unsupported opponent type {object_type!r}")
    if geometry.is_empty:
        raise PlanError(f"PAD opponent {object_id} has no {object_type} geometry on layer {layer_id}")
    return geometry, {
        "id": object_id,
        "kind": "PAD_HOLE" if object_type == "Hole" else "PAD",
        "net_name": pad["net_name"],
        "reference": pad["reference"],
        "number": pad["number"],
        "local_id": pad["local_id"],
        "footprint_uuid": pad["footprint_uuid"],
        "layer_id": layer_id,
    }


def geometry_to_paths(value: Any) -> list[list[Any]]:
    geometry = orient_polygons(normalize_polygonal(value), exterior_cw=True)
    paths: list[list[Any]] = []
    for polygon in sorted(
        polygon_parts(geometry),
        key=lambda item: (-item.area, item.bounds),
    ):
        rings = [polygon.exterior, *polygon.interiors]
        for ring in rings:
            # Six decimals keeps the boolean result a strict practical subset
            # without materially inflating the public-API payload.  The native
            # source already contains six-decimal mil coordinates elsewhere.
            points = [(clean_number(x, 6), clean_number(y, 6)) for x, y in ring.coords]
            deduplicated: list[tuple[int | float, int | float]] = []
            for point in points:
                if not deduplicated or point != deduplicated[-1]:
                    deduplicated.append(point)
            if deduplicated[0] != deduplicated[-1]:
                deduplicated.append(deduplicated[0])
            if len(deduplicated) < 4 or abs(signed_ring_area([(float(x), float(y)) for x, y in deduplicated])) < 1e-8:
                raise PlanError("candidate produced a degenerate contour")
            path: list[Any] = [deduplicated[0][0], deduplicated[0][1], "L"]
            for x, y in deduplicated[1:]:
                path.extend((x, y))
            paths.append(path)
    if not paths:
        raise PlanError("candidate has no contours")
    return paths


def path_geometry_from_output(paths: Sequence[Sequence[Any]]) -> Any:
    return fill_path_geometry({"path": list(paths)})[0]


def row_for_fill(row: ClearanceRow, fill_id: str) -> tuple[str, str]:
    matches = [
        (object_id, object_type)
        for object_id, object_type in zip(row.object_ids, row.object_types)
        if object_id != fill_id
    ]
    if len(matches) != 1:
        raise PlanError(f"cannot identify one opponent for {fill_id}: {row.object_ids}")
    return matches[0]


def build_direct_fill_change(
    fill_id: str,
    rows: Sequence[ClearanceRow],
    records_by_id: dict[str, NativeRecord],
    safety_margin_mil: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    fill = records_by_id.get(fill_id)
    if fill is None or fill.kind != "FILL":
        raise PlanError(f"missing FILL {fill_id}")
    original, source_path_diagnostics = fill_path_geometry(fill.body)
    keepouts: list[Any] = []
    row_diagnostics: list[dict[str, Any]] = []
    for row in rows:
        opponent_id, opponent_type = row_for_fill(row, fill_id)
        if opponent_type not in {"Track", "Via"}:
            raise PlanError(f"pilot supports only Track/Via opponents, got {opponent_type}")
        opponent = records_by_id.get(opponent_id)
        if opponent is None:
            raise PlanError(f"missing opponent {opponent_type}:{opponent_id}")
        opponent_geometry = direct_object_geometry(opponent)
        reconstructed_mil = original.distance(opponent_geometry)
        fill_half_width_mil = finite(fill.body.get("width", 0), "fill width") / 2.0
        expansion_mil = row.required_mil + fill_half_width_mil + safety_margin_mil
        keepout = opponent_geometry.buffer(
            expansion_mil,
            cap_style=1,
            join_style=1,
            quad_segs=BUFFER_QUAD_SEGS,
        )
        keepouts.append(keepout)
        row_diagnostics.append({
            "error_id": row.global_index,
            "object_pair": row.object_pair,
            "opponent_id": opponent_id,
            "opponent_type": opponent_type,
            "actual_native_drc_mil": row.actual_mil,
            "reconstructed_original_mil": reconstructed_mil,
            "distance_reconstruction_error_mil": reconstructed_mil - row.actual_mil,
            "required_mil": row.required_mil,
            "fill_half_width_mil": fill_half_width_mil,
            "safety_margin_mil": safety_margin_mil,
            "keepout_expansion_from_opponent_copper_mil": expansion_mil,
        })
    removal = original.intersection(unary_union(keepouts))
    candidate = normalize_polygonal(original.difference(unary_union(keepouts)))
    if candidate.is_empty:
        raise PlanError(f"candidate deletes FILL {fill_id}")
    candidate_paths = geometry_to_paths(candidate)
    decoded_candidate = path_geometry_from_output(candidate_paths)
    predicted_rows: list[dict[str, Any]] = []
    for row in rows:
        opponent_id, opponent_type = row_for_fill(row, fill_id)
        opponent_geometry = direct_object_geometry(records_by_id[opponent_id])
        predicted_rows.append({
            "error_id": row.global_index,
            "opponent_id": opponent_id,
            "opponent_type": opponent_type,
            "required_mil": row.required_mil,
            "predicted_candidate_clearance_mil": decoded_candidate.distance(opponent_geometry),
        })
    before = json.loads(json.dumps(fill.body))
    after = json.loads(json.dumps(fill.body))
    after["path"] = candidate_paths
    before_without_path = dict(before)
    after_without_path = dict(after)
    before_without_path.pop("path", None)
    after_without_path.pop("path", None)
    if canonical(before_without_path) != canonical(after_without_path):
        raise AssertionError("non-path FILL data changed")
    change = {"id": fill_id, "type": "FILL", "before": before, "after": after}
    report = {
        "id": fill_id,
        "layer_id": fill.body.get("layerId"),
        "net_name": fill.body.get("netName"),
        "source_path_diagnostics": source_path_diagnostics,
        "clearance_rows": row_diagnostics,
        "predicted_rows": predicted_rows,
        "original_area_mil2": original.area,
        "removed_area_mil2": removal.area,
        "candidate_area_mil2": decoded_candidate.area,
        "area_removed_fraction": removal.area / original.area,
        "original_polygon_count": len(polygon_parts(original)),
        "candidate_polygon_count": len(polygon_parts(decoded_candidate)),
        "candidate_contour_count": len(candidate_paths),
        "candidate_minimum_clearance_mil": decoded_candidate.minimum_clearance,
        "candidate_valid": decoded_candidate.is_valid,
        "only_path_changed": True,
    }
    return change, report


def build_fill_candidate(
    fill_id: str,
    rows: Sequence[ClearanceRow],
    records_by_id: dict[str, NativeRecord],
    pads_by_id: dict[str, dict[str, Any]],
    safety_margin_mil: float,
    geometry_cache: dict[tuple[str, str, int], Any],
) -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    fill = records_by_id.get(fill_id)
    if fill is None or fill.kind != "FILL":
        raise PlanError(f"missing FILL {fill_id}")
    layer_id = int(fill.body.get("layerId", -1))
    if layer_id not in COPPER_LAYERS:
        raise PlanError(f"target FILL {fill_id} is not copper: layer {layer_id}")
    original, source_path_diagnostics = fill_path_geometry(fill.body)
    fill_half_width_mil = finite(fill.body.get("width", 0), "fill width") / 2.0
    keepouts: list[Any] = []
    row_diagnostics: list[dict[str, Any]] = []
    for row in rows:
        if layer_id not in row.layer_ids:
            raise PlanError(f"{row.global_index}: DRC layer does not match FILL {fill_id}")
        opponent_id, opponent_type = row_for_fill(row, fill_id)
        key = (opponent_id, opponent_type, layer_id)
        if key not in geometry_cache:
            geometry_cache[key] = opponent_geometry(
                opponent_id, opponent_type, layer_id, records_by_id, pads_by_id
            )[0]
        opponent = geometry_cache[key]
        descriptor = opponent_geometry(
            opponent_id, opponent_type, layer_id, records_by_id, pads_by_id
        )[1]
        reconstructed_mil = original.distance(opponent)
        opponent_fill_half_width_mil = 0.0
        if opponent_type == "Fill Region":
            opponent_fill_half_width_mil = finite(
                records_by_id[opponent_id].body.get("width", 0), "opponent fill width"
            ) / 2.0
        expansion_mil = (
            row.required_mil
            + fill_half_width_mil
            + opponent_fill_half_width_mil
            + safety_margin_mil
        )
        keepouts.append(
            opponent.buffer(
                expansion_mil,
                cap_style=1,
                join_style=1,
                quad_segs=BUFFER_QUAD_SEGS,
            )
        )
        row_diagnostics.append({
            "error_id": row.global_index,
            "object_pair": row.object_pair,
            "opponent": descriptor,
            "actual_native_drc_mil": row.actual_mil,
            "reconstructed_original_mil": reconstructed_mil,
            "distance_reconstruction_error_mil": reconstructed_mil - row.actual_mil,
            "required_mil": row.required_mil,
            "target_fill_half_width_mil": fill_half_width_mil,
            "opponent_fill_half_width_mil": opponent_fill_half_width_mil,
            "safety_margin_mil": safety_margin_mil,
            "keepout_expansion_from_opponent_geometry_mil": expansion_mil,
        })
    combined_keepout = unary_union(keepouts)
    removal = original.intersection(combined_keepout)
    candidate = normalize_polygonal(original.difference(combined_keepout))
    if candidate.is_empty:
        raise PlanError(f"candidate deletes FILL {fill_id}")
    candidate_paths = geometry_to_paths(candidate)
    decoded_candidate = path_geometry_from_output(candidate_paths)
    added_area = decoded_candidate.difference(original).area
    if added_area > max(0.02, original.area * 1e-8):
        raise PlanError(f"serialized candidate adds {added_area} mil^2 to FILL {fill_id}")
    predicted_rows: list[dict[str, Any]] = []
    for row in rows:
        opponent_id, opponent_type = row_for_fill(row, fill_id)
        opponent = geometry_cache[(opponent_id, opponent_type, layer_id)]
        predicted = decoded_candidate.distance(opponent)
        predicted_rows.append({
            "error_id": row.global_index,
            "opponent_id": opponent_id,
            "opponent_type": opponent_type,
            "required_mil": row.required_mil,
            "predicted_candidate_clearance_mil": predicted,
            "predicted_rule_surplus_mil": predicted - row.required_mil,
        })
        minimum_expected = row.required_mil + fill_half_width_mil + safety_margin_mil - 0.01
        if opponent_type == "Fill Region":
            minimum_expected += finite(
                records_by_id[opponent_id].body.get("width", 0), "opponent fill width"
            ) / 2.0
        if predicted + 1e-9 < minimum_expected:
            raise PlanError(
                f"{fill_id}/{row.global_index}: predicted {predicted} < {minimum_expected} mil"
            )
    before = copy.deepcopy(fill.body)
    after = copy.deepcopy(fill.body)
    after["path"] = candidate_paths
    before_without_path = dict(before)
    after_without_path = dict(after)
    before_without_path.pop("path", None)
    after_without_path.pop("path", None)
    if canonical(before_without_path) != canonical(after_without_path):
        raise AssertionError("non-path FILL data changed")
    minimum_width_mil = MINIMUM_TRACK_WIDTH_MM / MM_PER_MIL
    original_eroded = normalize_polygonal(original.buffer(-minimum_width_mil / 2.0))
    candidate_eroded = normalize_polygonal(decoded_candidate.buffer(-minimum_width_mil / 2.0))
    change = {"id": fill_id, "type": "FILL", "before": before, "after": after}
    report = {
        "id": fill_id,
        "layer_id": layer_id,
        "net_name": str(fill.body.get("netName") or ""),
        "source_path_diagnostics": source_path_diagnostics,
        "clearance_rows": row_diagnostics,
        "predicted_rows": predicted_rows,
        "original_area_mil2": original.area,
        "removed_area_mil2": removal.area,
        "candidate_area_mil2": decoded_candidate.area,
        "serialized_added_area_mil2": added_area,
        "area_removed_fraction": removal.area / original.area,
        "original_polygon_count": len(polygon_parts(original)),
        "candidate_polygon_count": len(polygon_parts(decoded_candidate)),
        "candidate_contour_count": len(candidate_paths),
        "original_eroded_half_min_track_area_mil2": original_eroded.area,
        "candidate_eroded_half_min_track_area_mil2": candidate_eroded.area,
        "candidate_minimum_clearance_mil": decoded_candidate.minimum_clearance,
        "candidate_valid": decoded_candidate.is_valid,
        "only_path_changed": True,
    }
    return change, report, original, decoded_candidate


def build_copper_objects(
    records: Sequence[NativeRecord],
    pads_by_id: dict[str, dict[str, Any]],
    replacements: dict[str, Any],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    result: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        net_name = str(record.body.get("netName") or "")
        if not net_name:
            continue
        if record.kind in {"LINE", "ARC", "FILL"}:
            layer_id = int(record.body.get("layerId", -1))
            if layer_id not in COPPER_LAYERS:
                continue
            geometry = replacements.get(record.record_id)
            if geometry is None:
                geometry = direct_object_geometry(record)
            result[(layer_id, net_name)].append({
                "id": record.record_id,
                "kind": record.kind,
                "geometry": geometry,
            })
        elif record.kind == "VIA":
            geometry = direct_object_geometry(record)
            for layer_id in COPPER_LAYERS:
                if via_present_on_layer(record.body, layer_id):
                    result[(layer_id, net_name)].append({
                        "id": record.record_id,
                        "kind": record.kind,
                        "geometry": geometry,
                    })
    for object_id, pad in pads_by_id.items():
        net_name = str(pad["net_name"] or "")
        if not net_name:
            continue
        for layer_id in COPPER_LAYERS:
            geometry = pad_copper_geometry(pad["pad_body"], pad["component_body"], layer_id)
            if geometry.is_empty:
                continue
            result[(layer_id, net_name)].append({
                "id": object_id,
                "kind": "PAD",
                "geometry": geometry,
                "reference": pad["reference"],
                "number": pad["number"],
            })
    return result


def contact_ids(
    geometry: Any, own_id: str, objects: Sequence[dict[str, Any]]
) -> set[str]:
    if not objects:
        return set()
    geometries = [item["geometry"] for item in objects]
    tree = STRtree(geometries)
    result: set[str] = set()
    for index in tree.query(geometry.buffer(CONTACT_TOLERANCE_MIL)):
        item = objects[int(index)]
        if item["id"] == own_id:
            continue
        if geometry.distance(item["geometry"]) <= CONTACT_TOLERANCE_MIL:
            result.add(str(item["id"]))
    return result


def connectivity_audit(
    records: Sequence[NativeRecord],
    pads_by_id: dict[str, dict[str, Any]],
    original_geometries: dict[str, Any],
    candidate_geometries: dict[str, Any],
    reports_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    baseline = build_copper_objects(records, pads_by_id, {})
    final = build_copper_objects(records, pads_by_id, candidate_geometries)
    lost_contact_rows: list[dict[str, Any]] = []
    unanchored_components: list[dict[str, Any]] = []
    for fill_id, candidate in candidate_geometries.items():
        detail = reports_by_id[fill_id]
        key = (int(detail["layer_id"]), str(detail["net_name"]))
        before_contacts = contact_ids(original_geometries[fill_id], fill_id, baseline.get(key, []))
        after_contacts = contact_ids(candidate, fill_id, final.get(key, []))
        lost = sorted(before_contacts - after_contacts)
        if lost:
            lost_contact_rows.append({
                "fill_id": fill_id,
                "lost_same_net_object_ids": lost,
                "before_contact_count": len(before_contacts),
                "after_contact_count": len(after_contacts),
            })
        components = polygon_parts(candidate)
        component_contacts = []
        for index, component in enumerate(components):
            contacts = sorted(contact_ids(component, fill_id, final.get(key, [])))
            component_contacts.append({"component_index": index, "same_net_contacts": contacts})
            if not contacts:
                unanchored_components.append({
                    "fill_id": fill_id,
                    "component_index": index,
                    "area_mil2": component.area,
                })
        detail["same_net_connectivity"] = {
            "before_contact_ids": sorted(before_contacts),
            "after_contact_ids": sorted(after_contacts),
            "lost_contact_ids": lost,
            "candidate_components": component_contacts,
        }
    return {
        "changed_fill_count": len(candidate_geometries),
        "lost_same_net_contact_rows": lost_contact_rows,
        "unanchored_candidate_components": unanchored_components,
        "all_original_same_net_contacts_preserved": not lost_contact_rows,
        "all_candidate_components_have_same_net_anchor": not unanchored_components,
    }


def build_pilot(
    source: Path,
    drc: Path,
    fill_id: str,
    safety_margin_mm: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = parse_native_source(source)
    records_by_id = {record.record_id: record for record in records if record.record_id}
    if len(records_by_id) != sum(bool(record.record_id) for record in records):
        raise PlanError("duplicate native record IDs")
    docheads = [record for record in records if record.kind == "DOCHEAD"]
    if len(docheads) != 1 or docheads[0].body.get("uuid") != EXPECTED_PCB_UUID:
        raise PlanError("unexpected PCB source identity")
    counts = Counter(record.kind for record in records)
    if counts["FILL"] != EXPECTED_FILL_COUNT or counts["RULE"] != EXPECTED_RULE_COUNT:
        raise PlanError(f"protected native inventory changed: {counts}")
    _, clearance_rows = read_clearance_rows(drc)
    if len(clearance_rows) != EXPECTED_CLEARANCE_ERRORS:
        raise PlanError(f"clearance DRC count changed: {len(clearance_rows)}")
    fill_rows = [
        row
        for row in clearance_rows
        if fill_id in row.object_ids and "Fill Region" in row.object_types
    ]
    if not fill_rows:
        raise PlanError(f"FILL {fill_id} has no clearance rows")
    change, detail = build_direct_fill_change(
        fill_id,
        fill_rows,
        records_by_id,
        finite(safety_margin_mm, "safety margin") / MM_PER_MIL,
    )
    max_reconstruction_error = max(
        abs(row["distance_reconstruction_error_mil"])
        for row in detail["clearance_rows"]
    )
    minimum_surplus = min(
        row["predicted_candidate_clearance_mil"] - row["required_mil"]
        for row in detail["predicted_rows"]
    )
    if max_reconstruction_error > 0.01:
        raise PlanError(f"pilot geometry does not reproduce native DRC: {max_reconstruction_error} mil")
    if minimum_surplus < 0.15:
        raise PlanError(f"pilot margin too small after 0.0001 mil serialization: {minimum_surplus} mil")
    plan = {
        "schema": "stm32h747-multilayer-fill-clearance-plan-v1",
        "pcbUuid": EXPECTED_PCB_UUID,
        "manufacturingApproved": False,
        "scope": "one existing FILL path only; rules/components/nets/routes/pads/vias/holes immutable",
        "inputs": {
            "source": {"path": str(source.resolve()), "sha256": sha256_file(source)},
            "drc": {"path": str(drc.resolve()), "sha256": sha256_file(drc)},
        },
        "rules": {
            "action": "preserve selected JLCPCB Capability (Multiple Layers Board) rules unchanged",
            "safety_margin_mm": safety_margin_mm,
            "fill_half_line_width_included": True,
        },
        "changes": [change],
    }
    report = {
        "schema": "stm32h747-multilayer-fill-clearance-report-v1",
        "status": "offline-pilot-candidate-ready-for-guarded-public-api-test",
        "readOnlyAnalysis": True,
        "manufacturingApproved": False,
        "plan": {"path": str(DEFAULT_PILOT_PLAN.resolve())},
        "checks": {
            "native_distance_reconstruction_max_error_mil": max_reconstruction_error,
            "predicted_minimum_rule_surplus_mil": minimum_surplus,
            "only_fill_path_changes": True,
            "selected_rules_unchanged_by_plan": True,
            "candidate_nonempty": True,
        },
        "fill": detail,
        "requiredPostApply": [
            "read back the full native document source because the public FILL getter exposes only path[0]",
            "prove all non-target records and all 18 RULE rows are unchanged",
            "save/reopen and verify every contour survives",
            "rerun native DRC and connectivity checks before expanding the batch",
        ],
    }
    return plan, report


def build_remaining_plan(
    source: Path,
    drc: Path,
    checkpoint: Path,
    safety_margin_mm: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = parse_native_source(source)
    records_by_id = {record.record_id: record for record in records if record.record_id}
    if len(records_by_id) != sum(bool(record.record_id) for record in records):
        raise PlanError("duplicate native record IDs")
    docheads = [record for record in records if record.kind == "DOCHEAD"]
    if len(docheads) != 1 or docheads[0].body.get("uuid") != EXPECTED_PCB_UUID:
        raise PlanError("unexpected PCB source identity")
    counts = Counter(record.kind for record in records)
    if counts["FILL"] != EXPECTED_FILL_COUNT or counts["RULE"] != EXPECTED_RULE_COUNT:
        raise PlanError(f"protected native inventory changed: {counts}")
    drc_payload, clearance_rows = read_clearance_rows(drc)
    fill_rows = [row for row in clearance_rows if "Fill Region" in row.object_types]
    if not fill_rows:
        raise PlanError("current DRC has no FILL clearance rows")
    pads_by_id = build_pad_instances(records, checkpoint)
    if len(pads_by_id) != counts["PAD_NET"]:
        raise PlanError(f"PAD/PAD_NET join incomplete: {len(pads_by_id)} != {counts['PAD_NET']}")

    rows_by_fill: dict[str, list[ClearanceRow]] = defaultdict(list)
    protected_rows: list[dict[str, Any]] = []
    excluded_pilot_rows: list[str] = []
    for row in fill_rows:
        fill_ids = [
            object_id
            for object_id, object_type in zip(row.object_ids, row.object_types)
            if object_type == "Fill Region"
        ]
        if not fill_ids:
            raise AssertionError("FILL row has no FILL object")
        candidates = [value for value in fill_ids if value not in PROTECTED_FILL_IDS]
        if not candidates:
            protected_rows.append({"error_id": row.global_index, "fill_ids": fill_ids})
            continue
        # Only the GND region moves in the one Fill-to-Fill conflict.  The D13
        # analytic capsule is a protected source reconstruction primitive.
        target = candidates[0]
        if target == PILOT_FILL_ID:
            excluded_pilot_rows.append(row.global_index)
            continue
        rows_by_fill[target].append(row)

    target_ids = sorted(rows_by_fill)
    if PILOT_FILL_ID in target_ids or PROTECTED_FILL_IDS.intersection(target_ids):
        raise AssertionError("pilot/protected FILL entered the remaining plan")
    expected_unique_fill_ids = {
        object_id
        for row in fill_rows
        for object_id, object_type in zip(row.object_ids, row.object_types)
        if object_type == "Fill Region"
    }
    excluded_ids_present = expected_unique_fill_ids.intersection(
        {PILOT_FILL_ID} | set(PROTECTED_FILL_IDS)
    )
    if expected_unique_fill_ids != set(target_ids) | excluded_ids_present:
        raise PlanError("remaining FILL target partition is incomplete")

    safety_margin_mil = finite(safety_margin_mm, "safety margin") / MM_PER_MIL
    geometry_cache: dict[tuple[str, str, int], Any] = {}
    changes: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    original_geometries: dict[str, Any] = {}
    candidate_geometries: dict[str, Any] = {}
    for index, fill_id in enumerate(target_ids, 1):
        change, detail, original, candidate = build_fill_candidate(
            fill_id,
            rows_by_fill[fill_id],
            records_by_id,
            pads_by_id,
            safety_margin_mil,
            geometry_cache,
        )
        detail["sequence"] = index
        changes.append(change)
        details.append(detail)
        original_geometries[fill_id] = original
        candidate_geometries[fill_id] = candidate

    reports_by_id = {row["id"]: row for row in details}
    connectivity = connectivity_audit(
        records,
        pads_by_id,
        original_geometries,
        candidate_geometries,
        reports_by_id,
    )
    # Clearance cutouts can isolate a very small copper fragment from the rest
    # of a pour.  Such a fragment has neither a same-net route nor a pad/via
    # anchor and would become a native Connection Error.  Remove only those
    # newly isolated polygon components, record them explicitly, and rerun the
    # simultaneous final-state contact audit.
    if connectivity["unanchored_candidate_components"]:
        pruned_by_fill: dict[str, set[int]] = defaultdict(set)
        for row in connectivity["unanchored_candidate_components"]:
            pruned_by_fill[str(row["fill_id"])].add(int(row["component_index"]))
        change_by_id = {row["id"]: row for row in changes}
        minimum_width_mil = MINIMUM_TRACK_WIDTH_MM / MM_PER_MIL
        for fill_id, indexes in pruned_by_fill.items():
            old_candidate = candidate_geometries[fill_id]
            parts = polygon_parts(old_candidate)
            kept = [part for index, part in enumerate(parts) if index not in indexes]
            if not kept:
                raise PlanError(f"unanchored pruning would delete FILL {fill_id}")
            candidate = normalize_polygonal(unary_union(kept))
            paths = geometry_to_paths(candidate)
            candidate = path_geometry_from_output(paths)
            candidate_geometries[fill_id] = candidate
            change_by_id[fill_id]["after"]["path"] = paths
            detail = reports_by_id[fill_id]
            original = original_geometries[fill_id]
            detail["pruned_unanchored_components"] = [
                {
                    "component_index": index,
                    "area_mil2": parts[index].area,
                }
                for index in sorted(indexes)
            ]
            detail["candidate_area_mil2"] = candidate.area
            detail["removed_area_mil2"] = original.difference(candidate).area
            detail["area_removed_fraction"] = detail["removed_area_mil2"] / original.area
            detail["candidate_polygon_count"] = len(polygon_parts(candidate))
            detail["candidate_contour_count"] = len(paths)
            detail["candidate_minimum_clearance_mil"] = candidate.minimum_clearance
            detail["candidate_eroded_half_min_track_area_mil2"] = normalize_polygonal(
                candidate.buffer(-minimum_width_mil / 2.0)
            ).area
            detail["serialized_added_area_mil2"] = candidate.difference(original).area
            for row in detail["predicted_rows"]:
                opponent = geometry_cache[(
                    str(row["opponent_id"]),
                    str(row["opponent_type"]),
                    int(detail["layer_id"]),
                )]
                predicted = candidate.distance(opponent)
                row["predicted_candidate_clearance_mil"] = predicted
                row["predicted_rule_surplus_mil"] = predicted - float(row["required_mil"])
        connectivity = connectivity_audit(
            records,
            pads_by_id,
            original_geometries,
            candidate_geometries,
            reports_by_id,
        )
    reconstruction_errors = [
        abs(row["distance_reconstruction_error_mil"])
        for detail in details
        for row in detail["clearance_rows"]
    ]
    predicted_surpluses = [
        row["predicted_rule_surplus_mil"]
        for detail in details
        for row in detail["predicted_rows"]
    ]
    row_ids = {
        row["error_id"] for detail in details for row in detail["clearance_rows"]
    }
    expected_remaining_row_ids = {
        row.global_index for row in fill_rows if row.global_index not in excluded_pilot_rows
    }
    if row_ids != expected_remaining_row_ids:
        missing = sorted(expected_remaining_row_ids - row_ids)
        extra = sorted(row_ids - expected_remaining_row_ids)
        raise PlanError(f"remaining FILL DRC coverage mismatch: missing={missing}, extra={extra}")
    maximum_reconstruction_error = max(reconstruction_errors, default=0.0)
    if maximum_reconstruction_error > 0.002:
        raise PlanError(f"geometry reconstruction error too large: {maximum_reconstruction_error} mil")
    if not connectivity["all_original_same_net_contacts_preserved"]:
        raise PlanError(
            f"candidate loses same-net contacts: {connectivity['lost_same_net_contact_rows'][:3]}"
        )
    if not connectivity["all_candidate_components_have_same_net_anchor"]:
        raise PlanError(
            f"candidate creates unanchored copper: {connectivity['unanchored_candidate_components'][:3]}"
        )

    plan = {
        "schema": "stm32h747-multilayer-fill-clearance-plan-v1",
        "pcbUuid": EXPECTED_PCB_UUID,
        "stage": "remaining-after-local-routes-and-two-fill-pilots",
        "manufacturingApproved": False,
        "scope": (
            "existing copper FILL path only; rules/components/nets/routes/arcs/pads/vias/holes "
            "and all non-path FILL fields immutable"
        ),
        "inputs": {
            "source": {"path": str(source.resolve()), "sha256": sha256_file(source)},
            "drc": {"path": str(drc.resolve()), "sha256": sha256_file(drc)},
            "checkpoint": {"path": str(checkpoint.resolve()), "sha256": sha256_file(checkpoint)},
        },
        "rules": {
            "action": "preserve selected JLCPCB Capability (Multiple Layers Board) rules unchanged",
            "rule_record_count": EXPECTED_RULE_COUNT,
            "safety_margin_mm": safety_margin_mm,
            "fill_half_line_width_included": True,
            "opponent_fill_half_line_width_included": True,
            "minimum_track_width_mm_for_neck_diagnostics": MINIMUM_TRACK_WIDTH_MM,
        },
        "excluded": {
            "already_applied_pilot_fill_id": PILOT_FILL_ID,
            "already_applied_pilot_error_ids": sorted(excluded_pilot_rows),
            "protected_fill_ids": sorted(PROTECTED_FILL_IDS),
            "protected_fill_reason": "D13 analytic source capsule remains fixed; the opposing GND fill is clipped",
        },
        "changes": changes,
    }
    report = {
        "schema": "stm32h747-multilayer-fill-clearance-report-v1",
        "status": "offline-remaining-fill-candidate-ready-for-staged-guarded-public-api-application",
        "readOnlyAnalysis": True,
        "manufacturingApproved": False,
        "plan": {"path": str(DEFAULT_REMAINING_PLAN.resolve())},
        "inputs": plan["inputs"],
        "inventory": {
            "native_record_counts": dict(sorted(counts.items())),
            "clearance_rows_total": len(clearance_rows),
            "fill_clearance_rows_baseline": len(fill_rows),
            "excluded_already_applied_pilot_rows": len(excluded_pilot_rows),
            "remaining_fill_clearance_rows_covered": len(row_ids),
            "remaining_changed_fills": len(changes),
            "component_pad_instances_joined": len(pads_by_id),
            "non_fill_clearance_rows_unresolved_by_this_plan": len(clearance_rows) - len(fill_rows),
        },
        "checks": {
            "native_distance_reconstruction_max_error_mil": maximum_reconstruction_error,
            "predicted_minimum_rule_surplus_mil": min(predicted_surpluses, default=None),
            "predicted_all_target_rows_clear": all(value >= 0 for value in predicted_surpluses),
            "only_fill_path_changes": True,
            "selected_18_rules_unchanged_by_plan": True,
            "candidate_nonempty_all": all(row["candidate_area_mil2"] > 0 for row in details),
            "candidate_subset_roundtrip_max_added_area_mil2": max(
                (row["serialized_added_area_mil2"] for row in details), default=0
            ),
            **connectivity,
        },
        "risk_summary": {
            "maximum_area_removed_fraction": max(
                (row["area_removed_fraction"] for row in details), default=0
            ),
            "fills_increasing_polygon_count": [
                row["id"] for row in details
                if row["candidate_polygon_count"] > row["original_polygon_count"]
            ],
            "fills_losing_half_min_track_eroded_area": [
                row["id"] for row in details
                if row["candidate_eroded_half_min_track_area_mil2"] + 1e-6
                < row["original_eroded_half_min_track_area_mil2"]
            ],
            "interpretation": (
                "Erosion deltas identify copper narrowed by clearance cutouts; they are a review signal, "
                "not an assertion that the remaining neck violates minimum track width."
            ),
        },
        "fills": details,
        "requiredPostApply": [
            "apply in small batches through pcb_PrimitiveFill.modify; never use whole-document setSource",
            "narrowly allow only the installed 3.2 recreate normalizations zIndex -> -1 and refs null -> [null]",
            "read back the full native source because the public FILL getter exposes only path[0]",
            "prove each path and every disjoint exterior/CCW hole survives save/reopen",
            "prove all non-target records, all FILL non-path fields except the two known normalizations, and all 18 RULE rows remain unchanged",
            "rerun native DRC after every batch; stop on any new Connection Error",
            "rerun ERC/netlist/connectivity, 6-layer stack, drill, and diagnostic-Gerber audits after the final batch",
            "resolve the separate 357 non-FILL baseline clearances; this FILL-only plan cannot complete DRC",
        ],
    }
    return plan, report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pilot", "remaining"), default="remaining")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--drc", type=Path, default=DEFAULT_DRC)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--pilot-fill", default="378b6a6933052c9a")
    parser.add_argument("--safety-margin-mm", type=float, default=DEFAULT_SAFETY_MARGIN_MM)
    parser.add_argument("--pilot-plan", type=Path, default=DEFAULT_PILOT_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--remaining-plan", type=Path, default=DEFAULT_REMAINING_PLAN)
    parser.add_argument("--remaining-report", type=Path, default=DEFAULT_REMAINING_REPORT)
    parser.add_argument(
        "--skip-derived",
        action="store_true",
        help="do not emit the optional multicontour pilot and post-pilot derivative plans",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for path in (args.source, args.drc, args.checkpoint):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.mode == "pilot":
        plan_path = args.pilot_plan
        report_path = args.report
        plan, report = build_pilot(
            args.source,
            args.drc,
            args.pilot_fill,
            args.safety_margin_mm,
        )
    else:
        plan_path = args.remaining_plan
        report_path = args.remaining_report
        plan, report = build_remaining_plan(
            args.source,
            args.drc,
            args.checkpoint,
            args.safety_margin_mm,
        )
    atomic_write_json(plan_path, plan)
    report["plan"]["path"] = str(plan_path.resolve())
    report["plan"]["sha256"] = sha256_file(plan_path)
    report["plan"]["changeCount"] = len(plan["changes"])
    if args.mode == "remaining" and not args.skip_derived:
        pilot_detail = min(
            (
                row for row in report["fills"]
                if row["candidate_contour_count"] > 1
                and row["candidate_polygon_count"] == 1
                and not row.get("pruned_unanchored_components")
            ),
            key=lambda row: (
                row["candidate_contour_count"],
                row["area_removed_fraction"],
                len(row["clearance_rows"]),
                row["id"],
            ),
        )
        pilot_id = str(pilot_detail["id"])
        pilot_change = next(row for row in plan["changes"] if row["id"] == pilot_id)
        multicontour = copy.deepcopy(plan)
        multicontour["stage"] = "multicontour-hole-roundtrip-pilot"
        multicontour["scope"] = (
            "one two-contour existing FILL path only; validates a retained exterior plus interior hole "
            "through public modify and save/reopen"
        )
        multicontour["changes"] = [pilot_change]
        atomic_write_json(DEFAULT_MULTICONTOUR_PILOT, multicontour)
        after_multicontour = copy.deepcopy(plan)
        after_multicontour["stage"] = "remaining-after-two-fill-pilots"
        after_multicontour["excluded"]["multicontour_pilot_fill_id"] = pilot_id
        after_multicontour["changes"] = [
            row for row in plan["changes"] if row["id"] != pilot_id
        ]
        atomic_write_json(DEFAULT_AFTER_MULTICONTOUR_PLAN, after_multicontour)
        report["multicontourPilot"] = {
            "fill_id": pilot_id,
            "reason": "lowest-risk retained-hole candidate: one polygon, two contours, no pruned island",
            "candidate_contour_count": pilot_detail["candidate_contour_count"],
            "candidate_polygon_count": pilot_detail["candidate_polygon_count"],
            "area_removed_fraction": pilot_detail["area_removed_fraction"],
            "clearance_row_count": len(pilot_detail["clearance_rows"]),
            "same_net_contact_count": len(
                pilot_detail["same_net_connectivity"]["after_contact_ids"]
            ),
            "plan": {
                "path": str(DEFAULT_MULTICONTOUR_PILOT.resolve()),
                "sha256": sha256_file(DEFAULT_MULTICONTOUR_PILOT),
                "changeCount": 1,
            },
            "postPilotRemainingPlan": {
                "path": str(DEFAULT_AFTER_MULTICONTOUR_PLAN.resolve()),
                "sha256": sha256_file(DEFAULT_AFTER_MULTICONTOUR_PLAN),
                "changeCount": len(after_multicontour["changes"]),
            },
            "requiredGate": (
                "full source readback and save/reopen must preserve exactly two contours; native DRC "
                "must remove the five target rows and add no Connection Error before any larger batch"
            ),
        }
    atomic_write_json(report_path, report)
    print(json.dumps({
        "mode": args.mode,
        "plan": str(plan_path),
        "planSha256": sha256_file(plan_path),
        "report": str(report_path),
        "changes": len(plan["changes"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
