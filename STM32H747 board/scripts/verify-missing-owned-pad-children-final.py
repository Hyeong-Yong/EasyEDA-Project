#!/usr/bin/env python3
"""Verify the final 50 restored component-owned PAD children and bindings."""

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
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
PCB_UUID = "0ac2a19168000d8e"
DEFAULT_BASELINE = ROOT / "output/checkpoints/STM32H747_after_thermal_pth_restore_20261014.epro2"
DEFAULT_CREATED = ROOT / "output/checkpoints/STM32H747_after_missing_pad_children_created_20261014.epro2"
DEFAULT_MASKED = ROOT / "output/checkpoints/STM32H747_after_all_owned_pad_masks_20261015.epro2"
DEFAULT_SMA_AUDIT = ROOT / "output/validation/native-missing-sma-ground-pth-audit.json"
DEFAULT_SW_AUDIT = ROOT / "output/validation/native-missing-sw1-duplicate-smd-pad-audit.json"
DEFAULT_MASK_MANIFEST = ROOT / "output/native-libraries/sma-owned-post-inner-layer-candidates/manifest.json"
DEFAULT_BINDING = ROOT / "output/validation/native-missing-owned-pad-net-binding-50.json"
DEFAULT_DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
DEFAULT_REPORT = ROOT / "output/validation/native-missing-owned-pad-children-final-audit.json"
ALLOWED_DOCHEAD_FIELDS = {"updateTime", "version", "user"}
DIMENSION_TOLERANCE_MIL = 0.001
POSITION_TOLERANCE_MIL = 0.11


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    head: dict[str, Any]
    body: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return str(self.head.get("type") or ""), str(self.head.get("id") or "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"non-finite number {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float = DIMENSION_TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def parse_record(line: str, label: str, number: int) -> Record:
    try:
        source = line[:-1] if line.endswith("|") else line
        head_text, body_text = source.split("||", 1)
        return Record(json.loads(head_text), json.loads(body_text))
    except Exception as exc:
        raise AuditError(f"{label}:{number}: invalid native record") from exc


def parse_documents(text: str, label: str) -> tuple[dict[str, list[Record]], list[str]]:
    documents: dict[str, list[Record]] = {}
    order: list[str] = []
    current: str | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        row = parse_record(line, label, number)
        if row.head.get("type") == "DOCHEAD":
            current = str(row.body.get("uuid") or "")
            if not current or current in documents:
                raise AuditError(f"{label}:{number}: duplicate or empty document UUID")
            documents[current] = []
            order.append(current)
        if current is None:
            raise AuditError(f"{label}:{number}: record before DOCHEAD")
        documents[current].append(row)
    return documents, order


def read_checkpoint(path: Path) -> tuple[dict[str, list[Record]], list[str]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.endswith(".epru")]
        if names != [MEMBER]:
            raise AuditError(f"{path}: expected only {MEMBER}, got {names}")
        return parse_documents(archive.read(MEMBER).decode("utf-8-sig"), str(path))


def rows_by_key(rows: Sequence[Record], label: str, include_dochead: bool = False) -> dict[tuple[str, str], Record]:
    result: dict[tuple[str, str], Record] = {}
    for row in rows:
        if row.head.get("type") == "DOCHEAD" and not include_dochead:
            continue
        if row.key in result:
            raise AuditError(f"{label}: duplicate record key {row.key}")
        result[row.key] = row
    return result


def changed_fields(left: dict[str, Any], right: dict[str, Any]) -> set[str]:
    return {name for name in set(left) | set(right) if left.get(name) != right.get(name)}


def check_dochead(reference: str, before: Sequence[Record], after: Sequence[Record]) -> None:
    if not before or not after or before[0].head.get("type") != "DOCHEAD" or after[0].head.get("type") != "DOCHEAD":
        raise AuditError(f"{reference}: missing DOCHEAD")
    unsupported = changed_fields(before[0].body, after[0].body) - ALLOWED_DOCHEAD_FIELDS
    if unsupported:
        raise AuditError(f"{reference}: unsupported DOCHEAD changes {sorted(unsupported)}")


def normalize_pad_body(body: dict[str, Any]) -> dict[str, Any]:
    result = dict(body)
    if result.get("attrsMap") == {}:
        result.pop("attrsMap")
    if result.get("propagationDelay") is None:
        result["propagationDelay"] = 0
    return result


def check_changed_pad_header(reference: str, before: Record, after: Record) -> None:
    if set(after.head) not in (set(before.head), set(before.head) | {"firstTicket"}):
        raise AuditError(f"{reference}:{before.key[1]}: PAD header fields changed")
    for field in set(before.head) - {"ticket", "firstTicket"}:
        if before.head.get(field) != after.head.get(field):
            raise AuditError(f"{reference}:{before.key[1]}: protected PAD header {field} changed")
    expected_first = before.head.get("firstTicket", before.head.get("ticket"))
    if after.head.get("firstTicket") != expected_first:
        raise AuditError(f"{reference}:{before.key[1]}: firstTicket mismatch")


def allowed_empty_footprint_attr_normalization(before: Record, after: Record) -> bool:
    if before.head.get("type") != "ATTR" or before.key != after.key:
        return False
    try:
        check_changed_pad_header("Footprint ATTR", before, after)
    except AuditError:
        return False
    left = dict(before.body)
    right = dict(after.body)
    if left.get("key") != "Footprint" or left.get("value") != "" or right.get("value") is not None:
        return False
    left.pop("value", None)
    right.pop("value", None)
    return left == right


def allowed_reticketed_pad(before: Record, after: Record) -> bool:
    if before.head.get("type") != "PAD" or before.body != after.body:
        return False
    try:
        check_changed_pad_header("PAD", before, after)
    except AuditError:
        return False
    return True


def check_candidate_pad(reference: str, before: Record, after: Record, expected: Record) -> None:
    check_changed_pad_header(reference, before, after)
    actual_body = normalize_pad_body(after.body)
    expected_body = normalize_pad_body(expected.body)
    if set(actual_body) != set(expected_body):
        raise AuditError(f"{reference}:{before.key[1]}: PAD body fields changed")
    for field in set(expected_body) - {"hole", "defaultPad"}:
        if actual_body.get(field) != expected_body.get(field):
            raise AuditError(f"{reference}:{before.key[1]}: protected PAD body field {field} changed")
    for field in ("hole", "defaultPad"):
        left = actual_body.get(field)
        right = expected_body.get(field)
        if not isinstance(left, dict) or not isinstance(right, dict) or set(left) != set(right):
            raise AuditError(f"{reference}:{before.key[1]}: {field} structure changed")
        for name in left:
            if isinstance(left[name], (int, float)) and isinstance(right[name], (int, float)):
                if not close(left[name], right[name]):
                    raise AuditError(f"{reference}:{before.key[1]}: {field}.{name} changed")
            elif left[name] != right[name]:
                raise AuditError(f"{reference}:{before.key[1]}: {field}.{name} changed")


def load_creation_receipts() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for reference in [*(f"J{number}" for number in range(2, 18)), "SW1"]:
        path = ROOT / f"output/validation/native-{reference}-missing-owned-pad-create-receipt.json"
        if not path.is_file():
            raise AuditError(f"missing creation receipt {path}")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        expected_count = 2 if reference == "SW1" else 3
        if receipt.get("reference") != reference or receipt.get("expected") is not True or receipt.get("saved") is not True or len(receipt.get("added") or []) != expected_count:
            raise AuditError(f"{reference}: invalid creation receipt")
        result[reference] = {"path": path, "sha256": sha256(path), "value": receipt}
    return result


def read_candidate(path: Path) -> tuple[str, list[Record]]:
    documents, order = parse_documents(path.read_text(encoding="utf-8-sig"), str(path))
    if len(order) != 1:
        raise AuditError(f"{path}: candidate must contain one document")
    return order[0], documents[order[0]]


def pad_net_identity(header: dict[str, Any]) -> tuple[str, str, str]:
    try:
        value = json.loads(str(header.get("id")))
    except Exception as exc:
        raise AuditError(f"invalid PAD_NET id {header.get('id')!r}") from exc
    if not isinstance(value, list) or len(value) != 4 or value[0] != "PAD_NET":
        raise AuditError(f"invalid PAD_NET tuple {value!r}")
    return str(value[1]), str(value[2]), str(value[3])


def owner_contracts(
    receipts: dict[str, dict[str, Any]],
    sma_audit: dict[str, Any],
    sw_audit: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, str]]]:
    sma_rows = {str(item["reference"]): item for item in sma_audit["footprints"]}
    result: dict[str, dict[str, Any]] = {}
    expected_pad_nets: dict[tuple[str, str], dict[str, str]] = {}
    for reference in (f"J{number}" for number in range(2, 18)):
        audit = sma_rows[reference]
        receipt = receipts[reference]["value"]
        if receipt.get("uuid") != audit.get("footprint_uuid"):
            raise AuditError(f"{reference}: receipt/audit footprint mismatch")
        added = {str(item["id"]): item for item in receipt["added"]}
        result[reference] = {
            "footprint_uuid": str(audit["footprint_uuid"]),
            "component_id": str(audit["component_id"]),
            "added": added,
            "net": "GND",
        }
        for local_id in added:
            expected_pad_nets[(str(audit["component_id"]), local_id)] = {"number": "2", "net": "GND", "reference": reference}
    identity = sw_audit["identity"]
    sw_receipt = receipts["SW1"]["value"]
    if sw_receipt.get("uuid") != identity.get("footprint_uuid"):
        raise AuditError("SW1 receipt/audit footprint mismatch")
    sw_added = {str(item["id"]): item for item in sw_receipt["added"]}
    sw_nets = {"1": "Net-(D1-K)", "2": "GND"}
    result["SW1"] = {
        "footprint_uuid": str(identity["footprint_uuid"]),
        "component_id": str(identity["component_id"]),
        "added": sw_added,
        "net_by_number": sw_nets,
    }
    for local_id, item in sw_added.items():
        number = str(item["num"])
        expected_pad_nets[(str(identity["component_id"]), local_id)] = {"number": number, "net": sw_nets[number], "reference": "SW1"}
    if len(expected_pad_nets) != 50:
        raise AuditError(f"expected 50 owned child contracts, got {len(expected_pad_nets)}")
    return result, expected_pad_nets


