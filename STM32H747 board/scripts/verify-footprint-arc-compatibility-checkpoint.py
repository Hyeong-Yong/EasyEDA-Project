#!/usr/bin/env python3
"""Verify a post-update EasyEDA project checkpoint without opening EasyEDA."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLAN = ROOT / "output" / "validation" / "footprint-arc-compatibility-plan.json"
DEFAULT_REPORT = (
    ROOT
    / "output"
    / "validation"
    / "footprint-arc-compatibility-checkpoint-report.json"
)
EPSILON = 0.001
PAD_GEOMETRY_KEYS = (
    "partitionId",
    "groupId",
    "netName",
    "layerId",
    "num",
    "centerX",
    "centerY",
    "padAngle",
    "hole",
    "defaultPad",
    "specialPad",
    "padOffsetX",
    "padOffsetY",
    "relativeAngle",
    "plated",
    "padType",
    "locked",
    "zIndex",
    "connectMode",
    "spokeSpace",
    "spokeWidth",
    "spokeAngle",
    "unusedInnerLayers",
    "padLen",
)
PAD_EXPANSION_KEYS = (
    "topSolderExpansion",
    "bottomSolderExpansion",
    "topPasteExpansion",
    "bottomPasteExpansion",
)


class VerificationError(RuntimeError):
    pass


@dataclass
class Record:
    head: dict[str, Any]
    body: dict[str, Any] | None


@dataclass
class Document:
    records: list[Record]

    @property
    def dochead(self) -> Record:
        return self.records[0]

    @property
    def uuid(self) -> str:
        return str((self.dochead.body or {}).get("uuid", ""))

    @property
    def doc_type(self) -> str:
        return str((self.dochead.body or {}).get("docType", ""))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_record(line: str, source: str, line_number: int) -> Record:
    text = line[:-1] if line.endswith("|") else line
    divider = text.find("||")
    if divider < 0:
        raise VerificationError(f"missing || at {source}:{line_number}")
    try:
        head = json.loads(text[:divider])
        body_text = text[divider + 2 :]
        body = json.loads(body_text) if body_text else None
    except json.JSONDecodeError as exc:
        raise VerificationError(f"invalid JSON at {source}:{line_number}: {exc}") from exc
    if not isinstance(head, dict) or (body is not None and not isinstance(body, dict)):
        raise VerificationError(f"invalid record objects at {source}:{line_number}")
    return Record(head=head, body=body)


def parse_documents(text: str, source: str) -> list[Document]:
    documents: list[Document] = []
    current: Document | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        record = parse_record(line, source, line_number)
        if record.head.get("type") == "DOCHEAD":
            current = Document(records=[record])
            documents.append(current)
        elif current is None:
            raise VerificationError(f"record before DOCHEAD at {source}:{line_number}")
        else:
            current.records.append(record)
    return documents


def read_checkpoint(path: Path) -> tuple[str, list[Document]]:
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".epru")]
        if len(members) != 1:
            raise VerificationError(f"expected one epru member, found {members}")
        member = members[0]
        text = archive.read(member).decode("utf-8-sig")
    return member, parse_documents(text, f"{path}!/{member}")


def read_single_document(path: Path) -> Document:
    documents = parse_documents(path.read_text(encoding="utf-8-sig"), str(path))
    if len(documents) != 1:
        raise VerificationError(f"expected one document in {path}")
    return documents[0]


def live_records(document: Document) -> list[Record]:
    return [record for record in document.records if record.body is not None]


def row_by_id(document: Document) -> dict[str, Record]:
    result: dict[str, Record] = {}
    for record in live_records(document):
        record_id = record.head.get("id")
        if not record_id:
            continue
        if record_id in result:
            raise VerificationError(f"{document.uuid}: duplicate live id {record_id}")
        result[str(record_id)] = record
    return result


def pad_contract(document: Document) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in live_records(document):
        if record.head.get("type") != "PAD":
            continue
        record_id = str(record.head.get("id", ""))
        if not record_id or record_id in result:
            raise VerificationError(f"{document.uuid}: invalid PAD id {record_id!r}")
        body = record.body or {}
        contract = {key: body.get(key) for key in PAD_GEOMETRY_KEYS}
        if contract["relativeAngle"] is None:
            contract["relativeAngle"] = 0
        result[record_id] = contract
    return result


def pad_expansion_contract(document: Document) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in live_records(document):
        if record.head.get("type") != "PAD":
            continue
        record_id = str(record.head.get("id", ""))
        body = record.body or {}
        result[record_id] = {key: body.get(key) for key in PAD_EXPANSION_KEYS}
    return result


def verify_pad_expansions(
    expected: dict[str, dict[str, Any]], actual: dict[str, dict[str, Any]]
) -> int:
    if set(expected) != set(actual):
        raise VerificationError("PAD expansion identity set changed")
    normalized_defaults = 0
    for pad_id in expected:
        for key in PAD_EXPANSION_KEYS:
            left = expected[pad_id][key]
            right = actual[pad_id][key]
            if values_equal(left, right):
                continue
            if left is None and right == 0:
                normalized_defaults += 1
                continue
            raise VerificationError(
                f"PAD {pad_id} {key} changed from {left!r} to {right!r}"
            )
    return normalized_defaults


def values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=EPSILON)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(values_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(values_equal(left[key], right[key]) for key in left)
    return left == right


def assert_replacement(record: Record, transform: dict[str, Any], context: str) -> None:
    expected = transform["replacement_record"]
    if record.head.get("type") != "POLY" or record.head.get("id") != transform["keep_id"]:
        raise VerificationError(f"{context}: same-ID POLY replacement missing")
    body = record.body or {}
    expected_body = expected["body"]
    for key in ("groupId", "netName", "layerId", "width", "locked", "zIndex", "polyType"):
        if not values_equal(body.get(key), expected_body.get(key)):
            raise VerificationError(f"{context}: {key} changed")
    if not values_equal(body.get("path"), expected_body.get("path")):
        raise VerificationError(f"{context}: open ARC path changed")


def verify(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.checkpoint.resolve()
    plan_path = args.plan.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("schema") != "stm32h747-footprint-arc-compatibility-plan-v2":
        raise VerificationError("v2 compatibility plan required")
    summary = plan.get("summary", {})
    if (
        summary.get("target_footprints") != 35
        or summary.get("original_top_level_arcs") != 84
        or summary.get("replacement_polys") != 84
        or summary.get("deleted_reverse_mates") != 0
    ):
        raise VerificationError("v2 plan summary contract failed")

    member, documents = read_checkpoint(checkpoint)
    footprint_documents: dict[str, Document] = {}
    for document in documents:
        if document.doc_type != "FOOTPRINT":
            continue
        if document.uuid in footprint_documents:
            raise VerificationError(f"duplicate FOOTPRINT document {document.uuid}")
        footprint_documents[document.uuid] = document

    mapping_path = ROOT / plan["sources"]["mapping"]
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapped_uuids = {
        str(item["imported_uuid"])
        for item in mapping.get("library_map", {}).get("footprint", [])
    }
    if len(mapped_uuids) != 330:
        raise VerificationError(f"expected 330 mapped footprint UUIDs, found {len(mapped_uuids)}")
    missing_mapped = sorted(mapped_uuids - set(footprint_documents))
    if missing_mapped:
        raise VerificationError(f"checkpoint lacks mapped footprints: {missing_mapped}")

    target_reports: list[dict[str, Any]] = []
    transformed_ids: set[tuple[str, str]] = set()
    total_target_arcs = 0
    total_target_polys = 0
    total_target_pads = 0
    total_expansion_defaults_normalized = 0
    for target in plan["targets"]:
        uuid = target["imported_uuid"]
        document = footprint_documents.get(uuid)
        if document is None:
            raise VerificationError(f"{target['reference']}: footprint document missing")
        raw_document = read_single_document(ROOT / target["raw_source"])
        actual_rows = live_records(document)
        actual_counts = Counter(record.head.get("type") for record in actual_rows)
        arc_count = actual_counts.get("ARC", 0)
        poly_count = actual_counts.get("POLY", 0)
        if arc_count:
            raise VerificationError(f"{target['reference']}: {arc_count} ARC records remain")
        expected_poly_count = int(target["normalized_record_counts"].get("POLY", 0))
        if poly_count != expected_poly_count:
            raise VerificationError(
                f"{target['reference']}: POLY count {poly_count} != {expected_poly_count}"
            )

        by_id = row_by_id(document)
        expected_poly_ids = sorted(item["keep_id"] for item in target["transformations"])
        actual_poly_ids = sorted(
            str(record.head.get("id"))
            for record in actual_rows
            if record.head.get("type") == "POLY"
        )
        if actual_poly_ids != expected_poly_ids:
            raise VerificationError(f"{target['reference']}: exact POLY ID set changed")
        for transform in target["transformations"]:
            transform_id = transform["keep_id"]
            if transform.get("delete_ids"):
                raise VerificationError(f"{target['reference']}:{transform_id}: v2 deletion found")
            assert_replacement(
                by_id.get(transform_id, Record({}, None)),
                transform,
                f"{target['reference']}:{transform_id}",
            )
            key = (uuid, transform_id)
            if key in transformed_ids:
                raise VerificationError(f"duplicate transformed identity {key}")
            transformed_ids.add(key)

        expected_pads = pad_contract(raw_document)
        actual_pads = pad_contract(document)
        if not values_equal(actual_pads, expected_pads):
            bad_ids = sorted(
                set(actual_pads) | set(expected_pads),
                key=str,
            )
            bad_ids = [
                pad_id
                for pad_id in bad_ids
                if pad_id not in actual_pads
                or pad_id not in expected_pads
                or not values_equal(actual_pads[pad_id], expected_pads[pad_id])
            ]
            raise VerificationError(
                f"{target['reference']}: PAD identity/geometry changed: {bad_ids}"
            )
        try:
            normalized_expansions = verify_pad_expansions(
                pad_expansion_contract(raw_document),
                pad_expansion_contract(document),
            )
        except VerificationError as exc:
            raise VerificationError(f"{target['reference']}: {exc}") from exc

        raw_author_ids = {
            str(record.head.get("id"))
            for record in live_records(raw_document)
            if record.head.get("type") in target["author_record_types"]
        }
        actual_author_ids = {
            str(record.head.get("id"))
            for record in actual_rows
            if record.head.get("type") in target["author_record_types"]
        }
        if raw_author_ids != actual_author_ids:
            raise VerificationError(f"{target['reference']}: author record ID set changed")

        total_target_arcs += arc_count
        total_target_polys += poly_count
        total_target_pads += len(actual_pads)
        total_expansion_defaults_normalized += normalized_expansions
        target_reports.append(
            {
                "reference": target["reference"],
                "uuid": uuid,
                "arcCount": arc_count,
                "polyCount": poly_count,
                "polyIds": actual_poly_ids,
                "padCount": len(actual_pads),
                "padContractUnchanged": True,
                "padExpansionDefaultsNormalizedNullToZero": normalized_expansions,
                "authorRecordIdsUnchanged": True,
            }
        )

    mapped_arc_rows = [
        (uuid, str(record.head.get("id", "")))
        for uuid in mapped_uuids
        for record in live_records(footprint_documents[uuid])
        if record.head.get("type") == "ARC"
    ]
    if mapped_arc_rows:
        raise VerificationError(f"mapped footprints still contain ARC rows: {mapped_arc_rows}")
    if len(transformed_ids) != 84 or total_target_polys != 84 or total_target_arcs != 0:
        raise VerificationError("global ARC/POLY transformation totals failed")

    return {
        "schema": "stm32h747-footprint-arc-checkpoint-verification-v2",
        "status": "PASS",
        "checkpoint": checkpoint.relative_to(ROOT).as_posix(),
        "checkpointSha256": sha256_file(checkpoint),
        "checkpointMember": member,
        "plan": plan_path.relative_to(ROOT).as_posix(),
        "planSha256": sha256_file(plan_path),
        "mappedFootprints": len(mapped_uuids),
        "targetFootprints": len(target_reports),
        "mappedArcCount": len(mapped_arc_rows),
        "targetArcCount": total_target_arcs,
        "targetPolyCount": total_target_polys,
        "exactTransformedIds": len(transformed_ids),
        "targetPadCount": total_target_pads,
        "padContractsUnchanged": True,
        "padExpansionDefaultsNormalizedNullToZero": total_expansion_defaults_normalized,
        "targets": target_reports,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify(args)
        exit_code = 0
    except Exception as exc:
        report = {
            "schema": "stm32h747-footprint-arc-checkpoint-verification-v2",
            "status": "FAIL",
            "checkpoint": str(args.checkpoint),
            "error": str(exc),
        }
        exit_code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
