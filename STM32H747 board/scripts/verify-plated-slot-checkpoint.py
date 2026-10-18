"""Verify the applied CN1/CN3/CN4 plated-slot repair without EasyEDA APIs.

This read-only/static audit ties together four independent facts:

* the three authoritative project-footprint blocks changed only the intended
  13 PAD ``hole``, ``layerId`` and ``relativeAngle`` fields;
* the eight previously repaired USB-C polygon-pad paths remain byte-exact;
* the reopened native runtime reports all 13 pads as multilayer plated SLOTs
  at the Gerber world coordinates with the Gerber dimensions/rotations; and
* the native DRC connection count fell from the 29 slot-correlated findings
  captured by the repair plan to zero.

The script only reads saved artifacts and writes a derived JSON report.
"""

from __future__ import annotations

import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "output/checkpoints/STM32H747_after_usbc_pad_fix_20261014.epro2"
AFTER = ROOT / "output/checkpoints/STM32H747_after_drl_slot_fix_20261014.epro2"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
PLAN = ROOT / "output/validation/plated-slot-pad-fix-plan.json"
GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
RUNTIME = ROOT / "output/validation/native-runtime-plated-slots-after_drl_slot_fix.json"
PCB_SOURCE = ROOT / "output/validation/native-final-pcb-after_drl_slot_fix-reopened.epru"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
REPORT = ROOT / "output/validation/plated-slot-checkpoint-audit.json"

MM_TO_MIL = 1000.0 / 25.4
EXACT_TOLERANCE_MIL = 0.00016
RUNTIME_HOLE_TOLERANCE_MIL = 0.00006
RUNTIME_PAD_TOLERANCE_MIL = 0.051
RUNTIME_CENTER_TOLERANCE_MIL = 0.071

TARGETS = {
    "CN1": {"uuid": "83fb62ef25d3eef1", "component_id": "8dfdc04036ba85c3"},
    "CN3": {"uuid": "8bd1ebd7c6524c9d", "component_id": "1bb54a689e8b2f5b"},
    "CN4": {"uuid": "ae37a0fb8459ebec", "component_id": "3663918f8e6c2c4f"},
}


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float = EXACT_TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def rounded(value: Any, digits: int = 7) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        return json.loads(header_text), json.loads(body_text[:-1] if body_text.endswith("|") else body_text)
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def checkpoint_blocks(path: Path) -> dict[str, list[str]]:
    with zipfile.ZipFile(path) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current: list[str] = []
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, f"{path.name}:{MEMBER}", line_number)
        if header.get("type") == "DOCHEAD":
            if current_uuid is not None:
                result[current_uuid] = current
            current_uuid = str(body.get("uuid")) if body.get("docType") == "FOOTPRINT" else None
            current = [raw] if current_uuid is not None else []
        elif current_uuid is not None:
            current.append(raw)
    if current_uuid is not None:
        result[current_uuid] = current
    return result


def records(lines: Sequence[str], label: str) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, label, line_number)
        key = (str(header.get("type")), str(header.get("id")))
        if key in result:
            raise AssertionError(f"{label}: duplicate record key {key}")
        result[key] = (header, body)
    return result


def read_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
    ]


def assert_header_normalization(
    reference: str, key: tuple[str, str], before: dict[str, Any], after: dict[str, Any]
) -> bool:
    if before == after:
        return False
    differing = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    if differing != {"ticket"}:
        raise AssertionError(f"{reference} {key}: unsupported header changes {sorted(differing)}")
    for name in set(before) | set(after):
        if name != "ticket" and before.get(name) != after.get(name):
            raise AssertionError(f"{reference} {key}: header identity changed")
    return True


