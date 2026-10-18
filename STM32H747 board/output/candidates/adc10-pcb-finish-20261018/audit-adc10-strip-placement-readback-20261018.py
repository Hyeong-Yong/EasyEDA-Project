"""Independent rigid-placement/source-scope audit; no API/native writes."""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARSE = runpy.run_path(str(HERE / "audit-adc10-copper-cut-readback-20261018.py"))["parse"]
BASE = ROOT / "output/validation/native-adc10-pcb-copper_continue_r164-20261018.epru"
BASE_SHA = "8da561d713741da9d84514c117c1498f9e37311238ca6ea19350c62546549bc9"
PLAN = HERE / "strip/adc10-strip-phase1-placement-pad-clearance-20261018.json"
PLAN_SHA = "cf407e90cc9b11b496d21bec858fd2154372fc81ef99aac75d38066d17d4f74e"


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=int, choices=[1, 2, 3, 4], default=4)
    p.add_argument("--source")
    p.add_argument("--tag", default="")
    args = p.parse_args()
    source = Path(args.source).resolve() if args.source else ROOT / f"output/validation/native-adc10-pcb-strip_place{args.stage}-20261018.epru"
    assert sha(BASE) == BASE_SHA and sha(PLAN) == PLAN_SHA
    plan = json.loads(PLAN.read_text())
    before, headers = PARSE(BASE)
    actual, ah = PARSE(source)
    expected = copy.deepcopy(before)
    placements = plan["componentPlacements"][:min(34, args.stage*10)]
    errors, checks, coordinates, attr_models = [], [], [], []

    def check(ok, test, detail=None):
        row = {"test": test, "passed": bool(ok)}
        if detail is not None: row["detail"] = detail
        checks.append(row)
        if not ok: errors.append(row)

    owned = set()
    for placement in placements:
        cid, target = placement["componentId"], placement["afterBody"]
        key = "COMPONENT", cid
        old = before[key]
        check(old == placement["beforeBody"], "Exact parked component baseline " + placement["ref"])
        after = dict(target, x=round(target["x"], 4), y=round(target["y"], 4))
        expected[key] = after
        owned.add(key)
        check(actual.get(key) == after, "Only exact4decimal-mil XY output normalization " + placement["ref"],
              {"idealXYMil": [target["x"], target["y"]], "expectedNativeXYMil": [after["x"], after["y"]],
               "actualXYMil": [actual.get(key, {}).get("x"), actual.get(key, {}).get("y")]})
        coordinates.append({"ref": placement["ref"], "componentId": cid,
            "deltaMil": [after["x"]-target["x"], after["y"]-target["y"]],
            "deltaMm": [(after["x"]-target["x"])*.0254, (after["y"]-target["y"])*.0254]})
        angle = math.radians(target["angle"]-old["angle"])
        for k, b in before.items():
            if k[0] != "ATTR" or b.get("parentId") != cid: continue
            e = dict(b)
            e["angle"] = (b["angle"]+target["angle"]-old["angle"]) % 360
            if b.get("x") is not None and b.get("y") is not None:
                dx, dy = b["x"]-old["x"], b["y"]-old["y"]
                e["x"] = round(target["x"]+dx*math.cos(angle)-dy*math.sin(angle), 4)
                e["y"] = round(target["y"]+dx*math.sin(angle)+dy*math.cos(angle), 4)
            expected[k] = e
            owned.add(k)
            check(actual.get(k) == e, "Owned ATTR exact rigid rotation/translation plus4decimal output " + placement["ref"]+"."+b["key"],
                  {"id": k[1], "expected": e, "actual": actual.get(k)} if actual.get(k) != e else {"id": k[1]})
            attr_models.append({"ref": placement["ref"], "id": k[1], "key": b["key"], "expectedBody": e})
    missing, added = expected.keys()-actual.keys(), actual.keys()-expected.keys()
    diffs = [{"type": k[0], "id": k[1], "fields": [f for f in expected[k].keys()|actual[k].keys() if expected[k].get(f) != actual[k].get(f)]}
             for k in expected.keys()&actual.keys() if k[0] != "DOCHEAD" and expected[k] != actual[k]]
    check(not missing and not added, "Exact full native primitive membership", {"missing": list(missing), "extra": list(added)})
    check(not diffs, "No record changes outside qualified rigid placements/owned display geometry", diffs)
    protected = {k: b for k, b in before.items() if k not in owned and k[0] != "DOCHEAD"}
    check(all(actual.get(k) == b for k, b in protected.items()), "All non-placement native bodies including40cuts/R164 exact")
    for title, kinds in [("all routed copper unchanged", {"LINE", "ARC", "FILL", "POLY"}),
                         ("all634vias/4mechanicalpads unchanged", {"VIA", "PAD"}),
                         ("all18RULEdefinitions/template unchanged", {"RULE", "RULE_TEMPLATE"}),
                         ("everyPAD_NET unchanged", {"PAD_NET"}), ("J18 strings and six-layer stack unchanged", {"STRING", "LAYER", "LAYER_PHYS"})]:
        check({k:b for k,b in before.items() if k[0] in kinds} == {k:b for k,b in actual.items() if k[0] in kinds}, title)
    attrs = defaultdict(dict)
    for (kind, rid), b in actual.items():
        if kind == "ATTR": attrs[b["parentId"]][b["key"]] = b["value"]
    refs = {a["Designator"]: cid for cid, a in attrs.items() if "Designator" in a}
    inverse = {cid: ref for ref, cid in refs.items()}
    pins = {}
    for (kind, rid), b in actual.items():
        if kind != "PAD_NET" or not b.get("padNet"): continue
        _, cid, num, pid = json.loads(rid)
        key = inverse[cid], str(num)
        check(key not in pins or pins[key] == b["padNet"], "Duplicate physical pin nets agree " + str(key))
        pins[key] = b["padNet"]
    contract_path = ROOT / "output/candidates/adc10-dc-buffer-20261017/independent-adc10-expected-full-pin-contract-20261017.json"
    cp = {(r["ref"], str(r["number"])):r["net"] for r in json.loads(contract_path.read_text())["expectedPins"]}
    check(len(refs) == 354 and len(pins) == 1136 and pins == cp, "Frozen354parts1136pins exact independent schematic contract")
    tag = "-"+args.tag if args.tag else ""
    out = HERE / f"adc10-strip-place{args.stage}{tag}-independent-placement-audit-20261018.json"
    report = {"schema":"stm32h747-adc10-strip-rigid-placement-independent-audit-20261018-v1",
        "passed":not errors,"errors":errors,"stage":args.stage,"sourcePath":str(source),"sourceSha256":sha(source),
        "baselinePath":str(BASE),"baselineSha256":BASE_SHA,"placementManifestPath":str(PLAN),"placementManifestSha256":PLAN_SHA,
        "qualifiedPlacedComponents":len(placements),"ownedATTRGeometryRecords":len(attr_models),"protectedNativeBodies":len(protected),
        "physicalParts":len(refs),"connectedPins":len(pins),"coordinateRepresentations":coordinates,"attributeRigidModels":attr_models,
        "maxCoordinateOutputErrorMm":max(abs(x) for c in coordinates for x in c["deltaMm"]),"checks":checks,
        "limitations":["Actual source record/rigid placement proof only, not copper completion or finalDRC.",
            "All component XY coordinates must equal round(approvedTargetMil,4), all other component fields exact. Display attributes use exact rigid transform then4decimal output; no broad field tolerance.",
            "This stage deliberately expects every FILL unchanged. The later reviewed GND path modification requires a separate actual polygon/ground-connectivity audit."],
        "liveAPICalls":0,"nativeFilesWritten":0}
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"passed":not errors,"path":str(out),"sha256":sha(out),"placedComponents":len(placements),
        "physicalParts":len(refs),"connectedPins":len(pins),"maxXYOutputErrorMm":report["maxCoordinateOutputErrorMm"],
        "errorTests":[e["test"] for e in errors]},indent=2))
    if errors:raise SystemExit(1)


if __name__ == "__main__":main()
