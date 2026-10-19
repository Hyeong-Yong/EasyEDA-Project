"""Independent offline check of final ADC source, annotation, and exported connectivity."""
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALID = ROOT / "output/validation"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_source(path):
    records = {}
    for line in Path(path).read_text(encoding="utf8").splitlines():
        if not line.strip():
            continue
        header, body = line.split("||", 1)
        header, body = json.loads(header), json.loads(body.rstrip("|"))
        key = (header["type"], header.get("id"))
        assert key not in records, key
        records[key] = body
    return records


def read_netlist(path):
    text = Path(path).read_text(encoding="utf8").replace("\r\n", "\n")
    nodes = {}
    active, net = False, None
    for line in text.splitlines():
        line = line.strip()
        if line == "(" and not active:
            active, net = True, None
        elif line == ")" and active:
            assert net is not None
            active = False
        elif active and line:
            if net is None:
                net = line
            else:
                ref, number = line.split()[0].rsplit("-", 1)
                assert (ref, number) not in nodes
                nodes[ref, number] = net
    assert not active
    components = {}
    for block in re.findall(r"(?ms)^\[\n(.*?)^\]", text):
        ref = block.splitlines()[1]
        assert ref not in components
        components[ref] = block
    return nodes, components


def touches(point, segment):
    (x, y), ((ax, ay), (bx, by)) = point, segment
    return (abs((x-ax)*(by-ay)-(y-ay)*(bx-ax)) < 1e-5
            and min(ax, bx)-1e-5 <= x <= max(ax, bx)+1e-5
            and min(ay, by)-1e-5 <= y <= max(ay, by)+1e-5)