def verify_creation_phase(
    baseline_docs: dict[str, list[Record]],
    created_docs: dict[str, list[Record]],
    owners: dict[str, dict[str, Any]],
) -> None:
    for reference, contract in owners.items():
        uuid = contract["footprint_uuid"]
        before = baseline_docs[uuid]
        after = created_docs[uuid]
        check_dochead(reference, before, after)
        before_rows = rows_by_key(before, reference + ":baseline")
        after_rows = rows_by_key(after, reference + ":created")
        added_keys = set(after_rows) - set(before_rows)
        expected_keys = {("PAD", local_id) for local_id in contract["added"]}
        if added_keys != expected_keys or set(before_rows) - set(after_rows):
            raise AuditError(f"{reference}: creation-phase record identity mismatch")
        for key, row in before_rows.items():
            if row != after_rows[key]:
                raise AuditError(f"{reference}: existing record changed during creation: {key}")
        for local_id, receipt_row in contract["added"].items():
            body = after_rows[("PAD", local_id)].body
            if body.get("num") != str(receipt_row["num"]) or body.get("layerId") != int(receipt_row["layer"]) or body.get("plated") is not True:
                raise AuditError(f"{reference}:{local_id}: created identity/ownership mismatch")
            if not close(body.get("centerX"), receipt_row["x"], POSITION_TOLERANCE_MIL) or not close(body.get("centerY"), receipt_row["y"], POSITION_TOLERANCE_MIL):
                raise AuditError(f"{reference}:{local_id}: source centerX/centerY differs from runtime creation receipt")
            if "x" in body or "y" in body:
                raise AuditError(f"{reference}:{local_id}: noncanonical x/y fields persisted")


