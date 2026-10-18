#!/usr/bin/env python3
"""Prepare full-footprint candidates for the 48 restored SMA ground posts.

The script is read-only with respect to the EasyEDA project/checkpoint.  It
consumes the frozen Gerber audit plus the receipts written by the documented
PrimitivePad.create path, then copies each authoritative footprint block and
changes only the three new PAD bodies' ``unusedInnerLayers`` field from ``[]``
to ``[16]``.  Applying the candidates is a separate guarded API operation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_AUDIT = ROOT / "output/validation/native-missing-sma-ground-pth-audit.json"
DEFAULT_OUTPUT = ROOT / "output/native-libraries/sma-owned-post-inner-layer-candidates"
FROZEN_AUDIT_SHA256 = "7025ab3611c319c513a770dd557df1861d3e15724a11f37678c38ceeddfdfaf2"
HEX16 = re.compile(r"^[0-9a-f]{16}$")
TARGET_REFS = tuple(f"J{index}" for index in range(2, 18))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def parse_record(raw: bytes, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    line = raw.rstrip(b"\r\n")
    try:
        header_raw, body_raw = line.rstrip(b"|").split(b"||", 1)
        header = json.loads(header_raw.decode("utf-8-sig"))
        body = json.loads(body_raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"{label}: invalid native record") from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError(f"{label}: native header/body must be objects")
    return header, body


def checkpoint_blocks(path: Path) -> dict[str, list[bytes]]:
    result: dict[str, list[bytes]] = {}
    current_uuid: str | None = None
    current: list[bytes] = []
    with zipfile.ZipFile(path) as archive:
        for line_number, raw in enumerate(archive.read(MEMBER).splitlines(keepends=True), 1):
            if not raw.strip():
                continue
            header, body = parse_record(raw, f"{path.name}:{line_number}")
            if header.get("type") == "DOCHEAD":
                if current_uuid is not None:
                    result[current_uuid] = current
                current_uuid = str(body.get("uuid") or "")
                current = []
            if current_uuid is None:
                raise ValueError(f"{path.name}: record before DOCHEAD")
            current.append(raw)
    if current_uuid is not None:
        result[current_uuid] = current
    return result


def keyed(lines: Sequence[bytes], label: str) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for index, raw in enumerate(lines, 1):
        header, body = parse_record(raw, f"{label}:{index}")
        key = (str(header.get("type") or ""), str(header.get("id") or ""))
        if key in result:
            raise AssertionError(f"{label}: duplicate record {key}")
        result[key] = (header, body)
    return result


def close(left: Any, right: Any, tolerance: float = 0.00025) -> bool:
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"non-numeric geometry {left!r}/{right!r}") from exc
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance


def verify_added_body(reference: str, suffix: str, body: dict[str, Any], center: Sequence[float]) -> None:
    if (
        body.get("groupId") != 0
        or body.get("netName") != ""
        or body.get("layerId") != 12
        or str(body.get("num")) != "2"
        or body.get("padAngle") != 0
        or body.get("specialPad") != []
        or body.get("plated") is not True
        or body.get("unusedInnerLayers") != []
        or not close(body.get("centerX"), center[0], 0.00011)
        or not close(body.get("centerY"), center[1], 0.00011)
    ):
        raise AssertionError(f"{reference}/{suffix}: restored PAD identity/center contract changed")
    hole = body.get("hole")
    pad = body.get("defaultPad")
    if not (
        isinstance(hole, dict)
        and hole.get("holeType") == "ROUND"
        and close(hole.get("width"), 59.055118)
        and close(hole.get("height"), 59.055118)
        and isinstance(pad, dict)
        and pad.get("padType") == "ELLIPSE"
        and close(pad.get("width"), 98.425197)
        and close(pad.get("height"), 98.425197)
    ):
        raise AssertionError(f"{reference}/{suffix}: restored copper/drill geometry changed")


def serialize(header: dict[str, Any], body: dict[str, Any]) -> bytes:
    return f"{compact(header)}||{compact(body)}|\n".encode("utf-8")


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    audit_path = args.audit.resolve()
    output = safe_output(args.output)
    if sha256_file(audit_path) != FROZEN_AUDIT_SHA256:
        raise AssertionError("frozen SMA physical-post audit hash changed")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    footprints = {item["reference"]: item for item in audit["footprints"]}
    if tuple(sorted(footprints, key=lambda item: int(item[1:]))) != TARGET_REFS:
        raise AssertionError("frozen SMA footprint scope changed")
    blocks = checkpoint_blocks(checkpoint)
    if output.exists() and any(output.iterdir()):
        raise AssertionError(f"candidate output already contains files: {output}")
    output.mkdir(parents=True, exist_ok=True)

    plan_rows: list[dict[str, Any]] = []
    for reference in TARGET_REFS:
        evidence = footprints[reference]
        uuid = str(evidence["footprint_uuid"])
        if uuid not in blocks:
            raise AssertionError(f"{reference}: actual footprint {uuid} missing from checkpoint")
        receipt_path = ROOT / f"output/validation/native-{reference}-missing-owned-pad-create-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not (
            receipt.get("reference") == reference
            and receipt.get("uuid") == uuid
            and receipt.get("expected") is True
            and receipt.get("saved") is True
            and len(receipt.get("added") or []) == 3
        ):
            raise AssertionError(f"{reference}: direct-create receipt is not a successful 3-PAD proof")
        added_by_id = {str(item["id"]): item for item in receipt["added"]}
        if len(added_by_id) != 3 or any(not HEX16.fullmatch(suffix) for suffix in added_by_id):
            raise AssertionError(f"{reference}: receipt child IDs are invalid or duplicated")

        original = keyed(blocks[uuid], f"checkpoint:{reference}")
        pads = {record_id: body for (kind, record_id), (_, body) in original.items() if kind == "PAD"}
        if len(pads) != 5 or set(added_by_id) - set(pads):
            raise AssertionError(f"{reference}: expected 5 PADs including the 3 receipt children")
        central = pads.get(str(evidence["current_pad2_record_id"]))
        if central is None or str(central.get("num")) != "2" or central.get("unusedInnerLayers") != [16]:
            raise AssertionError(f"{reference}: existing e2 inner-layer repair changed")

        expected_centers = {
            tuple(float(value) for value in item["footprint_local_center_mil_y_up"])
            for item in audit["missing_pad_records"]
            if item["reference"] == reference
        }
        receipt_centers = {
            (float(item["x"]), float(item["y"])) for item in added_by_id.values()
        }
        if len(expected_centers) != 3 or not all(
            any(close(a[0], b[0], 0.00011) and close(a[1], b[1], 0.00011) for b in receipt_centers)
            for a in expected_centers
        ):
            raise AssertionError(f"{reference}: receipt centers differ from frozen Gerber evidence")
        for suffix, receipt_row in added_by_id.items():
            verify_added_body(reference, suffix, pads[suffix], [receipt_row["x"], receipt_row["y"]])

        candidate_lines: list[bytes] = []
        modifications: list[dict[str, Any]] = []
        for index, raw in enumerate(blocks[uuid], 1):
            header, body = parse_record(raw, f"{reference}:{index}")
            suffix = str(header.get("id") or "")
            if header.get("type") == "PAD" and suffix in added_by_id:
                changed = dict(body)
                changed["unusedInnerLayers"] = [16]
                candidate_lines.append(serialize(header, changed))
                modifications.append({
                    "record_id": suffix,
                    "pad_number": "2",
                    "local_center_mil_y_up": [body["centerX"], body["centerY"]],
                    "before_unused_inner_layers": [],
                    "after_unused_inner_layers": [16],
                    "hole": body["hole"],
                    "default_pad": body["defaultPad"],
                    "plated": body["plated"],
                })
            else:
                candidate_lines.append(raw if raw.endswith((b"\n", b"\r")) else raw + b"\n")
        candidate = b"".join(candidate_lines)
        final_records = keyed(candidate.splitlines(keepends=True), f"candidate:{reference}")
        if set(final_records) != set(original):
            raise AssertionError(f"{reference}: candidate record identity/type set changed")
        changed_bodies = []
        for key in original:
            if original[key][1] != final_records[key][1]:
                changed_bodies.append(key)
        if set(changed_bodies) != {("PAD", suffix) for suffix in added_by_id}:
            raise AssertionError(f"{reference}: candidate changed unsupported bodies {changed_bodies}")
        if len(modifications) != 3:
            raise AssertionError(f"{reference}: expected three exact inner-layer changes")

        candidate_path = output / f"{reference}_{uuid}.epru"
        candidate_path.write_bytes(candidate)
        plan_rows.append({
            "reference": reference,
            "footprint_uuid": uuid,
            "component_id": evidence["component_id"],
            "record_count": len(original),
            "record_type_counts": dict(sorted(Counter(key[0] for key in original).items())),
            "original_block_sha256": sha256_bytes(b"".join(blocks[uuid])),
            "receipt": str(receipt_path.resolve().relative_to(ROOT.resolve())),
            "receipt_sha256": sha256_file(receipt_path),
            "candidate": str(candidate_path.resolve().relative_to(ROOT.resolve())),
            "candidate_sha256": sha256_bytes(candidate),
            "modifications": sorted(modifications, key=lambda item: item["record_id"]),
        })

    manifest = {
        "schema": "stm32h747-sma-owned-post-inner-layer-candidates-v1",
        "status": "static-candidates-not-applied",
        "inputs": {
            "checkpoint": {"path": str(checkpoint), "sha256": sha256_file(checkpoint)},
            "frozen_sma_audit": {"path": str(audit_path), "sha256": FROZEN_AUDIT_SHA256},
        },
        "scope": {
            "references": list(TARGET_REFS),
            "footprints": 16,
            "existing_pad_bodies_changed": 0,
            "new_pad_bodies_changed": 48,
            "only_field_changed": "PAD.body.unusedInnerLayers",
            "before": [],
            "after": [16],
        },
        "candidates": plan_rows,
        "checks": {
            "all_receipts_successful": True,
            "all_new_child_ids_are_native_16hex": True,
            "all_centers_match_frozen_gerber_evidence": True,
            "all_copper_and_drill_geometry_preserved": True,
            "all_record_identity_and_type_sets_preserved": True,
            "only_48_new_pad_unused_inner_layers_changed": True,
        },
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "pass",
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "footprints": 16,
        "modified_new_pad_bodies": 48,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
