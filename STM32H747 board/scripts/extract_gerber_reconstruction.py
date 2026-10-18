#!/usr/bin/env python3
"""Extract loss-aware PCB reconstruction data from the archived KiCad Gerbers.

The Gerbers are the 2026-06 manufacturing reference, not the electrical source of
truth.  This tool deliberately preserves X2 object attributes and raw geometry so
that a later EasyEDA importer can use the files for placement/route comparison
without silently treating the old netlist as current.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


COPPER_NAME = {
    "F_Cu": "F.Cu",
    "In1_Cu": "In1.Cu",
    "In2_Cu": "In2.Cu",
    "In3_Cu": "In3.Cu",
    "In4_Cu": "In4.Cu",
    "B_Cu": "B.Cu",
}

MANUFACTURING_NAME = {
    "F_Cu": "F.Cu",
    "In1_Cu": "In1.Cu",
    "In2_Cu": "In2.Cu",
    "In3_Cu": "In3.Cu",
    "In4_Cu": "In4.Cu",
    "B_Cu": "B.Cu",
    "F_Mask": "F.Mask",
    "B_Mask": "B.Mask",
    "F_Paste": "F.Paste",
    "B_Paste": "B.Paste",
    "F_Silkscreen": "F.SilkS",
    "B_Silkscreen": "B.SilkS",
    "Edge_Cuts": "Edge.Cuts",
}

PAGE5_REFS = {
    *(f"C{i}" for i in range(62, 77)),
    "CN2", "CN3", "CN4", "FB3", "Q1", "TR1", "TVS1", "TVS2", "TVS3",
    "U5", "U6", "U7", "U8", "X2",
    *(f"R{i}" for i in range(74, 137)),
}

PAGE6_REFS = {
    "C80", "C81", "C82", "C86", "C87", "C88", "C93", "C94", "C95", "C96",
    *(f"J{i}" for i in range(2, 19)),
    *(f"R{i}" for i in range(137, 177)),
    *(f"TP{i}" for i in range(1, 17)),
}

REMOVED_LATEST = ["C77", "C78", "C79", "C83", "C84", "C85", "C89", "C90", "C91", "C92"]

BIAS_CHANNELS = [
    ("C77", "R137", "ADC1_INP0"),
    ("C78", "R138", "ADC1_INP1"),
    ("C79", "R139", "ADC1_INP16"),
    ("C83", "R149", "ADC2_INP3"),
    ("C84", "R150", "ADC2_INP12"),
    ("C85", "R151", "ADC2_INP13"),
    ("C89", "R161", "ADC3_INP2"),
    ("C90", "R162", "ADC3_INP6"),
    ("C91", "R163", "ADC3_INP7"),
    ("C92", "R164", "ADC3_INP8"),
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean_num(value: float | None, digits: int = 6):
    if value is None:
        return None
    value = round(float(value), digits)
    return 0.0 if value == -0.0 else value


def parse_xy_token(token: str | None, decimals: int) -> float | None:
    if token is None:
        return None
    return int(token) / (10 ** decimals)


def aperture_extents(ap: dict | None) -> tuple[float, float]:
    if not ap:
        return (0.0, 0.0)
    template = ap.get("template", "")
    params = ap.get("paramsMm", [])
    if not params:
        return (0.0, 0.0)
    if template == "C":
        return (params[0] / 2, params[0] / 2)
    if template in ("R", "O") and len(params) >= 2:
        return (params[0] / 2, params[1] / 2)
    if template == "P":
        return (params[0] / 2, params[0] / 2)
    if template == "RoundRect" and len(params) >= 9:
        radius = abs(params[0])
        xs = params[1:9:2]
        ys = params[2:9:2]
        return (max(abs(x) for x in xs) + radius, max(abs(y) for y in ys) + radius)
    if template.startswith("Outline") and len(params) >= 3:
        coord_count = len(params) - 1
        xs = params[:coord_count:2]
        ys = params[1:coord_count:2]
        return (max(abs(x) for x in xs), max(abs(y) for y in ys))
    return (max(abs(p) for p in params[:2]), max(abs(p) for p in params[:2]))


def primitive_points(obj: dict) -> list[tuple[float, float]]:
    kind = obj["kind"]
    if kind == "flash":
        return [(obj["atMm"][0], obj["atMm"][1])]
    if kind in ("line", "arc"):
        pts = [tuple(obj["startMm"]), tuple(obj["endMm"])]
        if kind == "arc":
            cx, cy = obj["centerMm"]
            r = math.hypot(pts[0][0] - cx, pts[0][1] - cy)
            pts += [(cx - r, cy - r), (cx + r, cy + r)]
        return pts
    if kind == "region":
        pts = []
        for contour in obj["contours"]:
            for seg in contour:
                pts.extend(primitive_points(seg))
        return pts
    return []


def parse_gerber(path: Path, layer: str) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    decimals = 6
    fs = re.search(r"%FSLAX(\d)(\d)Y(\d)(\d)\*%", text)
    if fs:
        decimals = int(fs.group(2))

    aperture_attrs: dict[str, str] = {}
    object_attrs: dict[str, str] = {}
    apertures: dict[str, dict] = {}
    current_aperture: str | None = None
    x = y = 0.0
    interpolation = "linear"
    polarity = "dark"
    in_region = False
    region_contours: list[list[dict]] = []
    current_contour: list[dict] | None = None
    objects: list[dict] = []

    add_re = re.compile(r"^%ADD(\d+)([^,\*]+)(?:,([^\*]+))?\*%$")
    coord_re = re.compile(r"([XYIJ])([+-]?\d+)")

    def snapshot_attrs() -> dict:
        return {k: v for k, v in object_attrs.items() if k in ("C", "P", "N")}

    def make_segment(nx: float, ny: float, i: float | None, j: float | None) -> dict:
        common = {
            "aperture": current_aperture,
            "attrs": snapshot_attrs(),
            "polarity": polarity,
            "startMm": [clean_num(x), clean_num(y)],
            "endMm": [clean_num(nx), clean_num(ny)],
        }
        if interpolation == "linear":
            return {"kind": "line", **common}
        cx = x + (i or 0.0)
        cy = y + (j or 0.0)
        return {
            "kind": "arc",
            **common,
            "centerMm": [clean_num(cx), clean_num(cy)],
            "clockwise": interpolation == "cw",
        }

    lines = text.splitlines()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("G04"):
            continue
        if line.startswith("%TA."):
            body = line[4:-2]
            key, *rest = body.split(",")
            aperture_attrs[key] = ",".join(rest)
            continue
        if line.startswith("%TO."):
            body = line[4:-2]
            key, *rest = body.split(",")
            object_attrs[key] = ",".join(rest)
            continue
        if line.startswith("%TD"):
            body = line[3:-2]
            if body.startswith("."):
                key = body[1:]
                aperture_attrs.pop(key, None)
                object_attrs.pop(key, None)
            else:
                aperture_attrs.clear()
                object_attrs.clear()
            continue
        m = add_re.match(line)
        if m:
            code, template, raw_params = m.groups()
            params = []
            if raw_params:
                for value in raw_params.split("X"):
                    try:
                        params.append(clean_num(float(value)))
                    except ValueError:
                        pass
            apertures[f"D{code}"] = {
                "template": template,
                "paramsMm": params,
                "function": aperture_attrs.get("AperFunction"),
            }
            continue
        if line.startswith("%LP"):
            polarity = "clear" if line.startswith("%LPC") else "dark"
            continue
        if line in ("G01*", "G1*"):
            interpolation = "linear"
            continue
        if line in ("G02*", "G2*"):
            interpolation = "cw"
            continue
        if line in ("G03*", "G3*"):
            interpolation = "ccw"
            continue
        if line == "G36*":
            in_region = True
            region_contours = []
            current_contour = None
            continue
        if line == "G37*":
            if current_contour:
                region_contours.append(current_contour)
            objects.append({
                "kind": "region",
                "aperture": current_aperture,
                "attrs": snapshot_attrs(),
                "polarity": polarity,
                "contours": region_contours,
            })
            in_region = False
            region_contours = []
            current_contour = None
            continue
        if re.fullmatch(r"D\d+\*", line):
            code = int(line[1:-1])
            if code >= 10:
                current_aperture = f"D{code}"
            continue

        if "X" not in line and "Y" not in line:
            continue
        coords = {k: parse_xy_token(v, decimals) for k, v in coord_re.findall(line)}
        nx = coords.get("X", x)
        ny = coords.get("Y", y)
        # G codes may be modal changes on the same coordinate command.
        if re.search(r"(?:^|[^0-9])G0?1", line):
            interpolation = "linear"
        elif re.search(r"(?:^|[^0-9])G0?2", line):
            interpolation = "cw"
        elif re.search(r"(?:^|[^0-9])G0?3", line):
            interpolation = "ccw"
        dm = re.search(r"D0?([123])\*", line)
        if not dm:
            x, y = nx, ny
            continue
        operation = int(dm.group(1))
        if operation == 2:
            if in_region:
                if current_contour:
                    region_contours.append(current_contour)
                current_contour = []
        elif operation == 1:
            seg = make_segment(nx, ny, coords.get("I"), coords.get("J"))
            if in_region:
                if current_contour is None:
                    current_contour = []
                current_contour.append(seg)
            else:
                objects.append(seg)
        elif operation == 3:
            objects.append({
                "kind": "flash",
                "aperture": current_aperture,
                "attrs": snapshot_attrs(),
                "polarity": polarity,
                "atMm": [clean_num(nx), clean_num(ny)],
            })
        x, y = nx, ny

    for ap in apertures.values():
        ex, ey = aperture_extents(ap)
        ap["halfExtentMm"] = [clean_num(ex), clean_num(ey)]
    return {
        "layer": layer,
        "file": path.name,
        "sha256": sha256(path),
        "format": {"units": "mm", "integerDigits": 4, "decimalDigits": decimals},
        "apertures": apertures,
        "objects": objects,
    }


def parse_drill(path: Path, plated: bool) -> dict:
    tools: dict[str, dict] = {}
    holes: list[dict] = []
    pending_function = None
    current_tool = None
    in_body = False
    rapid_point: tuple[float, float] | None = None
    route_point: tuple[float, float] | None = None
    route_cutting = False
    tool_re = re.compile(r"^(T\d+)C([0-9.]+)$")
    xy_re = re.compile(r"^X([+-]?[0-9.]+)Y([+-]?[0-9.]+)$")
    routed_xy_re = re.compile(r"^G0?([01])X([+-]?[0-9.]+)Y([+-]?[0-9.]+)$")
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("; #@! TA.AperFunction,"):
            pending_function = line.split("AperFunction,", 1)[1]
            continue
        m = tool_re.match(line)
        if m and not in_body:
            tool, diameter = m.groups()
            tools[tool] = {
                "diameterMm": clean_num(float(diameter)),
                "function": pending_function,
            }
            pending_function = None
            continue
        if line == "%":
            in_body = True
            continue
        if in_body and re.fullmatch(r"T\d+", line):
            current_tool = line
            rapid_point = None
            route_point = None
            route_cutting = False
            continue
        routed = routed_xy_re.match(line)
        if in_body and routed and current_tool:
            motion, raw_x, raw_y = routed.groups()
            point = (float(raw_x), float(raw_y))
            if motion == "0":
                rapid_point = point
                route_point = point
            elif route_cutting and route_point is not None:
                start = route_point
                end = point
                diameter = float(tools[current_tool]["diameterMm"])
                centerline = math.hypot(end[0] - start[0], end[1] - start[1])
                if centerline <= 0:
                    raise ValueError(f"zero-length routed drill segment in {path.name}: {line}")
                holes.append({
                    "kind": "slot",
                    "atMm": [clean_num((start[0] + end[0]) / 2), clean_num((start[1] + end[1]) / 2)],
                    "startMm": [clean_num(start[0]), clean_num(start[1])],
                    "endMm": [clean_num(end[0]), clean_num(end[1])],
                    "tool": current_tool,
                    "diameterMm": clean_num(diameter),
                    "centerlineLengthMm": clean_num(centerline),
                    "overallLengthMm": clean_num(centerline + diameter),
                    "angleDeg": clean_num(math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))),
                    "function": tools[current_tool].get("function"),
                    "plated": plated,
                })
                route_point = point
            continue
        if in_body and line == "M15":
            route_cutting = True
            route_point = rapid_point
            continue
        if in_body and line == "M16":
            route_cutting = False
            rapid_point = None
            route_point = None
            continue
        m = xy_re.match(line)
        if in_body and m and current_tool:
            holes.append({
                "atMm": [clean_num(float(m.group(1))), clean_num(float(m.group(2)))],
                "tool": current_tool,
                "diameterMm": tools[current_tool]["diameterMm"],
                "function": tools[current_tool].get("function"),
                "plated": plated,
            })
    slot_count = sum(1 for hole in holes if hole.get("kind") == "slot")
    return {
        "file": path.name,
        "sha256": sha256(path),
        "tools": tools,
        "holes": holes,
        "summary": {"roundHits": len(holes) - slot_count, "routedSlots": slot_count},
    }


def hole_index(drills: list[dict]) -> dict[tuple[float, float], list[dict]]:
    idx: dict[tuple[float, float], list[dict]] = defaultdict(list)
    for drill in drills:
        for hole in drill["holes"]:
            key = (round(hole["atMm"][0], 3), round(hole["atMm"][1], 3))
            idx[key].append(hole)
    return idx


def lookup_holes(idx: dict, at: list[float]) -> list[dict]:
    key = (round(at[0], 3), round(at[1], 3))
    candidates = []
    for dx in (-0.001, 0.0, 0.001):
        for dy in (-0.001, 0.0, 0.001):
            candidates.extend(idx.get((round(key[0] + dx, 3), round(key[1] + dy, 3)), []))
    return [
        {k: v for k, v in h.items() if k != "atMm"}
        for h in candidates
        if abs(h["atMm"][0] - at[0]) <= 0.00051 and abs(h["atMm"][1] - at[1]) <= 0.00051
    ]


def decode_gerber_attribute(value: str) -> str:
    """Decode the JSON-style unicode escapes KiCad emits in X2 attributes."""
    return re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        value,
    )


def annotate_npth_ownership(npth: dict, parsed: list[dict]) -> None:
    """Join NPTH drill hits to component attributes carried by mask flashes.

    Excellon only identifies these as ComponentDrill.  KiCad's solder-mask
    Gerbers retain the authoritative TO.C owner at the same coordinate, which
    distinguishes footprint-local mechanical holes from the four board-level
    REF** mounting holes.
    """
    evidence_by_coord: dict[tuple[float, float], list[dict]] = defaultdict(list)
    for layer_data in parsed:
        if layer_data["layer"] not in ("F.Mask", "B.Mask"):
            continue
        for obj in layer_data["objects"]:
            raw_ref = obj.get("attrs", {}).get("C")
            if obj.get("kind") != "flash" or not raw_ref:
                continue
            key = (round(obj["atMm"][0], 3), round(obj["atMm"][1], 3))
            evidence_by_coord[key].append({
                "layer": layer_data["layer"],
                "gerberComponentAttributeRaw": raw_ref,
                "componentRef": decode_gerber_attribute(raw_ref),
            })

    for hole in npth["holes"]:
        key = (round(hole["atMm"][0], 3), round(hole["atMm"][1], 3))
        evidence = []
        for dx in (-0.001, 0.0, 0.001):
            for dy in (-0.001, 0.0, 0.001):
                evidence.extend(
                    evidence_by_coord.get(
                        (round(key[0] + dx, 3), round(key[1] + dy, 3)), []
                    )
                )
        refs = sorted({item["componentRef"] for item in evidence})
        if len(refs) == 1:
            hole["componentRef"] = refs[0]
            hole["ownership"] = (
                "boardMountingHole" if refs[0] == "REF**" else "componentMechanicalHole"
            )
        elif refs:
            hole["componentRefCandidates"] = refs
            hole["ownership"] = "ambiguousComponentMechanicalHole"
        else:
            hole["ownership"] = "unattributed"
        hole["ownershipEvidence"] = evidence


def object_copy(obj: dict, layer: str) -> dict:
    return {"layer": layer, **obj}


def component_page(ref: str) -> int | None:
    if ref in PAGE5_REFS:
        return 5
    if ref in PAGE6_REFS or ref in REMOVED_LATEST:
        return 6
    return None


def build_component_manifest(parsed: list[dict], holes: dict) -> dict:
    components: dict[str, dict] = {}

    def ensure(ref: str) -> dict:
        if ref not in components:
            components[ref] = {
                "pdfPageKnown": component_page(ref),
                "presentInLatest": ref not in REMOVED_LATEST,
                "gerberRevision": "260616",
                "pads": {},
                "layerGeometry": defaultdict(list),
            }
        return components[ref]

    for layer_data in parsed:
        layer = layer_data["layer"]
        apertures = layer_data["apertures"]
        for obj in layer_data["objects"]:
            attrs = obj.get("attrs", {})
            ref = attrs.get("C")
            if ref:
                ensure(ref)["layerGeometry"][layer].append(object_copy(obj, layer))
            pad_attr = attrs.get("P")
            if not pad_attr or obj["kind"] != "flash":
                continue
            parts = pad_attr.split(",")
            if len(parts) < 2:
                continue
            ref, pad_no = parts[0], parts[1]
            pin_function = ",".join(parts[2:]) or None
            comp = ensure(ref)
            pad = comp["pads"].setdefault(pad_no, {
                "number": pad_no,
                "pinFunctionOld": pin_function,
                "netOld": attrs.get("N"),
                "flashes": [],
            })
            # Attributes are modal.  A new TO.P does not clear the prior TO.N.
            if attrs.get("N") is not None:
                pad["netOld"] = attrs["N"]
            ap = apertures.get(obj.get("aperture"), {})
            flash = {
                "layer": layer,
                "atMm": obj["atMm"],
                "aperture": obj.get("aperture"),
                "shape": ap.get("template"),
                "paramsMm": ap.get("paramsMm", []),
                "apertureFunction": ap.get("function"),
                "polarity": obj.get("polarity"),
                "holes": lookup_holes(holes, obj["atMm"]),
            }
            pad["flashes"].append(flash)

    for ref, comp in components.items():
        comp["layerGeometry"] = dict(sorted(comp["layerGeometry"].items()))
        pad_points = []
        all_points = []
        layers = set(comp["layerGeometry"])
        for pad in comp["pads"].values():
            for flash in pad["flashes"]:
                pad_points.append(tuple(flash["atMm"]))
                layers.add(flash["layer"])
        for layer, objects in comp["layerGeometry"].items():
            for obj in objects:
                all_points.extend(primitive_points(obj))
        all_points.extend(pad_points)
        if all_points:
            comp["boundsByCentersMm"] = [
                clean_num(min(p[0] for p in all_points)),
                clean_num(min(p[1] for p in all_points)),
                clean_num(max(p[0] for p in all_points)),
                clean_num(max(p[1] for p in all_points)),
            ]
        if pad_points:
            unique = sorted(set(pad_points))
            comp["estimatedAnchorMm"] = [
                clean_num(sum(p[0] for p in unique) / len(unique)),
                clean_num(sum(p[1] for p in unique) / len(unique)),
            ]
        if any(layer.startswith("B.") for layer in layers) and not any(
            layer in ("F.Cu", "F.Mask", "F.Paste", "F.SilkS") for layer in layers
        ):
            comp["sideHint"] = "B"
        elif "B.SilkS" in layers and "F.SilkS" not in layers:
            comp["sideHint"] = "B"
        else:
            comp["sideHint"] = "F"
        comp["pads"] = dict(sorted(comp["pads"].items(), key=lambda kv: (not kv[0].isdigit(), int(kv[0]) if kv[0].isdigit() else kv[0])))
    return dict(sorted(components.items()))


def join_latest_schematic(root: Path, components: dict) -> dict:
    """Attach the small authoritative BOM subset from the PDF semantic manifest."""
    path = root / "output" / "semantic" / "schematic-pages-2-6.json"
    if not path.exists():
        return {
            "status": "not_available",
            "expectedPath": str(path.relative_to(root)),
            "matchedGerberRefs": 0,
        }
    doc = json.loads(path.read_text(encoding="utf-8"))
    latest: dict[str, dict] = {}
    for page in doc.get("pages", []):
        pdf_page = page.get("pdf_page")
        new_sheet_index = page.get("new_sheet_index")
        for item in page.get("components", []):
            if item.get("is_power_symbol"):
                continue
            ref = item.get("base_reference") or item.get("reference")
            if not ref:
                continue
            entry = latest.setdefault(ref, {
                "reference": ref,
                "pdfPages": [],
                "newSheetIndices": [],
                "units": [],
                "value": item.get("value"),
                "footprint": item.get("footprint"),
                "description": item.get("fields", {}).get("Description"),
                "partNumber": item.get("fields", {}).get("Part Number"),
                "package": item.get("fields", {}).get("Package"),
                "type": item.get("fields", {}).get("Type"),
                "supplier": item.get("fields", {}).get("Supplier"),
                "datasheet": item.get("fields", {}).get("Datasheet"),
                "dnp": bool(item.get("dnp")),
            })
            if pdf_page not in entry["pdfPages"]:
                entry["pdfPages"].append(pdf_page)
            if new_sheet_index not in entry["newSheetIndices"]:
                entry["newSheetIndices"].append(new_sheet_index)
            unit_name = item.get("reference")
            if unit_name and unit_name not in entry["units"]:
                entry["units"].append(unit_name)
            entry["dnp"] = entry["dnp"] or bool(item.get("dnp"))

    matched = 0
    for ref, comp in components.items():
        if ref in latest:
            comp["latestSchematic"] = latest[ref]
            comp["pdfPageKnown"] = latest[ref]["pdfPages"][0] if len(latest[ref]["pdfPages"]) == 1 else latest[ref]["pdfPages"]
            comp["presentInLatest"] = True
            comp["latestJoinStatus"] = "matched"
            matched += 1
        elif ref in REMOVED_LATEST:
            comp["presentInLatest"] = False
            comp["latestJoinStatus"] = "removed_after_gerber"
        else:
            comp["presentInLatest"] = None
            comp["latestJoinStatus"] = "not_in_pdf_component_annotations"

    return {
        "status": "joined",
        "path": str(path.relative_to(root)),
        "sha256": sha256(path),
        "latestUniquePhysicalRefs": len(latest),
        "matchedGerberRefs": matched,
        "latestRefsWithoutGerber": sorted(set(latest) - set(components)),
        "gerberRefsWithoutLatestAnnotation": sorted(set(components) - set(latest) - set(REMOVED_LATEST)),
    }


def compact_region(region: dict) -> dict:
    result = {
        "kind": "region",
        "netOld": region.get("attrs", {}).get("N"),
        "polarity": region.get("polarity"),
        "contours": [],
    }
    for contour in region["contours"]:
        compact = []
        for seg in contour:
            item = {
                "kind": seg["kind"],
                "startMm": seg["startMm"],
                "endMm": seg["endMm"],
            }
            if seg["kind"] == "arc":
                item["centerMm"] = seg["centerMm"]
                item["clockwise"] = seg["clockwise"]
            compact.append(item)
        result["contours"].append(compact)
    return result


def build_copper_routes(parsed: list[dict], holes: dict) -> dict:
    layers = {}
    via_groups: dict[tuple[float, float, str | None], dict] = {}
    for layer_data in parsed:
        layer = layer_data["layer"]
        if layer not in COPPER_NAME.values():
            continue
        tracks = []
        regions = []
        conductor_flashes = []
        counters = Counter()
        for obj in layer_data["objects"]:
            attrs = obj.get("attrs", {})
            ap = layer_data["apertures"].get(obj.get("aperture"), {})
            function = ap.get("function")
            counters[obj["kind"]] += 1
            if attrs.get("P"):
                continue
            if obj["kind"] == "flash" and function == "ViaPad":
                x, y = obj["atMm"]
                key = (round(x, 6), round(y, 6), attrs.get("N"))
                via = via_groups.setdefault(key, {
                    "atMm": obj["atMm"],
                    "netOld": attrs.get("N"),
                    "layers": [],
                    "holes": lookup_holes(holes, obj["atMm"]),
                })
                via["layers"].append({
                    "layer": layer,
                    "aperture": obj.get("aperture"),
                    "diameterMm": ap.get("paramsMm", [None])[0],
                    "shape": ap.get("template"),
                })
                continue
            base = {k: v for k, v in obj.items() if k != "attrs"}
            base["netOld"] = attrs.get("N")
            base["apertureFunction"] = function
            if obj["kind"] in ("line", "arc"):
                ex, ey = aperture_extents(ap)
                base["widthMm"] = clean_num(max(ex, ey) * 2)
                tracks.append(base)
            elif obj["kind"] == "region":
                regions.append(compact_region(obj))
            elif obj["kind"] == "flash":
                base["shape"] = ap.get("template")
                base["paramsMm"] = ap.get("paramsMm", [])
                conductor_flashes.append(base)
        layers[layer] = {
            "tracks": tracks,
            "regions": regions,
            "conductorFlashes": conductor_flashes,
            "sourceObjectCounts": dict(counters),
        }
    vias = sorted(via_groups.values(), key=lambda v: (v["atMm"][0], v["atMm"][1], v["netOld"] or ""))
    return {"layers": layers, "vias": vias}


def board_bounds(edge_data: dict) -> list[float]:
    points = []
    for obj in edge_data["objects"]:
        points.extend(primitive_points(obj))
    return [
        clean_num(min(p[0] for p in points)),
        clean_num(min(p[1] for p in points)),
        clean_num(max(p[0] for p in points)),
        clean_num(max(p[1] for p in points)),
    ]


def latest_patches() -> dict:
    bias = []
    for cap, upper, adc_net in BIAS_CHANNELS:
        old_a = f"Net-({cap}-Pad1)"
        old_b = f"Net-({cap}-Pad2)"
        new = f"Net-({upper}-Pad2)"
        bias.append({
            "removedComponent": cap,
            "upperBiasResistor": upper,
            "adcNet": adc_net,
            "oldNets": [old_a, old_b],
            "latestNet": new,
            "routingAction": "reroute_across_removed_series_capacitor",
            "warning": "Both old nets logically merge, but the Gerber copper retains a physical capacitor gap; renaming alone does not connect it.",
        })
    return {
        "sourceOfTruth": "MCU_BOARD_v19_260827.pdf",
        "page5ValueOnly": {
            "C69": {"old": "0.1u", "latest": "470p", "partNumberLatest": "CL05B471KB5NNNC"},
            "R129": {"old": "10k", "latest": "100k", "partNumberLatest": "ERJ-2RKF1003X"},
        },
        "page6RemovedComponents": REMOVED_LATEST,
        "page6BiasChannels": bias,
        "page6ValueChanges": {
            **{r: {"old": "30k", "latest": "7.5k", "partNumberLatest": "ERJ-2RKF7501X"} for r in ("R137", "R138", "R139", "R149", "R150", "R151", "R161", "R162", "R163", "R164")},
            **{r: {"old": "30k", "latest": "30k_NC", "assemblyLatest": "DNP"} for r in ("R146", "R147", "R148", "R158", "R159", "R160", "R173", "R174", "R175", "R176")},
        },
    }


def enrich_patch_geometry(patches: dict, components: dict) -> None:
    for channel in patches["page6BiasChannels"]:
        comp = components.get(channel["removedComponent"], {})
        centres = {}
        for number, pad in comp.get("pads", {}).items():
            front = next((f for f in pad["flashes"] if f["layer"] == "F.Cu"), None)
            if front:
                centres[number] = front["atMm"]
        channel["formerPadCentersMm"] = centres
        if "1" in centres and "2" in centres:
            channel["replacementCopperHint"] = {
                "kind": "line",
                "startMm": centres["1"],
                "endMm": centres["2"],
                "netLatest": channel["latestNet"],
                "advisoryOnly": True,
            }


def summary_counts(components: dict, routes: dict) -> dict:
    pads = sum(len(c["pads"]) for c in components.values())
    pad_flashes = sum(len(p["flashes"]) for c in components.values() for p in c["pads"].values())
    layer_counts = {}
    for layer, data in routes["layers"].items():
        layer_counts[layer] = {
            "tracks": len(data["tracks"]),
            "regions": len(data["regions"]),
            "conductorFlashes": len(data["conductorFlashes"]),
        }
    return {
        "components": len(components),
        "uniqueComponentPads": pads,
        "componentPadFlashesAcrossCopperLayers": pad_flashes,
        "vias": len(routes["vias"]),
        "routesByLayer": layer_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    default_root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    gerber_dir = root / "보드 자료" / "MCU_BOARD_v19_260616_Gerber"
    output_dir = (args.output_dir or (root / "output" / "semantic")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    gerbers = []
    source_files = []
    for stem, layer in MANUFACTURING_NAME.items():
        path = gerber_dir / f"MCU_BOARD_v19_260616-{stem}.gbr"
        parsed = parse_gerber(path, layer)
        gerbers.append(parsed)
        source_files.append({"file": path.name, "sha256": parsed["sha256"], "layer": layer})

    pth = parse_drill(gerber_dir / "MCU_BOARD_v19_260616-PTH.drl", True)
    npth = parse_drill(gerber_dir / "MCU_BOARD_v19_260616-NPTH.drl", False)
    annotate_npth_ownership(npth, gerbers)
    drills = [pth, npth]
    holes = hole_index(drills)
    components = build_component_manifest(gerbers, holes)
    schematic_join = join_latest_schematic(root, components)
    routes = build_copper_routes(gerbers, holes)
    patches = latest_patches()
    enrich_patch_geometry(patches, components)
    edge = next(g for g in gerbers if g["layer"] == "Edge.Cuts")
    bounds = board_bounds(edge)

    transform = {
        "sourceCoordinateSystem": "KiCad Gerber absolute millimetres; Y is negative in this export",
        "boardBoundsSourceMm": bounds,
        "toBoardLocalMm": {
            "xRight": "sourceX - boardMinX",
            "yDown": "-sourceY + boardMaxY",
            "exampleFormula": [f"x={-bounds[0]:.6f}+sourceX", f"y={bounds[3]:.6f}-sourceY"],
        },
        "mmToMil": 39.37007874015748,
        "warning": "Do not assume EasyEDA database units from Gerber units; apply the target API's documented mm/mil conversion at import time.",
    }

    shared = {
        "schemaVersion": 1,
        "generatedBy": Path(__file__).name,
        "source": {
            "role": "old_manufacturing_geometry_reference_only",
            "gerberRevision": "260616",
            "latestSchematicRevision": "260827",
            "generator": "KiCad Pcbnew 9.0.6",
            "units": "mm",
            "coordinateFormat": "4.6 absolute",
            "sourceFiles": source_files + [
                {"file": pth["file"], "sha256": pth["sha256"], "layer": "PTH.Drill"},
                {"file": npth["file"], "sha256": npth["sha256"], "layer": "NPTH.Drill"},
            ],
            "latestSchematicSemanticJoin": schematic_join,
        },
        "coordinateTransform": transform,
        "latestPatches": patches,
        "limitations": [
            "Gerber has no original footprint-library identifier; join refs to output/semantic/schematic-pages-2-6.json for latest Footprint/Package/Part Number fields.",
            "Gerber component attributes recover manufactured shapes and global placement, but not editable KiCad constraints, zones, classes, ratsnest, or schematic links.",
            "The June routing is electrically stale for the ten removed page-6 capacitors; those channels require fresh routing from the verified August schematic.",
            "TO.C, TO.P, and TO.N are independently modal and are cleared by TD; consumers must not reset a net merely because a new pad attribute appears.",
        ],
    }

    footprint_doc = {
        **shared,
        "description": "Component pad, drill, mask, paste, and silkscreen geometry extracted from the archived Gerber set.",
        "aperturesByLayer": {g["layer"]: g["apertures"] for g in gerbers},
        "drills": drills,
        "components": components,
    }
    route_doc = {
        **shared,
        "description": "Net-attributed old copper tracks, arcs, regions, conductor flashes, and vias for placement/routing comparison.",
        "edgeCuts": edge["objects"],
        "copper": routes,
        "summary": summary_counts(components, routes),
    }

    footprint_path = output_dir / "gerber-component-footprints.json"
    route_path = output_dir / "gerber-copper-routes.json"
    footprint_path.write_text(json.dumps(footprint_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    route_path.write_text(json.dumps(route_doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")

    check = {
        "footprintManifest": {"path": str(footprint_path.relative_to(root)), "bytes": footprint_path.stat().st_size, "sha256": sha256(footprint_path)},
        "routeManifest": {"path": str(route_path.relative_to(root)), "bytes": route_path.stat().st_size, "sha256": sha256(route_path)},
        "summary": route_doc["summary"],
    }
    check_path = output_dir / "gerber-reconstruction-summary.json"
    check_path.write_text(json.dumps(check, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(check, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
