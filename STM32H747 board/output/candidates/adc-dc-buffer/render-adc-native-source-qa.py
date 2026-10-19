"""Render saved schematic source and saved project symbols for offline visual QA.

This is a transparent source renderer, not an EasyEDA native SVG export. It
does not modify source or operate any editor. Coordinates and vector paths
come directly from the reopened page and checkpoint library documents.
"""
import hashlib
import argparse
import html
import json
import math
import runpy
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "output/validation/native-adc-dc-final-reopened-20261016.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_adc_dc_schematic_saved_20261016.epro2"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
GEN = runpy.run_path(str(ROOT / "scripts/build-adc-dc-libraries.py"))
QA = runpy.run_path(str(HERE / "independent-static-adc-plan-review.py"))
COUNTS = Counter()
WARN = []


def esc(value):
    return html.escape(str(value), quote=True)


def num(value, default=0):
    return default if value is None else value


def text(body, value=None):
    if body.get("x") is None or body.get("y") is None:
        return ""
    size = num(body.get("fontSize"), 5.5)
    if size < 0.1:
        return ""
    content = body.get("value", "") if value is None else value
    if not content:
        return ""
    align = body.get("align", "LEFT_BOTTOM") or "LEFT_BOTTOM"
    anchor = "middle" if align.startswith("CENTER") else "end" if align.startswith("RIGHT") else "start"
    baseline = "hanging" if align.endswith("TOP") else "central" if align.endswith("MIDDLE") else "alphabetic"
    angle = -num(body.get("rotation"))
    x, y = body["x"], body["y"]
    color = body.get("color") or "#000080"
    COUNTS["text"] += 1
    return f'<text x="{x}" y="{y}" transform="rotate({angle} {x} {y})" font-family="{esc(body.get("fontFamily") or "Arial")}" font-size="{size}" fill="{esc(color)}" text-anchor="{anchor}" dominant-baseline="{baseline}" font-weight="{"bold" if body.get("fontWeight") else "normal"}" font-style="{"italic" if body.get("italic") else "normal"}">{esc(content)}</text>'


def draw(kind, body, *, library=False):
    if kind == "POLY":
        points = body.get("points", [])
        if points and isinstance(points[0], dict):
            coords = [(p["x"], p["y"]) for p in points]
        else:
            coords = list(zip(points[::2], points[1::2]))
        if not coords:
            return ""
        tag = "polygon" if body.get("closed") else "polyline"
        fill, stroke = body.get("fillColor") or "none", body.get("strokeColor") or "none"
        width = num(body.get("strokeWidth"), 0.6)
        COUNTS["poly"] += 1
        return f'<{tag} points="{" ".join(f"{x},{y}" for x,y in coords)}" fill="{esc(fill)}" stroke="{esc(stroke)}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'
    if kind == "LINE":
        COUNTS["line"] += 1
        return f'<line x1="{body["startX"]}" y1="{body["startY"]}" x2="{body["endX"]}" y2="{body["endY"]}" stroke="{esc(body.get("strokeColor") or "#009600")}" stroke-width="{num(body.get("strokeWidth"),0.6)}"/>'
    if kind == "RECT":
        x1, y1, x2, y2 = [body.get(k) for k in ("dotX1", "dotY1", "dotX2", "dotY2")]
        if None not in (x1, y1, x2, y2):
            return f'<rect x="{min(x1,x2)}" y="{min(y1,y2)}" width="{abs(x2-x1)}" height="{abs(y2-y1)}" stroke="{esc(body.get("strokeColor") or "none")}" stroke-width="{num(body.get("strokeWidth"),.6)}" fill="{esc(body.get("fillColor") or "none")}"/>'
        WARN.append({"kind": kind, "reason": "unrecognized rectangle", "body": body})
    if kind == "PIN" and body.get("display"):
        x, y, length = body["x"], body["y"], body["length"]
        # PIN rotation points inward in local Y-down source coordinates.
        theta = math.radians(num(body.get("rotation")))
        return f'<line x1="{x}" y1="{y}" x2="{x+length*math.cos(theta)}" y2="{y+length*math.sin(theta)}" stroke="{esc(body.get("color") or "#840000")}" stroke-width="0.6"/>'
    if kind == "TEXT":
        return text(body)
    if kind == "ATTR" and body.get("valueVisible"):
        if library and not body.get("parentId"):
            return ""
        return text(body)
    if kind not in {"DOCHEAD", "META", "PART", "CANVAS", "ATTR", "PIN", "COMPONENT", "WIRE", "RECT", "POLY", "LINE"}:
        WARN.append({"kind": kind, "reason": "not rendered"})
    return ""