def main():
    final_path = VALID / "native-adc-dc-final-reopened-20261016.epru"
    finalized_path = VALID / "native-adc-dc-finalized-20261016.epru"
    final, prior = read_source(final_path), read_source(finalized_path)
    annotation_key = ("TEXT", "f4ba1d7115d2fc19")
    annotation = {"x": 1045, "y": 735, "rotation": 0, "color": "#006666",
                  "fontFamily": "Arial", "fontSize": 6, "fontWeight": False,
                  "italic": False, "underline": False, "align": "LEFT_BOTTOM",
                  "value": "ADC1 DC revision 2026-10-16", "fillColor": "#006666", "zIndex": 4249}
    assert final.keys() - prior.keys() == {annotation_key}
    assert not prior.keys() - final.keys()
    assert final[annotation_key] == annotation
    normalizations = Counter()
    absent = object()
    for key, old in prior.items():
        new = final[key]
        for field in old.keys() | new.keys():
            a, b = old.get(field, absent), new.get(field, absent)
            if a == b:
                continue
            if key[0] == "DOCHEAD" and field in {"client", "updateTime", "version"}:
                normalizations["documentSessionBookkeeping"] += 1
            elif key[0] == "ATTR" and field == "strikeout" and a is absent and b is False:
                normalizations["explicitFalseStrikeout"] += 1
            elif (key[0] == "ATTR" and field == "zIndex" and isinstance(a, (int, float))
                  and isinstance(b, (int, float)) and 0 <= b <= 30):
                normalizations["attributeDisplayOrder"] += 1
            else:
                raise AssertionError((key, field, a, b))
    assert normalizations == {"documentSessionBookkeeping": 3, "explicitFalseStrikeout": 150,
                              "attributeDisplayOrder": 99}
    attrs = defaultdict(dict)
    for (kind, rid), body in final.items():
        if kind == "ATTR":
            attrs[body["parentId"]][body["key"]] = body["value"]
    by_ref = {a["Designator"]: cid for cid, a in attrs.items() if "Designator" in a}
    wire_nets = {rid: attrs[rid]["NET"] for kind, rid in final if kind == "WIRE" and "NET" in attrs[rid]}
    segments = defaultdict(list)
    for (kind, rid), body in final.items():
        if kind == "LINE" and body.get("lineGroup") in wire_nets:
            segments[wire_nets[body["lineGroup"]]].append(((body["startX"], body["startY"]),
                                                          (body["endX"], body["endY"])))
    library = json.loads((HERE / "adc-dc-runtime-library-map.json").read_text(encoding="utf8"))
    symbols = {s["uuid"]: s for s in library["symbols"].values()}
    old_nodes, old_components = read_netlist(VALID / "native-final-Protel2_durable_final.net")
    new_nodes, new_components = read_netlist(VALID / "native-adc-dc-Protel2-20261016.net")
    expected = dict(old_nodes)
    target_graph, target_values = {}, {}
    for i in range(3):
        n, pre, drv = i+1, f"ADC1_PRE{i+1}", f"ADC1_DRV{i+1}"
        raw = old_nodes[f"R{140+2*i}", "1"]
        adc = old_nodes[f"R{141+2*i}", "2"]
        target_graph.update({
            f"R{137+i}": {"1": pre, "2": "ADC_BIAS_2V5"},
            f"R{140+2*i}": {"1": raw, "2": pre},
            f"R{141+2*i}": {"1": drv, "2": adc},
            f"C{80+i}": {"1": adc, "2": "GND"},
            f"U{10+i}": {"1": drv, "2": "GND", "3": pre, "4": drv, "5": "+3V3"},
            f"C{97+i}": {"1": pre, "2": "GND"},
            f"C{100+i}": {"1": "+3V3", "2": "GND"}})
        target_values.update({f"R{137+i}": "6.8k", f"R{140+2*i}": "6.8k", f"R{141+2*i}": "47",
                              f"C{80+i}": "2.2nF", f"U{10+i}": "OPA320AIDBVR",
                              f"C{97+i}": "10nF", f"C{100+i}": "100nF"})
        expected[f"R{146+i}", "1"] = pre
    target_graph.update({"U9": {"1": "+3V3", "2": "ADC_BIAS_2V5", "3": "GND"},
                         "C103": {"1": "+3V3", "2": "GND"},
                         "C104": {"1": "ADC_BIAS_2V5", "2": "GND"},
                         "C105": {"1": "ADC_BIAS_2V5", "2": "GND"}})
    target_values.update({"U9": "REF3325AIDBZR", "C103": "1uF", "C104": "4.7uF", "C105": "100nF"})
    pin_count = 0
    for ref, pins in target_graph.items():
        cid = by_ref[ref]
        body, a = final["COMPONENT", cid], attrs[cid]
        assert a["Value"] == target_values[ref], (ref, a["Value"])
        symbol = symbols[a["Symbol"]]
        assert {p["number"] for p in symbol["pins"]} == set(pins)
        theta = math.radians(body["rotation"])
        for p in symbol["pins"]:
            point = (round(body["x"] + p["x"]*math.cos(theta) + p["y"]*math.sin(theta), 6),
                     round(body["y"] - p["x"]*math.sin(theta) + p["y"]*math.cos(theta), 6))
            actual = [net for net, lines in segments.items() if any(touches(point, line) for line in lines)]
            assert actual == [pins[p["number"]]], (ref, p["number"], point, actual)
            expected[ref, p["number"]] = pins[p["number"]]
            pin_count += 1
    assert expected == new_nodes
    changed_old = {ref for ref in old_components if old_components[ref] != new_components[ref]}
    expected_changed = {f"R{i}" for i in range(137, 146)} | {"C80", "C81", "C82"}
    expected_new = {"U9", "U10", "U11", "U12"} | {f"C{i}" for i in range(97, 106)}
    assert changed_old == expected_changed
    assert new_components.keys() - old_components.keys() == expected_new
    assert not old_components.keys() - new_components.keys()
    changed_nodes = [key for key in old_nodes if old_nodes[key] != new_nodes[key]]
    assert len(changed_nodes) == 15
    power_parts = ["FB2", "C34", "R71", "C36"]
    for ref in power_parts:
        assert old_components[ref] == new_components[ref]
        assert {key: net for key, net in old_nodes.items() if key[0] == ref} == {
            key: net for key, net in new_nodes.items() if key[0] == ref}
    report = {"schema": "st-research-final-independent-adc-audit-20261016-v1", "passed": True,
              "finalSource": str(final_path), "finalSourceSha256": digest(final_path),
              "finalSourceRecords": len(final), "legitimateRevisionAnnotationExact": annotation,
              "otherReopenChangesOnly": dict(normalizations), "finalSourceComponentsReviewed": len(target_graph),
              "finalSourcePinsGeometricallyReviewed": pin_count, "freshNetlistExactExpectedDelta": True,
              "baselineConnectedPins": len(old_nodes), "finalConnectedPins": len(new_nodes),
              "addedPins": len(new_nodes)-len(old_nodes), "approvedExistingPinNetChanges": len(changed_nodes),
              "unaffectedOriginalConnectedPinsExact": len(old_nodes)-len(changed_nodes),
              "changedOriginalComponentBlocksExactly": sorted(changed_old), "allOther318ComponentBlocksExact": True,
              "new13ComponentRefsExactly": sorted(expected_new), "sourceGraph": target_graph,
              "sourceValues": target_values, "vddaVrefSupplyPathUnchangedComponents": power_parts,
              "dcContract": {"noSeriesCouplingCapacitors": True, "gain": 0.5, "offsetV": 1.25,
                             "inputRangeV": [-2, 2], "adcInputRangeV": [0.25, 2.25],
                             "preBufferLowPassHz": 1/(2*math.pi*3400*1e-8),
                             "postBufferKickbackLowPassHz": 1/(2*math.pi*47*2.2e-9)},
              "limitations": ["Input source impedance and resistor/reference tolerances affect the nominal transfer.",
                              "VDDA/VREF+ noise remains an independent measurement error path.",
                              "Firmware was not audited; channel pin selection and acquisition time still need verification.",
                              "PCB ADC ECO not applied: schematic has343 physical components while PCB has330.",
                              "Not a manufacturing approval or measured analog performance guarantee."]}
    report_path = HERE / "st-research-final-independent-audit.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": True, "report": str(report_path), "sourceSha256": report["finalSourceSha256"],
                      "sourcePinsReviewed": pin_count, "unaffectedOriginalPins": report["unaffectedOriginalConnectedPinsExact"],
                      "connectedPins": len(new_nodes), "annotations": 1}, indent=2))


if __name__ == "__main__":
    main()
