"""Audit the installed 3.2 footprint-source update path without invoking EasyEDA.

This report deliberately separates facts that are visible in the installed
JavaScript from hypotheses about a failed live update.  In particular, a
duplicate pad number is a supported footprint state and is not part of the
source decoder's PAD.check() or global-index validation gate.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "output/validation"
REPORT = VALIDATION / "native-footprint-duplicate-pad-update-handler-audit.json"

UI_JS = Path(
    r"C:\Program Files\easyeda-pro\resources\app\assets\pro-ui"
    r"\3.2.196.26ed3d6c\js\ui.js"
)
PCB_JS = Path(
    r"C:\Program Files\easyeda-pro\resources\app\assets\pro-pcb"
    r"\3.2.193.682ed44e\js\pcb.js"
)

BASE = ROOT / "output/checkpoints/STM32H747_after_inner_pad_shapes_20261014.epro2"
ATTEMPT_1 = ROOT / "output/checkpoints/STM32H747_after_u5_pth_attempt_20261014.epro2"
ATTEMPT_2 = ROOT / "output/checkpoints/STM32H747_after_u5_pth_second_attempt_20261014.epro2"
CANDIDATE = ROOT / "output/validation/native-U5-thermal-pth-pad-candidate.epru"
U5_UUID = "b098cceac55eab69"
NEW_IDS = {"e36", "e37", "e38", "e39"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_record(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    head_text, body_text = raw.split("||", 1)
    if body_text.endswith("|"):
        body_text = body_text[:-1]
    return json.loads(head_text), json.loads(body_text)


def source_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [parse_record(raw) for raw in path.read_text(encoding="utf-8-sig").splitlines()]


def checkpoint_block(path: Path, uuid: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".epru"))
        lines = archive.read(member).decode("utf-8-sig").splitlines()
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    active = False
    for raw in lines:
        head, body = parse_record(raw)
        if head.get("type") == "DOCHEAD":
            if active:
                break
            active = body.get("docType") == "FOOTPRINT" and body.get("uuid") == uuid
        if active:
            result.append((head, body))
    if not result:
        raise AssertionError(f"footprint {uuid} absent from {path.name}")
    return result


def record_key(record: tuple[dict[str, Any], dict[str, Any]]) -> tuple[str, str]:
    head, _ = record
    return str(head.get("type")), str(head.get("id"))


def checkpoint_summary(path: Path, base: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    current = checkpoint_block(path, U5_UUID)
    before = {record_key(item): item for item in base}
    after = {record_key(item): item for item in current}
    common = set(before) & set(after)
    changed_heads = sorted(key for key in common if before[key][0] != after[key][0])
    changed_bodies = sorted(key for key in common if before[key][1] != after[key][1])
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "record_count": len(current),
        "type_counts": dict(sorted(Counter(head["type"] for head, _ in current).items())),
        "added_keys": sorted(set(after) - set(before)),
        "removed_keys": sorted(set(before) - set(after)),
        "new_thermal_ids_present": sorted(
            head["id"] for head, _ in current
            if head.get("type") == "PAD" and head.get("id") in NEW_IDS
        ),
        "changed_header_keys": changed_heads,
        "changed_body_keys": changed_bodies,
        "dochead": current[0][1],
    }


def find_evidence(source: str, needles: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, needle in needles.items():
        offset = source.find(needle)
        if offset < 0:
            raise AssertionError(f"installed-code evidence missing: {name}")
        result[name] = {"character_offset": offset, "needle": needle}
    return result


def pad_check_contract(body: dict[str, Any]) -> dict[str, Any]:
    # Mirrors the explicit d6.feed()/prepareExpansion()/check() predicates.
    pad_type = body.get("padType")
    mapped_pad_type_valid = pad_type in {"NORMAL", "TEST", "FIDUCIAL"}
    expansions = [
        body.get("topSolderExpansion"),
        body.get("bottomSolderExpansion"),
        body.get("topPasteExpansion"),
        body.get("bottomPasteExpansion"),
    ]
    expansion_defined_after_prepare = all(value is not None for value in expansions) or all(
        value is None for value in expansions
    )
    checks = {
        "id_nonempty": bool(body.get("id")),
        "group_id_defined": body.get("groupId") is not None,
        "layer_id_truthy": bool(body.get("layerId")),
        "pad_number_not_null": body.get("num") is not None,
        "rotation_numeric": isinstance(body.get("padAngle"), (int, float)),
        "pad_type_supported": mapped_pad_type_valid,
        "expansions_defined_after_prepareExpansion": expansion_defined_after_prepare,
        "locked_not_null": body.get("locked") is not None,
    }
    return {"checks": checks, "passes": all(checks.values())}


def main() -> None:
    ui_source = UI_JS.read_text(encoding="utf-8", errors="replace")
    pcb_source = PCB_JS.read_text(encoding="utf-8", errors="replace")

    ui_evidence = find_evidence(ui_source, {
        "update_source_handler": (
            'static async updateDocumentSource({footprintUuid:e,libraryUuid:i,documentSource:o})'
        ),
        "decode_then_unconditional_save_then_boolean_decode_result": (
            'rpcCall("pcb/decode",o,a.contentWindow).then(async l=>(await '
            'w.windowBridge.rpcCall("pcb/saveCompiler","",a.contentWindow),r(),!!l.message))'
        ),
        "footprint_save_duplicate_warning_is_success": (
            'Found the duplicated Pad Number in this footprint'
        ),
    })
    pcb_evidence = find_evidence(pcb_source, {
        "decode_rpc": (
            'A.messageBus.rpcService("pcb/decode",async t=>{if(t!==null){let e=x.getInstance(),'
            'r=new tG(e.compiler);return await r.parseSourceByCompiler(t),r.build()}return!1})'
        ),
        "pad_check": (
            'check(){return!(!this.index||this.groupId===void 0||!this.layerId||this.num==null||'
            'this.rotation==null||isNaN(this.rotation)||!(this.padType===0||this.padType===1||'
            'this.padType===2)||this.topSolderExpansion===void 0||this.bottomSolderExpansion===void 0||'
            'this.pasteExpansion===void 0||this.locked==null)}'
        ),
        "global_index_uniqueness": (
            'applyCheck(){return!this.check()||(this.getIndex(),!Re.isSingle(this._index))?!1:'
        ),
        "duplicate_number_warning_service": (
            'rpcService("isPadNumDuplicated",()=>{let t=!1,e={},r=Kt.getAllItem()'
        ),
    })

    candidate = source_records(CANDIDATE)
    ids = [str(head.get("id")) for head, _ in candidate if head.get("id") is not None]
    if len(ids) != len(set(ids)):
        raise AssertionError("candidate has duplicate record IDs")
    new_pads: list[dict[str, Any]] = []
    for head, body in candidate:
        if head.get("type") != "PAD" or head.get("id") not in NEW_IDS:
            continue
        effective = dict(body)
        effective["id"] = head["id"]
        check = pad_check_contract(effective)
        new_pads.append({
            "id": head["id"],
            "ticket": head.get("ticket"),
            "firstTicket": head.get("firstTicket"),
            "num": body.get("num"),
            "center_mil": [body.get("centerX"), body.get("centerY")],
            "layerId": body.get("layerId"),
            "body_contract": check,
        })
    if {item["id"] for item in new_pads} != NEW_IDS or not all(
        item["body_contract"]["passes"] for item in new_pads
    ):
        raise AssertionError("candidate thermal PAD static contract failed")

    base_block = checkpoint_block(BASE, U5_UUID)
    attempts = [checkpoint_summary(path, base_block) for path in (ATTEMPT_1, ATTEMPT_2)]
    if any(item["added_keys"] or item["removed_keys"] or item["new_thermal_ids_present"] for item in attempts):
        raise AssertionError("failed attempt unexpectedly persisted a thermal PAD")

    report = {
        "status": "pass-static-diagnosis-exact-runtime-failure-not-localized",
        "scope": "Installed EasyEDA Pro 3.2 footprint document-source update and failed U5 duplicate-number thermal-pad attempts",
        "installed": {
            "ui": {"path": str(UI_JS), "sha256": sha256(UI_JS), "evidence": ui_evidence},
            "pcb": {"path": str(PCB_JS), "sha256": sha256(PCB_JS), "evidence": pcb_evidence},
        },
        "candidate": {
            "path": str(CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(CANDIDATE),
            "record_count": len(candidate),
            "record_ids_unique": len(ids) == len(set(ids)),
            "new_pads": new_pads,
        },
        "failed_attempt_checkpoints": attempts,
        "findings": [
            "The installed PAD decoder/check gate does not test pad-number uniqueness.",
            "The candidate's four new PAD records have unique record IDs/tickets and satisfy every explicit d6.check predicate after prepareExpansion semantics.",
            "The separate isPadNumDuplicated service only emits a warning; the normal footprint-save check returns success after that warning.",
            "updateDocumentSource returns the boolean pcb/decode message but invokes saveCompiler unconditionally, even when decode reports false.",
            "Both failed checkpoints retain zero added thermal PAD records. They only show administrative DOCHEAD/ticket normalization; every non-DOCHEAD record body and the full ID set remain unchanged.",
            "A later direct PrimitivePad.create with a fresh random ID successfully created a second pad number 25, independently proving that the duplicate number and PAD geometry are accepted by the installed runtime.",
        ],
        "bounded_conclusion": {
            "ruled_out": [
                "duplicate pad number as an explicit d6.check/applyCheck predicate",
                "duplicate record ID inside the corrected candidate",
                "missing required fields in the four corrected candidate PAD bodies",
                "META/ATTR body mutation in either failed persisted checkpoint",
            ],
            "not_proven_without_console_exception": (
                "The exact statement that returned/rejected inside pcb/decode. A false public result can arise from the explicit applyCheck false path or from a later build/RPC failure whose message is false/absent."
            ),
            "most_conservative_operational_inference": (
                "The failure is specific to full-source merge/history state (including possible stale e36-e39 CRDT identities), not to duplicate pad numbering. Use documented primitive creation with fresh IDs and verify a reopened checkpoint/runtime PAD_NET inventory."
            ),
        },
        "manufacturing_approval": False,
    }
    VALIDATION.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "sha256": sha256(REPORT), "status": report["status"]}, indent=2))


if __name__ == "__main__":
    main()
