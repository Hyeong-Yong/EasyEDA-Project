"""Enumerate the two omitted duplicate-number SW1 SMD pads.

The Gerber contains two physical copper/mask/paste centers for logical pad 1
and two for logical pad 2.  The current native footprint contains only the
right-hand center of each logical number.  This static audit freezes the two
left-hand children and their final PCB binding contract.
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
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_thermal_pth_restore_20261014.epro2"
PCB_SOURCE = ROOT / "output/validation/native-final-pcb-after_thermal_pth_restore-reopened.epru"
GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
LIBRARY = ROOT / "output/native-libraries/manifest.json"
REPORT = ROOT / "output/validation/native-missing-sw1-duplicate-smd-pad-audit.json"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"

REFERENCE = "SW1"
COMPONENT_ID = "a628f3517e8fe1d3"
FOOTPRINT_UUID = "bdc7750c34538c7c"
MM_TO_MIL = 1000.0 / 25.4
TOLERANCE_MIL = 0.0002


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value: Any, digits: int = 7) -> int | float:
    result = round(float(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    return math.dist([float(left[0]), float(left[1])], [float(right[0]), float(right[1])])


def parse_record(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header, body = raw.split("||", 1)
    return json.loads(header), json.loads(body[:-1] if body.endswith("|") else body)


def footprint_records() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    with zipfile.ZipFile(CHECKPOINT) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    current = False
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw in lines:
        header, body = parse_record(raw)
        if header.get("type") == "DOCHEAD":
            current = body.get("docType") == "FOOTPRINT" and body.get("uuid") == FOOTPRINT_UUID
        if current:
            result.append((header, body))
    return result


def main() -> int:
    for path in (CHECKPOINT, PCB_SOURCE, GERBER, LIBRARY):
        if not path.is_file():
            raise FileNotFoundError(path)
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    library = json.loads(LIBRARY.read_text(encoding="utf-8"))
    pcb = [parse_record(raw) for raw in PCB_SOURCE.read_text(encoding="utf-8-sig").splitlines()]
    footprint = footprint_records()
    if not footprint:
        raise AssertionError("actual SW1 project footprint block is missing")

    component = next(
        body for header, body in pcb
        if header.get("type") == "COMPONENT" and header.get("id") == COMPONENT_ID
    )
    if component.get("layerId") != 1 or float(component.get("angle", 0)) != 0:
        raise AssertionError("SW1 component is not the frozen top-side zero-angle placement")
    attrs = {
        str(body.get("key")): str(body.get("value") or body.get("blockValue") or "")
        for header, body in pcb
        if header.get("type") == "ATTR" and body.get("parentId") == COMPONENT_ID
    }
    if attrs.get("Designator") != REFERENCE or attrs.get("Footprint") != FOOTPRINT_UUID:
        raise AssertionError(f"SW1 component binding changed: {attrs!r}")
    pad_nets = {}
    for header, body in pcb:
        if header.get("type") != "PAD_NET":
            continue
        try:
            identity = json.loads(str(header.get("id")))
        except json.JSONDecodeError:
            continue
        if identity[:2] == ["PAD_NET", COMPONENT_ID]:
            pad_nets[(str(identity[2]), str(identity[3]))] = str(body.get("padNet") or "")
    if pad_nets != {("1", "e1"): "Net-(D1-K)", ("2", "e2"): "GND"}:
        raise AssertionError(f"SW1 baseline PAD_NET binding changed: {pad_nets!r}")

    source_footprint = library["footprints"][REFERENCE]
    if source_footprint["anchor_mm"] != [226.209999, -79.88]:
        raise AssertionError("SW1 frozen Gerber anchor changed")
    anchor = [float(value) for value in source_footprint["anchor_mm"]]
    native_pads = {
        str(body.get("num")): (header, body)
        for header, body in footprint if header.get("type") == "PAD"
    }
    if set(native_pads) != {"1", "2"}:
        raise AssertionError(f"SW1 current native pad set changed: {set(native_pads)!r}")

    component_gerber = gerber["components"][REFERENCE]
    aperture_contract = {
        "F.Cu": ("D54", "R", [1.6, 1.0]),
        "F.Mask": ("D55", "R", [1.6, 1.0]),
        "F.Paste": ("D43", "R", [1.6, 1.0]),
    }
    for layer, (aperture, template, params) in aperture_contract.items():
        row = gerber["aperturesByLayer"][layer][aperture]
        if row.get("template") != template or row.get("paramsMm") != params:
            raise AssertionError(f"{layer} aperture contract changed: {row!r}")

    rows: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for number in ("1", "2"):
        logical = component_gerber["pads"][number]
        copper = logical.get("flashes") or []
        if len(copper) != 2:
            raise AssertionError(f"SW1 pad {number}: expected two physical copper centers")
        existing_header, existing_body = native_pads[number]
        source_positions = {tuple(float(value) for value in item["atMm"]) for item in copper}
        mask_positions = {
            tuple(float(value) for value in item["atMm"])
            for item in component_gerber["layerGeometry"]["F.Mask"]
        }
        paste_positions = {
            tuple(float(value) for value in item["atMm"])
            for item in component_gerber["layerGeometry"]["F.Paste"]
        }
        number_rows: list[dict[str, Any]] = []
        for flash in sorted(copper, key=lambda item: tuple(item["atMm"])):
            at = [float(value) for value in flash["atMm"]]
            if tuple(at) not in mask_positions or tuple(at) not in paste_positions:
                raise AssertionError(f"SW1 pad {number} {at}: missing exact mask/paste center")
            if (
                flash.get("shape") != "R"
                or flash.get("paramsMm") != [1.6, 1.0]
                or flash.get("apertureFunction") != "SMDPad,CuDef"
                or flash.get("polarity") != "dark"
                or flash.get("holes") != []
            ):
                raise AssertionError(f"SW1 pad {number}: invalid copper flash {flash!r}")
            local = [
                clean((at[0] - anchor[0]) * MM_TO_MIL),
                clean((at[1] - anchor[1]) * MM_TO_MIL),
            ]
            is_existing = distance(local, [existing_body["centerX"], existing_body["centerY"]]) <= TOLERANCE_MIL
            expected_net = "Net-(D1-K)" if number == "1" else "GND"
            row = {
                "reference": REFERENCE,
                "pad_number": number,
                "source_at_mm": at,
                "footprint_anchor_mm": anchor,
                "footprint_local_center_mil_y_up": local,
                "board_component_center_mil_y_up": [component["x"], component["y"]],
                "native_board_center_mil_y_up": [
                    clean(float(component["x"]) + local[0]),
                    clean(float(component["y"]) + local[1]),
                ],
                "existing_native_pad": is_existing,
                "existing_native_record_id": str(existing_header.get("id")) if is_existing else None,
                "expected_net": expected_net,
                "layer_id": 1,
                "hole": None,
                "plated": True,
                "default_pad": {"padType": "RECT", "width": 62.992126, "height": 39.370079, "radius": 0},
                "source_geometry": {
                    "copper": {"layer": "F.Cu", "aperture": "D54", "shape": "R", "size_mm": [1.6, 1.0]},
                    "mask": {"layer": "F.Mask", "aperture": "D55", "shape": "R", "size_mm": [1.6, 1.0]},
                    "paste": {"layer": "F.Paste", "aperture": "D43", "shape": "R", "size_mm": [1.6, 1.0]},
                },
                "candidate_body_template": existing_body,
                "candidate_body_changes": {
                    "centerX": local[0],
                    "centerY": local[1],
                },
            }
            number_rows.append(row)
            rows.append(row)
            if not is_existing:
                missing.append(row)
        if sum(item["existing_native_pad"] for item in number_rows) != 1:
            raise AssertionError(f"SW1 pad {number}: current footprint does not contain exactly one center")

    if len(rows) != 4 or len(missing) != 2:
        raise AssertionError("SW1 physical/current/missing pad cardinality changed")
    missing_by_number = Counter(item["pad_number"] for item in missing)
    if missing_by_number != Counter({"1": 1, "2": 1}):
        raise AssertionError(f"SW1 missing-number distribution changed: {missing_by_number!r}")
    current_counts = Counter(str(header.get("type")) for header, _ in pcb)
    if current_counts["PAD_NET"] != 1184:
        raise AssertionError(f"expected post-thermal PAD_NET=1184, got {current_counts['PAD_NET']}")
    report = {
        "status": "fail-final-physical-completeness-gate-2-sw1-smd-pads-omitted",
        "purpose": "Freeze duplicate-number SW1 SMD copper/mask/paste centers and native child binding",
        "inputs": {
            "checkpoint": {"path": str(CHECKPOINT.relative_to(ROOT)), "sha256": sha256(CHECKPOINT)},
            "pcb_source": {"path": str(PCB_SOURCE.relative_to(ROOT)), "sha256": sha256(PCB_SOURCE)},
            "gerber_manifest": {"path": str(GERBER.relative_to(ROOT)), "sha256": sha256(GERBER)},
            "library_manifest": {"path": str(LIBRARY.relative_to(ROOT)), "sha256": sha256(LIBRARY)},
        },
        "identity": {
            "reference": REFERENCE,
            "component_id": COMPONENT_ID,
            "footprint_uuid": FOOTPRINT_UUID,
            "component_footprint_attr_verified": True,
        },
        "totals": {
            "logical_pad_numbers": 2,
            "source_physical_smd_pads": 4,
            "current_native_physical_smd_pads": 2,
            "omitted_native_physical_smd_pads": 2,
            "post_thermal_component_pad_records": current_counts["PAD_NET"],
            "additional_sma_pth_children_required": 48,
            "additional_sw1_smd_children_required": 2,
            "final_component_pad_and_pad_net_records_expected": 1234,
            "final_runtime_pad_count_including_four_board_npth_expected": 1238,
        },
        "physical_pads": rows,
        "missing_pad_records": missing,
        "checks": {
            "each_logical_number_has_two_unique_copper_centers": True,
            "all_four_centers_have_exact_matching_mask_and_paste_flashes": True,
            "copper_mask_paste_are_all_rect_1_6_by_1_0mm": True,
            "current_native_footprint_contains_only_right_hand_e1_e2": True,
            "missing_centers_are_exactly_left_hand_pad1_and_pad2": True,
            "candidate_clones_existing_number_body_and_changes_only_center_and_identity": True,
        },
        "required_fix": {
            "model": "one new duplicate-number SMD PAD child for num1 and one for num2 in SW1 footprint",
            "bindings": {"1": "Net-(D1-K)", "2": "GND"},
            "post_fix_gate": [
                "SW1 footprint has four PAD records at all four source centers",
                "PCB has one PAD_NET child for each new footprint child ID",
                "component PAD/PAD_NET count reaches 1234 after the 48 SMA PTH children are also restored",
                "runtime pad count including four board NPTH reaches 1238",
                "DRC Connection Error remains zero",
            ],
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT.relative_to(ROOT)),
        "sha256": sha256(REPORT),
        "totals": report["totals"],
        "missing": [
            {"number": item["pad_number"], "local_mil": item["footprint_local_center_mil_y_up"], "net": item["expected_net"]}
            for item in missing
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
