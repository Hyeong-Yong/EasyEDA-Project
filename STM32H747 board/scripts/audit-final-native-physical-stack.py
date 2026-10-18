#!/usr/bin/env python3
"""Static final proof for the native six-copper-layer physical stack.

The reopened PCB source and its full project checkpoint are compared exactly
for all LAYER/LAYER_PHYS records.  Native thicknesses (mil) are then decoded
and compared with the UI-import plan (mm).  Dk/Df values are reported as UI
placeholders because the Gerber job does not specify impedance material data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
TARGET_UUID = "0ac2a19168000d8e"
DEFAULT_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_final_reconstruction_20261015.epro2"
DEFAULT_SOURCE = ROOT / "output/validation/native-final-pcb-final_reconstruction-reopened.epru"
DEFAULT_PLAN = ROOT / "output/validation/native-physical-stack-v19-6l-ui.json"
DEFAULT_OUTPUT = ROOT / "output/validation/native-final-physical-stack-audit.json"
MIL_TO_MM = 25.4 / 1000.0
THICKNESS_TOLERANCE_MM = 0.00002


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"non-finite number {value!r}")
    return result


def parse_record(line: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header_text, body_text = line.split("||", 1)
    if body_text.endswith("|"):
        body_text = body_text[:-1]
    return json.loads(header_text), json.loads(body_text)


def read_source(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [parse_record(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def read_target_checkpoint(path: Path, target_uuid: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    active = False
    found = False
    for line in lines:
        if not line.strip():
            continue
        header, body = parse_record(line)
        if header.get("type") == "DOCHEAD":
            if active:
                break
            active = str(body.get("uuid") or "") == target_uuid
            if active:
                found = True
                result.append((header, body))
        elif active:
            result.append((header, body))
    if not found:
        raise AuditError(f"target PCB UUID {target_uuid} absent from checkpoint")
    return result


def record_id_number(header: dict[str, Any], expected_type: str) -> int:
    value = json.loads(str(header.get("id")))
    if not isinstance(value, list) or len(value) != 2 or value[0] != expected_type:
        raise AuditError(f"invalid {expected_type} identity {header.get('id')!r}")
    return int(value[1])


def keyed(
    rows: list[tuple[dict[str, Any], dict[str, Any]]], kind: str
) -> dict[int, tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
    for header, body in rows:
        if header.get("type") != kind:
            continue
        key = record_id_number(header, kind)
        if key in result:
            raise AuditError(f"duplicate {kind} ID {key}")
        result[key] = (header, body)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--ui-plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--target-uuid", default=TARGET_UUID)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    checkpoint = args.checkpoint.resolve()
    source = args.source.resolve()
    plan_path = args.ui_plan.resolve()
    output = args.output.resolve()
    for path in (checkpoint, source, plan_path):
        if not path.is_file():
            raise AuditError(f"required artifact missing: {path}")

    source_rows = read_source(source)
    checkpoint_rows = read_target_checkpoint(checkpoint, args.target_uuid)
    source_layers = keyed(source_rows, "LAYER")
    checkpoint_layers = keyed(checkpoint_rows, "LAYER")
    source_phys = keyed(source_rows, "LAYER_PHYS")
    checkpoint_phys = keyed(checkpoint_rows, "LAYER_PHYS")
    if len(source_layers) != 64 or set(source_layers) != set(checkpoint_layers):
        raise AuditError("source/checkpoint LAYER inventory is not exact 64 IDs")
    if len(source_phys) != 17 or set(source_phys) != set(checkpoint_phys):
        raise AuditError("source/checkpoint LAYER_PHYS inventory is not exact 17 IDs")
    if any(source_layers[key][1] != checkpoint_layers[key][1] for key in source_layers):
        raise AuditError("source/checkpoint LAYER bodies differ")
    if any(source_phys[key][1] != checkpoint_phys[key][1] for key in source_phys):
        raise AuditError("source/checkpoint LAYER_PHYS bodies differ")

    ui = json.loads(plan_path.read_text(encoding="utf-8"))
    expected_rows = ui.get("physicalStacking") or []
    expected_ids = [int(row["values"]["Layer Id"]) for row in expected_rows]
    ordered_source = sorted(
        source_phys.items(), key=lambda item: int(item[1][1].get("zIndex", 0))
    )
    actual_ids = [layer_id for layer_id, _ in ordered_source]
    if expected_ids != actual_ids:
        raise AuditError(f"physical stack order differs: {actual_ids!r} != {expected_ids!r}")

    decoded: list[dict[str, Any]] = []
    max_error = 0.0
    for expected, (layer_id, (_, actual)) in zip(expected_rows, ordered_source):
        values = expected["values"]
        expected_mm = finite(values["Thickness"])
        actual_mil = finite(actual.get("thickness"))
        actual_mm = actual_mil * MIL_TO_MM
        error_mm = abs(actual_mm - expected_mm)
        max_error = max(max_error, error_mm)
        if error_mm > THICKNESS_TOLERANCE_MM:
            raise AuditError(f"layer {layer_id}: thickness error {error_mm:.9f} mm")
        if str(actual.get("material") or "") != str(values.get("Material") or ""):
            raise AuditError(f"layer {layer_id}: material differs")
        if finite(actual.get("permittivity")) != finite(values.get("Permittivity")):
            raise AuditError(f"layer {layer_id}: permittivity placeholder differs")
        if finite(actual.get("lossTangent")) != finite(values.get("Loss Tangent")):
            raise AuditError(f"layer {layer_id}: loss-tangent placeholder differs")
        decoded.append(
            {
                "layer_id": layer_id,
                "layer": values.get("Layer"),
                "layer_type": values.get("Layer Type"),
                "physical_type": values.get("Type"),
                "material": actual.get("material"),
                "native_thickness_mil": actual_mil,
                "decoded_thickness_mm": round(actual_mm, 9),
                "expected_thickness_mm": expected_mm,
                "error_mm": round(error_mm, 9),
                "permittivity_ui_placeholder": actual.get("permittivity"),
                "loss_tangent_ui_placeholder": actual.get("lossTangent"),
                "z_index": actual.get("zIndex"),
            }
        )

    six_copper_ids = [1, 15, 16, 17, 18, 2]
    for layer_id in six_copper_ids:
        body = source_layers[layer_id][1]
        if body.get("use") is not True or body.get("show") is not True:
            raise AuditError(f"copper layer {layer_id} is not enabled and visible")
    if any(source_layers[layer_id][1].get("use") is not False for layer_id in range(19, 47)):
        raise AuditError("unused Inner5..Inner32 layer unexpectedly enabled")

    types = Counter(row["physical_type"] for row in decoded)
    expected_types = Counter({
        "Copper": 6,
        "Substrate": 5,
        "SolderMask Layer": 2,
        "PasteMask Layer": 2,
        "Silk Layer": 2,
    })
    if types != expected_types:
        raise AuditError(f"physical layer type inventory differs: {types!r}")
    native_sum_mm = sum(row["decoded_thickness_mm"] for row in decoded)
    expected_sum_mm = sum(row["expected_thickness_mm"] for row in decoded)
    if abs(expected_sum_mm - 1.58) > 1e-9:
        raise AuditError(f"UI plan thickness sum {expected_sum_mm!r} != 1.58 mm")
    if abs(native_sum_mm - 1.58) > len(decoded) * THICKNESS_TOLERANCE_MM:
        raise AuditError(f"decoded native thickness sum {native_sum_mm!r} differs from 1.58 mm")

    rule_templates = [
        body.get("name")
        for header, body in source_rows
        if header.get("type") == "RULE_TEMPLATE"
    ]
    if rule_templates != ["JLCPCB Capability(Multiple Layers Board)"]:
        raise AuditError(f"unexpected design-rule template {rule_templates!r}")

    report = {
        "schema": "stm32h747-final-native-physical-stack-audit-v1",
        "status": "pass-static-six-layer-stack-not-impedance-or-manufacturing-approval",
        "manufacturing_approved": False,
        "inputs": {
            "checkpoint": {"path": str(checkpoint), "sha256": sha256(checkpoint), "bytes": checkpoint.stat().st_size},
            "pcb_source": {"path": str(source), "sha256": sha256(source), "bytes": source.stat().st_size},
            "ui_stack_plan": {"path": str(plan_path), "sha256": sha256(plan_path), "bytes": plan_path.stat().st_size},
        },
        "identity": {"pcb_uuid": args.target_uuid},
        "inventory": {
            "logical_layer_records": len(source_layers),
            "physical_layer_records": len(source_phys),
            "physical_types": dict(sorted(types.items())),
            "enabled_copper_layer_ids_top_to_bottom": six_copper_ids,
            "unused_inner_layer_ids_disabled": list(range(19, 47)),
        },
        "thickness": {
            "ui_plan_total_mm": round(expected_sum_mm, 9),
            "native_decoded_total_mm": round(native_sum_mm, 9),
            "maximum_per_layer_decode_error_mm": round(max_error, 9),
            "tolerance_per_layer_mm": THICKNESS_TOLERANCE_MM,
        },
        "physical_stack_top_to_bottom": decoded,
        "persistence": {
            "source_checkpoint_layer_id_sets_equal": True,
            "source_checkpoint_all_64_layer_bodies_exact": True,
            "source_checkpoint_all_17_physical_bodies_exact": True,
        },
        "design_rule_template": rule_templates[0],
        "checks": {
            "six_copper_layers_enabled": True,
            "five_fr4_dielectrics_present": True,
            "two_solder_mask_layers_present": True,
            "physical_thickness_is_1_58_mm_with_native_rounding": True,
            "portable_checkpoint_preserves_all_stack_records": True,
        },
        "limitations": [
            "The Gerber job does not specify dielectric constant or loss tangent; stored Dk/Df values are unchanged EasyEDA UI placeholders and are not verified impedance parameters.",
            "This stack audit does not approve impedance, material procurement, fabrication tolerances, DRC, or manufacturing release.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "inventory": report["inventory"], "thickness": report["thickness"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
