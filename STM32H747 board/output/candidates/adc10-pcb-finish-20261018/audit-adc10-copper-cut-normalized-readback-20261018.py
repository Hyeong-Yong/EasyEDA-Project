"""Independent actual-source proof including native collinear/empty-net cleanup."""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import runpy

from shapely.geometry import LineString, Point
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
M = runpy.run_path(str(HERE / "audit-adc10-copper-cut-readback-20261018.py"))
MANIFEST, MANIFEST_SHA = M["MANIFEST"], M["MANIFEST_SHA"]


def shape(body):
    return LineString([(body["startX"]*.0254, body["startY"]*.0254),
                       (body["endX"]*.0254, body["endY"]*.0254)]).buffer(body["width"]*.0254/2, quad_segs=64)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", choices=["rename_1", "rename_2", "r164"], default="r164")
    p.add_argument("--source")
    p.add_argument("--allow-r164-export-precision", action="store_true")
    p.add_argument("--tag", default="")
    args = p.parse_args()
    source = Path(args.source).resolve() if args.source else ROOT / f"output/validation/native-adc10-pcb-copper_continue_{args.stage}-20261018.epru"
    assert M["sha"](MANIFEST) == MANIFEST_SHA
    plan = json.loads(MANIFEST.read_text())
    baseline = Path(plan["sourcePath"])
    assert M["sha"](baseline) == plan["sourceSha256"]
    before, bh = M["parse"](baseline)
    after, ah = M["parse"](source)
    expected = copy.deepcopy(before)
    checks, errors = [], []

    def check(ok, test, detail=None):
        row = {"test": test, "passed": bool(ok)}
        if detail is not None: row["detail"] = detail
        checks.append(row)
        if not ok: errors.append(row)

    ops = plan["existingCopperOperations"]
    for op in ops:
        if op["action"] == "delete": expected.pop((op["type"], op["id"]))
    renamed = [o for o in ops if o["action"] == "modify"][:10 if args.stage == "rename_1" else 20]
    groups = defaultdict(list)
    for op in renamed: groups[op["afterBody"]["netName"]].append(op)
    normalizations, obsolete_keys = [], set()
    for net, pair in groups.items():
        check(len(pair) == 2, "Exactly2 original collinear segments " + net)
        actual = [(key, body) for key, body in after.items() if key[0] == "LINE" and body.get("netName") == net]
        check(len(actual) == 1, "Native pair merged into exactly1 segment " + net, [list(k) for k, _ in actual])
        if len(actual) != 1: continue
        key, body = actual[0]
        old_shape = unary_union([shape(o["beforeBody"]) for o in pair])
        new_shape = shape(body)
        xor, hausdorff = old_shape.symmetric_difference(new_shape).area, old_shape.hausdorff_distance(new_shape)
        check(xor < 1e-12 and hausdorff < 1e-10, "Exact same copper union geometry " + net,
              {"symmetricDifferenceAreaMm2": xor, "hausdorffMm": hausdorff})
        excluded = {"netName", "startX", "startY", "endX", "endY", "zIndex"}
        rest = lambda b: {k: v for k, v in b.items() if k not in excluded}
        check(rest(body) == rest(pair[0]["beforeBody"]) and body["zIndex"] == -1,
              "Native merge preserves all fields except endpoints/direction/net/zIndex " + net)
        for op in pair: expected.pop((op["type"], op["id"]))
        expected[key] = body
        old_net = pair[0]["beforeBody"]["netName"]
        pruned = []
        for kind, identity in [("NET", ["NET", old_net]), ("RULE_SELECTOR", ["RULE_SELECTOR", ["NET", old_net]])]:
            k = kind, json.dumps(identity, separators=(",", ":"))
            check(k in before, "Exact original old-net metadata identity " + str(k))
            b = before[k]
            if kind == "RULE_SELECTOR":
                check(not b["ruleKeyValue"] and not b["copperValue"] and not b["innerPlaneValue"],
                      "Deleted selector contains no rule overrides " + old_net, b)
            if k not in after:
                check(not [r for r in after.values() if str(r.get("netName") or r.get("padNet") or "").upper() == old_net.upper()],
                      "Pruned old-net metadata has zero actual circuit members " + old_net)
                expected.pop(k)
                obsolete_keys.add(k)
                pruned.append({"type": kind, "id": k[1], "originalBody": b})
        normalizations.append({"net": net, "oldIds": [o["id"] for o in pair], "newId": key[1],
            "newBody": body, "symmetricDifferenceAreaMm2": xor, "hausdorffMm": hausdorff,
            "nativeZIndex": -1, "prunedUnusedMetadata": pruned})
    coordinate_normalizations = []
    if args.stage == "r164":
        op = plan["R164Correction"]
        expected["COMPONENT", op["id"]] = op["afterBody"]
        for attr in plan["R164ExpectedOwnedATTRs"]: expected["ATTR", attr["id"]] = attr["expectedAfterBody"]
        if args.allow_r164_export_precision:
            precision_keys = [("COMPONENT", op["id"])]
            precision_keys += [("ATTR", a["id"]) for a in plan["R164ExpectedOwnedATTRs"] if a["key"] == "Designator"]
            for k in precision_keys:
                ideal, actual = expected[k]["y"], after[k]["y"]
                check(actual == round(ideal, 4) and abs(actual-ideal) < .00005,
                      "Only observed target coordinate exactly rounds to4decimal mil " + str(k),
                      {"idealMil": ideal, "actualMil": actual, "deltaMil": actual-ideal, "deltaMm": (actual-ideal)*.0254})
                if actual == round(ideal, 4) and abs(actual-ideal) < .00005:
                    expected[k] = dict(expected[k], y=actual)
                    coordinate_normalizations.append({"type": k[0], "id": k[1], "field": "y",
                        "idealMil": ideal, "actualMil": actual, "deltaMil": actual-ideal,
                        "deltaMm": (actual-ideal)*.0254,
                        "classification": "Observed exact4decimal-mil coordinate representation; no other field tolerance applied"})
    missing = sorted(expected.keys() - after.keys(), key=str)
    extra = sorted(after.keys() - expected.keys(), key=str)
    diffs = [{"type": k[0], "id": k[1], "fields": M["changed_fields"](expected[k], after[k]),
              "expected": expected[k], "actual": after[k]}
             for k in sorted(expected.keys() & after.keys(), key=str) if k[0] != "DOCHEAD" and expected[k] != after[k]]
    check(not missing and not extra, "Exact native membership after scoped merge and unused-net cleanup", {"missing": missing, "extra": extra})
    check(not diffs, "Every other native primitive body exactly protected", diffs)
    protected_rules = {k: b for k, b in before.items() if k[0] in {"RULE", "RULE_TEMPLATE"}}
    check(len([k for k in protected_rules if k[0] == "RULE"]) == 18 and protected_rules == {k: b for k, b in after.items() if k[0] in {"RULE", "RULE_TEMPLATE"}},
          "All18 RULE definitions and selected rule template exactly unchanged; empty NET-owned selectors are not definitions")
    for kinds, title in [({"VIA"}, "all634 VIAs"), ({"PAD"}, "all4 NPTH mechanical pads"), ({"STRING"}, "all21 J18 strings"),
                         ({"LAYER", "LAYER_PHYS"}, "complete six-layer stack"), ({"PAD_NET"}, "every physical pin-net assignment")]:
        check({k: b for k, b in before.items() if k[0] in kinds} == {k: b for k, b in after.items() if k[0] in kinds}, title + " exactly unchanged")
    attr = defaultdict(dict)
    for (kind, rid), b in after.items():
        if kind == "ATTR": attr[b["parentId"]][b["key"]] = b["value"]
    refs = {a["Designator"]: cid for cid, a in attr.items() if "Designator" in a}
    inverse = {cid: ref for ref, cid in refs.items()}
    actual_pins = {}
    for (kind, rid), b in after.items():
        if kind != "PAD_NET" or not b.get("padNet"): continue
        _, cid, number, pad = json.loads(rid)
        k = inverse[cid], str(number)
        check(k not in actual_pins or actual_pins[k] == b["padNet"], "Physical duplicate pads agree " + str(k))
        actual_pins[k] = b["padNet"]
    contract = json.loads(M["CONTRACT"].read_text())
    pins = {(v["ref"], str(v["number"])): v["net"] for v in contract["expectedPins"]}
    check(len(refs) == 354 and len(actual_pins) == 1136 and actual_pins == pins, "Frozen354parts/1136pins exact independent schematic contract")
    r164_gap = None
    if args.stage == "r164":
        bm = runpy.run_path(str(M["OLD"] / "independent-adc10-bias-feed-isolation-plan.py"))
        lib = bm["LM"]["read_libs"]()
        cid = refs["R164"]
        pad = next(b for (k, rid), b in lib["FOOTPRINT", attr[cid]["Footprint"]].items() if k == "PAD" and b["num"] == "2")
        a = bm["padshape"](pad, after["COMPONENT", cid])
        v = after["VIA", plan["R164Retained3V3Via"]["id"]]
        r164_gap = a.distance(Point(v["centerX"], v["centerY"]).buffer(v["viaDiameter"]/2, quad_segs=128))*.0254
        check(abs(r164_gap-.1850004285) < 1e-6 and r164_gap > .1524, "Actual translated R164 pad-to-via clearance", r164_gap)
    changed_header_count = sum(bh[k] != ah[k] for k in bh.keys() & ah.keys() if k[0] != "DOCHEAD")
    check(all({f: v for f, v in bh[k].items() if f != "ticket"} == {f: v for f, v in ah[k].items() if f != "ticket"}
              for k in bh.keys() & ah.keys() if k[0] != "DOCHEAD"), "Shared primitive headers differ only by native logical-ticket reindexing")
    suffix = "-" + args.tag if args.tag else ""
    out = HERE / f"adc10-copper-cut-normalized-{args.stage}{suffix}-independent-audit-20261018.json"
    report = {"schema": "stm32h747-adc10-native-cut-merge-readback-audit-20261018-v2",
        "passed": not errors, "stage": args.stage, "sourcePath": str(source), "sourceSha256": M["sha"](source),
        "baselinePath": str(baseline), "baselineSha256": M["sha"](baseline), "manifestSha256": MANIFEST_SHA,
        "records": len(after), "recordCounts": dict(Counter(k[0] for k in after)),
        "normalizations": normalizations, "unusedMetadataRemoved": len(obsolete_keys),
        "targetCoordinateRepresentationNormalizations": coordinate_normalizations,
        "nativeLogicalTicketReindexedSharedRecords": changed_header_count,
        "connectedPins": len(actual_pins), "physicalParts": len(refs), "R164PadToViaGapMm": r164_gap,
        "checks": checks, "errors": errors,
        "limitations": ["Actual static source audit only. No API/native writes. Header logical tickets are reindexed by native source serialization; body preservation is the protection contract.",
                        "Native same-net end-to-end collinear pair merging is proven exact by copper symmetric difference and Hausdorff metrics, not inferred from label names.",
                        "Only empty/unreferenced old NET metadata and empty NET-owned selectors are allowed to disappear. All18 rule definitions remain exact.",
                        "Cut-only board remains unrouted. This is not final full-board DRC or fabrication approval."], "liveAPICalls": 0, "nativeFilesWritten": 0}
    out.write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps({"passed": not errors, "path": str(out), "sha256": M["sha"](out),
        "stage": args.stage, "mergedGroups": len(normalizations), "unusedMetadataRemoved": len(obsolete_keys),
        "records": len(after), "pins": len(actual_pins), "parts": len(refs), "R164ViaGapMm": r164_gap,
        "errorTests": [e["test"] for e in errors]}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__": main()
