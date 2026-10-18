#!/usr/bin/env python3
"""Extract native-schematic source data from the authoritative KiCad PDF.

The KiCad PDF is unusually useful: every clickable component, net segment and
bus segment carries a JavaScript ``ShM([...])`` payload.  This extractor treats
that payload as the primary source of truth, then joins it to the hidden logical
text layer and the colour-coded PDF vector geometry.

It deliberately does *not* read or modify TEST_DAC8562 and it never changes the
source PDF.  The generated JSON is an intermediate reconstruction aid, not a
replacement for ERC and pin/net review in EasyEDA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "보드 자료" / "MCU_BOARD_v19_260827.pdf"
DEFAULT_OUTPUT = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
DEFAULT_GERBER_MANIFEST = ROOT / "output" / "semantic" / "gerber-component-footprints.json"

PT_TO_MM = 25.4 / 72.0
PT_TO_EASYEDA = 100.0 / 72.0
ANNOTATION_PAD_PT = 1.512
COORD_TOLERANCE_PT = 0.05

COLOR_WIRE = (0.0, 0.588235, 0.0)       # KiCad green, #009600
COLOR_BUS = (0.0, 0.0, 0.517647)        # KiCad dark blue, #000084
COLOR_SYMBOL = (0.517647, 0.0, 0.0)     # KiCad symbol red, #840000
COLOR_PIN_NUMBER = (0.662745, 0.0, 0.0) # KiCad pin number red, #A90000
COLOR_PIN_NAME = (0.0, 0.392157, 0.392157)  # KiCad cyan, #006464
COLOR_VALUE = (0.517647, 0.0, 0.517647) # KiCad magenta, #840084
COLOR_SYMBOL_FILL = (1.0, 1.0, 0.760784) # KiCad pale yellow, #FFFFC2
COLOR_DNP_SYMBOL = (0.629412, 0.629412, 0.629412)  # KiCad DNP grey, #A1A1A1
COLOR_DNP_CROSS = (0.883199, 0.179054, 0.192403)  # KiCad DNP cross-out

PAGE_NAMES = {
    2: "mcu",
    3: "mcu_vcc",
    4: "memory",
    5: "enet",
    6: "adc",
}

TECHLABS_RE = re.compile(r"TECHLABS|CO\s*\.?\s*,?\s*LTD", re.IGNORECASE)
MULTI_UNIT_RE = re.compile(r"^([A-Za-z#]+\d+)([A-Z])$")


def rnd(value: Any, places: int = 6) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), places)
    return value


def color_tuple(value: Any) -> tuple[float, ...] | None:
    if not isinstance(value, (tuple, list)):
        return None
    return tuple(round(float(v), 6) for v in value)


def same_color(value: Any, target: tuple[float, ...], tol: float = 0.00001) -> bool:
    colour = color_tuple(value)
    return bool(
        colour is not None
        and len(colour) == len(target)
        and all(abs(a - b) <= tol for a, b in zip(colour, target))
    )


def top_point_to_pdf(point: list[float], page_height: float) -> list[float]:
    return [rnd(point[0]), rnd(page_height - point[1])]


def scale_point(point: list[float], factor: float) -> list[float]:
    return [rnd(point[0] * factor), rnd(point[1] * factor)]


def scale_bbox(bbox: list[float], factor: float) -> list[float]:
    return [rnd(v * factor) for v in bbox]


def bbox_pdf_to_top(rect: Iterable[float], page_height: float) -> list[float]:
    x0, y0, x1, y1 = (float(v) for v in rect)
    return [rnd(x0), rnd(page_height - y1), rnd(x1), rnd(page_height - y0)]


def bbox_top_to_pdf(rect: Iterable[float], page_height: float) -> list[float]:
    x0, top, x1, bottom = (float(v) for v in rect)
    return [rnd(x0), rnd(page_height - bottom), rnd(x1), rnd(page_height - top)]


def coordinate_bbox(rect_pdf: Iterable[float], page_height: float) -> dict[str, list[float]]:
    pdf_rect = [rnd(v) for v in rect_pdf]
    top_rect = bbox_pdf_to_top(pdf_rect, page_height)
    return {
        "pdf_bl_pt": pdf_rect,
        "top_left_pt": top_rect,
        "top_left_mm": scale_bbox(top_rect, PT_TO_MM),
        "easyeda": scale_bbox(top_rect, PT_TO_EASYEDA),
    }


def decode_pdf_js(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "get_data"):
        value = value.get_data()
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


JS_ROW_RE = re.compile(
    r'\["((?:\\.|[^"\\])*)"(?:,\s*"((?:\\.|[^"\\])*)")?\]'
)


def parse_shm_rows(js: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for match in JS_ROW_RE.finditer(js):
        row: list[str] = []
        for raw in match.groups():
            if raw is None:
                continue
            try:
                row.append(json.loads(f'"{raw}"'))
            except json.JSONDecodeError:
                row.append(raw.replace(r'\"', '"').replace(r"\\", "\\"))
        rows.append(row)
    return rows


def ordered_fields(rows: list[list[str]]) -> tuple[list[dict[str, str]], dict[str, str], list[dict[str, str]]]:
    ordered: list[dict[str, str]] = []
    fields: dict[str, str] = {}
    urls: list[dict[str, str]] = []
    for row in rows:
        if len(row) == 1 and " = " in row[0]:
            key, value = row[0].split(" = ", 1)
            ordered.append({"name": key, "value": value})
            fields[key] = value
        elif len(row) == 2:
            urls.append({"label": row[0], "url": row[1]})
    return ordered, fields, urls


def classify_text(colour: tuple[float, ...] | None) -> str:
    if same_color(colour, COLOR_PIN_NUMBER):
        return "pin_number"
    if same_color(colour, COLOR_PIN_NAME):
        return "pin_name_or_reference"
    if same_color(colour, COLOR_VALUE):
        return "component_value"
    if same_color(colour, COLOR_WIRE):
        return "net_text"
    if same_color(colour, COLOR_BUS):
        return "bus_or_no_connect_text"
    if same_color(colour, COLOR_SYMBOL):
        return "symbol_text"
    return "other"


def serialise_word(word: dict[str, Any], page_height: float) -> dict[str, Any]:
    top_bbox = [float(word["x0"]), float(word["top"]), float(word["x1"]), float(word["bottom"])]
    return {
        "text": word["text"],
        "bbox": {
            "top_left_pt": [rnd(v) for v in top_bbox],
            "pdf_bl_pt": bbox_top_to_pdf(top_bbox, page_height),
            "easyeda": scale_bbox(top_bbox, PT_TO_EASYEDA),
        },
        "font": word.get("fontname"),
        "size_pt": rnd(word.get("size", 0.0)),
        "upright": bool(word.get("upright", True)),
        "stroking_color": list(color_tuple(word.get("stroking_color")) or ()),
        "non_stroking_color": list(color_tuple(word.get("non_stroking_color")) or ()),
        "category": classify_text(color_tuple(word.get("stroking_color"))),
    }


def line_points_top(line: dict[str, Any]) -> list[list[float]]:
    points = line.get("pts") or []
    if len(points) >= 2:
        return [[rnd(points[0][0]), rnd(points[0][1])], [rnd(points[-1][0]), rnd(points[-1][1])]]
    return [
        [rnd(line["x0"]), rnd(line["top"])],
        [rnd(line["x1"]), rnd(line["bottom"])],
    ]


def serialise_line(line: dict[str, Any], page_height: float) -> dict[str, Any]:
    points = line_points_top(line)
    return {
        "p1": points[0],
        "p2": points[1],
        "p1_pdf_bl": top_point_to_pdf(points[0], page_height),
        "p2_pdf_bl": top_point_to_pdf(points[1], page_height),
        "p1_easyeda": scale_point(points[0], PT_TO_EASYEDA),
        "p2_easyeda": scale_point(points[1], PT_TO_EASYEDA),
        "bbox_pdf_bl_pt": [rnd(line[k]) for k in ("x0", "y0", "x1", "y1")],
        "line_width_pt": rnd(line.get("linewidth", 0.0)),
        "stroking_color": list(color_tuple(line.get("stroking_color")) or ()),
    }


def path_to_json(path: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in path:
        if not entry:
            continue
        command = entry[0]
        points: list[list[float]] = []
        for item in entry[1:]:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                points.append([rnd(item[0]), rnd(item[1])])
        result.append({"op": command, "points": points})
    return result


def serialise_curve(curve: dict[str, Any], page_height: float) -> dict[str, Any]:
    top_bbox = [float(curve["x0"]), float(curve["top"]), float(curve["x1"]), float(curve["bottom"])]
    return {
        "bbox": {
            "top_left_pt": [rnd(v) for v in top_bbox],
            "pdf_bl_pt": bbox_top_to_pdf(top_bbox, page_height),
            "easyeda": scale_bbox(top_bbox, PT_TO_EASYEDA),
        },
        "path_top_left_pt": path_to_json(curve.get("path") or []),
        "line_width_pt": rnd(curve.get("linewidth", 0.0)),
        "stroke": bool(curve.get("stroke")),
        "fill": bool(curve.get("fill")),
        "stroking_color": list(color_tuple(curve.get("stroking_color")) or ()),
        "non_stroking_color": list(color_tuple(curve.get("non_stroking_color")) or ()),
    }


def serialise_rect(rect: dict[str, Any], page_height: float) -> dict[str, Any]:
    pdf_bbox = [float(rect[k]) for k in ("x0", "y0", "x1", "y1")]
    return {
        "bbox": coordinate_bbox(pdf_bbox, page_height),
        "line_width_pt": rnd(rect.get("linewidth", 0.0)),
        "stroke": bool(rect.get("stroke")),
        "fill": bool(rect.get("fill")),
        "stroking_color": list(color_tuple(rect.get("stroking_color")) or ()),
        "non_stroking_color": list(color_tuple(rect.get("non_stroking_color")) or ()),
    }


def exact_annotation_for_line(
    line: dict[str, Any],
    annotations: list[dict[str, Any]],
    tolerance: float = COORD_TOLERANCE_PT,
) -> dict[str, Any] | None:
    expected = [
        float(line["x0"]) - ANNOTATION_PAD_PT,
        float(line["y0"]) - ANNOTATION_PAD_PT,
        float(line["x1"]) + ANNOTATION_PAD_PT,
        float(line["y1"]) + ANNOTATION_PAD_PT,
    ]
    for annotation in annotations:
        rect = annotation["bbox"]["pdf_bl_pt"]
        if max(abs(float(rect[i]) - expected[i]) for i in range(4)) <= tolerance:
            return annotation
    return None


def point_on_segment(point: list[float], segment: dict[str, Any], tolerance: float = COORD_TOLERANCE_PT) -> bool:
    x, y = point
    a, b = segment["p1"], segment["p2"]
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    length = math.hypot(bx - ax, by - ay)
    if length and abs(cross) / length > tolerance:
        return False
    return (
        min(ax, bx) - tolerance <= x <= max(ax, bx) + tolerance
        and min(ay, by) - tolerance <= y <= max(ay, by) + tolerance
    )


def bbox_contains_point(rect: list[float], point: list[float], margin: float = 0.0) -> bool:
    return (
        rect[0] - margin <= point[0] <= rect[2] + margin
        and rect[1] - margin <= point[1] <= rect[3] + margin
    )


def bbox_contains_bbox(outer: list[float], inner: list[float], margin: float = 0.0) -> bool:
    return (
        outer[0] - margin <= inner[0]
        and outer[1] - margin <= inner[1]
        and outer[2] + margin >= inner[2]
        and outer[3] + margin >= inner[3]
    )


def word_centre(word: dict[str, Any]) -> list[float]:
    bbox = word["bbox"]["top_left_pt"]
    return [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]


def nearest_word_for_pin(
    words: list[dict[str, Any]],
    side: str,
    point: list[float],
    component_bbox: list[float],
    category: str,
) -> dict[str, Any] | None:
    centre_x = (component_bbox[0] + component_bbox[2]) / 2.0
    candidates: list[tuple[float, dict[str, Any]]] = []
    for word in words:
        if word["category"] != category:
            continue
        cx, cy = word_centre(word)
        if side == "left" and cx >= centre_x:
            continue
        if side == "right" and cx <= centre_x:
            continue
        if side == "top" and cy >= (component_bbox[1] + component_bbox[3]) / 2.0:
            continue
        if side == "bottom" and cy <= (component_bbox[1] + component_bbox[3]) / 2.0:
            continue

        if side in ("left", "right"):
            # KiCad prints the number just above and the name just below a pin.
            desired_delta = -2.19 if category == "pin_number" else 1.35
            primary = abs((cy - point[1]) - desired_delta)
            secondary = abs(cx - point[0]) * 0.01
            if primary <= 3.2:
                candidates.append((primary + secondary, word))
        else:
            distance = math.hypot(cx - point[0], cy - point[1])
            if distance <= 28.0:
                candidates.append((distance, word))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def pin_lines_for_component(
    rect_top: list[float], red_lines: list[dict[str, Any]]
) -> list[tuple[str, list[float], dict[str, Any]]]:
    x0, top, x1, bottom = rect_top
    expected_left = x0 + 1.08
    expected_right = x1 - 1.08
    expected_top = top + 1.08
    expected_bottom = bottom - 1.08
    found: list[tuple[str, list[float], dict[str, Any]]] = []
    seen: set[tuple[str, float, float]] = set()

    for line in red_lines:
        p1, p2 = line_points_top(line)
        line_bbox = [min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])]
        if not bbox_contains_bbox(rect_top, line_bbox, margin=0.25):
            continue
        dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
        side: str | None = None
        connection: list[float] | None = None
        if dy <= 0.03 and dx >= 2.0:
            left_point = p1 if p1[0] <= p2[0] else p2
            right_point = p2 if p2[0] >= p1[0] else p1
            if abs(left_point[0] - expected_left) <= 1.5:
                side, connection = "left", left_point
            elif abs(right_point[0] - expected_right) <= 1.5:
                side, connection = "right", right_point
        elif dx <= 0.03 and dy >= 2.0:
            top_point = p1 if p1[1] <= p2[1] else p2
            bottom_point = p2 if p2[1] >= p1[1] else p1
            if abs(top_point[1] - expected_top) <= 1.5:
                side, connection = "top", top_point
            elif abs(bottom_point[1] - expected_bottom) <= 1.5:
                side, connection = "bottom", bottom_point

        if side and connection:
            key = (side, round(connection[0], 3), round(connection[1], 3))
            if key not in seen:
                seen.add(key)
                found.append((side, connection, line))
    return sorted(found, key=lambda item: (item[0], item[1][1], item[1][0]))


def infer_multi_unit(reference: str) -> tuple[str, str | None]:
    match = MULTI_UNIT_RE.match(reference)
    if not match:
        return reference, None
    return match.group(1), match.group(2)


def extract_outlines(reader: PdfReader) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)

    def walk(items: list[Any], parents: list[str]) -> None:
        prior_title: str | None = None
        for item in items:
            if isinstance(item, list):
                walk(item, parents + ([prior_title] if prior_title else []))
                continue
            title = getattr(item, "title", str(item))
            prior_title = title
            try:
                page_number = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            entry: dict[str, Any] = {"title": title, "path": parents + [title]}
            destination = list(getattr(item, "dest_array", []) or [])
            if len(destination) >= 6 and str(destination[1]) == "/FitR":
                left, a, right, b = (float(destination[i]) for i in (2, 3, 4, 5))
                entry["fit_rect_pdf_bl_pt"] = [rnd(left), rnd(min(a, b)), rnd(right), rnd(max(a, b))]
            result[page_number].append(entry)

    walk(reader.outline, [])
    return result


def component_graphics(
    component_bbox: list[float],
    page_height: float,
    red_lines: list[dict[str, Any]],
    inactive_lines: list[dict[str, Any]],
    dnp_cross_lines: list[dict[str, Any]],
    symbol_rects: list[dict[str, Any]],
    symbol_curves: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    lines: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []
    dnp_cross: list[dict[str, Any]] = []
    rects: list[dict[str, Any]] = []
    curves: list[dict[str, Any]] = []
    origin = [component_bbox[0], component_bbox[1]]

    for line in red_lines:
        p1, p2 = line_points_top(line)
        line_bbox = [min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])]
        if bbox_contains_bbox(component_bbox, line_bbox, margin=0.25):
            item = serialise_line(line, page_height)
            item["p1_local_easyeda"] = scale_point([p1[0] - origin[0], p1[1] - origin[1]], PT_TO_EASYEDA)
            item["p2_local_easyeda"] = scale_point([p2[0] - origin[0], p2[1] - origin[1]], PT_TO_EASYEDA)
            lines.append(item)

    for source, destination in ((inactive_lines, inactive), (dnp_cross_lines, dnp_cross)):
        for line in source:
            p1, p2 = line_points_top(line)
            line_bbox = [min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1])]
            if bbox_contains_bbox(component_bbox, line_bbox, margin=0.25):
                item = serialise_line(line, page_height)
                item["p1_local_easyeda"] = scale_point([p1[0] - origin[0], p1[1] - origin[1]], PT_TO_EASYEDA)
                item["p2_local_easyeda"] = scale_point([p2[0] - origin[0], p2[1] - origin[1]], PT_TO_EASYEDA)
                destination.append(item)

    for rect in symbol_rects:
        top_bbox = [float(rect["x0"]), float(rect["top"]), float(rect["x1"]), float(rect["bottom"])]
        if bbox_contains_bbox(component_bbox, top_bbox, margin=0.25):
            item = serialise_rect(rect, page_height)
            item["bbox_local_easyeda"] = scale_bbox(
                [top_bbox[0] - origin[0], top_bbox[1] - origin[1], top_bbox[2] - origin[0], top_bbox[3] - origin[1]],
                PT_TO_EASYEDA,
            )
            rects.append(item)

    for curve in symbol_curves:
        top_bbox = [float(curve["x0"]), float(curve["top"]), float(curve["x1"]), float(curve["bottom"])]
        if bbox_contains_bbox(component_bbox, top_bbox, margin=0.25):
            curves.append(serialise_curve(curve, page_height))

    return {
        "lines": lines,
        "inactive_lines": inactive,
        "dnp_cross_lines": dnp_cross,
        "rects": rects,
        "curves": curves,
    }


def terminal_candidates_for_component(
    component: dict[str, Any],
    wire_segments: list[dict[str, Any]],
    no_connects: list[dict[str, Any]],
    page_height: float,
) -> list[dict[str, Any]]:
    """Return every plausible symbol-line endpoint with exact electrical context.

    Pin strokes are red for fitted parts and grey for KiCad DNP parts.  Keeping
    all endpoints here is intentional: the Gerber pad manifest and hidden pin
    numbers resolve the small number of internal symbol endpoints later.
    """

    source_lines = component["graphics"]["lines"] + component["graphics"]["inactive_lines"]
    point_lines: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    all_points: list[list[float]] = []
    for line in source_lines:
        for point in (line["p1"], line["p2"]):
            key = (round(float(point[0]), 3), round(float(point[1]), 3))
            point_lines[key].append(line)
            all_points.append([key[0], key[1]])
    if not point_lines:
        return []

    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    graphic_centre = [(min_x + max_x) / 2.0, (min_y + max_y) / 2.0]
    component_bbox = component["bbox"]["top_left_pt"]
    component_centre = [
        (component_bbox[0] + component_bbox[2]) / 2.0,
        (component_bbox[1] + component_bbox[3]) / 2.0,
    ]

    candidates: list[dict[str, Any]] = []
    for key, lines in sorted(point_lines.items()):
        point = [key[0], key[1]]
        nets = sorted(
            {
                segment["net"]
                for segment in wire_segments
                if point_on_segment(point, segment)
            }
        )
        no_connect = any(
            math.dist(point, mark["centre_top_left_pt"]) <= COORD_TOLERANCE_PT
            for mark in no_connects
        )
        dx = point[0] - graphic_centre[0]
        dy = point[1] - graphic_centre[1]
        if abs(dx) >= abs(dy):
            side = "left" if dx < 0 else "right"
        else:
            side = "top" if dy < 0 else "bottom"
        candidates.append(
            {
                "point": {
                    "top_left_pt": point,
                    "pdf_bl_pt": top_point_to_pdf(point, page_height),
                    "easyeda": scale_point(point, PT_TO_EASYEDA),
                    "local_easyeda": scale_point(
                        [point[0] - component_bbox[0], point[1] - component_bbox[1]],
                        PT_TO_EASYEDA,
                    ),
                },
                "side": side,
                "adjacent_nets": nets,
                "no_connect": no_connect,
                "touches_wire": bool(nets),
                "graphic_radial_distance_pt": rnd(math.hypot(dx, dy)),
                "component_centre_distance_pt": rnd(math.dist(point, component_centre)),
                "line_count_at_endpoint": len(lines),
                "line_colours": sorted({tuple(line["stroking_color"]) for line in lines}),
            }
        )
    return candidates


def extract_page(
    reader: PdfReader,
    plumber_page: Any,
    page_number: int,
    outline_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    pdf_page = reader.pages[page_number - 1]
    width, height = float(plumber_page.width), float(plumber_page.height)

    component_annotations: list[dict[str, Any]] = []
    net_annotations: list[dict[str, Any]] = []
    bus_annotations: list[dict[str, Any]] = []
    other_annotations: list[dict[str, Any]] = []

    for annotation_index, annotation_ref in enumerate(pdf_page.get("/Annots") or []):
        annotation = annotation_ref.get_object()
        action = annotation.get("/A") or {}
        if str(action.get("/S")) != "/JavaScript":
            continue
        js = decode_pdf_js(action.get("/JS"))
        rows = parse_shm_rows(js)
        ordered, fields, urls = ordered_fields(rows)
        rect_pdf = [float(v) for v in annotation.get("/Rect")]
        base = {
            "annotation_index": annotation_index,
            "bbox": coordinate_bbox(rect_pdf, height),
            "rows": rows,
        }
        if "Reference" in fields:
            reference = fields.get("Reference", "")
            base_reference, unit = infer_multi_unit(reference)
            value = fields.get("Value", "")
            upper_value = value.upper()
            base.update(
                {
                    "reference": reference,
                    "base_reference": base_reference,
                    "unit": unit,
                    "value": value,
                    "footprint": fields.get("Footprint", ""),
                    "fields_ordered": ordered,
                    "fields": fields,
                    "urls": urls,
                    "dnp": any(token in upper_value for token in ("_NC", "DNP", "DNF", "NO FIT")),
                    "is_power_symbol": reference.startswith("#PWR") or reference.startswith("#FLG"),
                }
            )
            component_annotations.append(base)
        elif "Net" in fields:
            base.update(
                {
                    "net": fields.get("Net", ""),
                    "netclass": fields.get("Resolved netclass", ""),
                    "sheet_references": fields.get("Sheet References", ""),
                    "fields_ordered": ordered,
                }
            )
            net_annotations.append(base)
        elif rows and all(len(row) == 1 for row in rows):
            base["members"] = [row[0] for row in rows]
            bus_annotations.append(base)
        else:
            base["js"] = js
            other_annotations.append(base)

    raw_words = plumber_page.extract_words(
        extra_attrs=["stroking_color", "non_stroking_color", "fontname", "size", "upright"],
        keep_blank_chars=False,
        use_text_flow=False,
        x_tolerance=1,
        y_tolerance=1,
    )
    words: list[dict[str, Any]] = []
    suppressed_words: list[dict[str, Any]] = []
    for word in raw_words:
        serialised = serialise_word(word, height)
        if TECHLABS_RE.search(serialised["text"]):
            suppressed_words.append(serialised)
        else:
            words.append(serialised)

    raw_lines = list(plumber_page.lines)
    green_lines = [line for line in raw_lines if same_color(line.get("stroking_color"), COLOR_WIRE)]
    blue_lines = [line for line in raw_lines if same_color(line.get("stroking_color"), COLOR_BUS)]
    red_lines = [line for line in raw_lines if same_color(line.get("stroking_color"), COLOR_SYMBOL)]
    inactive_lines = [line for line in raw_lines if same_color(line.get("stroking_color"), COLOR_DNP_SYMBOL)]
    dnp_cross_lines = [line for line in raw_lines if same_color(line.get("stroking_color"), COLOR_DNP_CROSS)]

    wire_segments: list[dict[str, Any]] = []
    bus_entries_raw: list[dict[str, Any]] = []
    for line in green_lines:
        annotation = exact_annotation_for_line(line, net_annotations)
        item = serialise_line(line, height)
        if annotation is not None:
            item["net"] = annotation["net"]
            item["annotation_index"] = annotation["annotation_index"]
            wire_segments.append(item)
        else:
            bus_entries_raw.append(item)

    # Unmatched green lines in this PDF are bus-entry diagonals.  Their wire-side
    # endpoint touches an already tagged green segment, making the member net exact.
    bus_entries: list[dict[str, Any]] = []
    for entry in bus_entries_raw:
        adjacent_nets: set[str] = set()
        for point in (entry["p1"], entry["p2"]):
            for segment in wire_segments:
                if point_on_segment(point, segment):
                    adjacent_nets.add(segment["net"])
        entry["net"] = sorted(adjacent_nets)[0] if len(adjacent_nets) == 1 else None
        entry["adjacent_nets"] = sorted(adjacent_nets)
        bus_entries.append(entry)

    # A KiCad no-connect mark is exactly two #000084 diagonal 3.456 pt lines
    # sharing a centre.  Bus segments are the remaining blue lines.
    no_connect_groups: dict[tuple[float, float], list[dict[str, Any]]] = defaultdict(list)
    non_nc_blue: list[dict[str, Any]] = []
    for line in blue_lines:
        p1, p2 = line_points_top(line)
        dx, dy = abs(p2[0] - p1[0]), abs(p2[1] - p1[1])
        if abs(dx - 3.456) <= 0.03 and abs(dy - 3.456) <= 0.03 and abs(float(line.get("linewidth", 0)) - 0.432) <= 0.03:
            centre = (round((p1[0] + p2[0]) / 2.0, 3), round((p1[1] + p2[1]) / 2.0, 3))
            no_connect_groups[centre].append(line)
        else:
            non_nc_blue.append(line)

    no_connects: list[dict[str, Any]] = []
    nc_centres: list[list[float]] = []
    for centre, lines in sorted(no_connect_groups.items()):
        if len(lines) != 2:
            non_nc_blue.extend(lines)
            continue
        centre_list = [centre[0], centre[1]]
        nc_centres.append(centre_list)
        no_connects.append(
            {
                "centre_top_left_pt": centre_list,
                "centre_pdf_bl_pt": top_point_to_pdf(centre_list, height),
                "centre_easyeda": scale_point(centre_list, PT_TO_EASYEDA),
                "lines": [serialise_line(line, height) for line in lines],
            }
        )

    bus_segments: list[dict[str, Any]] = []
    for line in non_nc_blue:
        annotation = exact_annotation_for_line(line, bus_annotations)
        item = serialise_line(line, height)
        if annotation:
            item["members"] = annotation.get("members", [])
            item["annotation_index"] = annotation["annotation_index"]
        bus_segments.append(item)

    green_curves = [
        curve
        for curve in plumber_page.curves
        if same_color(curve.get("stroking_color"), COLOR_WIRE)
        and same_color(curve.get("non_stroking_color"), COLOR_WIRE)
        and bool(curve.get("fill"))
    ]
    junctions: list[dict[str, Any]] = []
    for curve in green_curves:
        width_curve = float(curve["x1"]) - float(curve["x0"])
        height_curve = float(curve["bottom"]) - float(curve["top"])
        if width_curve <= 3.0 and height_curve <= 3.0:
            item = serialise_curve(curve, height)
            bbox = item["bbox"]["top_left_pt"]
            centre = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
            item["centre_top_left_pt"] = [rnd(v) for v in centre]
            item["centre_easyeda"] = scale_point(centre, PT_TO_EASYEDA)
            junctions.append(item)

    symbol_rects = [
        rect
        for rect in plumber_page.rects
        if same_color(rect.get("stroking_color"), COLOR_SYMBOL)
        or same_color(rect.get("non_stroking_color"), COLOR_SYMBOL_FILL)
    ]
    symbol_curves = [
        curve
        for curve in plumber_page.curves
        if same_color(curve.get("stroking_color"), COLOR_SYMBOL)
        or same_color(curve.get("non_stroking_color"), COLOR_SYMBOL_FILL)
    ]

    # Join the component popup rectangle to pin strokes, hidden pin text, net
    # tagged wires, and exact no-connect centres.
    for component in component_annotations:
        rect_top = component["bbox"]["top_left_pt"]
        component_words = [
            word
            for word in words
            if bbox_contains_point(rect_top, word_centre(word), margin=2.5)
        ]
        pins: list[dict[str, Any]] = []
        for side, connection, raw_line in pin_lines_for_component(rect_top, red_lines):
            number_word = nearest_word_for_pin(component_words, side, connection, rect_top, "pin_number")
            name_word = nearest_word_for_pin(component_words, side, connection, rect_top, "pin_name_or_reference")
            connected_nets = {
                segment["net"]
                for segment in wire_segments
                if point_on_segment(connection, segment)
            }
            no_connect = any(math.dist(connection, centre) <= COORD_TOLERANCE_PT for centre in nc_centres)
            name = name_word["text"] if name_word else None
            pin: dict[str, Any] = {
                "number": number_word["text"] if number_word else None,
                "name": name,
                "side": side,
                "connection": {
                    "top_left_pt": [rnd(v) for v in connection],
                    "pdf_bl_pt": top_point_to_pdf(connection, height),
                    "easyeda": scale_point(connection, PT_TO_EASYEDA),
                    "local_easyeda": scale_point(
                        [connection[0] - rect_top[0], connection[1] - rect_top[1]], PT_TO_EASYEDA
                    ),
                },
                "line": serialise_line(raw_line, height),
                "net": sorted(connected_nets)[0] if len(connected_nets) == 1 else None,
                "adjacent_nets": sorted(connected_nets),
                "no_connect": no_connect,
                "intrinsic_nc_pin": bool(name and name.upper() == "NC"),
            }
            if number_word and name_word and (connected_nets or no_connect or pin["intrinsic_nc_pin"]):
                pin["confidence"] = "high"
            elif number_word and name_word:
                pin["confidence"] = "text_and_geometry"
            else:
                pin["confidence"] = "geometry_only"
            pins.append(pin)

        component["origin_easyeda"] = [component["bbox"]["easyeda"][0], component["bbox"]["easyeda"][1]]
        component["pin_text_words"] = [
            word for word in component_words if word["category"] in ("pin_number", "pin_name_or_reference")
        ]
        component["pins"] = pins
        component["graphics"] = component_graphics(
            rect_top,
            height,
            red_lines,
            inactive_lines,
            dnp_cross_lines,
            symbol_rects,
            symbol_curves,
        )
        component["terminal_candidates"] = terminal_candidates_for_component(
            component, wire_segments, no_connects, height
        )

    unique_nets = sorted({annotation["net"] for annotation in net_annotations})
    page = {
        "pdf_page": page_number,
        "new_sheet_index": page_number - 1,
        "sheet_name": PAGE_NAMES[page_number],
        "size": {
            "width_pt": rnd(width),
            "height_pt": rnd(height),
            "width_mm": rnd(width * PT_TO_MM),
            "height_mm": rnd(height * PT_TO_MM),
            "width_easyeda": rnd(width * PT_TO_EASYEDA),
            "height_easyeda": rnd(height * PT_TO_EASYEDA),
        },
        "outline_symbols": outline_entries,
        "components": component_annotations,
        "net_annotations": net_annotations,
        "bus_annotations": bus_annotations,
        "other_annotations": other_annotations,
        "text_words": words,
        "suppressed_company_text_words": suppressed_words,
        "wire_segments": wire_segments,
        "bus_entries": bus_entries,
        "bus_segments": bus_segments,
        "no_connects": no_connects,
        "junctions": junctions,
        "summary": {
            "component_count": len(component_annotations),
            "physical_component_count": len([c for c in component_annotations if not c["is_power_symbol"]]),
            "power_symbol_count": len([c for c in component_annotations if c["is_power_symbol"]]),
            "dnp_component_count": len([c for c in component_annotations if c["dnp"]]),
            "unique_net_count": len(unique_nets),
            "net_annotation_count": len(net_annotations),
            "bus_annotation_count": len(bus_annotations),
            "wire_segment_count": len(wire_segments),
            "wire_segments_with_exact_js_net": len(wire_segments),
            "bus_entry_count": len(bus_entries),
            "bus_entries_with_inferred_unique_net": len([entry for entry in bus_entries if entry["net"]]),
            "bus_segment_count": len(bus_segments),
            "no_connect_count": len(no_connects),
            "junction_count": len(junctions),
            "pin_instance_count": sum(len(c["pins"]) for c in component_annotations),
            "pins_with_number_and_name": sum(
                1 for c in component_annotations for pin in c["pins"] if pin["number"] and pin["name"]
            ),
            "pins_with_net": sum(1 for c in component_annotations for pin in c["pins"] if pin["net"]),
            "suppressed_company_text_word_count": len(suppressed_words),
        },
    }
    return page


def natural_pin_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def normalise_net_name(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if text.upper() in {"N/C", "NC", "NO CONNECT"}:
        return None
    if text.startswith("unconnected-("):
        return None
    if text.startswith("/"):
        parts = text.split("/")
        if len(parts) >= 3:
            text = "/".join(parts[2:])
    return text


def point_key(point: list[float] | None) -> tuple[float, float] | None:
    if point is None:
        return None
    return (round(float(point[0]), 3), round(float(point[1]), 3))


def candidate_point_key(candidate: dict[str, Any]) -> tuple[float, float]:
    return point_key(candidate["point"]["top_left_pt"])  # type: ignore[return-value]


def old_pad_is_unconnected(pad: dict[str, Any]) -> bool:
    net = str(pad.get("netOld") or "")
    return net.upper() in {"N/C", "NC", "NO CONNECT"} or net.startswith("unconnected-(")


def make_pin_from_candidate(
    number: str,
    pad: dict[str, Any],
    candidate: dict[str, Any] | None,
    provenance: str,
    *,
    dnp: bool = False,
    hidden: bool = False,
) -> dict[str, Any]:
    pin_function = pad.get("pinFunctionOld")
    intrinsic_nc = (
        str(pad.get("netOld") or "").upper() in {"N/C", "NC", "NO CONNECT"}
        or str(pin_function or "").upper() in {"N/C", "NC", "NO CONNECT"}
    )
    if candidate is None:
        net = None
        no_connect = intrinsic_nc or str(pad.get("netOld") or "").startswith("unconnected-(")
        connection = None
        side = None
        adjacent_nets: list[str] = []
    else:
        adjacent_nets = list(candidate.get("adjacent_nets") or [])
        target = normalise_net_name(pad.get("netOld"))
        matching = [net for net in adjacent_nets if normalise_net_name(net) == target]
        net = matching[0] if matching else (adjacent_nets[0] if len(adjacent_nets) == 1 else None)
        no_connect = bool(candidate.get("no_connect"))
        connection = candidate["point"]
        side = candidate.get("side")

    if net:
        state = "connected"
    elif intrinsic_nc:
        state = "intrinsic_nc"
    elif no_connect:
        state = "no_connect_marker"
    elif dnp:
        state = "dnp_disconnected"
    else:
        state = "unconnected"

    return {
        "number": number,
        "name": pin_function,
        "side": side,
        "connection": connection,
        "line": None,
        "net": net,
        "adjacent_nets": adjacent_nets,
        "no_connect": no_connect,
        "intrinsic_nc_pin": intrinsic_nc,
        "hidden": hidden,
        "electrical_state": state,
        "confidence": "high" if provenance != "two_terminal_orientation" else "geometry_and_footprint",
        "provenance": provenance,
        "footprint_pad": {
            "number": number,
            "pin_function_old": pin_function,
            "gerber_net_old": pad.get("netOld"),
        },
    }


def candidate_for_existing_pin(
    component: dict[str, Any], pin: dict[str, Any]
) -> dict[str, Any] | None:
    connection = pin.get("connection") or {}
    key = point_key(connection.get("top_left_pt"))
    if key is None:
        return None
    for candidate in component.get("terminal_candidates", []):
        if candidate_point_key(candidate) == key:
            return candidate
    # The old detector can be more precise than the endpoint catalogue.  Keep
    # that exact point, but retain the same candidate schema.
    return {
        "point": connection,
        "side": pin.get("side"),
        "adjacent_nets": pin.get("adjacent_nets") or ([pin["net"]] if pin.get("net") else []),
        "no_connect": bool(pin.get("no_connect")),
        "touches_wire": bool(pin.get("net")),
        "graphic_radial_distance_pt": 0.0,
        "component_centre_distance_pt": 0.0,
    }


def unique_pin_number_words(component: dict[str, Any], expected: set[str]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[float, ...]]] = set()
    for word in component.get("pin_text_words", []):
        text = str(word.get("text") or "")
        if word.get("category") != "pin_number" or text not in expected:
            continue
        bbox = tuple(round(float(v), 3) for v in word["bbox"]["top_left_pt"])
        key = (text, bbox)
        if key not in seen:
            seen.add(key)
            found.append(word)
    return found


def choose_candidate_near_word(
    component: dict[str, Any],
    word: dict[str, Any],
    pad: dict[str, Any],
    assigned: set[tuple[float, float]],
) -> dict[str, Any] | None:
    centre = word_centre(word)
    target_net = normalise_net_name(pad.get("netOld"))
    choices: list[tuple[float, dict[str, Any]]] = []
    for candidate in component.get("terminal_candidates", []):
        key = candidate_point_key(candidate)
        if key in assigned:
            continue
        point = candidate["point"]["top_left_pt"]
        distance = math.dist(centre, point)
        if distance > 32.0:
            continue
        exact_net = any(normalise_net_name(net) == target_net for net in candidate.get("adjacent_nets", []))
        score = distance
        if exact_net:
            score -= 40.0
        if candidate.get("touches_wire") or candidate.get("no_connect"):
            score -= 2.0
        # Pin numbers sit between the body and terminal, so symmetric distances
        # can tie.  The electrically exposed endpoint is the more radial one.
        score -= 0.05 * float(candidate.get("graphic_radial_distance_pt", 0.0))
        choices.append((score, candidate))
    return min(choices, key=lambda pair: pair[0])[1] if choices else None


def choose_candidate_for_old_net(
    components: list[dict[str, Any]],
    pad: dict[str, Any],
    assigned_by_component: dict[int, set[tuple[float, float]]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    target = normalise_net_name(pad.get("netOld"))
    if target is None:
        return None
    choices: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for component in components:
        assigned = assigned_by_component[id(component)]
        for candidate in component.get("terminal_candidates", []):
            if candidate_point_key(candidate) in assigned:
                continue
            if not any(normalise_net_name(net) == target for net in candidate.get("adjacent_nets", [])):
                continue
            # Nearby power symbols can overlap a small component annotation.
            # The real terminal is consistently the matching point nearest the
            # component annotation centre.
            score = float(candidate.get("component_centre_distance_pt", 0.0))
            choices.append((score, component, candidate))
    if not choices:
        return None
    _, component, candidate = min(choices, key=lambda item: item[0])
    return component, candidate


def select_two_terminal_candidates(
    component: dict[str, Any],
    count: int,
    assigned: set[tuple[float, float]],
) -> list[dict[str, Any]]:
    choices = [
        candidate
        for candidate in component.get("terminal_candidates", [])
        if candidate_point_key(candidate) not in assigned
    ]
    choices.sort(
        key=lambda candidate: (
            bool(candidate.get("touches_wire") or candidate.get("no_connect")),
            float(candidate.get("graphic_radial_distance_pt", 0.0)),
        ),
        reverse=True,
    )
    selected = choices[:count]
    if len(selected) <= 1:
        return selected
    points = [candidate["point"]["top_left_pt"] for candidate in selected]
    x_span = max(point[0] for point in points) - min(point[0] for point in points)
    y_span = max(point[1] for point in points) - min(point[1] for point in points)
    if x_span >= y_span:
        selected.sort(key=lambda candidate: candidate["point"]["top_left_pt"][0])
    else:
        selected.sort(key=lambda candidate: candidate["point"]["top_left_pt"][1])
    return selected


def add_wire_endpoint_fallbacks(component: dict[str, Any], page: dict[str, Any]) -> None:
    bbox = component["bbox"]["top_left_pt"]
    existing = {candidate_point_key(candidate) for candidate in component.get("terminal_candidates", [])}
    for segment in page["wire_segments"]:
        for point in (segment["p1"], segment["p2"]):
            key = point_key(point)
            if key in existing or not bbox_contains_point(bbox, point, margin=0.25):
                continue
            centre = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
            dx, dy = point[0] - centre[0], point[1] - centre[1]
            side = ("left" if dx < 0 else "right") if abs(dx) >= abs(dy) else ("top" if dy < 0 else "bottom")
            component["terminal_candidates"].append(
                {
                    "point": {
                        "top_left_pt": [rnd(v) for v in point],
                        "pdf_bl_pt": segment["p1_pdf_bl"] if point == segment["p1"] else segment["p2_pdf_bl"],
                        "easyeda": segment["p1_easyeda"] if point == segment["p1"] else segment["p2_easyeda"],
                        "local_easyeda": scale_point([point[0] - bbox[0], point[1] - bbox[1]], PT_TO_EASYEDA),
                    },
                    "side": side,
                    "adjacent_nets": [segment["net"]],
                    "no_connect": False,
                    "touches_wire": True,
                    "graphic_radial_distance_pt": rnd(math.hypot(dx, dy)),
                    "component_centre_distance_pt": rnd(math.hypot(dx, dy)),
                    "line_count_at_endpoint": 0,
                    "line_colours": [],
                    "fallback": "wire_endpoint_inside_component_bbox",
                }
            )
            existing.add(key)  # type: ignore[arg-type]


def complete_physical_pin_groups(
    pages: list[dict[str, Any]], gerber_components: dict[str, Any]
) -> dict[str, Any]:
    groups: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for page in pages:
        for component in page["components"]:
            if not component["is_power_symbol"]:
                add_wire_endpoint_fallbacks(component, page)
                groups[component["base_reference"]].append((page, component))

    group_results: list[dict[str, Any]] = []
    for base_reference, page_components in sorted(groups.items(), key=lambda item: natural_pin_key(item[0])):
        manifest_component = gerber_components.get(base_reference)
        if not manifest_component:
            result = {
                "base_reference": base_reference,
                "status": "missing_gerber_component",
                "expected_pad_count": None,
            }
            group_results.append(result)
            for _, component in page_components:
                component["pin_validation"] = result
            continue

        pads: dict[str, dict[str, Any]] = manifest_component.get("pads") or {}
        expected_numbers = set(pads)
        assigned_by_component: dict[int, set[tuple[float, float]]] = {
            id(component): set() for _, component in page_components
        }
        final_by_component: dict[int, list[dict[str, Any]]] = {
            id(component): [] for _, component in page_components
        }
        mapped_numbers: set[str] = set()

        # First retain the exact, visible pin-number extraction (MCU, SDRAM,
        # connectors and most ICs).  Geometry-only false positives are dropped.
        for _, component in page_components:
            seen_local: set[str] = set()
            for old_pin in component.get("pins", []):
                number = old_pin.get("number")
                if number not in expected_numbers or number in mapped_numbers or number in seen_local:
                    continue
                candidate = candidate_for_existing_pin(component, old_pin)
                pin = make_pin_from_candidate(
                    number,
                    pads[number],
                    candidate,
                    "hidden_text_and_pin_stroke",
                    dnp=component["dnp"],
                )
                if old_pin.get("name"):
                    pin["name"] = old_pin["name"]
                if old_pin.get("line"):
                    pin["line"] = old_pin["line"]
                final_by_component[id(component)].append(pin)
                mapped_numbers.add(number)
                seen_local.add(number)
                if candidate:
                    assigned_by_component[id(component)].add(candidate_point_key(candidate))

        # Hidden red pin-number words recover rotated/offset symbols for which
        # the initial side-based detector did not identify a pin line.
        for _, component in page_components:
            for word in unique_pin_number_words(component, expected_numbers - mapped_numbers):
                number = word["text"]
                if number in mapped_numbers:
                    continue
                candidate = choose_candidate_near_word(
                    component, word, pads[number], assigned_by_component[id(component)]
                )
                if candidate is None and not old_pad_is_unconnected(pads[number]):
                    continue
                pin = make_pin_from_candidate(
                    number,
                    pads[number],
                    candidate,
                    "hidden_pin_number_nearest_terminal",
                    dnp=component["dnp"],
                    hidden=candidate is None,
                )
                final_by_component[id(component)].append(pin)
                mapped_numbers.add(number)
                if candidate:
                    assigned_by_component[id(component)].add(candidate_point_key(candidate))

        # For passives whose pin numbers are hidden, the Gerber X2 pad net is
        # joined to the exact current-PDF net-tagged terminal.
        for number in sorted(expected_numbers - mapped_numbers, key=natural_pin_key):
            match = choose_candidate_for_old_net(
                [component for _, component in page_components],
                pads[number],
                assigned_by_component,
            )
            if match is None:
                continue
            component, candidate = match
            pin = make_pin_from_candidate(
                number,
                pads[number],
                candidate,
                "gerber_pad_net_to_exact_pdf_net_terminal",
                dnp=component["dnp"],
            )
            final_by_component[id(component)].append(pin)
            mapped_numbers.add(number)
            assigned_by_component[id(component)].add(candidate_point_key(candidate))

        # Disconnected DNP two-terminal symbols are grey and crossed out in the
        # PDF.  Their two farthest grey terminal endpoints give an exact symbol
        # location; numbering uses the standard left/top -> 1 convention because
        # neither terminal participates in the netlist.
        if len(page_components) == 1:
            _, component = page_components[0]
            remaining = sorted(expected_numbers - mapped_numbers, key=natural_pin_key)
            if component["dnp"] and remaining:
                selected = select_two_terminal_candidates(
                    component, len(remaining), assigned_by_component[id(component)]
                )
                for number, candidate in zip(remaining, selected):
                    pin = make_pin_from_candidate(
                        number,
                        pads[number],
                        candidate,
                        "two_terminal_orientation",
                        dnp=True,
                    )
                    final_by_component[id(component)].append(pin)
                    mapped_numbers.add(number)
                    assigned_by_component[id(component)].add(candidate_point_key(candidate))

        # Intrinsic N/C pads intentionally omitted from the drawn KiCad symbol
        # (for example USB-C A8/B8 and transformer N/C pads) become hidden native
        # pins so the EasyEDA device still matches every footprint pad.
        for number in sorted(expected_numbers - mapped_numbers, key=natural_pin_key):
            if not old_pad_is_unconnected(pads[number]):
                continue
            # Prefer the sole component; multi-unit devices already expose all
            # numbered balls and should not normally reach this branch.
            component = page_components[0][1]
            pin = make_pin_from_candidate(
                number,
                pads[number],
                None,
                "hidden_intrinsic_nc_footprint_pad",
                dnp=component["dnp"],
                hidden=True,
            )
            final_by_component[id(component)].append(pin)
            mapped_numbers.add(number)

        # A final geometry fallback is restricted to one physical component and
        # consumes only still-unassigned terminals.  This handles a latest-sheet
        # net rename while retaining exact PDF endpoint coordinates.
        if len(page_components) == 1:
            _, component = page_components[0]
            remaining = sorted(expected_numbers - mapped_numbers, key=natural_pin_key)
            selected = select_two_terminal_candidates(
                component, len(remaining), assigned_by_component[id(component)]
            )
            for number, candidate in zip(remaining, selected):
                pin = make_pin_from_candidate(
                    number,
                    pads[number],
                    candidate,
                    "remaining_exact_symbol_terminal",
                    dnp=component["dnp"],
                )
                final_by_component[id(component)].append(pin)
                mapped_numbers.add(number)
                assigned_by_component[id(component)].add(candidate_point_key(candidate))

        numbers = [
            pin["number"]
            for _, component in page_components
            for pin in final_by_component[id(component)]
        ]
        duplicate_numbers = sorted(number for number, count in Counter(numbers).items() if count > 1)
        missing_numbers = sorted(expected_numbers - set(numbers), key=natural_pin_key)
        extra_numbers = sorted(set(numbers) - expected_numbers, key=natural_pin_key)
        status = "complete" if not (duplicate_numbers or missing_numbers or extra_numbers) else "incomplete"
        result = {
            "base_reference": base_reference,
            "status": status,
            "expected_pad_count": len(expected_numbers),
            "extracted_pin_count": len(numbers),
            "expected_pad_numbers": sorted(expected_numbers, key=natural_pin_key),
            "missing_pad_numbers": missing_numbers,
            "extra_pin_numbers": extra_numbers,
            "duplicate_pin_numbers": duplicate_numbers,
            "gerber_revision": manifest_component.get("gerberRevision"),
        }
        group_results.append(result)
        for _, component in page_components:
            component["pins_initial_geometry"] = component.get("pins", [])
            component["pins"] = sorted(final_by_component[id(component)], key=lambda pin: natural_pin_key(pin["number"]))
            component["pin_validation"] = result
            component["footprint_pad_count"] = len(expected_numbers)

    complete = [result for result in group_results if result["status"] == "complete"]
    incomplete = [result for result in group_results if result["status"] != "complete"]
    return {
        "physical_component_group_count": len(group_results),
        "complete_group_count": len(complete),
        "incomplete_group_count": len(incomplete),
        "incomplete_groups": incomplete,
        "groups": group_results,
    }


def complete_power_symbol_pins(pages: list[dict[str, Any]]) -> dict[str, Any]:
    incomplete: list[dict[str, Any]] = []
    total = 0
    for page in pages:
        for component in page["components"]:
            if not component["is_power_symbol"]:
                continue
            total += 1
            add_wire_endpoint_fallbacks(component, page)
            target = None if component["value"] == "PWR_FLAG" else normalise_net_name(component["value"])
            choices: list[tuple[float, dict[str, Any]]] = []
            for candidate in component.get("terminal_candidates", []):
                nets = candidate.get("adjacent_nets") or []
                if not nets:
                    continue
                if target is not None and not any(normalise_net_name(net) == target for net in nets):
                    continue
                score = float(candidate.get("component_centre_distance_pt", 0.0))
                choices.append((score, candidate))
            if choices:
                candidate = min(choices, key=lambda item: item[0])[1]
                adjacent = list(candidate.get("adjacent_nets") or [])
                net = next((net for net in adjacent if normalise_net_name(net) == target), None)
                if net is None and len(adjacent) == 1:
                    net = adjacent[0]
                provenance = "power_symbol_value_to_exact_pdf_net_terminal"
            elif component.get("terminal_candidates") and target is not None:
                # KiCad can connect a power symbol directly to a component pin
                # without drawing a green wire.  Ground-style symbols connect at
                # their top extremum; upward supply symbols connect at the bottom.
                candidates = component["terminal_candidates"]
                ground_style = "GND" in component["value"].upper() or "EARTH" in component["value"].upper()
                candidate = (
                    min(candidates, key=lambda item: item["point"]["top_left_pt"][1])
                    if ground_style
                    else max(candidates, key=lambda item: item["point"]["top_left_pt"][1])
                )
                adjacent = []
                net = component["value"]
                provenance = "power_symbol_intrinsic_net_at_direct_pin_terminal"
            else:
                candidate = None

            if candidate is not None:
                pin = {
                    "number": "1",
                    "name": component["value"],
                    "side": candidate.get("side"),
                    "connection": candidate["point"],
                    "line": None,
                    "net": net,
                    "adjacent_nets": adjacent,
                    "no_connect": False,
                    "intrinsic_nc_pin": False,
                    "hidden": False,
                    "electrical_state": "connected",
                    "confidence": "high",
                    "provenance": provenance,
                }
                component["pins_initial_geometry"] = component.get("pins", [])
                component["pins"] = [pin]
                component["pin_validation"] = {
                    "status": "complete",
                    "expected_pad_count": 1,
                    "extracted_pin_count": 1,
                    "missing_pad_numbers": [],
                }
            else:
                component["pins_initial_geometry"] = component.get("pins", [])
                component["pins"] = []
                result = {
                    "pdf_page": page["pdf_page"],
                    "reference": component["reference"],
                    "value": component["value"],
                    "status": "incomplete",
                    "expected_pad_count": 1,
                    "extracted_pin_count": 0,
                    "missing_pad_numbers": ["1"],
                }
                component["pin_validation"] = result
                incomplete.append(result)
    return {
        "power_symbol_count": total,
        "complete_power_symbol_count": total - len(incomplete),
        "incomplete_power_symbol_count": len(incomplete),
        "incomplete_power_symbols": incomplete,
    }


def propagate_direct_power_nets(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Propagate net names across exact co-located power/component pins."""

    power_nodes: dict[tuple[int, tuple[float, float]], str] = {}
    for page in pages:
        for component in page["components"]:
            if not component["is_power_symbol"]:
                continue
            for pin in component.get("pins", []):
                connection = pin.get("connection") or {}
                key = point_key(connection.get("top_left_pt"))
                if key is not None and pin.get("net"):
                    power_nodes[(page["pdf_page"], key)] = pin["net"]

    updated: list[dict[str, Any]] = []
    for page in pages:
        for component in page["components"]:
            if component["is_power_symbol"]:
                continue
            for pin in component.get("pins", []):
                if pin.get("net"):
                    continue
                connection = pin.get("connection") or {}
                key = point_key(connection.get("top_left_pt"))
                if key is None:
                    continue
                net = power_nodes.get((page["pdf_page"], key))
                if not net:
                    continue
                pin["net"] = net
                pin["adjacent_nets"] = [net]
                pin["electrical_state"] = "connected"
                pin["direct_power_symbol_net"] = True
                pin["provenance"] = f"{pin.get('provenance', 'pin')}+coincident_power_symbol"
                updated.append(
                    {
                        "pdf_page": page["pdf_page"],
                        "reference": component["reference"],
                        "pin": pin["number"],
                        "net": net,
                        "point_top_left_pt": list(key),
                    }
                )
    return {"updated_pin_count": len(updated), "updated_pins": updated}


