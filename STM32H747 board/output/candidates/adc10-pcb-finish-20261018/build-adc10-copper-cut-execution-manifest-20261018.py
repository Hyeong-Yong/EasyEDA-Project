"""Build a guarded OFFLINE manifest for root's public-API copper cut phase.

This script never calls EasyEDA, never writes a native source/candidate, and
does not add any new routing. The library agent owns all new routing.
"""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path
import runpy

from shapely import affinity
from shapely.geometry import Point


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "output/candidates/adc10-dc-buffer-20261017"
PRE_PLAN = OLD / "adc10-pre-copper-isolation-plan-20261017.json"
BIAS_PLAN = OLD / "independent-adc10-bias-feed-isolation-plan-20261017.json"
WIP_SOURCE = ROOT / "output/validation/native-adc10-pcb-oriented_reopened-20261017.epru"
BM = runpy.run_path(str(OLD / "independent-adc10-bias-feed-isolation-plan.py"))
MM = .0254
R164_DELTA_MM = -.050


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body_sha(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def parse(path):
    rows, headers, attrs = {}, {}, defaultdict(dict)
    for raw in path.read_text(encoding="utf8").splitlines():
        if not raw.strip(): continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], h.get("id")
        assert key not in rows, (path, key)
        rows[key], headers[key] = b, h
        if h["type"] == "ATTR": attrs[b["parentId"]][b["key"]] = (key, b)
    refs = {a["Designator"][1]["value"]: cid for cid, a in attrs.items() if "Designator" in a}
    return rows, headers, attrs, refs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Fresh root-exported PCB baseline; no live reads")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--tag", default="fresh")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    assert sha(source) == args.expected_sha256, (source, sha(source), args.expected_sha256)
    rows, headers, attrs, refs = parse(source)
    wip, wh, wa, wr = parse(WIP_SOURCE)
    pre = json.loads(PRE_PLAN.read_text(encoding="utf8"))
    bias = json.loads(BIAS_PLAN.read_text(encoding="utf8"))
    errors, checks = [], []

    def check(ok, name, details=None):
        row = {"test": name, "passed": bool(ok)}
        if details is not None: row["details"] = details
        checks.append(row)
        if not ok: errors.append(row)

    doc = next(b for (kind, rid), b in rows.items() if kind == "DOCHEAD")
    check(doc.get("docType") == "PCB" and doc.get("uuid") == "0ac2a19168000d8e", "Correct STM32H747 native PCB identity", doc)
    check(len(refs) == 354, "Frozen354part PCB membership")
    check(pre["passedBoundedGeometryChecks"] and bias["passed"], "Both prior bounded source-geometry planning reports passed")
    ops = []
    for original in pre["operations"]:
        op = copy.deepcopy(original)
        key = op["type"], op["id"]
        check(key in rows and rows.get(key) == op["beforeBody"], "Fresh exact original PRE primitive guard " + "/".join(key))
        op["beforeHeader"] = headers[key]
        op["beforeBodySha256"] = body_sha(rows[key])
        op["beforeBody"] = rows[key]
        op["publicAPI"] = ({"method": "pcb_PrimitiveFill.delete", "args": [[op["id"]]]} if op["action"] == "delete"
                           else {"method": "pcb_PrimitiveLine.modify", "args": [op["id"], {"net": op["afterBody"]["netName"]}]})
        ops.append(op)
    for channel in bias["channels"]:
        key = tuple(channel["feedLineKey"])
        check(key in rows and rows.get(key) == channel["feedLineBody"], "Fresh exact original bias LINE guard " + channel["ref"])
        check(rows[key]["layerId"] == 1 and rows[key]["netName"] == "+3V3", "Bias cut remains top main3V3 feed " + channel["ref"])
        via_key = tuple(channel["dedicatedViaKey"])
        check(rows.get(via_key) == channel["dedicatedViaBody"], "Dedicated main3V3 VIA body preserved " + channel["ref"])
        ops.append({"action": "delete", "type": "LINE", "id": key[1], "channel": channel["ref"],
                    "beforeHeader": headers[key], "beforeBodySha256": body_sha(rows[key]), "beforeBody": rows[key],
                    "afterBody": None,
                    "reason": "Cut only the dedicated main3V3-to-quiet-bias resistor feed. Do not rename its via, which remains in global3V3 In2 plane.",
                    "publicAPI": {"method": "pcb_PrimitiveLine.delete", "args": [[key[1]]]}})
    check(len(ops) == 40 and len({(o["type"], o["id"]) for o in ops}) == 40,
          "Exactly40 independent existing-copper operations")
    check(Counter((o["action"], o["type"]) for o in ops) == Counter({("delete", "FILL"): 10, ("delete", "LINE"): 10, ("modify", "LINE"): 20}),
          "Scope exact10FILLdelete10biasLINEdelete20PRELINE-net-only")
    for op in ops:
        if op["action"] == "modify":
            check({k for k in op["beforeBody"].keys() | op["afterBody"].keys() if op["beforeBody"].get(k) != op["afterBody"].get(k)} == {"netName"},
                  "Net-only LINE change " + op["id"])

    # Preserve all drills. Translate R164 away from its dedicated main3V3 via
    # by0.050mm rather than removing a usable power via/drill.
    cid = refs["R164"]
    key = "COMPONENT", cid
    before_component = rows[key]
    check(before_component == wip.get(key) and before_component["angle"] == 90 and before_component["layerId"] == 1,
          "R164 current full-precision top90degree baseline unchanged")
    after_component = copy.deepcopy(before_component)
    after_component["y"] += R164_DELTA_MM / MM
    component_op = {"action": "modify", "type": "COMPONENT", "id": cid, "ref": "R164",
        "allowedChangedFields": ["y"], "deltaMmYUp": [0, R164_DELTA_MM],
        "beforeHeader": headers[key], "beforeBodySha256": body_sha(before_component), "beforeBody": before_component,
        "afterBody": after_component,
        "publicAPI": {"method": "pcb_PrimitiveComponent.modify", "args": [cid,
            {"x": before_component["x"], "y": after_component["y"], "rotation": 90, "layerEnum": "EPCB_LayerId.TOP"}]},
        "reason": "Increase R164 quiet-bias pad2-to-retained main3V3 via clearance without changing any drill, net, UID, angle or footprint master"}
    expected_attrs = []
    for attr_key, body in attrs[cid].values():
        after_body = copy.deepcopy(body)
        if after_body.get("y") is not None: after_body["y"] += R164_DELTA_MM/MM
        expected_attrs.append({"type": "ATTR", "id": attr_key[1], "key": body["key"],
            "beforeHeader": headers[attr_key], "beforeBody": body, "beforeBodySha256": body_sha(body),
            "expectedAfterBody": after_body,
            "note": "Owned attribute geometry is expected to translate with native component movement. Do not change values, identity, visibility, rotation, or formatting."})
    check(len(expected_attrs) == 3, "Exactly3 native owned R164 ATTR records guarded")
    libs = BM["LM"]["read_libs"]()
    fp = attrs[cid]["Footprint"][1]["value"]
    pads = {str(p["num"]): p for (kind, pid), p in libs["FOOTPRINT", fp].items() if kind == "PAD"}
    bias_channel = next(c for c in bias["channels"] if c["ref"] == "R164")
    via_key = tuple(bias_channel["dedicatedViaKey"])
    via = rows[via_key]
    via_shape = Point(via["centerX"], via["centerY"]).buffer(via["viaDiameter"]/2, quad_segs=128)
    old_pad = BM["padshape"](pads["2"], before_component)
    new_pad = BM["padshape"](pads["2"], after_component)
    old_gap, new_gap = old_pad.distance(via_shape)*MM, new_pad.distance(via_shape)*MM
    check(abs(old_gap-.1350004285) < 1e-6 and new_gap > .180,
          "R164 translation improves gap above0.1524mm with positive margin", {"oldGapMm": old_gap, "newGapMm": new_gap, "ruleMm": .1524})
    anchor_report = []
    for channel in pre["channels"]:
        rb = channel["biasResistor"]
        cc = after_component if rb == "R164" else rows["COMPONENT", refs[rb]]
        fuid = attrs[refs[rb]]["Footprint"][1]["value"]
        master = libs["FOOTPRINT", fuid]
        pin_centers = {}
        angle = math.radians(cc["angle"])
        for (kind, pid), pad in master.items():
            if kind != "PAD": continue
            x = cc["x"] + pad["centerX"]*math.cos(angle) - pad["centerY"]*math.sin(angle)
            y = cc["y"] + pad["centerX"]*math.sin(angle) + pad["centerY"]*math.cos(angle)
            pin_centers[str(pad["num"])] = {"xyMilYUp": [x, y], "xyMmYUp": [x*MM, y*MM], "masterPadPrimitiveId": pid}
        line_ops = [op for op in ops if op["action"] == "modify" and op["afterBody"]["netName"] == channel["newPRE"]]
        endpoints = [(op["beforeBody"]["startX"], op["beforeBody"]["startY"]) for op in line_ops]
        endpoints += [(op["beforeBody"]["endX"], op["beforeBody"]["endY"]) for op in line_ops]
        anchor = max(endpoints)
        anchor_report.append({"sma": channel["sma"], "biasResistor": rb,
            "newPRE": channel["newPRE"], "newDRV": channel["newDRV"], "buffer": channel["buffer"],
            "existingPREAnchorMilYUp": list(anchor), "existingPREAnchorMmYUp": [v*MM for v in anchor],
            "biasPad1PRE": pin_centers["1"], "biasPad2Quiet2V5": pin_centers["2"],
            "seriesInput": channel["pinPositions"][channel["seriesResistor"]+".1"],
            "newRouteOwner": "/root/adc_library_builder"})

    allowed = {(o["type"], o["id"]) for o in ops} | {key} | {("ATTR", a["id"]) for a in expected_attrs}
    protected = {k: b for k, b in rows.items() if k not in allowed and k[0] != "DOCHEAD"}
    protected3v3 = {k: b for k, b in protected.items() if b.get("netName") == "+3V3"}
    protected_post = {tuple([c["type"], c["id"]]): rows[c["type"], c["id"]] for c in pre["post47ADCProtectedCopper"]}
    check(all(body_sha(body) == next(p["bodySha256"] for p in pre["post47ADCProtectedCopper"] if (p["type"], p["id"]) == k) for k, body in protected_post.items()),
          "Every protected post47ADC native copper primitive exactly matches prior verified original")
    record_counts = Counter(k[0] for k in rows)
    expected_counts = record_counts.copy()
    expected_counts["LINE"] -= 10
    expected_counts["FILL"] -= 10
    # No source candidate is written: this is only an in-memory bounded scope
    # model to prove the existing-copper operation membership.
    in_memory = copy.deepcopy(rows)
    for op in ops:
        k = op["type"], op["id"]
        if op["action"] == "delete": del in_memory[k]
        else: in_memory[k] = op["afterBody"]
    in_memory[key] = after_component
    for attr in expected_attrs: in_memory["ATTR", attr["id"]] = attr["expectedAfterBody"]
    check(all(in_memory[k] == body for k, body in protected.items()), "All non-target native record bodies preserved in in-memory model")
    check(Counter(k[0] for k in in_memory) == expected_counts, "Only10LINE and10FILL removed; all VIA/PAD/drills/parts/net assignments preserved")
    report = {
        "schema": "stm32h747-adc10-copper-cut-root-execution-manifest-20261018-v1",
        "passedPreflightGuards": not errors, "errors": errors, "planningOnly": True,
        "sourcePath": str(source), "sourceSha256": sha(source), "sourceBytes": source.stat().st_size,
        "projectNameRequired": "STM32H747_MCU_BOARD_v19", "PCBRequired": "0ac2a19168000d8e",
        "frozenSchematic": {"physicalParts": 354, "connectedPins": 1136, "newOpenZeroDetector": False, "newBandwidthRedesign": False},
        "scope": {"existingCopperOperations": 40, "deleteBiasLINE": 10, "deleteExclusiveMIXFILL": 10,
            "renameUpstreamPRELINE": 20, "moveR164Component": 1, "implicitOwnedR164ATTR": 3,
            "VIADeletes": 0, "NPTHOrBoardChanges": 0, "newRoutingByThisAgent": 0},
        "priorVerifiedReports": [{"path": str(PRE_PLAN), "sha256": sha(PRE_PLAN)}, {"path": str(BIAS_PLAN), "sha256": sha(BIAS_PLAN)}],
        "operationGroups": [
            {"phase": "guard-all", "instructions": "Before ANY mutation compare every original type/ID/full body, owned R164 ATTR, frozen354parts1136pin contract, current project/window and fresh backup. Abort on ANY mismatch."},
            {"phase": "delete-exclusive-MIX-FILL", "method": "pcb_PrimitiveFill.delete", "ids": [op["id"] for op in ops if op["action"] == "delete" and op["type"] == "FILL"]},
            {"phase": "delete-local-main3V3-feed-LINE", "method": "pcb_PrimitiveLine.delete", "ids": [op["id"] for op in ops if op["action"] == "delete" and op["type"] == "LINE"]},
            {"phase": "net-only-PRE-LINE", "method": "pcb_PrimitiveLine.modify", "operations": [{"id": op["id"], "property": {"net": op["afterBody"]["netName"]}} for op in ops if op["action"] == "modify"]},
            {"phase": "R164-clearance-translation", "operation": component_op},
            {"phase": "capture-and-audit", "instructions": "Root exports actual native source immediately, checks all exact target/protected records, unchanged PAD_NET and354part1136pin contract. Do not claim DRC/routing complete. Continue only with reviewed library-agent routes."}],
        "existingCopperOperations": ops, "R164Correction": component_op, "R164ExpectedOwnedATTRs": expected_attrs,
        "R164Retained3V3Via": {"type": via_key[0], "id": via_key[1], "bodySha256": body_sha(via), "body": via,
            "oldPadToViaGapMm": old_gap, "newPadToViaGapMm": new_gap, "ruleMm": .1524,
            "planeNetRemainsMain3V3": True, "drillUnchanged": True,
            "allOtherNetClearanceState": "Library agent must integrate translated R164 pad copper into local TOP-GND void/route checks; native strict DRC is final authority."},
        "newRouteAnchors": anchor_report,
        "protectedADCpostCopper": [{"type": k[0], "id": k[1], "bodySha256": body_sha(b)} for k, b in sorted(protected_post.items())],
        "protectedGlobal3V3Copper": [{"type": k[0], "id": k[1], "bodySha256": body_sha(b)} for k, b in sorted(protected3v3.items())],
        "protectedRecordCount": len(protected),
        "protectedRecordsBodySha256": body_sha([[list(k), b] for k, b in sorted(protected.items())]),
        "protectedRecordBodyGuards": [{"type": k[0], "id": k[1], "bodySha256": body_sha(b)} for k, b in sorted(protected.items())],
        "expectedPostCutRecordCounts": dict(sorted(expected_counts.items())),
        "checks": checks,
        "atomicity": "The public API has no transaction guarantee documented here. This is one guard-all/staged-apply/recheck unit, not a claimed atomic native transaction. Root must preserve a fresh checkpoint and stop without further edits on a partial API failure; never silently reconstruct deleted primitives with guessed IDs.",
        "limitations": ["Planning artifact only; no native/API/UI call and no native source/PCB candidate written by this agent.",
            "No PRE, DRV, power, reference or ADC bucket route is created by this manifest. The library agent owns every new route and GND void.",
            "After cut phase circuits are intentionally incomplete until buffers/new routes are installed. Never power or fabricate a cut-only board.",
            "R164 move is conditioned on integrated neighboring copper/ground validation, plus final unchanged18rule native DRC. No rule relaxation allowed."],
        "liveAPICalls": 0, "nativeFilesWritten": 0,
    }
    out = HERE / f"adc10-copper-cut-execution-manifest-{args.tag}-20261018.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": sha(out), "passedPreflightGuards": not errors,
        "sourceSha256": sha(source), "existingCopperOperations": len(ops), "newR164GapMm": new_gap,
        "protectedRecords": len(protected), "errors": errors}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
