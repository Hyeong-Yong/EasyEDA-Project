"""Static R146/R147/R148 ownership and deletion-only electrical contract.

No EasyEDA/API access. Reads saved page, checkpoint symbols and native netlist;
writes only this candidate folder's independent review artifacts.
"""
import hashlib
import json
import math
import re
import runpy
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "output/validation/native-adc-dc-display-final-reopened-20261016.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_adc_dc_corners_j18_direction_v2_20261016.epro2"
NETLIST = ROOT / "output/validation/native-adc-inline-before-Protel2-20261016.net"
PREVIOUS_NETLIST = ROOT / "output/validation/native-adc-dc-Protel2-20261016.net"
REFS = ("R146", "R147", "R148")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    rows = {}
    for line in path.read_text(encoding="utf8").splitlines():
        if not line.strip():
            continue
        header, body = line.split("||", 1)
        header, body = json.loads(header), json.loads(body.rstrip("|"))
        key = (header["type"], header.get("id"))
        assert key not in rows
        rows[key] = (header, body)
    return rows


def bounds(points):
    if not points:
        return None
    return [min(x for x, y in points), min(y for x, y in points),
            max(x for x, y in points), max(y for x, y in points)]


def main():
    rows = parse(SOURCE)
    attrs, attr_records = defaultdict(dict), defaultdict(list)
    for (kind, rid), (header, body) in rows.items():
        if kind == "ATTR":
            attrs[body.get("parentId")][body.get("key")] = body.get("value")
            attr_records[body.get("parentId")].append({"type": kind, "id": rid, "body": body})
    by_ref = {a["Designator"]: rid for rid, a in attrs.items() if "Designator" in a}
    libraries = runpy.run_path(str(ROOT / "scripts/build-adc-dc-libraries.py"))["read_checkpoint"](CHECKPOINT)
    net_parse = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))["parse_protel2"]
    raw_net = NETLIST.read_text(encoding="utf8")
    pins = net_parse(raw_net)
    nodes = {(p["ref"], p["number"]): p["net"] for p in pins}
    assert len(nodes) == len(pins) == 1093
    previous_nodes = {(p["ref"], p["number"]): p["net"] for p in net_parse(PREVIOUS_NETLIST.read_text(encoding="utf8"))}
    assert nodes == previous_nodes
    component_blocks = {b.splitlines()[1]: b for b in re.findall(r"(?ms)^\[\n(.*?)^\]", raw_net.replace("\r\n", "\n"))}
    assert len(component_blocks) == 343
    whole_delete, channels = set(), []
    for i, ref in enumerate(REFS):
        cid = by_ref[ref]
        body = rows[("COMPONENT", cid)][1]
        properties = attrs[cid]
        assert properties["Value"] == "30k_NC" and properties["DNP"] == "yes"
        assert properties["Add into BOM"] == "no" and properties["Convert to PCB"] == "yes"
        symbol_id = properties["Symbol"]
        symbol = libraries[("SYMBOL", symbol_id)]
        symbol_attrs = defaultdict(dict)
        for h, b in symbol.values():
            if h["type"] == "ATTR":
                symbol_attrs[b.get("parentId")][b.get("key")] = b.get("value")
        local_polys = []
        pin_positions = {}
        for h, b in symbol.values():
            if h["type"] == "POLY":
                xy = [(p["x"], p["y"]) for p in b.get("points", [])]
                local_polys.append({"id": h["id"], "bounds": bounds(xy),
                                    "strokeColor": b.get("strokeColor"), "fillColor": b.get("fillColor"),
                                    "strokeWidth": b.get("strokeWidth"), "pointCount": len(xy)})
            if h["type"] == "PIN":
                number = symbol_attrs[h["id"]]["Pin Number"]
                assert body["rotation"] == 0 and not body["isMirror"]
                pin_positions[number] = [body["x"] + b["x"], body["y"] + b["y"]]
        assert pin_positions == {"1": [345 + (335 if i > 0 else 0) + (330 if i > 1 else 0), 195],
                                 "2": [345 + (335 if i > 0 else 0) + (330 if i > 1 else 0), 225]}
        x = pin_positions["1"][0]
        top = [(k, b) for k, (_, b) in rows.items() if k[0] == "LINE"
               and [b["startX"], b["startY"], b["endX"], b["endY"]] == [x, 190, x, 195]]
        bottom = [(k, b) for k, (_, b) in rows.items() if k[0] == "LINE"
                  and [b["startX"], b["startY"], b["endX"], b["endY"]] == [x, 225, x, 230]]
        assert len(top) == len(bottom) == 1
        top_key, top_body = top[0]
        bottom_key, bottom_body = bottom[0]
        bottom_wire = bottom_body["lineGroup"]
        bottom_children = [(k, b) for k, (_, b) in rows.items()
                           if b.get("lineGroup") == bottom_wire]
        assert len(bottom_children) == 1
        ground = [(k, b) for k, (_, b) in rows.items() if k[0] == "COMPONENT"
                  and b["x"] == x and b["y"] == 235 and attrs[k[1]].get("Global Net Name") == "GND"]
        assert len(ground) == 1
        ground_key, ground_body = ground[0]
        for number, net in (("1", f"ADC1_PRE{i+1}"), ("2", "GND")):
            assert nodes[(ref, number)] == net
        delete = {("COMPONENT", cid), top_key, bottom_key, ("WIRE", bottom_wire), ground_key}
        delete.update((a["type"], a["id"]) for a in attr_records[cid])
        delete.update((a["type"], a["id"]) for a in attr_records[bottom_wire])
        delete.update((a["type"], a["id"]) for a in attr_records[ground_key[1]])
        whole_delete.update(delete)
        library_bbox = bounds([(body["x"] + p["x"], body["y"] + p["y"])
                               for h, b in symbol.values() if h["type"] == "POLY" for p in b["points"]])
        red_crosses = [p for p in local_polys if p["strokeColor"] == "#E12E31"]
        # Existing PDF-derived symbols retain two coincident copies of each
        # red diagonal. All four are owned by the deleted instance.
        assert len(red_crosses) == 4
        red_diagonals = {tuple((p["x"], p["y"]) for p in b["points"])
                         for h, b in symbol.values() if h["type"] == "POLY" and b.get("strokeColor") == "#E12E31"}
        assert len(red_diagonals) == 2
        # Independent root-POLY search: no resistor glyph or NC overlay lives on
        # the page. The one nearby root green dot is the shared PRE junction.
        nearby_root_polys = []
        for (kind, rid), (_, b) in rows.items():
            if kind != "POLY" or not b.get("points"):
                continue
            box = bounds([(p["x"], p["y"]) for p in b["points"]])
            if box[0] >= x - 10 and box[2] <= x + 55 and box[1] >= 185 and box[3] <= 240:
                nearby_root_polys.append({"id": rid, "bounds": box, "strokeColor": b.get("strokeColor")})
        assert all(p["strokeColor"] == "#009600" for p in nearby_root_polys)
        top_siblings = [{"type": k[0], "id": k[1], "body": b} for k, (_, b) in rows.items()
                        if b.get("lineGroup") == top_body["lineGroup"] and k != top_key]
        assert top_siblings
        channels.append({"ref": ref, "componentId": cid, "properties": properties,
                         "componentBody": body, "ownedAttrs": attr_records[cid],
                         "symbolId": symbol_id, "symbolRecordCounts": dict(Counter(h["type"] for h, b in symbol.values())),
                         "visualOwnership": "All resistor, reference/value/tolerance PDF glyphs and red NC overlays belong to this library symbol instance; remove instance, do NOT delete shared library document.",
                         "symbolPolysCompact": local_polys, "symbolVisualBoundsOnPage": library_bbox,
                         "redNcCrossLocalIds": [p["id"] for p in red_crosses], "pinPositions": pin_positions,
                         "topStub": {"type": top_key[0], "id": top_key[1], "body": top_body,
                                     "sharedWireIdToPreserve": top_body["lineGroup"], "otherLinesToPreserve": top_siblings},
                         "bottomStub": {"type": bottom_key[0], "id": bottom_key[1], "body": bottom_body,
                                        "wireId": bottom_wire, "wireBody": rows[("WIRE", bottom_wire)][1],
                                        "ownedWireAttrs": attr_records[bottom_wire]},
                         "dedicatedGround": {"type": ground_key[0], "id": ground_key[1], "body": ground_body,
                                             "attrs": attr_records[ground_key[1]]},
                         "nearbyRootPolysNotDnpOwnedPreserve": nearby_root_polys,
                         "deleteRecordKeys": sorted(delete),
                         "baselineConnectedPins": [{"ref": ref, "number": n, "net": nodes[(ref, n)]} for n in ("1", "2")]})
    expected = [p for p in pins if p["ref"] not in REFS]
    assert len(expected) == 1087
    assert len(whole_delete) == sum(len(c["deleteRecordKeys"]) for c in channels)
    fresh_path = ROOT / "output/validation/native-adc-inline-before-20261016.epru"
    fresh_check = None
    if fresh_path.exists():
        fresh = parse(fresh_path)
        missing = sorted(k for k in whole_delete if k not in fresh)
        changed = sorted(k for k in whole_delete if k in fresh and rows[k][1] != fresh[k][1])
        assert not missing and not changed
        fresh_check = {"path": str(fresh_path), "sha256": sha(fresh_path),
                       "all84DeletionBodiesExactAgainstFreshCapture": True,
                       "missingDeletionKeys": missing, "changedDeletionBodies": changed,
                       "nonTargetFreshCaptureDifferencesFromEarlierSavedSource": [
                           {"record": k, "fields": sorted(f for f in set(rows[k][1]) | set(fresh[k][1])
                                                         if rows[k][1].get(f) != fresh[k][1].get(f))}
                           for k in sorted(rows.keys() & fresh.keys(), key=lambda k: (k[0], str(k[1])))
                           if k not in whole_delete and rows[k][1] != fresh[k][1]],
                       "instruction": "Use fresh capture as candidate baseline; preserve its prior unrelated layout edits. The 84 DNP deletion bodies are unchanged."}
    report = {"schema": "adc-inline-independent-dnp-ownership-20261016-v1", "passed": True,
              "sourcePath": str(SOURCE), "sourceSha256": sha(SOURCE),
              "checkpointPath": str(CHECKPOINT), "checkpointSha256": sha(CHECKPOINT),
              "netlistPath": str(NETLIST), "netlistSha256": sha(NETLIST),
              "freshBeforeNetlist1093PinIdentitiesExactlyMatchPriorNetlist": True,
              "previousNetlistPath": str(PREVIOUS_NETLIST), "previousNetlistSha256": sha(PREVIOUS_NETLIST),
              "freshBeforeNativeErcPassed": json.loads((ROOT / "output/validation/native-adc-inline-before-erc-20261016.json").read_text(encoding="utf8")).get("passed") is True,
              "channels": channels, "deleteRecordCounts": dict(Counter(k for k, rid in sorted(whole_delete))),
              "totalDnpAndDedicatedStubGroundRecords": len(whole_delete),
              "freshBaselineCrossCheck": fresh_check,
              "noRootGlyphPolysNeedDeleting": True,
              "electricalMeaning": {"dnpIsNotNoConnectPin": True, "eachDnpResistorIsConnectedPreToGroundInNetlist": True,
                 "populated30kWouldAlterGainAndOffset": True, "physicalDnpRemovalChangesNominalCircuit": False,
                 "openInputBiasProblemFixedByDnpDeletion": False, "formulaForLowSourceImpedanceInput": "VADC=0.5*VIN+1.25V",
                 "gain": 0.5, "offsetV": 1.25, "inputRangeV": [-2, 2], "outputRangeV": [0.25, 2.25],
                 "sourceImpedanceWarning": "Finite source resistance affects divider gain and offset; zero electrical delta here assumes the declared DNP condition and no other circuit redesign."},
              "expectedNetlistContract": {"baselineConnectedPins": 1093, "removedConnectedPins": 6,
                  "expectedConnectedPins": 1087, "baselinePhysicalComponentBlocks": 343,
                  "expectedPhysicalComponentBlocks": 340, "allRemainingPinNetIdentitiesUnchanged": True,
                  "expectedPins": sorted(expected, key=lambda p: (p["ref"], p["number"])),
                  "expectedComponentRefs": sorted(set(component_blocks) - set(REFS)),
                  "gainAndPartsContract": {"R137/R138/R139/R140/R142/R144": "6.8k, 0.1%", "R141/R143/R145": "47", "C80/C81/C82": "2.2nF C0G", "U9": "REF3325", "U10/U11/U12": "OPA320 unity-gain followers", "seriesDcBlockingCaps": 0}},
              "warnings": ["Deletion-only contract; new authorized electrical architecture requires a separately reviewed contract.",
                           "Do not delete PRE shared WIRE groups when removing only top DNP stubs.",
                           "Native ERC, fresh netlist and visual QA still required after any application.",
                           "No PCB changes or live EasyEDA operations performed."]}
    out = HERE / "independent-dnp-deletion-audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": True, "report": str(out), "sha256": sha(out),
                      "sourceSha256": report["sourceSha256"], "deleteRecordCounts": report["deleteRecordCounts"],
                      "expectedConnectedPins": 1087, "expectedComponentBlocks": 340,
                      "channels": [{"ref": c["ref"], "componentId": c["componentId"],
                                    "symbolVisualBounds": c["symbolVisualBoundsOnPage"],
                                    "symbolRecordCounts": c["symbolRecordCounts"],
                                    "deleteRecordCount": len(c["deleteRecordKeys"])} for c in channels]}, indent=2))


if __name__ == "__main__":
    main()
