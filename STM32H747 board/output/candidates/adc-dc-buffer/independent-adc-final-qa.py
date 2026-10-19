"""Final/reopened preservation and fresh native Protel2 ADC ECO audit."""
import hashlib
import json
import re
import runpy
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALID = ROOT / "output/validation"
QA = runpy.run_path(str(HERE / "independent-static-adc-plan-review.py"))
NET = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))
PARSE = QA["parse"]
PLAN = QA["PLAN"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_delta(first, second, permit_font=False, permit_reopen=False):
    a, b = PARSE(first), PARSE(second)
    errors, changes, rules = [], [], Counter()
    for key in a.keys() - b.keys():
        errors.append({"missingRecord": key})
    revision_notes = []
    for key in b.keys() - a.keys():
        body = b[key]
        if (permit_reopen and key == ("TEXT", "f4ba1d7115d2fc19")
                and body.get("x") == 1045 and body.get("y") == 735
                and body.get("value") == "ADC1 DC revision 2026-10-16"
                and body.get("fontSize") == 6 and body.get("rotation") == 0):
            revision_notes.append({"record": key, "body": body})
            rules["explicit permitted on-page revision annotation"] += 1
        else:
            errors.append({"extraRecord": key, "body": body})
    absent = object()
    for key in sorted(a.keys() & b.keys()):
        for field in a[key].keys() | b[key].keys():
            old, new = a[key].get(field, absent), b[key].get(field, absent)
            if old == new:
                continue
            rule = None
            if key[0] == "DOCHEAD" and field in {"updateTime", "version", "client"}:
                rule = "session header bookkeeping"
            if permit_font and key[0] == "ATTR" and a[key].get("key") == "NET" and field == "fontSize" and old is None and new == 0.001:
                rule = "exact thirty added NET display fonts set to epsilon"
            if permit_reopen and key[0] == "ATTR":
                if field == "zIndex" and isinstance(old, (int, float)) and isinstance(new, (int, float)) and 0 <= new <= 30:
                    rule = "native attribute display-order renumber"
                if field == "strikeout" and old is absent and new is False:
                    rule = "native explicit false strikeout default"
            change = {"record": key, "field": field, "before": "<absent>" if old is absent else old,
                      "after": "<absent>" if new is absent else new, "rule": rule}
            changes.append(change)
            if rule:
                rules[rule] += 1
            else:
                errors.append(change)
    if permit_font and rules["exact thirty added NET display fonts set to epsilon"] != 30:
        errors.append({"fontCount": rules["exact thirty added NET display fonts set to epsilon"]})
    return {"passed": not errors, "beforePath": str(first), "afterPath": str(second),
            "beforeSha256": sha(first), "afterSha256": sha(second), "beforeRecords": len(a), "afterRecords": len(b),
            "ruleCounts": dict(rules), "revisionNotes": revision_notes, "changes": changes, "errors": errors}


def net_nodes(path):
    raw = Path(path).read_text(encoding="utf8").replace("\r\n", "\n")
    pins = NET["parse_protel2"](raw)
    nodes = {(p["ref"], p["number"]): p["net"] for p in pins}
    assert len(pins) == len(nodes)
    components = {block.splitlines()[1]: block for block in re.findall(r"(?ms)^\[\n(.*?)^\]", raw)}
    return nodes, components


def display_delta(first, second):
    plan = json.loads((HERE / "adc-dc-18-display-attrs-plan.json").read_text(encoding="utf8"))
    assert sha(first) == plan["baselineSha256"]
    before, after = PARSE(first), PARSE(second)
    edits = {("ATTR", e["id"]): e for e in plan["edits"]}
    errors = []
    for key in before.keys() ^ after.keys():
        errors.append({"unexpectedRecordMembershipChange": key})
    exact_other = 0
    for key in before.keys() & after.keys():
        if key in edits:
            if before[key] != edits[key]["before"] or after[key] != edits[key]["after"]:
                errors.append({"notExactApprovedLabelBody": key})
        elif before[key] == after[key]:
            exact_other += 1
        elif key[0] == "DOCHEAD":
            differences = {f for f in before[key].keys() | after[key].keys() if before[key].get(f) != after[key].get(f)}
            if differences - {"client", "updateTime", "version"}:
                errors.append({"unexpectedHeaderChange": sorted(differences)})
            else:
                exact_other += 1
        else:
            errors.append({"unapprovedOtherBodyChange": key})
    return {"passed": not errors, "beforePath": str(first), "finalSourcePath": str(second),
            "finalSourceSha256": sha(second), "approvedAttributeBodiesExact": len(edits),
            "otherBodiesExactExceptSessionHeader": exact_other, "electricalChanges": 0,
            "errors": errors}


def main():
    accepted = VALID / "native-adc-dc-accepted-20261016.epru"
    finalized = VALID / "native-adc-dc-finalized-20261016.epru"
    reopened = VALID / "native-adc-dc-final-reopened-20261016.epru"
    display_final = VALID / "native-adc-dc-display-final-reopened-20261016.epru"
    font_delta = source_delta(accepted, finalized, permit_font=True)
    reopen_delta = source_delta(finalized, reopened, permit_reopen=True)
    label_delta = display_delta(reopened, display_final)
    fresh_path = VALID / "native-adc-dc-Protel2-20261016.net"
    old_path = VALID / "native-final-Protel2_durable_final.net"
    fresh, fresh_components = net_nodes(fresh_path)
    old, old_components = net_nodes(old_path)
    expected = dict(old)
    approved_changes = []
    for i in range(3):
        pre, drv = f"ADC1_PRE{i+1}", f"ADC1_DRV{i+1}"
        for key, new in (((f"R{137+i}", "1"), pre), ((f"R{137+i}", "2"), "ADC_BIAS_2V5"),
                         ((f"R{140+2*i}", "2"), pre), ((f"R{141+2*i}", "1"), drv), ((f"R{146+i}", "1"), pre)):
            approved_changes.append({"node": key, "oldNet": expected[key], "newNet": new})
            expected[key] = new
    graph = json.loads((HERE / "independent-static-adc-plan-review.json").read_text(encoding="utf8"))["pinGraph"]
    for ref, pins in graph.items():
        for number, data in pins.items():
            expected[(ref, number)] = data["net"]
    mismatches = [{"node": key, "expected": expected.get(key), "actual": fresh.get(key)}
                  for key in expected.keys() | fresh.keys() if expected.get(key) != fresh.get(key)]
    old_rebind = {c["ref"] for c in PLAN["components"] if not c["new"]}
    new_refs = {c["ref"] for c in PLAN["components"] if c["new"]}
    changed_component_blocks = {ref for ref in old_components.keys() & fresh_components.keys() if old_components[ref] != fresh_components[ref]}
    assert changed_component_blocks == old_rebind
    assert fresh_components.keys() - old_components.keys() == new_refs
    assert not old_components.keys() - fresh_components.keys()
    erc_path = VALID / "native-adc-dc-erc-20261016.json"
    erc = json.loads(erc_path.read_text(encoding="utf8"))
    nodes_report = {"passed": not mismatches, "baselineConnectedPins": len(old), "finalConnectedPins": len(fresh),
        "newPins": len(fresh.keys() - old.keys()), "missingOriginalPins": len(old.keys() - fresh.keys()),
        "approvedOriginalPinNetChanges": approved_changes, "unexpectedNodeMismatches": mismatches,
        "allTarget60PinMappingsMatchIndependentSourceGraph": not mismatches,
        "originalUnaffectedConnectedPinsExact": len(old) - len(approved_changes),
        "physicalSchematicComponentsBefore": len(old_components), "physicalSchematicComponentsAfter": len(fresh_components),
        "changedOldComponentBlocksExactlyApproved12Rebinds": sorted(changed_component_blocks),
        "allOther318OldComponentBlocksExact": True, "new13ComponentRefs": sorted(new_refs),
        "freshNetlistSha256": sha(fresh_path), "baselineNetlistSha256": sha(old_path),
        "nativeErcPassed": erc.get("passed") is True}
    report = {"schema": "independent-adc-final-qa-20261016-v1", "passed": font_delta["passed"] and reopen_delta["passed"] and label_delta["passed"] and nodes_report["passed"] and nodes_report["nativeErcPassed"],
        "acceptedToFinalized": font_delta, "finalizedToReopened": reopen_delta,
        "finalExact18DisplayAttributes": label_delta, "freshNativeNetlist": nodes_report,
        "dcContract": {"seriesDcBlockingCapacitors": 0, "gain": 0.5, "offsetV": 1.25,
                       "inputRangeV": [-2, 2], "adcRangeV": [0.25, 2.25], "threeIndependentFollowers": True},
        "pcbAdcEcoApplied": False, "pcbAdcComponentDiscrepancyExpected": "343 physical schematic components vs old PCB330; ADC PCB ECO intentionally not applied", "manufacturingApproval": False}
    path = HERE / "independent-adc-final-qa.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": report["passed"], "acceptedToFinalized": font_delta["passed"], "finalizedToReopened": reopen_delta["passed"],
                      "reopenErrors": reopen_delta["errors"], "displayFinal": label_delta, "freshNetlist": nodes_report}, indent=2))
    if not report["passed"]:
        raise ValueError("Final ADC QA has remaining source/readback or netlist blocker")


if __name__ == "__main__":
    main()
