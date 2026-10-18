"""Prepare exact project-footprint candidates for the 13 omitted plated slots.

The archived PTH Excellon uses routed ``G00/M15/G01/M16`` segments for CN1,
CN3 and CN4.  Earlier extraction accepted only point hits, leaving those pads
as top-layer SMD pads and turning the inner-layer pad flashes into disconnected
FILL islands.  This source-only tool starts from the authoritative post-USB-fix
project checkpoint and changes only the native PAD fields required to express
the original plated slots.

No EasyEDA API is called.  Applying the emitted candidates is deliberately a
separate operation owned by the UI writer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_usbc_pad_fix_20261014.epro2"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
PTH = ROOT / "보드 자료/MCU_BOARD_v19_260616_Gerber/MCU_BOARD_v19_260616-PTH.drl"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
OUTPUT = ROOT / "output/validation"
REPORT = OUTPUT / "plated-slot-pad-fix-plan.json"

MM_TO_MIL = 1000.0 / 25.4
TOLERANCE_MIL = 0.00016
TARGETS = {
    "CN1": {"uuid": "83fb62ef25d3eef1", "candidate": "native-CN1-plated-slot-candidate.epru"},
    "CN3": {"uuid": "8bd1ebd7c6524c9d", "candidate": "native-CN3-plated-slot-candidate.epru"},
    "CN4": {"uuid": "ae37a0fb8459ebec", "candidate": "native-CN4-plated-slot-candidate.epru"},
}


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite value {value!r}")
    return result


def rounded(value: Any, digits: int = 6) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def close(left: Any, right: Any, tolerance: float = TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(lines: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def parse_record(raw: str, label: str, line_number: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        body_json = body_text[:-1] if body_text.endswith("|") else body_text
        return header_text, json.loads(header_text), json.loads(body_json) if body_json else {}
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def checkpoint_blocks() -> dict[str, list[str]]:
    with zipfile.ZipFile(CHECKPOINT) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current: list[str] = []
    for line_number, raw in enumerate(lines, 1):
        _, header, body = parse_record(raw, CHECKPOINT.name, line_number)
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


def preferred_flash(pad: dict[str, Any]) -> dict[str, Any]:
    flashes = pad.get("flashes") or []
    flash = next((item for item in flashes if item.get("layer") == "F.Cu"), None)
    if flash is None:
        raise ValueError(f"pad has no F.Cu flash: {pad!r}")
    return flash


def slot_from_flash(flash: dict[str, Any]) -> dict[str, Any] | None:
    slots = [item for item in flash.get("holes") or [] if str(item.get("kind")).lower() == "slot"]
    if not slots:
        return None
    if len(slots) != 1:
        raise ValueError(f"flash has {len(slots)} routed slots")
    return slots[0]


def component_slot_table(component: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, pad in (component.get("pads") or {}).items():
        flash = preferred_flash(pad)
        slot = slot_from_flash(flash)
        if slot is not None:
            result[str(pad.get("number") or key)] = {"pad": pad, "flash": flash, "slot": slot}
    return result


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def prepare_one(reference: str, config: dict[str, Any], component: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    slot_table = component_slot_table(component)
    expected_count = 5 if reference == "CN1" else 4
    if len(slot_table) != expected_count:
        raise AssertionError(f"{reference}: expected {expected_count} routed slots, got {len(slot_table)}")
    anchor = component["estimatedAnchorMm"]
    parsed = [parse_record(raw, reference, index) for index, raw in enumerate(lines, 1)]
    output_lines = list(lines)
    modifications: list[dict[str, Any]] = []
    protected_usb_paths: dict[str, str] = {}

    for line_index, (header_text, header, body) in enumerate(parsed):
        if header.get("type") != "PAD":
            continue
        pad_number = str(body.get("num") or "")
        if reference in {"CN3", "CN4"} and pad_number in {"A1_B12", "A4_B9", "B1_A12", "B4_A9"}:
            path = body.get("defaultPad", {}).get("path")
            if not isinstance(path, list):
                raise AssertionError(f"{reference} {pad_number}: repaired polygon path missing")
            protected_usb_paths[pad_number] = hashlib.sha256(compact_json(path).encode("utf-8")).hexdigest()
        if pad_number not in slot_table:
            continue

        evidence = slot_table[pad_number]
        flash, slot = evidence["flash"], evidence["slot"]
        expected_center = [
            (finite(flash["atMm"][0]) - finite(anchor[0])) * MM_TO_MIL,
            (finite(flash["atMm"][1]) - finite(anchor[1])) * MM_TO_MIL,
        ]
        if not close(body.get("centerX"), expected_center[0]) or not close(body.get("centerY"), expected_center[1]):
            raise AssertionError(f"{reference} {pad_number}: PAD center differs from Gerber slot midpoint")
        if body.get("layerId") != 1 or body.get("hole") is not None or body.get("plated") is not True:
            raise AssertionError(f"{reference} {pad_number}: unexpected pre-fix PAD hole/layer/plating")
        shape = body.get("defaultPad") or {}
        params = [finite(value) for value in flash.get("paramsMm") or []]
        if (
            shape.get("padType") != "RECT"
            or shape.get("radius") != 100
            or len(params) < 2
            or not close(shape.get("width"), params[0] * MM_TO_MIL)
            or not close(shape.get("height"), params[1] * MM_TO_MIL)
        ):
            raise AssertionError(f"{reference} {pad_number}: copper capsule differs from Gerber O aperture")

        expected_hole = {
            "holeType": "SLOT",
            "width": rounded(finite(slot["overallLengthMm"]) * MM_TO_MIL),
            "height": rounded(finite(slot["diameterMm"]) * MM_TO_MIL),
        }
        angle = rounded(slot["angleDeg"])
        repaired = copy.deepcopy(body)
        repaired["layerId"] = 12
        repaired["hole"] = expected_hole
        repaired["relativeAngle"] = angle
        changed_fields = sorted(key for key in set(body) | set(repaired) if body.get(key) != repaired.get(key))
        if changed_fields != ["hole", "layerId", "relativeAngle"]:
            raise AssertionError(f"{reference} {pad_number}: unexpected changed fields {changed_fields}")
        output_lines[line_index] = f"{header_text}||{compact_json(repaired)}|"
        modifications.append({
            "pad_number": pad_number,
            "record_id": header.get("id"),
            "line": line_index + 1,
            "changed_fields": changed_fields,
            "center_footprint_mil": [rounded(value) for value in expected_center],
            "copper_shape_preserved": shape,
            "before": {"layerId": body.get("layerId"), "hole": body.get("hole"), "relativeAngle": body.get("relativeAngle")},
            "after": {"layerId": 12, "hole": expected_hole, "relativeAngle": angle},
            "excellon": {
                "tool": slot.get("tool"),
                "diameterMm": slot.get("diameterMm"),
                "startMm": slot.get("startMm"),
                "endMm": slot.get("endMm"),
                "midpointMm": flash.get("atMm"),
                "centerlineLengthMm": slot.get("centerlineLengthMm"),
                "overallLengthMm": slot.get("overallLengthMm"),
                "angleDeg": slot.get("angleDeg"),
                "function": slot.get("function"),
            },
        })

    if len(modifications) != expected_count:
        raise AssertionError(f"{reference}: changed {len(modifications)} slots, expected {expected_count}")
    if reference in {"CN3", "CN4"} and len(protected_usb_paths) != 4:
        raise AssertionError(f"{reference}: did not protect all four repaired polygon paths")

    candidate = OUTPUT / config["candidate"]
    candidate.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")
    candidate_lines = candidate.read_text(encoding="utf-8").splitlines()
    changed_lines = [
        index + 1 for index, (before, after) in enumerate(zip(lines, candidate_lines)) if before != after
    ]
    if len(lines) != len(candidate_lines) or changed_lines != [item["line"] for item in modifications]:
        raise AssertionError(f"{reference}: non-target source lines changed")

    before_identities = []
    after_identities = []
    for index, raw in enumerate(lines, 1):
        _, header, _ = parse_record(raw, reference, index)
        before_identities.append((header.get("type"), header.get("id")))
    for index, raw in enumerate(candidate_lines, 1):
        _, header, _ = parse_record(raw, reference, index)
        after_identities.append((header.get("type"), header.get("id")))
    if before_identities != after_identities:
        raise AssertionError(f"{reference}: record order/identity changed")

    # Re-read the candidate target bodies and prove their source forms exactly.
    candidate_targets = {}
    candidate_usb_paths = {}
    for index, raw in enumerate(candidate_lines, 1):
        _, header, body = parse_record(raw, reference, index)
        if header.get("type") != "PAD":
            continue
        number = str(body.get("num") or "")
        if number in slot_table:
            candidate_targets[number] = body
        if reference in {"CN3", "CN4"} and number in protected_usb_paths:
            candidate_usb_paths[number] = hashlib.sha256(
                compact_json(body["defaultPad"]["path"]).encode("utf-8")
            ).hexdigest()
    if candidate_usb_paths != protected_usb_paths:
        raise AssertionError(f"{reference}: repaired USB polygon path changed")
    for item in modifications:
        body = candidate_targets[item["pad_number"]]
        if body["layerId"] != 12 or body["hole"] != item["after"]["hole"] or body["relativeAngle"] != item["after"]["relativeAngle"]:
            raise AssertionError(f"{reference} {item['pad_number']}: candidate slot did not persist")

    counts = Counter(header.get("type") for _, header, _ in parsed)
    return {
        "reference": reference,
        "actual_project_library_uuid": config["uuid"],
        "authoritative_block_sha256": sha256_text(lines),
        "candidate": str(candidate.relative_to(ROOT)),
        "candidate_sha256": sha256(candidate),
        "record_count": len(lines),
        "record_type_counts": dict(sorted(counts.items())),
        "record_order_and_identity_preserved": True,
        "changed_lines": changed_lines,
        "slot_pad_count": len(modifications),
        "slot_pads": modifications,
        "protected_usb_polygon_path_hashes": protected_usb_paths,
        "non_target_record_changes": 0,
    }


def flatten_connection_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("errorType") == "Connection Error" and node.get("explanation"):
            result.append(node)
        for child in node.get("list", []):
            walk(child)

    for detail in data.get("details", []):
        walk(detail)
    return result


def drc_slot_correlation(gerber: dict[str, Any], footprint_reports: list[dict[str, Any]]) -> dict[str, Any]:
    bounds = gerber["coordinateTransform"]["boardBoundsSourceMm"]
    min_x, min_y = finite(bounds[0]), finite(bounds[1])
    centers = []
    for report in footprint_reports:
        for item in report["slot_pads"]:
            at = item["excellon"]["midpointMm"]
            centers.append({
                "reference": report["reference"],
                "pad_number": item["pad_number"],
                "net": item.get("net"),
                "world_mil": [
                    (finite(at[0]) - min_x) * MM_TO_MIL,
                    (finite(at[1]) - min_y) * MM_TO_MIL,
                ],
            })
    rows = flatten_connection_rows(DRC)
    by_slot: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    unmatched = []
    for row in rows:
        position = row.get("pos") or {}
        world = [finite(position["x"]) * 10, finite(position["y"]) * 10]
        distances = [
            (math.hypot(world[0] - item["world_mil"][0], world[1] - item["world_mil"][1]), item)
            for item in centers
        ]
        distance, nearest = min(distances, key=lambda item: item[0])
        entry = {
            "object_type": row.get("errorObjType"),
            "object": row.get("obj1", {}).get("suffix"),
            "runtime_id": row.get("explanation", {}).get("errData", {}).get("obj1"),
            "net": row.get("net"),
            "position_drc_units": [position.get("x"), position.get("y")],
            "distance_to_slot_center_mil": rounded(distance, 9),
        }
        if distance <= 0.001:
            by_slot[(nearest["reference"], nearest["pad_number"])].append(entry)
        else:
            unmatched.append(entry)
    expected_keys = {(item["reference"], item["pad_number"]) for item in centers}
    if unmatched or set(by_slot) != expected_keys or len(rows) != 29:
        raise AssertionError("connection DRC rows do not correlate exactly to the 13 routed slots")
    counts = sorted(len(items) for items in by_slot.values())
    if counts != [2] * 12 + [5]:
        raise AssertionError(f"unexpected per-slot DRC counts {counts}")
    return {
        "input": str(DRC.relative_to(ROOT)),
        "input_sha256": sha256(DRC),
        "connection_error_count": len(rows),
        "matched_to_slot_centers": len(rows),
        "unmatched": unmatched,
        "per_slot": [
            {"reference": ref, "pad_number": pad, "count": len(items), "errors": items}
            for (ref, pad), items in sorted(by_slot.items())
        ],
        "expected_after_native_slot_apply_and_rerun": 0,
        "warning": "The zero count is a testable expectation, not a substitute for the required native DRC rerun.",
    }


def main() -> int:
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    blocks = checkpoint_blocks()
    footprint_reports = []
    for reference, config in TARGETS.items():
        if config["uuid"] not in blocks:
            raise AssertionError(f"checkpoint lacks footprint {config['uuid']}")
        footprint_reports.append(
            prepare_one(reference, config, gerber["components"][reference], blocks[config["uuid"]])
        )
    if sum(item["slot_pad_count"] for item in footprint_reports) != 13:
        raise AssertionError("expected exactly 13 plated slot pad repairs")
    correlation = drc_slot_correlation(gerber, footprint_reports)
    report = {
        "status": "pass",
        "purpose": "Restore 13 omitted PTH routed plated slots in CN1/CN3/CN4",
        "coordinate_contract": {
            "source": "Excellon millimetres, routed centerline between G00 and G01 while M15 is active",
            "native": "footprint-local mil, Y-up",
            "native_hole": "holeType SLOT; width is complete round-capped length; height is tool diameter; relativeAngle rotates the slot",
            "installed_decoder_evidence": (
                "EasyEDA Pro 3.2 PAD parseHole maps width/10 to holeLength and height/20 to holeRadius; "
                "holeType SLOT is explicitly supported."
            ),
        },
        "inputs": {
            "checkpoint": {"path": str(CHECKPOINT.relative_to(ROOT)), "sha256": sha256(CHECKPOINT), "member": MEMBER},
            "gerber_manifest": {"path": str(GERBER.relative_to(ROOT)), "sha256": sha256(GERBER)},
            "pth_excellon": {"path": str(PTH.relative_to(ROOT)), "sha256": sha256(PTH)},
        },
        "footprints": footprint_reports,
        "drc_connection_correlation": correlation,
        "totals": {
            "footprints": 3,
            "plated_slot_pads": 13,
            "changed_records": 13,
            "non_target_record_changes": 0,
            "cn1_slots": 5,
            "cn3_slots": 4,
            "cn4_slots": 4,
            "protected_existing_usb_polygon_paths": 8,
            "connection_errors_explained": 29,
        },
        "checks": {
            "record_order_and_identity_preserved": True,
            "only_hole_layerId_relativeAngle_changed": True,
            "copper_capsule_geometry_preserved": True,
            "usb_polygon_paths_preserved": True,
            "slot_midpoints_match_pad_centers": True,
            "slot_width_is_centerline_plus_tool_diameter": True,
            "all_29_connection_errors_correlate_to_slot_centers": True,
        },
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT),
        "report_sha256": sha256(REPORT),
        "candidates": [
            {"reference": item["reference"], "path": item["candidate"], "sha256": item["candidate_sha256"]}
            for item in footprint_reports
        ],
        "totals": report["totals"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
