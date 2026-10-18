#!/usr/bin/env python3
"""Audit an EasyEDA checkpoint after reviewed unused-inner-layer PAD updates.

This is a static checkpoint reader.  It does not open or control EasyEDA.  The
installed 3.2 compiler canonicalizes a rewritten FOOTPRINT by adding an empty
NET and an invisible empty Footprint ATTR, refreshing DOCHEAD metadata,
reticketing changed PAD rows, and rounding PAD dimensions to four decimal mil.
Those known normalizations are accepted explicitly; electrical and geometric
PAD semantics, all non-target records, and every non-target document remain
strictly protected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_drl_slot_fix_20261014.epro2"
)
DEFAULT_MANIFEST = (
    ROOT / "output" / "native-libraries" /
    "unused-inner-layer-pad-candidates" / "manifest.json"
)
DEFAULT_REPORT = (
    ROOT / "output" / "validation" /
    "native-unused-inner-layer-pad-checkpoint-audit.json"
)
PROJECT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
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
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        source = line[:-1] if line.endswith("|") else line
        if "||" not in source:
            raise AuditError(f"{label}:{line_number}: missing ||")
        head_text, body_text = source.split("||", 1)
        try:
            head = json.loads(head_text)
            body = json.loads(body_text) if body_text else None
        except json.JSONDecodeError as exc:
            raise AuditError(f"{label}:{line_number}: invalid JSON") from exc
        record = Record(head, body)
        if head.get("type") == "DOCHEAD":
            current = str((body or {}).get("uuid") or "")
            if not current or current in documents:
                raise AuditError(f"{label}:{line_number}: duplicate/empty document UUID")
            documents[current] = []
            order.append(current)
        if current is None:
            raise AuditError(f"{label}:{line_number}: record before DOCHEAD")
        documents[current].append(record)
    return documents, order


def read_checkpoint(path: Path) -> tuple[dict[str, list[Record]], list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".epru")]
        if names != [PROJECT_MEMBER]:
            raise AuditError(f"{path}: expected only {PROJECT_MEMBER}, got {names}")
        text = archive.read(PROJECT_MEMBER).decode("utf-8-sig")
    return parse_records(text, str(path))


def read_candidate(path: Path) -> tuple[str, list[Record]]:
    documents, order = parse_records(path.read_text(encoding="utf-8-sig"), str(path))
    if len(order) != 1:
        raise AuditError(f"{path}: expected one document")
    return order[0], documents[order[0]]


def rows_by_key(rows: list[Record], label: str) -> dict[tuple[str, str], Record]:
    result: dict[tuple[str, str], Record] = {}
    for record in rows:
        if record.head.get("type") == "DOCHEAD":
            continue
        if not record.key[1]:
            raise AuditError(f"{label}: non-DOCHEAD record has empty ID")
        if record.key in result:
            raise AuditError(f"{label}: duplicate record key {record.key}")
        result[record.key] = record
    return result


def exact_records(left: list[Record], right: list[Record]) -> bool:
    return left == right


def close_value(left: Any, right: Any, tolerance: float = DIMENSION_TOLERANCE_MIL) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(close_value(a, b, tolerance) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(close_value(left[key], right[key], tolerance) for key in left)
    return left == right


def normalize_pad_body(body: dict[str, Any]) -> dict[str, Any]:
    value = dict(body)
    if value.get("attrsMap") == {}:
        value.pop("attrsMap")
    if value.get("propagationDelay") is None:
        value["propagationDelay"] = 0
    return value


def allowed_added_rows(rows: list[Record]) -> bool:
    if len(rows) != 2:
        return False
    by_type = {str(record.head.get("type")): record for record in rows}
    if set(by_type) != {"NET", "ATTR"}:
        return False
    net = by_type["NET"]
    attr = by_type["ATTR"]
    expected_net_body = {
        "netType": None,
        "specialColor": None,
        "retLine": True,
        "differentialName": None,
        "isPositiveNet": False,
        "equalLengthGroupName": None,
    }
    expected_attr_body = {
        "groupID": 0,
        "parentId": "",
        "layerId": 3,
        "x": None,
        "y": None,
        "key": "Footprint",
        "value": "",
        "keyVisible": False,
        "valueVisible": False,
        "fontFamily": "default",
        "fontSize": 50,
        "strokeWidth": 8,
        "bold": 0,
        "italic": 0,
        "origin": "LEFT_BOTTOM",
        "angle": 0,
        "reverse": False,
        "expansion": 0,
        "mirror": False,
        "locked": False,
        "zIndex": -1,
        "specialColor": None,
    }
    return (
        set(net.head) == {"type", "ticket", "id"}
        and set(attr.head) == {"type", "ticket", "id"}
        and isinstance(net.head.get("ticket"), int)
        and isinstance(attr.head.get("ticket"), int)
        and net.head.get("id") == '["NET",""]'
        and net.body == expected_net_body
        and len(str(attr.head.get("id") or "")) == 17
        and str(attr.head.get("id")).startswith("e")
        and all(character in "0123456789abcdef" for character in str(attr.head.get("id"))[1:])
        and attr.body == expected_attr_body
    )


def audit_target(
    reference: str,
    uuid: str,
    baseline: list[Record],
    actual: list[Record],
    candidate: list[Record],
    modifications: list[dict[str, Any]],
) -> dict[str, Any]:
    if baseline[0].head.get("type") != "DOCHEAD" or actual[0].head.get("type") != "DOCHEAD":
        raise AuditError(f"{reference}: invalid DOCHEAD")
    base_head = baseline[0].body or {}
    actual_head = actual[0].body or {}
    allowed_dochead = {"updateTime", "version", "user"}
    if {
        key for key in set(base_head) | set(actual_head)
        if base_head.get(key) != actual_head.get(key)
    } - allowed_dochead:
        raise AuditError(f"{reference}: unexpected DOCHEAD change")

    base_rows = rows_by_key(baseline, reference + ":baseline")
    actual_rows = rows_by_key(actual, reference + ":actual")
    candidate_rows = rows_by_key(candidate, reference + ":candidate")
    if set(base_rows) != set(candidate_rows):
        raise AuditError(f"{reference}: candidate identity set differs from baseline")
    if set(base_rows) - set(actual_rows):
        raise AuditError(f"{reference}: existing records are missing after update")
    added_keys = set(actual_rows) - set(base_rows)
    added = [actual_rows[key] for key in sorted(added_keys)]
    if not allowed_added_rows(added):
        raise AuditError(f"{reference}: unexpected compiler-added records {sorted(added_keys)}")

    modified_ids = {str(item["record_id"]): item for item in modifications}
    if len(modified_ids) != 2:
        raise AuditError(f"{reference}: expected two reviewed PAD changes")
    max_dimension_delta = 0.0
    for key, before in base_rows.items():
        after = actual_rows[key]
        expected = candidate_rows[key]
        record_type, record_id = key
        if record_id not in modified_ids:
            if before != after:
                raise AuditError(f"{reference}: protected record changed: {key}")
            continue
        if record_type != "PAD":
            raise AuditError(f"{reference}: reviewed target is not PAD: {key}")
        if expected.body is None or after.body is None or before.body is None:
            raise AuditError(f"{reference}:{record_id}: missing PAD body")
        if set(after.head) != set(before.head) | {"firstTicket"}:
            raise AuditError(f"{reference}:{record_id}: PAD header field set changed")
        for field in set(before.head) - {"ticket"}:
            if after.head.get(field) != before.head.get(field):
                raise AuditError(f"{reference}:{record_id}: PAD header {field} changed")
        if after.head.get("firstTicket") != before.head.get("ticket"):
            raise AuditError(f"{reference}:{record_id}: compiler firstTicket is not original ticket")
        normalized_after = normalize_pad_body(after.body)
        if set(expected.body) != set(normalized_after):
            raise AuditError(f"{reference}:{record_id}: PAD body field set changed")
        for field in set(expected.body) - {"hole", "defaultPad"}:
            if expected.body.get(field) != normalized_after.get(field):
                raise AuditError(f"{reference}:{record_id}: protected PAD field changed: {field}")
        for field in ("hole", "defaultPad"):
            if not close_value(expected.body.get(field), normalized_after.get(field)):
                raise AuditError(f"{reference}:{record_id}: PAD {field} exceeds normalization tolerance")
        for shape_key in ("hole", "defaultPad"):
            old_shape = before.body.get(shape_key) or {}
            new_shape = after.body.get(shape_key) or {}
            for field in set(old_shape) & set(new_shape):
                left, right = old_shape[field], new_shape[field]
                if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                    max_dimension_delta = max(max_dimension_delta, abs(float(left) - float(right)))
        if after.body.get("unusedInnerLayers") != modified_ids[record_id]["after_unused_inner_layers"]:
            raise AuditError(f"{reference}:{record_id}: unusedInnerLayers mismatch")
    return {
        "reference": reference,
        "footprint_uuid": uuid,
        "modified_pad_ids": sorted(modified_ids),
        "compiler_added_record_keys": [list(key) for key in sorted(added_keys)],
        "maximum_pad_dimension_normalization_mil": max_dimension_delta,
        "maximum_pad_dimension_normalization_mm": max_dimension_delta * 0.0254,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=path.name + ".tmp-", dir=path.parent)
    temporary = Path(temp_name)
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
    if manifest.get("schema") != "stm32h747-unused-inner-layer-pad-plan-v1":
        raise AuditError("reviewed v1 manifest required")
    candidates = {item["reference"]: item for item in manifest["candidate_scope"]["candidates"]}
    references = args.references or list(manifest["candidate_scope"]["target_references"])
    if len(references) != len(set(references)) or set(references) - set(candidates):
        raise AuditError("references must be unique reviewed J2-J17 targets")
    baseline_docs, baseline_order = read_checkpoint(args.baseline)
    actual_docs, actual_order = read_checkpoint(args.checkpoint)
    if baseline_order != actual_order or set(baseline_docs) != set(actual_docs):
        raise AuditError("project document UUID set/order changed")
    target_uuids = {str(candidates[reference]["footprint_uuid"]) for reference in references}
    externally_audited = set(args.allow_non_target_document or [])
    if externally_audited & target_uuids or externally_audited - set(baseline_docs):
        raise AuditError("externally audited UUIDs must be existing non-target documents")
    changed_non_targets = [
        uuid for uuid in baseline_order
        if uuid not in target_uuids | externally_audited
        and not exact_records(baseline_docs[uuid], actual_docs[uuid])
    ]
    if changed_non_targets:
        raise AuditError(f"non-target documents changed: {changed_non_targets[:10]}")
    results = []
    for reference in references:
        item = candidates[reference]
        uuid = str(item["footprint_uuid"])
        candidate_path = ROOT / Path(str(item["candidate_path"]))
        candidate_uuid, candidate_rows = read_candidate(candidate_path)
        if candidate_uuid != uuid or sha256_file(candidate_path) != item["candidate_sha256"]:
            raise AuditError(f"{reference}: candidate identity/hash mismatch")
        results.append(audit_target(
            reference,
            uuid,
            baseline_docs[uuid],
            actual_docs[uuid],
            candidate_rows,
            item["modifications"],
        ))
    report = {
        "schema": "stm32h747-unused-inner-layer-pad-checkpoint-audit-v1",
        "status": "pass",
        "inputs": {
            "baseline": {"path": str(args.baseline), "sha256": sha256_file(args.baseline)},
            "checkpoint": {"path": str(args.checkpoint), "sha256": sha256_file(args.checkpoint)},
            "manifest": {"path": str(args.manifest), "sha256": sha256_file(args.manifest)},
        },
        "project_document_count": len(baseline_docs),
        "document_uuid_set_and_order_unchanged": True,
        "non_target_documents_exactly_unchanged": (
            len(baseline_docs) - len(target_uuids) - len(externally_audited)
        ),
        "externally_audited_non_target_document_uuids": sorted(externally_audited),
        "reviewed_references": references,
        "results": results,
        "normalization_policy": {
            "allowed_dochead_fields": ["updateTime", "version", "user"],
            "allowed_added_rows": ["empty NET", "invisible empty Footprint ATTR"],
            "pad_dimension_tolerance_mil": DIMENSION_TOLERANCE_MIL,
            "pad_dimension_tolerance_mm": DIMENSION_TOLERANCE_MIL * 0.0254,
        },
    }
    write_json(args.report, report)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--references", nargs="+")
    parser.add_argument(
        "--allow-non-target-document",
        action="append",
        help="UUID changed by a separately audited concurrent repair",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for key in ("checkpoint", "baseline", "manifest", "report"):
        value = getattr(args, key)
        if not value.is_absolute():
            setattr(args, key, (Path.cwd() / value).resolve())
    report = run(args)
    print(json.dumps({
        "status": report["status"],
        "references": report["reviewed_references"],
        "project_documents": report["project_document_count"],
        "non_target_documents_unchanged": report["non_target_documents_exactly_unchanged"],
        "max_normalization_mm": max(
            item["maximum_pad_dimension_normalization_mm"] for item in report["results"]
        ),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
