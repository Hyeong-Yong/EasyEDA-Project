#!/usr/bin/env python3
"""Statically audit whether an obsolete PCB can be removed without its SCH/CBB.

This tool only reads an exported EasyEDA project and the locally installed
EasyEDA JavaScript bundles.  It never opens EasyEDA or calls an EasyEDA API.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_stack_ui_native_20261014.epro2"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" / "pcb-replacement-delete-safety-audit.json"
)
PROJECT_SOURCE_ENTRY = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_DELETE_PCB_UUID = "3ca9811d1a42d086"
DEFAULT_PROTECTED_SCH_UUID = "416c10313f778784"
DEFAULT_UI_JS = Path(
    r"C:\Program Files\easyeda-pro\resources\app\assets\pro-ui"
    r"\3.2.196.26ed3d6c\js\ui.js"
)
DEFAULT_SCH_JS = Path(
    r"C:\Program Files\easyeda-pro\resources\app\assets\pro-sch"
    r"\3.2.192.b79ad524\js\sch-main.js"
)


def load_helpers() -> Any:
    path = ROOT / "scripts" / "audit-native-pcb-staging-checkpoint.py"
    spec = importlib.util.spec_from_file_location("pcb_delete_audit_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load checkpoint helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPERS = load_helpers()


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


def walk(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")


def document_meta(document: dict[str, Any]) -> dict[str, Any]:
    metas = [record.body for record in document["records"] if record.kind == "META"]
    if len(metas) > 1:
        raise AssertionError(f"document {document['uuid']} has {len(metas)} META records")
    return metas[0] if metas else {}


def parse_documents(checkpoint: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    semantic_hits: list[str] = []
    with zipfile.ZipFile(checkpoint) as archive:
        project2 = json.loads(archive.read("project2.json").decode("utf-8-sig"))
        with archive.open(PROJECT_SOURCE_ENTRY) as stream:
            for line_number, raw in enumerate(stream, 1):
                if not raw.strip():
                    continue
                record = HELPERS.parse_record_bytes(raw, f"{PROJECT_SOURCE_ENTRY}:{line_number}")
                if record.kind == "DOCHEAD":
                    current = {
                        "uuid": str(record.body.get("uuid") or ""),
                        "doc_type": str(record.body.get("docType") or ""),
                        "dochead": record.body,
                        "records": [],
                        "line_number": line_number,
                    }
                    documents.append(current)
                if current is None:
                    raise ValueError(f"record before first DOCHEAD at line {line_number}")
                current["records"].append(record)
                for json_path, value in walk(record.body):
                    key = json_path.rsplit(".", 1)[-1].casefold()
                    if key in {"blocksymboluuid", "cbbuuid"} or (
                        isinstance(value, str)
                        and value.casefold() in {"block_symbol", "cbb"}
                    ):
                        semantic_hits.append(
                            f"{current['uuid']}:{record.kind}:{record.record_id}:{json_path}={value!r}"
                        )
        return documents, project2, archive.namelist()


def document_summary(document: dict[str, Any]) -> dict[str, Any]:
    meta = document_meta(document)
    return {
        "uuid": document["uuid"],
        "doc_type": document["doc_type"],
        "title": meta.get("title", ""),
        "meta_links": {
            key: meta.get(key)
            for key in ("board", "schematic", "parent", "source")
            if key in meta
        },
        "record_count": len(document["records"]),
        "record_counts": dict(sorted(Counter(
            record.kind for record in document["records"]
        ).items())),
    }


def exact_value_hits(
    documents: list[dict[str, Any]], values: set[str]
) -> dict[str, list[dict[str, Any]]]:
    result = {value: [] for value in values}
    for document in documents:
        for record in document["records"]:
            for json_path, value in walk({"header": record.header, "body": record.body}):
                if isinstance(value, str) and value in result:
                    result[value].append({
                        "owner_uuid": document["uuid"],
                        "owner_doc_type": document["doc_type"],
                        "record_type": record.kind,
                        "record_id": record.record_id,
                        "json_path": json_path,
                    })
    return result


def source_evidence(ui_js: Path, sch_js: Path) -> dict[str, Any]:
    ui_text = ui_js.read_text(encoding="utf-8", errors="replace")
    sch_text = sch_js.read_text(encoding="utf-8", errors="replace")
    payload = (
        'leftTreeDelete2",{toDelBoards:[],toDelCbbs:[],toDelPanels:[],'
        'toDelPcbs:[e],toDelSchs:[],toDelSheets:[]}'
    )
    board_condition = (
        'r.includes(w.sch)&&(w.sch=""),n.includes(w.pcb)&&(w.pcb=""),'
        'w.sch===""&&w.pcb===""||!w.sch&&!w.pcb||c.includes(w.uuid)'
    )
    ui_index = ui_text.find(payload)
    sch_index = sch_text.find(board_condition)
    ui_context = (
        ui_text[max(0, ui_index - 180):ui_index + len(payload) + 180]
        if ui_index >= 0 else ""
    )
    sch_context = (
        sch_text[max(0, sch_index - 180):sch_index + len(board_condition) + 240]
        if sch_index >= 0 else ""
    )
    return {
        "ui_bundle": {
            "path": str(ui_js),
            "sha256": sha256_file(ui_js),
            "delete_pcb_payload_index": ui_index,
            "delete_pcb_payload_verified": ui_index >= 0,
            "context_sha256": sha256_bytes(ui_context.encode("utf-8")),
        },
        "schematic_bundle": {
            "path": str(sch_js),
            "sha256": sha256_file(sch_js),
            "board_detach_condition_index": sch_index,
            "board_detach_condition_verified": sch_index >= 0,
            "context_sha256": sha256_bytes(sch_context.encode("utf-8")),
        },
        "semantics": {
            "direct_dmt_delete_pcb_payload": {
                "toDelPcbs": "[exact requested UUID]",
                "toDelBoards": [],
                "toDelCbbs": [],
                "toDelSchs": [],
                "toDelSheets": [],
            },
            "board_is_deleted_only_after_requested_links_are_cleared_and_both_sch_and_pcb_are_empty": True,
        },
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.checkpoint, args.ui_js, args.sch_js):
        if not path.is_file():
            raise FileNotFoundError(path)
    documents, project2, zip_entries = parse_documents(args.checkpoint)
    by_uuid: dict[str, list[dict[str, Any]]] = {}
    for document in documents:
        by_uuid.setdefault(document["uuid"], []).append(document)
    if len(by_uuid.get(args.delete_pcb_uuid, [])) != 1:
        raise AssertionError("delete PCB UUID is not unique")
    if len(by_uuid.get(args.protected_schematic_uuid, [])) != 1:
        raise AssertionError("protected schematic UUID is not unique")

    delete_pcb = by_uuid[args.delete_pcb_uuid][0]
    protected_sch = by_uuid[args.protected_schematic_uuid][0]
    if delete_pcb["doc_type"] != "PCB" or protected_sch["doc_type"] != "SCH":
        raise AssertionError("requested UUID document types differ from PCB/SCH")
    delete_meta = document_meta(delete_pcb)
    sch_meta = document_meta(protected_sch)
    delete_title = str(delete_meta.get("title") or "")
    shared_board_uuid = str(delete_meta.get("board") or "")
    if not shared_board_uuid or sch_meta.get("board") != shared_board_uuid:
        raise AssertionError("obsolete PCB and protected schematic do not share a board UUID")
    board_docs = by_uuid.get(shared_board_uuid, [])
    if len(board_docs) != 1 or board_docs[0]["doc_type"] != "BOARD":
        raise AssertionError("shared BOARD document is missing or ambiguous")

    pages = [
        document for document in documents
        if document["doc_type"] == "SCH_PAGE"
        and document_meta(document).get("schematic") == args.protected_schematic_uuid
    ]
    pages.sort(key=lambda document: int(document_meta(document).get("zIndex") or 0))
    if len(pages) != args.expected_page_count:
        raise AssertionError(
            f"protected schematic page count={len(pages)}, expected={args.expected_page_count}"
        )

    title_collisions = [
        document for document in documents
        if str(document_meta(document).get("title") or "").casefold() == delete_title.casefold()
    ]
    same_title_symbols = [
        document for document in title_collisions if document["doc_type"] == "SYMBOL"
    ]
    cbb_doc_types = [
        document for document in documents
        if "CBB" in document["doc_type"].upper()
        or "BLOCK" in document["doc_type"].upper()
    ]
    cbb_semantic_hits: list[str] = []
    for document in documents:
        for record in document["records"]:
            for json_path, value in walk(record.body):
                key = json_path.rsplit(".", 1)[-1].casefold()
                if key in {"blocksymboluuid", "cbbuuid"} or (
                    isinstance(value, str) and value.casefold() in {"block_symbol", "cbb"}
                ):
                    cbb_semantic_hits.append(
                        f"{document['uuid']}:{record.kind}:{record.record_id}:{json_path}={value!r}"
                    )

    refs = exact_value_hits(
        documents,
        {args.delete_pcb_uuid, args.protected_schematic_uuid, shared_board_uuid},
    )
    handler = source_evidence(args.ui_js, args.sch_js)
    image_entries = [
        name for name in zip_entries
        if name.casefold() == f"image/{args.delete_pcb_uuid}.webp".casefold()
    ]
    no_cbb_collision = (
        project2.get("cbb_project") in (0, False, None)
        and not same_title_symbols
        and not cbb_doc_types
        and not cbb_semantic_hits
    )
    schematic_survival_safe = (
        len(title_collisions) == 1
        and no_cbb_collision
        and handler["ui_bundle"]["delete_pcb_payload_verified"]
        and handler["schematic_bundle"]["board_detach_condition_verified"]
        and len(pages) == args.expected_page_count
    )
    replacement_pcbs_on_shared_board = [
        document for document in documents
        if document["doc_type"] == "PCB"
        and document["uuid"] != args.delete_pcb_uuid
        and document_meta(document).get("board") == shared_board_uuid
    ]
    board_link_continuity_after_delete = bool(replacement_pcbs_on_shared_board)

    return {
        "schema": "stm32h747-pcb-replacement-delete-safety-audit-v1",
        "status": (
            "schematic-documents-safe-for-exact-dmt-pcb-delete; "
            "board-to-pcb-link-would-be-empty-until-replacement-is-attached"
            if schematic_survival_safe and not board_link_continuity_after_delete else
            "schematic-documents-and-board-link-safe-for-exact-dmt-pcb-delete"
            if schematic_survival_safe else "unsafe-or-inconclusive"
        ),
        "read_only": True,
        "checkpoint": {
            "path": str(args.checkpoint),
            "sha256": sha256_file(args.checkpoint),
            "project2": project2,
            "document_count": len(documents),
            "document_type_counts": dict(sorted(Counter(
                document["doc_type"] for document in documents
            ).items())),
        },
        "delete_target": document_summary(delete_pcb),
        "protected_schematic": {
            **document_summary(protected_sch),
            "shared_board": document_summary(board_docs[0]),
            "pages": [document_summary(page) for page in pages],
        },
        "identity_graph": {
            "delete_pcb_and_schematic_share_board_uuid": shared_board_uuid,
            "delete_pcb_title_collisions": [
                document_summary(document) for document in title_collisions
            ],
            "same_title_project_symbol_count": len(same_title_symbols),
            "serialized_references": refs,
            "delete_target_image_entries": image_entries,
            "delete_target_parent_is_empty": delete_meta.get("parent") in (None, ""),
            "no_serialized_child_or_parent_uuid_reference": (
                len(refs[args.delete_pcb_uuid]) == 1
            ),
            "replacement_pcbs_already_on_shared_board": [
                document_summary(document) for document in replacement_pcbs_on_shared_board
            ],
            "board_link_continuity_after_delete": board_link_continuity_after_delete,
        },
        "cbb_reuse_block_evidence": {
            "project2_cbb_project": project2.get("cbb_project"),
            "cbb_or_block_document_types": [
                document_summary(document) for document in cbb_doc_types
            ],
            "semantic_hits": cbb_semantic_hits,
            "same_title_symbol_documents": [
                document_summary(document) for document in same_title_symbols
            ],
            "no_same_name_cbb_or_reuse_block": no_cbb_collision,
        },
        "installed_delete_handler_evidence": handler,
        "verdict": {
            "exact_dmt_delete_pcb_uuid_is_safe_for_protected_schematic": schematic_survival_safe,
            "exact_delete_preserves_continuous_board_to_pcb_link": (
                board_link_continuity_after_delete
            ),
            "protected_schematic_page_count": len(pages),
            "important_scope": (
                "This verdict applies only to DMT_Pcb.deletePcb(exact UUID). "
                "Do not substitute Board deletion or generic multi-selection deletion."
            ),
            "recommended_sequence": (
                "Because copyPcb cannot attach a replacement while the BOARD PCB slot is occupied: "
                "retain the verified backup, call DMT_Pcb.deletePcb with only the exact obsolete "
                "UUID, immediately verify BOARD/SCH/all five pages, then copy/attach the replacement "
                "PCB and run the final checkpoint audit."
            ),
            "required_post_delete_checks": [
                "export a new checkpoint",
                f"assert PCB UUID {args.delete_pcb_uuid} is absent",
                f"assert SCH UUID {args.protected_schematic_uuid} and all pages remain",
                f"assert BOARD UUID {shared_board_uuid} still links the schematic",
            ],
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--delete-pcb-uuid", default=DEFAULT_DELETE_PCB_UUID)
    parser.add_argument("--protected-schematic-uuid", default=DEFAULT_PROTECTED_SCH_UUID)
    parser.add_argument("--expected-page-count", type=int, default=5)
    parser.add_argument("--ui-js", type=Path, default=DEFAULT_UI_JS)
    parser.add_argument("--sch-js", type=Path, default=DEFAULT_SCH_JS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({
            "status": report["status"],
            "checkpoint_sha256": report["checkpoint"]["sha256"],
            "delete_pcb_uuid": report["delete_target"]["uuid"],
            "protected_schematic_uuid": report["protected_schematic"]["uuid"],
            "protected_page_count": len(report["protected_schematic"]["pages"]),
            "same_title_symbol_count": (
                report["identity_graph"]["same_title_project_symbol_count"]
            ),
        }, ensure_ascii=False, separators=(",", ":")))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
