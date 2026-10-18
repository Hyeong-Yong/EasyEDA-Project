"""Prepare exact U5/U7 per-layer pad-shape repair candidates.

The archived Gerber defines U5 pad 25 and U7 pad 33 as a large rectangular
thermal pad on F.Cu plus a 0.6 mm circular plated annulus on every inner layer
and B.Cu.  A single EasyEDA multilayer ``defaultPad`` incorrectly repeats the
large top rectangle on every copper layer.  EasyEDA Pro 3.2's native
``specialPad`` field can retain the top rectangle while assigning the exact
0.6 mm circular shape to inner/bottom copper.

This tool reads the complete post-slot-fix checkpoint and raw Gerbers, changes
only each target PAD's ``specialPad`` field, and emits full FOOTPRINT sources.
It never calls an EasyEDA API.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from extract_gerber_reconstruction import parse_gerber


ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_drl_slot_fix_20261014.epro2"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
COMPONENTS = ROOT / "output/semantic/gerber-component-footprints.json"
GERBER_DIR = ROOT / "보드 자료/MCU_BOARD_v19_260616_Gerber"
OUTPUT = ROOT / "output/validation"
REPORT = OUTPUT / "u5-u7-special-pad-fix-plan.json"
PCB_JS = Path(r"C:\Program Files\easyeda-pro\resources\app\assets\pro-pcb\3.2.193.682ed44e\js\pcb.js")
PAD_DOC = ROOT / ".tools/easyeda-api/format/pcb/pad_via.md"
PAD_API_DOC = ROOT / ".tools/easyeda-api/references/classes/IPCB_PrimitivePad.md"

MM_TO_MIL = 1000.0 / 25.4
TOLERANCE_MM = 0.00001
TOLERANCE_MIL = 0.00016
COPPER_FILES = {
    "F.Cu": "MCU_BOARD_v19_260616-F_Cu.gbr",
    "In1.Cu": "MCU_BOARD_v19_260616-In1_Cu.gbr",
    "In2.Cu": "MCU_BOARD_v19_260616-In2_Cu.gbr",
    "In3.Cu": "MCU_BOARD_v19_260616-In3_Cu.gbr",
    "In4.Cu": "MCU_BOARD_v19_260616-In4_Cu.gbr",
    "B.Cu": "MCU_BOARD_v19_260616-B_Cu.gbr",
}
TARGETS = {
    "U5": {
        "uuid": "b098cceac55eab69",
        "pad_number": "25",
        "top_size_mm": 2.5,
        "candidate": "native-U5-special-pad-candidate.epru",
    },
    "U7": {
        "uuid": "15077d1eac66847c",
        "pad_number": "33",
        "top_size_mm": 3.45,
        "candidate": "native-U7-special-pad-candidate.epru",
    },
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
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(lines: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_record(raw: str, label: str, line_number: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        return header_text, json.loads(header_text), json.loads(body_text[:-1] if body_text.endswith("|") else body_text)
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def checkpoint_footprints() -> dict[str, list[str]]:
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


def dark_flashes_at(parsed: dict[str, Any], at_mm: Sequence[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    target = [finite(at_mm[0]), finite(at_mm[1])]
    for index, item in enumerate(parsed["objects"]):
        if item.get("kind") != "flash" or item.get("polarity") != "dark":
            continue
        point = item.get("atMm") or []
        if len(point) < 2 or math.dist(target, [finite(point[0]), finite(point[1])]) > TOLERANCE_MM:
            continue
        aperture = parsed["apertures"][item["aperture"]]
        result.append({
            "object_index": index,
            "aperture": item["aperture"],
            "attrs": item.get("attrs") or {},
            "template": aperture.get("template"),
            "params_mm": aperture.get("paramsMm") or [],
            "source_at_mm": item["atMm"],
        })
    return result


def find_shape(flashes: list[dict[str, Any]], template: str, params: Sequence[float]) -> dict[str, Any]:
    matches = [
        item for item in flashes
        if str(item.get("template")).upper() == template.upper()
        and len(item.get("params_mm") or []) == len(params)
        and all(abs(finite(left) - finite(right)) <= 0.000001 for left, right in zip(item["params_mm"], params))
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {template}{list(params)} flash, got {matches}")
    return matches[0]


def installed_schema_evidence() -> dict[str, Any]:
    source = PCB_JS.read_text(encoding="utf-8", errors="replace")
    needles = {
        "serializer": (
            'function MSe(o){if(!(o instanceof et)||o.type!=2||o.isPolygon())return[];'
            'let t=aX(o.top),e=aX(o.inner),r=aX(o.bottom);return[{startLayer:1,endLayer:1,pad:t},'
            '{startLayer:1,endLayer:2,pad:e},{startLayer:2,endLayer:2,pad:r}]}'
        ),
        "decoder": "parseSpecialPad(e){!Array.isArray(e)||e.length==0||(this.type=2,e.forEach",
        "public_setter_no_effect": "当前版本不产生任何效果",
    }
    result: dict[str, Any] = {
        "pcb_js": {"path": str(PCB_JS), "sha256": sha256(PCB_JS)},
        "format_document": {"path": str(PAD_DOC), "sha256": sha256(PAD_DOC), "special_pad_lines": [102, 105]},
        "public_api_document": {
            "path": str(PAD_API_DOC), "sha256": sha256(PAD_API_DOC),
            "setState_SpecialPad_documented_no_effect_line": 2933,
        },
        "matches": {},
    }
    for name, needle in needles.items():
        haystack = PAD_API_DOC.read_text(encoding="utf-8") if name == "public_setter_no_effect" else source
        position = haystack.find(needle)
        if position < 0:
            raise AssertionError(f"installed schema evidence missing: {name}")
        result["matches"][name] = {"byte_index_utf8_text": position, "needle": needle}
    result["canonical_special_pad"] = [
        {"startLayer": 1, "endLayer": 1, "role": "top"},
        {"startLayer": 1, "endLayer": 2, "role": "inner"},
        {"startLayer": 2, "endLayer": 2, "role": "bottom"},
    ]
    return result


def prepare_one(
    reference: str,
    config: dict[str, Any],
    component: dict[str, Any],
    lines: list[str],
    copper: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pad_number = config["pad_number"]
    pad = component["pads"][pad_number]
    front = next(item for item in pad["flashes"] if item.get("layer") == "F.Cu")
    at_mm = front["atMm"]
    layer_evidence = {layer: dark_flashes_at(parsed, at_mm) for layer, parsed in copper.items()}

    # F.Cu contains both the large exposed rectangle and the 0.6 mm via-pad
    # flash.  Every other copper layer contains only the 0.6 mm circular pad.
    front_rectangle = find_shape(layer_evidence["F.Cu"], "R", [config["top_size_mm"], config["top_size_mm"]])
    front_circle = find_shape(layer_evidence["F.Cu"], "C", [0.6])
    circular_evidence: dict[str, dict[str, Any]] = {"F.Cu": front_circle}
    for layer in ("In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"):
        if len(layer_evidence[layer]) != 1:
            raise AssertionError(f"{reference} {pad_number}: expected one dark flash on {layer}")
        circular_evidence[layer] = find_shape(layer_evidence[layer], "C", [0.6])
    for layer, evidence in circular_evidence.items():
        if evidence["attrs"].get("N") != "GND":
            raise AssertionError(f"{reference} {pad_number}: {layer} annulus is not GND")
    if front_rectangle["attrs"].get("N") != "GND":
        raise AssertionError(f"{reference} {pad_number}: top rectangle is not GND")

    # The authoritative checkpoint has already passed through the 3.2
    # serializer, which stores parametric pad dimensions at four decimals.
    # Match that persisted top shape exactly so defaultPad remains byte-stable.
    top_size = rounded(config["top_size_mm"] * MM_TO_MIL, 4)
    annulus_size = rounded(0.6 * MM_TO_MIL)
    top_shape = {"padType": "RECT", "width": top_size, "height": top_size, "radius": 0}
    circular_shape = {"padType": "ELLIPSE", "width": annulus_size, "height": annulus_size}
    special_pad = [
        {"startLayer": 1, "endLayer": 1, "pad": copy.deepcopy(top_shape)},
        {"startLayer": 1, "endLayer": 2, "pad": copy.deepcopy(circular_shape)},
        {"startLayer": 2, "endLayer": 2, "pad": copy.deepcopy(circular_shape)},
    ]

    output_lines = list(lines)
    modifications: list[dict[str, Any]] = []
    for index, raw in enumerate(lines, 1):
        header_text, header, body = parse_record(raw, reference, index)
        if header.get("type") != "PAD" or str(body.get("num")) != pad_number:
            continue
        if body.get("layerId") != 12 or body.get("plated") is not True:
            raise AssertionError(f"{reference} {pad_number}: target is not a plated multilayer pad")
        hole = body.get("hole") or {}
        expected_hole = 0.3 * MM_TO_MIL
        if (
            hole.get("holeType") != "ROUND"
            or not close(hole.get("width"), expected_hole)
            or not close(hole.get("height"), expected_hole)
        ):
            raise AssertionError(f"{reference} {pad_number}: 0.3 mm PTH drill changed")
        if body.get("defaultPad") != top_shape:
            raise AssertionError(
                f"{reference} {pad_number}: top rectangle differs from Gerber: {body.get('defaultPad')} != {top_shape}"
            )
        if body.get("specialPad") != [] or body.get("unusedInnerLayers") != []:
            raise AssertionError(f"{reference} {pad_number}: unexpected pre-existing per-layer state")
        repaired = copy.deepcopy(body)
        repaired["specialPad"] = special_pad
        changed = sorted(key for key in set(body) | set(repaired) if body.get(key) != repaired.get(key))
        if changed != ["specialPad"]:
            raise AssertionError(f"{reference} {pad_number}: unexpected changed fields {changed}")
        output_lines[index - 1] = f"{header_text}||{compact(repaired)}|"
        modifications.append({
            "record_id": header.get("id"),
            "line": index,
            "pad_number": pad_number,
            "changed_fields": changed,
            "center_mil": [body.get("centerX"), body.get("centerY")],
            "hole_preserved": hole,
            "plated_preserved": body.get("plated"),
            "default_top_pad_preserved": body.get("defaultPad"),
            "before_special_pad": body.get("specialPad"),
            "after_special_pad": special_pad,
            "unused_inner_layers_preserved": body.get("unusedInnerLayers"),
        })
    if len(modifications) != 1:
        raise AssertionError(f"{reference}: expected exactly one target PAD, got {len(modifications)}")

    candidate = OUTPUT / config["candidate"]
    candidate.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")
    reread = candidate.read_text(encoding="utf-8").splitlines()
    if len(reread) != len(lines):
        raise AssertionError(f"{reference}: candidate record count changed")
    changed_lines = [i + 1 for i, (before, after) in enumerate(zip(lines, reread)) if before != after]
    if changed_lines != [modifications[0]["line"]]:
        raise AssertionError(f"{reference}: candidate changed unexpected rows {changed_lines}")

    return {
        "reference": reference,
        "actual_project_library_uuid": config["uuid"],
        "authoritative_checkpoint_block_sha256": sha256_text(lines),
        "candidate": str(candidate.relative_to(ROOT)),
        "candidate_sha256": sha256(candidate),
        "record_count": len(lines),
        "record_type_counts": dict(sorted(Counter(
            parse_record(raw, reference, i)[1].get("type") for i, raw in enumerate(lines, 1)
        ).items())),
        "record_order_and_identity_preserved": True,
        "modified_record_count": 1,
        "modification": modifications[0],
        "non_target_record_changes": 0,
        "gerber": {
            "pad_center_mm": at_mm,
            "top_rectangle": front_rectangle,
            "top_via_annulus": front_circle,
            "inner_and_bottom_annuli": {
                layer: circular_evidence[layer]
                for layer in ("In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu")
            },
            "expected_top_shape_native_mil": top_shape,
            "expected_inner_bottom_shape_native_mil": circular_shape,
        },
    }


def main() -> int:
    footprints = checkpoint_footprints()
    components = json.loads(COMPONENTS.read_text(encoding="utf-8"))["components"]
    copper = {
        layer: parse_gerber(GERBER_DIR / filename, layer)
        for layer, filename in COPPER_FILES.items()
    }
    reports: list[dict[str, Any]] = []
    for reference, config in TARGETS.items():
        uuid = config["uuid"]
        if uuid not in footprints:
            raise AssertionError(f"{reference}: full checkpoint footprint {uuid} missing")
        reports.append(prepare_one(reference, config, components[reference], footprints[uuid], copper))

    report = {
        "status": "pass-candidates-not-applied",
        "purpose": "Restore Gerber-exact inner and bottom annuli for U5 pad25 and U7 pad33",
        "inputs": {
            "checkpoint": {"path": str(CHECKPOINT.relative_to(ROOT)), "sha256": sha256(CHECKPOINT), "member": MEMBER},
            "component_manifest": {"path": str(COMPONENTS.relative_to(ROOT)), "sha256": sha256(COMPONENTS)},
            "raw_copper_gerbers": {
                layer: {"path": str((GERBER_DIR / filename).relative_to(ROOT)), "sha256": sha256(GERBER_DIR / filename)}
                for layer, filename in COPPER_FILES.items()
            },
        },
        "installed_native_contract": installed_schema_evidence(),
        "footprints": reports,
        "totals": {
            "footprints": 2,
            "modified_pad_records": 2,
            "modified_fields": ["specialPad"],
            "non_target_record_changes": sum(item["non_target_record_changes"] for item in reports),
            "gerber_copper_layers_proved_per_pad": 6,
        },
        "checks": {
            "full_checkpoint_sources_used": True,
            "only_specialPad_field_changed": True,
            "top_rectangle_defaultPad_preserved": True,
            "hole_position_plating_and_unused_layers_preserved": True,
            "inner_and_bottom_circular_shapes_match_raw_gerber": True,
            "all_non_target_records_byte_exact": True,
            "public_no_effect_setter_not_used": True,
        },
        "application_gates": [
            "Root/UI writer must apply each complete FOOTPRINT source through the guarded project-library update path.",
            "Close/reload footprint and PCB caches before inspecting instantiated pads.",
            "Capture runtime specialPadShapeAspect for both pads and export a new full checkpoint.",
            "Prove exactly two PAD specialPad fields changed and rerun native DRC.",
            "Do not hide inner layers on U5/U7: all four archived inner Gerbers contain a GND annulus.",
        ],
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT),
        "report_sha256": sha256(REPORT),
        "candidates": [
            {"reference": item["reference"], "path": item["candidate"], "sha256": item["candidate_sha256"]}
            for item in reports
        ],
        "totals": report["totals"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
