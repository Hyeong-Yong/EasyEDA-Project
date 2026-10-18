#!/usr/bin/env python3
"""Simulate strictly visual native-SVG repairs for pixel QA.

The script never changes an EasyEDA source.  It removes diagnosed SVG-only
overlays and corrects the renderer-default outline on component-owned filled
POLYs so the expected effect can be measured before the native source is
patched and re-exported.
"""

from __future__ import annotations

import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "output" / "validation" / "native-svg-overlay-repair-plan.json"
SEMANTIC_PATH = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
SOURCE_DIR = ROOT / "output" / "validation" / "native-svg"
OUTPUT_DIR = SOURCE_DIR / "simulated-repair"
REPORT_PATH = ROOT / "output" / "validation" / "native-svg-simulated-repair-qa.json"


def load_qa_module():
    path = ROOT / "scripts" / "qa-native-svg.py"
    spec = importlib.util.spec_from_file_location("qa_native_svg", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_component_ids(path: Path) -> set[str]:
    result: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "||" not in raw:
            continue
        head_raw = raw.split("||", 1)[0]
        head = json.loads(head_raw)
        if head.get("type") == "COMPONENT" and head.get("id"):
            result.add(str(head["id"]))
    return result


def is_component_child(identity: str | None, component_ids: set[str]) -> bool:
    if not identity or "-" not in identity:
        return False
    return identity.split("-", 1)[0] in component_ids


def patch_svg(source_path: Path, destination_path: Path, component_ids: set[str], company_ids: set[str]) -> dict:
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
    tree = ET.parse(source_path)
    root = tree.getroot()
    parent = {child: node for node in root.iter() for child in node}
    tiny_net_text = 0
    zero_length_pin_bars = 0
    removed_company = 0
    fill_only_default_strokes_zeroed = 0

    for element in list(root.iter()):
        tag = element.tag.rsplit("}", 1)[-1]
        identity = element.get("id")
        owner = parent.get(element)
        if owner is None:
            continue
        if tag == "text":
            style = element.get("style") or ""
            element.set("style", re.sub(r"font-size:[^;]+", "font-size:0.001px", style, count=1))
            tiny_net_text += 1
            continue
        if identity in company_ids:
            owner.remove(element)
            removed_company += 1
            continue
        if tag == "g" and element.get("c_partid") == "part_pin" and is_component_child(identity, component_ids):
            for child in element:
                if child.tag.rsplit("}", 1)[-1] == "path" and child.get("class") == "pin-bar":
                    child.set("d", re.sub(r"\b([hv])\s+-?[0-9.]+", r"\1 0", child.get("d") or "", count=1))
                    zero_length_pin_bars += 1
            continue
        if tag != "polyline" or not is_component_child(identity, component_ids):
            continue
        style = element.get("style") or ""
        if "stroke-width:1;stroke:#A00000;" not in style or "fill:none" in style:
            continue
        fill_match = re.search(r"fill:(#[0-9A-Fa-f]{6})", style)
        updated = re.sub(r"stroke-width:1(?=;)", "stroke-width:0.001", style, count=1)
        if fill_match:
            updated = re.sub(r"stroke:#A00000(?=;)", f"stroke:{fill_match.group(1)}", updated, count=1)
        element.set("style", updated)
        fill_only_default_strokes_zeroed += 1

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination_path, encoding="utf-8", xml_declaration=False)
    return {
        "source": str(source_path.relative_to(ROOT)),
        "simulated_svg": str(destination_path.relative_to(ROOT)),
        "net_text_nodes_font_size_0_001": tiny_net_text,
        "native_pin_bars_length_zero": zero_length_pin_bars,
        "removed_company_glyph_polys": removed_company,
        "fill_only_default_strokes_tiny_same_fill": fill_only_default_strokes_zeroed,
    }


