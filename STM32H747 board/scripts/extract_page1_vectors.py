"""Extract page 1 PDF drawing operators into EasyEDA-friendly vector JSON.

The source PDF is read only. Visible KiCad text is emitted in the PDF as filled
polygon outlines; the searchable Helvetica text uses PDF rendering mode 3 and
is therefore invisible. Both representations are retained so a caller can
choose pixel-faithful polygons or editable native text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any

import pdfplumber
from pypdf import PdfReader
from pypdf.generic import ContentStream


PT_TO_MM = 25.4 / 72.0


def matrix(values: list[float]) -> list[list[float]]:
    a, b, c, d, e, f = values
    return [[a, c, e], [b, d, f], [0.0, 0.0, 1.0]]


def matmul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [sum(left[row][k] * right[k][col] for k in range(3)) for col in range(3)]
        for row in range(3)
    ]


def transform(ctm: list[list[float]], x: float, y: float) -> tuple[float, float]:
    return (
        ctm[0][0] * x + ctm[0][1] * y + ctm[0][2],
        ctm[1][0] * x + ctm[1][1] * y + ctm[1][2],
    )


def rgb_hex(color: list[float] | tuple[float, ...] | None) -> str | None:
    if color is None or len(color) < 3:
        return None
    channels = [max(0, min(255, round(float(v) * 255))) for v in color[:3]]
    return "#" + "".join(f"{v:02X}" for v in channels)


def rounded(value: float, places: int = 9) -> float:
    return round(float(value), places)


def point_payload(x_pt: float, y_pt_bottom: float, page_height_pt: float) -> dict[str, list[float]]:
    y_pt_top = page_height_pt - y_pt_bottom
    return {
        "pt_top_left": [rounded(x_pt), rounded(y_pt_top)],
        "mm_top_left": [rounded(x_pt * PT_TO_MM, 6), rounded(y_pt_top * PT_TO_MM, 6)],
        "pt_pdf_bottom_left": [rounded(x_pt), rounded(y_pt_bottom)],
    }


def state_default() -> dict[str, Any]:
    return {
        "ctm": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        "stroke_rgb": [0.0, 0.0, 0.0],
        "fill_rgb": [0.0, 0.0, 0.0],
        "line_width_raw": 1.0,
        "line_cap": 0,
        "line_join": 0,
        "miter_limit": 10.0,
        "dash": [[], 0.0],
    }


def transformed_line_width(state: dict[str, Any]) -> float:
    ctm = state["ctm"]
    sx = math.hypot(ctm[0][0], ctm[1][0])
    sy = math.hypot(ctm[0][1], ctm[1][1])
    return float(state["line_width_raw"]) * (sx + sy) / 2.0


def semantic_group(bounds_top: list[float], fill_hex: str | None, stroke_hex: str | None) -> str:
    x0, top, x1, bottom = bounds_top
    color = fill_hex or stroke_hex
    if color == "#0000C2":
        if 270 <= top and bottom <= 320:
            return "center_title.mcu_board"
        if 315 <= top and bottom <= 365:
            return "center_title.revision"
        if 330 <= top and bottom <= 490:
            centers = [
                (358.2, 441.0, "hierarchy.mcu_1"),
                (468.0, 550.8, "hierarchy.mcu_2"),
                (572.4, 655.2, "hierarchy.memory"),
                (673.2, 756.0, "hierarchy.enet_usb_vcp"),
                (774.0, 856.8, "hierarchy.adc_tim_spi"),
            ]
            cx = (x0 + x1) / 2.0
            for left, right, name in centers:
                if left - 2 <= cx <= right + 2:
                    return name
        if x0 >= 960 and top >= 730:
            return "title_block.blue_text"
        return "blue_visible_text"
    if color == "#FFFFC2":
        return "hierarchy.sheet_fill"
    if color == "#840000":
        if x0 >= 960 and top >= 730:
            return "title_block.red_text_or_rule"
        if x0 <= 40 or x1 >= 1150 or top <= 40 or bottom >= 805:
            return "drawing_frame.zone_labels_or_rule"
        return "drawing_frame_or_title_block"
    return "other"


def bounds_for_subpaths(subpaths: list[dict[str, Any]]) -> list[float]:
    points: list[tuple[float, float]] = []
    for subpath in subpaths:
        for segment in subpath["segments"]:
            if segment["op"] == "M" or segment["op"] == "L":
                points.append(tuple(segment["pt_pdf_bottom_left"]))
            elif segment["op"] == "C":
                points.extend(tuple(p) for p in segment["pt_pdf_bottom_left"])
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def top_bounds(native_bounds: list[float], page_height_pt: float) -> list[float]:
    x0, y0, x1, y1 = native_bounds
    return [x0, page_height_pt - y1, x1, page_height_pt - y0]


def classify_geometry(subpaths: list[dict[str, Any]], fill: bool, stroke: bool) -> str:
    if len(subpaths) != 1:
        return "compound_path"
    segments = subpaths[0]["segments"]
    ops = [s["op"] for s in segments]
    if "C" in ops:
        return "bezier"
    points = [s["pt_pdf_bottom_left"] for s in segments if s["op"] in ("M", "L")]
    if not fill and stroke and len(points) == 2:
        return "line"
    unique = []
    for p in points:
        if p not in unique:
            unique.append(p)
    if len(unique) == 4:
        xs = sorted({rounded(p[0], 6) for p in unique})
        ys = sorted({rounded(p[1], 6) for p in unique})
        if len(xs) == 2 and len(ys) == 2:
            return "rectangle"
    return "polygon"


def serialize_subpaths(
    raw_subpaths: list[dict[str, Any]], page_height_pt: float
) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for raw in raw_subpaths:
        segments = []
        for segment in raw["segments"]:
            op = segment["op"]
            if op in ("M", "L"):
                x, y = segment["points"][0]
                payload = point_payload(x, y, page_height_pt)
                segments.append({"op": op, **payload})
            elif op == "C":
                pdf_points = segment["points"]
                segments.append(
                    {
                        "op": "C",
                        "pt_pdf_bottom_left": [
                            [rounded(x), rounded(y)] for x, y in pdf_points
                        ],
                        "pt_top_left": [
                            [rounded(x), rounded(page_height_pt - y)] for x, y in pdf_points
                        ],
                        "mm_top_left": [
                            [rounded(x * PT_TO_MM, 6), rounded((page_height_pt - y) * PT_TO_MM, 6)]
                            for x, y in pdf_points
                        ],
                    }
                )
        serialized.append({"closed": bool(raw["closed"]), "segments": segments})
    return serialized


def extract_vectors(reader: PdfReader, page_index: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    page = reader.pages[page_index]
    page_height_pt = float(page.mediabox.height)
    content = ContentStream(page.get_contents(), reader)
    state = state_default()
    stack: list[dict[str, Any]] = []
    current_subpaths: list[dict[str, Any]] = []
    current_subpath: dict[str, Any] | None = None
    vectors: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    draw_order = 0

    def start_subpath(x: float, y: float) -> None:
        nonlocal current_subpath
        tx, ty = transform(state["ctm"], x, y)
        current_subpath = {"closed": False, "segments": [{"op": "M", "points": [(tx, ty)]}]}
        current_subpaths.append(current_subpath)

    def add_line(x: float, y: float) -> None:
        if current_subpath is None:
            raise RuntimeError("PDF line operator without an active subpath")
        tx, ty = transform(state["ctm"], x, y)
        current_subpath["segments"].append({"op": "L", "points": [(tx, ty)]})

    def add_curve(points: list[tuple[float, float]]) -> None:
        if current_subpath is None:
            raise RuntimeError("PDF curve operator without an active subpath")
        transformed = [transform(state["ctm"], x, y) for x, y in points]
        current_subpath["segments"].append({"op": "C", "points": transformed})

    def current_point() -> tuple[float, float]:
        if current_subpath is None:
            raise RuntimeError("No active subpath")
        segment = current_subpath["segments"][-1]
        return tuple(segment["points"][-1])

    def emit(fill: bool, stroke: bool, evenodd: bool, close: bool = False) -> None:
        nonlocal current_subpaths, current_subpath, draw_order
        if close and current_subpath is not None:
            current_subpath["closed"] = True
        if not current_subpaths:
            return
        native_bounds = bounds_for_subpaths(
            [
                {
                    "closed": p["closed"],
                    "segments": [
                        {
                            "op": s["op"],
                            "pt_pdf_bottom_left": (
                                [list(point) for point in s["points"]]
                                if s["op"] == "C"
                                else list(s["points"][0])
                            ),
                        }
                        for s in p["segments"]
                    ],
                }
                for p in current_subpaths
            ]
        )
        bounds_top_pt = top_bounds(native_bounds, page_height_pt)
        fill_hex = rgb_hex(state["fill_rgb"]) if fill else None
        stroke_hex = rgb_hex(state["stroke_rgb"]) if stroke else None
        serialized = serialize_subpaths(current_subpaths, page_height_pt)
        vectors.append(
            {
                "draw_order": draw_order,
                "geometry": classify_geometry(serialized, fill, stroke),
                "semantic_group": semantic_group(bounds_top_pt, fill_hex, stroke_hex),
                "fill": fill,
                "fill_rule": "evenodd" if evenodd else "nonzero",
                "fill_rgb": [rounded(v, 6) for v in state["fill_rgb"]] if fill else None,
                "fill_hex": fill_hex,
                "stroke": stroke,
                "stroke_rgb": [rounded(v, 6) for v in state["stroke_rgb"]] if stroke else None,
                "stroke_hex": stroke_hex,
                "line_width_pt": rounded(transformed_line_width(state)),
                "line_width_mm": rounded(transformed_line_width(state) * PT_TO_MM, 6),
                "line_cap": state["line_cap"],
                "line_join": state["line_join"],
                "miter_limit": state["miter_limit"],
                "dash": state["dash"],
                "bounds_pt_top_left": [rounded(v) for v in bounds_top_pt],
                "bounds_mm_top_left": [rounded(v * PT_TO_MM, 6) for v in bounds_top_pt],
                "subpaths": serialized,
            }
        )
        draw_order += 1
        current_subpaths = []
        current_subpath = None

    for operands, operator_bytes in content.operations:
        op = operator_bytes.decode("latin1")
        numeric_ops = {"cm", "rg", "RG", "w", "J", "j", "M", "m", "l", "c", "v", "y", "re"}
        values = [float(v) for v in operands] if op in numeric_ops else []
        if op == "q":
            stack.append(deepcopy(state))
        elif op == "Q":
            state = stack.pop()
        elif op == "cm":
            state["ctm"] = matmul(state["ctm"], matrix(values))
        elif op == "rg":
            state["fill_rgb"] = values[:3]
        elif op == "RG":
            state["stroke_rgb"] = values[:3]
        elif op == "w":
            state["line_width_raw"] = values[0]
        elif op == "J":
            state["line_cap"] = int(values[0])
        elif op == "j":
            state["line_join"] = int(values[0])
        elif op == "M":
            state["miter_limit"] = values[0]
        elif op == "d":
            state["dash"] = [[float(v) for v in operands[0]], float(operands[1])]
        elif op == "m":
            start_subpath(values[0], values[1])
        elif op == "l":
            add_line(values[0], values[1])
        elif op == "c":
            add_curve([(values[0], values[1]), (values[2], values[3]), (values[4], values[5])])
        elif op == "v":
            cp = current_point()
            p2 = transform(state["ctm"], values[0], values[1])
            p3 = transform(state["ctm"], values[2], values[3])
            if current_subpath is None:
                raise RuntimeError("PDF v operator without an active subpath")
            current_subpath["segments"].append({"op": "C", "points": [cp, p2, p3]})
        elif op == "y":
            p1 = transform(state["ctm"], values[0], values[1])
            p3 = transform(state["ctm"], values[2], values[3])
            if current_subpath is None:
                raise RuntimeError("PDF y operator without an active subpath")
            current_subpath["segments"].append({"op": "C", "points": [p1, p3, p3]})
        elif op == "h":
            if current_subpath is not None:
                current_subpath["closed"] = True
        elif op == "re":
            x, y, width, height = values
            start_subpath(x, y)
            add_line(x + width, y)
            add_line(x + width, y + height)
            add_line(x, y + height)
            add_line(x, y)
            if current_subpath is not None:
                current_subpath["closed"] = True
        elif op == "S":
            emit(False, True, False)
        elif op == "s":
            emit(False, True, False, True)
        elif op in ("f", "F"):
            emit(True, False, False)
        elif op == "f*":
            emit(True, False, True)
        elif op == "B":
            emit(True, True, False)
        elif op == "B*":
            emit(True, True, True)
        elif op == "b":
            emit(True, True, False, True)
        elif op == "b*":
            emit(True, True, True, True)
        elif op == "n":
            current_subpaths = []
            current_subpath = None
        elif op == "Do":
            name = str(operands[0])
            xobjects = page["/Resources"].get("/XObject", {})
            xobj_ref = xobjects.get(operands[0])
            xobj = xobj_ref.get_object() if xobj_ref is not None else None
            if xobj is not None and str(xobj.get("/Subtype")) == "/Image":
                corners = [transform(state["ctm"], x, y) for x, y in [(0, 0), (1, 0), (1, 1), (0, 1)]]
                xs = [p[0] for p in corners]
                ys = [p[1] for p in corners]
                bounds = [min(xs), min(ys), max(xs), max(ys)]
                bounds_top_pt = top_bounds(bounds, page_height_pt)
                decoded = xobj.get_data()
                images.append(
                    {
                        "draw_order": draw_order,
                        "name": name,
                        "semantic_group": "title_block.logo",
                        "pixel_width": int(xobj.get("/Width")),
                        "pixel_height": int(xobj.get("/Height")),
                        "bits_per_component": int(xobj.get("/BitsPerComponent")),
                        "color_space": str(xobj.get("/ColorSpace")),
                        "filter": str(xobj.get("/Filter")),
                        "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
                        "bounds_pt_top_left": [rounded(v) for v in bounds_top_pt],
                        "bounds_mm_top_left": [rounded(v * PT_TO_MM, 6) for v in bounds_top_pt],
                        "ctm": [[rounded(v) for v in row] for row in state["ctm"]],
                        "note": "The source logo is a raster XObject, not a PDF vector path.",
                    }
                )
                draw_order += 1
    return vectors, images


def searchable_text(pdf_path: Path, page_index: int) -> list[dict[str, Any]]:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_index]
        words = page.extract_words(
            x_tolerance=1,
            y_tolerance=1,
            keep_blank_chars=False,
            extra_attrs=["fontname", "size", "stroking_color", "non_stroking_color"],
        )
    result = []
    for word in words:
        result.append(
            {
                "text": word["text"],
                "font": word["fontname"],
                "effective_size_pt": rounded(word["size"], 6),
                "effective_size_mm": rounded(word["size"] * PT_TO_MM, 6),
                "render_mode": 3,
                "visible_in_source": False,
                "fill_hex": rgb_hex(word.get("non_stroking_color")),
                "stroke_hex": rgb_hex(word.get("stroking_color")),
                "bounds_pt_top_left": [
                    rounded(word["x0"]),
                    rounded(word["top"]),
                    rounded(word["x1"]),
                    rounded(word["bottom"]),
                ],
                "bounds_mm_top_left": [
                    rounded(word["x0"] * PT_TO_MM, 6),
                    rounded(word["top"] * PT_TO_MM, 6),
                    rounded(word["x1"] * PT_TO_MM, 6),
                    rounded(word["bottom"] * PT_TO_MM, 6),
                ],
            }
        )
    return result


def annotations(reader: PdfReader, page_index: int) -> list[dict[str, Any]]:
    page = reader.pages[page_index]
    page_height_pt = float(page.mediabox.height)
    page_ids = {p.indirect_reference.idnum: i + 1 for i, p in enumerate(reader.pages)}
    annots_obj = page.get("/Annots")
    annots = annots_obj.get_object() if annots_obj is not None else []
    result = []
    for annot_ref in annots:
        annot = annot_ref.get_object()
        if str(annot.get("/Subtype")) != "/Link":
            continue
        rect = [float(v) for v in annot.get("/Rect")]
        dest = annot.get("/Dest")
        dest_page = None
        if dest and hasattr(dest[0], "idnum"):
            dest_page = page_ids.get(dest[0].idnum)
        bounds_top = top_bounds(rect, page_height_pt)
        result.append(
            {
                "bounds_pt_top_left": [rounded(v) for v in bounds_top],
                "bounds_mm_top_left": [rounded(v * PT_TO_MM, 6) for v in bounds_top],
                "destination_page": dest_page,
                "border": [float(v) for v in annot.get("/Border", [])],
            }
        )
    return result


def build_document(pdf_path: Path) -> dict[str, Any]:
    reader = PdfReader(str(pdf_path))
    page = reader.pages[0]
    width_pt = float(page.mediabox.width)
    height_pt = float(page.mediabox.height)
    vectors, images = extract_vectors(reader, 0)
    return {
        "schema": "easyeda-reference-vectors/v1",
        "source": {
            "path": str(pdf_path.resolve()),
            "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
            "page": 1,
            "producer": str(reader.metadata.producer),
            "creator": str(reader.metadata.creator),
        },
        "coordinate_system": {
            "preferred": "top-left",
            "units": ["pt", "mm"],
            "pt_to_mm": PT_TO_MM,
            "page_width_pt": width_pt,
            "page_height_pt": height_pt,
            "page_width_mm": rounded(width_pt * PT_TO_MM, 6),
            "page_height_mm": rounded(height_pt * PT_TO_MM, 6),
            "nominal_sheet": "A3 landscape, 420 x 297 mm",
            "pdf_native_origin": "bottom-left",
            "easyeda_schematic": {
                "unit": "10 mil = 0.254 mm = 0.72 pt",
                "origin": "bottom-left",
                "x_formula_from_mm_top_left": "x / 0.254",
                "y_formula_from_mm_top_left": "(297.0022 - y) / 0.254",
                "direct_formula_from_pt_pdf_bottom_left": "coordinate / 0.72",
                "source_frame_line_width_mil": 6.0,
                "recommended_polygon_line_width": 6,
            },
        },
        "palette": {
            "frame_and_title_red": "#840000",
            "schematic_blue": "#0000C2",
            "hierarchy_fill_yellow": "#FFFFC2",
            "background": "#FFFFFF",
        },
        "implementation_notes": [
            "All visible lettering except the embedded company logo is represented by filled PDF paths.",
            "The Helvetica text objects use rendering mode 3 and are invisible search/accessibility overlays.",
            "For pixel-faithful output, create native filled POLY/BEZIER objects from vectors in draw_order.",
            "For editable output, replace selected visible glyph paths with native TEXT using searchable_text bounds; Helvetica/Arial substitution can change glyph metrics.",
            "Do not place a raster image of the complete PDF page.",
            "The company logo is the only raster object in the source PDF; exact all-vector reconstruction requires a separate trace or original vector logo asset.",
        ],
        "layout": {
            "frame": {
                "outer_rect_mm_top_left": [10.0, 10.0, 409.989, 287.0022],
                "inner_rect_mm_top_left": [12.0, 12.0, 407.989, 285.0022],
                "line_width_pt": 0.432,
                "line_width_mm": 0.1524,
                "column_boundaries_mm": [12.0, 60.0, 110.0, 160.0, 210.0, 260.0, 310.0, 360.0, 407.989],
                "row_boundaries_mm_top_left": [12.0, 60.0, 110.0, 160.0, 210.0, 260.0, 285.0022],
            },
            "hierarchy_blocks": [
                {"label": "MCU#1", "target_page": 2, "sheet_name": "mcu", "rect_mm_top_left": [126.365, 128.27, 155.575, 175.895]},
                {"label": "MCU#2", "target_page": 3, "sheet_name": "mcu_vcc", "rect_mm_top_left": [165.1, 128.27, 194.31, 175.895]},
                {"label": "MEM", "target_page": 4, "sheet_name": "memory", "rect_mm_top_left": [201.93, 128.27, 231.14, 175.895]},
                {"label": "ENET / USB / VCP", "target_page": 5, "sheet_name": "enet", "rect_mm_top_left": [237.49, 128.27, 266.7, 175.895]},
                {"label": "ADC / TIM / SPI", "target_page": 6, "sheet_name": "adc", "rect_mm_top_left": [273.05, 128.27, 302.26, 175.895]},
            ],
            "title_block": {
                "outer_rect_mm_top_left": [339.989, 259.0022, 407.989, 285.0022],
                "horizontal_rules_y_mm_top_left": [267.0022, 272.0022, 277.0022, 282.0022],
                "vertical_rules": [
                    {"x_mm": 379.989, "y0_mm": 282.0022, "y1_mm": 285.0022},
                    {"x_mm": 397.989, "y0_mm": 277.0022, "y1_mm": 282.0022},
                ],
                "logo_image_bounds_mm_top_left": [341.8586, 260.036742, 365.141942, 265.9634],
            },
        },
        "vectors": vectors,
        "images": images,
        "searchable_text": searchable_text(pdf_path, 0),
        "link_annotations": annotations(reader, 0),
        "counts": {
            "vectors": len(vectors),
            "images": len(images),
            "searchable_words": len(searchable_text(pdf_path, 0)),
            "link_annotations": len(annotations(reader, 0)),
        },
    }


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_dir = script_dir.parent
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=project_dir / "보드 자료" / "MCU_BOARD_v19_260827.pdf",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_dir / "output" / "page1" / "reference-vectors.json",
    )
    args = parser.parse_args()
    document = build_document(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output.resolve())
    print(json.dumps(document["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
