#!/usr/bin/env python3
"""Audit routed-PCB geometry and stack persistence in an EasyEDA checkpoint.

This utility is read-only with respect to all inputs.  It streams the project
archive, isolates the PCB DOCHEAD block by UUID, and compares that persisted
block with the canonical routed source and the native getter readback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_routed_staging_inspection_20261014.epro2"
)
DEFAULT_CANONICAL = ROOT / "output" / "native-pcb" / "native-pcb-routed.epru"
DEFAULT_READBACK = ROOT / "output" / "validation" / "native-routed-staging-reopened.epru"
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" /
    "native-pcb-routed-staging-checkpoint-audit.json"
)
TARGET_UUID = "6da689cbfc28e476"
PROJECT_SOURCE_ENTRY = "STM32H747_MCU_BOARD_v19.epru"
GEOMETRY_TYPES = frozenset({"LINE", "ARC", "FILL", "VIA", "PAD"})
ELECTRICAL_TYPES = frozenset({"COMPONENT", "ATTR", "PAD_NET", "NET"})


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    if not relative.parts:
        raise ValueError("output cannot be the output root")
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass(frozen=True)
class Record:
    header: dict[str, Any]
    body: dict[str, Any]
    raw: bytes

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")


def parse_record_bytes(raw: bytes, label: str) -> Record:
    line = raw.rstrip(b"\r\n")
    if not line:
        raise ValueError(f"{label}: empty record")
    normalized = line if line.endswith(b"|") else line + b"|"
    try:
        header_raw, body_raw = normalized[:-1].split(b"||", 1)
        header = json.loads(header_raw.decode("utf-8-sig"))
        body = {} if body_raw == b"" else json.loads(body_raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label}: invalid native record") from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError(f"{label}: header/body are not JSON objects")
    return Record(header, body, raw)


def parse_source(path: Path) -> list[Record]:
    return [
        parse_record_bytes(line, f"{path}:{index}")
        for index, line in enumerate(path.read_bytes().splitlines(keepends=True), 1)
        if line.strip()
    ]


def isolate_checkpoint_block(
    checkpoint: Path, target_uuid: str
) -> tuple[list[Record], bytes, dict[str, Any]]:
    with zipfile.ZipFile(checkpoint) as archive:
        names = archive.namelist()
        if PROJECT_SOURCE_ENTRY not in names or "project2.json" not in names:
            raise ValueError("checkpoint lacks project source or project2.json")
        project_bytes = archive.read("project2.json")
        project_json = json.loads(project_bytes.decode("utf-8-sig"))
        inner_digest = hashlib.sha256()
        inner_size = 0
        matches = 0
        capturing = False
        block_parts: list[bytes] = []
        block_records: list[Record] = []
        current_doc_uuid = ""
        package_layer_phys_by_doc: dict[str, list[int]] = {}
        with archive.open(PROJECT_SOURCE_ENTRY) as stream:
            for line_number, raw in enumerate(stream, 1):
                inner_digest.update(raw)
                inner_size += len(raw)
                if not raw.strip():
                    if capturing:
                        block_parts.append(raw)
                    continue
                record = parse_record_bytes(raw, f"{PROJECT_SOURCE_ENTRY}:{line_number}")
                if record.kind == "DOCHEAD":
                    uuid = str(record.body.get("uuid") or "")
                    current_doc_uuid = uuid
                    if capturing and uuid != target_uuid:
                        capturing = False
                    if uuid == target_uuid:
                        matches += 1
                        if matches > 1:
                            raise ValueError(f"duplicate target DOCHEAD UUID: {target_uuid}")
                        capturing = True
                if record.kind == "LAYER_PHYS":
                    physical_id = layer_id(record)
                    if physical_id is None:
                        raise ValueError(
                            f"{PROJECT_SOURCE_ENTRY}:{line_number}: LAYER_PHYS has no layer ID"
                        )
                    package_layer_phys_by_doc.setdefault(current_doc_uuid, []).append(physical_id)
                if capturing:
                    block_parts.append(raw)
                    block_records.append(record)
        if matches != 1:
            raise ValueError(f"target DOCHEAD occurrence count is {matches}, expected 1")
        block_bytes = b"".join(block_parts)
        return block_records, block_bytes, {
            "zip_entries": names,
            "project2": project_json,
            "project2_sha256": sha256_bytes(project_bytes),
            "inner_source_bytes": inner_size,
            "inner_source_sha256": inner_digest.hexdigest(),
            "target_dochead_occurrences": matches,
            "package_layer_phys_by_doc": package_layer_phys_by_doc,
        }


def id_map(records: Iterable[Record], label: str) -> dict[str, Record]:
    result: dict[str, Record] = {}
    for record in records:
        if not record.record_id:
            continue
        if record.record_id in result:
            raise ValueError(f"{label}: duplicate ID {record.record_id}")
        result[record.record_id] = record
    return result


def by_type(records: Iterable[Record], kind: str) -> list[Record]:
    return [record for record in records if record.kind == kind]


def layer_id(record: Record) -> int | None:
    value = record.body.get("layerId")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if record.record_id.startswith("["):
        parsed = json.loads(record.record_id)
        if isinstance(parsed, list) and len(parsed) >= 2 and parsed[0] in {"LAYER", "LAYER_PHYS"}:
            return int(parsed[1])
    return None


def id_set_sha256(ids: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(sorted(ids)) + "\n").encode("utf-8"))


def typed_body_digest(records: Iterable[Record], kinds: set[str] | frozenset[str]) -> str:
    rows = sorted(
        (record.kind, record.record_id, record.body)
        for record in records if record.kind in kinds
    )
    return sha256_bytes(("\n".join(compact(row) for row in rows) + "\n").encode("utf-8"))


def record_body_differences(
    left: Iterable[Record], right: Iterable[Record], kinds: set[str] | frozenset[str]
) -> list[str]:
    left_map = {
        (record.kind, record.record_id): record.body
        for record in left if record.kind in kinds
    }
    right_map = {
        (record.kind, record.record_id): record.body
        for record in right if record.kind in kinds
    }
    return sorted(
        f"{kind}:{record_id}"
        for kind, record_id in set(left_map) & set(right_map)
        if left_map[(kind, record_id)] != right_map[(kind, record_id)]
    )


def normalize_simple_fill_duplicates(body: dict[str, Any]) -> dict[str, Any]:
    """Remove consecutive duplicate points from the simple Gerber L encoding."""
    result = json.loads(compact(body))
    paths = result.get("path")
    if not (
        isinstance(paths, list) and len(paths) == 1 and isinstance(paths[0], list)
        and len(paths[0]) >= 5 and paths[0][2] == "L"
        and all(isinstance(value, (int, float)) for value in paths[0][3:])
        and len(paths[0][3:]) % 2 == 0
    ):
        return result
    source = paths[0]
    points = [(source[0], source[1])]
    for index in range(3, len(source), 2):
        point = (source[index], source[index + 1])
        if point != points[-1]:
            points.append(point)
    normalized: list[Any] = [points[0][0], points[0][1], "L"]
    for point in points[1:]:
        normalized.extend(point)
    result["path"] = [normalized]
    return result


def normalized_geometry_digest(records: Iterable[Record]) -> str:
    rows = sorted(
        (
            record.kind,
            record.record_id,
            normalize_simple_fill_duplicates(record.body)
            if record.kind == "FILL" else record.body,
        )
        for record in records if record.kind in GEOMETRY_TYPES
    )
    return sha256_bytes(("\n".join(compact(row) for row in rows) + "\n").encode("utf-8"))


def scan_stack_keys(value: Any, prefix: str = "$") -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            if any(token in key.casefold() for token in ("layer", "stack", "copper", "physical")):
                matches.append({"path": path, "value": child})
            matches.extend(scan_stack_keys(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(scan_stack_keys(child, f"{prefix}[{index}]"))
    return matches


def audit(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.checkpoint, args.canonical, args.readback):
        if not path.is_file():
            raise FileNotFoundError(path)
    checkpoint_records, block_bytes, archive = isolate_checkpoint_block(
        args.checkpoint, args.target_uuid
    )
    canonical_records = parse_source(args.canonical)
    readback_records = parse_source(args.readback)
    checkpoint_counts = Counter(record.kind for record in checkpoint_records)
    canonical_counts = Counter(record.kind for record in canonical_records)
    readback_counts = Counter(record.kind for record in readback_records)

    checkpoint_by_id = id_map(checkpoint_records, "checkpoint")
    canonical_by_id = id_map(canonical_records, "canonical")
    readback_by_id = id_map(readback_records, "readback")

    missing: dict[str, Any] = {}
    for kind, expected_count in (("LINE", 603), ("FILL", 226)):
        canonical_type = by_type(canonical_records, kind)
        checkpoint_ids = {record.record_id for record in by_type(checkpoint_records, kind)}
        missing_records = [record for record in canonical_type if record.record_id not in checkpoint_ids]
        if len(missing_records) != expected_count:
            raise AssertionError(f"checkpoint missing {len(missing_records)} {kind}, expected {expected_count}")
        readback_ids = {record.record_id for record in by_type(readback_records, kind)}
        readback_missing = {
            record.record_id for record in canonical_type if record.record_id not in readback_ids
        }
        missing_ids = {record.record_id for record in missing_records}
        if missing_ids != readback_missing:
            raise AssertionError(f"checkpoint/readback missing {kind} ID sets differ")
        missing[kind] = {
            "count": len(missing_records),
            "id_set_sha256": id_set_sha256(missing_ids),
            "by_layer": dict(sorted(Counter(layer_id(record) for record in missing_records).items())),
            "ids": sorted(missing_ids),
            "exactly_equal_to_readback_missing_set": True,
        }

    complete_id_types = ["ARC", "VIA", "PAD", "COMPONENT", "ATTR", "PAD_NET", "NET"]
    complete: dict[str, Any] = {}
    for kind in complete_id_types:
        source_ids = {
            record.record_id for record in
            (canonical_records if kind in {"ARC", "VIA", "PAD", "COMPONENT", "ATTR", "PAD_NET", "NET"} else readback_records)
            if record.kind == kind
        }
        # ATTR/COMPONENT/PAD_NET/NET are equivalent between canonical and readback.
        checkpoint_ids = {record.record_id for record in checkpoint_records if record.kind == kind}
        if source_ids != checkpoint_ids:
            raise AssertionError(f"checkpoint {kind} ID set differs")
        complete[kind] = {"count": len(checkpoint_ids), "id_set_complete": True}

    geometry_diff = record_body_differences(checkpoint_records, readback_records, GEOMETRY_TYPES)
    electrical_diff = record_body_differences(checkpoint_records, readback_records, ELECTRICAL_TYPES)
    permitted_geometry_normalizations: list[dict[str, Any]] = []
    if geometry_diff == ["FILL:df8b96ef8c197120"]:
        checkpoint_fill = checkpoint_by_id["df8b96ef8c197120"]
        readback_fill = readback_by_id["df8b96ef8c197120"]
        if normalize_simple_fill_duplicates(checkpoint_fill.body) != normalize_simple_fill_duplicates(
            readback_fill.body
        ):
            raise AssertionError("df8b checkpoint/readback bodies differ beyond a duplicate point")
        checkpoint_path = checkpoint_fill.body["path"][0]
        readback_path = readback_fill.body["path"][0]
        permitted_geometry_normalizations.append({
            "id": "df8b96ef8c197120",
            "type": "FILL",
            "difference": "checkpoint writer inserted one consecutive duplicate L-path point",
            "checkpoint_path_token_count": len(checkpoint_path),
            "readback_path_token_count": len(readback_path),
            "geometry_after_consecutive_duplicate_normalization_equal": True,
        })
        geometry_diff = []
    if geometry_diff or electrical_diff:
        raise AssertionError(
            f"checkpoint/readback body differences: geometry={geometry_diff[:8]}, electrical={electrical_diff[:8]}"
        )
    checkpoint_normalized_geometry_digest = normalized_geometry_digest(checkpoint_records)
    readback_normalized_geometry_digest = normalized_geometry_digest(readback_records)
    if checkpoint_normalized_geometry_digest != readback_normalized_geometry_digest:
        raise AssertionError("checkpoint/readback normalized geometry digests differ")

    checkpoint_layers = {layer_id(record): record for record in by_type(checkpoint_records, "LAYER")}
    readback_layers = {layer_id(record): record for record in by_type(readback_records, "LAYER")}
    checkpoint_phys = {layer_id(record): record for record in by_type(checkpoint_records, "LAYER_PHYS")}
    readback_phys = {layer_id(record): record for record in by_type(readback_records, "LAYER_PHYS")}
    missing_layers = sorted(set(readback_layers) - set(checkpoint_layers))
    missing_phys = sorted(set(readback_phys) - set(checkpoint_phys))
    common_layer_body_changes = sorted(
        layer for layer in set(checkpoint_layers) & set(readback_layers)
        if checkpoint_layers[layer].body != readback_layers[layer].body
    )
    common_phys_body_changes = sorted(
        layer for layer in set(checkpoint_phys) & set(readback_phys)
        if checkpoint_phys[layer].body != readback_phys[layer].body
    )
    logical_copper_ids = [1, 15, 16, 17, 18, 2]
    checkpoint_logical_copper_use = {
        layer: bool(checkpoint_layers[layer].body.get("use"))
        for layer in logical_copper_ids if layer in checkpoint_layers
    }
    package_phys_id_counts = Counter(
        physical_id
        for ids in archive["package_layer_phys_by_doc"].values()
        for physical_id in ids
    )
    routed_copper_by_layer_and_type: dict[int, Counter[str]] = {}
    for record in checkpoint_records:
        if record.kind not in {"LINE", "ARC", "FILL", "VIA"}:
            continue
        primitive_layer = layer_id(record)
        if primitive_layer not in {1, 2, 15, 16, 17, 18}:
            continue
        routed_copper_by_layer_and_type.setdefault(primitive_layer, Counter())[record.kind] += 1
    rule_templates = [record.body for record in checkpoint_records if record.kind == "RULE_TEMPLATE"]
    auto_router_rules = [
        record.body for record in checkpoint_records
        if record.kind == "RULE" and record.record_id == '["RULE","AUTO_ROUTER","Common"]'
    ]

    metas = [record.body for record in checkpoint_records if record.kind == "META"]
    canvases = [record.body for record in checkpoint_records if record.kind == "CANVAS"]
    stack_key_hits = (
        scan_stack_keys(archive["project2"], "$.project2")
        + scan_stack_keys(metas, "$.target.META")
        + scan_stack_keys(canvases, "$.target.CANVAS")
    )
    non_image_entries = [
        name for name in archive["zip_entries"]
        if not name.endswith("/") and not name.startswith("IMAGE/")
    ]
    if non_image_entries != ["project2.json", PROJECT_SOURCE_ENTRY]:
        raise AssertionError(f"unexpected non-image checkpoint entries: {non_image_entries}")

    target_head = checkpoint_records[0]
    return {
        "schema": "stm32h747-routed-staging-checkpoint-audit-v1",
        "status": "checkpoint-is-not-a-durable-six-layer-manufacturing-source",
        "manufacturing_ready": False,
        "read_only": True,
        "checkpoint": {
            "path": str(args.checkpoint),
            "sha256": sha256_file(args.checkpoint),
            "zip_entries": archive["zip_entries"],
            "non_image_entries": non_image_entries,
            "project2": archive["project2"],
            "project2_sha256": archive["project2_sha256"],
            "inner_source_entry": PROJECT_SOURCE_ENTRY,
            "inner_source_bytes": archive["inner_source_bytes"],
            "inner_source_sha256": archive["inner_source_sha256"],
        },
        "target_pcb": {
            "uuid": args.target_uuid,
            "dochead_occurrences": archive["target_dochead_occurrences"],
            "dochead": target_head.body,
            "meta": metas,
            "canvas": canvases,
            "record_count": len(checkpoint_records),
            "block_bytes_including_final_lf": len(block_bytes),
            "block_sha256": sha256_bytes(block_bytes),
            "counts": dict(sorted(checkpoint_counts.items())),
        },
        "geometry": {
            "canonical_counts": dict(sorted(canonical_counts.items())),
            "checkpoint_counts": dict(sorted(checkpoint_counts.items())),
            "readback_counts": dict(sorted(readback_counts.items())),
            "missing": missing,
            "complete_id_types": complete,
            "checkpoint_readback_shared_geometry_raw_body_differences": len(
                permitted_geometry_normalizations
            ),
            "permitted_zero_length_writer_normalizations": permitted_geometry_normalizations,
            "checkpoint_readback_shared_geometry_differences_after_normalization": 0,
            "checkpoint_readback_shared_electrical_body_differences": 0,
            "checkpoint_readback_geometry_digest": typed_body_digest(
                checkpoint_records, GEOMETRY_TYPES
            ),
            "readback_geometry_digest": typed_body_digest(readback_records, GEOMETRY_TYPES),
            "checkpoint_normalized_geometry_digest": checkpoint_normalized_geometry_digest,
            "readback_normalized_geometry_digest": readback_normalized_geometry_digest,
            "checkpoint_electrical_digest": typed_body_digest(
                checkpoint_records, ELECTRICAL_TYPES
            ),
            "readback_electrical_digest": typed_body_digest(
                readback_records, ELECTRICAL_TYPES
            ),
        },
        "stack_and_rules_persistence": {
            "checkpoint_layer_ids": sorted(checkpoint_layers),
            "readback_layer_ids": sorted(readback_layers),
            "missing_layer_ids_from_checkpoint": missing_layers,
            "checkpoint_logical_copper_use": checkpoint_logical_copper_use,
            "checkpoint_logical_six_copper_layers_enabled": all(
                checkpoint_logical_copper_use.get(layer) is True
                for layer in logical_copper_ids
            ),
            "checkpoint_layer_phys_ids": sorted(checkpoint_phys),
            "readback_layer_phys_ids": sorted(readback_phys),
            "missing_layer_phys_ids_from_checkpoint": missing_phys,
            "common_layer_ids_with_body_changes": common_layer_body_changes,
            "common_layer_phys_ids_with_body_changes": common_phys_body_changes,
            "checkpoint_rule_selector_count": checkpoint_counts["RULE_SELECTOR"],
            "readback_rule_selector_count": readback_counts["RULE_SELECTOR"],
            "checkpoint_rule_templates": rule_templates,
            "checkpoint_auto_router_common": auto_router_rules,
            "checkpoint_routed_copper_by_layer_and_type": {
                str(layer): dict(sorted(counts.items()))
                for layer, counts in sorted(routed_copper_by_layer_and_type.items())
            },
            "stack_related_fields_outside_layer_records": stack_key_hits,
            "package_layer_phys_ids_by_doc_uuid": archive["package_layer_phys_by_doc"],
            "package_layer_phys_total": sum(package_phys_id_counts.values()),
            "package_layer_phys_id_counts": dict(sorted(package_phys_id_counts.items())),
            "package_contains_any_inner_copper_or_extra_substrate_phys": any(
                layer in package_phys_id_counts for layer in (15, 16, 17, 18, 362, 363, 364, 365)
            ),
            "portable_six_layer_stack_encoded_elsewhere_in_checkpoint": False,
            "finding": (
                "The archive retains logical copper LAYER 1/15/16/17/18/2 as enabled, but has "
                "only the default nine-record physical sequence. It contains only project2.json, "
                "the concatenated native project source, and preview images; project2/META/CANVAS "
                "contain no stack field. The target omits substrate LAYER 362-365 and LAYER_PHYS "
                "15-18/362-365, so this portable checkpoint does not encode the getter's actual "
                "six-layer physical stack. The retained rule template is explicitly the JLCPCB "
                "two-layer template and its autorouter rule lists only layers 1/2/12, while "
                "routed copper primitives already exist on layers 15-18."
            ),
        },
        "required_next_gates": [
            "apply repaired geometry only to an active native six-layer PCB",
            "save and reopen; verify native getter primitive and component counts",
            "export a new full checkpoint and repeat this block-level stack audit",
            "verify native netlist and run native DRC",
            "compare manufacturing export geometry with source Gerber",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--readback", type=Path, default=DEFAULT_READBACK)
    parser.add_argument("--target-uuid", default=TARGET_UUID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(compact({
            "status": report["status"],
            "target_uuid": report["target_pcb"]["uuid"],
            "missing_line": report["geometry"]["missing"]["LINE"]["count"],
            "missing_fill": report["geometry"]["missing"]["FILL"]["count"],
            "checkpoint_layer_phys": len(
                report["stack_and_rules_persistence"]["checkpoint_layer_phys_ids"]
            ),
            "readback_layer_phys": len(
                report["stack_and_rules_persistence"]["readback_layer_phys_ids"]
            ),
            "manufacturing_ready": False,
        }))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, AssertionError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
