#!/usr/bin/env python3
"""Verify the 48 reviewed SMA post inner-layer masks in a saved checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROJECT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_BASELINE = ROOT / "output/checkpoints/STM32H747_after_missing_pad_children_created_20261014.epro2"
DEFAULT_MANIFEST = ROOT / "output/native-libraries/sma-owned-post-inner-layer-candidates/manifest.json"
DEFAULT_REPORT = ROOT / "output/validation/native-sma-owned-post-inner-layer-checkpoint-audit.json"
ALLOWED_DOCHEAD_FIELDS = {"updateTime", "version", "user"}
DIMENSION_TOLERANCE_MIL = 0.00005


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    head: dict[str, Any]
    body: dict[str, Any] | None

    @property
    def key(self) -> tuple[str, str]:
        return str(self.head.get("type") or ""), str(self.head.get("id") or "")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_records(text: str, label: str) -> tuple[dict[str, list[Record]], list[str]]:
    documents: dict[str, list[Record]] = {}
    order: list[str] = []
    current: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        source = line[:-1] if line.endswith("|") else line
        if "||" not in source:
            raise AuditError(f"{label}:{number}: missing ||")
        head_text, body_text = source.split("||", 1)
        try:
            head = json.loads(head_text)
            body = json.loads(body_text) if body_text else None
        except json.JSONDecodeError as exc:
            raise AuditError(f"{label}:{number}: invalid JSON") from exc
        record = Record(head, body)
        if head.get("type") == "DOCHEAD":
            current = str((body or {}).get("uuid") or "")
            if not current or current in documents:
                raise AuditError(f"{label}:{number}: duplicate or empty document UUID")
            documents[current] = []
            order.append(current)
        if current is None:
            raise AuditError(f"{label}:{number}: record before DOCHEAD")
        documents[current].append(record)
    return documents, order


def read_checkpoint(path: Path) -> tuple[dict[str, list[Record]], list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".epru")]
        if names != [PROJECT_MEMBER]:
            raise AuditError(f"{path}: expected only {PROJECT_MEMBER}, got {names}")
        return parse_records(archive.read(PROJECT_MEMBER).decode("utf-8-sig"), str(path))


def read_candidate(path: Path) -> tuple[str, list[Record]]:
    documents, order = parse_records(path.read_text(encoding="utf-8-sig"), str(path))
    if len(order) != 1:
        raise AuditError(f"{path}: expected one document")
    return order[0], documents[order[0]]


def rows_by_key(rows: list[Record], label: str) -> dict[tuple[str, str], Record]:
    result: dict[tuple[str, str], Record] = {}
    for row in rows:
        if row.head.get("type") == "DOCHEAD":
            continue
        if not row.key[1] or row.key in result:
            raise AuditError(f"{label}: empty or duplicate record key {row.key}")
        result[row.key] = row
    return result


def close_value(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=DIMENSION_TOLERANCE_MIL)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(close_value(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(close_value(left[key], right[key]) for key in left)
    return left == right


def normalize_pad_body(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    if result.get("attrsMap") == {}:
        result.pop("attrsMap")
    if result.get("propagationDelay") is None:
        result["propagationDelay"] = 0
    return result


def allowed_reticket(before: Record, after: Record) -> bool:
    if before.key != after.key:
        return False
    if set(after.head) not in (set(before.head), set(before.head) | {"firstTicket"}):
        return False
    for field in set(before.head) - {"ticket", "firstTicket"}:
        if before.head.get(field) != after.head.get(field):
            return False
    expected_first = before.head.get("firstTicket", before.head.get("ticket"))
    return after.head.get("firstTicket") == expected_first


def allowed_empty_footprint_attr_normalization(before: Record, after: Record) -> bool:
    if before.head.get("type") != "ATTR" or not allowed_reticket(before, after):
        return False
    left = dict(before.body or {})
    right = dict(after.body or {})
    if left.get("key") != "Footprint" or left.get("value") != "" or right.get("value") is not None:
        return False
    left.pop("value", None)
    right.pop("value", None)
    return left == right


def audit_ui_state_normalization(uuid: str, before: list[Record], after: list[Record]) -> dict[str, Any]:
    if not before or not after or before[0].head.get("type") != "DOCHEAD" or after[0].head.get("type") != "DOCHEAD":
        raise AuditError(f"{uuid}: invalid UI-state document")
    doc_type = str(before[0].body.get("docType") or "")
    if after[0].body.get("docType") != doc_type:
        raise AuditError(f"{uuid}: UI-state document type changed")
    unsupported_dochead = changed_fields(before[0].body, after[0].body) - ALLOWED_DOCHEAD_FIELDS
    if unsupported_dochead:
        raise AuditError(f"{uuid}: unsupported UI-state DOCHEAD changes {sorted(unsupported_dochead)}")
    left = rows_by_key(before, uuid + ":ui-before")
    right = rows_by_key(after, uuid + ":ui-after")
    if set(left) != set(right):
        raise AuditError(f"{uuid}: UI-state record identity set changed")
    changed = [key for key in left if left[key] != right[key]]
    if doc_type == "SCH_PAGE" and changed == [("META", "META")]:
        old, new = left[changed[0]], right[changed[0]]
        if changed_fields(old.body, new.body) == {"zIndex"} and old.body.get("zIndex") == 2 and new.body.get("zIndex") == 2.5 and allowed_reticket(old, new):
            return {"uuid": uuid, "doc_type": doc_type, "record": list(changed[0]), "change": "META.zIndex 2 -> 2.5", "semantic_primitives_changed": 0}
    if doc_type == "PCB" and changed == [("ACTIVE_LAYER", "ACTIVE_LAYER")]:
        old, new = left[changed[0]], right[changed[0]]
        if changed_fields(old.body, new.body) == {"layerId"} and allowed_reticket(old, new):
            return {"uuid": uuid, "doc_type": doc_type, "record": list(changed[0]), "change": f"ACTIVE_LAYER.layerId {old.body.get('layerId')} -> {new.body.get('layerId')}", "semantic_primitives_changed": 0}
    raise AuditError(f"{uuid}: unreviewed external document changes {changed}")


def changed_fields(left: dict[str, Any], right: dict[str, Any]) -> set[str]:
    return {key for key in set(left) | set(right) if left.get(key) != right.get(key)}


def audit_target(
    item: dict[str, Any],
    baseline: list[Record],
    actual: list[Record],
    candidate: list[Record],
) -> dict[str, Any]:
    reference = str(item["reference"])
    uuid = str(item["footprint_uuid"])
    if not baseline or not actual or baseline[0].head.get("type") != "DOCHEAD" or actual[0].head.get("type") != "DOCHEAD":
        raise AuditError(f"{reference}: invalid DOCHEAD")
    base_dochead = baseline[0].body or {}
    actual_dochead = actual[0].body or {}
    unsupported = changed_fields(base_dochead, actual_dochead) - ALLOWED_DOCHEAD_FIELDS
    if unsupported:
        raise AuditError(f"{reference}: unsupported DOCHEAD changes {sorted(unsupported)}")
    baseline_rows = rows_by_key(baseline, reference + ":baseline")
    actual_rows = rows_by_key(actual, reference + ":actual")
    candidate_rows = rows_by_key(candidate, reference + ":candidate")
    if set(baseline_rows) != set(candidate_rows) or set(actual_rows) != set(candidate_rows):
        raise AuditError(f"{reference}: record identity/type set changed")
    modifications = {str(row["record_id"]): row for row in item["modifications"]}
    if len(modifications) != 3:
        raise AuditError(f"{reference}: expected three reviewed PAD changes")
    max_delta = 0.0
    for key, before in baseline_rows.items():
        after = actual_rows[key]
        expected = candidate_rows[key]
        record_type, record_id = key
        if record_id not in modifications:
            if before == after:
                continue
            if record_type == "PAD" and before.body == after.body and allowed_reticket(before, after):
                continue
            if allowed_empty_footprint_attr_normalization(before, after):
                continue
            raise AuditError(f"{reference}: protected record changed {key}")
            continue
        if record_type != "PAD" or before.body is None or after.body is None or expected.body is None:
            raise AuditError(f"{reference}:{record_id}: invalid reviewed PAD")
        if not allowed_reticket(before, after):
            raise AuditError(f"{reference}:{record_id}: PAD header normalization mismatch")
        normalized = normalize_pad_body(after.body)
        normalized_expected = normalize_pad_body(expected.body)
        if set(normalized) != set(normalized_expected):
            raise AuditError(f"{reference}:{record_id}: PAD body field set changed")
        for field in set(normalized_expected) - {"hole", "defaultPad"}:
            if normalized.get(field) != normalized_expected.get(field):
                raise AuditError(f"{reference}:{record_id}: protected PAD field changed: {field}")
        for field in ("hole", "defaultPad"):
            if not close_value(normalized.get(field), normalized_expected.get(field)):
                raise AuditError(f"{reference}:{record_id}: {field} exceeds normalization tolerance")
            old_shape = before.body.get(field) or {}
            new_shape = after.body.get(field) or {}
            for name in set(old_shape) & set(new_shape):
                if isinstance(old_shape[name], (int, float)) and isinstance(new_shape[name], (int, float)):
                    max_delta = max(max_delta, abs(float(old_shape[name]) - float(new_shape[name])))
        if after.body.get("unusedInnerLayers") != [16]:
            raise AuditError(f"{reference}:{record_id}: unusedInnerLayers is not [16]")
    pads = [row for key, row in actual_rows.items() if key[0] == "PAD"]
    pad1 = [row for row in pads if row.body.get("num") == "1"]
    pad2 = [row for row in pads if row.body.get("num") == "2"]
    nonempty = [row for row in pads if row.body.get("unusedInnerLayers")]
    if len(pads) != 5 or len(pad1) != 1 or len(pad2) != 4 or len(nonempty) != 5:
        raise AuditError(f"{reference}: final physical PAD/mask counts differ")
    if not pad1[0].body.get("unusedInnerLayers"):
        raise AuditError(f"{reference}: existing pad1 inner-layer mask disappeared")
    if any(row.body.get("unusedInnerLayers") != [16] for row in pad2):
        raise AuditError(f"{reference}: one or more pad2 posts does not hide only In2")
    return {
        "reference": reference,
        "footprint_uuid": uuid,
        "modified_pad_ids": sorted(modifications),
        "maximum_shape_normalization_mil": max_delta,
        "protected_record_count": len(baseline_rows) - len(modifications),
        "physical_pad_count": len(pads),
        "nonempty_unused_inner_layer_pad_count": len(nonempty),
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schema") != "stm32h747-sma-owned-post-inner-layer-candidates-v1":
        raise AuditError("reviewed SMA candidate manifest required")
    if manifest.get("scope", {}).get("new_pad_bodies_changed") != 48:
        raise AuditError("manifest must contain exactly 48 reviewed changes")
    baseline_docs, baseline_order = read_checkpoint(args.baseline)
    actual_docs, actual_order = read_checkpoint(args.checkpoint)
    if baseline_order != actual_order or set(baseline_docs) != set(actual_docs):
        raise AuditError("project document UUID set/order changed")
    target_uuids = {str(item["footprint_uuid"]) for item in manifest["candidates"]}
    externally_audited = set(args.allow_non_target_document or [])
    if externally_audited & target_uuids or externally_audited - set(actual_docs):
        raise AuditError("invalid externally audited document UUID")
    ui_state_normalizations = [
        audit_ui_state_normalization(uuid, baseline_docs[uuid], actual_docs[uuid])
        for uuid in sorted(externally_audited)
    ]
    changed_non_targets = [
        uuid for uuid in baseline_order
        if uuid not in target_uuids | externally_audited and baseline_docs[uuid] != actual_docs[uuid]
    ]
    if changed_non_targets:
        raise AuditError(f"non-target documents changed: {changed_non_targets[:10]}")
    results = []
    for item in manifest["candidates"]:
        uuid = str(item["footprint_uuid"])
        candidate_path = ROOT / Path(str(item["candidate"]))
        candidate_uuid, candidate_rows = read_candidate(candidate_path)
        if candidate_uuid != uuid or sha256_file(candidate_path) != item["candidate_sha256"]:
            raise AuditError(f"{item['reference']}: candidate identity/hash mismatch")
        results.append(audit_target(item, baseline_docs[uuid], actual_docs[uuid], candidate_rows))
    report = {
        "schema": "stm32h747-sma-owned-post-inner-layer-checkpoint-audit-v1",
        "status": "pass",
        "inputs": {
            "baseline": {"path": str(args.baseline), "sha256": sha256_file(args.baseline)},
            "checkpoint": {"path": str(args.checkpoint), "sha256": sha256_file(args.checkpoint)},
            "manifest": {"path": str(args.manifest), "sha256": sha256_file(args.manifest)},
        },
        "footprints": len(results),
        "modified_new_pad_bodies": sum(len(item["modified_pad_ids"]) for item in results),
        "existing_pad_bodies_changed": 0,
        "total_nonempty_unused_inner_layer_pad_records": sum(
            item["nonempty_unused_inner_layer_pad_count"] for item in results
        ),
        "only_semantic_change": "PAD.body.unusedInnerLayers [] -> [16]",
        "document_uuid_set_and_order_unchanged": True,
        "non_target_documents_exactly_unchanged": len(baseline_docs) - len(target_uuids) - len(externally_audited),
        "externally_audited_non_target_document_uuids": sorted(externally_audited),
        "validated_ui_state_normalizations": ui_state_normalizations,
        "results": results,
    }
    write_json(args.report, report)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--allow-non-target-document", action="append")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for field in ("checkpoint", "baseline", "manifest", "report"):
        value = getattr(args, field)
        if not value.is_absolute():
            setattr(args, field, (Path.cwd() / value).resolve())
    report = run(args)
    print(json.dumps({
        "status": report["status"],
        "footprints": report["footprints"],
        "modifiedNewPads": report["modified_new_pad_bodies"],
        "existingPadsChanged": report["existing_pad_bodies_changed"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