def verify_footprint(
    reference: str,
    before_lines: Sequence[str],
    after_lines: Sequence[str],
    planned: dict[str, Any],
) -> dict[str, Any]:
    before = records(before_lines, f"before:{reference}")
    after = records(after_lines, f"after:{reference}")
    if set(before) != set(after):
        raise AssertionError(f"{reference}: record identity/type set changed")
    type_counts = Counter(kind for kind, _ in after)
    if dict(type_counts) != planned["record_type_counts"]:
        raise AssertionError(f"{reference}: record type counts changed")

    planned_by_id = {str(item["record_id"]): item for item in planned["slot_pads"]}
    changed_target_ids: set[str] = set()
    reticketed: list[dict[str, Any]] = []
    dochead_updates = 0
    raw_unchanged = 0
    protected_hashes: dict[str, str] = {}

    for key in sorted(before):
        before_header, before_body = before[key]
        after_header, after_body = after[key]
        if assert_header_normalization(reference, key, before_header, after_header):
            reticketed.append({
                "type": key[0], "id": key[1],
                "before_ticket": before_header.get("ticket"), "after_ticket": after_header.get("ticket"),
            })
        if key[0] == "DOCHEAD":
            left, right = dict(before_body), dict(after_body)
            changed = sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))
            if changed != ["updateTime", "version"] or after_body.get("updateTime") != int(after_body["version"]):
                raise AssertionError(f"{reference}: unsupported DOCHEAD normalization {changed}")
            for name in changed:
                left.pop(name, None)
                right.pop(name, None)
            if left != right:
                raise AssertionError(f"{reference}: non-version DOCHEAD fields changed")
            dochead_updates += 1
            continue

        if key[0] == "PAD" and key[1] in planned_by_id:
            expected = planned_by_id[key[1]]
            changed_fields = sorted(
                name for name in set(before_body) | set(after_body)
                if before_body.get(name) != after_body.get(name)
            )
            if changed_fields != ["hole", "layerId", "relativeAngle"]:
                raise AssertionError(f"{reference} {key[1]}: changed fields {changed_fields}")
            for name in set(before_body) | set(after_body):
                if name not in changed_fields and before_body.get(name) != after_body.get(name):
                    raise AssertionError(f"{reference} {key[1]}: protected field {name} changed")
            for name in changed_fields:
                if before_body.get(name) != expected["before"].get(name):
                    raise AssertionError(f"{reference} {key[1]}: unexpected before {name}")
                if name == "hole":
                    actual_hole = after_body.get("hole") or {}
                    expected_hole = expected["after"]["hole"]
                    matches = (
                        actual_hole.get("holeType") == expected_hole["holeType"]
                        and close(actual_hole.get("width"), expected_hole["width"], RUNTIME_HOLE_TOLERANCE_MIL)
                        and close(actual_hole.get("height"), expected_hole["height"], RUNTIME_HOLE_TOLERANCE_MIL)
                    )
                else:
                    matches = after_body.get(name) == expected["after"].get(name)
                if not matches:
                    raise AssertionError(f"{reference} {key[1]}: unexpected after {name}")
            if after_body.get("plated") is not True or after_body.get("defaultPad") != expected["copper_shape_preserved"]:
                raise AssertionError(f"{reference} {key[1]}: plating/copper capsule changed")
            changed_target_ids.add(key[1])
        elif before_body != after_body:
            raise AssertionError(f"{reference} {key}: non-target body changed")
        elif before_header == after_header:
            raw_unchanged += 1

        if key[0] == "PAD":
            pad_number = str(after_body.get("num") or "")
            if pad_number in planned.get("protected_usb_polygon_path_hashes", {}):
                path = (after_body.get("defaultPad") or {}).get("path")
                digest = compact_hash(path)
                want = planned["protected_usb_polygon_path_hashes"][pad_number]
                if digest != want:
                    raise AssertionError(f"{reference} {pad_number}: USB polygon path changed")
                protected_hashes[pad_number] = digest

    if changed_target_ids != set(planned_by_id):
        raise AssertionError(f"{reference}: did not change exact planned PAD set")
    if protected_hashes != planned.get("protected_usb_polygon_path_hashes", {}):
        raise AssertionError(f"{reference}: protected USB path set changed")
    return {
        "reference": reference,
        "footprint_uuid": TARGETS[reference]["uuid"],
        "record_count": len(after),
        "record_type_counts": dict(type_counts),
        "record_identity_set_preserved": True,
        "changed_pad_records": len(changed_target_ids),
        "changed_pad_ids": sorted(changed_target_ids),
        "changed_fields": ["hole", "layerId", "relativeAngle"],
        "non_target_body_changes": 0,
        "protected_usb_polygon_path_hashes": protected_hashes,
        "serializer_normalization": {
            "reticketed_headers": reticketed,
            "dochead_version_updates": dochead_updates,
            "raw_unchanged_records": raw_unchanged,
        },
    }


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
    drc = json.loads(DRC.read_text(encoding="utf-8"))
    before_blocks = checkpoint_blocks(BEFORE)
    after_blocks = checkpoint_blocks(AFTER)
    planned_by_reference = {item["reference"]: item for item in plan["footprints"]}

    footprint_reports: list[dict[str, Any]] = []
    for reference, target in TARGETS.items():
        uuid = target["uuid"]
        if uuid not in before_blocks or uuid not in after_blocks:
            raise AssertionError(f"{reference}: authoritative footprint block missing")
        footprint_reports.append(
            verify_footprint(
                reference,
                before_blocks[uuid],
                after_blocks[uuid],
                planned_by_reference[reference],
            )
        )

    runtime_by_id = {str(item["id"]): item for item in runtime.get("slots", [])}
    if runtime.get("totalPads") != 1180 or len(runtime_by_id) != 13:
        raise AssertionError("runtime snapshot must contain totalPads=1180 and 13 selected slots")
    bounds = gerber["coordinateTransform"]["boardBoundsSourceMm"]
    board_min_x, board_min_y = finite(bounds[0]), finite(bounds[1])
    runtime_reports: list[dict[str, Any]] = []

    for reference, target in TARGETS.items():
        component_id = target["component_id"]
        planned = planned_by_reference[reference]
        for slot in planned["slot_pads"]:
            runtime_id = component_id + str(slot["record_id"])
            actual = runtime_by_id.get(runtime_id)
            if actual is None:
                raise AssertionError(f"runtime slot missing: {reference} {slot['pad_number']} ({runtime_id})")
            expected_hole = slot["after"]["hole"]
            actual_hole = actual.get("hole") or []
            # Runtime PAD.hole serializes SLOT as [type, diameter, overallLength].
            if (
                len(actual_hole) != 3 or actual_hole[0] != "SLOT"
                or not close(actual_hole[1], expected_hole["height"], RUNTIME_HOLE_TOLERANCE_MIL)
                or not close(actual_hole[2], expected_hole["width"], RUNTIME_HOLE_TOLERANCE_MIL)
            ):
                raise AssertionError(f"{reference} {slot['pad_number']}: runtime hole mismatch {actual_hole}")
            expected_angle = slot["after"]["relativeAngle"]
            if not close(actual.get("holeRotation"), expected_angle, RUNTIME_HOLE_TOLERANCE_MIL):
                raise AssertionError(f"{reference} {slot['pad_number']}: runtime hole rotation mismatch")
            if actual.get("layer") != 12 or actual.get("plated") is not True:
                raise AssertionError(f"{reference} {slot['pad_number']}: slot is not plated multilayer")

            expected_pad = slot["copper_shape_preserved"]
            actual_pad = actual.get("pad") or []
            if (
                len(actual_pad) != 4 or actual_pad[0] != "RECT"
                or not close(actual_pad[1], expected_pad["width"], RUNTIME_PAD_TOLERANCE_MIL)
                or not close(actual_pad[2], expected_pad["height"], RUNTIME_PAD_TOLERANCE_MIL)
                or not close(actual_pad[3], expected_pad["radius"], RUNTIME_PAD_TOLERANCE_MIL)
            ):
                raise AssertionError(f"{reference} {slot['pad_number']}: runtime copper mismatch {actual_pad}")

            midpoint = slot["excellon"]["midpointMm"]
            expected_world = [
                (finite(midpoint[0]) - board_min_x) * MM_TO_MIL,
                (finite(midpoint[1]) - board_min_y) * MM_TO_MIL,
            ]
            actual_world = [finite(actual["x"]), finite(actual["y"])]
            center_error = math.dist(expected_world, actual_world)
            if center_error > RUNTIME_CENTER_TOLERANCE_MIL:
                raise AssertionError(
                    f"{reference} {slot['pad_number']}: runtime center error {center_error} mil"
                )
            runtime_reports.append({
                "reference": reference,
                "pad_number": str(slot["pad_number"]),
                "runtime_id": runtime_id,
                "gerber_tool": slot["excellon"]["tool"],
                "gerber_route_start_mm": slot["excellon"]["startMm"],
                "gerber_route_end_mm": slot["excellon"]["endMm"],
                "gerber_midpoint_mm": midpoint,
                "gerber_world_center_mil_y_up": [rounded(value, 6) for value in expected_world],
                "runtime_world_center_mil_y_up": actual_world,
                "runtime_center_error_mil": rounded(center_error, 9),
                "expected_native_hole": expected_hole,
                "runtime_hole": actual_hole,
                "expected_rotation_deg": expected_angle,
                "runtime_rotation_deg": actual["holeRotation"],
                "runtime_layer": actual["layer"],
                "runtime_plated": actual["plated"],
                "expected_copper": expected_pad,
                "runtime_copper": actual_pad,
            })

    pcb_records = read_records(PCB_SOURCE)
    pcb_counts = Counter(str(header.get("type")) for header, _ in pcb_records)
    if pcb_counts["COMPONENT"] != 330 or pcb_counts["PAD_NET"] != 1176 or pcb_counts["PAD"] != 4:
        raise AssertionError(f"reopened PCB protected counts changed: {dict(pcb_counts)}")

    if drc.get("violations") != 2195 or drc.get("counts") != {"Clearance Error": 2195}:
        raise AssertionError(f"post-slot DRC is not the expected clearance-only result: {drc.get('counts')}")
    old_connections = plan["drc_connection_correlation"]["connection_error_count"]
    if old_connections != 29 or plan["drc_connection_correlation"]["matched_to_slot_centers"] != 29:
        raise AssertionError("repair plan does not preserve the 29/29 pre-fix correlation proof")

    max_center_error = max(item["runtime_center_error_mil"] for item in runtime_reports)
    report = {
        "status": "pass",
        "purpose": "Post-apply proof for 13 Gerber-routed plated slots in CN1/CN3/CN4",
        "inputs": {
            "before_checkpoint": {"path": str(BEFORE.relative_to(ROOT)), "sha256": sha256(BEFORE)},
            "after_checkpoint": {"path": str(AFTER.relative_to(ROOT)), "sha256": sha256(AFTER)},
            "repair_plan": {"path": str(PLAN.relative_to(ROOT)), "sha256": sha256(PLAN)},
            "gerber_manifest": {"path": str(GERBER.relative_to(ROOT)), "sha256": sha256(GERBER)},
            "runtime_slot_snapshot": {"path": str(RUNTIME.relative_to(ROOT)), "sha256": sha256(RUNTIME)},
            "reopened_pcb_source": {"path": str(PCB_SOURCE.relative_to(ROOT)), "sha256": sha256(PCB_SOURCE)},
            "post_fix_drc": {"path": str(DRC.relative_to(ROOT)), "sha256": sha256(DRC)},
        },
        "coordinate_contract": {
            "board": "mil, Y-up",
            "world_center": "(Gerber midpoint mm - board source minimum mm) * 1000/25.4",
            "runtime_hole_array": "[SLOT, toolDiameterMil, overallLengthMil]",
        },
        "footprints": footprint_reports,
        "runtime_slots": runtime_reports,
        "reopened_pcb": {
            "record_type_counts": dict(pcb_counts),
            "component_count": pcb_counts["COMPONENT"],
            "pad_net_count": pcb_counts["PAD_NET"],
            "top_level_pad_count": pcb_counts["PAD"],
            "runtime_total_pad_count": runtime["totalPads"],
        },
        "drc": {
            "before_connection_errors": old_connections,
            "before_errors_matched_to_slot_centers": 29,
            "after_connection_errors": 0,
            "after_counts": drc["counts"],
            "after_total": drc["violations"],
            "connection_delta": -29,
        },
        "totals": {
            "footprints": len(footprint_reports),
            "protected_footprint_records": sum(item["record_count"] for item in footprint_reports),
            "changed_pad_records": sum(item["changed_pad_records"] for item in footprint_reports),
            "non_target_body_changes": sum(item["non_target_body_changes"] for item in footprint_reports),
            "protected_usb_polygon_paths": sum(len(item["protected_usb_polygon_path_hashes"]) for item in footprint_reports),
            "runtime_slots_verified": len(runtime_reports),
            "max_runtime_center_error_mil": max_center_error,
        },
        "checks": {
            "footprint_record_identity_and_type_sets_preserved": True,
            "only_13_hole_layerId_relativeAngle_bodies_changed": True,
            "all_other_footprint_bodies_unchanged": True,
            "eight_usb_polygon_paths_preserved": True,
            "runtime_has_13_multilayer_plated_slots": True,
            "runtime_slot_dimensions_and_rotations_match_excellon": True,
            "runtime_slot_centers_match_gerber": True,
            "reopened_board_has_330_components_and_1180_runtime_pads": True,
            "connection_drc_29_to_0": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT),
        "sha256": sha256(REPORT),
        "totals": report["totals"],
        "drc": report["drc"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
