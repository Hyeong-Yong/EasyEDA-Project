"""Independent, offline operating-point review; never calls an EDA/native API."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_source(path: Path):
    result = []
    for line in path.read_text(encoding="utf8").splitlines():
        fields = line.split("||")
        if len(fields) > 1:
            result.append((json.loads(fields[0]), json.loads(fields[1].rstrip("|"))))
    return result


def main():
    plan_path = HERE / "schematic-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf8"))
    inputs = []
    values = {}
    for page in plan["pages"]:
        path = Path(page["candidatePath"])
        rows = read_source(path)
        attrs = {}
        for h, b in rows:
            if h["type"] == "ATTR":
                attrs.setdefault(b["parentId"], {})[b["key"]] = b.get("value")
        for a in attrs.values():
            if "Designator" in a:
                values[a["Designator"]] = {k: a.get(k) for k in ("Value", "Tolerance", "Voltage Rating", "Dielectric", "Temperature Coefficient")}
        inputs.append({"path": str(path), "sha256": sha(path), "matches_plan_sha256": sha(path) == page["candidateSha256"]})

    n = 10
    rs, rpd, rpre, cpre = 50.0, 100000.0, 3320.0, 10e-9
    rin, rf, cf, rbucket, cbucket = 4000.0, 2800.0, 10e-9, 47.0, 10e-9
    vref, rtop, rbottom = 2.5, 15800.0, 10000.0
    vplus = vref * rbottom / (rtop + rbottom)
    gain, noise_gain = -rf / rin, 1 + rf / rin
    center = noise_gain * vplus
    rsource_thevenin = rs * rpd / (rs + rpd)
    source_load = rpd / (rs + rpd)
    f1 = 1 / (2 * math.pi * (rpre + rsource_thevenin) * cpre)
    f2 = 1 / (2 * math.pi * rf * cf)
    a = 1 / (f1 * f1 * f2 * f2)
    b = 1 / (f1 * f1) + 1 / (f2 * f2)
    f3 = math.sqrt((-b + math.sqrt(b * b + 4 * a)) / (2 * a))
    fbucket = 1 / (2 * math.pi * rbucket * cbucket)
    ac = {}
    for f in (60, 7800, 1000000):
        h = 1 / math.sqrt((1 + (f / f1) ** 2) * (1 + (f / f2) ** 2))
        ac[str(f)] = {"gain_relative_to_dc": h, "attenuation_db": 20 * math.log10(h), "phase_deg": -180 / math.pi * (math.atan(f / f1) + math.atan(f / f2))}

    buffer_source = max(0, (2 - vplus) / rin)
    buffer_sink = max(0, (vplus + 2) / rin)
    iq_opa189_hot_max = 1.8e-3
    iq_ref_hot_max = 1.2e-3
    ref_divider_load = vref / (rtop + rbottom)
    positive_current = 11 * iq_opa189_hot_max + iq_ref_hot_max + ref_divider_load + n * buffer_source
    rfeed_worst = 4.7 * 1.01
    afe_min = 4.75 - positive_current * rfeed_worst
    negative_load = n * iq_opa189_hot_max + n * buffer_sink + 1.186 / 10000
    negative_raw_load = negative_load + .5e-3 + 2e-6
    # 80% is an engineering allowance, NOT a guaranteed converter efficiency.
    pump_input_allowance = negative_raw_load / .8 + .7e-3
    pump_input_min = 4.75 - pump_input_allowance * rfeed_worst
    vnegative = -1.186 * (1 + 15400 / 10000)
    vnegative_conservative_abs = abs(vnegative) * 1.03 + 1.186 * (15400 / 10000) * (.001 * 2 / (1 - .001)) + 1e-6 * 15400
    raw25 = pump_input_min - negative_raw_load * 15
    required_raw_abs = vnegative_conservative_abs + .5 + .05
    allowable_rout = (pump_input_min - required_raw_abs) / negative_raw_load

    csamp, dv, tacq = 16e-12, 3.3, 5e-6
    shared_step = dv * csamp / (csamp + cbucket)
    bucket_tau = rbucket * (csamp + cbucket)
    residual = shared_step * math.exp(-tacq / bucket_tau)
    lsb = 3.3 / 65536
    runtime = plan["allPinContracts"]
    checks = {
        "ten_front_opamps_plus_one_offset_opamp": all(runtime[f"U{i}"]["5"] == "+5V_AFE" for i in range(20, 30)) and runtime["U32"]["5"] == "+5V_AFE",
        "only_ten_front_opamps_use_negative_rail": all(runtime[f"U{i}"]["2"] == "-3V_AFE" for i in range(20, 30)) and runtime["U32"]["2"] == "GND",
        "final_ten_opa320_remain_original_3v3": all(runtime[f"U{i}"]["5"] == "+3V3" and runtime[f"U{i}"]["2"] == "GND" for i in range(10, 20)),
        "negative_ldo_pin_contract": runtime["U31"] == {"1": "GND", "2": "AFE_VNEG_RAW", "3": "AFE_VNEG_RAW", "4": "AFE_NEG_FB", "5": "-3V_AFE"},
        "negative_divider_orientation": runtime["R198"] == {"1": "-3V_AFE", "2": "AFE_NEG_FB"} and runtime["R199"] == {"1": "GND", "2": "AFE_NEG_FB"},
        "offset_buffer_feedback_before_1k_output_isolator": runtime["U32"]["1"] == runtime["U32"]["4"] == runtime["R204"]["1"] == "AFE_OFFSET_BUFFER" and runtime["R204"]["2"] == runtime["C159"]["1"] == "ADC_OFFSET_0V97",
        "no_independent_vdda_regulator_fitted": plan["independentVddaRegulatorFitted"] is False,
        "all_candidate_hashes_match_current_plan": all(x["matches_plan_sha256"] for x in inputs),
    }
    required_values = {"R197": "4.7", "R198": "15.4k", "R199": "10.0k", "R200": "4.7", "R201": "1.0", "R202": "15.8k", "R203": "10.0k", "R204": "1.00k", "C105": "1uF", "C155": "10nF", "C104": "4.7uF", "C159": "4.7uF"}
    checks["fixed_power_reference_values_match_review"] = all(values.get(k, {}).get("Value") == v for k, v in required_values.items())

    report = {
        "schema": "adc10-labtool-independent-design-review-20261018-v1",
        "status": "PASS_OPERATING_POINT_AND_BOUNDED_IDEAL_CALCULATIONS_WITH_EXPLICIT_QUALIFICATIONS" if all(checks.values()) else "FAIL_OFFLINE_CONTRACT",
        "implementation_by_this_review": False,
        "native_api_used": False,
        "pcb_modified": False,
        "firmware_modified": False,
        "manufacturing_approved": False,
        "test_dac8562_access": False,
        "plan_sha256": sha(plan_path),
        "inputs": inputs,
        "checks": checks,
        "scope": "Powered normal operation, SMA connector voltage within -2..+2V, 50-ohm source, DC/60Hz and several-kHz signal bandwidth. No fault/startup/overvoltage certification; no claim of measured noise or native/ERC/DRC success.",
        "dc": {"vplus_v": vplus, "adc_offset_v": center, "gain_from_sma_v_per_v": gain, "gain_from_ideal_generator_emf_v_per_v": gain * source_load, "adc_points_from_actual_sma_v": {str(v): center + gain * v for v in (-2, 0, 2)}, "adc_points_from_50ohm_generator_emf_v": {str(v): center + gain * source_load * v for v in (-2, 0, 2)}, "open_sma_ideal_v": 0, "open_adc_ideal_v": center, "source_loading_error_percent": 100 * (1 - source_load), "sign_inversion_requires_calibration": True, "exact_0_and_3v3_endpoints_claimed": False, "headroom_at_assumed_main_3v3_minus5percent_v": 3.135 - (center + 1.4)},
        "filter": {"input_pole_hz_with_50ohm_source": f1, "feedback_signal_pole_hz": f2, "combined_signal_minus3db_hz": f3, "response": ac, "feedback_noise_gain_dc": noise_gain, "feedback_noise_gain_high_frequency": 1, "offset_divider_pole_hz_4u7": 1 / (2 * math.pi * (rtop * rbottom / (rtop + rbottom)) * 4.7e-6), "offset_output_isolation_pole_hz_1k_4u7": 1 / (2 * math.pi * 1000 * 4.7e-6), "front_open_decay_tau_s": (rpd + rpre) * cpre, "anti_alias_16bit_guarantee": False, "one_mhz_waveform_supported": False},
        "power": {"supply_assumption_v": [4.75, 5.25], "positive_feed_resistor_nominal_ohm": 4.7, "positive_feed_resistor_max_1percent_ohm": rfeed_worst, "opa189_hot_iq_max_A_each": iq_opa189_hot_max, "positive_amp_count": 11, "negative_amp_count": 10, "ref5025_hot_iq_max_A": iq_ref_hot_max, "ref_dc_divider_load_A": ref_divider_load, "front_buffer_source_max_A_each": buffer_source, "front_buffer_sink_max_A_each": buffer_sink, "positive_feed_normal_dc_bound_A": positive_current, "positive_feed_min_v_excluding_ac_ripple_and_startup": afe_min, "opa189_cm_max_at_that_min_supply_v": afe_min - 2.5, "opa189_cm_margin_above_plus2_v": afe_min - 2.5 - 2, "positive_feed_dissipation_W": positive_current ** 2 * rfeed_worst, "positive_filter_nominal_total_uF_including_all_decoupling": 11.5, "positive_filter_nominal_pole_hz": 1 / (2 * math.pi * 4.7 * 11.5e-6), "negative_ldo_nominal_v": vnegative, "negative_divider_current_A": 1.186 / 10000, "negative_ldo_load_dc_bound_A": negative_load, "negative_raw_load_allowance_A_including_max_legacy_ignd_and_en": negative_raw_load, "pump_input_current_engineering_allowance_A_at_assumed_80percent_efficiency": pump_input_allowance, "efficiency_allowance_not_datasheet_guarantee": True, "pump_input_min_v_in_that_engineering_scenario": pump_input_min, "raw_negative_magnitude_v_at_15ohm_rout_25C_scenario": raw25, "negative_ldo_output_conservative_magnitude_v_including_extra_error_terms": vnegative_conservative_abs, "required_raw_negative_magnitude_v_including_0p5dropout_and_50mVripple_reserve": required_raw_abs, "maximum_acceptable_pump_rout_ohm_in_same_scenario": allowable_rout, "pump_rout_full_temperature_guaranteed": False, "pump_60mA_output_limit_margin_A": .06 - negative_raw_load, "negative_ldo_dissipation_upper_estimate_W_using_raw5p25": (5.25 - abs(vnegative)) * negative_load + 5.25 * .5e-3, "additional_plus5_dc_engineering_budget_A": positive_current + pump_input_allowance, "main_3v3_opa320_hot_iq_plus_feedback_source_allowance_A": 10 * 1.85e-3 + n * buffer_sink, "main_3v3_vdda_vref_power_domain_preserved": True, "new_12v_input_support": False},
        "adc_bucket": {"resistor_ohm": rbucket, "capacitor_F": cbucket, "pole_hz": fbucket, "ideal_tau_s": rbucket * cbucket, "assumed_adc_sampling_capacitor_F_not_verified_stm_value": csamp, "assumed_adjacent_channel_voltage_step_v": dv, "ideal_charge_sharing_step_v": shared_step, "ideal_recovery_tau_including_csamp_s": bucket_tau, "required_documented_initial_acquisition_time_s": tacq, "ideal_residual_v_after5us": residual, "half_lsb_16bit_at3v3_v": lsb / 2, "ideal_model_residual_below_half_lsb": residual < lsb / 2, "maximum_acquisitions_per_second_per_adc_4channels": 4 * 15600, "four_channel_acquisition_only_duty_at5us": 4 * 15600 * tacq, "firmware_sample_time_verified": False, "native_adc_internal_switch_impedance_and_parasitics_modelled": False, "opamp_stability_guaranteed_by_rc_alone": False},
        "noise": {"ref5025_classic_low_frequency_noise_typ_uVpp_without_nr": 7.5, "ref_to_adc_dc_noise_gain": noise_gain * rbottom / (rtop + rbottom), "adc_ref_noise_typ_uVpp_before_nr_and_filter": 7.5 * noise_gain * rbottom / (rtop + rbottom), "nr_1uF_typ_total_noise_reduction_qualifier": "Datasheet describes about half overall noise; not a guaranteed spectral/integrated bound for this complete circuit.", "opa320_white_voltage_noise_estimate_uVrms_7nV_sqrtHz_through_bucket_only": 7e-9 * math.sqrt(math.pi / 2 * fbucket) * 1e6, "opa320_white_voltage_noise_estimate_uVrms_8p5nV_sqrtHz_through_bucket_only": 8.5e-9 * math.sqrt(math.pi / 2 * fbucket) * 1e6, "estimate_excludes_adc_own_noise_reference_gain_noise_low_frequency_noise_and_full_transfer": True, "bucket_47ohm_johnson_equivalent_kTC_uVrms_300K": math.sqrt(1.380649e-23 * 300 / cbucket) * 1e6, "do_not_double_count_kTC_and_integrated_same_resistor_noise": True, "mcu_vref_still_filtered_main3v3": True, "measured_noise_reduction_claim": False},
        "open_input": {"sma_pulldown_ohm": rpd, "opa189_max_bias_current_A_25C": 300e-12, "opa189_max_bias_current_A_0to85C": 1e-9, "opa189_max_bias_current_A_minus40to125C": 10e-9, "worst_open_input_bias_offset_v_full_temperature": 10e-9 * (rpd + rpre), "worst_open_adc_bias_offset_v_full_temperature": 10e-9 * (rpd + rpre) * abs(gain), "not_included": ["external connector/PCB leakage", "opamp offset", "reference/gain errors"], "literal_adc_pin_0v_when_open": False},
        "remaining_qualifications": ["The 5V rail must remain within4.75..5.25V under the complete board load; no12V direct input.", "OPA189 upper common-mode margin must also cover actual+5AFE ripple, supply tolerance, resistor tolerance and transients; the normal-DC bound is not a startup proof.", "TPS60403 output resistance15ohm is limited to25C specified condition. Confirm temperature/capacitor-effective-value/startup/dropout margin with the actual converter and board.", "TPS723 new/legacy variants have different electrical/startup conditions. Selected15.4k/10k orientation andEN-to-IN are correct; effective outputC/ESR andCFF must match the selected variant.", "REF5025AI classic is NOT REF5025E.1ohm series output-capacitor ESR is intentional; theNR1uF and two offset LPFs delay startup. Wait for measured settling before using conversions.", "Offset buffer feedback must be beforeR2041k. The large downstream4.7uF is not placed directly inside the follower loop.", "Powered-off inputs and overvoltage/ESD protection are unqualified. Do not infer rail-sinking/back-power safety merely because an individual opamp input current is below absolute maximum.", "Final OPA320 andMCUVDDA/VREF stay on the existing3.3V domain; separate-rail sequencing proposal was rejected and is not fitted.", "47ohm/10nF is a reasonable prospective charge-reservoir/noise tradeoff, not proof of zero crosstalk. Verify>=5us actual sample acquisition, first-after-channel-change behavior and worst-case adjacent-channel step on hardware.", "Signal feedback filtering does not remove all post-amplifier noise. ADC reference noise, own converter noise, layout, finite PSRR and aliasing remain.", "This report audits fixed design calculations and declared candidate pin contracts only, not native geometric connectivity, libraries/footprints, ERC, DRC or CAM."],
        "primary_sources": {"OPA189": "https://www.ti.com/lit/ds/symlink/opa189.pdf", "OPA320": "https://www.ti.com/lit/ds/symlink/opa320.pdf", "TPS60403": "https://www.ti.com/lit/ds/symlink/tps60403.pdf", "TPS723": "https://www.ti.com/lit/ds/symlink/tps723.pdf", "REF5025": "https://www.ti.com/lit/ds/symlink/ref50.pdf", "STM32H747": "https://www.st.com/resource/en/datasheet/stm32h747xi.pdf"},
    }
    destination = HERE / "independent-design-review.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"path": str(destination), "sha256": sha(destination), "status": report["status"], "checks": checks, "v_adc_range": report["dc"]["adc_points_from_actual_sma_v"], "positive_min": afe_min, "cm_margin": afe_min - 4.5, "ideal_bucket_residual_uV": residual * 1e6}, ensure_ascii=False))


if __name__ == "__main__":
    main()