def refresh_page_pin_summaries(pages: list[dict[str, Any]]) -> None:
    for page in pages:
        pins = [pin for component in page["components"] for pin in component.get("pins", [])]
        page["summary"].update(
            {
                "pin_instance_count": len(pins),
                "pins_with_number": sum(bool(pin.get("number")) for pin in pins),
                "pins_with_number_and_name": sum(bool(pin.get("number") and pin.get("name")) for pin in pins),
                "pins_with_net": sum(bool(pin.get("net")) for pin in pins),
                "pins_with_no_connect_marker": sum(bool(pin.get("no_connect")) for pin in pins),
                "hidden_intrinsic_nc_pins": sum(bool(pin.get("hidden") and pin.get("intrinsic_nc_pin")) for pin in pins),
                "components_with_incomplete_pin_validation": sum(
                    component.get("pin_validation", {}).get("status") != "complete"
                    for component in page["components"]
                ),
            }
        )


def extract(source: Path, gerber_manifest_path: Path) -> dict[str, Any]:
    reader = PdfReader(source)
    if len(reader.pages) < 6:
        raise ValueError(f"Expected the 6-page authoritative PDF, found {len(reader.pages)} pages")

    outlines = extract_outlines(reader)
    catalog = reader.trailer["/Root"]
    names = catalog.get("/Names") or {}
    javascript_names = names.get("/JavaScript") if hasattr(names, "get") else None
    js_init: list[dict[str, str]] = []
    if javascript_names:
        tree = javascript_names.get_object()
        raw_names = list(tree.get("/Names") or [])
        for i in range(0, len(raw_names), 2):
            name = str(raw_names[i])
            action = raw_names[i + 1].get_object()
            js_init.append({"name": name, "javascript": decode_pdf_js(action.get("/JS"))})

    with pdfplumber.open(source) as plumber_pdf:
        pages = [
            extract_page(reader, plumber_pdf.pages[page_number - 1], page_number, outlines.get(page_number, []))
            for page_number in range(2, 7)
        ]

    if not gerber_manifest_path.is_file():
        raise FileNotFoundError(
            f"Gerber component/pad manifest is required for strict pin completion: {gerber_manifest_path}"
        )
    gerber_manifest = json.loads(gerber_manifest_path.read_text(encoding="utf-8"))
    physical_validation = complete_physical_pin_groups(
        pages, gerber_manifest.get("components") or {}
    )
    power_validation = complete_power_symbol_pins(pages)
    direct_power_propagation = propagate_direct_power_nets(pages)
    refresh_page_pin_summaries(pages)
    unresolved_electrical_pins: list[dict[str, Any]] = []
    allowed_terminal_states = {"connected", "no_connect_marker", "intrinsic_nc", "dnp_disconnected"}
    for page in pages:
        for component in page["components"]:
            for pin in component.get("pins", []):
                state = pin.get("electrical_state")
                invalid = state not in allowed_terminal_states or (state == "connected" and not pin.get("net"))
                if invalid:
                    unresolved_electrical_pins.append(
                        {
                            "pdf_page": page["pdf_page"],
                            "reference": component["reference"],
                            "pin": pin.get("number"),
                            "state": state,
                            "net": pin.get("net"),
                        }
                    )
    strict_complete = (
        physical_validation["incomplete_group_count"] == 0
        and power_validation["incomplete_power_symbol_count"] == 0
        and not unresolved_electrical_pins
    )

    return {
        "schema": "techlabs-kicad-pdf-semantic-extraction-v1",
        "source": {
            "path": str(source.resolve()),
            "filename": source.name,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "authoritative_pdf_pages": 6,
            "included_pdf_pages": [2, 3, 4, 5, 6],
            "deleted_cover_page": 1,
        },
        "gerber_pad_authority": {
            "path": str(gerber_manifest_path.resolve()),
            "filename": gerber_manifest_path.name,
            "sha256": hashlib.sha256(gerber_manifest_path.read_bytes()).hexdigest(),
            "schema_version": gerber_manifest.get("schemaVersion"),
            "role": "footprint pad-number/count authority; current PDF remains net/geometry authority",
        },
        "coordinate_system": {
            "pdf_bl_pt": "PDF points, origin bottom-left",
            "top_left_pt": "PDF points, origin top-left",
            "top_left_mm": "millimetres, origin top-left",
            "easyeda": "top-left coordinates at 100 units/inch; value = PDF pt * 100/72",
            "annotation_line_padding_pt": ANNOTATION_PAD_PT,
            "geometry_match_tolerance_pt": COORD_TOLERANCE_PT,
        },
        "semantic_authority": [
            "per-annotation /A /JS ShM payloads for exact component fields and exact net/bus identity",
            "PDF outline FitR destinations and component annotation rectangles for instance extents",
            "hidden Tr=3 Helvetica text for reference/value/pin name/pin number placement",
            "colour-coded vector geometry for pins, wires, buses, junctions and no-connect marks",
        ],
        "suppression": {
            "company_text_pattern": TECHLABS_RE.pattern,
            "note": "TECHLABS/CO.,LTD words are excluded from text_words for the requested redraw; source PDF is unchanged.",
        },
        "catalog_javascript": js_init,
        "pages": pages,
        "strict_pin_validation": {
            "status": "complete" if strict_complete else "incomplete",
            "physical_components": physical_validation,
            "power_symbols": power_validation,
            "direct_power_propagation": direct_power_propagation,
            "electrical_connectivity": {
                "status": "complete" if not unresolved_electrical_pins else "incomplete",
                "unresolved_pin_count": len(unresolved_electrical_pins),
                "unresolved_pins": unresolved_electrical_pins,
                "allowed_terminal_states": sorted(allowed_terminal_states),
            },
        },
        "validation_required": [
            "Create real EasyEDA components/pins/nets from this data; do not flatten to vectors.",
            "Audit every pin/net on each sheet and run ERC before PCB conversion.",
            "Treat bus-entry member propagation as inferred from an exact shared endpoint.",
            "Compare PCB only after the five-sheet schematic and its netlist are validated.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gerber-manifest", type=Path, default=DEFAULT_GERBER_MANIFEST)
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_file():
        parser.error(f"Source PDF does not exist: {source}")

    gerber_manifest = args.gerber_manifest.resolve()
    data = extract(source, gerber_manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    for page in data["pages"]:
        summary = page["summary"]
        print(
            f"p{page['pdf_page']}->{page['new_sheet_index']} {page['sheet_name']}: "
            f"components={summary['component_count']} nets={summary['unique_net_count']} "
            f"wires={summary['wire_segment_count']} pins={summary['pin_instance_count']} "
            f"pin_nets={summary['pins_with_net']} NC={summary['no_connect_count']}"
        )
    validation = data["strict_pin_validation"]
    print(
        "strict pins:",
        validation["status"],
        f"physical incomplete={validation['physical_components']['incomplete_group_count']}",
        f"power incomplete={validation['power_symbols']['incomplete_power_symbol_count']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
