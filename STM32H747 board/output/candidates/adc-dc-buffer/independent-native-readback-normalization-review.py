"""Bounded per-field audit of native ADC page decoder normalizations."""
import copy
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
QA = runpy.run_path(str(HERE / "independent-static-adc-plan-review.py"))
PLAN = QA["PLAN"]
ACCEPTED = HERE.parents[1] / "validation/native-adc-dc-accepted-20261016.epru"


def main():
    candidate = QA["parse"](PLAN["candidatePath"])
    accepted = QA["parse"](ACCEPTED)
    baseline = QA["parse"](PLAN["baselinePath"])
    target_components = {c["componentId"] for c in PLAN["components"]}
    added_keys = {(r["h"]["type"], r["h"].get("id")) for r in PLAN["added"]}
    deleted_keys = set(candidate) - set(accepted)
    new_keys = set(accepted) - set(candidate)
    normal = copy.deepcopy(accepted)
    renames = []
    unknown = []
    changes = []
    missing = object()
    for key in sorted(deleted_keys):
        old = candidate[key]
        matches = [k for k in new_keys if k[0] == "ATTR" and accepted[k].get("parentId") == old.get("parentId") and accepted[k].get("key") == old.get("key")]
        valid = key[0] == "ATTR" and key in added_keys and old.get("parentId") in target_components and len(matches) == 1
        if not valid:
            unknown.append({"record": key, "error": "not an expected new target metadata ATTR identity remap", "matches": matches})
            continue
        replacement = matches[0]
        assert accepted[replacement]["value"] == old["value"]
        renames.append({"oldRecordId": key[1], "nativeRecordId": replacement[1], "parentId": old["parentId"], "attributeKey": old["key"], "value": old["value"]})
        normal[key] = normal.pop(replacement)
        new_keys.remove(replacement)
    if new_keys:
        unknown.append({"unexpectedAddedRecords": sorted(new_keys)})
    bias_positions = {"7ddd73c0b38755f1": 345, "d6843d6273b35f38": 680, "f6a06b7190d45f7e": 1010}
    normalized_fields = Counter()
    renamed_metadata_records = {("ATTR", x["oldRecordId"]) for x in renames}
    for record in sorted(set(candidate) & set(normal)):
        expected = candidate[record]
        actual = normal[record]
        original_actual = copy.deepcopy(actual)
        if actual == expected:
            continue
        for field in sorted(expected.keys() | actual.keys()):
            ev, av = expected.get(field, missing), actual.get(field, missing)
            if ev == av:
                continue
            rule = None
            kind, rid = record
            if kind == "DOCHEAD" and field in {"updateTime", "version", "client"}:
                rule = "document session/header bookkeeping only"
            elif kind == "COMPONENT" and rid in target_components and field == "attrs":
                ea, aa = copy.deepcopy(ev), copy.deepcopy(av)
                symbol_name = ea.pop("SymbolName", None)
                if symbol_name is not None and "SymbolName" not in aa and ea == aa:
                    attrs = {b["key"]: b["value"] for (t, i), b in normal.items() if t == "ATTR" and b.get("parentId") == rid}
                    parsed_symbol = json.loads(symbol_name)
                    if parsed_symbol["uuid"] == attrs.get("Symbol"):
                        rule = "redundant COMPONENT attrs.SymbolName removed; electrical Symbol ATTR UUID exact"
            elif kind == "LINE" and record in added_keys and field == "strokeWidth" and ev == 0.6 and av is None:
                rule = "new wire default stroke width 0.6 serialized as null"
            elif kind == "TEXT" and record in added_keys:
                if field == "fillColor" and ev is None and av == expected.get("color"):
                    rule = "new text fillColor inherits exact existing text color"
                elif field == "strikeout" and ev is False and av is missing:
                    rule = "false strikeout omitted"
            elif kind == "ATTR":
                ak, parent = expected.get("key"), expected.get("parentId")
                if field == "strikeout" and ev is False and av is missing:
                    rule = "false strikeout omitted"
                elif field == "zIndex" and isinstance(ev, (int, float)) and isinstance(av, (int, float)) and 0 <= av <= 30:
                    rule = "attribute display-order renumber only"
                elif field == "fontFamily" and parent in target_components and ak in {"Designator", "Value"} and ev is None and av == "Arial":
                    rule = "visible target-component attribute default font Arial"
                elif field in {"fontWeight", "italic", "underline"} and parent in target_components and ak in {"Designator", "Value"} and ev is None and av is False:
                    rule = "visible target-component attribute false default font style"
                elif field == "color" and parent in target_components and ak in {"Designator", "Value"} and ev is None and av == "#000080":
                    rule = "visible target-component default attribute color"
                elif field == "fillColor" and parent in target_components and ak in {"Designator", "Value"} and ev is None and av == original_actual.get("color"):
                    rule = "visible target-component attribute fillColor inherits exact color"
                elif field == "valueVisible" and ak == "NET" and ev is False and av is True:
                    rule = "wire net-label display enabled; net value and identity unchanged"
                elif parent in bias_positions and ak == "NET" and expected.get("value") == "ADC_BIAS_2V5":
                    if (field == "x" and ev is None and av == bias_positions[parent]) or (field == "y" and ev is None and av == 150) or (field == "rotation" and ev == 0 and av == 90):
                        rule = "three changed bias labels assigned exact native display anchor"
                if rule is None and record in renamed_metadata_records and parent in target_components and expected.get("x") is None and expected.get("y") is None:
                    if ((field == "align" and ev == "LEFT_BOTTOM" and av is None)
                            or (field in {"fontWeight", "italic", "underline", "keyVisible", "valueVisible"} and ev is False and av is None)
                            or (field == "rotation" and ev == 0 and av is None)
                            or (field == "locked" and ev is False and av is missing)):
                        rule = "42 recreated hidden metadata ATTR records clear unused display defaults only"
            changes.append({"record": record, "field": field, "expected": "<absent>" if ev is missing else ev,
                            "actual": "<absent>" if av is missing else av, "rule": rule})
            if rule is None:
                unknown.append(changes[-1])
                continue
            normalized_fields[rule] += 1
            if ev is missing:
                actual.pop(field, None)
            else:
                actual[field] = copy.deepcopy(ev)
    fully_equal = normal == candidate
    protected = {k for k in baseline.keys() & candidate.keys() if baseline[k] == candidate[k]}
    protected_exact_raw = sum(k in accepted and baseline[k] == accepted[k] for k in protected)
    protected_normalized = sum(k in normal and baseline[k] == normal[k] for k in protected)
    report = {"passed": not unknown and fully_equal, "candidateSha256": PLAN["candidateSha256"],
        "acceptedPath": str(ACCEPTED), "acceptedSha256": hashlib.sha256(ACCEPTED.read_bytes()).hexdigest(),
        "candidateRecordCount": len(candidate), "acceptedRecordCount": len(accepted),
        "metadataAttributeIdRemaps": renames, "metadataAttributeIdRemapCount": len(renames),
        "normalizationRuleCounts": dict(normalized_fields), "normalizations": changes,
        "unclassifiedChanges": unknown, "normalizedAcceptedExactlyEqualsCandidate": fully_equal,
        "protectedBaselineRecordCount": len(protected), "protectedRawExactCount": protected_exact_raw,
        "protectedNormalizedExactCount": protected_normalized,
        "electricalNetValuesUuidBindingsPinGeometryAndComponentPositions": "exact candidate equality after only explicit display/session/metadata-ID rules",
        "staticCandidateGraphProofCarriesForward": fully_equal,
        "manufacturingApproval": False}
    path = HERE / "independent-native-readback-normalization-review.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"normalizations", "metadataAttributeIdRemaps", "unclassifiedChanges"}}, indent=2))
    print("unclassifiedChanges", len(unknown))
    if not report["passed"]:
        raise ValueError("Unexpected non-normalization source changes")


if __name__ == "__main__":
    main()