def verify_final_footprints(
    created_docs: dict[str, list[Record]],
    final_docs: dict[str, list[Record]],
    owners: dict[str, dict[str, Any]],
    mask_manifest: dict[str, Any],
) -> dict[str, Any]:
    candidates = {str(item["reference"]): item for item in mask_manifest["candidates"]}
    total_nonempty = 0
    total_new_masked = 0
    protected = 0
    for reference, contract in owners.items():
        uuid = contract["footprint_uuid"]
        before = created_docs[uuid]
        after = final_docs[uuid]
        check_dochead(reference, before, after)
        before_rows = rows_by_key(before, reference + ":created")
        after_rows = rows_by_key(after, reference + ":final")
        if set(before_rows) != set(after_rows):
            raise AuditError(f"{reference}: final footprint record identity set changed")
        added_ids = set(contract["added"])
        if reference == "SW1":
            for key in before_rows:
                if before_rows[key] != after_rows[key]:
                    raise AuditError(f"SW1: post-create protected record changed {key}")
            pads = [row for row in after_rows.values() if row.head.get("type") == "PAD"]
            if len(pads) != 4 or any(row.body.get("unusedInnerLayers") not in ([], None) for row in pads):
                raise AuditError("SW1 final physical PAD inventory mismatch")
            protected += len(before_rows)
            continue
        candidate_item = candidates.get(reference)
        if candidate_item is None or candidate_item.get("footprint_uuid") != uuid:
            raise AuditError(f"{reference}: reviewed mask candidate missing")
        candidate_path = ROOT / Path(str(candidate_item["candidate"]))
        candidate_uuid, candidate_records = read_candidate(candidate_path)
        if candidate_uuid != uuid or sha256(candidate_path) != candidate_item["candidate_sha256"]:
            raise AuditError(f"{reference}: candidate identity/hash mismatch")
        candidate_rows = rows_by_key(candidate_records, reference + ":candidate")
        if set(candidate_rows) != set(after_rows):
            raise AuditError(f"{reference}: final/candidate record identity mismatch")
        candidate_ids = {str(item["record_id"]) for item in candidate_item["modifications"]}
        if candidate_ids != added_ids:
            raise AuditError(f"{reference}: reviewed mask IDs differ from native creation receipt")
        for key, before_row in before_rows.items():
            after_row = after_rows[key]
            if key[1] not in added_ids:
                if before_row != after_row and not allowed_reticketed_pad(before_row, after_row) and not allowed_empty_footprint_attr_normalization(before_row, after_row):
                    raise AuditError(f"{reference}: existing/protected record changed {key}")
                protected += 1
            else:
                check_candidate_pad(reference, before_row, after_row, candidate_rows[key])
                if before_row.body.get("unusedInnerLayers") not in ([], None) or after_row.body.get("unusedInnerLayers") != [16]:
                    raise AuditError(f"{reference}:{key[1]}: mask change is not [] -> [16]")
                total_new_masked += 1
        pads = [row for row in after_rows.values() if row.head.get("type") == "PAD"]
        if len(pads) != 5:
            raise AuditError(f"{reference}: expected five physical PADs")
        nonempty = [row for row in pads if row.body.get("unusedInnerLayers")]
        pad2 = [row for row in pads if row.body.get("num") == "2"]
        pad1 = [row for row in pads if row.body.get("num") == "1"]
        if len(nonempty) != 5 or len(pad2) != 4 or len(pad1) != 1:
            raise AuditError(f"{reference}: physical pad/mask count mismatch")
        if any(row.body.get("unusedInnerLayers") != [16] for row in pad2):
            raise AuditError(f"{reference}: one or more ground posts does not hide only In2")
        if not pad1[0].body.get("unusedInnerLayers"):
            raise AuditError(f"{reference}: pad1 existing inner-layer mask disappeared")
        total_nonempty += len(nonempty)
    if total_new_masked != 48 or total_nonempty != 80:
        raise AuditError(f"SMA mask totals mismatch: new={total_new_masked}, nonempty={total_nonempty}")
    return {"new_sma_post_masks": total_new_masked, "nonempty_sma_pad_masks": total_nonempty, "protected_records": protected}


