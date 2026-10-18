"""Verify the final U5/U7 owned thermal-PTH restoration without EasyEDA writes.

The verifier consumes saved/static artifacts only.  It never imports an EDA
bridge module and never calls an EasyEDA API.  A successful run proves that:

* the authoritative U5/U7 FOOTPRINT blocks retain every pre-existing record
  body, apart from normal DOCHEAD metadata, and gain exactly four PAD records
  each;
* the eight new records are duplicate-number, multilayer, plated 0.3 mm holes
  with 0.6 mm round copper at the Gerber-proved local coordinates;
* the reopened PCB source contains a distinct GND PAD_NET for every dynamically
  generated child suffix (1184 PAD_NET records total), with no VIA/PAD fallback;
* the cold-reopened runtime has 1188 pads and the eight owned children at the
  exact Gerber world coordinates, all on GND; and
* Connection Error falls from the immutable pre-fix 16 to zero, while no final
  non-clearance DRC category remains.

Expected input schemas
----------------------

``--before-checkpoint`` and ``--final-checkpoint`` are EasyEDA ``.epro2`` ZIP
archives containing ``STM32H747_MCU_BOARD_v19.epru``.  ``--pcb-source`` is the
reopened native PCB ``.epru`` text.  ``--runtime`` is the JSON emitted by
``save-and-capture-final-pcb.mjs`` and must contain ``totalPads``, ``selected``
and ``extraPads``.  Both DRC inputs are complete JSON captures with ``counts``
and ``details``.  ``--gerber-evidence`` is the frozen output of
``prepare-u5-u7-thermal-pth-pad-fix.py``; it is checked back to the individual
drill and all six copper-layer flashes rather than trusted only by filename.

Only the derived ``--report`` JSON is written.
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
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"

DEFAULT_BEFORE = ROOT / "output/checkpoints/STM32H747_after_inner_pad_shapes_20261014.epro2"
DEFAULT_PRE_FIX_DRC = ROOT / "output/validation/u5-u7-thermal-pth-pre-fix-drc.json"
DEFAULT_GERBER_EVIDENCE = ROOT / "output/validation/u5-u7-thermal-pth-pad-fix-plan.json"
DEFAULT_REPORT = ROOT / "output/validation/u5-u7-owned-thermal-pth-final-audit.json"

# These three inputs are the reviewed, immutable authority for this repair.
FROZEN_BEFORE_SHA256 = "a7150f1b8a54827ab413aa4075a700d298d811d21bd50ea79221ab850239b2ac"
FROZEN_PRE_FIX_DRC_SHA256 = "28833addfc371685d9ca26dcbbffb4922a4c82ec2a321bc11d083b568a9db722"
FROZEN_GERBER_EVIDENCE_SHA256 = "a30ed6204a499ff327ad1d10d371c335cae27fc47dfbf3a19ecb8e9a255539dd"

PCB_UUID = "0ac2a19168000d8e"
MM_TO_MIL = 1000.0 / 25.4
SOURCE_TOLERANCE_MIL = 0.00016
EVIDENCE_TOLERANCE_MM = 0.00001
RUNTIME_CENTER_TOLERANCE_MIL = 0.071
RUNTIME_SHAPE_TOLERANCE_MIL = 0.051
RUNTIME_EXACT_GETTER_TOLERANCE_MIL = 0.001

TARGETS: dict[str, dict[str, str]] = {
    "U5": {
        "footprint_uuid": "b098cceac55eab69",
        "component_id": "0c0d782d6b7f0167",
        "pad_number": "25",
        "central_record_id": "e25",
    },
    "U7": {
        "footprint_uuid": "15077d1eac66847c",
        "component_id": "ae8670f38e12646e",
        "pad_number": "33",
        "central_record_id": "e33",
    },
}

COPPER_LAYERS = ("F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu")
ALLOWED_DOCHEAD_METADATA = {"updateTime", "version", "user"}


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float = SOURCE_TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def rounded(value: Any, digits: int = 9) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def native_lines_hash(lines: Sequence[str]) -> str:
    payload = "\n".join(lines) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def input_record(path: Path) -> dict[str, Any]:
    return {"path": display_path(path), "sha256": sha256(path)}


def require_file(path: Path, label: str) -> Path:
    result = path.resolve()
    if not result.is_file():
        raise FileNotFoundError(f"{label} does not exist or is not a file: {result}")
    return result


def read_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{label}: top-level JSON value must be an object")
    return value


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        if body_text.endswith("|"):
            body_text = body_text[:-1]
        header = json.loads(header_text)
        body = json.loads(body_text)
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise ValueError(f"native record {label}:{line_number} must contain two JSON objects")
    return header, body


def read_native_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records = [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
        if raw.strip()
    ]
    seen: set[str] = set()
    for header, _ in records:
        record_id = header.get("id")
        if record_id is None:
            continue
        record_id = str(record_id)
        if record_id in seen:
            raise AssertionError(f"{path.name}: duplicate native record id {record_id!r}")
        seen.add(record_id)
    return records


def checkpoint_footprint_blocks(path: Path, member: str) -> dict[str, list[str]]:
    with zipfile.ZipFile(path) as archive:
        try:
            lines = archive.read(member).decode("utf-8-sig").splitlines()
        except KeyError as exc:
            raise AssertionError(f"{path.name}: checkpoint member missing: {member}") from exc

    result: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current_lines: list[str] = []

    def finish() -> None:
        nonlocal current_uuid, current_lines
        if current_uuid is None:
            return
        if current_uuid in result:
            raise AssertionError(f"{path.name}: duplicate FOOTPRINT block {current_uuid}")
        result[current_uuid] = current_lines

    for line_number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        header, body = parse_record(raw, f"{path.name}:{member}", line_number)
        if header.get("type") == "DOCHEAD":
            finish()
            current_uuid = str(body.get("uuid")) if body.get("docType") == "FOOTPRINT" else None
            current_lines = [raw] if current_uuid is not None else []
        elif current_uuid is not None:
            current_lines.append(raw)
    finish()
    return result


def keyed_records(
    lines: Sequence[str], label: str
) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    ids: set[str] = set()
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, label, line_number)
        kind = str(header.get("type"))
        record_id = "" if header.get("id") is None else str(header.get("id"))
        key = (kind, record_id)
        if key in result:
            raise AssertionError(f"{label}: duplicate record key {key}")
        if record_id:
            if record_id in ids:
                raise AssertionError(f"{label}: duplicate record id {record_id}")
            ids.add(record_id)
        result[key] = (header, body)
    return result


def changed_fields(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))


def verify_existing_header(
    reference: str,
    key: tuple[str, str],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any] | None:
    changed = changed_fields(before, after)
    if not changed:
        return None
    if changed != ["ticket"]:
        raise AssertionError(f"{reference} {key}: unsupported header changes {changed}")
    if not isinstance(after.get("ticket"), int):
        raise AssertionError(f"{reference} {key}: normalized ticket is not an integer")
    return {
        "type": key[0],
        "id": key[1],
        "before_ticket": before.get("ticket"),
        "after_ticket": after.get("ticket"),
    }


def verify_dochead_body(
    reference: str, before: dict[str, Any], after: dict[str, Any], footprint_uuid: str
) -> list[str]:
    changed = changed_fields(before, after)
    unsupported = sorted(set(changed) - ALLOWED_DOCHEAD_METADATA)
    if unsupported:
        raise AssertionError(f"{reference}: unsupported DOCHEAD body changes {unsupported}")
    left, right = dict(before), dict(after)
    for name in ALLOWED_DOCHEAD_METADATA:
        left.pop(name, None)
        right.pop(name, None)
    if left != right:
        raise AssertionError(f"{reference}: protected DOCHEAD body changed")
    if after.get("docType") != "FOOTPRINT" or str(after.get("uuid")) != footprint_uuid:
        raise AssertionError(f"{reference}: final DOCHEAD identity changed")
    if "updateTime" not in after or "version" not in after:
        raise AssertionError(f"{reference}: final DOCHEAD lacks updateTime/version")
    if int(after["updateTime"]) != int(after["version"]):
        raise AssertionError(f"{reference}: final DOCHEAD updateTime/version pair is inconsistent")
    return changed


def require_round_hole(hole: Any, label: str) -> None:
    if not isinstance(hole, dict) or set(hole) != {"holeType", "width", "height"}:
        raise AssertionError(f"{label}: source hole must be a canonical ROUND object")
    if hole.get("holeType") != "ROUND":
        raise AssertionError(f"{label}: source hole is not ROUND")
    if not close(hole.get("width"), 11.811) or not close(hole.get("height"), 11.811):
        raise AssertionError(f"{label}: source hole is not 0.3 mm")


def require_round_copper(default_pad: Any, label: str) -> None:
    if not isinstance(default_pad, dict) or set(default_pad) != {"padType", "width", "height"}:
        raise AssertionError(f"{label}: source copper must be a canonical ELLIPSE object")
    if default_pad.get("padType") != "ELLIPSE":
        raise AssertionError(f"{label}: source copper is not ELLIPSE")
    if not close(default_pad.get("width"), 23.622047) or not close(default_pad.get("height"), 23.622047):
        raise AssertionError(f"{label}: source copper is not 0.6 mm")


def verify_new_pad_body(
    reference: str,
    suffix: str,
    body: dict[str, Any],
    pad_number: str,
) -> None:
    label = f"{reference} added PAD {suffix}"
    required_fields = {
        "groupId", "netName", "layerId", "num", "centerX", "centerY", "padAngle",
        "hole", "defaultPad", "specialPad", "padOffsetX", "padOffsetY", "relativeAngle",
        "plated", "padType", "topSolderExpansion", "bottomSolderExpansion",
        "topPasteExpansion", "bottomPasteExpansion", "locked", "zIndex", "connectMode",
        "spokeSpace", "spokeWidth", "spokeAngle", "unusedInnerLayers", "padLen", "attrsMap",
    }
    missing = sorted(required_fields - set(body))
    if missing:
        raise AssertionError(f"{label}: missing canonical fields {missing}")
    if str(body.get("num")) != pad_number:
        raise AssertionError(f"{label}: duplicate pad number changed")
    if body.get("groupId") != 0 or body.get("netName") != "" or body.get("layerId") != 12:
        raise AssertionError(f"{label}: group/library-net/multilayer contract changed")
    if body.get("padAngle") != 0 or body.get("relativeAngle") != 0:
        raise AssertionError(f"{label}: unexpected rotation")
    if body.get("padOffsetX") != 0 or body.get("padOffsetY") != 0:
        raise AssertionError(f"{label}: unexpected pad offset")
    if body.get("plated") is not True or body.get("padType") != "NORMAL":
        raise AssertionError(f"{label}: pad is not a normal plated pad")
    if body.get("specialPad") != [] or body.get("unusedInnerLayers") != []:
        raise AssertionError(f"{label}: added pad has special/unused-layer overrides")
    if body.get("locked") is not False or body.get("attrsMap") != {}:
        raise AssertionError(f"{label}: locked/attribute state changed")
    if body.get("padLen") != 0 or not isinstance(body.get("zIndex"), int):
        raise AssertionError(f"{label}: zIndex/padLen is non-canonical")
    for name in (
        "topSolderExpansion", "bottomSolderExpansion", "topPasteExpansion",
        "bottomPasteExpansion", "connectMode", "spokeSpace", "spokeWidth", "spokeAngle",
    ):
        if body.get(name) is not None:
            raise AssertionError(f"{label}: unexpected {name} override")
    require_round_hole(body.get("hole"), label)
    require_round_copper(body.get("defaultPad"), label)


def evidence_contract(evidence: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    footprints = evidence.get("footprints")
    if not isinstance(footprints, list):
        raise AssertionError("Gerber evidence: footprints must be an array")
    by_reference = {
        str(item.get("reference")): item for item in footprints if isinstance(item, dict)
    }
    if set(by_reference) != set(TARGETS):
        raise AssertionError(f"Gerber evidence: target set changed: {sorted(by_reference)}")

    expected: dict[str, list[dict[str, Any]]] = {}
    board_min_samples: list[list[float]] = []
    evidence_reports: list[dict[str, Any]] = []

    for reference, target in TARGETS.items():
        item = by_reference[reference]
        if str(item.get("actual_project_library_uuid")) != target["footprint_uuid"]:
            raise AssertionError(f"Gerber evidence: {reference} footprint UUID changed")
        if str(item.get("pad_number")) != target["pad_number"]:
            raise AssertionError(f"Gerber evidence: {reference} pad number changed")
        center_mm = [finite(value) for value in item.get("top_exposed_pad_center_mm", [])]
        if len(center_mm) != 2:
            raise AssertionError(f"Gerber evidence: {reference} center must contain two numbers")
        extras = item.get("extra_thermal_pths")
        additions = item.get("added_pad_records")
        if not isinstance(extras, list) or len(extras) != 4:
            raise AssertionError(f"Gerber evidence: {reference} must contain four extra PTHs")
        if not isinstance(additions, list) or len(additions) != 4:
            raise AssertionError(f"Gerber evidence: {reference} must contain four local pad rows")

        rows: list[dict[str, Any]] = []
        for index, (extra, addition) in enumerate(zip(extras, additions, strict=True), 1):
            if not isinstance(extra, dict) or not isinstance(addition, dict):
                raise AssertionError(f"Gerber evidence: {reference} row {index} is not an object")
            source_mm = [finite(value) for value in extra.get("source_at_mm", [])]
            world_mil = [finite(value) for value in extra.get("native_world_center_mil_y_up", [])]
            local_mil = [finite(value) for value in addition.get("footprint_local_center_mil_y_up", [])]
            if len(source_mm) != 2 or len(world_mil) != 2 or len(local_mil) != 2:
                raise AssertionError(f"Gerber evidence: {reference} row {index} coordinate shape changed")
            computed_local = [
                (source_mm[0] - center_mm[0]) * MM_TO_MIL,
                (source_mm[1] - center_mm[1]) * MM_TO_MIL,
            ]
            if math.dist(computed_local, local_mil) > SOURCE_TOLERANCE_MIL:
                raise AssertionError(f"Gerber evidence: {reference} row {index} local transform changed")
            board_min_samples.append([
                source_mm[0] - world_mil[0] / MM_TO_MIL,
                source_mm[1] - world_mil[1] / MM_TO_MIL,
            ])

            drill = extra.get("drill")
            if not isinstance(drill, dict):
                raise AssertionError(f"Gerber evidence: {reference} row {index} lacks drill proof")
            if (
                drill.get("tool") != "T4"
                or not close(drill.get("diameterMm"), 0.3, 0.000001)
                or drill.get("function") != "Plated,PTH,ComponentDrill"
                or drill.get("plated") is not True
            ):
                raise AssertionError(f"Gerber evidence: {reference} row {index} drill contract changed")
            if math.dist([finite(value) for value in drill.get("atMm", [])], source_mm) > EVIDENCE_TOLERANCE_MM:
                raise AssertionError(f"Gerber evidence: {reference} row {index} drill coordinate changed")

            copper = extra.get("copper_by_layer")
            if not isinstance(copper, dict) or set(copper) != set(COPPER_LAYERS):
                raise AssertionError(f"Gerber evidence: {reference} row {index} six-layer proof changed")
            for layer in COPPER_LAYERS:
                flash = copper[layer]
                if (
                    not isinstance(flash, dict)
                    or flash.get("polarity") != "dark"
                    or flash.get("template") != "C"
                    or flash.get("params_mm") != [0.6]
                    or flash.get("aperture_function") != "ComponentPad"
                    or (flash.get("attrs") or {}).get("N") != "GND"
                ):
                    raise AssertionError(
                        f"Gerber evidence: {reference} row {index} {layer} flash contract changed"
                    )
                if layer in {"F.Cu", "B.Cu"} and (flash.get("attrs") or {}).get("P") != f",{target['pad_number']}":
                    raise AssertionError(
                        f"Gerber evidence: {reference} row {index} {layer} pin attribute changed"
                    )
                if math.dist([finite(value) for value in flash.get("at_mm", [])], source_mm) > EVIDENCE_TOLERANCE_MM:
                    raise AssertionError(
                        f"Gerber evidence: {reference} row {index} {layer} coordinate changed"
                    )
            if extra.get("existing_route_via_matches") != 0:
                raise AssertionError(f"Gerber evidence: {reference} row {index} became a route VIA")

            rows.append({
                "source_mm": source_mm,
                "local_mil_y_up": local_mil,
                "world_mil_y_up": world_mil,
            })

        if len({tuple(row["local_mil_y_up"]) for row in rows}) != 4:
            raise AssertionError(f"Gerber evidence: {reference} local coordinates are not unique")
        if len({tuple(row["world_mil_y_up"]) for row in rows}) != 4:
            raise AssertionError(f"Gerber evidence: {reference} world coordinates are not unique")
        expected[reference] = rows
        evidence_reports.append({
            "reference": reference,
            "footprint_uuid": target["footprint_uuid"],
            "component_id": target["component_id"],
            "pad_number": target["pad_number"],
            "exposed_pad_center_mm": center_mm,
            "thermal_pths": rows,
            "drill": "T4 0.3 mm Plated,PTH,ComponentDrill",
            "copper": "0.6 mm dark ComponentPad on GND across six copper layers",
        })

    board_min = board_min_samples[0]
    for sample in board_min_samples[1:]:
        if math.dist(sample, board_min) > EVIDENCE_TOLERANCE_MM:
            raise AssertionError("Gerber evidence: inconsistent board-minimum world transform")
    for reference, rows in expected.items():
        for row in rows:
            computed_world = [
                (row["source_mm"][0] - board_min[0]) * MM_TO_MIL,
                (row["source_mm"][1] - board_min[1]) * MM_TO_MIL,
            ]
            if math.dist(computed_world, row["world_mil_y_up"]) > SOURCE_TOLERANCE_MIL:
                raise AssertionError(f"Gerber evidence: {reference} world transform changed")

    totals = evidence.get("totals") or {}
    if (
        totals.get("omitted_extra_component_pths") != 8
        or totals.get("raw_copper_flashes_proved") != 48
        or totals.get("post_special_pad_connection_findings") != 16
    ):
        raise AssertionError("Gerber evidence: reviewed 8-PTH/48-flash/Connection16 totals changed")
    return expected, {
        "board_source_minimum_mm": [rounded(value, 9) for value in board_min],
        "footprints": evidence_reports,
        "totals": {
            "plated_component_drills": 8,
            "six_layer_component_pad_flashes": 48,
            "pre_fix_connection_findings": 16,
        },
    }


def match_expected_geometry(
    reference: str,
    suffix: str,
    body: dict[str, Any],
    available: list[dict[str, Any]],
) -> dict[str, Any]:
    actual = [finite(body.get("centerX")), finite(body.get("centerY"))]
    matches = [
        row for row in available
        if math.dist(actual, row["local_mil_y_up"]) <= SOURCE_TOLERANCE_MIL
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{reference} added PAD {suffix}: expected one exact Gerber local center, got {len(matches)}"
        )
    match = matches[0]
    available.remove(match)
    return match


def verify_footprint_block(
    reference: str,
    target: dict[str, str],
    before_lines: Sequence[str],
    final_lines: Sequence[str],
    expected_geometry: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    before = keyed_records(before_lines, f"before:{reference}")
    final = keyed_records(final_lines, f"final:{reference}")
    before_keys, final_keys = set(before), set(final)
    missing = sorted(before_keys - final_keys)
    if missing:
        raise AssertionError(f"{reference}: pre-existing footprint records were deleted: {missing}")
    added_keys = sorted(final_keys - before_keys)
    if len(added_keys) != 4 or any(kind != "PAD" for kind, _ in added_keys):
        raise AssertionError(f"{reference}: expected exactly four added PAD records, got {added_keys}")

    before_counts = Counter(kind for kind, _ in before_keys)
    final_counts = Counter(kind for kind, _ in final_keys)
    if final_counts != before_counts + Counter({"PAD": 4}):
        raise AssertionError(f"{reference}: footprint record-type counts changed unexpectedly")

    reticketed: list[dict[str, Any]] = []
    dochead_metadata_changes: list[str] = []
    exact_existing_bodies = 0
    for key in sorted(before_keys):
        before_header, before_body = before[key]
        final_header, final_body = final[key]
        normalization = verify_existing_header(reference, key, before_header, final_header)
        if normalization is not None:
            reticketed.append(normalization)
        if key[0] == "DOCHEAD":
            dochead_metadata_changes = verify_dochead_body(
                reference, before_body, final_body, target["footprint_uuid"]
            )
        elif before_body != final_body:
            raise AssertionError(f"{reference} {key}: pre-existing record body changed")
        else:
            exact_existing_bodies += 1

    central_key = ("PAD", target["central_record_id"])
    if central_key not in before or central_key not in final:
        raise AssertionError(f"{reference}: central exposed PAD {central_key[1]} is missing")
    central_before = before[central_key][1]
    central_final = final[central_key][1]
    if str(central_final.get("num")) != target["pad_number"]:
        raise AssertionError(f"{reference}: central exposed pad number changed")
    if central_final.get("centerX") != 0 or central_final.get("centerY") != 0:
        raise AssertionError(f"{reference}: central exposed pad moved")
    if len(central_final.get("specialPad") or []) != 3:
        raise AssertionError(f"{reference}: central three-range specialPad repair is missing")
    if central_final.get("specialPad") != central_before.get("specialPad"):
        raise AssertionError(f"{reference}: central specialPad changed")

    available = [dict(row) for row in expected_geometry]
    added_reports: list[dict[str, Any]] = []
    z_indexes: set[int] = set()
    for key in added_keys:
        header, body = final[key]
        suffix = key[1]
        if not re.fullmatch(r"[0-9a-f]{16}", suffix):
            raise AssertionError(f"{reference}: generated child suffix is not a native 16-hex ID: {suffix}")
        if header.get("type") != "PAD" or str(header.get("id")) != suffix:
            raise AssertionError(f"{reference} {suffix}: new PAD header identity changed")
        if not isinstance(header.get("ticket"), int):
            raise AssertionError(f"{reference} {suffix}: new PAD lacks an integer ticket")
        verify_new_pad_body(reference, suffix, body, target["pad_number"])
        z_index = int(body["zIndex"])
        # The documented PrimitivePad.create path persists newly created
        # footprint children with the editor's unstacked sentinel zIndex=-1.
        # That sentinel is intentionally shared; only assigned non-negative
        # z-index values must be unique.
        if z_index != -1 and z_index in z_indexes:
            raise AssertionError(f"{reference}: added PAD zIndex {z_index} is duplicated")
        if z_index != -1:
            z_indexes.add(z_index)
        expected = match_expected_geometry(reference, suffix, body, available)
        added_reports.append({
            "suffix": suffix,
            "record_header": header,
            "pad_number": target["pad_number"],
            "local_center_mil_y_up": [finite(body["centerX"]), finite(body["centerY"])],
            "source_at_mm": expected["source_mm"],
            "expected_world_center_mil_y_up": expected["world_mil_y_up"],
            "layer_id": body["layerId"],
            "hole": body["hole"],
            "default_pad": body["defaultPad"],
            "plated": body["plated"],
            "library_net_name": body["netName"],
            "body_sha256": compact_hash(body),
        })
    if available:
        raise AssertionError(f"{reference}: not all four Gerber local centers were restored")

    same_number_before = [
        body for (kind, _), (_, body) in before.items()
        if kind == "PAD" and str(body.get("num")) == target["pad_number"]
    ]
    same_number_final = [
        body for (kind, _), (_, body) in final.items()
        if kind == "PAD" and str(body.get("num")) == target["pad_number"]
    ]
    if len(same_number_before) != 1 or len(same_number_final) != 5:
        raise AssertionError(
            f"{reference}: duplicate-number PAD inventory is not central 1 -> central+thermal 5"
        )

    added_reports.sort(key=lambda item: tuple(item["local_center_mil_y_up"]))
    report = {
        "reference": reference,
        "footprint_uuid": target["footprint_uuid"],
        "before_block_sha256": native_lines_hash(before_lines),
        "final_block_sha256": native_lines_hash(final_lines),
        "record_counts_before": dict(sorted(before_counts.items())),
        "record_counts_final": dict(sorted(final_counts.items())),
        "records_added": 4,
        "added_record_types": ["PAD"] * 4,
        "pre_existing_record_bodies_changed": 0,
        "exact_pre_existing_non_dochead_bodies": exact_existing_bodies,
        "central_pad": {
            "record_id": target["central_record_id"],
            "pad_number": target["pad_number"],
            "special_pad": central_final["specialPad"],
            "special_pad_sha256": compact_hash(central_final["specialPad"]),
        },
        "added_pads": added_reports,
        "serializer_metadata": {
            "reticketed_existing_headers": reticketed,
            "dochead_changed_fields": dochead_metadata_changes,
            "allowed_dochead_fields": sorted(ALLOWED_DOCHEAD_METADATA),
        },
    }
    return report, added_reports, central_final


def iter_drc_leaves(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield value
        for child in value.values():
            yield from iter_drc_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_drc_leaves(child)


def drc_leaf_counts(drc: dict[str, Any], label: str) -> tuple[Counter[str], list[dict[str, Any]]]:
    leaves = list(iter_drc_leaves(drc.get("details", [])))
    indexes: set[str] = set()
    counts: Counter[str] = Counter()
    for leaf in leaves:
        error_type = str(leaf.get("errorType"))
        if error_type in {"", "None"}:
            raise AssertionError(f"{label}: DRC leaf lacks errorType")
        counts[error_type] += 1
        err = leaf["explanation"]["errData"]
        index = str(leaf.get("globalIndex") or err.get("globalIndex"))
        if index in {"", "None"} or index in indexes:
            raise AssertionError(f"{label}: missing/duplicate DRC globalIndex {index!r}")
        indexes.add(index)
    return counts, leaves


def verify_pre_fix_drc(
    drc: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    expected_counts = {"Clearance Error": 2119, "Connection Error": 16}
    if drc.get("pcbUuid") != PCB_UUID or drc.get("counts") != expected_counts:
        raise AssertionError(f"pre-fix DRC identity/counts changed: {drc.get('counts')}")
    if drc.get("violations") != sum(expected_counts.values()):
        raise AssertionError("pre-fix DRC violation total changed")
    leaf_counts, leaves = drc_leaf_counts(drc, "pre-fix DRC")
    if dict(leaf_counts) != expected_counts:
        raise AssertionError(f"pre-fix DRC detail counts changed: {dict(leaf_counts)}")

    expected_fill_ids: set[str] = set()
    for footprint in evidence["footprints"]:
        for extra in footprint["extra_thermal_pths"]:
            fills = extra.get("preserved_inner_fill_primitives") or {}
            for layer in ("In1.Cu", "In2.Cu"):
                row = fills.get(layer)
                if not isinstance(row, dict) or not row.get("primitive_id"):
                    raise AssertionError(f"Gerber evidence lacks {layer} pre-fix fill identity")
                expected_fill_ids.add(str(row["primitive_id"]))
    if len(expected_fill_ids) != 16:
        raise AssertionError("Gerber evidence does not identify exactly 16 pre-fix fill objects")

    connection_leaves = [leaf for leaf in leaves if leaf.get("errorType") == "Connection Error"]
    observed_fill_ids: list[str] = []
    for leaf in connection_leaves:
        objects = [str(value) for value in leaf.get("objs", [])]
        if len(objects) != 1:
            raise AssertionError("pre-fix Connection Error must identify exactly one fill object")
        observed_fill_ids.append(objects[0])
    if len(observed_fill_ids) != 16 or set(observed_fill_ids) != expected_fill_ids:
        raise AssertionError("pre-fix Connection16 no longer equals the exact U5/U7 In1/In2 fills")
    return {
        "pcb_uuid": PCB_UUID,
        "counts": expected_counts,
        "violations": drc["violations"],
        "connection_fill_ids": sorted(expected_fill_ids),
        "connection_findings_exactly_explained": 16,
    }


def parse_pad_net_id(value: Any, label: str) -> tuple[str, str, str]:
    try:
        parsed = json.loads(str(value))
    except Exception as exc:
        raise AssertionError(f"{label}: PAD_NET id is not JSON: {value!r}") from exc
    if not isinstance(parsed, list) or len(parsed) != 4 or parsed[0] != "PAD_NET":
        raise AssertionError(f"{label}: PAD_NET id shape changed: {parsed!r}")
    return str(parsed[1]), str(parsed[2]), str(parsed[3])


def verify_pcb_source(
    path: Path,
    footprint_additions: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
    records = read_native_records(path)
    counts = Counter(str(header.get("type")) for header, _ in records)
    required_counts = {"COMPONENT": 330, "PAD_NET": 1184, "VIA": 634, "PAD": 4}
    for kind, expected in required_counts.items():
        if counts[kind] != expected:
            raise AssertionError(f"reopened PCB {kind} count {counts[kind]} != {expected}")

    pcb_docheads = [
        body for header, body in records
        if header.get("type") == "DOCHEAD" and body.get("docType") == "PCB"
    ]
    if len(pcb_docheads) != 1 or str(pcb_docheads[0].get("uuid")) != PCB_UUID:
        raise AssertionError("reopened PCB DOCHEAD identity changed")

    component_ids = {
        str(header.get("id")) for header, _ in records if header.get("type") == "COMPONENT"
    }
    designators: dict[str, list[str]] = {}
    for header, body in records:
        if header.get("type") == "ATTR" and body.get("key") == "Designator":
            designators.setdefault(str(body.get("value")), []).append(str(body.get("parentId")))
    for reference, target in TARGETS.items():
        if target["component_id"] not in component_ids:
            raise AssertionError(f"reopened PCB lacks {reference} component {target['component_id']}")
        if designators.get(reference) != [target["component_id"]]:
            raise AssertionError(f"reopened PCB {reference} designator mapping changed")

    pad_nets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for header, body in records:
        if header.get("type") != "PAD_NET":
            continue
        key = parse_pad_net_id(header.get("id"), path.name)
        if key in pad_nets:
            raise AssertionError(f"reopened PCB duplicate PAD_NET identity {key}")
        pad_nets[key] = body

    target_reports: list[dict[str, Any]] = []
    for reference, target in TARGETS.items():
        suffixes = [item["suffix"] for item in footprint_additions[reference]]
        expected_suffixes = {target["central_record_id"], *suffixes}
        matching = {
            suffix: body
            for (component_id, pad_number, suffix), body in pad_nets.items()
            if component_id == target["component_id"] and pad_number == target["pad_number"]
        }
        if set(matching) != expected_suffixes:
            raise AssertionError(
                f"reopened PCB {reference}.{target['pad_number']} PAD_NET suffix set changed: "
                f"{sorted(matching)}"
            )
        for suffix, body in matching.items():
            if body.get("padNet") != "GND":
                raise AssertionError(f"reopened PCB {reference} child {suffix} is not explicitly GND")
        target_reports.append({
            "reference": reference,
            "component_id": target["component_id"],
            "pad_number": target["pad_number"],
            "central_suffix": target["central_record_id"],
            "added_suffixes": sorted(suffixes),
            "explicit_pad_net_rows": [
                {
                    "suffix": suffix,
                    "identity": ["PAD_NET", target["component_id"], target["pad_number"], suffix],
                    "pad_net": matching[suffix]["padNet"],
                }
                for suffix in sorted(matching)
            ],
        })

    expected_world = [
        item["expected_world_center_mil_y_up"]
        for rows in footprint_additions.values()
        for item in rows
    ]
    fallback_matches: list[dict[str, Any]] = []
    for header, body in records:
        if header.get("type") not in {"VIA", "PAD"}:
            continue
        if "centerX" not in body or "centerY" not in body:
            continue
        point = [finite(body["centerX"]), finite(body["centerY"])]
        if any(math.dist(point, world) <= SOURCE_TOLERANCE_MIL for world in expected_world):
            fallback_matches.append({"type": header["type"], "id": header.get("id"), "center": point})
    if fallback_matches:
        raise AssertionError(f"reopened PCB contains VIA/top-level PAD fallback at thermal centers: {fallback_matches}")

    return {
        "pcb_uuid": PCB_UUID,
        "record_type_counts": dict(sorted(counts.items())),
        "component_count": counts["COMPONENT"],
        "pad_net_count": counts["PAD_NET"],
        "route_via_count": counts["VIA"],
        "top_level_pad_count": counts["PAD"],
        "target_pad_nets": target_reports,
        "fallback_via_or_top_level_pad_matches": 0,
    }, pad_nets


def source_special_pad_as_runtime(value: Any) -> list[list[Any]]:
    if not isinstance(value, list):
        raise AssertionError("source specialPad must be an array")
    result: list[list[Any]] = []
    for row in value:
        if not isinstance(row, dict) or not isinstance(row.get("pad"), dict):
            raise AssertionError("source specialPad row shape changed")
        pad = row["pad"]
        shape = [pad.get("padType"), pad.get("width"), pad.get("height")]
        if pad.get("padType") == "RECT":
            shape.append(pad.get("radius"))
        result.append([row.get("startLayer"), row.get("endLayer"), shape])
    return result


def runtime_shape_equal(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected, strict=True):
        if not isinstance(actual_row, list) or len(actual_row) != 3:
            return False
        if actual_row[:2] != expected_row[:2]:
            return False
        actual_shape, expected_shape = actual_row[2], expected_row[2]
        if not isinstance(actual_shape, list) or len(actual_shape) != len(expected_shape):
            return False
        if actual_shape[0] != expected_shape[0]:
            return False
        if not all(
            close(left, right, RUNTIME_SHAPE_TOLERANCE_MIL)
            for left, right in zip(actual_shape[1:], expected_shape[1:], strict=True)
        ):
            return False
    return True


def require_runtime_common(
    row: dict[str, Any], reference: str, expected_id: str, pad_number: str
) -> None:
    if str(row.get("reference")) != reference:
        raise AssertionError(f"runtime {expected_id}: reference changed")
    if str(row.get("id")) != expected_id:
        raise AssertionError(f"runtime {reference}: primitive id changed")
    if str(row.get("padNumber")) != pad_number:
        raise AssertionError(f"runtime {expected_id}: pad number changed")
    if row.get("layer") != 12 or row.get("plated") is not True or row.get("net") != "GND":
        raise AssertionError(f"runtime {expected_id}: multilayer/plated/GND contract changed")


def verify_runtime(
    runtime: dict[str, Any],
    footprint_additions: dict[str, list[dict[str, Any]]],
    central_bodies: dict[str, dict[str, Any]],
    evidence_report: dict[str, Any],
    pad_nets: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    if runtime.get("pcbUuid") != PCB_UUID:
        raise AssertionError("runtime PCB UUID changed")
    if runtime.get("totalPads") != 1188:
        raise AssertionError(f"runtime totalPads {runtime.get('totalPads')} != 1188")
    selected = runtime.get("selected")
    extras = runtime.get("extraPads")
    if not isinstance(selected, list) or len(selected) != 2:
        raise AssertionError("runtime selected must contain the two central exposed pads")
    if not isinstance(extras, list) or len(extras) != 8:
        raise AssertionError("runtime extraPads must contain the eight restored thermal PTHs")
    if not all(isinstance(row, dict) for row in selected + extras):
        raise AssertionError("runtime selected/extraPads rows must be objects")

    evidence_centers = {
        item["reference"]: item["exposed_pad_center_mm"]
        for item in evidence_report["footprints"]
    }
    board_min = evidence_report["board_source_minimum_mm"]
    selected_by_id = {str(row.get("id")): row for row in selected}
    if len(selected_by_id) != 2:
        raise AssertionError("runtime central primitive IDs are not unique")
    central_reports: list[dict[str, Any]] = []
    for reference, target in TARGETS.items():
        expected_id = target["component_id"] + target["central_record_id"]
        row = selected_by_id.get(expected_id)
        if row is None:
            raise AssertionError(f"runtime central pad missing: {reference} {expected_id}")
        require_runtime_common(row, reference, expected_id, target["pad_number"])
        body = central_bodies[reference]
        expected_special = source_special_pad_as_runtime(body.get("specialPad"))
        if not runtime_shape_equal(row.get("specialPad"), expected_special):
            raise AssertionError(f"runtime {reference}: central specialPad differs from final source")
        hole = row.get("hole")
        if (
            not isinstance(hole, list) or len(hole) != 2 or hole[0] != "ROUND"
            or not close(hole[1], 11.811, RUNTIME_EXACT_GETTER_TOLERANCE_MIL)
        ):
            raise AssertionError(f"runtime {reference}: central hole changed")
        source_pad = body.get("defaultPad") or {}
        actual_pad = row.get("pad")
        expected_pad = [source_pad.get("padType"), source_pad.get("width"), source_pad.get("height")]
        if source_pad.get("padType") == "RECT":
            expected_pad.append(source_pad.get("radius"))
        if (
            not isinstance(actual_pad, list) or len(actual_pad) != len(expected_pad)
            or actual_pad[0] != expected_pad[0]
            or not all(
                close(left, right, RUNTIME_SHAPE_TOLERANCE_MIL)
                for left, right in zip(actual_pad[1:], expected_pad[1:], strict=True)
            )
        ):
            raise AssertionError(f"runtime {reference}: central default pad changed")
        center_mm = evidence_centers[reference]
        expected_world = [
            (center_mm[0] - board_min[0]) * MM_TO_MIL,
            (center_mm[1] - board_min[1]) * MM_TO_MIL,
        ]
        actual_world = [finite(row.get("x")), finite(row.get("y"))]
        center_error = math.dist(actual_world, expected_world)
        if center_error > RUNTIME_CENTER_TOLERANCE_MIL:
            raise AssertionError(f"runtime {reference}: central world center error {center_error} mil")
        central_reports.append({
            "reference": reference,
            "runtime_id": expected_id,
            "world_center_mil_y_up": actual_world,
            "expected_world_center_mil_y_up": expected_world,
            "center_error_mil": rounded(center_error),
            "net": row["net"],
            "special_pad": row["specialPad"],
        })

    extras_by_id = {str(row.get("id")): row for row in extras}
    if len(extras_by_id) != 8:
        raise AssertionError("runtime restored thermal primitive IDs are not unique")
    expected_ids = {
        TARGETS[reference]["component_id"] + item["suffix"]
        for reference, rows in footprint_additions.items()
        for item in rows
    }
    if set(extras_by_id) != expected_ids:
        raise AssertionError(
            f"runtime restored child identity set changed: missing={sorted(expected_ids - set(extras_by_id))}, "
            f"unexpected={sorted(set(extras_by_id) - expected_ids)}"
        )

    extra_reports: list[dict[str, Any]] = []
    for reference, rows in footprint_additions.items():
        target = TARGETS[reference]
        for source_row in rows:
            suffix = source_row["suffix"]
            runtime_id = target["component_id"] + suffix
            row = extras_by_id[runtime_id]
            require_runtime_common(row, reference, runtime_id, target["pad_number"])
            if row.get("specialPad") != []:
                raise AssertionError(f"runtime {runtime_id}: unexpected specialPad override")
            hole = row.get("hole")
            if (
                not isinstance(hole, list) or len(hole) != 2 or hole[0] != "ROUND"
                or not close(hole[1], 11.811, RUNTIME_EXACT_GETTER_TOLERANCE_MIL)
            ):
                raise AssertionError(f"runtime {runtime_id}: restored hole is not ROUND 0.3 mm")
            pad = row.get("pad")
            if (
                not isinstance(pad, list) or len(pad) != 3 or pad[0] != "ELLIPSE"
                or not close(pad[1], 23.6, RUNTIME_EXACT_GETTER_TOLERANCE_MIL)
                or not close(pad[2], 23.6, RUNTIME_EXACT_GETTER_TOLERANCE_MIL)
            ):
                raise AssertionError(f"runtime {runtime_id}: restored copper is not getter-exact 0.6 mm")
            expected_world = source_row["expected_world_center_mil_y_up"]
            actual_world = [finite(row.get("x")), finite(row.get("y"))]
            center_error = math.dist(actual_world, expected_world)
            if center_error > RUNTIME_CENTER_TOLERANCE_MIL:
                raise AssertionError(f"runtime {runtime_id}: Gerber world center error {center_error} mil")
            pad_net_key = (target["component_id"], target["pad_number"], suffix)
            if pad_nets.get(pad_net_key, {}).get("padNet") != "GND":
                raise AssertionError(f"runtime {runtime_id}: explicit persisted child PAD_NET is not GND")
            extra_reports.append({
                "reference": reference,
                "runtime_id": runtime_id,
                "child_suffix": suffix,
                "pad_number": target["pad_number"],
                "source_at_mm": source_row["source_at_mm"],
                "local_center_mil_y_up": source_row["local_center_mil_y_up"],
                "expected_world_center_mil_y_up": expected_world,
                "runtime_world_center_mil_y_up": actual_world,
                "center_error_mil": rounded(center_error),
                "layer": row["layer"],
                "hole": hole,
                "plated": row["plated"],
                "copper": pad,
                "runtime_net": row["net"],
                "persisted_pad_net": "GND",
            })
    extra_reports.sort(key=lambda item: (item["reference"], tuple(item["local_center_mil_y_up"])))
    return {
        "pcb_uuid": PCB_UUID,
        "stage": runtime.get("stage"),
        "total_pads": runtime["totalPads"],
        "central_pads": central_reports,
        "restored_owned_thermal_pths": extra_reports,
        "restored_count": len(extra_reports),
        "max_world_center_error_mil": max(item["center_error_mil"] for item in extra_reports),
    }


def verify_final_drc(drc: dict[str, Any], pre_fix: dict[str, Any]) -> dict[str, Any]:
    if drc.get("pcbUuid") != PCB_UUID:
        raise AssertionError("final DRC PCB UUID changed")
    counts = drc.get("counts")
    if not isinstance(counts, dict):
        raise AssertionError("final DRC counts must be an object")
    numeric_counts = {str(name): int(value) for name, value in counts.items()}
    if numeric_counts.get("Connection Error", 0) != 0:
        raise AssertionError(f"final Connection Error is not zero: {numeric_counts}")
    non_clearance = sorted(
        name for name, count in numeric_counts.items() if count > 0 and name != "Clearance Error"
    )
    if non_clearance:
        raise AssertionError(f"final DRC contains non-clearance categories: {non_clearance}")
    positive_counts = {name: count for name, count in numeric_counts.items() if count > 0}
    violations = int(drc.get("violations", -1))
    if violations != sum(positive_counts.values()):
        raise AssertionError("final DRC violations does not equal the positive category total")
    leaf_counts, _ = drc_leaf_counts(drc, "final DRC")
    if dict(leaf_counts) != positive_counts:
        raise AssertionError(
            f"final DRC detail/category counts disagree: details={dict(leaf_counts)}, counts={positive_counts}"
        )
    return {
        "pcb_uuid": PCB_UUID,
        "before_counts": pre_fix["counts"],
        "before_connection_errors": pre_fix["counts"]["Connection Error"],
        "final_counts": numeric_counts,
        "final_violations": violations,
        "final_connection_errors": 0,
        "connection_delta": -16,
        "non_clearance_categories": [],
        "clearance_count_delta": numeric_counts.get("Clearance Error", 0) - pre_fix["counts"]["Clearance Error"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Statically verify the final eight U5/U7 owned thermal PTHs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--before-checkpoint", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--final-checkpoint", type=Path, required=True)
    parser.add_argument("--pcb-source", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--final-drc", type=Path, required=True)
    parser.add_argument("--pre-fix-drc", type=Path, default=DEFAULT_PRE_FIX_DRC)
    parser.add_argument("--gerber-evidence", type=Path, default=DEFAULT_GERBER_EVIDENCE)
    parser.add_argument("--checkpoint-member", default=CHECKPOINT_MEMBER)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    before_path = require_file(args.before_checkpoint, "before checkpoint")
    final_checkpoint_path = require_file(args.final_checkpoint, "final checkpoint")
    pcb_source_path = require_file(args.pcb_source, "reopened PCB source")
    runtime_path = require_file(args.runtime, "runtime layered-pad snapshot")
    final_drc_path = require_file(args.final_drc, "final DRC snapshot")
    pre_fix_drc_path = require_file(args.pre_fix_drc, "immutable pre-fix DRC snapshot")
    evidence_path = require_file(args.gerber_evidence, "Gerber evidence plan")
    report_path = args.report.resolve()

    frozen_actual = {
        "before_checkpoint": sha256(before_path),
        "pre_fix_drc": sha256(pre_fix_drc_path),
        "gerber_evidence": sha256(evidence_path),
    }
    frozen_expected = {
        "before_checkpoint": FROZEN_BEFORE_SHA256,
        "pre_fix_drc": FROZEN_PRE_FIX_DRC_SHA256,
        "gerber_evidence": FROZEN_GERBER_EVIDENCE_SHA256,
    }
    if frozen_actual != frozen_expected:
        raise AssertionError(
            f"authoritative frozen-input hash mismatch: actual={frozen_actual}, expected={frozen_expected}"
        )

    evidence = read_json(evidence_path, "Gerber evidence")
    expected_geometry, evidence_report = evidence_contract(evidence)
    pre_fix_drc = read_json(pre_fix_drc_path, "pre-fix DRC")
    pre_fix_report = verify_pre_fix_drc(pre_fix_drc, evidence)

    before_blocks = checkpoint_footprint_blocks(before_path, args.checkpoint_member)
    final_blocks = checkpoint_footprint_blocks(final_checkpoint_path, args.checkpoint_member)
    footprint_reports: list[dict[str, Any]] = []
    footprint_additions: dict[str, list[dict[str, Any]]] = {}
    central_bodies: dict[str, dict[str, Any]] = {}
    for reference, target in TARGETS.items():
        footprint_uuid = target["footprint_uuid"]
        if footprint_uuid not in before_blocks:
            raise AssertionError(f"before checkpoint lacks {reference} footprint {footprint_uuid}")
        if footprint_uuid not in final_blocks:
            raise AssertionError(f"final checkpoint lacks {reference} footprint {footprint_uuid}")
        footprint_report, additions, central = verify_footprint_block(
            reference,
            target,
            before_blocks[footprint_uuid],
            final_blocks[footprint_uuid],
            expected_geometry[reference],
        )
        footprint_reports.append(footprint_report)
        footprint_additions[reference] = additions
        central_bodies[reference] = central

    pcb_report, pad_nets = verify_pcb_source(pcb_source_path, footprint_additions)
    runtime = read_json(runtime_path, "runtime layered-pad snapshot")
    runtime_report = verify_runtime(
        runtime, footprint_additions, central_bodies, evidence_report, pad_nets
    )
    final_drc = read_json(final_drc_path, "final DRC")
    final_drc_report = verify_final_drc(final_drc, pre_fix_report)

    report = {
        "schema_version": 1,
        "status": "pass",
        "purpose": "Final static proof for eight U5/U7 component-owned thermal PTH pads",
        "inputs": {
            "before_checkpoint": {**input_record(before_path), "member": args.checkpoint_member},
            "final_checkpoint": {**input_record(final_checkpoint_path), "member": args.checkpoint_member},
            "reopened_pcb_source": input_record(pcb_source_path),
            "runtime_layered_pads": input_record(runtime_path),
            "final_drc": input_record(final_drc_path),
            "immutable_pre_fix_drc": input_record(pre_fix_drc_path),
            "gerber_evidence": input_record(evidence_path),
        },
        "frozen_authority": {
            "hashes_verified": frozen_expected,
            "before_checkpoint_is_after_inner_pad_shapes": True,
            "pre_fix_connection_snapshot_is_immutable": True,
        },
        "coordinate_contract": {
            "source_and_board_units": "mil, Y-up",
            "world_formula": "(Gerber source mm - board source minimum mm) * 1000/25.4",
            "local_formula": "(Gerber source mm - exposed-pad center mm) * 1000/25.4",
            "source_tolerance_mil": SOURCE_TOLERANCE_MIL,
            "runtime_center_tolerance_mil": RUNTIME_CENTER_TOLERANCE_MIL,
            "runtime_getters_quantize_xy_and_copper_to_0_1_mil": True,
        },
        "gerber_evidence": evidence_report,
        "footprints": footprint_reports,
        "reopened_pcb": pcb_report,
        "runtime": runtime_report,
        "drc": final_drc_report,
        "totals": {
            "target_footprints": 2,
            "new_owned_pad_records": sum(item["records_added"] for item in footprint_reports),
            "pre_existing_record_body_changes": sum(
                item["pre_existing_record_bodies_changed"] for item in footprint_reports
            ),
            "explicit_new_child_pad_nets": 8,
            "reopened_pcb_pad_net_records": pcb_report["pad_net_count"],
            "runtime_total_pads": runtime_report["total_pads"],
            "runtime_restored_owned_thermal_pths": runtime_report["restored_count"],
            "pre_fix_connection_errors": final_drc_report["before_connection_errors"],
            "final_connection_errors": final_drc_report["final_connection_errors"],
        },
        "checks": {
            "frozen_before_checkpoint_pre_fix_drc_and_gerber_evidence_hashes_match": True,
            "u5_u7_existing_footprint_record_bodies_preserved": True,
            "central_e25_e33_special_pad_shapes_preserved": True,
            "exactly_four_duplicate_number_pad_records_added_to_each_footprint": True,
            "all_eight_source_pads_are_round_plated_multilayer_0_3mm_hole_0_6mm_copper": True,
            "all_eight_local_centers_match_gerber": True,
            "all_eight_generated_child_suffixes_have_explicit_gnd_pad_net_records": True,
            "pcb_pad_net_count_is_1184": True,
            "no_route_via_or_top_level_pad_fallback_at_thermal_centers": True,
            "runtime_pad_count_is_1188": True,
            "runtime_has_exactly_four_owned_gnd_thermal_children_per_target": True,
            "all_eight_runtime_world_centers_match_gerber": True,
            "connection_error_16_to_0": True,
            "final_drc_has_no_non_clearance_category": True,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "status": report["status"],
        "report": display_path(report_path),
        "report_sha256": sha256(report_path),
        "totals": report["totals"],
        "drc": report["drc"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
