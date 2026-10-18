"""Build an editable native EasyEDA page from the exact reference PDF vectors."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import uuid
import zipfile
from collections import Counter
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output" / "page1"
REFERENCE = OUTPUT / "reference-vectors.json"
NAME = "STM32H747_MCU_BOARD_v19"
FACTOR = 100.0 / 72.0


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def record(kind, value, identity=None, ticket=1):
    head = {"type": kind, "ticket": ticket}
    if identity is not None:
        head["id"] = identity
    return compact(head) + "||" + compact(value) + "|"


def ident(label):
    return uuid.uuid5(uuid.NAMESPACE_URL, "stm32h747-page1/" + label).hex[:16]


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reference = json.loads(REFERENCE.read_text(encoding="utf8"))
    reader = PdfReader(reference["source"]["path"])
    page = reader.pages[0]
    width = reference["coordinate_system"]["page_width_pt"]
    height = reference["coordinate_system"]["page_height_pt"]
    width_units, height_units = width * FACTOR, height * FACTOR
    schematic_id = ident("schematic")
    page_id = ident("page-01")
    client_id = ident("client")
    timestamp = int(time.time() * 1000)
    log = []
    log.append(record("DOCHEAD", {"docType": "SCH", "uuid": schematic_id, "client": client_id, "updateTime": timestamp, "version": str(timestamp), "user": {"uuid": schematic_id}}))
    log.append(record("META", {"title": "MCU_BOARD", "name": "MCU_BOARD", "board": "", "source": "", "zIndex": 1}, "META"))
    log.append(record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": page_id, "client": client_id, "updateTime": timestamp, "version": str(timestamp), "user": {"uuid": page_id}}))
    log.append(record("META", {"title": "01_HIERARCHY", "name": "01_HIERARCHY", "schematic": schematic_id, "description": "Exact vector reconstruction of MCU_BOARD_v19_260827.pdf page 1. Other circuit pages have not yet been created.", "source": "", "zIndex": 1, "sort": 1, "showTitleBlock": False}, "META"))
    log.append(record("CANVAS", {"originX": 0, "originY": 0, "gridType": "NONE", "unit": "mm"}, "CANVAS"))
    groups = sorted({v["semantic_group"] for v in reference["vectors"]} | {"title_block.logo", "paper"})
    group_ids = {name: ident("group/" + name) for name in groups}
    for group_name, group_id in group_ids.items():
        log.append(record("GROUP", {"groupId": group_id, "parentId": "0", "title": group_name}, group_id))
    log.append(record("RECT", {"partId": "", "groupId": group_ids["paper"], "locked": True, "zIndex": -100, "dotX1": 0, "dotY1": height_units, "dotX2": width_units, "dotY2": 0, "radiusX": 0, "radiusY": 0, "rotation": 0, "strokeColor": "", "strokeStyle": 0, "fillColor": "#FFFFFF", "strokeWidth": 0, "fillStyle": 1}, ident("paper")))
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="419.989mm" height="297.0022mm" viewBox="0 0 {width} {height}">', '<rect width="100%" height="100%" fill="white"/>']
    events = [(v["draw_order"], "vector", v) for v in reference["vectors"]] + [(v["draw_order"], "image", v) for v in reference["images"]]
    native_counts = Counter()
    for order, kind, value in sorted(events, key=lambda e: e[0]):
        if kind == "image":
            xobject = page["/Resources"]["/XObject"][value["name"]].get_object()
            image = Image.frombytes("RGB", (value["pixel_width"], value["pixel_height"]), xobject.get_data())
            image_stream = io.BytesIO()
            image.save(image_stream, format="PNG")
            image_bytes = image_stream.getvalue()
            (OUTPUT / "techlabs-logo.png").write_bytes(image_bytes)
            content = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
            x0, y0, x1, y1 = value["bounds_pt_top_left"]
            log.append(record("OBJ", {"partId": "", "groupId": group_ids[value["semantic_group"]], "locked": False, "zIndex": order, "fileName": "techlabs-logo.png", "startX": x0 * FACTOR, "startY": (height - y0) * FACTOR, "width": (x1-x0) * FACTOR, "height": (y1-y0) * FACTOR, "rotation": 0, "isMirror": False, "content": content}, ident(f"image/{order}")))
            svg.append(f'<image x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" xlink:href="{content}"/>')
            native_counts["OBJ"] += 1
            continue
        subpaths = value["subpaths"]
        if len(subpaths) != 1:
            raise ValueError("Compound path conversion must be implemented explicitly.")
        points = []
        svg_commands = []
        for segment in subpaths[0]["segments"]:
            if segment["op"] not in ("M", "L"):
                raise ValueError("Unexpected curve in the page 1 reference.")
            px, py = segment["pt_pdf_bottom_left"]
            tx, ty = segment["pt_top_left"]
            points.extend([round(px * FACTOR, 8), round(py * FACTOR, 8)])
            svg_commands.append(f'{segment["op"]}{tx},{ty}')
        if subpaths[0]["closed"]:
            svg_commands.append("Z")
        stroke = value["stroke_hex"] or ""
        fill = value["fill_hex"] or ""
        if value["geometry"] == "rectangle":
            xs, ys = points[::2], points[1::2]
            body = {"partId": "", "groupId": group_ids[value["semantic_group"]], "locked": False, "zIndex": order, "dotX1": min(xs), "dotY1": max(ys), "dotX2": max(xs), "dotY2": min(ys), "radiusX": 0, "radiusY": 0, "rotation": 0, "strokeColor": stroke, "strokeStyle": 0, "fillColor": fill, "strokeWidth": round(value["line_width_pt"] * FACTOR, 8) if value["stroke"] else 0, "fillStyle": 1 if fill else 0}
            log.append(record("RECT", body, ident(f"vector/{order}")))
            native_counts["RECT"] += 1
        else:
            body = {"partId": "", "groupId": group_ids[value["semantic_group"]], "locked": False, "zIndex": order, "points": points, "closed": subpaths[0]["closed"], "strokeColor": stroke, "strokeStyle": 0, "fillColor": fill, "strokeWidth": round(value["line_width_pt"] * FACTOR, 8) if value["stroke"] else 0, "fillStyle": 1 if fill else 0}
            log.append(record("POLY", body, ident(f"vector/{order}")))
            native_counts["POLY"] += 1
        svg.append(f'<path d="{" ".join(svg_commands)}" fill="{fill or "none"}" stroke="{stroke or "none"}" stroke-width="{value["line_width_pt"] if value["stroke"] else 0}" stroke-linecap="{["butt","round","square"][value["line_cap"]]}" stroke-linejoin="{["miter","round","bevel"][value["line_join"]]}" fill-rule="nonzero"/>')
    svg.append("</svg>")
    source = "\n".join(log) + "\n"
    (OUTPUT / "page1-source.epru").write_text(source, encoding="utf8")
    (OUTPUT / "page1-vector-preview.svg").write_text("\n".join(svg), encoding="utf8")
    project_metadata = {"title": NAME, "cbb_project": False, "editorVersion": "3.2.206", "introduction": "STM32H747 MCU board reconstruction from the 2026-08-27 PDF", "description": "A3 page 1 exact editable vector reconstruction. Circuit pages 2-6 remain pending.", "tags": "[]"}
    project_file = OUTPUT / (NAME + "_page1.epro2")
    with zipfile.ZipFile(project_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project2.json", json.dumps(project_metadata, ensure_ascii=False, indent=2))
        archive.writestr(NAME + ".epru", source)
    manifest = {"projectName": NAME, "schematicUuid": schematic_id, "pageUuid": page_id, "pageName": "01_HIERARCHY", "sourcePdfSha256": reference["source"]["sha256"], "pageMm": [419.989, 297.0022], "nativePrimitiveCounts": dict(native_counts), "groups": len(group_ids), "electricalComponents": 0, "electricalWires": 0, "note": "Visible text is preserved as editable polygon outlines for exact typography. Five hierarchy boxes are native graphic index blocks; child circuit pages and electrical hierarchy are pending.", "epro2": str(project_file), "sha256": hashlib.sha256(project_file.read_bytes()).hexdigest()}
    (OUTPUT / "build-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
