"""Audit the final native PCB drill inventory against authoritative Excellon.

This is a static/read-only verifier.  It does not call EasyEDA.  The audit
joins the final PCB COMPONENT/PAD_NET records to the authoritative project
FOOTPRINT blocks in a full ``.epro2`` checkpoint, transforms every footprint
hole to the board coordinate system, and then performs one-to-one matching
against the original PTH and NPTH drill hits.

Expected physical inventory from the June manufacturing source:

* 634 routing VIAs (round plated ViaDrill hits)
* 133 round component PTH pads
* 13 routed component PTH slots
* 9 component-owned mechanical NPTH pads
* 4 top-level 3.2 mm mounting NPTH pads

The final eight U5/U7 thermal holes are included in the 133 component PTHs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_CHECKPOINT = (
    ROOT / "output/checkpoints/STM32H747_after_thermal_pth_restore_20261014.epro2"
)
DEFAULT_PCB = (
    ROOT / "output/validation/native-final-pcb-after_thermal_pth_restore-reopened.epru"
)
DEFAULT_MANIFEST = ROOT / "output/semantic/gerber-component-footprints.json"
DEFAULT_DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
DEFAULT_REPORT = ROOT / "output/validation/native-final-drill-inventory-audit.json"

MM_TO_MIL = 1000.0 / 25.4
# Excellon coordinates are emitted to 0.001 mm while copper flashes retain
# six decimal places.  Native VIA/PAD centers follow the copper flash, so the
# correct identity tolerance is half an Excellon least-significant digit plus
# a small native four-decimal-mil serialization allowance.
POSITION_TOLERANCE_MIL = 0.0290
SIZE_TOLERANCE_MIL = 0.0010
ANGLE_TOLERANCE_DEG = 0.0001


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"non-finite numeric value {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def clean(value: Any, digits: int = 7) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        if body_text.endswith("|"):
            body_text = body_text[:-1]
        return json.loads(header_text), json.loads(body_text)
    except Exception as exc:  # pragma: no cover - diagnostic context matters
        raise AuditError(f"invalid native record {label}:{line_number}: {exc}") from exc


def read_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
        if raw.strip()
    ]


def read_checkpoint_blocks(
    path: Path,
) -> tuple[dict[str, list[tuple[dict[str, Any], dict[str, Any]]]], dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(MEMBER).decode("utf-8-sig")
    blocks: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    types: dict[str, str] = {}
    current_uuid: str | None = None
    for line_number, line in enumerate(raw.splitlines(), 1):
        header, body = parse_record(line, f"{path.name}:{MEMBER}", line_number)
        if header.get("type") == "DOCHEAD":
            current_uuid = str(body.get("uuid") or "")
            if not current_uuid:
                raise AuditError(f"DOCHEAD at line {line_number} has no uuid")
            if current_uuid in blocks:
                raise AuditError(f"duplicate checkpoint document uuid {current_uuid}")
            blocks[current_uuid] = [(header, body)]
            types[current_uuid] = str(body.get("docType") or "")
        elif current_uuid is not None:
            blocks[current_uuid].append((header, body))
    return blocks, types


def child_attributes(
    records: Sequence[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for header, body in records:
        if header.get("type") != "ATTR":
            continue
        parent = str(body.get("parentId") or "")
        key = str(body.get("key") or "")
        value = body.get("value")
        if value is None:
            value = body.get("blockValue")
        if parent and key:
            result[parent][key] = "" if value is None else str(value)
    return result


def pad_net_identity(header: dict[str, Any]) -> tuple[str, str, str]:
    try:
        value = json.loads(str(header.get("id")))
    except Exception as exc:
        raise AuditError(f"invalid PAD_NET identity {header.get('id')!r}") from exc
    if not isinstance(value, list) or len(value) != 4 or value[0] != "PAD_NET":
        raise AuditError(f"invalid PAD_NET tuple {value!r}")
    return str(value[1]), str(value[2]), str(value[3])


def board_point(source_mm: Sequence[Any], bounds: Sequence[Any]) -> tuple[float, float]:
    return (
        (finite(source_mm[0]) - finite(bounds[0])) * MM_TO_MIL,
        (finite(source_mm[1]) - finite(bounds[1])) * MM_TO_MIL,
    )


def distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    return math.dist([finite(left[0]), finite(left[1])], [finite(right[0]), finite(right[1])])


def expected_drills(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    bounds = manifest["coordinateTransform"]["boardBoundsSourceMm"]
    result: dict[str, list[dict[str, Any]]] = {
        "via_round": [],
        "component_round": [],
        "component_slot": [],
        "npth": [],
    }
    for drill_file in manifest.get("drills", []):
        file_name = str(drill_file.get("file") or "")
        for index, hole in enumerate(drill_file.get("holes", [])):
            item = dict(hole)
            item["source_file"] = file_name
            item["source_index"] = index
            item["board_center_mil_y_up"] = list(board_point(hole["atMm"], bounds))
            function = str(hole.get("function") or "")
            is_slot = hole.get("kind") == "slot"
            if hole.get("plated") is False or "NonPlated" in function or "NPTH" in function:
                key = "npth"
            elif function == "Plated,PTH,ViaDrill" and not is_slot:
                key = "via_round"
            elif function == "Plated,PTH,ComponentDrill" and is_slot:
                key = "component_slot"
            elif function == "Plated,PTH,ComponentDrill" and not is_slot:
                key = "component_round"
            else:
                raise AuditError(f"unclassified drill hit {hole!r}")
            result[key].append(item)
    expected = {"via_round": 634, "component_round": 133, "component_slot": 13, "npth": 13}
    counts = {key: len(value) for key, value in result.items()}
    if counts != expected:
        raise AuditError(f"authoritative drill inventory changed: {counts!r} != {expected!r}")
    return result


def native_inventory(
    checkpoint: Path,
    pcb_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    blocks, doc_types = read_checkpoint_blocks(checkpoint)
    footprint_blocks = {
        uuid: rows for uuid, rows in blocks.items() if doc_types.get(uuid) == "FOOTPRINT"
    }
    pcb = read_records(pcb_path)
    pcb_counts = Counter(str(header.get("type")) for header, _ in pcb)
    attrs = child_attributes(pcb)
    components: dict[str, dict[str, Any]] = {}
    refs: dict[str, str] = {}
    for header, body in pcb:
        if header.get("type") != "COMPONENT":
            continue
        component_id = str(header.get("id"))
        reference = attrs.get(component_id, {}).get("Designator", "")
        footprint_uuid = attrs.get(component_id, {}).get("Footprint", "")
        if not reference or not footprint_uuid:
            raise AuditError(f"COMPONENT {component_id} lacks Designator/Footprint ATTR")
        if reference in refs:
            raise AuditError(f"duplicate component reference {reference}")
        if footprint_uuid not in footprint_blocks:
            raise AuditError(f"{reference}: footprint block {footprint_uuid} absent from checkpoint")
        if body.get("layerId") != 1 or not close(body.get("angle", 0), 0, ANGLE_TOLERANCE_DEG):
            raise AuditError(f"{reference}: non-baked component placement {body!r}")
        components[component_id] = {
            "reference": reference,
            "footprint_uuid": footprint_uuid,
            "x": finite(body.get("x")),
            "y": finite(body.get("y")),
        }
        refs[reference] = component_id
    if len(components) != 330:
        raise AuditError(f"expected 330 native COMPONENTs, got {len(components)}")

    pad_nets: dict[tuple[str, str], dict[str, Any]] = {}
    for header, body in pcb:
        if header.get("type") != "PAD_NET":
            continue
        component_id, number, local_id = pad_net_identity(header)
        key = (component_id, local_id)
        if key in pad_nets:
            raise AuditError(f"duplicate PAD_NET child identity {key!r}")
        pad_nets[key] = {
            "number": number,
            "net": str(body.get("padNet") or ""),
            "record_id": str(header.get("id")),
        }

    result: dict[str, list[dict[str, Any]]] = {
        "via_round": [],
        "component_round": [],
        "component_slot": [],
        "component_npth": [],
        "board_npth": [],
    }
    for header, body in pcb:
        kind = str(header.get("type"))
        if kind == "VIA":
            result["via_round"].append({
                "native_record_id": str(header.get("id")),
                "center_mil": [finite(body.get("centerX")), finite(body.get("centerY"))],
                "diameter_mil": finite(body.get("holeDiameter")),
                "net": str(body.get("netName") or ""),
            })
        elif kind == "PAD":
            hole = body.get("hole") or {}
            if finite(hole.get("width", 0)) <= 0 and finite(hole.get("height", 0)) <= 0:
                continue
            if body.get("plated") is not False:
                raise AuditError(f"unexpected top-level plated PAD {header.get('id')}")
            result["board_npth"].append({
                "native_record_id": str(header.get("id")),
                "center_mil": [finite(body.get("centerX")), finite(body.get("centerY"))],
                "diameter_mil": max(finite(hole.get("width")), finite(hole.get("height"))),
                "reference": "REF**",
                "pad_number": str(body.get("num") or ""),
            })

    seen_pad_net: set[tuple[str, str]] = set()
    component_pad_counts: Counter[str] = Counter()
    for component_id, component in components.items():
        rows = footprint_blocks[component["footprint_uuid"]]
        for header, body in rows:
            if header.get("type") != "PAD":
                continue
            local_id = str(header.get("id"))
            key = (component_id, local_id)
            binding = pad_nets.get(key)
            if binding is None:
                raise AuditError(
                    f"{component['reference']} {local_id}: footprint PAD lacks PCB PAD_NET child"
                )
            seen_pad_net.add(key)
            pad_number = str(body.get("num") or "")
            if binding["number"] != pad_number:
                raise AuditError(
                    f"{component['reference']} {local_id}: PAD_NET number {binding['number']!r} "
                    f"!= footprint number {pad_number!r}"
                )
            component_pad_counts[component["reference"]] += 1
            hole = body.get("hole") or {}
            width = finite(hole.get("width", 0))
            height = finite(hole.get("height", 0))
            if width <= 0 and height <= 0:
                continue
            common = {
                "native_record_id": local_id,
                "pad_net_record_id": binding["record_id"],
                "reference": component["reference"],
                "footprint_uuid": component["footprint_uuid"],
                "pad_number": pad_number,
                "center_mil": [
                    component["x"] + finite(body.get("centerX")),
                    component["y"] + finite(body.get("centerY")),
                ],
                "net": binding["net"],
                "plated": body.get("plated") is True,
                "hole_type": str(hole.get("holeType") or ""),
                "hole_width_mil": width,
                "hole_height_mil": height,
                "hole_angle_deg": finite(body.get("relativeAngle", 0)),
                "unused_inner_layers": [int(value) for value in (body.get("unusedInnerLayers") or [])],
            }
            if body.get("plated") is False:
                result["component_npth"].append(common)
            elif body.get("plated") is True and common["hole_type"] == "ROUND":
                result["component_round"].append(common)
            elif body.get("plated") is True and common["hole_type"] == "SLOT":
                result["component_slot"].append(common)
            else:
                raise AuditError(f"unclassified footprint hole PAD {common!r}")

    extra_pad_nets = set(pad_nets) - seen_pad_net
    if extra_pad_nets:
        preview = sorted(extra_pad_nets)[:10]
        raise AuditError(f"PCB contains PAD_NET children absent from footprint sources: {preview!r}")
    return result, {
        "pcb_record_type_counts": dict(sorted(pcb_counts.items())),
        "footprint_blocks": len(footprint_blocks),
        "component_count": len(components),
        "component_pad_records": sum(component_pad_counts.values()),
        "pad_net_records": len(pad_nets),
        "references": sorted(refs),
    }


def match_round(
    category: str,
    expected: Sequence[dict[str, Any]],
    actual: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    remaining = set(range(len(actual)))
    matches: list[dict[str, Any]] = []
    for source in expected:
        source_center = source["board_center_mil_y_up"]
        source_diameter = finite(source["diameterMm"]) * MM_TO_MIL
        candidates: list[tuple[float, int]] = []
        for index in remaining:
            target = actual[index]
            target_diameter = target.get("diameter_mil")
            if target_diameter is None:
                target_diameter = max(
                    finite(target.get("hole_width_mil")), finite(target.get("hole_height_mil"))
                )
            separation = distance(source_center, target["center_mil"])
            if separation <= POSITION_TOLERANCE_MIL and close(
                target_diameter, source_diameter, SIZE_TOLERANCE_MIL
            ):
                candidates.append((separation, index))
        if len(candidates) != 1:
            raise AuditError(
                f"{category}: drill {source.get('atMm')} diameter={source_diameter} "
                f"has {len(candidates)} native matches"
            )
        separation, index = candidates[0]
        remaining.remove(index)
        target = actual[index]
        matches.append({
            "source_index": source["source_index"],
            "source_at_mm": source["atMm"],
            "native_record_id": target["native_record_id"],
            "reference": target.get("reference"),
            "pad_number": target.get("pad_number"),
            "net": target.get("net"),
            "unused_inner_layers": target.get("unused_inner_layers"),
            "center_error_mil": clean(separation, 9),
            "source_diameter_mm": source["diameterMm"],
            "native_diameter_mil": clean(
                target.get("diameter_mil")
                if target.get("diameter_mil") is not None
                else max(target["hole_width_mil"], target["hole_height_mil"]),
                7,
            ),
        })
    if remaining:
        raise AuditError(f"{category}: {len(remaining)} unmatched native holes remain")
    return matches


def angular_error(left: Any, right: Any) -> float:
    delta = (finite(left) - finite(right)) % 180.0
    return min(delta, 180.0 - delta)


def match_slots(
    expected: Sequence[dict[str, Any]], actual: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    remaining = set(range(len(actual)))
    matches: list[dict[str, Any]] = []
    for source in expected:
        source_center = source["board_center_mil_y_up"]
        source_width = finite(source["overallLengthMm"]) * MM_TO_MIL
        source_height = finite(source["diameterMm"]) * MM_TO_MIL
        source_angle = finite(source["angleDeg"])
        candidates: list[tuple[float, int]] = []
        for index in remaining:
            target = actual[index]
            separation = distance(source_center, target["center_mil"])
            if (
                separation <= POSITION_TOLERANCE_MIL
                and close(target["hole_width_mil"], source_width, SIZE_TOLERANCE_MIL)
                and close(target["hole_height_mil"], source_height, SIZE_TOLERANCE_MIL)
                and angular_error(target["hole_angle_deg"], source_angle) <= ANGLE_TOLERANCE_DEG
            ):
                candidates.append((separation, index))
        if len(candidates) != 1:
            raise AuditError(
                f"component_slot: drill {source.get('atMm')} has {len(candidates)} native matches"
            )
        separation, index = candidates[0]
        remaining.remove(index)
        target = actual[index]
        matches.append({
            "source_index": source["source_index"],
            "source_at_mm": source["atMm"],
            "source_start_mm": source["startMm"],
            "source_end_mm": source["endMm"],
            "native_record_id": target["native_record_id"],
            "reference": target["reference"],
            "pad_number": target["pad_number"],
            "net": target["net"],
            "center_error_mil": clean(separation, 9),
            "source_diameter_mm": source["diameterMm"],
            "source_overall_length_mm": source["overallLengthMm"],
            "source_angle_deg": source_angle,
            "native_hole_mil": [target["hole_width_mil"], target["hole_height_mil"]],
            "native_angle_deg": target["hole_angle_deg"],
        })
    if remaining:
        raise AuditError(f"component_slot: {len(remaining)} unmatched native slots remain")
    return matches


def summarize_errors(matches: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(matches)
    errors = [finite(row["center_error_mil"]) for row in rows]
    return {
        "count": len(rows),
        "max_center_error_mil": clean(max(errors, default=0), 9),
        "mean_center_error_mil": clean(sum(errors) / len(errors) if errors else 0, 9),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--pcb", type=Path, default=DEFAULT_PCB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--drc", type=Path, default=DEFAULT_DRC)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    args.checkpoint = args.checkpoint.resolve()
    args.pcb = args.pcb.resolve()
    args.manifest = args.manifest.resolve()
    args.drc = args.drc.resolve()
    args.output = args.output.resolve()
    for path in (args.checkpoint, args.pcb, args.manifest, args.drc):
        if not path.is_file():
            raise AuditError(f"required artifact missing: {path}")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = expected_drills(manifest)
    actual, native_summary = native_inventory(args.checkpoint, args.pcb)
    actual_counts = {key: len(value) for key, value in actual.items()}
    wanted_counts = {
        "via_round": 634,
        "component_round": 133,
        "component_slot": 13,
        "component_npth": 9,
        "board_npth": 4,
    }
    if actual_counts != wanted_counts:
        raise AuditError(f"native drill inventory {actual_counts!r} != {wanted_counts!r}")

    matches = {
        "via_round": match_round("via_round", expected["via_round"], actual["via_round"]),
        "component_round": match_round(
            "component_round", expected["component_round"], actual["component_round"]
        ),
        "component_slot": match_slots(expected["component_slot"], actual["component_slot"]),
    }
    npth_actual = [*actual["component_npth"], *actual["board_npth"]]
    matches["npth"] = match_round("npth", expected["npth"], npth_actual)
    component_npth_matched = sum(row.get("reference") != "REF**" for row in matches["npth"])
    board_npth_matched = len(matches["npth"]) - component_npth_matched
    if (component_npth_matched, board_npth_matched) != (9, 4):
        raise AuditError(
            f"NPTH ownership mismatch: component={component_npth_matched}, board={board_npth_matched}"
        )

    thermal = [
        row for row in matches["component_round"]
        if row.get("reference") in {"U5", "U7"} and row.get("pad_number") in {"25", "33"}
    ]
    thermal_counts = Counter(str(row.get("reference")) for row in thermal)
    if thermal_counts != Counter({"U5": 5, "U7": 5}):
        raise AuditError(f"U5/U7 central plus thermal PTH inventory mismatch: {dict(thermal_counts)}")
    if any(row.get("net") != "GND" for row in thermal):
        raise AuditError("one or more U5/U7 pad25/pad33 PTHs are not bound to GND")
    sma_ground_posts = [
        row for row in matches["component_round"]
        if row.get("reference") in {f"J{number}" for number in range(2, 18)}
        and row.get("pad_number") == "2"
    ]
    if len(sma_ground_posts) != 64:
        raise AuditError(f"expected 64 physical SMA ground posts, got {len(sma_ground_posts)}")
    if any(row.get("unused_inner_layers") != [16] for row in sma_ground_posts):
        raise AuditError("one or more SMA pad2 ground posts does not hide source-absent In2 copper")

    drc = json.loads(args.drc.read_text(encoding="utf-8"))
    connection_count = int((drc.get("counts") or {}).get("Connection Error", 0))
    if connection_count != 0:
        raise AuditError(f"final DRC still has {connection_count} Connection Error findings")

    report = {
        "status": "pass-static-drill-identity-not-manufacturing-approval",
        "purpose": "One-to-one native drill identity audit against original PTH/NPTH Excellon",
        "inputs": {
            "checkpoint": {"path": str(args.checkpoint.relative_to(ROOT)), "sha256": sha256(args.checkpoint)},
            "pcb_source": {"path": str(args.pcb.relative_to(ROOT)), "sha256": sha256(args.pcb)},
            "gerber_manifest": {"path": str(args.manifest.relative_to(ROOT)), "sha256": sha256(args.manifest)},
            "drc": {"path": str(args.drc.relative_to(ROOT)), "sha256": sha256(args.drc)},
        },
        "coordinate_contract": {
            "source": "Excellon/Gerber absolute mm, numeric Y-up",
            "native": "board-local mil, Y-up",
            "formula": "(sourceMm - boardBoundsSourceMm minimum) * 1000/25.4",
            "position_tolerance_mil": POSITION_TOLERANCE_MIL,
            "position_tolerance_basis": "sqrt(2)*0.0005 mm Excellon XY quantization plus native 0.0001 mil serialization",
            "size_tolerance_mil": SIZE_TOLERANCE_MIL,
        },
        "authoritative_source_inventory": {
            "pth_round_hits": 767,
            "pth_routed_slots": 13,
            "via_round": len(expected["via_round"]),
            "component_round": len(expected["component_round"]),
            "component_slot": len(expected["component_slot"]),
            "npth_round": len(expected["npth"]),
        },
        "native_inventory": {
            **actual_counts,
            "component_plus_board_npth": len(npth_actual),
            "total_physical_drills": sum(actual_counts.values()),
            **native_summary,
        },
        "match_summary": {key: summarize_errors(rows) for key, rows in matches.items()},
        "thermal_pth": {
            "count": len(thermal),
            "by_reference_including_central": dict(sorted(thermal_counts.items())),
            "restored_extra_count": len(thermal) - 2,
            "all_gnd": True,
            "matches": thermal,
        },
        "sma_ground_posts": {
            "count": len(sma_ground_posts),
            "references": 16,
            "posts_per_reference": 4,
            "all_gnd": all(row.get("net") == "GND" for row in sma_ground_posts),
            "all_unused_inner_layers": [16],
        },
        "npth_ownership": {
            "component": component_npth_matched,
            "board_mounting": board_npth_matched,
        },
        "drc": {
            "passed": bool(drc.get("passed")),
            "counts": drc.get("counts") or {},
            "connection_error_count": connection_count,
            "clearance_findings_remain": int((drc.get("counts") or {}).get("Clearance Error", 0)),
        },
        "checks": {
            "all_634_native_vias_match_unique_via_drill_hits": True,
            "all_133_component_round_pths_match_unique_component_drill_hits": True,
            "all_13_component_slots_match_unique_routed_slot_hits": True,
            "all_13_npths_match_unique_nonplated_hits": True,
            "npth_ownership_is_9_component_plus_4_board": True,
            "all_component_pad_records_have_exact_pad_net_child_ids": True,
            "u5_u7_each_have_central_plus_four_thermal_pths_on_gnd": True,
            "all_64_sma_ground_posts_hide_only_source_absent_in2_copper": True,
            "drc_connection_error_count_is_zero": True,
        },
        "matches": matches,
        "limitations": [
            "This proves native source/checkpoint drill identity and connectivity metadata; it is not a manufacturing release.",
            "Remaining clearance findings must be dispositioned independently before fabrication approval.",
            "A diagnostic Gerber/Excellon export should be compared separately; this report does not treat an export as authoritative source replacement.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(args.output.relative_to(ROOT)),
        "sha256": sha256(args.output),
        "native_inventory": report["native_inventory"],
        "match_summary": report["match_summary"],
        "drc": report["drc"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
