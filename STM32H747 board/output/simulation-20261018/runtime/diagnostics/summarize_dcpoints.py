"""Add explicitly partial fit metrics to the preserved independent-point summary."""
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
target=HERE.parent/"dcpoint-summary.json"
summary=json.loads(target.read_text())
valid=[r for r in summary["results"] if r["validated_true_dc"]]
nominal=[r for r in valid if r["group"]=="nominal"]
fit={"expected_nominal_gain_v_per_v":-.7,"gain_linearity_acceptance_tolerance_specified":False,"valid_points":len(nominal),"requested_points":17,"complete_coverage":len(nominal)==17,"interpretation":"Fit only the successfully validated DC points. Missing points remain failures; this fit does not validate the complete requested sweep."}
if len(nominal)>=3:
    x=np.array([r["voltages_currents"]["v(raw_j2)"] for r in nominal])
    y=np.array([r["voltages_currents"]["v(adc_j2)"] for r in nominal])
    off=np.array([r["voltages_currents"]["v(off)"] for r in nominal])
    slope,intercept=np.polyfit(x,y,1)
    residual=y-(slope*x+intercept)
    fit.update(fitted_gain_v_per_v=float(slope),fitted_offset_v=float(intercept),gain_error_percent=float((slope/-.7-1)*100),max_abs_residual_from_fit_v=float(np.max(np.abs(residual))),max_abs_error_from_case_bias_and_ideal_gain_v=float(np.max(np.abs(y-(1.7*off-.7*x)))),sma_coverage_min_v=float(x.min()),sma_coverage_max_v=float(x.max()))
summary["acceptance"]["nominal_gain_linearity"]=fit
summary["acceptance"]["group_validation_counts"]={group:{"valid":sum(r["group"]==group for r in valid),"requested":sum(r["group"]==group for r in summary["results"])} for group in ["nominal","corner"]}
headroom=min(valid,key=lambda r:r["adc_rail_headroom_v"])
summary["acceptance"]["minimum_headroom_case"]={k:headroom[k] for k in ["case","v5_source_v","v3_v","requested_sma_v","adc_rail_headroom_v"]}
temporary=target.with_suffix(".tmp")
temporary.write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
temporary.replace(target)
print(json.dumps(summary["acceptance"]))
