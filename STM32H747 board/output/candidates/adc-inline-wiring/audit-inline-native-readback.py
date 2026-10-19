"""Strict read-only native decoder normalization audit for inline ADC redraw."""
import argparse
import copy
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARSE = runpy.run_path(str(HERE.parent / "adc-dc-buffer/independent-static-adc-plan-review.py"))["parse"]
PLAN = json.loads((HERE / "adc-inline-schematic-plan.json").read_text(encoding="utf8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT / "output/validation/native-adc-inline-accepted-20261016.epru")
    ap.add_argument("--tag", default="accepted")
    args = ap.parse_args()
    candidate, baseline, actual = PARSE(PLAN["candidatePath"]), PARSE(PLAN["baselinePath"]), PARSE(args.source)
    assert hashlib.sha256(Path(PLAN["candidatePath"]).read_bytes()).hexdigest() == PLAN["candidateSha256"]
    errors, normalized = [], []
    changed_plan = {(x["type"],x["id"]) for x in PLAN["changes"]}
    added_plan = {(x["h"]["type"],x["h"].get("id")) for x in PLAN["added"]}
    deleted_plan = {(x["h"]["type"],x["h"].get("id")) for x in PLAN["deleted"]}
    if candidate.keys() != actual.keys():
        errors.append({"unexpectedRecordKeys": {"missing": sorted(candidate.keys()-actual.keys()),"added":sorted(actual.keys()-candidate.keys())}})
    attrs = {v["parentId"]: v["value"] for (k,_),v in candidate.items() if k=="ATTR" and v.get("key")=="NET"}
    for key in candidate.keys() & actual.keys():
        a,b = candidate[key],actual[key]
        if a == b:
            continue
        fields = {f for f in a.keys() | b.keys() if a.get(f,"__ABSENT__") != b.get(f,"__ABSENT__")}
        rule = None
        if key[0] == "DOCHEAD" and fields <= {"client","version","updateTime"}:
            rule = "session-header only"
        elif key[0] == "LINE" and key in added_plan and fields == {"strokeWidth"} and a.get("strokeWidth") == .6 and b.get("strokeWidth") is None:
            rule = "new wire LINE default strokeWidth 0.6 to null native default"
        elif key[0] == "POLY" and key in changed_plan | added_plan and fields == {"points"}:
            without_hash = lambda points: [{k:v for k,v in p.items() if k != "hashed"} for p in points]
            if without_hash(a["points"]) == without_hash(b["points"]) and all(isinstance(p.get("hashed"),int) for p in b["points"]):
                rule = "moved/new POLY recomputed integer point hashes; all other point fields exact"
        elif key[0] == "ATTR" and fields == {"zIndex"} and a.get("key") in {"NET","Relevance"}:
            net = attrs.get(a.get("parentId"),"")
            z_expected = {"NET": (7,6), "Relevance":(6,5)} if net.startswith("ADC1_PRE") else {"NET":(3,8),"Relevance":(2,7)} if net.startswith("ADC1_DRV") else {}
            if (a.get("zIndex"),b.get("zIndex")) == z_expected.get(a.get("key")):
                rule = "six inline wire NET/Relevance display z-order normalization"
        if rule:
            normalized.append({"record":key,"fields":sorted(fields),"rule":rule})
        else:
            errors.append({"record":key,"fields":sorted(fields),"error":"unclassified native change"})
    protected = set(baseline) - changed_plan - deleted_plan
    protected_diffs = [k for k in protected if k not in actual or baseline[k] != actual[k]]
    classified_keys = {tuple(n["record"]) for n in normalized}
    if set(protected_diffs) - classified_keys:
        errors.append({"protectedUnclassifiedChanges":sorted(set(protected_diffs)-classified_keys)})
    target_nets = {f"ADC1_{t}{n}" for t in ("PRE","DRV") for n in (1,2,3)}
    net_labels = [{"id":rid,"net":v["value"],"fontSize":v.get("fontSize"),"valueVisible":v.get("valueVisible")} for (k,rid),v in actual.items() if k=="ATTR" and v.get("key")=="NET" and v.get("value") in target_nets]
    if len(net_labels) != 6 or any(v["fontSize"] != .001 for v in net_labels):
        errors.append({"hiddenNetFontContractFailed":net_labels})
    report = {"passed":not errors,"sourcePath":str(args.source),"sourceSha256":hashlib.sha256(args.source.read_bytes()).hexdigest(),"candidateSha256":PLAN["candidateSha256"],"recordCount":len(actual),"allRecordKeysExact":candidate.keys()==actual.keys(),"normalizationCounts":dict(Counter(x["rule"] for x in normalized)),"normalizations":normalized,"allActualCoordinatesPinBindingsValuesNetsUuidsExact":not errors,"protectedBaselineRecordCount":len(protected),"protectedBaselineRawExactCount":len(protected)-len(protected_diffs),"protectedNormalizedDifferences":[n for n in normalized if tuple(n["record"]) in protected],"preDrvNetLabelFonts":net_labels,"epsilonFontRepairRequired":False,"nativeErcAndNetlistStillRequired":True,"errors":errors}
    path = HERE / f"adc-inline-{args.tag}-normalization-audit.json"
    path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"normalizations","protectedNormalizedDifferences","preDrvNetLabelFonts"}},indent=2))
    if errors:
        raise ValueError("Native inline readback mismatch")


if __name__ == "__main__":
    main()
