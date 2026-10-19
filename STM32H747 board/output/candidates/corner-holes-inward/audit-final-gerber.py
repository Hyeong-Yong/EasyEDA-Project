"""Independent read-only actual-Gerber corner/drill audit and vector previews."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path

from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
OLD = ROOT / "output/validation/STM32H747_multilayer_drc_pass_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
NEW = ROOT / "output/validation/STM32H747_corners_j18_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
SOURCE = ROOT / "output/validation/native-j18-bottom-title-20261016.epru"
PLAN = OUT / "plan.json"
REPORT = OUT / "actual-gerber-final-audit.json"
MEMBERS = ["Gerber_TopLayer.GTL", "Gerber_InnerLayer1.G1", "Gerber_InnerLayer2.G2",
           "Gerber_InnerLayer3.G3", "Gerber_InnerLayer4.G4", "Gerber_BottomLayer.GBL"]
OLD_CENTRES = [(4, 4), (4, 150), (96, 4), (96, 150)]
NEW_CENTRES = [(5, 5), (5, 149), (95, 5), (95, 149)]
MM = .0254


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def records(path):
    out = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            h, b = line.split("||", 1)
            out.append((json.loads(h), json.loads(b.rstrip("|"))))
    return out


def drill_key(item):
    return (item.category, item.center_mm, item.diameter_mm, item.start_mm, item.end_mm)


def native_points(path):
    require(path[2] == "L" and all(isinstance(v, (int, float)) for v in path[3:]), "Unexpected native void command")
    return [(path[0] * MM, path[1] * MM), *[(path[i] * MM, path[i + 1] * MM) for i in range(3, len(path), 2)]]


def svg_geometry(geometry, fill):
    if geometry.is_empty:
        return ""
    if geometry.geom_type != "Polygon":
        return "".join(svg_geometry(part, fill) for part in geometry.geoms)
    rings = [geometry.exterior, *geometry.interiors]
    d = " ".join("M " + " L ".join(f"{x:.6f},{y:.6f}" for x, y in ring.coords) + " Z" for ring in rings)
    return f'<path d="{d}" fill="{fill}" fill-rule="evenodd"/>'


def geom_of(obj, layer, helper):
    if obj["kind"] == "region":
        return helper.region_geometry(obj)
    ap = layer["apertures"][obj["aperture"]]
    shape, p = ap["template"], ap["paramsMm"]
    if obj["kind"] == "flash":
        x, y = obj["atMm"]
        if shape == "C":
            return Point(x, y).buffer(p[0] / 2, quad_segs=64)
        if shape == "R":
            return box(x - p[0] / 2, y - p[1] / 2, x + p[0] / 2, y + p[1] / 2)
        if shape == "O":
            if p[0] >= p[1]:
                return LineString([(x - (p[0] - p[1]) / 2, y), (x + (p[0] - p[1]) / 2, y)]).buffer(p[1] / 2, quad_segs=32)
            return LineString([(x, y - (p[1] - p[0]) / 2), (x, y + (p[1] - p[0]) / 2)]).buffer(p[0] / 2, quad_segs=32)
        raise RuntimeError(f"Unsupported visible flash: {shape}")
    require(shape == "C", "Unsupported non-circular stroke")
    return LineString(helper.segment_points(obj)).buffer(p[0] / 2, quad_segs=16)


def pil_save(svg_shapes, bounds, path, mirror=False, scale=100):
    sys.path.append(r"C:\Users\jjj\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages")
    from PIL import Image, ImageDraw
    xmin, ymin, xmax, ymax = bounds
    ss = 2
    image = Image.new("RGB", (round((xmax - xmin) * scale * ss), round((ymax - ymin) * scale * ss)), "#123b36")
    draw = ImageDraw.Draw(image)
    def xy(x, y):
        return ((xmax - x if mirror else x - xmin) * scale * ss, (ymax - y) * scale * ss)
    def poly(geometry, colour):
        if geometry.is_empty:
            return
        if geometry.geom_type != "Polygon":
            for part in geometry.geoms:
                poly(part, colour)
            return
        draw.polygon([xy(x, y) for x, y in geometry.exterior.coords], fill=colour)
        for ring in geometry.interiors:
            draw.polygon([xy(x, y) for x, y in ring.coords], fill="#123b36")
    for geometry, colour in svg_shapes:
        poly(geometry, colour)
    image.resize((image.width // ss, image.height // ss), Image.Resampling.LANCZOS).save(path)


def render(title, shapes, bounds, name, mirror=False, scale=100):
    xmin, ymin, xmax, ymax = bounds
    transform = f"translate({xmin+xmax} {ymin+ymax}) scale(-1 -1)" if mirror else f"translate(0 {ymin+ymax}) scale(1 -1)"
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{xmin} {ymin} {xmax-xmin} {ymax-ymin}" width="{(xmax-xmin)*scale}" height="{(ymax-ymin)*scale}"><title>{title}</title><rect x="{xmin}" y="{ymin}" width="{xmax-xmin}" height="{ymax-ymin}" fill="#123b36"/><g transform="{transform}">'
    svg += "".join(svg_geometry(g, colour) for g, colour in shapes)
    svg += "</g></svg>"
    sp, pp = OUT / (name + ".svg"), OUT / (name + ".png")
    sp.write_text(svg, encoding="utf-8")
    pil_save(shapes, bounds, pp, mirror=mirror, scale=scale)
    return [{"path": str(p.resolve()), "sha256": digest(p.read_bytes())} for p in (sp, pp)]


def main():
    a = load("corner_gerber_identity", ROOT / "scripts/audit-cn1-cutout-gerber-20261016.py")
    helper = load("corner_gerber_geometry", ROOT / "scripts/audit-multilayer-gerber-changed-copper.py")
    drill = load("corner_actual_drill", ROOT / "scripts/audit-diagnostic-gerber-drill-zip.py")
    parser = a.load_parser()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    native = {str(h.get("id")): b for h, b in records(SOURCE)}
    old_drills, old_meta, _ = drill.read_candidate_zip(OLD)
    new_drills, new_meta, _ = drill.read_candidate_zip(NEW)
    dc_old = Counter(map(drill_key, old_drills))
    dc_new = Counter(map(drill_key, new_drills))
    removed, added = list((dc_old - dc_new).elements()), list((dc_new - dc_old).elements())
    require(len(old_drills) == len(new_drills) == 793, "Drill count is not 793")
    require(len(removed) == len(added) == 4, "Not exactly four drill changes")
    for values, centres in ((removed, OLD_CENTRES), (added, NEW_CENTRES)):
        require(all(v[0] == "npth_round" and abs(v[2] - 3.2) < 1e-8 for v in values), "Unexpected changed drill type or size")
        require(sorted(v[1] for v in values) == sorted(centres), "Unexpected mounting-hole coordinates")
    dr = {"status": "pass", "old_count": 793, "new_count": 793, "unchanged_geometry_count": 789,
          "moved_npth_diameter_mm": 3.2, "old_centres_mm": OLD_CENTRES, "new_centres_mm": NEW_CENTRES,
          "inventory_before": drill.inventory(old_drills), "inventory_after": drill.inventory(new_drills),
          "supplemental_members": [v for v in new_meta if not v.get("includedInCanonicalInventory", True)]}
    rows, final_layers, cached_regions = [], {}, {}
    with zipfile.ZipFile(OLD) as old, zipfile.ZipFile(NEW) as new:
        for member in MEMBERS:
            before = a.parsed(old.read(member), member, parser)
            after = a.parsed(new.read(member), member, parser)
            final_layers[member] = after
            bh, ah = a.object_hashes(before), a.object_hashes(after)
            bc, ac = Counter(bh), Counter(ah)
            missing, present = bc - ac, ac - bc
            bi = [i for i, h in enumerate(bh) if missing[h]]
            ai = [i for i, h in enumerate(ah) if present[h]]
            require(len(bi) == len(ai) == 5, f"Unexpected changed object count in {member}: {bi}/{ai}")
            br = [i for i in bi if before["objects"][i]["kind"] == "region"]
            ar = [i for i in ai if after["objects"][i]["kind"] == "region"]
            require(len(br) == len(ar) == 1, "Expected one target plane region")
            for layer, inds, region, centres in ((before, bi, br[0], OLD_CENTRES), (after, ai, ar[0], NEW_CENTRES)):
                flashes = [layer["objects"][i] for i in inds if i != region]
                require(sorted(tuple(o["atMm"]) for o in flashes) == sorted(centres), "Unexpected changed copper flash position")
                require(all(o["kind"] == "flash" and o["polarity"] == "dark" and a.shape(layer["apertures"][o["aperture"]]) == {"template": "C", "paramsMm": [3.2], "function": None} for o in flashes), "Unexpected changed copper flash shape")
            unchanged_sequence = [h for i, h in enumerate(bh) if i not in bi] == [h for i, h in enumerate(ah) if i not in ai]
            require(unchanged_sequence, "Non-target Gerber objects differ")
            old_g = helper.region_geometry(before["objects"][br[0]])
            new_g = helper.region_geometry(after["objects"][ar[0]])
            cached_regions[member] = (ar[0], new_g)
            allowed = unary_union([box(x - 4.001, y - 4.001, x + 4.001, y + 4.001).union(Point(nx, ny).buffer(3.601, quad_segs=128)) for (x, y), (nx, ny) in zip(OLD_CENTRES, NEW_CENTRES)])
            outside = old_g.symmetric_difference(new_g).difference(allowed)
            escaped = outside.area
            outside_quantization_tube = outside.difference(old_g.boundary.buffer(.00002).union(new_g.boundary.buffer(.00002))).area
            residual = outside
            overlap_indices = []
            if escaped > .00001:
                window = box(*outside.bounds).buffer(.001)
                for oi, obj in enumerate(after["objects"]):
                    if oi in ai or obj["polarity"] != "dark":
                        continue
                    pts = parser.primitive_points(obj)
                    if not pts:
                        continue
                    ex, ey = after["apertures"].get(obj.get("aperture"), {}).get("halfExtentMm", [0, 0])
                    extent = box(min(p[0] for p in pts) - ex, min(p[1] for p in pts) - ey, max(p[0] for p in pts) + ex, max(p[1] for p in pts) + ey)
                    if not extent.intersects(window):
                        continue
                    try:
                        geometry = geom_of(obj, after, helper)
                    except RuntimeError:
                        continue
                    if geometry.intersects(residual):
                        overlap_indices.append(oi)
                        residual = residual.difference(geometry)
                print(json.dumps({"member": member, "outside_area": escaped, "outside_copper_union_residual_area": residual.area,
                                  "overlap_indices": overlap_indices, "outside_parts": [{"bounds": list(p.bounds), "area": p.area} for p in sorted(helper.parts(outside), key=lambda p: p.area, reverse=True)[:12]]}), flush=True)
            change = next(c for c in plan["fill_changes"] if c["after"]["layerId"] == {MEMBERS[0]: 1, MEMBERS[1]: 15, MEMBERS[2]: 16, MEMBERS[3]: 17, MEMBERS[4]: 18, MEMBERS[5]: 2}[member])
            expected_paths = change["after"]["path"][len(change["before"]["path"]):]
            holes = [Polygon(ring) for part in helper.parts(new_g) for ring in part.interiors]
            checks = []
            for path in expected_paths:
                expected = Polygon(native_points(path))
                centre = expected.centroid
                matches = [h for h in holes if h.covers(centre)]
                require(len(matches) == 1, "New void missing or ambiguous in actual Gerber")
                actual = matches[0]
                err = max(abs(x - y) for x, y in zip(expected.bounds, actual.bounds))
                area_err = expected.symmetric_difference(actual).area
                require(err < .00002 and area_err < .0002, f"Void differs from reviewed plan: {err}/{area_err}")
                radial = min(centre.distance(Point(x, y)) for x, y in actual.exterior.coords)
                require(radial > 3.60040, f"Void radius too small: {radial}")
                require(new_g.intersection(centre.buffer(3.60040, quad_segs=128)).area < 1e-8, "Plane intrudes into new void")
                checks.append({"centre_mm": list(centre.coords)[0], "actual_bounds_mm": list(actual.bounds),
                               "bounds_max_error_mm": err, "symmetric_difference_area_mm2": area_err,
                               "minimum_vertex_radius_mm": radial, "npth_edge_to_void_boundary_mm": centre.distance(actual.boundary) - 1.6,
                               "status": "pass"})
            if member == MEMBERS[2]:
                require(len(checks) == 3 and new_g.distance(Point(95, 5)) > 5, "Unexpected In2 upper-right corner copper")
            else:
                require(len(checks) == 4, "Expected four new plane voids")
            rows.append({"member": member, "status": "pass", "objects_before": len(bh), "objects_after": len(ah),
                         "unchanged_object_sequence_exact": unchanged_sequence, "unchanged_objects": len(bh) - 5,
                         "changed_region_before_index": br[0], "changed_region_after_index": ar[0],
                         "changed_drill_flash_count": 4, "plane_delta_outside_corner_regions_mm2": escaped,
                         "outside_corner_delta_outside_0_00002mm_boundary_tube_mm2": outside_quantization_tube,
                         "outside_corner_delta_remaining_after_other_unchanged_copper_mm2": residual.area,
                         "unchanged_copper_covering_export_region_deltas_indices": overlap_indices,
                         "outside_corner_region_delta_parts": [{"bounds_mm": list(p.bounds), "area_mm2": p.area} for p in sorted(helper.parts(outside), key=lambda p: p.area, reverse=True)[:12]],
                         "new_closed_voids": checks})
            print(f"Verified {member}: {len(checks)} actual closed voids; {len(bh)-5} non-target objects exact", flush=True)
        outline = a.parsed(new.read("Gerber_BoardOutlineLayer.GKO"), "outline", parser)
        old_outline = a.parsed(old.read("Gerber_BoardOutlineLayer.GKO"), "outline", parser)
        require(a.object_hashes(outline) == a.object_hashes(old_outline), "Outline changed")
        silk = a.parsed(new.read("Gerber_BottomSilkscreenLayer.GBO"), "silk", parser)
        require(all(o["kind"] == "line" and o["polarity"] == "dark" for o in silk["objects"]), "Unsupported bottom-silk object")
        title_strokes = [o for o in silk["objects"] if min(o["startMm"][1], o["endMm"][1]) > 9.8]
        require(len(title_strokes) == 83, "J18 SPI2 title missing from actual Gerber")
        strings = [b for b in native.values() if b.get("text") and b.get("layerId") == 4]
        require(len(strings) == 21 and all(s.get("mirror") is True for s in strings), "Expected 21 mirrored native labels")
        title = [s for s in strings if s["text"] == "J18 SPI2"]
        require(len(title) == 1, "Native title mismatch")
        local_drills = [d for d in new_drills if 36 < d.center_mm[0] < 49 and 3 < d.center_mm[1] < 7 and abs(d.diameter_mm - 1) < .0001]
        require(len(local_drills) == 10, f"J18 expected 10 physical drills, got {len(local_drills)}")
        bottom = final_layers[MEMBERS[-1]]
        pad_flashes = [o for o in bottom["objects"] if o["kind"] == "flash" and any(math.dist(o["atMm"], d.center_mm) < .002 for d in local_drills)]
        require(len(pad_flashes) == 10, "J18 expected ten exported bottom pad flashes")
        shapes = [(geom_of(o, bottom, helper), "#d1b16a") for o in pad_flashes]
        shapes += [(geom_of(o, silk, helper), "#fafafa") for o in silk["objects"]]
        shapes += [(Point(d.center_mm).buffer(d.diameter_mm / 2, quad_segs=64), "#111821") for d in local_drills]
        previews = render("Actual GBO + bottom copper pads + Excellon drills; BACKSIDE view (Gerber Y-up + X reflected)", shapes, (35, 0, 50.5, 11.7), "j18-actual-gerber-backside", mirror=True, scale=110)
        top = final_layers[MEMBERS[0]]
        for corner, centre in enumerate(NEW_CENTRES):
            x, y = centre
            bounds = (0 if x < 50 else 90, 0 if y < 75 else 144, 10 if x < 50 else 100, 10 if y < 75 else 154)
            window = box(*bounds)
            shapes = []
            for i, obj in enumerate(top["objects"]):
                pts = parser.primitive_points(obj)
                if not pts:
                    continue
                bx = [p[0] for p in pts]; by = [p[1] for p in pts]
                if max(bx) < bounds[0] - 2 or min(bx) > bounds[2] + 2 or max(by) < bounds[1] - 2 or min(by) > bounds[3] + 2:
                    continue
                geometry = cached_regions[MEMBERS[0]][1] if i == cached_regions[MEMBERS[0]][0] else geom_of(obj, top, helper)
                if geometry.intersects(window):
                    shapes.append((geometry.intersection(window), "#d1b16a" if obj["polarity"] == "dark" else "#123b36"))
            shapes += [(geom_of(o, outline, helper).intersection(window), "#f2f2f2") for o in outline["objects"]]
            shapes += [(Point(d.center_mm).buffer(d.diameter_mm / 2, quad_segs=64).intersection(window), "#111821") for d in new_drills if window.covers(Point(d.center_mm))]
            previews += render(f"Actual top copper, unchanged board outline and actual drills, corner {corner+1}", shapes, bounds, f"corner-{corner+1}-actual-gerber", scale=90)
    checks = {"all_793_drills_only_four_approved_npth_moves": True, "six_copper_layers_only_local_plane_voids_and_four_npth_flashes_changed": all(r["outside_corner_delta_remaining_after_other_unchanged_copper_mm2"] < .00001 and r["outside_corner_delta_outside_0_00002mm_boundary_tube_mm2"] < 1e-10 for r in rows),
              "all_23_new_closed_voids_match_reviewed_plan": sum(len(r["new_closed_voids"]) for r in rows) == 23,
              "all_other_copper_objects_exact_sequence": all(r["unchanged_object_sequence_exact"] for r in rows),
              "outline_exact_unchanged": True, "actual_bottom_silk_includes_title_83_strokes": True,
              "all_21_native_labels_mirrored": True, "j18_ten_actual_bottom_pads_and_drills_overlaid": True}
    report = {"status": "pass-diagnostic-not-manufacturing-approved" if all(checks.values()) else "caveat-noncorner-plane-export-delta-needs-review", "manufacturing_approved": False,
              "inputs": {key: {"path": str(p.resolve()), "sha256": digest(p.read_bytes())} for key, p in {"old_zip": OLD, "new_zip": NEW, "native_title_source": SOURCE, "reviewed_plan": PLAN, "audit_script": Path(__file__)}.items()},
              "checks": checks, "drills": dr, "copper_layers": rows,
              "bottom_silk": {"actual_stroke_count": len(silk["objects"]), "actual_title_strokes": len(title_strokes), "native_texts": [s["text"] for s in strings], "backside_render": "Standard Gerber Y-up displayed with screen Y inversion; bottom side adds X reflection"},
              "previews": previews,
              "limitations": ["No live EasyEDA calls or native project writes. No TEST_DAC8562 access.",
                              "Actual Gerber native NPTH pads export as dark diameter-3.2mm flashes; physical NPTH drilling removes them. Plane void geometry is checked independently, and render overlays actual drills.",
                              "Region self-touch bridge paths are interpreted with the existing Shapely polygon repair; circle native coordinates quantize at 0.0001mil and Gerber at 0.00001mm.",
                              "This bounded export comparison is not full CAM, DRC, netlist/ECO, impedance or manufacturing approval."]}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(REPORT.resolve()), "sha256": digest(REPORT.read_bytes()), "checks": checks}, indent=2))


def finalize_j18_preview_qa():
    a = load("corner_gerber_preview_identity", ROOT / "scripts/audit-cn1-cutout-gerber-20261016.py")
    helper = load("corner_preview_geometry", ROOT / "scripts/audit-multilayer-gerber-changed-copper.py")
    drill = load("corner_preview_drill", ROOT / "scripts/audit-diagnostic-gerber-drill-zip.py")
    parser = a.load_parser()
    drills, _, _ = drill.read_candidate_zip(NEW)
    local = [d for d in drills if 36 < d.center_mm[0] < 49 and 3 < d.center_mm[1] < 7 and abs(d.diameter_mm - 1) < .0001]
    with zipfile.ZipFile(NEW) as archive:
        bottom = a.parsed(archive.read(MEMBERS[-1]), "bottom", parser)
        silk = a.parsed(archive.read("Gerber_BottomSilkscreenLayer.GBO"), "silk", parser)
    pads = [o for o in bottom["objects"] if o["kind"] == "flash" and any(math.dist(o["atMm"], d.center_mm) < .002 for d in local)]
    shapes = [(geom_of(o, bottom, helper), "#d1b16a") for o in pads]
    shapes += [(geom_of(o, silk, helper), "#fafafa") for o in silk["objects"]]
    shapes += [(Point(d.center_mm).buffer(d.diameter_mm / 2, quad_segs=64), "#111821") for d in local]
    extra = render("Actual bottom Gerber TOP PROJECTION (NOT physical backside); Y-up, no X reflection", shapes, (35, 0, 50.5, 11.7), "j18-actual-gerber-top-projection-NOT-backside", mirror=False, scale=110)
    heights = []
    for name, y in (("1 PD3", 1.15), ("SCK", 2.15)):
        strokes = [o for o in silk["objects"] if all(abs(p[0] - 47.765) < 1.2 and abs(p[1] - y) < .4 for p in (o["startMm"], o["endMm"]))]
        lo = min(min(o["startMm"][1], o["endMm"][1]) - silk["apertures"][o["aperture"]]["paramsMm"][0] / 2 for o in strokes)
        hi = max(max(o["startMm"][1], o["endMm"][1]) + silk["apertures"][o["aperture"]]["paramsMm"][0] / 2 for o in strokes)
        heights.append({"text": name, "actual_stroke_count": len(strokes), "ink_y_min_mm": lo, "ink_y_max_mm": hi, "ink_height_mm": hi - lo})
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    report["inputs"]["audit_script"]["sha256"] = digest(Path(__file__).read_bytes())
    report["checks"]["actual_bottom_text_physically_backside_readable"] = False
    report["bottom_silk"]["actual_ink_height_measurements"] = heights
    report["bottom_silk"]["visual_qa"] = {
        "backside_text_readable": False,
        "observed": "Standard Gerber Y-up view plus bottom-side X reflection produces horizontally mirrored lettering. Without X reflection, lettering is readable in TOP PROJECTION. Native STRING mirror=true is confirmed, but it does not establish physical backside legibility in this actual export.",
        "physical_edge_orientation": "For both conventional Y-up previews, the physical board y=0 edge is at the bottom of the image, y increases upward. The backside preview additionally reflects X; native x=47.765 pin1 appears in the left column. The readable top projection has pin1 in the right column and is not labeled backside.",
        "no_native_change": True,
    }
    report["previews"] = [p for p in report["previews"] if "top-projection-NOT-backside" not in p["path"]] + extra
    report["status"] = "caveat-noncorner-plane-export-delta-and-backside-text-orientation-needs-review"
    report["limitations"].append("Cause of noncorner changed-plane REGION deltas is unconfirmed. Native preserved L-only polygon thermal contours do not prove exact exported region equivalence. No blanket manufacturing/CAM pass is claimed.")
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(REPORT.resolve()), "sha256": digest(REPORT.read_bytes()), "ink_height_measurements": heights}, indent=2))


if __name__ == "__main__":
    if "--j18-qa-only" not in sys.argv:
        main()
    finalize_j18_preview_qa()
