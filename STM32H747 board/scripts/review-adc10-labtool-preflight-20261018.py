"""Read-only native design inventory and preliminary AFE calculations.

Writes a review report only. Never modifies a native schematic, PCB, or library.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/candidates/adc10-labtool-20261018"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path: Path) -> list[dict]:
    result = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "||" not in line:
            continue
        head, body = line.split("||", 1)
        body = body.removesuffix("|")
        result.append({"h": json.loads(head), "b": json.loads(body) if body else ""})
    return result


def compare(before_path: Path, captured_path: Path) -> dict:
    # View state and editor client identity are not electrical/physical edits.
    excluded = {"DOCHEAD", "CANVAS"}
    before = records(before_path)
    captured = records(captured_path)
    keyed = lambda rows: {
        (r["h"]["type"], r["h"]["id"]): r["b"]
        for r in rows if r["h"]["type"] not in excluded
    }
    a, b = keyed(before), keyed(captured)
    delta = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
    return {
        "previous_path": str(before_path.relative_to(ROOT)),
        "captured_path": str(captured_path.relative_to(ROOT)),
        "previous_sha256": digest(before_path),
        "captured_sha256": digest(captured_path),
        "record_counts": dict(Counter(r["h"]["type"] for r in captured)),
        "excluded_types": sorted(excluded),
        "changed_non_view_record_count": len(delta),
        "changed_non_view_records": [list(k) for k in delta],
    }


def main() -> None:
    sch = ROOT / "output/validation/native-adc10-sch-labtool_before-20261018.epru"
    pcb = ROOT / "output/validation/native-adc10-pcb-labtool_before-20261018.epru"
    checkpoint = ROOT / "output/checkpoints/STM32H747_before_labtool_afe_20261018.epro2"
    for path in (sch, pcb, checkpoint):
        if not path.is_file():
            raise RuntimeError(f"Missing required native capture: {path}")
    sch_rows = records(sch)
    pcb_rows = records(pcb)
    if sch_rows[0]["b"].get("uuid") != "a07bf8e4331877a8":
        raise RuntimeError("Wrong schematic page")
    if pcb_rows[0]["b"].get("uuid") != "0ac2a19168000d8e":
        raise RuntimeError("Wrong PCB")

    # Illustrative fixed-range inverting shifter, NOT an applied design.
    rin, rf = 4000.0, 3000.0
    ref, rtop, rbottom = 2.5, 16500.0, 10000.0
    vplus = ref * rbottom / (rtop + rbottom)
    gain = -rf / rin
    offset = (1 - gain) * vplus
    source_r, pulldown = 50.0, 1_000_000.0
    attenuation = pulldown / (pulldown + source_r)
    report = {
        "schema": "adc10-labtool-preflight-20261018-v1",
        "status": "preliminary_review_pending_bandwidth_choice",
        "native_design_modified": False,
        "native_library_modified": False,
        "firmware_modified": False,
        "manufacturing_approved": False,
        "project_name": "STM32H747_MCU_BOARD_v19",
        "project_uuid": "761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c",
        "dedicated_window_id": "25441fd2-fc1e-49ec-800a-41d996a74f69",
        "recovery_checkpoint": {"path": str(checkpoint.relative_to(ROOT)), "bytes": checkpoint.stat().st_size, "sha256": digest(checkpoint)},
        "baseline_comparisons": {
            "schematic": compare(ROOT / "output/validation/native-adc10-sch-reopened-20261017.epru", sch),
            "pcb": compare(ROOT / "output/validation/native-adc10-pcb-routed_reopen_probe-20261018.epru", pcb),
        },
        "scope": {"connectors": [f"J{i}" for i in range(2, 12)], "channel_count": 10, "preserve_mcu_pins": True, "preserve_dc": True, "ac_coupling": False, "automatic_ground_switch": False, "test_dac8562_access": False},
        "verified_power_inventory": {
            "available_rails": ["+5V", "+3V3", "+1V8", "GND"],
            "existing_negative_rail": False,
            "adc_vdda_path": "+3V3 -> FB2 -> VDDA",
            "adc_vref_positive_path": "VDDA -> R71 (0 ohm) -> VREF+",
            "existing_bias_reference_is_adc_vref": False,
            "opa320_total_supply_max_v": 5.5,
        },
        "proposed_architecture_not_applied": [
            "GND-referenced input with pulldown; no positive-bias resistor connected to SMA",
            "DC-coupled bipolar-capable input buffer with adequate negative supply headroom",
            "Post-buffer inverting attenuator/level shifter, low-noise filtered buffered offset",
            "Per-channel ADC kickback isolation and charge reservoir, with settling verification",
            "Review VDDA/VREF+ noise as well as offset-reference noise",
        ],
        "illustrative_dc_calculation_only": {
            "rin_ohm": rin, "rf_ohm": rf,
            "reference_v": ref, "divider_top_ohm": rtop, "divider_bottom_ohm": rbottom,
            "vplus_v": vplus, "gain_from_buffer": gain, "adc_offset_v": offset,
            "input_pulldown_ohm": pulldown, "source_impedance_ohm": source_r,
            "source_loading_ratio": attenuation,
            "points": [{"source_v": v, "adc_v": offset + gain * attenuation * v} for v in (-2, 0, 2)],
            "open_input_adc_v_ideal": offset,
            "open_input_sma_v_ideal": 0.0,
            "polarity": "inverting; user firmware calibration must use this sign",
            "offset_reference_noise_gain": (1 - gain) * rbottom / (rtop + rbottom),
            "reference_divider_10uF_pole_hz_ideal": 1 / (2 * math.pi * (rtop * rbottom / (rtop + rbottom)) * 10e-6),
            "not_validated": ["component tolerances", "temperature", "startup", "opamp models", "overload protection", "noise integration", "filter response", "layout", "ERC", "DRC"],
        },
        "pending_decision": {
            "question": "Prioritize DC/60Hz low noise with several-kHz bandwidth, pass 1MHz, or use component-population alternatives?",
            "existing_samples_per_second_per_channel": 15600,
            "nyquist_hz": 7800,
            "one_mhz_waveform_acquisition_supported_at_existing_sampling": False,
            "native_application_must_wait_for_filter_and_driver_bandwidth_contract": True,
        },
        "required_before_manufacturing": ["final part and power budget selection", "independent electrical review", "10-channel schematic ERC and pin-net audit", "PCB ECO with protected geometry preservation", "full strict 18-rule DRC without waivers", "reopened saved source and netlist verification", "CAM and hardware validation"],
        "primary_sources": {
            "labtool": "https://github.com/embeddedartists/labtool",
            "opa192_candidate": "https://www.ti.com/lit/ds/symlink/opa192.pdf",
            "opa320_existing": "https://www.ti.com/lit/ds/symlink/opa320.pdf",
            "reference_candidate": "https://www.ti.com/lit/ds/symlink/ref50.pdf",
            "charge_pump_candidate": "https://www.ti.com/lit/ds/symlink/tps60403.pdf",
            "analog_ldo_candidate": "https://www.ti.com/lit/ds/symlink/tps7a20.pdf",
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "preflight-review.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "native_design_modified": False, "baseline_changes": {k: v["changed_non_view_record_count"] for k, v in report["baseline_comparisons"].items()}, "illustrative_endpoints_v": [p["adc_v"] for p in report["illustrative_dc_calculation_only"]["points"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
