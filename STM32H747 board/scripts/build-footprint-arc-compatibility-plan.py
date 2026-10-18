#!/usr/bin/env python3
"""Build an offline, UUID-keyed footprint ARC compatibility repair plan.

The project checkpoint contains the complete project-local FOOTPRINT sources,
whereas EasyEDA 3.2's footprint-editor getter can omit authored drawing
primitives.  This tool extracts the complete sources without opening EasyEDA,
then describes the only permitted change: every -180 degree ARC record becomes
one open NORMAL POLY ARC path with the same record ID.

The current 3.2 runtime treats NORMAL POLY as ``Line``.  Its closedness gate is
therefore not applied.  Reverse semicircle pairs remain two exact open strokes.
The one-to-one conversion is also safe for EasyEDA's project-library merge
writer, which does not delete records merely because they are absent from an
update source.

No EasyEDA API is called.  Raw source files are exact full documents extracted
from the checkpoint; normalized files are static previews used for validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = (
    ROOT
    / "output"
    / "checkpoints"
    / "STM32H747_after_capsule_compatibility_20261014.epro2"
)
DEFAULT_MAP = ROOT / "output" / "validation" / "native-component-link-rebind-plan.json"
DEFAULT_OUTPUT = ROOT / "output" / "validation" / "footprint-arc-compatibility-plan.json"
DEFAULT_SOURCE_DIR = ROOT / "output" / "validation" / "footprint-arc-compatibility"

HEX16 = re.compile(r"^[0-9a-f]{16}$")
PAIR_KEYS = (
    "partitionId",
    "groupId",
    "netName",
    "layerId",
    "angle",
    "width",
    "arcType",
    "locked",
    "specialColor",
    "number",
)
POLY_COPY_KEYS = (
    "partitionId",
    "groupId",
    "netName",
    "layerId",
    "width",
    "locked",
    "zIndex",
    "specialColor",
    "number",
)
EXPECTED_TARGET_FOOTPRINTS = 35
EXPECTED_ARCS = 84
EXPECTED_PAIRS = 41
EXPECTED_UNMATCHED = 2


class PlanError(RuntimeError):
    pass


@dataclass
class Record:
    head: dict[str, Any]
    body: dict[str, Any]
    raw_line: str


@dataclass
class Document:
    records: list[Record]
    start_line: int

    @property
    def dochead(self) -> Record:
        return self.records[0]

    @property
    def uuid(self) -> str:
        return str(self.dochead.body.get("uuid", ""))

    @property
    def doc_type(self) -> str:
        return str(self.dochead.body.get("docType", ""))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256_bytes(payload.encode("utf-8"))


def parse_record(raw_line: str, source: str, line_number: int) -> Record:
    text = raw_line[:-1] if raw_line.endswith("|") else raw_line
    try:
        head_text, body_text = text.split("||", 1)
        head = json.loads(head_text)
        body = json.loads(body_text) if body_text else {}
    except (ValueError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid native record at {source}:{line_number}: {exc}") from exc
    if not isinstance(head, dict) or not isinstance(body, dict):
        raise PlanError(f"non-object native record at {source}:{line_number}")
    return Record(head=head, body=body, raw_line=raw_line)


def parse_documents(text: str, source: str) -> list[Document]:
    documents: list[Document] = []
    current: Document | None = None
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if not raw_line:
            continue
        record = parse_record(raw_line, source, line_number)
        if record.head.get("type") == "DOCHEAD":
            current = Document(records=[record], start_line=line_number)
            documents.append(current)
        elif current is None:
            raise PlanError(f"record precedes DOCHEAD at {source}:{line_number}")
        else:
            current.records.append(record)
    return documents


def serialize_records(records: list[Record]) -> str:
    lines = []
    for record in records:
        lines.append(
            json.dumps(record.head, separators=(",", ":"), ensure_ascii=False)
            + "||"
            + json.dumps(record.body, separators=(",", ":"), ensure_ascii=False)
            + "|"
        )
    return "\n".join(lines) + "\n"


def raw_document_text(document: Document) -> str:
    return "\n".join(record.raw_line for record in document.records) + "\n"


def decimal_number(value: Decimal) -> int | float:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(format(normalized, "f"))


def midpoint(left: Any, right: Any) -> int | float:
    return decimal_number((Decimal(str(left)) + Decimal(str(right))) / Decimal(2))


def half_distance(body: dict[str, Any]) -> int | float:
    dx = Decimal(str(body["endX"])) - Decimal(str(body["startX"]))
    dy = Decimal(str(body["endY"])) - Decimal(str(body["startY"]))
    # Every verified reverse pair is axis aligned.  Refuse to round a new
    # diagonal construction instead of silently changing authored geometry.
    if dx != 0 and dy != 0:
        raise PlanError(f"paired ARC diameter is unexpectedly diagonal: {body}")
    return decimal_number((abs(dx) + abs(dy)) / Decimal(2))


def pair_signature(body: dict[str, Any]) -> tuple[str, ...]:
    return tuple(json.dumps(body.get(key), sort_keys=True) for key in PAIR_KEYS)


def reverse_endpoints(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("startX") == right.get("endX")
        and left.get("startY") == right.get("endY")
        and left.get("endX") == right.get("startX")
        and left.get("endY") == right.get("startY")
    )


def poly_body(arc_body: dict[str, Any], path: list[Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in POLY_COPY_KEYS:
        if key in arc_body:
            result[key] = arc_body[key]
    result["path"] = path
    result["polyType"] = "NORMAL"
    return result


def replacement_record(arc: Record, path: list[Any]) -> Record:
    head = dict(arc.head)
    head["type"] = "POLY"
    return Record(head=head, body=poly_body(arc.body, path), raw_line="")


def count_types(records: list[Record]) -> dict[str, int]:
    return dict(sorted(Counter(record.head.get("type") for record in records).items()))


def make_transformations(
    document: Document,
) -> tuple[list[dict[str, Any]], list[Record], int, int]:
    arcs = [(index, record) for index, record in enumerate(document.records) if record.head.get("type") == "ARC"]
    transformations: list[dict[str, Any]] = []
    replacements: dict[str, Record] = {}
    reverse_mates: dict[str, str] = {}

    for _, arc in arcs:
        arc_id = str(arc.head.get("id", ""))
        if float(arc.body.get("angle", 0)) != -180.0:
            raise PlanError(f"{document.uuid}:{arc_id} is not a -180 degree ARC")
        candidates = [
            other
            for _, other in arcs
            if other is not arc
            and pair_signature(other.body) == pair_signature(arc.body)
            and reverse_endpoints(arc.body, other.body)
        ]
        if len(candidates) > 1:
            raise PlanError(f"{document.uuid}:{arc_id} has ambiguous reverse mates")
        if candidates:
            mate = candidates[0]
            mate_id = str(mate.head.get("id", ""))
            reverse_mates[arc_id] = mate_id

        path = [
            arc.body["startX"],
            arc.body["startY"],
            "ARC",
            arc.body["angle"],
            arc.body["endX"],
            arc.body["endY"],
        ]
        replacement = replacement_record(arc, path)
        replacements[arc_id] = replacement
        transformations.append(
            {
                "kind": "arc_to_same_id_open_poly_arc",
                "keep_id": arc_id,
                "delete_ids": [],
                "reverse_pair_id": reverse_mates.get(arc_id),
                "original_records": [{"head": arc.head, "body": arc.body}],
                "replacement_record": {"head": replacement.head, "body": replacement.body},
                "geometry": {
                    "start_x": arc.body["startX"],
                    "start_y": arc.body["startY"],
                    "end_x": arc.body["endX"],
                    "end_y": arc.body["endY"],
                    "angle": arc.body["angle"],
                    "stroke_width": arc.body["width"],
                    "runtime_open_path_proof": "polyType NORMAL -> Line; Sd('Line') is false",
                },
            }
        )

    for arc_id, mate_id in reverse_mates.items():
        if reverse_mates.get(mate_id) != arc_id:
            raise PlanError(f"{document.uuid}:{arc_id} reverse-pair relation is not symmetric")
    pair_count = len(reverse_mates) // 2
    unmatched_count = len(arcs) - len(reverse_mates)

    normalized: list[Record] = []
    for record in document.records:
        record_id = str(record.head.get("id", ""))
        normalized.append(replacements.get(record_id, record))
    if any(record.head.get("type") == "ARC" for record in normalized):
        raise PlanError(f"{document.uuid}: normalized preview still has ARC records")
    if len(normalized) != len(document.records):
        raise PlanError(f"{document.uuid}: one-to-one conversion changed record count")
    return transformations, normalized, pair_count, unmatched_count


def safe_reference(title: str) -> str:
    reference = title.split("_", 1)[0]
    if not re.fullmatch(r"[A-Z]+[0-9]+", reference):
        raise PlanError(f"cannot derive physical reference from title {title!r}")
    return reference


def body_digest(records: list[Record], record_type: str) -> str:
    return canonical_digest(
        [
            {"head": record.head, "body": record.body}
            for record in records
            if record.head.get("type") == record_type
        ]
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.checkpoint.resolve()
    mapping_path = args.mapping.resolve()
    with zipfile.ZipFile(checkpoint) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".epru")]
        if len(members) != 1:
            raise PlanError(f"expected one epru member, found {members}")
        member = members[0]
        checkpoint_text = archive.read(member).decode("utf-8-sig")
    documents = parse_documents(checkpoint_text, f"{checkpoint}!/{member}")

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mapped = mapping.get("library_map", {}).get("footprint", [])
    if len(mapped) != 330:
        raise PlanError(f"expected 330 mapped footprints, found {len(mapped)}")
    title_by_uuid = {str(item["imported_uuid"]): str(item["title"]) for item in mapped}
    if len(title_by_uuid) != len(mapped) or any(not HEX16.fullmatch(key) for key in title_by_uuid):
        raise PlanError("footprint UUID map is duplicate or malformed")

    doc_by_uuid: dict[str, Document] = {}
    for document in documents:
        if document.doc_type != "FOOTPRINT" or document.uuid not in title_by_uuid:
            continue
        if document.uuid in doc_by_uuid:
            raise PlanError(f"checkpoint contains duplicate mapped FOOTPRINT {document.uuid}")
        doc_by_uuid[document.uuid] = document
    if set(doc_by_uuid) != set(title_by_uuid):
        missing = sorted(set(title_by_uuid) - set(doc_by_uuid))
        raise PlanError(f"checkpoint lacks mapped FOOTPRINT documents: {missing}")

    args.source_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = args.source_dir / "raw"
    normalized_dir = args.source_dir / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    targets: list[dict[str, Any]] = []
    paired_count = 0
    unmatched_count = 0
    original_arc_count = 0
    for uuid, document in sorted(doc_by_uuid.items(), key=lambda item: title_by_uuid[item[0]]):
        original_counts = count_types(document.records)
        if original_counts.get("ARC", 0) == 0:
            continue
        title = title_by_uuid[uuid]
        reference = safe_reference(title)
        raw_text = raw_document_text(document)
        transformations, normalized, pairs, unmatched = make_transformations(document)
        normalized_text = serialize_records(normalized)
        raw_name = f"{reference}_{uuid}.epru"
        normalized_name = f"{reference}_{uuid}.epru"
        raw_path = raw_dir / raw_name
        normalized_path = normalized_dir / normalized_name
        raw_path.write_text(raw_text, encoding="utf-8", newline="\n")
        normalized_path.write_text(normalized_text, encoding="utf-8", newline="\n")

        normalized_counts = count_types(normalized)
        paired_count += pairs
        unmatched_count += unmatched
        original_arc_count += original_counts["ARC"]
        if normalized_counts.get("POLY", 0) - original_counts.get("POLY", 0) != len(transformations):
            raise PlanError(f"{uuid}: POLY count delta does not match transformations")
        if len(transformations) != original_counts["ARC"]:
            raise PlanError(f"{uuid}: every ARC must have one same-ID replacement")
        if len(document.records) != len(normalized):
            raise PlanError(f"{uuid}: merge-safe conversion must not delete records")

        # The post-capsule checkpoint must be the source so the user's three
        # verified OVAL->RECT compatibility repairs are retained exactly.
        if reference in {"CN1", "CN3", "CN4"}:
            top_ovals = [
                record.head.get("id")
                for record in document.records
                if record.head.get("type") == "PAD"
                and record.body.get("layerId") == 1
                and record.body.get("defaultPad", {}).get("padType") == "OVAL"
            ]
            if top_ovals:
                raise PlanError(f"{reference}: checkpoint regressed to OVAL pads: {top_ovals}")

        author_types = sorted(
            {
                record.head.get("type")
                for record in [*document.records, *normalized]
                if record.head.get("type")
                not in {"DOCHEAD", "LAYER", "CANVAS", "ACTIVE_LAYER", "META", "NET"}
            }
        )
        targets.append(
            {
                "reference": reference,
                "title": title,
                "imported_uuid": uuid,
                "checkpoint_doc_version": str(document.dochead.body.get("version", "")),
                "checkpoint_doc_update_time": document.dochead.body.get("updateTime"),
                "raw_source": raw_path.resolve().relative_to(ROOT.resolve()).as_posix(),
                "raw_source_sha256": sha256_file(raw_path),
                "normalized_preview": normalized_path.resolve().relative_to(ROOT.resolve()).as_posix(),
                "normalized_preview_sha256": sha256_file(normalized_path),
                "raw_record_counts": original_counts,
                "normalized_record_counts": normalized_counts,
                "author_record_types": author_types,
                "raw_pad_digest": body_digest(document.records, "PAD"),
                "raw_non_arc_digest": canonical_digest(
                    [
                        {"head": record.head, "body": record.body}
                        for record in document.records
                        if record.head.get("type") != "ARC"
                    ]
                ),
                "transformations": transformations,
            }
        )

    observed = (len(targets), original_arc_count, paired_count, unmatched_count)
    expected = (
        EXPECTED_TARGET_FOOTPRINTS,
        EXPECTED_ARCS,
        EXPECTED_PAIRS,
        EXPECTED_UNMATCHED,
    )
    if observed != expected:
        raise PlanError(f"unexpected ARC inventory {observed}, expected {expected}")

    return {
        "schema": "stm32h747-footprint-arc-compatibility-plan-v2",
        "purpose": (
            "Replace top-level footprint ARC records with exact installed-3.2-compatible "
            "same-ID NORMAL POLY open-arc records without changing pads or other author data."
        ),
        "safety": {
            "generated_offline": True,
            "easyeda_api_executed": False,
            "only_arc_records_change": True,
            "raw_sources_are_complete_checkpoint_documents": True,
            "merge_safe_same_id_one_to_one": True,
            "records_deleted": False,
            "runtime_uses_complete_normalized_checkpoint_document": True,
        },
        "runtime_contract": {
            "installed_version": "3.2.206",
            "poly_type": "NORMAL",
            "open_arc_path": ["startX", "startY", "ARC", "angle", "endX", "endY"],
            "no_unit_conversion": True,
            "open_arc_reason": "NORMAL maps to Line and Sd('Line') is false",
            "attrs_map_not_used_by_line_arc_poly": True,
        },
        "sources": {
            "checkpoint": checkpoint.relative_to(ROOT).as_posix(),
            "checkpoint_sha256": sha256_file(checkpoint),
            "checkpoint_member": member,
            "mapping": mapping_path.relative_to(ROOT).as_posix(),
            "mapping_sha256": sha256_file(mapping_path),
        },
        "summary": {
            "mapped_footprints": len(mapped),
            "target_footprints": len(targets),
            "original_top_level_arcs": original_arc_count,
            "reverse_arc_pairs": paired_count,
            "unmatched_open_semicircles": unmatched_count,
            "replacement_polys": original_arc_count,
            "deleted_reverse_mates": 0,
            "final_top_level_arcs": 0,
            "errors": 0,
        },
        "targets": targets,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = build(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({"output": str(args.output), **plan["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