def main():
    global SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--tag", default="adc-saved")
    args = parser.parse_args()
    SOURCE = args.source.resolve()
    tag = args.tag
    rows = QA["parse"](SOURCE)
    libraries = GEN["read_checkpoint"](CHECKPOINT)
    attrs = defaultdict(dict)
    for (kind, rid), body in rows.items():
        if kind == "ATTR":
            attrs[body["parentId"]][body["key"]] = body["value"]
    elements = []
    missing_symbols = []
    for (kind, rid), body in sorted(rows.items(), key=lambda item: num(item[1].get("zIndex"))):
        if kind == "COMPONENT":
            symbol = attrs[rid].get("Symbol")
            document = libraries.get(("SYMBOL", symbol))
            if document is None:
                missing_symbols.append({"id": rid, "symbol": symbol, "ref": attrs[rid].get("Designator")})
                continue
            part = body.get("partId", "A")
            items = [(h, b) for h, b in document.values() if isinstance(b, dict) and (not b.get("partId") or b.get("partId") == part)]
            output = "".join(draw(h["type"], b, library=True) for h, b in sorted(items, key=lambda item: num(item[1].get("zIndex"))))
            elements.append(f'<g data-component="{esc(attrs[rid].get("Designator",rid))}" transform="translate({body["x"]} {body["y"]}) rotate({-num(body.get("rotation"))}) scale({-1 if body.get("isMirror") else 1} 1)">{output}</g>')
        else:
            elements.append(draw(kind, body))
    content = "".join(elements)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="3307" height="2339" viewBox="0 0 1653.5 1169.5"><rect x="0" y="0" width="1653.5" height="1169.5" fill="white"/>{content}</svg>'
    svg_path, png_path = HERE / f"{tag}-source-visual-qa.svg", HERE / f"{tag}-source-visual-qa.png"
    svg_path.write_text(svg, encoding="utf8")
    with tempfile.TemporaryDirectory(prefix="adc-svg-render-", dir=HERE) as profile:
        result = subprocess.run([str(CHROME), "--headless=new", f"--user-data-dir={profile}", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=3307,2339", f"--screenshot={png_path}", svg_path.resolve().as_uri()], capture_output=True, text=True, timeout=55, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        if result.returncode:
            raise RuntimeError(result.stderr[-1500:])
    crops = {f"{tag}-input-chains": (100, 110, 1220, 290),
             f"{tag}-reference-context": (980, 710, 1450, 865),
             f"{tag}-three-buffers": (110, 810, 520, 1120),
             f"{tag}-lower-context": (90, 695, 1480, 1125)}
    with Image.open(png_path) as image:
        for label, box in crops.items():
            image.crop(tuple(round(n*2) for n in box)).save(HERE / (label + ".png"))
    report = {"sourcePath": str(SOURCE), "sourceSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
              "checkpointPath": str(CHECKPOINT), "renderer": "independent source/SVG renderer, NOT native EasyEDA export",
              "pageRecords": len(rows), "missingSymbols": missing_symbols, "drawn": dict(COUNTS), "unsupportedPrimitives": WARN,
              "svgPath": str(svg_path), "pngPath": str(png_path), "crops": {k: list(v) for k,v in crops.items()},
              "manualVisualReviewPending": True, "manufacturingApproval": False}
    (HERE / f"{tag}-source-visual-qa.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"sourceSha256": report["sourceSha256"], "missingSymbols": missing_symbols, "unsupported": len(WARN), "svgPath": str(svg_path), "pngPath": str(png_path)}, indent=2))


if __name__ == "__main__":
    main()
