#!/usr/bin/env python3
"""Render native EasyEDA SVG exports on the PDF page canvas and compare pixels.

This is a visual QA helper only.  It does not edit the native schematic or the
source PDF.  The exported SVGs include a content bounding-box margin; for an
apples-to-apples comparison we render the fixed A3 page canvas at exactly the
same 3307 x 2339 pixels as the checked-in 200 dpi PDF reference PNGs.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import argparse
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
SVG_DIR = ROOT / "output" / "validation" / "native-svg"
REFERENCE_DIR = ROOT / "reference" / "schematic-pages" / "v19_260827"
SEMANTIC_PATH = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
REPORT_PATH = ROOT / "output" / "validation" / "native-svg-pixel-qa.json"
NORMALIZED_DIR = SVG_DIR / "normalized"
RENDERED_DIR = SVG_DIR / "rendered"
DIFF_DIR = SVG_DIR / "diff"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

PAGE_WIDTH_EASYEDA = 1653.5
PAGE_HEIGHT_EASYEDA = 1169.3
RASTER_WIDTH = 3307
RASTER_HEIGHT = 2339

# The one repeated PDF image was independently decoded and confirmed to be
# entirely the requested-to-remove TECHLABS mark/tagline/company block.
TECHLABS_IMAGE_TOP_LEFT_PT = [969.048, 737.112024, 1035.048024, 753.912]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_root_viewport(source: str) -> str:
    match = re.search(r"<svg\b[^>]*>", source, flags=re.IGNORECASE)
    if not match:
        raise ValueError("SVG root element not found")
    tag = match.group(0)
    replacements = {
        "width": str(RASTER_WIDTH),
        "height": str(RASTER_HEIGHT),
        "viewBox": f"0 0 {PAGE_WIDTH_EASYEDA} {PAGE_HEIGHT_EASYEDA}",
    }
    for name, value in replacements.items():
        pattern = rf'\b{name}="[^"]*"'
        if re.search(pattern, tag, flags=re.IGNORECASE):
            tag = re.sub(pattern, f'{name}="{value}"', tag, count=1, flags=re.IGNORECASE)
        else:
            tag = tag[:-1] + f' {name}="{value}">'
    return source[: match.start()] + tag + source[match.end() :]


def render_svg(svg_path: Path, png_path: Path) -> None:
    args = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        f"--window-size={RASTER_WIDTH},{RASTER_HEIGHT}",
        f"--screenshot={png_path}",
        svg_path.resolve().as_uri(),
    ]
    with tempfile.TemporaryDirectory(prefix="stm32-svg-qa-", dir=ROOT / "tmp") as profile:
        args.insert(2, f"--user-data-dir={profile}")
        completed = subprocess.run(
            args, capture_output=True, text=True, timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Chrome SVG render failed ({completed.returncode}): "
            f"{completed.stderr[-2000:]}"
        )
    with Image.open(png_path) as image:
        if image.size != (RASTER_WIDTH, RASTER_HEIGHT):
            raise ValueError(f"Unexpected render size {image.size} for {png_path}")


def bbox_easyeda_to_pixels(bbox: list[float], margin: int = 8) -> tuple[int, int, int, int]:
    sx = RASTER_WIDTH / PAGE_WIDTH_EASYEDA
    sy = RASTER_HEIGHT / PAGE_HEIGHT_EASYEDA
    x0, y0, x1, y1 = bbox
    return (
        max(0, int(np.floor(x0 * sx)) - margin),
        max(0, int(np.floor(y0 * sy)) - margin),
        min(RASTER_WIDTH, int(np.ceil(x1 * sx)) + margin),
        min(RASTER_HEIGHT, int(np.ceil(y1 * sy)) + margin),
    )


def techlabs_mask(page: dict) -> tuple[np.ndarray, list[list[int]]]:
    mask = np.zeros((RASTER_HEIGHT, RASTER_WIDTH), dtype=bool)
    boxes: list[list[int]] = []

    # PDF point coordinates and EasyEDA coordinates share the same top-left
    # orientation; the semantic transform is exactly 100/72.
    factor = 100.0 / 72.0
    image_box = [value * factor for value in TECHLABS_IMAGE_TOP_LEFT_PT]
    source_boxes = [image_box]
    source_boxes.extend(
        list(item["bbox"]["easyeda"])
        for item in page.get("suppressed_company_text_words", [])
    )
    for source_box in source_boxes:
        pixel_box = bbox_easyeda_to_pixels(source_box)
        x0, y0, x1, y1 = pixel_box
        mask[y0:y1, x0:x1] = True
        boxes.append(list(pixel_box))
    return mask, boxes


def dilated(mask: np.ndarray, tolerance: int) -> np.ndarray:
    if tolerance <= 0:
        return mask
    image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    expanded = image.filter(ImageFilter.MaxFilter(tolerance * 2 + 1))
    return np.asarray(expanded) > 0


def match_stats(reference: np.ndarray, candidate: np.ndarray, tolerance: int = 3) -> dict:
    ref_count = int(reference.sum())
    candidate_count = int(candidate.sum())
    candidate_match = int((candidate & dilated(reference, tolerance)).sum())
    reference_match = int((reference & dilated(candidate, tolerance)).sum())
    return {
        "reference_pixels": ref_count,
        "candidate_pixels": candidate_count,
        "precision_within_tolerance": candidate_match / candidate_count if candidate_count else 1.0,
        "recall_within_tolerance": reference_match / ref_count if ref_count else 1.0,
        "tolerance_px": tolerance,
    }


def color_masks(rgb: np.ndarray, ignored: np.ndarray) -> dict[str, np.ndarray]:
    values = rgb.astype(np.int16)
    red, green, blue = values[:, :, 0], values[:, :, 1], values[:, :, 2]
    chroma = values.max(axis=2) - values.min(axis=2)
    nonwhite = values.min(axis=2) < 242
    masks = {
        "all_nonwhite": nonwhite,
        "green": (green > 55) & (green > red * 1.20 + 8) & (green > blue * 1.20 + 8),
        "red": (red > 55) & (red > green * 1.20 + 8) & (red > blue * 1.20 + 8),
        "blue": (blue > 55) & (blue > red * 1.20 + 8) & (blue > green * 1.20 + 8),
        "magenta": (red > 55) & (blue > 55) & (green * 1.25 + 8 < np.minimum(red, blue)),
        "teal": (green > 55) & (blue > 55) & (red * 1.25 + 8 < np.minimum(green, blue)),
        "neutral_dark": (values.max(axis=2) < 160) & (chroma < 35),
    }
    return {name: mask & ~ignored for name, mask in masks.items()}


def make_diff(
    reference_image: Image.Image,
    reference_mask: np.ndarray,
    candidate_mask: np.ndarray,
    ignored: np.ndarray,
    path: Path,
) -> None:
    base = np.asarray(reference_image.convert("RGB")).astype(np.float32)
    gray = np.mean(base, axis=2, keepdims=True)
    canvas = np.repeat(gray, 3, axis=2) * 0.22 + 198.0
    missing = reference_mask & ~dilated(candidate_mask, 3) & ~ignored
    extra = candidate_mask & ~dilated(reference_mask, 3) & ~ignored
    overlap = reference_mask & dilated(candidate_mask, 3) & ~ignored
    canvas[overlap] = [70, 70, 70]
    canvas[missing] = [255, 0, 0]
    canvas[extra] = [0, 170, 255]
    canvas[ignored] = [255, 240, 160]
    Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8), mode="RGB").save(path)


def make_side_by_side(reference: Image.Image, candidate: Image.Image, path: Path) -> None:
    target_width = 1200
    target_height = round(RASTER_HEIGHT * target_width / RASTER_WIDTH)
    left = reference.convert("RGB").resize((target_width, target_height), Image.Resampling.LANCZOS)
    right = candidate.convert("RGB").resize((target_width, target_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (target_width * 2, target_height), "white")
    canvas.paste(left, (0, 0))
    canvas.paste(right, (target_width, 0))
    canvas.save(path)


def main() -> None:
    global SVG_DIR, REPORT_PATH, NORMALIZED_DIR, RENDERED_DIR, DIFF_DIR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg-dir", type=Path, default=SVG_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    arguments = parser.parse_args()
    SVG_DIR = arguments.svg_dir.resolve()
    REPORT_PATH = arguments.report.resolve()
    for output in (SVG_DIR, REPORT_PATH):
        if not output.is_relative_to(ROOT):
            raise SystemExit(f"QA path must remain within STM32H747 scope: {output}")
    NORMALIZED_DIR = SVG_DIR / "normalized"
    RENDERED_DIR = SVG_DIR / "rendered"
    DIFF_DIR = SVG_DIR / "diff"
    (ROOT / "tmp").mkdir(exist_ok=True)
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    semantic = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    pages = {int(page["pdf_page"]): page for page in semantic["pages"]}
    svg_paths = sorted(path for path in SVG_DIR.glob("*.svg") if path.is_file())
    if len(svg_paths) != 5:
        raise SystemExit(f"Expected five exported SVG files, found {len(svg_paths)}")
    for directory in (NORMALIZED_DIR, RENDERED_DIR, DIFF_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    report_pages = []
    for offset, svg_path in enumerate(svg_paths, start=2):
        page = pages[offset]
        normalized_path = NORMALIZED_DIR / f"page-{offset}.svg"
        rendered_path = RENDERED_DIR / f"page-{offset}.png"
        diff_path = DIFF_DIR / f"page-{offset}-geometry-diff.png"
        side_by_side_path = DIFF_DIR / f"page-{offset}-side-by-side.png"
        normalized_path.write_text(
            replace_root_viewport(svg_path.read_text(encoding="utf-8")),
            encoding="utf-8",
            newline="\n",
        )
        render_svg(normalized_path, rendered_path)

        reference_path = REFERENCE_DIR / f"page-{offset}.png"
        with Image.open(reference_path) as reference_open, Image.open(rendered_path) as candidate_open:
            reference = reference_open.convert("RGB")
            candidate = candidate_open.convert("RGB")
            if reference.size != (RASTER_WIDTH, RASTER_HEIGHT):
                raise ValueError(f"Unexpected reference size {reference.size}: {reference_path}")
            ignored, ignored_boxes = techlabs_mask(page)
            reference_array = np.asarray(reference)
            candidate_array = np.asarray(candidate)
            reference_masks = color_masks(reference_array, ignored)
            candidate_masks = color_masks(candidate_array, ignored)
            categories = {
                name: match_stats(reference_masks[name], candidate_masks[name])
                for name in reference_masks
            }
            valid = ~ignored
            absolute = np.abs(reference_array.astype(np.int16) - candidate_array.astype(np.int16))
            rgb_mae = float(absolute[valid].mean())
            changed = np.any(absolute > 24, axis=2) & valid
            make_diff(
                reference,
                reference_masks["all_nonwhite"],
                candidate_masks["all_nonwhite"],
                ignored,
                diff_path,
            )
            make_side_by_side(reference, candidate, side_by_side_path)

        report_pages.append(
            {
                "pdf_page": offset,
                "source_svg": {
                    "path": str(svg_path.relative_to(ROOT)),
                    "sha256": sha256(svg_path),
                },
                "normalized_svg": str(normalized_path.relative_to(ROOT)),
                "rendered_png": str(rendered_path.relative_to(ROOT)),
                "reference_png": str(reference_path.relative_to(ROOT)),
                "geometry_diff_png": str(diff_path.relative_to(ROOT)),
                "side_by_side_png": str(side_by_side_path.relative_to(ROOT)),
                "techlabs_ignored_pixel_boxes": ignored_boxes,
                "pixel_metrics_outside_techlabs": {
                    "rgb_mean_absolute_error": rgb_mae,
                    "fraction_pixels_rgb_delta_gt_24": float(changed.sum() / valid.sum()),
                    "color_geometry": categories,
                },
            }
        )

    report = {
        "schema": "stm32h747-native-svg-pixel-qa-v1",
        "status": "rendered_for_visual_review",
        "comparison": {
            "page_canvas_easyeda": [PAGE_WIDTH_EASYEDA, PAGE_HEIGHT_EASYEDA],
            "raster_pixels": [RASTER_WIDTH, RASTER_HEIGHT],
            "native_svg_normalization": "Crop the EasyEDA export content bounds to the exact A3 page canvas 0,0,1653.5,1169.3 without modifying drawing primitives.",
            "reference": "Latest v19 PDF pages 2-6 rendered at 200 dpi",
            "ignored_difference": "Only the repeated TECHLABS raster mark/tagline/company image and TECHLABS/CO.,LTD word boxes requested for removal, each with an 8 px antialias margin.",
            "geometry_metric": "Bidirectional binary-mask coverage within 3 px, calculated separately by color family.",
        },
        "sources": {
            "semantic": {
                "path": str(SEMANTIC_PATH.relative_to(ROOT)),
                "sha256": sha256(SEMANTIC_PATH),
            }
        },
        "pages": report_pages,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"report": str(REPORT_PATH), "sha256": sha256(REPORT_PATH)}, indent=2))


if __name__ == "__main__":
    main()
