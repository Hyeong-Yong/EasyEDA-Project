"""Approved bounded Inner1 (layer15) branch alternative, offline only."""
import json
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
I=runpy.run_path(str(HERE/"plan-inner3-branches.py"));T=I["T"];M=I["M"]


def main():
    b=M["Board"]();b.route_power_fill_exceptions=T["POWER_FILL_EXCEPTION"];b.allow_explicit_ground_return=True;b.use_actual_passive_bodies=True
    six=T["AllLayers"](b);ir=I["InnerRouter"](six,15)
    prior=json.loads((HERE/"bottom-bucket-routing-manifest.json").read_text());results=[]
    for r in prior["channels"]:
        if "signalRoute" not in r:continue
        p=r["centerXYmm"];ax=r["axisOfPositiveLocalX"];h=(.5,.25) if ax[0] else (.25,.5)
        r["assemblyBoundingBoxMm"]=[p[0]-h[0],p[1]-h[1],p[0]+h[0],p[1]+h[1]]
        assert b.body_clear(r["assemblyBoundingBoxMm"]),r["ref"]
        results.append(r);b.accept(r)
    # More constrained inner escapes first; ADC0 exterior can use the remaining
    # nearby free bottom sites reached through the chosen single plane layer.
    for net in ["ADC2_INP12","ADC3_INP7","ADC3_INP2","ADC3_INP6","ADC1_INP16","ADC1_INP0"]:
        ch=next(c for c in b.inv if c["net"]==net)
        taps=ir.alternatives(ch)
        r=b.search(ch,limit=12,tap_sources=taps) if taps else {"ref":next(p["ref"] for p in ch["originalAnalogParts"] if p["ref"].startswith("C")),"net":net,"status":"NO_BOUNDED_LAYER15_BRANCH_ALTERNATIVE"}
        if "signalRoute" in r:
            s=r["selectedRoutingSource"];r["additionalSignalRoutes"]=[s["innerBranchRoute"]];r["newSignalVias"]=[s]
            r["electricalEscapeToCapPathMm"]=s["electricalDistanceFromEscapeMm"]+r["signalRoute"]["lengthMm"]
            b.accept(r);six.accept(r)
            for route in r["additionalSignalRoutes"]:
                o={"id":"BRANCH:"+r["ref"],"kind":"NEW_LINE","net":net,"layers":[15],"paths":M["capsule"](route["pointsMm"],M["WIDTH"]/2)};o["bbox"]=M["paths_bbox"](o["paths"]);o["viaBlocked"]=M["offset"](o["paths"],M["CLR"]+T["VIA_MARGIN"]);six.additional.append(o)
        results.append(r)
        report={"schema":"adc10-bottom-complete-layer15-branches-20261018-v1","sourceSha256":M["EXPECTED_SHA"],"channels":results,"legacyBottomAssemblyEnvelopes":b.legacy_bottom_envelopes,"legacyBottomActualPassiveBodies":b.legacy_bottom_actual_bodies,"allOriginalCopperAndDrillsUnchanged":True,"additionalDrills":sum(len(r.get("newSignalVias",[])) for r in results),"chosenInnerBranchLayer":15,"status":"OFFLINE_ONLY_PENDING_LOCAL_FILL_REPAIR_AND_NATIVE_DRC","manufacturingReady":False}
        (HERE/"bottom-bucket-layer15-manifest.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
        M["render"](b,results,HERE/"bottom-bucket-layer15-progress.png")
    print(json.dumps({"solved":sum("signalRoute" in r for r in results),"total":len(results),"additionalDrills":sum(len(r.get("newSignalVias",[])) for r in results)}),flush=True)


if __name__=="__main__":main()
