"""Read frozen STM32 sources; write descriptive JSON only beside this script.

No native application/API, database mutation, or CAD/model assignment occurs.
The epro2 checkpoint supplies the embedded footprint/device document bodies.
Dimensions below describe 2D land-pattern graphics, not verified 3D bodies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PCB = ROOT / "output/validation/native-adc10-pcb-labtool_adc10_routed_final_saved-20261018.epru"
NET = ROOT / "output/validation/native-adc10-labtool_schematic-Protel2-20261018.net"
CHECK = ROOT / "output/checkpoints/STM32H747_labtool_adc10_routed_final_20261018.epro2"
MM = 0.0254


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_lines(lines):
    rows = {}
    for line in lines:
        if not line.strip():
            continue
        h, b = line.split("||", 1)
        h = json.loads(h)
        b = b.rstrip("|")
        key = h["type"], str(h.get("id", ""))
        if key not in rows or h.get("ticket", 0) >= rows[key][0].get("ticket", 0):
            rows[key] = h, json.loads(b) if b else None
    return {k: b for k, (h, b) in rows.items() if b is not None}


def attr_map(rows):
    attrs = defaultdict(dict)
    for (kind, rid), body in rows.items():
        if kind == "ATTR":
            attrs[body.get("parentId", "")][body["key"]] = body.get("value")
    return attrs


def sortref(ref):
    m = re.fullmatch(r"(\D+)(\d+)", ref)
    return (m[1], int(m[2])) if m else (ref, 0)


def arc_points(start, end, degrees):
    if not degrees or abs(degrees) >= 360:
        return [start, end]
    x1, y1 = start
    x2, y2 = end
    theta = math.radians(degrees)
    dx, dy = x2 - x1, y2 - y1
    chord = math.hypot(dx, dy)
    if chord == 0 or abs(math.sin(theta / 2)) < 1e-12:
        return [start, end]
    distance = chord / (2 * math.tan(theta / 2))
    cx = (x1 + x2) / 2 - dy / chord * distance
    cy = (y1 + y2) / 2 + dx / chord * distance
    initial = math.atan2(y1 - cy, x1 - cx)
    radius = math.hypot(x1 - cx, y1 - cy)
    count = max(2, math.ceil(abs(degrees) / 0.5))
    return [(cx + radius * math.cos(initial + theta * i / count),
             cy + radius * math.sin(initial + theta * i / count)) for i in range(count + 1)]


def path_points(path):
    if not isinstance(path, list) or len(path) < 2:
        return []
    if isinstance(path[0], list):
        return [p for child in path for p in path_points(child)]
    out = []
    i = 0
    while i < len(path):
        token = path[i]
        if token == "ARC" and out and i + 3 < len(path):
            end = (path[i + 2], path[i + 3])
            out.extend(arc_points(out[-1], end, path[i + 1])[1:])
            i += 4
        elif isinstance(token, (int, float)) and i + 1 < len(path) and isinstance(path[i + 1], (int, float)):
            out.append((token, path[i + 1]))
            i += 2
        else:
            i += 1
    return out


def bbox(points):
    if not points:
        return None
    xs, ys = zip(*points)
    bb = [min(xs) * MM, min(ys) * MM, max(xs) * MM, max(ys) * MM]
    return {"xmin_mm": bb[0], "ymin_mm": bb[1], "xmax_mm": bb[2], "ymax_mm": bb[3],
            "width_mm": bb[2] - bb[0], "height_mm": bb[3] - bb[1]}


def pad_points(body):
    d = body.get("defaultPad", {})
    if "path" in d:
        return path_points(d["path"])
    if "diameter" in d:
        w = h = d["diameter"]
    else:
        w, h = d.get("width", 0), d.get("height", 0)
    a = math.radians(body.get("padAngle", 0))
    # Conservative rotated rectangle around the copper pad, also for ovals.
    return [(body.get("centerX", 0) + x * math.cos(a) - y * math.sin(a),
             body.get("centerY", 0) + x * math.sin(a) + y * math.cos(a))
            for x, y in [(-w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2)]]


def graphic_points(kind, body):
    if kind in ("LINE", "ARC"):
        p = [(body["startX"], body["startY"]), (body["endX"], body["endY"])]
        if body.get("angle"):
            p = arc_points(p[0], p[1], body["angle"])
    elif kind in ("POLY", "FILL"):
        p = path_points(body.get("path", []))
    else:
        return []
    half = body.get("width", 0) / 2
    return [(x + dx, y + dy) for x, y in p for dx, dy in [(-half, -half), (half, half)]]


def geometry_summary(rows):
    padpts, drawn = [], defaultdict(list)
    pads = []
    for (kind, rid), body in rows.items():
        if kind == "PAD":
            padpts.extend(pad_points(body))
            pads.append({"id": rid, **body})
        elif kind in ("LINE", "ARC", "POLY", "FILL"):
            drawn[body.get("layerId")].extend(graphic_points(kind, body))
    holes = [p for p in pads if max((p.get("hole") or {}).get("width", 0), (p.get("hole") or {}).get("height", 0)) > 0]
    surface = [p for p in pads if p.get("layerId") in (1, 2)]
    kind = "surface-mount" if not holes else "through-hole" if not surface else "mixed surface/through-hole"
    centers = defaultdict(list)
    for p in pads:
        centers[str(p.get("num", ""))].append([p.get("centerX", 0) * MM, p.get("centerY", 0) * MM])
    centermean = {k: [sum(p[0] for p in pp) / len(pp), sum(p[1] for p in pp) / len(pp)] for k, pp in centers.items()}
    orient = {"pin_centers_mm": dict(centermean),
              "warning": "Component rotation alone is insufficient: old per-reference footprints may already contain rotated/offset package geometry."}
    if len(pads) == 2 and "1" in centermean and "2" in centermean:
        a, b = centermean["1"], centermean["2"]
        orient["two_terminal_pin1_to_pin2_axis_deg"] = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360
        orient["two_terminal_midpoint_mm"] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    return {"pad_count": len(pads), "physical_hole_count": len(holes), "mounting_geometry": kind,
            "pad_envelope_mm": bbox(padpts), "drawn_envelopes_by_layer_mm": {str(k): bbox(v) for k, v in drawn.items()},
            "orientation_hints": orient,
            "dimension_note": "2D graphics/pad bounds including stroke; not a verified component body or Z height. Arc display bounds sampled at <=0.5 degree.",
            "pads_native_mil": pads,
            "drawing_records_native_mil": [{"type": k, "id": rid, **b} for (k, rid), b in rows.items() if k in ("LINE", "ARC", "POLY", "FILL")]}


def package_group(ref, props, fp_title):
    p = props.get("Package", "")
    family = re.match(r"\D+", ref)[0]
    code = re.search(r"(?:^|[_\s])([0-9]{4})(?:$|[_\s])", p)
    if code and family in ("R", "C", "FB", "L"):
        return family + "_" + code[1]
    if family in ("R", "C", "FB", "L"):
        code = re.search(r"(?:R|C|L)(0402|0603|0805|1206)", p + " " + fp_title)
        if code:
            return family + "_" + code[1]
    title = re.sub(r"^[A-Z]+\d+_", "", fp_title)
    title = re.sub(r"^2_CustomLibrary:", "", title)
    return title or p or "unclassified"


def main():
    assert sha(PCB) == "b7c6b99df160aaed2bb1f91717c2bde25e379bfdba88ec23dea5b4fdb7548d0f"
    assert sha(NET) == "dd848d6113c5ec2a0835c128ed664aff57e1df0f7967b9571fbd861d7ab4c12d"
    assert sha(CHECK) == "afe1b3ebefdce0cb36eb040363c2c272dc4cf3b026746c0a2ee15b16079f8115"
    pcb = parse_lines(PCB.read_text(encoding="utf-8").splitlines())
    attrs = attr_map(pcb)
    components = {rid: b for (kind, rid), b in pcb.items() if kind == "COMPONENT"}
    need_fp = {attrs[c]["Footprint"] for c in components}
    need_dev = {attrs[c]["Device"] for c in components}
    docs = {}
    current = None
    lines = []
    with zipfile.ZipFile(CHECK) as archive:
        filename = next(n for n in archive.namelist() if n.endswith(".epru"))
        with archive.open(filename) as handle:
            for raw_line in handle:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith('{"type":"DOCHEAD"}'):
                    if current is not None and lines:
                        docs[current] = parse_lines(lines)
                    head = json.loads(line.split("||", 1)[1].rstrip("|"))
                    current = (head["docType"], head["uuid"])
                    keep = (current[0] == "FOOTPRINT" and current[1] in need_fp) or (current[0] == "DEVICE" and current[1] in need_dev) or current == ("PCB", "0ac2a19168000d8e")
                    lines = [line] if keep else []
                elif lines:
                    lines.append(line)
            if current is not None and lines:
                docs[current] = parse_lines(lines)
    assert {uuid for kind, uuid in docs if kind == "FOOTPRINT"} == need_fp
    for key, val in pcb.items():
        if key[0] in ("COMPONENT", "ATTR", "PAD_NET"):
            assert docs["PCB", "0ac2a19168000d8e"][key] == val, key
    netprops = {}
    for match in re.finditer(r"(?ms)^\[\s*\n(.*?)^\]", NET.read_text(encoding="utf-8-sig")):
        ll = match[1].splitlines()
        props = dict(zip(ll[::2], ll[1::2]))
        if "DESIGNATOR" in props:
            netprops[props["DESIGNATOR"]] = props
    fps = {}
    for uuid in sorted(need_fp):
        rows = docs["FOOTPRINT", uuid]
        meta = rows.get(("META", "META"), {})
        geom = geometry_summary(rows)
        modelkeys = {k: v for k, v in meta.items() if re.search(r"(?i)3d|height|model|step", k)}
        semantic = sorted(((k, b) for (k, rid), b in rows.items() if k in ("PAD", "LINE", "ARC", "POLY", "FILL")), key=lambda v: json.dumps(v, sort_keys=True))
        fps[uuid] = {"uuid": uuid, "title": meta.get("title"), "meta": meta,
                     "geometry_sha256": hashlib.sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest(),
                     "model_height_metadata": modelkeys, "verified_body_height_mm": None, **geom}
    parts = []
    groups = defaultdict(list)
    for cid, b in components.items():
        at = attrs[cid]
        ref = at["Designator"]
        props = netprops[ref]
        fp = fps[at["Footprint"]]
        dmeta = docs["DEVICE", at["Device"]].get(("META", "META"), {})
        dmodel = {k: v for k, v in dmeta.get("attributes", {}).items() if re.search(r"(?i)3d|height|model|step", k)}
        group = package_group(ref, props, fp["title"] or "")
        p = {"ref": ref, "component_id": cid, "unique_id": b.get("attrs", {}).get("Unique ID"),
             "value": props.get("Value"), "part_number": props.get("Part Number"), "package": props.get("Package"),
             "description": props.get("Description"), "dnp": props.get("DNP", "no").lower() == "yes",
             "footprint_uuid": at["Footprint"], "footprint_title": fp["title"], "device_uuid": at["Device"],
             "package_group": group, "side": "top" if b["layerId"] == 1 else "bottom" if b["layerId"] == 2 else str(b["layerId"]),
             "x_mm": b["x"] * MM, "y_mm": b["y"] * MM, "rotation_deg": b.get("angle", 0),
             "verified_body_height_mm": None, "model_height_metadata": {**dmodel, **{k: v for k, v in b.get("attrs", {}).items() if re.search(r"(?i)3d|height|model|step", k)}},
             "pad_envelope_mm": fp["pad_envelope_mm"], "drawn_envelopes_by_layer_mm": fp["drawn_envelopes_by_layer_mm"],
             "orientation_hints": fp["orientation_hints"],
             "mounting_geometry": fp["mounting_geometry"]}
        parts.append(p)
        groups[group].append(p)
    parts.sort(key=lambda p: sortref(p["ref"]))
    assert len(parts) == 437 and len({p["ref"] for p in parts}) == 437
    group_info = [{"group": g, "count": len(pp), "fitted_count": sum(not p["dnp"] for p in pp),
                   "refs": sorted([p["ref"] for p in pp], key=sortref), "part_numbers": sorted({p["part_number"] for p in pp if p["part_number"]}),
                   "footprint_uuids": sorted({p["footprint_uuid"] for p in pp}),
                   "packages": sorted({p["package"] for p in pp if p["package"]})} for g, pp in sorted(groups.items())]
    summary = {"schema": "stm32-final-pcb-3d-source-inventory-v1", "source_read_only": True, "native_calls": 0,
               "sources": [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in (PCB, NET, CHECK)],
               "component_count": len(parts), "fitted_components": sum(not p["dnp"] for p in parts),
               "dnp_refs": [p["ref"] for p in parts if p["dnp"]], "unique_used_footprints": len(fps),
               "side_counts": dict(Counter(p["side"] for p in parts)), "package_groups": group_info,
               "height_metadata_count": sum(bool(p["model_height_metadata"]) for p in parts),
               "footprint_model_height_metadata_count": sum(bool(f["model_height_metadata"]) for f in fps.values()),
               "part_attribute_conflicts": [{"ref": "U8", "netlist_package_attribute": "SOIC-8", "actual_footprint_title": "SOIC-16 [3.9mm x 9.9mm_P1.27mm]", "actual_physical_pads": 16,
                                              "action": "Use actual 16-pin geometry/CH340C identity for the model, not the stale Package attribute."}],
               "limitations": ["Uses the frozen final native project checkpoint for embedded libraries. The eprj2 direct documents/components tables are empty; no database writes or history replay were attempted.",
                               "All component positions, attributes and PAD_NET records match the saved final PCB checkpoint.",
                               "2D graphics and pad envelopes are not verified component body dimensions or 3D height.",
                               "No actual 3D model was assigned or validated by this inventory. DNP parts are physical footprints but should be omitted from an as-fitted rendering.",
                               "Native footprint geometry coordinates are mil; CANVAS unit is the editor display setting."]}
    for name, obj in [("components-437.json", parts), ("footprints-288.json", fps), ("summary.json", summary)]:
        path = OUT / name
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("component_count", "fitted_components", "dnp_refs", "unique_used_footprints", "side_counts", "height_metadata_count", "footprint_model_height_metadata_count")}))
    print(json.dumps({g["group"]: g["count"] for g in group_info}))


if __name__ == "__main__":
    main()