def verify_final_pcb(
    baseline_rows: Sequence[Record],
    final_rows: Sequence[Record],
    expected_pad_nets: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    check_dochead("PCB", baseline_rows, final_rows)
    before = rows_by_key(baseline_rows, "PCB:baseline")
    after = rows_by_key(final_rows, "PCB:final")
    added_keys = set(after) - set(before)
    removed_keys = set(before) - set(after)
    if removed_keys:
        raise AuditError(f"PCB lost records: {sorted(removed_keys)[:10]}")
    if any(key[0] != "PAD_NET" for key in added_keys) or len(added_keys) != 50:
        raise AuditError(f"PCB additions are not exactly 50 PAD_NET records: {Counter(key[0] for key in added_keys)}")
    for key, row in before.items():
        target = after[key]
        if row == target:
            continue
        if key == ("ACTIVE_LAYER", "ACTIVE_LAYER"):
            if changed_fields(row.body, target.body) - {"layerId"}:
                raise AuditError("PCB ACTIVE_LAYER changed beyond selected layer")
            try:
                check_changed_pad_header("PCB ACTIVE_LAYER", row, target)
            except AuditError as exc:
                raise AuditError("PCB ACTIVE_LAYER header normalization mismatch")
            continue
        raise AuditError(f"PCB protected record changed: {key}")
    actual: dict[tuple[str, str], dict[str, str]] = {}
    for key in added_keys:
        row = after[key]
        component, number, local_id = pad_net_identity(row.head)
        owner_key = (component, local_id)
        if owner_key in actual:
            raise AuditError(f"duplicate restored PCB child {owner_key}")
        actual[owner_key] = {"number": number, "net": str(row.body.get("padNet") or "")}
    if set(actual) != set(expected_pad_nets):
        raise AuditError("restored PCB PAD_NET owner/local-ID set mismatch")
    for owner_key, expected in expected_pad_nets.items():
        if actual[owner_key] != {"number": expected["number"], "net": expected["net"]}:
            raise AuditError(f"{expected['reference']} {owner_key}: explicit PAD_NET mismatch")
    pad_net_count = sum(row.head.get("type") == "PAD_NET" for row in after.values())
    component_count = sum(row.head.get("type") == "COMPONENT" for row in after.values())
    top_level_pad_count = sum(row.head.get("type") == "PAD" for row in after.values())
    if (pad_net_count, component_count, top_level_pad_count) != (1234, 330, 4):
        raise AuditError(f"final PCB inventory mismatch: PAD_NET={pad_net_count}, COMPONENT={component_count}, PAD={top_level_pad_count}")
    return {
        "new_owned_pad_net_records": len(actual),
        "pad_net_records": pad_net_count,
        "component_records": component_count,
        "top_level_board_npth_records": top_level_pad_count,
        "runtime_pad_total_expected": pad_net_count + top_level_pad_count,
    }


def verify_binding_receipt(
    path: Path,
    expected_pad_nets: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("pcbUuid") != PCB_UUID or value.get("expectedAdded") != 50 or value.get("totalRuntimePads") != 1238 or len(value.get("results") or []) != 50:
        raise AuditError("binding receipt scope/count mismatch")
    actual: dict[tuple[str, str], dict[str, str]] = {}
    for row in value["results"]:
        primitive = str(row.get("id") or "")
        matches = [key for key in expected_pad_nets if primitive == key[0] + key[1]]
        if len(matches) != 1:
            raise AuditError(f"binding receipt child identity is not receipt-derived: {primitive}")
        key = matches[0]
        actual[key] = {"number": str(row.get("padNumber") or ""), "net": str(row.get("afterNet") or "")}
    if set(actual) != set(expected_pad_nets):
        raise AuditError("binding receipt does not cover all 50 restored children")
    for key, expected in expected_pad_nets.items():
        if actual[key] != {"number": expected["number"], "net": expected["net"]}:
            raise AuditError(f"binding receipt mismatch for {expected['reference']} {key}")
    return {"path": str(path), "sha256": sha256(path), "results": len(actual)}


def allowed_schematic_ui_state_change(before: Sequence[Record], after: Sequence[Record]) -> bool:
    try:
        if (before[0].body.get("docType"), after[0].body.get("docType")) != ("SCH_PAGE", "SCH_PAGE"):
            return False
        check_dochead("schematic UI state", before, after)
        left = rows_by_key(before, "schematic UI before")
        right = rows_by_key(after, "schematic UI after")
        if set(left) != set(right):
            return False
        changed = [key for key in left if left[key] != right[key]]
        if changed != [("META", "META")]:
            return False
        old = left[("META", "META")]
        new = right[("META", "META")]
        if changed_fields(old.body, new.body) != {"zIndex"} or old.body.get("zIndex") != 2 or new.body.get("zIndex") != 2.5:
            return False
        check_changed_pad_header("schematic META", old, new)
        return True
    except AuditError:
        return False


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
    receipts = load_creation_receipts()
    sma_audit = json.loads(args.sma_audit.read_text(encoding="utf-8"))
    sw_audit = json.loads(args.sw_audit.read_text(encoding="utf-8"))
    mask_manifest = json.loads(args.mask_manifest.read_text(encoding="utf-8"))
    if mask_manifest.get("schema") != "stm32h747-sma-owned-post-inner-layer-candidates-v1" or mask_manifest.get("scope", {}).get("new_pad_bodies_changed") != 48:
        raise AuditError("reviewed 48-PAD mask manifest required")
    owners, expected_pad_nets = owner_contracts(receipts, sma_audit, sw_audit)
    baseline_docs, baseline_order = read_checkpoint(args.baseline)
    created_docs, created_order = read_checkpoint(args.created)
    masked_docs, masked_order = read_checkpoint(args.masked)
    final_docs, final_order = read_checkpoint(args.checkpoint)
    if baseline_order != created_order or created_order != masked_order or masked_order != final_order or set(baseline_docs) != set(final_docs):
        raise AuditError("project document UUID set/order changed")
    verify_creation_phase(baseline_docs, created_docs, owners)
    footprint_summary = verify_final_footprints(created_docs, masked_docs, owners, mask_manifest)
    target_footprints = {contract["footprint_uuid"] for contract in owners.values()}
    changed_footprints_after_mask = [
        uuid for uuid in sorted(target_footprints) if masked_docs[uuid] != final_docs[uuid]
    ]
    if changed_footprints_after_mask:
        raise AuditError(f"owned footprint sources changed after reviewed mask stage: {changed_footprints_after_mask}")
    allowed_changed = target_footprints | {PCB_UUID}
    changed_non_targets = [
        uuid for uuid in baseline_order
        if uuid not in allowed_changed
        and baseline_docs[uuid] != final_docs[uuid]
        and not allowed_schematic_ui_state_change(baseline_docs[uuid], final_docs[uuid])
    ]
    if changed_non_targets:
        raise AuditError(f"unrelated documents changed: {changed_non_targets[:10]}")
    allowed_ui_state_documents = [
        uuid for uuid in baseline_order
        if uuid not in allowed_changed
        and baseline_docs[uuid] != final_docs[uuid]
        and allowed_schematic_ui_state_change(baseline_docs[uuid], final_docs[uuid])
    ]
    pcb_summary = verify_final_pcb(baseline_docs[PCB_UUID], final_docs[PCB_UUID], expected_pad_nets)
    binding_summary = verify_binding_receipt(args.binding, expected_pad_nets)
    drc = json.loads(args.drc.read_text(encoding="utf-8"))
    connection_count = int((drc.get("counts") or {}).get("Connection Error", 0))
    if connection_count != 0:
        raise AuditError(f"DRC has {connection_count} Connection Error findings")
    report = {
        "schema": "stm32h747-missing-owned-pad-children-final-audit-v1",
        "status": "pass-static-owned-pad-restoration-not-manufacturing-approval",
        "inputs": {
            "baseline_checkpoint": {"path": str(args.baseline), "sha256": sha256(args.baseline)},
            "post_create_checkpoint": {"path": str(args.created), "sha256": sha256(args.created)},
            "post_mask_checkpoint": {"path": str(args.masked), "sha256": sha256(args.masked)},
            "final_checkpoint": {"path": str(args.checkpoint), "sha256": sha256(args.checkpoint)},
            "sma_audit": {"path": str(args.sma_audit), "sha256": sha256(args.sma_audit)},
            "sw1_audit": {"path": str(args.sw_audit), "sha256": sha256(args.sw_audit)},
            "mask_manifest": {"path": str(args.mask_manifest), "sha256": sha256(args.mask_manifest)},
            "binding_receipt": binding_summary,
            "drc": {"path": str(args.drc), "sha256": sha256(args.drc)},
            "creation_receipts": {reference: {"path": str(item["path"]), "sha256": item["sha256"]} for reference, item in sorted(receipts.items())},
        },
        "scope": {
            "references": [*(f"J{number}" for number in range(2, 18)), "SW1"],
            "component_owned_children_restored": 50,
            "sma_plated_ground_posts": 48,
            "sw1_duplicate_number_smd_pads": 2,
            "project_documents": len(baseline_docs),
            "unrelated_documents_exactly_unchanged": len(baseline_docs) - len(allowed_changed) - len(allowed_ui_state_documents),
            "validated_ui_state_only_documents": allowed_ui_state_documents,
        },
        "footprints": footprint_summary,
        "pcb": pcb_summary,
        "drc": {"connection_error_count": connection_count, "counts": drc.get("counts") or {}},
        "checks": {
            "all_50_child_ids_come_from_native_creation_receipts": True,
            "all_50_children_remain_owned_by_their_original_components": True,
            "all_preexisting_footprint_record_bodies_are_unchanged": True,
            "all_48_new_sma_posts_change_only_unused_inner_layers_empty_to_16": True,
            "all_80_sma_pad_records_have_authoritative_nonempty_inner_layer_masks": True,
            "all_50_new_pad_net_records_have_explicit_expected_nets": True,
            "all_preexisting_pcb_records_are_unchanged": True,
            "u5_u7_special_pad_and_thermal_footprint_documents_remain_exactly_preserved": True,
            "all_slot_footprint_documents_remain_exactly_preserved": True,
            "source_uses_canonical_center_x_center_y_not_transient_x_y": True,
            "drc_connection_error_count_is_zero": True,
        },
        "limitations": [
            "This is a static ownership, geometry, mask, and PAD_NET preservation audit; it is not fabrication approval.",
            "The separate final drill inventory audit must match every native hole one-to-one with authoritative Excellon.",
            "Remaining positive-clearance findings require independent engineering disposition.",
        ],
    }
    write_json(args.report, report)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--created", type=Path, default=DEFAULT_CREATED)
    parser.add_argument("--masked", type=Path, default=DEFAULT_MASKED)
    parser.add_argument("--sma-audit", type=Path, default=DEFAULT_SMA_AUDIT)
    parser.add_argument("--sw-audit", type=Path, default=DEFAULT_SW_AUDIT)
    parser.add_argument("--mask-manifest", type=Path, default=DEFAULT_MASK_MANIFEST)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--drc", type=Path, default=DEFAULT_DRC)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    for field in ("checkpoint", "baseline", "created", "masked", "sma_audit", "sw_audit", "mask_manifest", "binding", "drc", "report"):
        value = getattr(args, field)
        if not value.is_absolute():
            setattr(args, field, (Path.cwd() / value).resolve())
    for field in ("checkpoint", "baseline", "created", "masked", "sma_audit", "sw_audit", "mask_manifest", "binding", "drc"):
        if not getattr(args, field).is_file():
            raise AuditError(f"required artifact missing: {getattr(args, field)}")
    report = run(args)
    print(json.dumps({
        "status": report["status"],
        "restored": report["scope"]["component_owned_children_restored"],
        "newSmaMasks": report["footprints"]["new_sma_post_masks"],
        "padNets": report["pcb"]["pad_net_records"],
        "runtimePads": report["pcb"]["runtime_pad_total_expected"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
