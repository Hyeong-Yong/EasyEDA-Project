"""Read-only positive-coordinate bottom-silk pilot/final rendering."""

import importlib.util
import json
import math
import sys
import zipfile
from pathlib import Path

from shapely.geometry import Point

OUT = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location("j18_render", OUT / "audit-final-gerber.py")
r = importlib.util.module_from_spec(s)
sys.modules[s.name] = r
s.loader.exec_module(r)
a = r.load("j18_render_identity", r.ROOT / "scripts/audit-cn1-cutout-gerber-20261016.py")
h = r.load("j18_render_geometry", r.ROOT / "scripts/audit-multilayer-gerber-changed-copper.py")
d = r.load("j18_render_drill", r.ROOT / "scripts/audit-diagnostic-gerber-drill-zip.py")
p = a.load_parser()
source = Path(sys.argv[1]).resolve()
name = sys.argv[2]
with zipfile.ZipFile(source) as archive:
    member = next(n for n in archive.namelist() if n.endswith(".GBO"))
    data = archive.read(member)
    silk = a.parsed(data, name, p)
with zipfile.ZipFile(r.NEW) as archive:
    bottom = a.parsed(archive.read("Gerber_BottomLayer.GBL"), "bottom", p)
drills, _, _ = d.read_candidate_zip(r.NEW)
local = [v for v in drills if 36 < v.center_mm[0] < 49 and 3 < v.center_mm[1] < 7 and abs(v.diameter_mm - 1) < .0001]
pads = [o for o in bottom["objects"] if o["kind"] == "flash" and any(math.dist(o["atMm"], v.center_mm) < .002 for v in local)]
shapes = [(r.geom_of(o, bottom, h), "#d1b16a") for o in pads]
shapes += [(r.geom_of(o, silk, h), "#fafafa") for o in silk["objects"]]
shapes += [(Point(v.center_mm).buffer(v.diameter_mm / 2, quad_segs=64), "#111821") for v in local]
previews = r.render("Actual GBO physical BACKSIDE: standard Gerber Y-up plus backside X reflection; original Cu pad/drill registration", shapes, (35, 0, 50.5, 11.7), name, mirror=True, scale=110)
report = {"source": str(source), "source_sha256": r.digest(source.read_bytes()), "actual_gbo_sha256": r.digest(data),
          "stroke_count": len(silk["objects"]), "previews": previews,
          "scope": "Only actual bottom-silk parse/render; original frozen ten J18 Cu pads/drills are overlaid. No live API or native write, no copper/CAM rerun.",
          "view": "Standard Gerber Y-up plus backside X reflection; board y=0 edge at image bottom; pin1 left bottom row."}
path = OUT / (name + "-report.json")
path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"report": str(path.resolve()), "sha256": r.digest(path.read_bytes()), **report}, indent=2))
