"""Read-only scope audit of the saved ADC10 schematic checkpoint.

The native project is an append-only .epru log.  Empty bodies are tombstones;
comparing every historical line would incorrectly treat deleted shapes as live.
This audit materializes the highest-ticket record per document/type/ID and
compares both full parsed records and their exact original serialized lines.
It never calls EasyEDA or modifies any source project/checkpoint.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BEFORE = ROOT / "output/checkpoints/STM32H747_before_adc10_20261017.epro2"
AFTER = ROOT / "output/checkpoints/STM32H747_adc10_schematic_20261017.epro2"
TARGET = ("SCH_PAGE", "a07bf8e4331877a8")
REPORT = HERE / "independent-adc10-checkpoint-scope-audit-20261017.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def materialize(path):
    with zipfile.ZipFile(path) as archive:
        names = [n for n in archive.namelist() if n.endswith(".epru")]
        assert len(names) == 1, names
        source = archive.read(names[0]).decode("utf8")
    docs = {}
    current = None
    history_tombstones = 0
    for number, raw in enumerate(source.splitlines(), 1):
        if not raw.strip():
            continue
        h, value = raw.split("||", 1)
        h = json.loads(h)
        value = value.rstrip("|")
        body = json.loads(value) if value else None
        if not isinstance(body, dict):
            history_tombstones += 1
        if h["type"] == "DOCHEAD":
            assert isinstance(body, dict), (number, h)
            current = (body["docType"], body["uuid"])
            docs.setdefault(current, {})
        assert current is not None, number
        key = (h["type"], str(h.get("id", "")))
        previous = docs[current].get(key)
        if previous is None or h.get("ticket", 0) >= previous[0].get("ticket", 0):
            docs[current][key] = (h, body, raw)
    live = {}
    removed = 0
    for doc, records in docs.items():
        live[doc] = {}
        for key, record in records.items():
            if isinstance(record[1], dict):
                live[doc][key] = record
            else:
                removed += 1
    return live, {
        "document_count": len(live),
        "document_types": dict(sorted(Counter(k[0] for k in live).items())),
        "historical_empty_or_nondict_body_records": history_tombstones,
        "effective_tombstoned_records": removed,
        "effective_live_records": sum(map(len, live.values())),
    }


def record_digest(records, exact=False):
    if exact:
        data = "\n".join(records[k][2] for k in sorted(records)).encode("utf8")
    else:
        data = json.dumps(
            [[list(k), records[k][0], records[k][1]] for k in sorted(records)],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf8")
    return sha(data)


def main():
    before, before_stats = materialize(BEFORE)
    after, after_stats = materialize(AFTER)
    errors = []
    if before.keys() != after.keys():
        errors.append("Document identity membership changed")
    protected = []
    changed = []
    for doc in sorted(before.keys() & after.keys()):
        a, b = before[doc], after[doc]
        semantic_equal = {k: r[:2] for k, r in a.items()} == {k: r[:2] for k, r in b.items()}
        raw_equal = {k: r[2] for k, r in a.items()} == {k: r[2] for k, r in b.items()}
        row = {
            "doc_type": doc[0], "uuid": doc[1],
            "before_live_records": len(a), "after_live_records": len(b),
            "header_and_body_equal": semantic_equal,
            "exact_serialized_record_lines_equal": raw_equal,
            "before_materialized_record_sha256": record_digest(a),
            "after_materialized_record_sha256": record_digest(b),
            "before_exact_record_lines_sha256": record_digest(a, True),
            "after_exact_record_lines_sha256": record_digest(b, True),
        }
        if doc == TARGET:
            changed_keys = [k for k in a.keys() | b.keys() if a.get(k) != b.get(k)]
            row["changed_record_types_including_added_deleted"] = dict(sorted(Counter(k[0] for k in changed_keys).items()))
            row["note"] = "Authorized page06 ADC10 change; native generated POLY/ELE_PLACEHOLDER caches included. Independent reopened physical graph and full-pin audit is separate."
            changed.append(row)
            if semantic_equal:
                errors.append("Target schematic page unexpectedly unchanged")
        else:
            protected.append(row)
            if not semantic_equal or not raw_equal:
                errors.append("Protected document changed: " + "/".join(doc))
    if len(protected) != 3923 or len(changed) != 1:
        errors.append("Unexpected protected/target document counts")
    report = {
        "schema": "stm32h747-independent-adc10-checkpoint-scope-v1",
        "scope": "Read-only saved checkpoint audit; only schematic page06 may change. No PCB ECO or manufacturing validation claimed.",
        "before": {"path": str(BEFORE), "file_bytes": BEFORE.stat().st_size,
                   "sha256": sha(BEFORE.read_bytes()), **before_stats},
        "after": {"path": str(AFTER), "file_bytes": AFTER.stat().st_size,
                  "sha256": sha(AFTER.read_bytes()), **after_stats},
        "target_document": changed,
        "protected_document_count": len(protected),
        "protected_document_types": dict(sorted(Counter(r["doc_type"] for r in protected).items())),
        "all_protected_header_and_body_records_equal": all(r["header_and_body_equal"] for r in protected),
        "all_protected_serialized_record_lines_byte_equal": all(r["exact_serialized_record_lines_equal"] for r in protected),
        "protected_documents": protected,
        "errors": errors, "passed": not errors,
        "native_or_API_writes": False,
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(json.dumps({"report": str(REPORT), "sha256": sha(REPORT.read_bytes()),
                     "passed": not errors, "protected_documents": len(protected),
                     "exact_serialized_records_equal": report["all_protected_serialized_record_lines_byte_equal"],
                     "changed_documents": len(changed), "errors": errors}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