def crop_pair(reference: Image.Image, candidate: Image.Image, easyeda_box: list[float], path: Path) -> None:
    sx = reference.width / 1653.5
    sy = reference.height / 1169.3
    x0, y0, x1, y1 = easyeda_box
    pixel_box = (round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy))
    left = reference.convert("RGB").crop(pixel_box)
    right = candidate.convert("RGB").crop(pixel_box)
    maximum = 1200
    if left.width > maximum:
        height = round(left.height * maximum / left.width)
        left = left.resize((maximum, height), Image.Resampling.LANCZOS)
        right = right.resize((maximum, height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (left.width * 2, left.height), "white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (left.width, 0))
    canvas.save(path)


def main() -> None:
    qa = load_qa_module()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    semantic = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    semantic_pages = {int(page["pdf_page"]): page for page in semantic["pages"]}
    plan_pages = {int(page["pdf_page"]): page for page in plan["pages"]}
    svg_paths = sorted(path for path in SOURCE_DIR.glob("*.svg") if path.is_file())
    if len(svg_paths) != 5:
        raise SystemExit(f"Expected five source SVG files, found {len(svg_paths)}")
    for name in ("source", "normalized", "rendered", "diff", "crop"):
        (OUTPUT_DIR / name).mkdir(parents=True, exist_ok=True)

    dense_boxes = {
        2: [350, 115, 900, 875],
        3: [330, 130, 1080, 940],
        4: [170, 120, 1470, 930],
        5: [120, 90, 1510, 950],
        6: [120, 90, 1510, 950],
    }
    results = []
    for page, source_path in zip(range(2, 7), svg_paths, strict=True):
        durable_path = ROOT / "output" / "validation" / f"native-durable-page-{page}.epru"
        component_ids = parse_component_ids(durable_path)
        company_ids = set(plan_pages[page]["strict_company_repair"]["target_ids"])
        patched_path = OUTPUT_DIR / "source" / f"page-{page}.svg"
        mutation = patch_svg(source_path, patched_path, component_ids, company_ids)

        normalized_path = OUTPUT_DIR / "normalized" / f"page-{page}.svg"
        normalized_path.write_text(
            qa.replace_root_viewport(patched_path.read_text(encoding="utf-8")),
            encoding="utf-8",
            newline="\n",
        )
        rendered_path = OUTPUT_DIR / "rendered" / f"page-{page}.png"
        qa.render_svg(normalized_path, rendered_path)
        reference_path = ROOT / "reference" / "schematic-pages" / "v19_260827" / f"page-{page}.png"
        diff_path = OUTPUT_DIR / "diff" / f"page-{page}-geometry-diff.png"
        pair_path = OUTPUT_DIR / "diff" / f"page-{page}-side-by-side.png"
        crop_path = OUTPUT_DIR / "crop" / f"page-{page}-dense-crop-pair.png"
        with Image.open(reference_path) as reference_open, Image.open(rendered_path) as candidate_open:
            reference = reference_open.convert("RGB")
            candidate = candidate_open.convert("RGB")
            ignored, ignored_boxes = qa.techlabs_mask(semantic_pages[page])
            reference_array = np.asarray(reference)
            candidate_array = np.asarray(candidate)
            reference_masks = qa.color_masks(reference_array, ignored)
            candidate_masks = qa.color_masks(candidate_array, ignored)
            categories = {
                name: qa.match_stats(reference_masks[name], candidate_masks[name])
                for name in reference_masks
            }
            valid = ~ignored
            absolute = np.abs(reference_array.astype(np.int16) - candidate_array.astype(np.int16))
            changed = np.any(absolute > 24, axis=2) & valid
            qa.make_diff(
                reference,
                reference_masks["all_nonwhite"],
                candidate_masks["all_nonwhite"],
                ignored,
                diff_path,
            )
            qa.make_side_by_side(reference, candidate, pair_path)
            crop_pair(reference, candidate, dense_boxes[page], crop_path)
            metrics = {
                "rgb_mae": float(absolute[valid].mean()),
                "rgb_changed_fraction_gt_24": float(changed.sum() / valid.sum()),
                "categories": categories,
            }
        results.append(
            {
                "pdf_page": page,
                "mutation": mutation,
                "rendered_png": str(rendered_path.relative_to(ROOT)),
                "geometry_diff_png": str(diff_path.relative_to(ROOT)),
                "side_by_side_png": str(pair_path.relative_to(ROOT)),
                "dense_crop_pair_png": str(crop_path.relative_to(ROOT)),
                "techlabs_ignored_pixel_boxes": ignored_boxes,
                "pixel_metrics_outside_techlabs": metrics,
            }
        )

    report = {
        "schema": "stm32h747-native-svg-simulated-repair-qa-v1",
        "status": "visual simulation only; native source not modified",
        "repair_plan": str(PLAN_PATH.relative_to(ROOT)),
        "simulation_limits": [
            "The simulation applies the renderer-equivalent tiny NET font, zero PIN length, and tiny same-fill POLY stroke; native persistence still requires an actual pilot.",
            "Final acceptance requires a fresh SVG exported from the repaired EasyEDA native source plus ERC/netlist checks.",
        ],
        "pages": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(REPORT_PATH),
                "pages": [
                    {
                        "page": item["pdf_page"],
                        **item["mutation"],
                        "all_nonwhite": item["pixel_metrics_outside_techlabs"]["categories"]["all_nonwhite"],
                    }
                    for item in results
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
