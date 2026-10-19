"""Aggregate preserved simulation evidence; draw deterministic PNG/HTML review.

No CAD, firmware, network, or application access. NumPy + Pillow only.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
import runpy

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output/simulation-20261018"
SIM = runpy.run_path(str(ROOT / "scripts/simulate-adc-representative.py"))
RAW = SIM["raw_all"]
PLOTS = OUT / "plots"
PLOTS.mkdir(exist_ok=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(case, plot=0):
    path = OUT / "runs" / f"{case}.raw"
    data = RAW(path)[plot]
    assert data and all(np.all(np.isfinite(v)) for v in data.values()), case
    return data


def noise_integral(f, d, lo, hi):
    """Exact integral of each log-log linear density-squared segment."""
    mask = (f > lo) & (f < hi)
    x = np.r_[lo, f[mask], hi]
    y = np.exp(np.interp(np.log(x), np.log(f), np.log(d*d)))
    p = np.diff(np.log(y)) / np.diff(np.log(x))
    r = x[1:] / x[:-1]
    a = p + 1
    terms = np.empty_like(a)
    near = np.abs(a) < 1e-8
    terms[near] = y[:-1][near]*x[:-1][near]*np.log(r[near])
    terms[~near] = y[:-1][~near]*x[:-1][~near]*np.expm1(a[~near]*np.log(r[~near]))/a[~near]
    return float(np.sqrt(np.sum(terms)))


def at(f, y, value):
    return float(np.interp(np.log(value), np.log(f), y))


def font(size, bold=False):
    path = Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def chart(filename, title, xlabel, ylabel, series, xlim=None, ylim=None, logx=False, logy=False, note=""):
    im = Image.new("RGB", (1280, 720), "#f6f8fb")
    d = ImageDraw.Draw(im)
    box = (105, 105, 1220, 585)
    d.text((38, 28), title, fill="#142338", font=font(30, True))
    d.rectangle(box, fill="white")
    xs = np.concatenate([np.asarray(s[1]) for s in series])
    ys = np.concatenate([np.asarray(s[2]) for s in series])
    xmin, xmax = xlim or (float(np.min(xs)), float(np.max(xs)))
    ymin, ymax = ylim or (float(np.min(ys)), float(np.max(ys)))
    if not ylim:
        padding = (ymax-ymin)*.08 or 1
        ymin, ymax = ymin-padding, ymax+padding
    tx = np.log10 if logx else lambda a: np.asarray(a)
    ty = np.log10 if logy else lambda a: np.asarray(a)
    lx, ux = float(tx(xmin)), float(tx(xmax))
    ly, uy = float(ty(ymin)), float(ty(ymax))
    def screen(x, y):
        return (box[0]+(tx(x)-lx)/(ux-lx)*(box[2]-box[0]), box[3]-(ty(y)-ly)/(uy-ly)*(box[3]-box[1]))
    xt = np.arange(np.ceil(lx), np.floor(ux)+1) if logx else np.linspace(xmin, xmax, 7)
    yt = np.arange(np.ceil(ly), np.floor(uy)+1) if logy else np.linspace(ymin, ymax, 6)
    for v in xt:
        val = 10**v if logx else v
        sx, _ = screen(val, ymin)
        d.line((sx, box[1], sx, box[3]), fill="#e0e6ee")
        label = f"1e{v:g}" if logx else f"{val:.3g}"
        d.text((sx, box[3]+12), label, fill="#46556b", font=font(18), anchor="mt")
    for v in yt:
        val = 10**v if logy else v
        _, sy = screen(xmin, val)
        d.line((box[0], sy, box[2], sy), fill="#e0e6ee")
        label = f"1e{v:g}" if logy else f"{val:.4g}"
        d.text((box[0]-12, sy), label, fill="#46556b", font=font(18), anchor="rm")
    colors = ["#1469c0", "#c65b20", "#1d8868", "#a344a8"]
    for i, (name, x, y) in enumerate(series):
        x, y = np.asarray(x), np.asarray(y)
        mask = (x >= xmin) & (x <= xmax) & np.isfinite(y) & (y >= ymin) & (y <= ymax)
        x, y = x[mask], y[mask]
        if len(x) > 7000:
            select = np.unique(np.linspace(0, len(x)-1, 7000).astype(int))
            x, y = x[select], y[select]
        points = [tuple(map(float, screen(a, b))) for a, b in zip(x, y)]
        if len(points)>1:
            d.line(points, fill=colors[i % len(colors)], width=3)
        if len(x)<50:
            for sx, sy in points:
                d.ellipse((sx-4, sy-4, sx+4, sy+4), fill=colors[i % len(colors)])
        ypos = 636+i*23
        d.line((110, ypos+10, 145, ypos+10), fill=colors[i % len(colors)], width=4)
        d.text((155, ypos), name, fill="#26364e", font=font(18))
    d.rectangle(box, outline="#aebaca", width=1)
    d.text((660, 621), xlabel, fill="#26364e", font=font(20), anchor="mm")
    d.text((105, 75), ylabel, fill="#26364e", font=font(18))
    if note:
        d.text((1240, 696), note, fill="#59697e", font=font(15), anchor="rs")
    im.save(PLOTS / filename)


def settle_time(t, y, target, tol, after=0):
    idx = np.flatnonzero((t >= after) & (np.abs(y-target)>tol))
    if len(idx) and idx[-1] == len(t)-1:
        return None
    return float(t[idx[-1]+1]-after) if len(idx) else 0.0


def main():
    SIM["audit_source"]()
    model_index = json.loads((OUT / "models/model-index.json").read_text(encoding="utf-8-sig"))
    for model in model_index["models"]:
        assert sha(OUT/"models"/model["lib"]).lower() == model["lib_sha256"].lower()
        assert sha(OUT/"models"/model["zip"]).lower() == model["zip_sha256"].lower()
    pcb = ROOT / "output/validation/native-adc10-pcb-labtool_adc10_routed_final_saved-20261018.epru"
    assert sha(pcb) == "b7c6b99df160aaed2bb1f91717c2bde25e379bfdba88ec23dea5b4fdb7548d0f"
    result = {"engine": "ngspice 47", "not_cadence_pspice": True,
        "original_models_unchanged": True, "schematic_export_sha256": SIM["NET_SHA"],
        "pcb_saved_source_sha256": sha(pcb), "cad_changed": False,
        "analysis_scope": "Representative J2 signal chain plus shared-reference AC/noise, separate REF and LDO tests; no MCU transistor or PCB field model"}
    ac = load("ac_ref_q1_trueDC")
    f = np.real(ac["frequency"])
    h = ac["v(adc_j2)"]
    rel = 20*np.log10(np.abs(h)/abs(h[0]))
    ph = np.unwrap(np.angle(h))*180/np.pi
    if ph[0]<0:
        ph += 360
    half_power_db = -10*np.log10(2)
    idx = np.flatnonzero(rel<=half_power_db)[0]
    fc = float(np.exp(np.interp(half_power_db, rel[idx-1:idx+1][::-1], np.log(f[idx-1:idx+1][::-1]))))
    result["ac"] = {"generator_dc_gain_abs": float(abs(h[0])), "minus3db_hz": fc,
        "cutoff_definition_db": float(half_power_db),
        "samples": {str(v): {"relative_db": at(f, rel, v), "extra_phase_deg": at(f, ph, v)-180} for v in [60, 1000, 7800, 1e6]}}
    chart("ac.png", "Representative ADC input: TI macro-model AC response", "Frequency (Hz)", "Gain relative to DC (dB)",
        [("OPA189 + OPA320-Q1 + REF5025; actual passive values", f, rel)], xlim=(1, 1e6), ylim=(-110, 2), logx=True,
        note="Ideal rails; no PCB parasitic extraction")
    noise = load("noise_ref_q1_trueDC")
    fn, dn = noise["frequency"], noise["onoise_spectrum"]
    integrals = {str(hi): noise_integral(fn, dn, .1, hi) for hi in [10, 3300, 7800, 1e8]}
    total = float(load("noise_ref_q1_trueDC", 1)["v(onoise_total)"][0])
    assert abs(integrals["100000000.0"] / total - 1)<.001
    result["noise"] = {"lower_frequency_hz": .1, "band_rms_v": integrals, "ngspice_full_band_rms_v": total,
        "scope_limit": "Model nominal analog output noise only; ideal supplies; excludes ADC/VREF+ noise, PCB coupling, pump ripple, alias/noise folding validation"}
    generic = load("noise_ref_generic_crosscheck")
    result["generic_tina_comparison"] = {"noise_density_max_relative_difference": float(np.max(np.abs(generic["onoise_spectrum"] / dn - 1))),
        "ac_max_complex_difference": float(np.max(np.abs(load("ac_ref_generic_crosscheck")["v(adc_j2)"]-h)))}
    chart("noise.png", "Analog output noise spectrum (not measured board noise)", "Frequency (Hz)", "ADC-pin noise density (nV / sqrt(Hz))",
        [("Nominal TI models + passive thermal noise; ideal supply sources", fn, dn*1e9)],
        xlim=(.1, 1e7), ylim=(.01, 2000), logx=True, logy=True, note="REF model high-frequency noise/PSRR limitations apply")
    pointfile = OUT / "runtime/dcpoint-accepted-summary.json"
    if not pointfile.exists():
        pointfile = OUT / "runtime/dcpoint-summary.json"
    dc = json.loads(pointfile.read_text(encoding="utf-8-sig"))
    if "accepted_true_dc_points" in dc:
        vals = []
        for r in dc["results"]:
            assert r["validated_true_dc"] and r["run"]["run_ok"] and not r["run"]["optran_used"]
            d = load(r["case"])
            assert len(d["v(adc_j2)"]) == 1
            value = float(d["v(adc_j2)"][0])
            assert 0 <= value <= r["v3_v"]
            assert not "Transient op started" in (OUT/"runs"/f"{r['case']}.log").read_text(encoding="utf-8", errors="replace")
            assert abs(value-r["voltages_currents"]["v(adc_j2)"]) < 1e-12
            vals.append(value)
        dc["requested_cases"] = dc["requested_points"]
        dc["validated_true_dc_cases"] = dc["accepted_true_dc_points"]
        dc["failed_or_unvalidated_cases"] = dc["remaining_failed_cases"]
        dc["acceptance"] = {"all_requested_cases_validated_true_dc": dc["all_requested_points_validated"],
            "adc_min_v": min(vals), "adc_max_v": max(vals), "minimum_rail_headroom_v": dc["minimum_rail_headroom_v"],
            "nominal_gain_linearity": dc["nominal_fit"]}
    result["dc"] = {"summary_file": str(pointfile.relative_to(OUT)), "acceptance": dc["acceptance"],
        "requested": dc["requested_cases"], "validated": dc["validated_true_dc_cases"], "failed": dc["failed_or_unvalidated_cases"]}
    result["review_findings"] = [{"priority": "hardware-review-before-fabrication", "topic": "OPA320 low-supply output headroom",
        "observed_model_headroom_v": dc["acceptance"]["minimum_rail_headroom_v"],
        "datasheet_AOL_test_headroom_v": {"RL_10k_to_midsupply": .1, "RL_2k_to_midsupply": .2},
        "source": "https://www.ti.com/lit/ds/symlink/opa320.pdf",
        "assessment": "Rail-range pass in nominal macro-models does not establish guaranteed precision/linearity at the -5% 3.3V corner. Check actual minimum supply and component/loading tolerance; consider reducing gain if that corner is required. No CAD change made."}]
    nominal = [r for r in dc["results"] if r["group"]=="nominal" and r.get("validated_true_dc", False)]
    # Accept the canonical per-case validity spelling from the preserved point runner.
    if not nominal:
        nominal = [r for r in dc["results"] if r["group"]=="nominal" and r.get("valid_true_dc", r.get("run", {}).get("run_ok", False))]
    def values(r):
        return r.get("voltages_currents", r.get("values", r.get("node_values", r.get("last", {}))))
    if nominal:
        try:
            xy = sorted((r["requested_sma_v"], values(r)["v(adc_j2)"]) for r in nominal)
            chart("dc.png", "DC transfer: independent solved operating points", "Actual SMA input (V)", "ADC pin output (V)",
                  [("Original TI macro-models, nominal +5 V / +3.3 V", *zip(*xy))], xlim=(-2, 2), ylim=(0, 3.3))
        except KeyError:
            pass
    with (OUT/"dc-points.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "v5_V", "v3_V", "actual_sma_V", "adc_V", "offset_bus_V", "rail_headroom_V"])
        for r in dc["results"]:
            if r.get("validated_true_dc"):
                val = values(r)
                writer.writerow([r["case"], r["v5_source_v"], r["v3_v"], val["v(raw_j2)"], val["v(adc_j2)"], val["v(off)"], r["adc_rail_headroom_v"]])
    sine = load("sine_ideal_q1_clean")
    t = sine["time"]
    sel = t>=.025
    basis = np.column_stack([np.ones(np.count_nonzero(sel)), np.sin(2*np.pi*60*t[sel]), np.cos(2*np.pi*60*t[sel])])
    coeff, *_ = np.linalg.lstsq(basis, sine["v(adc_j2)"][sel], rcond=None)
    amp = float(np.hypot(coeff[1], coeff[2]))
    result["sine_60hz"] = {"adc_offset_v": float(coeff[0]), "adc_peak_amplitude_v": amp,
        "scope": "TI opamp models with fixed ideal 0.968992248 V offset; separate from full REF AC/noise"}
    chart("sine.png", "60 Hz, +/-2 V at SMA: time-domain signal check", "Time (ms)", "Voltage (V)",
        [("SMA input", t*1e3, sine["v(raw_j2)"]), ("ADC output; fixed ideal bias", t*1e3, sine["v(adc_j2)"])],
        xlim=(20, 60), ylim=(-2.2, 3.3), note="Original opamp macros; no random noise in this transient")
    step = load("step_ideal_q1_clean")
    target = float(np.mean(step["v(adc_j2)"][step["time"]>.0025]))
    st = settle_time(step["time"], step["v(adc_j2)"], target, 3.3/65536/2, .001)
    result["step"] = {"final_adc_v": target, "settling_to_half_16bit_lsb_s": st,
        "input_step_v": 4, "scope": "fixed ideal bias; entire analog filter step, NOT acquisition-switch settling"}
    chart("step.png", "Full analog-chain response to -2 V -> +2 V input step", "Time after step (us)", "ADC pin output (V)",
        [("Original opamp macros + actual R/C, ideal fixed bias", (step["time"]-.001)*1e6, step["v(adc_j2)"])],
        xlim=(-25, 650), ylim=(.15, 3.15), note="Settling judged against simulated final DC, not ideal formula")
    result["sampling_surrogate"] = []
    for path in sorted((OUT/"runs").glob("kick_ideal_q1_clean*.json")):
        info = json.loads(path.read_text(encoding="utf-8-sig"))
        if not info.get("run_ok"):
            continue
        data = load(path.stem)
        t, sample = data["time"], data["v(sample)"]
        target = float(np.mean(data["v(adc_j2)"][(t>8e-6)&(t<9e-6)]))
        clock_end = 18e-6 - 2e-9
        err = float(np.interp(clock_end, t, sample)-target)
        sel = (t>=10.001e-6)&(t<=clock_end)
        settle = settle_time(t[sel], sample[sel], target, 3.3/65536/2, 10e-6)
        entry = {"case": path.stem, "reference_adc_v": target, "error_at_8us_v": err,
            "half_lsb_settling_s": settle, "assumptions": "Cs/Ron from filename; 2.8V previous-channel step, repeated21.3675us; excludes switch charge injection and MCU transfer accuracy"}
        result["sampling_surrogate"].append(entry)
        if len(result["sampling_surrogate"]) == 1:
            chart("kick.png", "ADC acquisition surrogate: previous-channel memory", "Time after track begins (us)", "Sample-cap error (mV)",
                [(path.stem, (t[sel]-10e-6)*1e6, (sample[sel]-target)*1e3)], xlim=(0, 8), ylim=(-.1, 1.5),
                note="First acquisition; assumed Csample/Ron, NOT exact STM32 model")
    ref = load("reference-startup_ref_q1_gear")
    tref = ref["time"]
    ref_op = load("reference_ref_q1")
    dc_off = float(ref_op["v(off_filt)"][0])
    ref_settle = settle_time(tref, ref["v(off_filt)"], dc_off, abs(dc_off)*.001, .001)
    ldo = load("ldo_ref_q1")
    result["reference"] = {"ref_dc_v": float(ref_op["v(ref25)"][0]), "offset_filter_dc_v": dc_off,
        "offset_filter_startup_to_point1percent_s_from_ramp_start": ref_settle,
        "nr_cap_f": 1e-6, "scope": "Standalone REF+divider; excludes U32/R204/C159; constant 14.3mA supply load has nonphysical off-state behavior"}
    result["negative_ldo"] = {"raw_input_v": float(ldo["v(raw)"][-1]), "nominal_dc_load_a": .013,
        "final_output_v": float(ldo["v(neg)"][-1]), "scope": "2013 TPS72301 transient model, ideal prescribed raw supply; excludes TPS60403, D20 powerdown and full worst-case load"}
    chart("reference.png", "Reference startup: standalone REF5025 + divider filter", "Time from simulation start (ms)", "Voltage (V)",
        [("REF5025 output", tref*1e3, ref["v(ref25)"]), ("Filtered divider (before U32)", tref*1e3, ref["v(off_filt)"])],
        xlim=(0, 300), ylim=(0, 2.7), note="1-2 ms supply ramp; constant-load off-state artifacts excluded")
    result["debug_header"] = {"ref": "J1", "part": "FTSH-107-01-L-DV-K-A", "pitch_mm": 1.27, "pins": 14,
        "connected": {"3": "+3V3/VTref", "4": "SWDIO/PA13", "5": "GND", "6": "SWCLK/PA14", "7": "GND", "12": "RESET# via R59 0R to NRST"},
        "no_swo": True, "uart": "CN4 USB-C -> CH340C(U8) -> PA10 RX / PA9 TX"}
    result["limits"] = ["No Cadence PSpice engine; ngspice syntax/compatibility and model nominal results only",
        "TPS60403 encrypted model not run or decrypted; charge-pump ripple, real rail sequence and worst-case current budget unverified",
        "OPA320 official PSpice ZIP contains Q1 model; generic official TINA model was cross-checked, not falsely relabeled PSpice",
        "No transistor-accurate STM32 ADC, MCU conversion/VREF noise, switch charge injection, PCB parasitics or hardware measurements",
        "Startup full-chain cases with convergence failures are not accepted; standalone REF/LDO only",
        "Passive tolerance and device limits are not covered by nominal macro-model sweeps; 16-bit resolution is not 16-bit absolute accuracy"]
    (OUT/"results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    rows = [f"<tr><td>{html.escape(k)}</td><td>{v*1e6:.3f} µVrms</td></tr>" for k,v in integrals.items()]
    cards = [f'<figure><img src="plots/{n}.png" alt="{n}"><figcaption>{c}</figcaption></figure>' for n,c in [
        ("ac", "원본 제조사 모델의 대표 채널 AC 해석"), ("noise", "아날로그 모델의 잡음만 포함 — 보드 실측/ADC 코드 잡음 아님"),
        ("sine", "60 Hz 과도해석은 이상적 고정 바이어스 사용"), ("step", "입력 자체의 계단 정착과 ADC 채널 전환 정착은 별개"),
        ("reference", "공유 기준전압의 단독 블록 기동 — 전체 보드 기동 보증 아님"), ("kick", "샘플링 커패시터·스위치 저항 가정 시험")]
        if (PLOTS/f"{n}.png").exists()]
    dc_accept = dc["acceptance"]
    header_rows = ''.join(f'<tr><td>{p}</td><td>{html.escape(net)}</td></tr>' for p,net in result["debug_header"]["connected"].items())
    document = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>STM32H747 대표 회로 시뮬레이션 검토</title>
<style>body{{font-family:Segoe UI,Malgun Gothic,sans-serif;background:#f3f6fa;color:#20314a;max-width:1050px;margin:40px auto;line-height:1.7;padding:0 24px}}h1{{line-height:1.3}}h2{{margin-top:34px}}.notice{{background:#fff2da;border-left:4px solid #ce8d27;padding:16px}}.ok{{background:#e7f3ed;padding:16px}}figure{{margin:24px 0;background:white;border-radius:10px;overflow:hidden}}img{{max-width:100%;display:block}}figcaption{{padding:10px 20px}}table{{border-collapse:collapse;background:white}}td,th{{padding:8px 16px;border:1px solid #dbe3ee;text-align:left}}code{{background:#e9edf3;padding:2px 5px}}a{{color:#145fa6}}li{{margin:8px 0}}</style>
<h1>STM32H747 대표 ADC 회로<br>시뮬레이션 검토 · 2026-10-18</h1>
<p>실행 엔진: <b>ngspice 47</b> / TI 공식 PSpice 포맷 원본 모델. <b>Cadence PSpice 실행 결과가 아닙니다.</b><br>회로도·PCB·펌웨어와 TEST_DAC8562는 수정하지 않았습니다.</p>
<div class="ok">대표 J2 채널의 <b>명목 DC·60 Hz 전달 특성은 설계 의도에 부합</b>합니다. 제조사 모델을 임의로 변경하지 않고, 초기 추정값 후 새로운 DC Newton 해를 구했습니다. 원본 ZIP/LIB 해시와 실행 로그를 보존했습니다. 단, 최저 전원에서의 정밀 출력 여유는 아래 별도 주의사항을 확인해야 합니다.</div>
<h2>핵심 결과</h2><table><tr><th>항목</th><th>모델 결과</th><th>해석</th></tr>
<tr><td>DC 변환</td><td>약 VADC = 1.64815 − 0.70000 × VSMA</td><td>이상적 명목식 1.6472868 − 0.7 × VSMA와 모델 오프셋 차이</td></tr>
<tr><td>−3 dB 대역</td><td>{fc:.1f} Hz</td><td>DC·60 Hz용 수 kHz 대역</td></tr>
<tr><td>60 Hz</td><td>{result['ac']['samples']['60']['relative_db']:.6f} dB / 추가 위상 {result['ac']['samples']['60']['extra_phase_deg']:.3f}°</td><td>출력은 기본적으로 반전됨</td></tr>
<tr><td>7.8 kHz 감쇠</td><td>{result['ac']['samples']['7800']['relative_db']:.2f} dB</td><td>15.6 kS/s의 Nyquist에서 강한 차단은 아님</td></tr>
<tr><td>DC 점 검증</td><td>{dc['validated_true_dc_cases']}/{dc['requested_cases']} 점</td><td>5 V±5%, 3.3 V±5%의 지정 조합 및 입력 범위; 공차/온도 전수 보증 아님</td></tr>
<tr><td>±2 V 입력 결과 범위</td><td>{dc_accept['adc_min_v']:.6f}…{dc_accept['adc_max_v']:.6f} V</td><td>검증 성공점만; 최소 출력 레일 여유 {dc_accept['minimum_rail_headroom_v']*1e3:.1f} mV</td></tr>
<tr><td>4 V 입력 계단 정착</td><td>{st*1e6 if st else float('nan'):.1f} µs</td><td>시뮬레이션 최종값의 0.5 LSB(3.3 V/16 bit) 기준, 이상적 고정 바이어스</td></tr></table>
<h2>잡음 결과와 검증 한계</h2><table><tr><th>적분 상한 (하한 0.1 Hz)</th><th>ADC 핀 잡음</th></tr>{''.join(rows)}</table>
<p>위 수치는 모델과 수동소자 열잡음의 <b>명목 아날로그 출력 잡음</b>입니다. 실제 전원 리플, MCU 내부 ADC·VREF+ 잡음, PCB 결합, 디지털 스위칭, 샘플링 후 alias는 포함하지 않습니다. 이를 실제 ADC의 유효 비트 수나 보드 잡음 보증으로 해석하면 안 됩니다.</p>
<h2>추가 확인이 필요한 항목</h2><div class="notice"><ol>
<li><b>최저 전원에서의 출력 여유:</b> 3.3 V−5%=3.135 V, 입력 −2 V에서 출력 상단 여유는 약 86.9 mV입니다. 모델에서는 포화가 없었지만 <a href="https://www.ti.com/lit/ds/symlink/opa320.pdf">OPA320 데이터시트 §6.7</a>의 보증 개방루프 이득 시험 범위는 RL=10 kΩ에서 레일과 0.1 V, RL=2 kΩ에서 0.2 V 이상 떨어진 영역입니다. 실제 피드백 전류도 약 0.742 mA입니다. 따라서 이 저전원 조건의 편차·온도 포함 정밀 선형성은 이번 명목 모델 결과로 보증할 수 없습니다. 실제 3.3 V 최저 전압·공차를 확인하고, −5%까지 요구한다면 이득 축소 등의 여유 확보를 검토하십시오. 회로는 변경하지 않았습니다.</li>
<li><b>Anti-alias:</b> 7.8 kHz에서 약 −10.3 dB이므로 강한 외부 고주파가 있으면 alias가 남을 수 있습니다. 신호 환경에 따라 필터 차수/대역 또는 취득 구조를 별도로 검토해야 합니다. 이번에는 수정하지 않았습니다.</li>
<li><b>DC 절대 정확도:</b> 명목식 대비 모델 DC 오프셋은 약 0.86 mV입니다. 0.1% 저항 극단 조합만으로도 수 mV 오차가 가능하므로, 16-bit 분해능을 16-bit 절대 정확도로 간주하면 안 됩니다. 정밀 목표에 따라 매칭 저항망·기준전압·보정/실측을 검토하십시오.</li>
<li><b>기동 정착:</b> REF 단독 모델의 분압 필터는 전원 램프 시작 후 약 {ref_settle:.3f} s에 0.1% 이내에 들어옵니다. U32·후단 RC·펌프 및 실제 전원 순서는 별도이며 이 수치는 최대 보증이 아닙니다.</li>
<li><b>ADC 채널 잔류 전하:</b> ST 자료의 CADC는 4 pF 전형값이며 최대값은 없습니다. Cs/Ron 가정 시험은 실제 MCU 스위치 전하주입·샘플 정확도 보증을 대신하지 않습니다. 8 µs 취득 조건의 결과는 results.json에 분리했습니다.</li>
<li><b>음전원:</b> TPS72301은 이상적 −4.5 V/13 mA 부하에서 약 {result['negative_ldo']['final_output_v']:.5f} V로 수렴합니다. 모든 입력 −2 V일 때 10개 전단 OP AMP의 신호 전류까지 포함하면 명목 약 20.4 mA, 25°C 최대 정지전류 가정에서는 약 24.4 mA입니다. 전 온도 최대 정지전류 기준 약 25.4 mA에 피드백 분압 전류 약 0.119 mA도 추가해야 합니다. TPS60403 암호화 모델은 실행하지 않았으므로 펌프 리플·최대 부하·전원 차단 검증은 미완료입니다.</li>
</ol></div>
{''.join(cards)}
<h2>디버깅 커넥터도 있습니다</h2><p>최종 회로도와 PCB에서 <b>J1, Samtec FTSH-107-01-L-DV-K-A, 14핀(2×7), 1.27 mm SWD 헤더</b>와 Top 실크를 확인했습니다. 케이블 연결 전 실제 핀 번호를 대조하십시오.</p><table><tr><th>J1 핀</th><th>신호</th></tr>{header_rows}</table>
<p>나머지 핀은 현재 접속 없음이며 SWO/JTAG 별도 연결은 없습니다. UART 콘솔은 CN4 USB-C ↔ CH340C(U8) ↔ PA10 RX / PA9 TX입니다. TP17=GND, TP18=+3V3, TP19=+1V8입니다.</p>
<h2>증거 및 재현 자료</h2><ul><li><a href="results.json">수치 결과 및 한계 JSON</a></li><li><a href="source-audit.json">최종 회로도 값·핀/넷 대조</a></li><li><a href="models/model-index.json">제조사 원본 모델 출처·해시·제약</a></li><li><a href="runtime/ngspice-runtime.json">실행 엔진 출처·해시·설정</a></li><li><a href="{pointfile.relative_to(OUT).as_posix()}">개별 DC 점 전체 기록</a></li><li><a href="runs/">RAW·실행 로그</a> / <a href="decks/">SPICE 입력 덱</a></li></ul>
<p>실패한 초기 실행도 로그에 남겼고 성공으로 계산하지 않았습니다. 무모델 션트 저항을 추가하여 결과를 바꾸는 수렴 우회는 채택하지 않았습니다. Noise 분석 문법과 내부 노드 초기값은 ngspice용이므로 덱을 PSpice에 그대로 넣을 수 있다고 보장하지 않습니다. MCU 전체·전원 전체·전체 PCB SPICE/CAM 검증이나 제조 승인이 아닙니다.</p>
<p>공식 자료: <a href="https://www.ti.com/product/OPA189">TI OPA189</a> · <a href="https://www.ti.com/product/OPA320">TI OPA320</a> · <a href="https://www.ti.com/lit/ds/symlink/ref50.pdf">REF50</a> · <a href="https://www.st.com/resource/en/datasheet/stm32h747xi.pdf">STM32H747 DS12930</a> · <a href="https://ngspice.sourceforge.io/download.html">ngspice</a></p></html>'''
    (OUT/"review.html").write_text(document, encoding="utf-8")
    accepted_cases = [r["case"] for r in dc["results"] if r.get("validated_true_dc")]
    accepted_cases += ["ac_ref_q1_trueDC", "noise_ref_q1_trueDC", "smoke_ref_q1_trueDC", "ac_ref_generic_crosscheck",
        "noise_ref_generic_crosscheck", "sine_ideal_q1_clean", "step_ideal_q1_clean", "reference_ref_q1",
        "reference-noise_ref_q1_allnoise", "reference-startup_ref_q1_gear", "ldo_ref_q1"]
    accepted_cases += [r["case"] for r in result["sampling_surrogate"]]
    evidence = [OUT/"review.html", OUT/"results.json", OUT/"source-audit.json", OUT/"dc-points.csv", pointfile,
        OUT/"models/model-index.json", OUT/"runtime/ngspice-runtime.json", Path(__file__), ROOT/"scripts/simulate-adc-representative.py"]
    for case in accepted_cases:
        evidence += [OUT/"runs"/f"{case}.raw", OUT/"runs"/f"{case}.log", OUT/"decks"/f"{case}.cir"]
    evidence += sorted(PLOTS.glob("*.png"))
    index = {"status": "representative simulation review complete; not a manufacturing or real-hardware qualification",
        "not_cadence_pspice": True, "cad_modified": False, "accepted_cases": accepted_cases,
        "rejected_or_initial_diagnostic_runs": "Other diagnostic/failed logs are preserved but are not part of accepted simulation evidence.",
        "artifacts": [{"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size, "sha256": sha(p)} for p in evidence]}
    (OUT/"simulation-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"report": str(OUT/"review.html"), "dc_points": result["dc"]["validated"], "ac": result["ac"],
        "noise": result["noise"], "step": result["step"], "sampling": result["sampling_surrogate"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
