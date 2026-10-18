#!/usr/bin/env python3
"""Generate only new project-local ADC DC-buffer libraries, offline.

No native project or existing library is written. All generated artifacts are
bounded to output/candidates/adc-dc-buffer. Datasheet land patterns are library
references only; this schematic-only task does not place or alter PCB copper.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/candidates/adc-dc-buffer"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_adc_dc_buffer_20261016.epro2"
PROJECT = "STM32H747_MCU_BOARD_v19"
PREFIX = "STM_H747_ADC_DC_20261016_"
STAMP = 1792108800000
SOURCES = {
    "OPA320": "https://www.ti.com/lit/ds/symlink/opa320.pdf",
    "REF3325": "https://www.ti.com/lit/ds/symlink/ref33.pdf",
}


def compact(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def uid(kind, label):
    return hashlib.sha256(f"stm32h747-adc-dc-buffer-20261016\0{kind}\0{label}".encode()).hexdigest()[:16]


class Doc:
    def __init__(self, kind, label, title):
        self.kind, self.label, self.title = kind, label, title
        self.uuid = uid(kind, label)
        self.records = []
        self.add("DOCHEAD", {"docType": kind, "client": uid("CLIENT", PROJECT), "uuid": self.uuid,
                "updateTime": STAMP, "version": str(STAMP), "editVersion": "3.2.206",
                "user": {"uuid": self.uuid, "username": "", "nickname": ""}})

    def add(self, kind, value, key=None):
        index = len(self.records) + 1
        head = {"type": kind, "ticket": index}
        if kind != "DOCHEAD":
            head["id"] = key if key is not None else uid(self.label, f"{kind}/{index}")
        self.records.append((head, value))
        return head.get("id")

    def source(self):
        baseline = copy.deepcopy(self.records)
        baseline[0][1]["version"] = str(STAMP)
        digest = hashlib.sha256(compact(baseline).encode()).hexdigest()
        self.records[0][1]["version"] = str(STAMP + int(digest[:8], 16))
        return "".join(f"{compact(h)}||{compact(v)}|\n" for h, v in self.records)


def common(z=0):
    return {"partId": "A", "groupId": "", "locked": False, "zIndex": z}


def attr(doc, parent, key, value, x=None, y=None, visible=False, align="LEFT_MIDDLE", size=5):
    return doc.add("ATTR", {**common(len(doc.records)), "parentId": parent, "key": key, "value": value,
        "keyVisible": False, "valueVisible": visible, "x": x, "y": y, "rotation": 0,
        "color": "#006464" if key in ("Pin Name", "Pin Number") else "#000080", "fillColor": None,
        "fontFamily": "Arial", "fontSize": size, "strikeout": False, "underline": False,
        "italic": False, "fontWeight": False, "align": align, "version": "2.0"})


def poly(doc, points, closed=False, fill="", width=0.6):
    doc.add("POLY", {**common(len(doc.records)), "points": [{"x": x, "y": y} for x, y in points],
        "closed": closed, "startShape": None, "endShape": None, "strokeColor": "#840000",
        "strokeStyle": "SOLID", "fillColor": fill, "strokeWidth": width,
        "fillStyle": "SOLID" if fill else "NONE"})


def pin(doc, number, name, x, y, length, rotation, electric, *, show_name=True, show_number=True):
    key = uid(doc.label, f"PIN/{number}")
    doc.add("PIN", {**common(len(doc.records)), "display": True, "x": x, "y": y,
        "length": length, "rotation": rotation, "color": "#840000", "pinShape": "NONE"}, key)
    dx, dy = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rotation]
    nx, ny = x + dx * (length + 2), y + dy * (length + 2)
    if rotation in (0, 180):
        name_align = "LEFT_MIDDLE" if rotation == 0 else "RIGHT_MIDDLE"
        number_x, number_y = x + dx * length / 2, y - 3
        number_align = "CENTER_BOTTOM"
    else:
        name_align = "CENTER_TOP" if rotation == 90 else "CENTER_BOTTOM"
        number_x, number_y = x + 3, y + dy * length / 2
        number_align = "LEFT_MIDDLE"
    attr(doc, key, "Pin Name", name, nx, ny, show_name, name_align, 4.5)
    attr(doc, key, "Pin Number", str(number), number_x, number_y, show_number, number_align, 4)
    attr(doc, key, "Pin Type", electric)
    return {"number": str(number), "name": name, "primitiveId": key, "x": x, "y": y,
            "length": length, "rotation": rotation, "electric": electric, "partId": "A"}


def symbol(label, title, kind):
    title = PREFIX + title
    doc = Doc("SYMBOL", label, title)
    doc.add("CANVAS", {"originX": 0, "originY": 0}, "CANVAS")
    doc.add("PART", {"title": "A"}, "A")
    doc.add("META", {"title": title, "description": "Editable ADC DC-preserving hardware component",
        "docType": 2, "tags": ["PROJECT_LOCAL", "ADC_DC_BUFFER_20261016"],
        "source": doc.uuid + "|project"}, "META")
    pins = []
    if kind == "opamp":
        poly(doc, [(-20, -25), (-20, 25), (25, 0)], True, "#FFFFC2")
        pins = [pin(doc, "1", "OUT", 45, 0, 20, 180, "OUT", show_name=False),
                pin(doc, "2", "V-", 0, 35, 20, 270, "Ground"),
                pin(doc, "3", "+", -40, -10, 20, 0, "IN"),
                pin(doc, "4", "-", -40, 10, 20, 0, "IN"),
                pin(doc, "5", "V+", 0, -35, 20, 90, "Power")]
        attr(doc, "", "Designator", "U?", -22, -49, True)
        attr(doc, "", "Value", title, -22, -42, True)
    elif kind == "reference":
        poly(doc, [(-25, -20), (25, -20), (25, 20), (-25, 20)], True, "#FFFFC2")
        pins = [pin(doc, "1", "IN", -45, -10, 20, 0, "Power"),
                pin(doc, "2", "OUT", 45, -10, 20, 180, "OUT"),
                pin(doc, "3", "GND", 0, 40, 20, 270, "Ground")]
        attr(doc, "", "Designator", "U?", -25, -35, True)
        attr(doc, "", "Value", title, -25, -28, True)
    elif kind == "resistor":
        poly(doc, [(-10, -4), (10, -4), (10, 4), (-10, 4)], True)
        pins = [pin(doc, "1", "1", -15, 0, 5, 0, "Passive", show_name=False, show_number=False),
                pin(doc, "2", "2", 15, 0, 5, 180, "Passive", show_name=False, show_number=False)]
        attr(doc, "", "Designator", "R?", -10, -12, True)
        attr(doc, "", "Value", "R", -10, 11, True)
    elif kind == "capacitor":
        poly(doc, [(-8, -2), (8, -2)], width=1)
        poly(doc, [(-8, 2), (8, 2)], width=1)
        pins = [pin(doc, "1", "1", 0, -10, 8, 90, "Passive", show_name=False, show_number=False),
                pin(doc, "2", "2", 0, 10, 8, 270, "Passive", show_name=False, show_number=False)]
        attr(doc, "", "Designator", "C?", 12, -7, True)
        attr(doc, "", "Value", "C", 12, 2, True)
    else:
        raise ValueError(kind)
    return doc, {"uuid": doc.uuid, "title": title, "pins": pins, "partId": "A",
                 "coordinateUnit": "0.01 inch, positive y down in symbol-local source"}


def read_checkpoint(path=CHECKPOINT):
    with zipfile.ZipFile(path) as archive:
        source = archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode("utf8")
    documents = {}
    cur = None
    for line in source.splitlines():
        if not line.strip():
            continue
        h, v = line.split("||", 1)
        h, v = json.loads(h), json.loads(v.rstrip("|"))
        if h["type"] == "DOCHEAD":
            cur = (v["docType"], v["uuid"])
            documents.setdefault(cur, {})
        key = (h["type"], str(h.get("id", "")))
        old = documents[cur].get(key)
        if old is None or h.get("ticket", 0) >= old[0].get("ticket", 0):
            documents[cur][key] = (h, v)
    return documents


def runtime_map():
    after_path = ROOT / "output/checkpoints/STM32H747_after_adc_library_import_20261016.epro2"
    before = read_checkpoint(CHECKPOINT)
    after = read_checkpoint(after_path)
    manifest = json.loads((OUT / "adc-dc-library-manifest.json").read_text(encoding="utf8"))
    result = {"schema": "adc-dc-runtime-library-map-20261016-v1", "devices": {}, "symbols": {}, "footprints": {}}
    new_docs = set(after) - set(before)
    mapping = {}
    matches_by_kind = {}
    for group, kind in (("symbols", "SYMBOL"), ("footprints", "FOOTPRINT"), ("devices", "DEVICE")):
        for key, original in manifest[group].items():
            matches = []
            for identity in new_docs:
                if identity[0] != kind:
                    continue
                meta = next((v for h, v in after[identity].values() if h["type"] == "META"), {})
                source = str(meta.get("source", ""))
                if source.split("|")[0] == original["uuid"] or meta.get("title") == original["title"]:
                    matches.append((identity, meta))
            if len(matches) != 1:
                raise ValueError(f"Runtime map ambiguous/missing {group}/{key}: {matches}")
            identity, meta = matches[0]
            mapped = copy.deepcopy(original)
            mapped.update(uuid=identity[1], oldUuid=original["uuid"], source=meta.get("source", ""),
                          title=meta.get("title", original["title"]))
            mapped["runtimeMeta"] = meta
            result[group][key] = mapped
            mapping[original["uuid"]] = identity[1]
            matches_by_kind[identity] = f"{group}/{key}"
    for d in result["devices"].values():
        d["symbolUuid"] = mapping[d["symbolUuid"]]
        d["footprintUuid"] = mapping[d["footprintUuid"]]
        d["attributes"]["Symbol"] = d["symbolUuid"]
        d["attributes"]["Footprint"] = d["footprintUuid"]
    result["uuidMap"] = mapping
    result["checkpoint"] = str(after_path)
    result["checkpointSha256"] = hashlib.sha256(after_path.read_bytes()).hexdigest()
    result["newDocumentCount"] = len(new_docs)
    if len(new_docs) != 19 or set(matches_by_kind) != new_docs:
        raise ValueError(f"Unexpected new documents {new_docs - set(matches_by_kind)}")
    changed = []
    bookkeeping = []
    ignore = {"DOCHEAD", "CANVAS", "ACTIVE_LAYER", "ELE_PLACEHOLDER"}
    for identity, old_rows in before.items():
        if identity not in after:
            changed.append({"document": identity, "reason": "missing"})
            continue
        new_rows = after[identity]
        for key in set(old_rows) | set(new_rows):
            old = old_rows.get(key)
            new = new_rows.get(key)
            ob = old[1] if old else None
            nb = new[1] if new else None
            if ob == nb:
                continue
            entry = {"document": identity, "record": key, "before": ob, "after": nb}
            (bookkeeping if key[0] in ignore else changed).append(entry)
    pcbs = [key for key in before if key[0] == "PCB"]
    schpages = [key for key in before if key[0] == "SCH_PAGE"]
    pcb_components = sum(h["type"] == "COMPONENT" for key in pcbs for h, v in before[key].values())
    audit = {"schema": "adc-dc-library-import-preservation-20261016-v1", "before": str(CHECKPOINT), "after": str(after_path),
        "newDocuments": [{"docType": k[0], "uuid": k[1], "manifestKey": matches_by_kind[k]} for k in sorted(new_docs)],
        "newCounts": dict(Counter(k[0] for k in new_docs)), "existingDocumentCount": len(before),
        "existingDocumentBodiesUnchangedExceptBookkeeping": not changed, "nonBookkeepingChanges": changed,
        "bookkeepingChanges": bookkeeping, "schematicPagesPreserved": len(schpages),
        "pcbCount": len(pcbs), "pcbComponentsPreserved": pcb_components,
        "physicalDrillsPreserved": 793 if not changed else None,
        "physicalDrillProof": "All existing PCB and footprint bodies exactly preserved; invariant inherits the independently verified pre-change 793 physical drills.",
        "passed": not changed and len(new_docs) == 19 and len(schpages) == 5 and pcb_components == 330}
    (OUT / "adc-dc-runtime-library-map.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    (OUT / "adc-dc-library-import-preservation-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"map": str(OUT / "adc-dc-runtime-library-map.json"), "auditPassed": audit["passed"],
                      "newCounts": audit["newCounts"], "nonBookkeepingChanges": len(changed), "bookkeepingChanges": len(bookkeeping)}, ensure_ascii=False))
    if changed:
        raise ValueError("Unexpected existing non-bookkeeping body changes")


def clone_footprint(label, title, source_uuid, documents):
    title = PREFIX + title
    if ("FOOTPRINT", source_uuid) not in documents:
        base = {"R0402": "R1_", "C0402": "C1_", "C0603": "C31_", "C0805": "C29_"}[label]
        matches = [key[1] for key, rows in documents.items() if key[0] == "FOOTPRINT"
                   and any(h["type"] == "META" and isinstance(v, dict)
                           and v.get("title", "").startswith(base) for h, v in rows.values())]
        if not matches:
            raise ValueError(f"Expected existing footprint {base}: {matches}")
        geometry = []
        for candidate in matches:
            pads = [copy.deepcopy(v) for h, v in documents[("FOOTPRINT", candidate)].values() if h["type"] == "PAD"]
            for p in pads:
                p.pop("groupId", None)
                p.pop("unusedInnerLayers", None)
                p.pop("num", None)
                p.pop("zIndex", None)
            geometry.append(compact(sorted(pads, key=compact)))
        if len(set(geometry)) != 1:
            raise ValueError(f"Ambiguous existing footprint pad geometry {base}: {matches}")
        source_uuid = max(matches, key=lambda candidate: max(h.get("ticket", 0) for h, v in documents[("FOOTPRINT", candidate)].values() if h["type"] == "META"))
    rows = documents[("FOOTPRINT", source_uuid)]
    doc = Doc("FOOTPRINT", label, title)
    for h, v in rows.values():
        if h["type"] in ("DOCHEAD", "DELETE_DOC") or not isinstance(v, dict):
            continue
        body = copy.deepcopy(v)
        if h["type"] == "META":
            body.update(title=title, source=doc.uuid + "|project",
                        description=f"New project-local clone of existing footprint {source_uuid}; no PCB mutation")
        doc.add(h["type"], body, h.get("id"))
    pads = [{"number": str(v["num"]), "xMil": v["centerX"], "yMil": v["centerY"],
             "defaultPad": v["defaultPad"]} for h, v in doc.records if h["type"] == "PAD"]
    assert sorted(p["number"] for p in pads) == ["1", "2"]
    return doc, {"uuid": doc.uuid, "title": title, "pads": pads, "cloneSourceUuid": source_uuid,
                 "geometryOrigin": "existing checkpoint footprint; exact bodies except new META identity",
                 "manufacturingApproval": False}


def sot_footprint(label, title, package):
    title = PREFIX + title
    doc = Doc("FOOTPRINT", label, title)
    doc.add("META", {"title": title, "source": doc.uuid + "|project", "tags": ["ADC_DC_BUFFER_20261016"],
        "description": "TI datasheet example land pattern; assembly/factory approval pending"}, "META")
    doc.add("CANVAS", {"originX": 0, "originY": 0, "unit": "mm", "gridType": "NONE"}, "CANVAS")
    doc.add("ACTIVE_LAYER", {"layerId": 1}, "ACTIVE_LAYER")
    for layer_id, layer_type, name, active, inactive in (
            (1, "TOP", "Top Layer", "#FF0000", "#7F0000"),
            (3, "TOP_SILK", "Top Silkscreen Layer", "#FFCC00", "#7F6600"),
            (5, "TOP_SOLDER_MASK", "Top Solder Mask Layer", "#800080", "#400040"),
            (7, "TOP_PASTE_MASK", "Top Paste Mask Layer", "#808080", "#404040"),
            (9, "TOP_ASSEMBLY", "Top Assembly Layer", "#33CC99", "#19664C"),
            (48, "COMPONENT_SHAPE", "Component Shape Layer", "#00CCCC", "#006666")):
        doc.add("LAYER", {"layerType": layer_type, "layerName": name, "use": True, "show": True,
            "locked": False, "activeColor": active, "activateTransparency": 1,
            "inactiveColor": inactive, "inactiveTransparency": 1}, compact(["LAYER", layer_id]))
    # TI top view: left row top-to-bottom 1/2/3 and right row bottom-to-top
    # 4/5. Native footprint coordinates are Y-up, unlike symbol-local Y-down.
    if package == "DBV5":
        xy = {"1": (-1.3, 0.95), "2": (-1.3, 0), "3": (-1.3, -0.95),
              "4": (1.3, -0.95), "5": (1.3, 0.95)}
        width, height, drawing, body = 1.1, 0.6, "DBV0005A 4214839/K 08/2024", (1.6, 2.9)
    else:
        xy = {"1": (-1.05, 0.95), "2": (-1.05, -0.95), "3": (1.05, 0)}
        width, height, drawing, body = 1.3, 0.6, "DBZ0003A 4214838/F 08/2024", (1.3, 2.92)
    cv = lambda x: round(x / 0.0254, 6)
    pads = []
    for number, (x, y) in xy.items():
        shape = {"padType": "RECT", "width": cv(width), "height": cv(height), "radius": cv(0.05)}
        doc.add("PAD", {"groupId": 0, "netName": "", "layerId": 1, "num": number,
            "centerX": cv(x), "centerY": cv(y), "padAngle": 0, "hole": None, "defaultPad": shape,
            "specialPad": [], "padOffsetX": 0, "padOffsetY": 0, "relativeAngle": 0, "plated": False,
            "padType": "NORMAL", "topSolderExpansion": cv(0.07), "bottomSolderExpansion": None,
            "topPasteExpansion": 0, "bottomPasteExpansion": None, "locked": False, "zIndex": int(number),
            "connectMode": None, "spokeSpace": None, "spokeWidth": None, "spokeAngle": None,
            "unusedInnerLayers": [], "padLen": 0, "propagationDelay": 0}, uid(label, "pad/" + number))
        pads.append({"number": number, "centerMm": [x, y], "copperSizeMm": [width, height],
                     "cornerRadiusMm": 0.05, "solderMaskExpansionMm": 0.07, "pasteExpansionMm": 0})
    # Assembly outline and conservative courtyard on non-copper layers only.
    for layer, half_x, half_y, line_width in ((9, body[0] / 2, body[1] / 2, 0.10), (48, 2.1, 1.8, 0.05)):
        vertices = [(-half_x, -half_y), (half_x, -half_y), (half_x, half_y), (-half_x, half_y)]
        for a, b in zip(vertices, vertices[1:] + vertices[:1]):
            doc.add("LINE", {"groupId": 0, "netName": "", "layerId": layer, "startX": cv(a[0]),
                "startY": cv(a[1]), "endX": cv(b[0]), "endY": cv(b[1]), "lineWidth": cv(line_width),
                "locked": False, "zIndex": len(doc.records)})
    # Visible pin-1 silkscreen dot is represented as a short line, away from pads.
    doc.add("LINE", {"groupId": 0, "netName": "", "layerId": 3, "startX": cv(-1.95), "startY": cv(1.5),
        "endX": cv(-1.85), "endY": cv(1.5), "lineWidth": cv(0.20), "locked": False, "zIndex": len(doc.records)})
    return doc, {"uuid": doc.uuid, "title": title, "pads": pads, "drawing": drawing,
                 "geometryOrigin": "TI official example land pattern, top view, native footprint Y-up",
                 "manufacturingApproval": False, "notes": "Verify chosen package/assembly land pattern and pin-1 orientation before PCB update."}


def device(label, title, sym, foot, value, designator, attributes=None):
    title = PREFIX + title
    doc = Doc("DEVICE", label, title)
    props = {"Convert to PCB": "yes", "Add into BOM": "yes", "Designator": designator,
             "Symbol": sym["uuid"], "Footprint": foot["uuid"], "Value": value,
             "Name": "={Value}", "Package": foot["title"], "DNP": "no", **(attributes or {})}
    doc.add("META", {"title": title, "source": doc.uuid + "|project", "images": [""],
        "tags": ["STM32H747_MCU_BOARD_v19", "ADC_DC_BUFFER_20261016"], "attributes": props}, "META")
    return doc, {"uuid": doc.uuid, "title": title, "symbolUuid": sym["uuid"], "footprintUuid": foot["uuid"],
                 "attributes": props, "pinToPad": {p["number"]: p["number"] for p in sym["pins"]}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    documents = read_checkpoint()
    existing_ids = {key[1] for key in documents}
    symbols, footprints, devices, generated = {}, {}, {}, []
    for key, title, kind in (("OPA320", "OPA320AIDBVR", "opamp"), ("REF3325", "REF3325AIDBZR", "reference"),
                             ("R", "ADC_DC_R", "resistor"), ("C", "ADC_DC_C", "capacitor")):
        doc, info = symbol(key, title, kind)
        symbols[key] = info
        generated.append(doc)
    clones = {"R0402": ("ADC_DC_R0402", "8f44438a0ed8d240"),
              "C0402": ("ADC_DC_C0402", "9e353eb6a704affd"),
              "C0603": ("ADC_DC_C0603", "0866d66c95bbef96"),
              "C0805": ("ADC_DC_C0805", "765fa1bbb384e74b")}
    for key, (title, old_uuid) in clones.items():
        doc, info = clone_footprint(key, title, old_uuid, documents)
        footprints[key] = info
        generated.append(doc)
    for key, title in (("DBV5", "ADC_DC_TI_DBV0005A_SOT23_5"), ("DBZ3", "ADC_DC_TI_DBZ0003A_SOT23_3")):
        doc, info = sot_footprint(key, title, key)
        footprints[key] = info
        generated.append(doc)
    specs = [
        ("OPA320", "OPA320AIDBVR", "OPA320", "DBV5", "OPA320AIDBVR", "U?", {"Manufacturer": "Texas Instruments", "Part Number": "OPA320AIDBVR", "Datasheet": SOURCES["OPA320"]}),
        ("REF3325", "REF3325AIDBZR", "REF3325", "DBZ3", "REF3325AIDBZR", "U?", {"Manufacturer": "Texas Instruments", "Part Number": "REF3325AIDBZR", "Datasheet": SOURCES["REF3325"], "Output Voltage": "2.5 V"}),
        ("R47", "ADC_DC_R47_0402", "R", "R0402", "47", "R?", {"Tolerance": "1%"}),
        ("R6K8", "ADC_DC_R6K8_0P1_0402", "R", "R0402", "6.8k", "R?", {"Tolerance": "0.1%", "Temperature Coefficient": "25 ppm/K or better", "Description": "DC gain/offset matched 6.8k 0.1% resistor; procurement MPN selection pending"}),
        ("C2N2", "ADC_DC_C2N2_C0G_0402", "C", "C0402", "2.2nF", "C?", {"Dielectric": "C0G/NP0", "Tolerance": "5%", "Voltage Rating": "25 V or greater"}),
        ("C10N", "ADC_DC_C10N_C0G_0402", "C", "C0402", "10nF", "C?", {"Dielectric": "C0G/NP0", "Tolerance": "5%", "Voltage Rating": "25 V or greater"}),
        ("C100N", "ADC_DC_C100N_X7R_0402", "C", "C0402", "100nF", "C?", {"Dielectric": "X7R", "Voltage Rating": "10 V or greater"}),
        ("C1U", "ADC_DC_C1U_X7R_0603", "C", "C0603", "1uF", "C?", {"Dielectric": "X7R", "Voltage Rating": "10 V or greater"}),
        ("C4U7", "ADC_DC_C4U7_X7R_0805", "C", "C0805", "4.7uF", "C?", {"Dielectric": "X7R", "Voltage Rating": "10 V or greater"}),
    ]
    for key, title, sk, fk, value, ref, attrs in specs:
        doc, info = device(key, title, symbols[sk], footprints[fk], value, ref, attrs)
        devices[key] = info
        generated.append(doc)
    ids = [d.uuid for d in generated]
    assert len(ids) == len(set(ids)) and not (set(ids) & existing_ids)
    for d in devices.values():
        sf = next(s for s in symbols.values() if s["uuid"] == d["symbolUuid"])
        fp = next(f for f in footprints.values() if f["uuid"] == d["footprintUuid"])
        assert {p["number"] for p in sf["pins"]} == {p["number"] for p in fp["pads"]}
    order = {"SYMBOL": 0, "FOOTPRINT": 1, "DEVICE": 2}
    generated.sort(key=lambda d: (order[d.kind], d.label))
    source = "".join(d.source() for d in generated)
    source_path = OUT / "adc-dc-new-libraries.epru"
    source_path.write_text(source, encoding="utf8", newline="\n")
    for d in generated:
        extension = {"SYMBOL": "esym", "FOOTPRINT": "efoo", "DEVICE": "edevice"}[d.kind]
        (OUT / f"{d.label}_{d.uuid}.{extension}").write_text(d.source(), encoding="utf8", newline="\n")
    package = OUT / "STM32H747_adc_dc_new_libraries_20261016.epro2"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project2.json", json.dumps({"title": PROJECT, "cbb_project": False,
            "editorVersion": "3.2.206", "description": "New ADC DC-preserving buffer libraries only; no schematic/PCB documents", "tags": "[]"}, ensure_ascii=False))
        archive.writestr(PROJECT + ".epru", source)
    manifest = {"schema": "adc-dc-new-libraries-20261016-v1", "project": PROJECT,
        "sourceCheckpoint": str(CHECKPOINT), "sourceCheckpointSha256": hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest(),
        "newOnly": True, "mutatesExistingLibraries": False, "containsSchematicOrPcb": False,
        "counts": dict(Counter(d.kind for d in generated)), "symbols": symbols,
        "footprints": footprints, "devices": devices, "officialSources": SOURCES,
        "sourcePath": str(source_path), "sourceSha256": hashlib.sha256(source.encode()).hexdigest(),
        "packagePath": str(package), "packageSha256": hashlib.sha256(package.read_bytes()).hexdigest(),
        "validation": {"uniqueNewUuidNoCollision": True, "allSymbolPinsMatchFootprintPads": True,
                       "nativeLibraryImportPending": True, "manufacturingApproved": False},
        "importantNotes": ["Native 3.2.206 uses Pin Name/Pin Number/Pin Type ATTR keys, not legacy NAME/NUMBER keys.",
            "All symbol pins are real numbered electrical primitives; component Designator/Value remain editable visible ATTR records, not PDF glyphs.",
            "Imported devices need runtime project-local name/source metadata rebind as in prior native library workflow.",
            "All generated documents are new UUIDs; cloned passive footprint IDs only occur within new document scope.",
            "No test equipment, simulation, native ERC, or PCB DRC has been performed by this offline library generator."]}
    (OUT / "adc-dc-library-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"package": str(package), "sha256": manifest["packageSha256"], "counts": manifest["counts"],
                      "manifest": str(OUT / "adc-dc-library-manifest.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    runtime_map() if "--runtime-map" in sys.argv else main()
