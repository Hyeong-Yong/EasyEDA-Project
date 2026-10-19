"""Prepare exactly eighteen display-only label edits from the frozen saved source."""
import copy
import hashlib
import json
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "output/validation/native-adc-dc-final-reopened-20261016.epru"
QA = runpy.run_path(str(HERE / "independent-static-adc-plan-review.py"))


def main():
    source = SOURCE.read_text(encoding="utf8")
    before = QA["parse"](SOURCE)
    after = copy.deepcopy(before)
    components = {rid: body for (kind, rid), body in before.items() if kind == "COMPONENT"}
    refs = {body["value"]: body["parentId"] for (kind, rid), body in before.items() if kind == "ATTR" and body.get("key") == "Designator"}
    edits = []
    for ref in ("U10", "U11", "U12", "C80", "C81", "C82", "C103", "C104", "C105"):
        cid = refs[ref]
        component = components[cid]
        for attribute_key in ("Designator", "Value"):
            matches = [key for key, body in before.items() if key[0] == "ATTR" and body.get("parentId") == cid and body.get("key") == attribute_key]
            assert len(matches) == 1
            key = matches[0]
            body = after[key]
            old = copy.deepcopy(body)
            if ref.startswith("U"):
                body["x"] = 205
                body["y"] = component["y"] - (43 if attribute_key == "Designator" else 36)
            else:
                body["x"] = component["x"] + 15
            fields = sorted(field for field in body if old[field] != body[field])
            assert fields in (["x", "y"], ["x"])
            assert body["value"] == old["value"] and body["parentId"] == old["parentId"]
            edits.append({"id": key[1], "type": "ATTR", "ref": ref, "attributeKey": attribute_key,
                          "changedFields": fields, "before": old, "after": copy.deepcopy(body)})
    assert len(edits) == 18
    edited_ids = {x["id"] for x in edits}
    assert sum(before[key] != after[key] for key in before) == 18
    output = []
    for raw in source.splitlines():
        if not raw.strip():
            continue
        head, body_text = raw.split("||", 1)
        header = json.loads(head)
        key = (header["type"], header.get("id"))
        output.append(head + "||" + json.dumps(after[key], separators=(",", ":")) + "|")
    candidate = "\n".join(output) + "\n"
    candidate_path = HERE / "06_ADC_TIMER_DAC_display_labels_candidate.epru"
    candidate_path.write_text(candidate, encoding="utf8", newline="\n")
    plan = {"schema": "adc-dc-18-display-attrs-20261016-v1", "sourcePath": str(SOURCE),
            "baselineSha256": hashlib.sha256(source.encode()).hexdigest(), "candidatePath": str(candidate_path),
            "candidateSha256": hashlib.sha256(candidate.encode()).hexdigest(), "pageUuid": "a07bf8e4331877a8",
            "attributeCount": 18, "edits": edits, "electricalChanges": 0,
            "allOtherRecordBodiesExact": True, "allOtherRecordCount": len(before) - 18,
            "coordinates": {"OPA320": "x205; Designator bufferY-43; Value bufferY-36", "capacitors": "existing xCentre+15; y unchanged"},
            "reason": "Keep OPA part text clear of triangle and power pin; capacitor labels clear of plate ends."}
    path = HERE / "adc-dc-18-display-attrs-plan.json"
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: v for k,v in plan.items() if k != "edits"}, indent=2))


if __name__ == "__main__":
    main()
