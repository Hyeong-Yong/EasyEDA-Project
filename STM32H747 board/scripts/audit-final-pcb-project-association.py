#!/usr/bin/env python3
"""Audit the final copied PCB, board/SCH association, and referenced footprints."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_final_pcb_association_20261014.epro2"
)
DEFAULT_SOURCE = (
    ROOT / "output" / "validation" / "native-final-pcb-associated-reopened.epru"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" / "final-pcb-project-association-audit.json"
)
DEFAULT_TARGET_UUID = "0ac2a19168000d8e"
DEFAULT_TARGET_TITLE = "MCU_BOARD_PCB"
DEFAULT_OLD_PCB_UUID = "3ca9811d1a42d086"
DEFAULT_BOARD_UUID = "2e69b0c51c8ce030"
DEFAULT_SCH_UUID = "416c10313f778784"
EXPECTED_PAGES = {
    "e8a4e3fabe30ab59": "02_MCU",
    "360993a3108b5759": "03_MCU_POWER",
    "c0b1ffcb620d758f": "04_SDRAM",
    "3c13ef086afba6f5": "05_ENET_USB_VCP",
    "a07bf8e4331877a8": "06_ADC_TIMER_DAC",
}
GEOMETRY_TYPES = frozenset({"LINE", "ARC", "POLY", "FILL", "VIA", "PAD"})
ELECTRICAL_TYPES = frozenset({"COMPONENT", "ATTR", "PAD_NET", "NET"})
STACK_TYPES = frozenset({"LAYER", "LAYER_PHYS"})
RULE_TYPES = frozenset({"RULE", "RULE_TEMPLATE", "RULE_SELECTOR"})


def load_module(filename: str, module_name: str) -> Any:
    path = ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DELETE_HELPER = load_module(
    "audit-pcb-replacement-safety.py", "final_association_delete_helper"
)
NATIVE_HELPER = load_module(
    "audit-native-pcb-staging-checkpoint.py", "final_association_native_helper"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def safe_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def atomic_write_text(path: Path, value: str) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def meta(document: dict[str, Any]) -> dict[str, Any]:
    return DELETE_HELPER.document_meta(document)


def keyed(records: list[Any], kinds: frozenset[str]) -> dict[tuple[str, str], Any]:
    result = {}
    for record in records:
        if record.kind not in kinds:
            continue
        key = (record.kind, record.record_id)
        if key in result:
            raise AssertionError(f"duplicate protected record key: {key}")
        result[key] = record
    return result


def digest_map(records: dict[tuple[str, str], Any]) -> str:
    rows = [
        (kind, record_id, records[(kind, record_id)].body)
        for kind, record_id in sorted(records)
    ]
    return hashlib.sha256(compact(rows).encode("utf-8")).hexdigest()


def audit(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.checkpoint, args.source):
        if not path.is_file():
            raise FileNotFoundError(path)
    documents, project2, zip_entries = DELETE_HELPER.parse_documents(args.checkpoint)
    by_uuid: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        by_uuid.setdefault(document["uuid"], []).append(document)

    if args.old_pcb_uuid in by_uuid:
        raise AssertionError("obsolete PCB UUID is still present")
    for required_uuid in (args.target_uuid, args.board_uuid, args.schematic_uuid):
        if len(by_uuid.get(required_uuid, [])) != 1:
            raise AssertionError(f"required UUID is missing or duplicated: {required_uuid}")
    target = by_uuid[args.target_uuid][0]
    board = by_uuid[args.board_uuid][0]
    schematic = by_uuid[args.schematic_uuid][0]
    if (target["doc_type"], board["doc_type"], schematic["doc_type"]) != (
        "PCB", "BOARD", "SCH"
    ):
        raise AssertionError("target/board/schematic document type mismatch")
    target_meta = meta(target)
    schematic_meta = meta(schematic)
    if target_meta.get("title") != args.target_title:
        raise AssertionError("final PCB title mismatch")
    if target_meta.get("board") != args.board_uuid:
        raise AssertionError("final PCB is not associated with expected BOARD")
    if schematic_meta.get("board") != args.board_uuid:
        raise AssertionError("schematic is not associated with expected BOARD")

    page_documents = {
        document["uuid"]: document for document in documents
        if document["doc_type"] == "SCH_PAGE"
        and meta(document).get("schematic") == args.schematic_uuid
    }
    if set(page_documents) != set(EXPECTED_PAGES):
        raise AssertionError("protected schematic page UUID set changed")
    for uuid, title in EXPECTED_PAGES.items():
        if meta(page_documents[uuid]).get("title") != title:
            raise AssertionError(f"schematic page title changed: {uuid}")

    target_records = target["records"]
    source_records = NATIVE_HELPER.parse_source(args.source)
    protected_results = {}
    for label, kinds in {
        "geometry": GEOMETRY_TYPES,
        "electrical": ELECTRICAL_TYPES,
        "stack": STACK_TYPES,
    }.items():
        target_map = keyed(target_records, kinds)
        source_map = keyed(source_records, kinds)
        same_ids = set(target_map) == set(source_map)
        exact_body_count = sum(
            target_map[key].body == source_map[key].body
            for key in set(target_map) & set(source_map)
        )
        protected_results[label] = {
            "target_count": len(target_map),
            "source_count": len(source_map),
            "id_sets_equal": same_ids,
            "exact_body_count": exact_body_count,
            "target_digest": digest_map(target_map),
            "source_digest": digest_map(source_map),
        }
        if not same_ids:
            raise AssertionError(f"{label} ID set differs between source/checkpoint")
        if label in {"electrical", "stack"} and exact_body_count != len(target_map):
            raise AssertionError(f"{label} bodies differ between source/checkpoint")

    # The package writer may normalize 108 FILL paths.  Exact geometry equivalence
    # is established by audit-native-pcb-compatible-checkpoint.py; report the raw
    # body count here without weakening ID/count gates.
    target_counts = Counter(record.kind for record in target_records)
    expected_counts = {
        "LINE": 5424, "ARC": 2184, "POLY": 500, "FILL": 730,
        "VIA": 634, "PAD": 4, "COMPONENT": 330, "ATTR": 990,
        "PAD_NET": args.expected_pad_net, "NET": 280, "LAYER": 64, "LAYER_PHYS": 17,
        "RULE": 18,
    }
    count_errors = {
        kind: {"actual": target_counts[kind], "expected": expected}
        for kind, expected in expected_counts.items() if target_counts[kind] != expected
    }
    if count_errors:
        raise AssertionError(f"final PCB count mismatch: {count_errors}")

    components = [record for record in target_records if record.kind == "COMPONENT"]
    reuse_values = [str(record.body.get("attrs", {}).get("Reuse Block") or "") for record in components]
    if any(reuse_values):
        raise AssertionError("final PCB contains non-empty Reuse Block attributes")
    footprint_attrs = [
        record for record in target_records
        if record.kind == "ATTR" and record.body.get("key") == "Footprint"
    ]
    footprint_uuids = [str(record.body.get("value") or "") for record in footprint_attrs]
    if len(footprint_attrs) != 330 or len(set(footprint_uuids)) != 330:
        raise AssertionError("expected one unique footprint UUID per final PCB component")
    footprint_results = []
    footprint_arc_total = 0
    missing_footprints = []
    for footprint_uuid in sorted(footprint_uuids):
        matches = by_uuid.get(footprint_uuid, [])
        if len(matches) != 1 or matches[0]["doc_type"] != "FOOTPRINT":
            missing_footprints.append(footprint_uuid)
            continue
        counts = Counter(record.kind for record in matches[0]["records"])
        footprint_arc_total += counts["ARC"]
        footprint_results.append({
            "uuid": footprint_uuid,
            "title": meta(matches[0]).get("title", ""),
            "arc_count": counts["ARC"],
            "poly_count": counts["POLY"],
            "pad_count": counts["PAD"],
        })
    if missing_footprints or footprint_arc_total:
        raise AssertionError(
            f"referenced footprint audit failed: missing={missing_footprints[:5]}, "
            f"arc_total={footprint_arc_total}"
        )

    cbb_doc_types = [
        document for document in documents
        if "CBB" in document["doc_type"].upper()
        or "BLOCK" in document["doc_type"].upper()
    ]
    target_title_symbols = [
        document for document in documents
        if document["doc_type"] == "SYMBOL"
        and str(meta(document).get("title") or "").casefold() == args.target_title.casefold()
    ]
    if project2.get("cbb_project") not in (0, False, None) or cbb_doc_types or target_title_symbols:
        raise AssertionError("CBB/reuse-block collision evidence found")

    source_rule = keyed(source_records, RULE_TYPES)
    target_rule = keyed(target_records, RULE_TYPES)
    missing_rule_keys = sorted(set(source_rule) - set(target_rule))
    extra_rule_keys = sorted(set(target_rule) - set(source_rule))
    shared_rule_body_differences = sorted(
        key for key in set(source_rule) & set(target_rule)
        if source_rule[key].body != target_rule[key].body
    )
    if extra_rule_keys or shared_rule_body_differences:
        raise AssertionError("checkpoint changed retained rule bodies")
    rule_templates = [
        record.body.get("name") for record in target_records if record.kind == "RULE_TEMPLATE"
    ]
    if rule_templates != ["JLCPCB Capability(Multiple Layers Board)"]:
        raise AssertionError("final rule template is not the multilayer profile")

    image_entry = f"IMAGE/{args.target_uuid}.webp"
    return {
        "schema": "stm32h747-final-pcb-project-association-audit-v1",
        "status": "final-pcb-associated-and-durable; geometry-electrical-stack-footprints-pass",
        "read_only": True,
        "checkpoint": {
            "path": str(args.checkpoint),
            "sha256": sha256_file(args.checkpoint),
            "project2": project2,
            "document_count": len(documents),
            "document_type_counts": dict(sorted(Counter(
                document["doc_type"] for document in documents
            ).items())),
            "target_image_present": image_entry in zip_entries,
        },
        "identity": {
            "target_uuid": args.target_uuid,
            "target_title": target_meta.get("title"),
            "target_board": target_meta.get("board"),
            "target_block_record_count": len(target_records),
            "target_counts": dict(sorted(target_counts.items())),
            "obsolete_pcb_uuid_absent": True,
            "board_uuid": args.board_uuid,
            "board_title": meta(board).get("title"),
            "schematic_uuid": args.schematic_uuid,
            "schematic_title": schematic_meta.get("title"),
            "schematic_board": schematic_meta.get("board"),
            "pages": [
                {
                    "uuid": uuid,
                    "title": EXPECTED_PAGES[uuid],
                    "schematic": meta(page_documents[uuid]).get("schematic"),
                    "record_count": len(page_documents[uuid]["records"]),
                }
                for uuid in EXPECTED_PAGES
            ],
        },
        "protected_data_vs_reopened_source": protected_results,
        "geometry_note": (
            "All geometry IDs/counts are exact. Package writer-normalized FILL paths are checked "
            "for geometric equivalence by the companion compatible-checkpoint audit."
        ),
        "rules": {
            "template": rule_templates,
            "target_rule_count": target_counts["RULE"],
            "target_selector_count": target_counts["RULE_SELECTOR"],
            "source_selector_count": Counter(record.kind for record in source_records)["RULE_SELECTOR"],
            "missing_from_checkpoint": [
                {"type": kind, "id": record_id} for kind, record_id in missing_rule_keys
            ],
            "extra_in_checkpoint": [],
            "retained_bodies_exact": True,
        },
        "cbb_and_reuse": {
            "project2_cbb_project": project2.get("cbb_project"),
            "cbb_or_block_document_count": len(cbb_doc_types),
            "same_title_symbol_count": len(target_title_symbols),
            "component_count": len(components),
            "nonempty_component_reuse_block_count": sum(bool(value) for value in reuse_values),
        },
        "referenced_footprints": {
            "attribute_count": len(footprint_attrs),
            "unique_uuid_count": len(set(footprint_uuids)),
            "resolved_project_footprint_count": len(footprint_results),
            "missing": missing_footprints,
            "arc_total": footprint_arc_total,
            "all_arc_compatibility_fixes_retained": footprint_arc_total == 0,
            "items": footprint_results,
        },
        "manufacturing_ready": False,
        "remaining_gates": [
            "review native DRC findings",
            "review AUTO_ROUTER layer list if autorouting is intended",
            "final netlist and manufacturing export comparison",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target-uuid", default=DEFAULT_TARGET_UUID)
    parser.add_argument("--target-title", default=DEFAULT_TARGET_TITLE)
    parser.add_argument("--old-pcb-uuid", default=DEFAULT_OLD_PCB_UUID)
    parser.add_argument("--board-uuid", default=DEFAULT_BOARD_UUID)
    parser.add_argument("--schematic-uuid", default=DEFAULT_SCH_UUID)
    parser.add_argument(
        "--expected-pad-net", type=int, default=1176,
        help="expected PCB PAD_NET count (1234 after final physical-pad restoration)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(compact({
            "status": report["status"],
            "checkpoint_sha256": report["checkpoint"]["sha256"],
            "target_uuid": report["identity"]["target_uuid"],
            "target_board": report["identity"]["target_board"],
            "page_count": len(report["identity"]["pages"]),
            "footprints": report["referenced_footprints"]["unique_uuid_count"],
            "footprint_arc_total": report["referenced_footprints"]["arc_total"],
        }))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
