#!/usr/bin/env python3
"""Attribute visual-only overlays in native schematic SVG exports.

This diagnostic is intentionally read-only with respect to the PDF and native
EasyEDA sources.  It emits a strict repair plan containing only stable native
IDs and PDF vector draw orders; applying the plan remains a separate step.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from extract_page1_vectors import extract_vectors


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_PATH = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
LIBRARY_MANIFEST_PATH = ROOT / "output" / "native-libraries" / "manifest.json"
NATIVE_DIR = ROOT / "output" / "validation"
SVG_DIR = NATIVE_DIR / "native-svg"
OUTPUT_PATH = NATIVE_DIR / "native-svg-overlay-repair-plan.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(label: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, "stm32h747-native/" + label).hex[:16]


def parse_epru(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "||" not in raw:
            continue
        head_raw, body_raw = raw.split("||", 1)
        body_raw = body_raw[:-1] if body_raw.endswith("|") else body_raw
        try:
            head = json.loads(head_raw)
            body = json.loads(body_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed EPRU record at {path}:{line_number}") from exc
        records.append({"line": line_number, "head": head, "body": body})
    return records


def intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def contained(a: list[float], b: list[float], epsilon: float = 0.0) -> bool:
    return (
        a[0] >= b[0] - epsilon
        and a[1] >= b[1] - epsilon
        and a[2] <= b[2] + epsilon
        and a[3] <= b[3] + epsilon
    )


def union_box(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def vector_entry(page: int, vector: dict[str, Any]) -> dict[str, Any]:
    count = len(vector.get("subpaths") or [])
    return {
        "draw_order": int(vector["draw_order"]),
        "bounds_pt_top_left": vector["bounds_pt_top_left"],
        "geometry": vector.get("geometry"),
        "fill": bool(vector.get("fill")),
        "stroke": bool(vector.get("stroke")),
        "fill_hex": vector.get("fill_hex"),
        "stroke_hex": vector.get("stroke_hex"),
        "line_width_pt": vector.get("line_width_pt"),
        "subpath_count": count,
        "native_poly_ids": [stable_id(f"{page}/vector/{vector['draw_order']}/{index}") for index in range(count)],
    }


def svg_text_inventory(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    texts = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "text":
            continue
        value = "".join(element.itertext())
        texts.append(
            {
                "id": element.get("id"),
                "value": value,
                "x": element.get("x"),
                "y": element.get("y"),
                "style": element.get("style"),
            }
        )
    colors = Counter()
    for item in texts:
        style = item.get("style") or ""
        marker = "fill:"
        color = style.split(marker, 1)[1].split(";", 1)[0] if marker in style else ""
        colors[color] += 1
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "literal_text_count": len(texts),
        "literal_text_color_counts": dict(sorted(colors.items())),
        "literal_text_ids": [item["id"] for item in texts],
        "samples": texts[:20],
        "note": (
            "The PDF-visible text is retained as POLY outlines. Every SVG <text> node is therefore a native "
            "overlay, currently dominated by auto-visible WIRE/NET attributes."
        ),
    }


def native_page_inventory(page: int, path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    records = parse_epru(path)
    record_types = {
        str(record["head"].get("id")): str(record["head"].get("type"))
        for record in records if record["head"].get("id") is not None
    }
    wire_ids = {record["head"].get("id") for record in records if record["head"].get("type") == "WIRE"}
    net_attrs = []
    for record in records:
        head, body = record["head"], record["body"]
        if head.get("type") != "ATTR" or body.get("parentId") not in wire_ids or body.get("key") != "NET":
            continue
        net_attrs.append(
            {
                "id": head.get("id"),
                "parent_wire_id": body.get("parentId"),
                "net": body.get("value"),
                "valueVisible": body.get("valueVisible"),
                "line": record["line"],
            }
        )
    visible = [item for item in net_attrs if item["valueVisible"] is True]
    result = {
        "pdf_page": page,
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "wire_count": len(wire_ids),
        "wire_net_attr_count": len(net_attrs),
        "visible_wire_net_attr_count": len(visible),
        "visible_wire_net_attrs": visible,
        "strict_repair": {
            "operation": "set ATTR.fontSize to a tiny positive 0.001 while preserving the NET value",
            "target_ids": [item["id"] for item in visible],
            "preconditions": {
                "type": "ATTR",
                "parent_type": "WIRE",
                "key": "NET",
                "current_valueVisible": True,
            },
            "runtime_constraint": (
                "EasyEDA correctNetNamesValueVisibleForOnes144542() forces ordinary WIRE net-name ATTRs visible "
                "again during applySource/init; fontSize=0 also falls back to 10, so 0.001 is the durable pilot."
            ),
            "forbidden_changes": ["ATTR.value", "WIRE", "LINE", "COMPONENT", "PIN", "POLY"],
        },
    }
    return result, record_types


def main() -> None:
    semantic = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    library = json.loads(LIBRARY_MANIFEST_PATH.read_text(encoding="utf-8"))
    pdf_path = ROOT / "보드 자료" / "MCU_BOARD_v19_260827.pdf"
    reader = PdfReader(str(pdf_path))
    svg_paths = sorted(SVG_DIR.glob("*.svg"))
    if len(svg_paths) != 5:
        raise SystemExit(f"Expected five SVG exports, found {len(svg_paths)}")

    page_results = []
    all_company_orders: set[int] | None = None
    for page_data, svg_path in zip(semantic["pages"], svg_paths, strict=True):
        page = int(page_data["pdf_page"])
        vectors, images = extract_vectors(reader, page - 1)
        word_boxes = [item["bbox"]["top_left_pt"] for item in page_data["suppressed_company_text_words"]]
        words_union = union_box(word_boxes)
        # The visible glyph outlines sit slightly above the invisible searchable
        # text boxes.  The narrow title-band window is bounded well away from
        # the frame rules at y=734.18 and y=766.58 pt.
        company_band = [min(box[0] for box in word_boxes) - 1.0, 738.0, max(box[2] for box in word_boxes) + 1.0, 754.5]
        overlapping = [vector for vector in vectors if intersects(vector["bounds_pt_top_left"], company_band)]
        candidates = [
            vector for vector in overlapping
            if (vector.get("fill_hex") or "").upper() == "#840000"
            and contained(vector["bounds_pt_top_left"], company_band, epsilon=0.01)
        ]
        orders = {int(vector["draw_order"]) for vector in candidates}
        all_company_orders = orders if all_company_orders is None else all_company_orders & orders

        durable_path = NATIVE_DIR / f"native-durable-page-{page}.epru"
        native, durable_record_types = native_page_inventory(page, durable_path)
        candidate_entries = [vector_entry(page, vector) for vector in candidates]
        for entry in candidate_entries:
            present_ids = [
                identity for identity in entry["native_poly_ids"]
                if durable_record_types.get(identity) == "POLY"
            ]
            entry["durable_present_poly_ids"] = present_ids
            entry["durable_absent_poly_ids"] = [
                identity for identity in entry["native_poly_ids"] if identity not in present_ids
            ]
        native["svg"] = svg_text_inventory(svg_path)
        page_results.append(
            {
                "pdf_page": page,
                "pdf_vector_count": len(vectors),
                "pdf_image_count": len(images),
                "company_word_boxes_pt_top_left": word_boxes,
                "company_words_union_pt_top_left": words_union,
                "company_glyph_search_band_pt_top_left": company_band,
                "company_band_overlapping_vectors": [vector_entry(page, vector) for vector in overlapping],
                "company_glyph_candidates": candidate_entries,
                "strict_company_repair": {
                    "operation": "remove only currently present POLY records",
                    "target_ids": [
                        identity for entry in candidate_entries for identity in entry["durable_present_poly_ids"]
                    ],
                    "already_absent_ids": [
                        identity for entry in candidate_entries for identity in entry["durable_absent_poly_ids"]
                    ],
                    "preconditions": {
                        "type": "POLY",
                        "draw_orders": [int(vector["draw_order"]) for vector in candidates],
                        "fill_hex": "#840000",
                        "bounds_fully_inside_company_band": True,
                    },
                    "forbidden_changes": ["frame POLY draw_order 1-3", "title-block rules", "other title text"],
                },
                "native": native,
            }
        )

    visual_vector_count = sum(
        len(part.get("owned_vector_orders") or [])
        for symbol in library["symbols"].values()
        for part in (symbol.get("part_transforms") or {}).values()
    )
    pin_count = sum(len(symbol.get("pins") or []) for symbol in library["symbols"].values())
    report = {
        "schema": "stm32h747-native-svg-overlay-repair-plan-v1",
        "status": "diagnosed-not-applied",
        "inputs": {
            "pdf": {"path": str(pdf_path.relative_to(ROOT)), "sha256": sha256(pdf_path)},
            "semantic": {"path": str(SEMANTIC_PATH.relative_to(ROOT)), "sha256": sha256(SEMANTIC_PATH)},
            "library_manifest": {
                "path": str(LIBRARY_MANIFEST_PATH.relative_to(ROOT)),
                "sha256": sha256(LIBRARY_MANIFEST_PATH),
            },
        },
        "diagnosis": {
            "wire_net_overlay": (
                "Runtime/API persistence changed WIRE NET ATTR valueVisible from false to true. The SVG text nodes "
                "are additional to the preserved PDF glyph POLYs. Plain valueVisible=false is not durable because "
                "correctNetNamesValueVisibleForOnes144542() forces it true; use a tiny positive font size without "
                "changing NET values."
            ),
            "component_symbol_styling": (
                "Component-owned PDF fill-only POLYs were emitted with strokeWidth=null. In a SYMBOL document the "
                "native renderer supplies its default 1-unit #A00000 outline, producing bold/mixed-color glyphs and "
                "an extra border around filled shapes. Renderer basicStyle uses strokeWidth || 1, so zero also falls "
                "back to 1; fill-only POLYs require a tiny positive 0.001 strokeWidth (and preferably strokeColor "
                "equal to fillColor)."
            ),
            "native_pin_overlay": (
                "Each semantic PIN renders a native pin-bar on top of the already-preserved PDF red pin-line POLY. "
                "Keep PIN IDs and x/y electrical endpoints authoritative. PIN display=false is overwritten by the "
                "component parent; pilot schema-safe length=0 (renderer has no fallback for length) or color='none' "
                "if the native importer accepts it, while retaining the original PDF pin-line POLY."
            ),
            "company_glyphs": (
                "The old containment check used the invisible searchable word boxes and removed only two unrelated/" 
                "partial paths. Exact visible #840000 glyph vectors in the narrow company title band are enumerated."
            ),
        },
        "library_visual_overlap": {
            "component_owned_pdf_vector_count": visual_vector_count,
            "native_semantic_pin_count": pin_count,
            "required_generator_change": {
                "file": "scripts/build-native-libraries.py",
                "function": "add_symbol_pdf_vectors",
                "fill_only_poly": {"strokeWidth": 0.001, "strokeColor": "same as fillColor"},
                "semantic_pin_visual_pilot": {
                    "length": 0,
                    "preserve": ["id", "x", "y", "rotation", "Pin Name", "Pin Number", "Pin Type"],
                },
                "forbidden": ["pin IDs", "pin endpoints", "component placements", "nets", "devices", "footprints"],
            },
        },
        "company_vector_consistency": {
            "candidate_draw_orders_common_to_all_pages": sorted(all_company_orders or []),
            "expect_same_template_orders": len(all_company_orders or []) > 0,
        },
        "pages": page_results,
        "validation_contract": {
            "must_preserve": [
                "1057/1057 native Protel2 netlist match",
                "110 NC pins accounted",
                "all COMPONENT/PIN/WIRE/LINE IDs and geometry except explicitly listed visual fields",
            ],
            "rerun": [
                "native SVG export and scripts/qa-native-svg.py",
                "ERC",
                "scripts/verify-native-netlist.py",
            ],
        },
    }
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "sha256": sha256(OUTPUT_PATH),
                "pages": [
                    {
                        "page": item["pdf_page"],
                        "company_candidates": len(item["company_glyph_candidates"]),
                        "visible_wire_net_attrs": item["native"]["visible_wire_net_attr_count"],
                        "svg_text": item["native"]["svg"]["literal_text_count"],
                    }
                    for item in page_results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
