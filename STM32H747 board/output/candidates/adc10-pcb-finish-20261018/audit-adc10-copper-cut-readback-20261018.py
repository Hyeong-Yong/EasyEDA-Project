"""Independent read-only audit of root's staged native copper-cut captures."""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
from pathlib import Path
import runpy

from shapely.geometry import Point


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MANIFEST = HERE / "adc10-copper-cut-execution-manifest-fresh-20261018.json"
MANIFEST_SHA = "389a1ddba84f1344f9cf76dd89ba1d1e203ad9bae2ac4f0eeff9f82be91eafe1"
OLD = ROOT / "output/candidates/adc10-dc-buffer-20261017"
CONTRACT = OLD / "independent-adc10-expected-full-pin-contract-20261017.json"
STAGES = ["isolate", "rename_1", "rename_2", "r164"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    rows, heads = {}, {}
    for line in path.read_text(encoding="utf8").splitlines():
        if not line.strip(): continue
        h, b = line.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], h.get("id")
        assert key not in rows, (path, key)
        rows[key], heads[key] = b, h
    return rows, heads


def changed_fields(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict): return ["whole-body"]
    return [key for key in sorted(a.keys() | b.keys()) if a.get(key) != b.get(key)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=STAGES, default="r164")
    parser.add_argument("--source")
    args = parser.parse_args()
    source = Path(args.source).resolve() if args.source else ROOT / f"output/validation/native-adc10-pcb-copper_{args.stage}-20261018.epru"
    assert sha(MANIFEST) == MANIFEST_SHA
    plan = json.loads(MANIFEST.read_text(encoding="utf8"))
    baseline = Path(plan["sourcePath"])
    assert sha(baseline) == plan["sourceSha256"]
    before, bh = parse(baseline)
    after, ah = parse(source)
    index = STAGES.index(args.stage)
    expected = copy.deepcopy(before)
    operations = plan["existingCopperOperations"]
    renames = [o for o in operations if o["action"] == "modify"]
    for op in operations:
        if op["action"] == "delete": expected.pop((op["type"], op["id"]))
    if index >= 1:
        for op in renames[:10]: expected["LINE", op["id"]] = op["afterBody"]
    if index >= 2:
        for op in renames[10:]: expected["LINE", op["id"]] = op["afterBody"]
    if index >= 3:
        op = plan["R164Correction"]
        expected["COMPONENT", op["id"]] = op["afterBody"]
        for attr in plan["R164ExpectedOwnedATTRs"]: expected["ATTR", attr["id"]] = attr["expectedAfterBody"]
    errors, tests = [], []

    def check(ok, test, detail=None):
        row = {"test": test, "passed": bool(ok)}
        if detail is not None: row["detail"] = detail
        tests.append(row)
        if not ok: errors.append(row)

    missing = sorted(expected.keys() - after.keys())
    added = sorted(after.keys() - expected.keys())
    diffs = [{"type": key[0], "id": key[1], "fields": changed_fields(expected[key], after[key]),
              "expected": expected[key], "actual": after[key]}
             for key in sorted(expected.keys() & after.keys(), key=str)
             if key[0] != "DOCHEAD" and expected[key] != after[key]]
    check(not missing and not added, "Exact stage-native primitive membership", {"missing": missing, "unexpected": added})
    check(not diffs, "Every stage-native record body equals the independently modeled guarded edits", diffs)
    allowed = {(o["type"], o["id"]) for o in operations} | {("COMPONENT", plan["R164Correction"]["id"])}
    allowed |= {("ATTR", a["id"]) for a in plan["R164ExpectedOwnedATTRs"]}
    protected = {key: b for key, b in before.items() if key not in allowed and key[0] != "DOCHEAD"}
    protected_diffs = [{"type": key[0], "id": key[1]} for key, body in protected.items() if after.get(key) != body]
    check(not protected_diffs and len(protected) == 12925, "All12925 non-target original native bodies exact", protected_diffs)
    keygroups = {}
    for group, kinds in {"VIA": {"VIA"}, "mechanicalPAD": {"PAD"}, "J18BottomSTRING": {"STRING"},
                         "rules": {"RULE", "RULE_TEMPLATE", "RULE_SELECTOR"},
                         "sixLayerStack": {"LAYER", "LAYER_PHYS"}, "physicalPinNets": {"PAD_NET"}}.items():
        old = {key: body for key, body in before.items() if key[0] in kinds}
        new = {key: body for key, body in after.items() if key[0] in kinds}
        keygroups[group] = {"beforeCount": len(old), "afterCount": len(new), "exactBodies": old == new}
        check(old == new, "Protected " + group + " complete membership/bodies exact", keygroups[group])
    attributes = defaultdict(dict)
    for (kind, rid), body in after.items():
        if kind == "ATTR": attributes[body["parentId"]][body["key"]] = body["value"]
    refs = {values["Designator"]: cid for cid, values in attributes.items() if "Designator" in values}
    check(len(refs) == sum(key[0] == "COMPONENT" for key in after) == 354, "354 physical parts retained")
    by_cid = {cid: ref for ref, cid in refs.items()}
    actual_pins, duplicate_conflicts = {}, []
    for (kind, rid), body in after.items():
        if kind != "PAD_NET" or not body.get("padNet"): continue
        _, cid, num, pad_id = json.loads(rid)
        key = by_cid[cid], str(num)
        if key in actual_pins and actual_pins[key] != body["padNet"]:
            duplicate_conflicts.append({"pin": key, "nets": [actual_pins[key], body["padNet"]]})
        actual_pins[key] = body["padNet"]
    contract = json.loads(CONTRACT.read_text(encoding="utf8"))
    expected_pins = {(p["ref"], str(p["number"])): p["net"] for p in contract["expectedPins"]}
    pin_diff = [{"ref": k[0], "pin": k[1], "expected": expected_pins.get(k), "actual": actual_pins.get(k)}
                for k in sorted(expected_pins.keys() | actual_pins.keys()) if expected_pins.get(k) != actual_pins.get(k)]
    check(not duplicate_conflicts and len(actual_pins) == 1136 and actual_pins == expected_pins,
          "Actual native PAD_NET exactly matches frozen1136-pin independent schematic contract",
          {"mismatches": pin_diff, "conflictingPhysicalDuplicatePads": duplicate_conflicts})
    r164_gap = None
    if index >= 3:
        m = runpy.run_path(str(OLD / "independent-adc10-bias-feed-isolation-plan.py"))
        libs = m["LM"]["read_libs"]()
        cid = refs["R164"]
        footprint = libs["FOOTPRINT", attributes[cid]["Footprint"]]
        p = next(body for (kind, rid), body in footprint.items() if kind == "PAD" and body["num"] == "2")
        shape = m["padshape"](p, after["COMPONENT", cid])
        via = after["VIA", plan["R164Retained3V3Via"]["id"]]
        via_shape = Point(via["centerX"], via["centerY"]).buffer(via["viaDiameter"]/2, quad_segs=128)
        r164_gap = shape.distance(via_shape)*.0254
        check(r164_gap >= .180 and abs(r164_gap-.1850004285) < 1e-6,
              "Actual R164 pad2-to-retained main3V3 via gap meets0.1524mm", r164_gap)
    report = {
        "schema": "stm32h747-adc10-independent-native-copper-cut-readback-20261018-v1",
        "stage": args.stage, "passed": not errors, "errors": errors,
        "sourcePath": str(source), "sourceSha256": sha(source), "sourceRecords": len(after),
        "baselinePath": str(baseline), "baselineSha256": sha(baseline),
        "manifestPath": str(MANIFEST), "manifestSha256": MANIFEST_SHA,
        "beforeRecordCounts": dict(Counter(k[0] for k in before)), "afterRecordCounts": dict(Counter(k[0] for k in after)),
        "protectedNativeBodies": len(protected), "protectedBodyErrors": protected_diffs,
        "protectedGroups": keygroups, "connectedPinCount": len(actual_pins), "physicalParts": len(refs),
        "R164Retained3V3ViaGapMm": r164_gap, "checks": tests,
        "limitations": ["Static actual-native source audit only; no live API calls or PCB writes.",
                        "Cut phase is intentionally unrouted/incomplete. New routes, local GND voids and full unchanged-rule native DRC remain required.",
                        "Pin-net contract is not routed copper continuity. No manufacturing approval implied."],
        "nativeFilesWritten": 0, "liveAPICalls": 0,
    }
    out = HERE / f"adc10-copper-cut-independent-{args.stage}-readback-20261018.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": sha(out), "passed": not errors, "stage": args.stage,
        "sourceSha256": sha(source), "records": len(after), "protectedBodies": len(protected),
        "physicalParts": len(refs), "connectedPins": len(actual_pins), "R164ViaGapMm": r164_gap,
        "errorTests": [{"test": e["test"], "detailCount": len(e.get("detail", [])) if isinstance(e.get("detail"), list) else None} for e in errors]}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
