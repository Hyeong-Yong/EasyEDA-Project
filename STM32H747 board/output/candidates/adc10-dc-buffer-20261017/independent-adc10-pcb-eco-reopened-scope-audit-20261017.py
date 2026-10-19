"""Read-only PCB ECO save/reopen and whole-checkpoint preservation proof."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import runpy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION = ROOT / "output/validation"
BEFORE_SOURCE = VALIDATION / "native-adc10-pcb-eco_applied-20261017.epru"
AFTER_SOURCE = VALIDATION / "native-adc10-pcb-eco_reopened-20261017.epru"
BEFORE_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_adc10_schematic_20261017.epro2"
AFTER_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_adc10_pcb_eco_wip_20261017.epro2"
TARGET = ("PCB", "0ac2a19168000d8e")
M = runpy.run_path(str(HERE / "independent-adc10-checkpoint-scope-audit-20261017.py"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_records(path):
    rows = {}
    for raw in path.read_text(encoding="utf8").splitlines():
        if not raw.strip():
            continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], str(h.get("id", ""))
        assert key not in rows, key
        rows[key] = (h, b, raw)
    return rows


def info(path):
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path)}


def main():
    errors = []
    a, b = source_records(BEFORE_SOURCE), source_records(AFTER_SOURCE)
    changed_keys = [key for key in sorted(a.keys() | b.keys())
                    if a.get(key, (None, None))[:2] != b.get(key, (None, None))[:2]]
    serialized_keys = [key for key in sorted(a.keys() & b.keys()) if a[key][2] != b[key][2]]
    reordered_keys = [key for key in serialized_keys if key[0] != "DOCHEAD"]
    designators = {row[1]["parentId"]: row[1]["value"] for key, row in b.items()
                   if key[0] == "ATTR" and row[1].get("key") == "Designator"}
    reordered_refs = {designators.get(key[1]) for key in reordered_keys}
    expected_target_refs = ({f"C{i}" for i in range(97, 120)} |
                            {f"U{i}" for i in range(9, 20)} |
                            {f"R{i}" for i in range(137, 146)} |
                            {f"R{i}" for i in range(149, 158)} |
                            {f"R{i}" for i in range(161, 173)} |
                            {f"C{i}" for i in [80, 81, 82, 86, 87, 88, 93, 94, 95, 96]})
    if a.keys() != b.keys() or any(key[0] != "DOCHEAD" for key in changed_keys):
        errors.append("Native applied/reopened source records differ outside DOCHEAD")
    if sha(AFTER_SOURCE) != "342e8f1baecba1759fc477f0ac42f252f80ea2ac08de380d90c160c6853f786f":
        errors.append("Unexpected reopened source hash")
    if len(reordered_keys) != 74 or reordered_refs != expected_target_refs or any(key[0] != "COMPONENT" or a[key][:2] != b[key][:2] for key in reordered_keys):
        errors.append("Unexpected save/reopen key-order-only serialization differences")
    before, before_stats = M["materialize"](BEFORE_CHECKPOINT)
    after, after_stats = M["materialize"](AFTER_CHECKPOINT)
    if before.keys() != after.keys():
        errors.append("Whole checkpoint document identities changed")
    protected, changed = [], []
    for doc in sorted(before.keys() & after.keys()):
        old, new = before[doc], after[doc]
        parsed_equal = {k: v[:2] for k, v in old.items()} == {k: v[:2] for k, v in new.items()}
        raw_equal = {k: v[2] for k, v in old.items()} == {k: v[2] for k, v in new.items()}
        row = {"doc_type": doc[0], "uuid": doc[1],
               "before_live_records": len(old), "after_live_records": len(new),
               "headers_and_bodies_equal": parsed_equal,
               "exact_serialized_record_lines_equal": raw_equal,
               "before_materialized_sha256": M["record_digest"](old),
               "after_materialized_sha256": M["record_digest"](new),
               "before_exact_record_lines_sha256": M["record_digest"](old, True),
               "after_exact_record_lines_sha256": M["record_digest"](new, True)}
        if doc == TARGET:
            changed.append(row)
        else:
            protected.append(row)
            if not parsed_equal or not raw_equal:
                errors.append("Protected document changed: " + "/".join(doc))
    if len(protected) != 3923 or len(changed) != 1 or changed[0]["headers_and_bodies_equal"]:
        errors.append("Unexpected target/protected document state")
    report = {
        "schema": "stm32h747-adc10-independent-pcb-eco-save-reopen-scope-v1",
        "passed": not errors, "errors": errors,
        "appliedSource": {**info(BEFORE_SOURCE), "record_count": len(a)},
        "reopenedSource": {**info(AFTER_SOURCE), "record_count": len(b)},
        "sourceChangedRecordIdentities": [list(k) for k in changed_keys],
        "allNonDOCHEADParsedSourceHeadersAndBodiesExactlyEqual": not any(k[0] != "DOCHEAD" for k in changed_keys),
        "sourceKeyOrderOnlyReencodedRecordIdentities": [list(k) for k in reordered_keys],
        "sourceKeyOrderOnlyReencodedTargetReferences": sorted(reordered_refs),
        "sourceKeyOrderNormalizationExplanation": "Exactly the 74 new/replaced COMPONENT records serialize nested attrs.Unique ID before Reuse Block after reopening. Full parsed headers, bodies, values, IDs, geometry and tickets are identical; only JSON dictionary member order differs. This is not treated as an electrical or geometric change.",
        "beforeCheckpoint": {**info(BEFORE_CHECKPOINT), **before_stats},
        "afterCheckpoint": {**info(AFTER_CHECKPOINT), **after_stats},
        "changedTargetPCB": changed,
        "protectedDocumentCount": len(protected),
        "protectedDocumentTypes": dict(sorted(Counter(k["doc_type"] for k in protected).items())),
        "allProtectedHeadersAndBodiesEqual": all(r["headers_and_bodies_equal"] for r in protected),
        "allProtectedSerializedRecordLinesByteEqual": all(r["exact_serialized_record_lines_equal"] for r in protected),
        "protectedDocuments": protected,
        "limitations": ["This is source/checkpoint preservation proof only. ECO parts are not yet placed/routed and fabrication approval is withheld.",
                        "Native empty-body tombstones are excluded only after selecting the latest-ticket effective record. All prior log history stays untouched."],
        "liveAPICalls": 0, "nativeFilesWritten": 0,
    }
    out = HERE / "independent-adc10-pcb-eco-reopened-scope-audit-20261017.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": sha(out), "passed": not errors,
                      "protected_documents": len(protected), "source_changed_records": [list(k) for k in changed_keys],
                      "all_protected_record_lines_byte_equal": report["allProtectedSerializedRecordLinesByteEqual"],
                      "errors": errors}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
