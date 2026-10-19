"""Read-only comparison of two explicit bottom-silk manufacturing mirror flags."""

import importlib.util
import json
import sys
import zipfile
from pathlib import Path
from shapely import affinity

from shapely.geometry import Point

OUT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("corner_renderer", OUT / "audit-final-gerber.py")
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)
a = r.load("variant_identity", r.ROOT / "scripts/audit-cn1-cutout-gerber-20261016.py")
h = r.load("variant_geometry", r.ROOT / "scripts/audit-multilayer-gerber-changed-copper.py")
d = r.load("variant_drill", r.ROOT / "scripts/audit-diagnostic-gerber-drill-zip.py")
p = a.load_parser()
with zipfile.ZipFile(r.NEW) as archive:
    baseline = a.parsed(archive.read("Gerber_BottomSilkscreenLayer.GBO"), "default", p)
    bottom = a.parsed(archive.read("Gerber_BottomLayer.GBL"), "bottom", p)
drills, _, _ = d.read_candidate_zip(r.NEW)
local = [v for v in drills if 36 < v.center_mm[0] < 49 and 3 < v.center_mm[1] < 7 and abs(v.diameter_mm - 1) < .0001]
pads = [o for o in bottom["objects"] if o["kind"] == "flash" and any(__import__("math").dist(o["atMm"], v.center_mm) < .002 for v in local)]
pad_shapes = [(r.geom_of(o, bottom, h), "#d1b16a") for o in pads]
drill_shapes = [(Point(v.center_mm).buffer(v.diameter_mm / 2, quad_segs=64), "#111821") for v in local]
rows = []
for variant, flag in (("nomirror", False), ("mirror", True)):
    path = r.ROOT / f"output/validation/STM32H747_j18_silk_{variant}_DIAGNOSTIC_NOT_FOR_FAB.zip"
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        member = next(name for name in members if name.endswith(".GBO"))
        data = archive.read(member)
    layer = a.parsed(data, variant, p)
    negative = flag is True
    shapes = ([] if negative else pad_shapes) + [(r.geom_of(o, layer, h), "#fafafa") for o in layer["objects"]] + ([] if negative else drill_shapes)
    bounds = (-50.5, 0, -35, 11.7) if negative else (35, 0, 50.5, 11.7)
    previews = []
    for view, reflect in (("top", False), ("backside", True)):
        previews += r.render(f"Actual GBO, export isMirror={flag}, conventional Gerber Y-up {view} view; {'NEGATIVE X FILM, not registered to original pads' if negative else 'original pad/drill registration'}", shapes, bounds, f"j18-{variant}-export-{view}" + ("-negative-x-film" if negative else ""), mirror=reflect, scale=110)
    points = [pt for obj in layer["objects"] for pt in p.primitive_points(obj)]
    rows.append({"variant": variant, "export_layer4_isMirror": flag, "zip": str(path.resolve()), "sha256": r.digest(path.read_bytes()), "member": member,
                 "gbo_sha256": r.digest(data), "object_count": len(layer["objects"]),
                 "default_GBO_geometry_object_sequence_exact": a.object_hashes(layer) == a.object_hashes(baseline),
                 "max_same_sequence_endpoint_difference_vs_default_after_unreflecting_export_x_mm": max(__import__("math").dist((( -o[key][0] if flag else o[key][0]), o[key][1]), b[key]) for o, b in zip(layer["objects"], baseline["objects"]) for key in ("startMm", "endMm")),
                 "original_positive_x_pad_drill_registration_retained": not negative,
                 "physical_backside_text_readable_from_visual_qa": negative,
                 "interpretation": "isMirror=true reflects whole output film into negative X, not just glyphs; it is not a registration-preserving fix" if negative else "isMirror=false retains film registration but native mirror=true text is mirrored from physical backside",
                 "stroke_centreline_bounds_mm": [min(q[0] for q in points), min(q[1] for q in points), max(q[0] for q in points), max(q[1] for q in points)],
                 "previews": previews})
report = {"scope": "Read-only GBO export-option comparison; native STRINGs unchanged. No EasyEDA/API calls.",
          "input_default_zip": {"path": str(r.NEW.resolve()), "sha256": r.digest(r.NEW.read_bytes())},
          "variants": rows,
          "coordinate_convention": "Gerber positive Y is upward; top view inverts Y to image coordinates. Physical backside additionally reflects X. y=0 board edge is at image bottom. Native pin1 x=47.765 is right in top view and left in backside view.",
          "manufacturing_approved": False}
out = OUT / "actual-j18-export-mirror-variants.json"
out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(out.resolve()), "sha256": r.digest(out.read_bytes()), "variants": [{k: v for k, v in row.items() if k != "previews"} for row in rows]}, indent=2))
