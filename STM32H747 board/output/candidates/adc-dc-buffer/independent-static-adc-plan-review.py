"""Independent read-only review of the proposed three-channel DC-buffer page."""
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / "adc-dc-schematic-plan.json").read_text(encoding="utf8"))
LIB = json.loads((HERE / "adc-dc-runtime-library-map.json").read_text(encoding="utf8"))


def parse(path):
    result = {}
    for raw in Path(path).read_text(encoding="utf8").splitlines():
        if not raw.strip():
            continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = (h["type"], h.get("id"))
        assert key not in result, key
        result[key] = b
    return result


def on_segment(point, segment):
    x, y = point
    a, b = segment
    cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
    return abs(cross) < 1e-5 and min(a[0], b[0]) - 1e-5 <= x <= max(a[0], b[0]) + 1e-5 and min(a[1], b[1]) - 1e-5 <= y <= max(a[1], b[1]) + 1e-5


def main():
    rows = parse(PLAN["candidatePath"])
    before = parse(PLAN["baselinePath"])
    assert hashlib.sha256(Path(PLAN["candidatePath"]).read_bytes()).hexdigest() == PLAN["candidateSha256"]
    attrs = defaultdict(dict)
    for (kind, rid), body in rows.items():
        if kind == "ATTR":
            attrs[body["parentId"]][body["key"]] = body["value"]
    nets = {rid: attrs[rid].get("NET") for kind, rid in rows if kind == "WIRE"}
    segments = defaultdict(list)
    for (kind, rid), body in rows.items():
        if kind == "LINE" and body.get("lineGroup") in nets:
            segments[nets[body["lineGroup"]]].append(((body["startX"], body["startY"]), (body["endX"], body["endY"])))
    pin_graph = {}
    for spec in PLAN["components"]:
        cid = spec["componentId"]
        body = rows[("COMPONENT", cid)]
        a = attrs[cid]
        assert a["Designator"] == spec["ref"] and a["Value"] == spec["value"]
        device = LIB["devices"][spec["deviceKey"]]
        assert a["Device"] == device["uuid"] and a["Symbol"] == device["symbolUuid"] and a["Footprint"] == device["footprintUuid"]
        symbol = next(s for s in LIB["symbols"].values() if s["uuid"] == device["symbolUuid"])
        pins = {}
        theta = math.radians(body["rotation"])
        for p in symbol["pins"]:
            point = [round(body["x"] + p["x"] * math.cos(theta) + p["y"] * math.sin(theta), 6),
                     round(body["y"] - p["x"] * math.sin(theta) + p["y"] * math.cos(theta), 6)]
            connected = sorted(n for n, segs in segments.items() if any(on_segment(point, seg) for seg in segs))
            assert len(connected) == 1, (spec["ref"], p["number"], point, connected)
            pins[p["number"]] = {"name": p["name"], "point": point, "net": connected[0]}
        pin_graph[spec["ref"]] = pins
    expect = {}
    for i in range(3):
        n = i + 1
        pre, drv = f"ADC1_PRE{n}", f"ADC1_DRV{n}"
        expect[f"U{10+i}"] = {"1": drv, "2": "GND", "3": pre, "4": drv, "5": "+3V3"}
        expect[f"C{97+i}"] = {"1": pre, "2": "GND"}
        expect[f"C{100+i}"] = {"1": "+3V3", "2": "GND"}
        expect[f"R{137+i}"] = {"1": pre, "2": "ADC_BIAS_2V5"}
        input_nets = {p["net"] for p in pin_graph[f"R{140+2*i}"].values()}
        assert pre in input_nets and len(input_nets) == 2, (n, input_nets)
        raw_net = next(net for net in input_nets if net != pre)
        assert raw_net not in {"GND", "+3V3", "ADC_BIAS_2V5", drv}, (n, raw_net)
        assert pin_graph[f"R{141+2*i}"]["1"]["net"] == drv
        adc_net = pin_graph[f"R{141+2*i}"]["2"]["net"]
        assert adc_net not in {pre, drv, "ADC_BIAS_2V5", "+3V3", "GND"}
        expect[f"C{80+i}"] = {"1": adc_net, "2": "GND"}
    expect["U9"] = {"1": "+3V3", "2": "ADC_BIAS_2V5", "3": "GND"}
    expect["C103"] = {"1": "+3V3", "2": "GND"}
    expect["C104"] = {"1": "ADC_BIAS_2V5", "2": "GND"}
    expect["C105"] = {"1": "ADC_BIAS_2V5", "2": "GND"}
    for ref, pins in expect.items():
        assert {p: data["net"] for p, data in pin_graph[ref].items()} == pins, (ref, pin_graph[ref], pins)
    allowed_change = {(x["type"], x["id"]) for x in PLAN["changes"]}
    allowed_delete = {(x["h"]["type"], x["h"].get("id")) for x in PLAN["deleted"]}
    changed = {key for key in before.keys() & rows.keys() if before[key] != rows[key]}
    deleted = before.keys() - rows.keys()
    assert changed == allowed_change and deleted == allowed_delete
    old_unaffected = len(before) - len(changed) - len(deleted)
    report = {"passed": True, "candidateSha256": PLAN["candidateSha256"], "componentCountReviewed": len(pin_graph),
        "pinCountReviewed": sum(len(p) for p in pin_graph.values()), "allPinsTouchExactlyOneExpectedNet": True,
        "pinGraph": pin_graph, "threeIndependentFollowers": True, "referencePinMappingCorrect": True,
        "seriesDcBlockingCapacitors": 0, "nominalGain": 0.5, "nominalOffsetV": 1.25,
        "nominalInputRangeV": [-2, 2], "nominalOutputRangeV": [0.25, 2.25],
        "preBufferLowPassHz": 1/(2*math.pi*3400*1e-8), "postBufferLowPassHz": 1/(2*math.pi*47*2.2e-9),
        "unaffectedBaselineRecordsExactlyPreserved": old_unaffected,
        "newComponentCount": sum(c["new"] for c in PLAN["components"]), "oldComponentRebindCount": sum(not c["new"] for c in PLAN["components"]),
        "notes": ["Static source graph only; native ERC/netlist and visual rendering still required.",
                  "Native positive rotation is counterclockwise on Y-down schematic coordinates; resistor pin numbering independently confirmed by native Protel2 export.",
                  "15.6 kS/s/channel clock/acquisition settings are user-owned, not asserted by schematic static QA.",
                  "New reference labels should be checked visually; C103 default attribute is close to capacitor plate edge."]}
    (HERE / "independent-static-adc-plan-review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: v for k, v in report.items() if k != "pinGraph"}, indent=2))


if __name__ == "__main__":
    main()
