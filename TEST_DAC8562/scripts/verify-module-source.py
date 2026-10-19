"""Independently audit the exported EasyEDA page's pin/wire geometry."""
import itertools
import json
import math
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "output" / "stm32h747-dac-sma"
with zipfile.ZipFile(FOLDER / "STM32H747_DAC_SMA_2CH_DRAFT.epro2") as archive:
    source = archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode()
docs, doc = [], None
for line in source.splitlines():
    left, right = line.split("||", 1)
    header, payload = json.loads(left), json.loads(right.rstrip("|"))
    if header["type"] == "DOCHEAD":
        doc = []
        docs.append(doc)
    doc.append((header, payload))
index = {d[0][1]["uuid"]: d for d in docs}
page = next(d for d in docs if d[0][1]["docType"] == "SCH_PAGE")
attrs = {}
for h, p in page:
    if h["type"] == "ATTR":
        attrs.setdefault(p["parentId"], {})[p["key"]] = p["value"]
segments = []
for h, p in page:
    if h["type"] == "LINE" and p.get("lineGroup") in attrs:
        segments.append((attrs[p["lineGroup"]]["NET"], (p["startX"], p["startY"]), (p["endX"], p["endY"])))

def on(point, a, b):
    return min(a[0], b[0]) <= point[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= point[1] <= max(a[1], b[1]) and abs((point[0]-a[0])*(b[1]-a[1])-(point[1]-a[1])*(b[0]-a[0])) < 1e-6

def intersections(a, b, c, d):
    points = {p for p in (a, b, c, d) if on(p, a, b) and on(p, c, d)}
    if a[0] == b[0] and c[1] == d[1]:
        p = (a[0], c[1])
        if on(p, a, b) and on(p, c, d): points.add(p)
    if a[1] == b[1] and c[0] == d[0]:
        p = (c[0], a[1])
        if on(p, a, b) and on(p, c, d): points.add(p)
    return points

collisions = []
for (n1, a, b), (n2, c, d) in itertools.combinations(segments, 2):
    if n1 != n2:
        points = intersections(a, b, c, d)
        if points:
            collisions.append({"nets": [n1, n2], "points": sorted(points)})
actual, floating, multiple = {}, [], []
for h, p in page:
    if h["type"] != "COMPONENT": continue
    props = attrs[h["id"]]
    sym = index[props["Symbol"]]
    nums = {v["parentId"]: str(v["value"]) for t, v in sym if t["type"] == "ATTR" and v.get("key") == "Pin Number"}
    angle = math.radians(p["rotation"])
    for t, v in sym:
        if t["type"] != "PIN" or v.get("partId") != p["partId"]: continue
        x = round(p["x"] + v["x"]*math.cos(angle) - v["y"]*math.sin(angle), 6)
        y = round(p["y"] + v["x"]*math.sin(angle) + v["y"]*math.cos(angle), 6)
        name = props["Designator"]+"."+nums[t["id"]]
        nets = {n for n, a, b in segments if on((x, y), a, b)}
        if not nets: floating.append(name)
        if len(nets) > 1: multiple.append({"pin": name, "nets": sorted(nets)})
        for net in nets: actual.setdefault(net, set()).add(name)
expected = json.loads((FOLDER / "expected-connectivity.json").read_text(encoding="utf-8"))["nets"]
actual = {n: sorted(p) for n, p in actual.items()}
result = {"independentGeometryAudit": True, "allExpectedNetsMatch": actual == expected,
          "crossNetIntersections": collisions, "floatingPins": floating, "multipleNetPins": multiple,
          "physicalComponents": len({p.split(".")[0] for pins in actual.values() for p in pins}),
          "nets": len(actual), "connectedPins": sum(len(p) for p in actual.values()),
          "limitations": "Offline format/pin/geometry audit; not EasyEDA ERC, PCB DRC, SPICE or hardware validation."}
(FOLDER / "source-geometry-audit.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
print(json.dumps(result))
if not result["allExpectedNetsMatch"] or collisions or floating or multiple:
    raise SystemExit(1)
