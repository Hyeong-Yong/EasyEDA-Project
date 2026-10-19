"""Read-only qualified hardware-open-zero review; NOT a circuit candidate."""
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    inv_path = HERE / "independent-adc-input-inventory.json"
    inv = json.loads(inv_path.read_text(encoding="utf8"))
    rb, ri, vref = 6800.0, 6800.0, 2.5

    def buffer_v(vs, rs):
        return vref - (vref - vs) * rb / (rb + ri + rs)

    def rs_at(vs, threshold):
        return rb * (vref - vs) / (vref - threshold) - rb - ri

    report = {
        "schema": "independent-adc10-qualified-raw-zero-feasibility-20261016-v1",
        "status": "READ_ONLY_FEASIBILITY_COMPLETE_IMPLEMENTATION_BLOCKED_BY_TWO_USER_CHOICES",
        "nativeMutationPerformed": False,
        "pcbMutationPerformed": False,
        "newLibrariesOrCircuitCandidatesBuilt": False,
        "verifiedInventory": {
            "sourceReportPath": str(inv_path),
            "sourceReportSha256": hashlib.sha256(inv_path.read_bytes()).hexdigest(),
            "sourceSchematicSha256": inv["schematicSourceSha256"],
            "sourceNetlistSha256": inv["nativeNetlistSha256"],
            "sourcePcbSha256": inv["pcbSourceSha256"],
            "totalSmaInputs": 10,
            "bankCounts": inv["countsByAdcBank"],
            "alreadyBufferedSmaRefs": ["J2", "J3", "J4"],
            "remainingOrdinarySmaRefs": ["J5", "J6", "J7", "J8", "J9", "J10", "J11"],
            "remainingCount": 7,
            "J11SpecialTestOnlyEvidence": False,
            "mapping": [{"sma": x["sma"]["ref"], "port": x["adcPort"], "gpio": x["gpio"], "mcuBall": x["mcuBall"],
                         "pcbSmaXYmm": x["sma"]["pcb"]["XYmm"], "mixNet": x["mixNet"],
                         "bias": {"ref": x["biasResistor"]["ref"], "value": x["biasResistor"]["value"]},
                         "input": {"ref": x["inputResistor"]["ref"], "value": x["inputResistor"]["value"]},
                         "series": {"ref": x["seriesResistor"]["ref"], "value": x["seriesResistor"]["value"]},
                         "adcCap": {"ref": x["adcCapacitor"]["ref"], "value": x["adcCapacitor"]["value"]},
                         "dnp": x["shuntDnpResistor"]["ref"] if x["shuntDnpResistor"] else None,
                         "alreadyBuffered": x["alreadyUpdatedDcBuffer"]} for x in inv["inputs"]],
            "originalAdc23FilterValues": {"bias": "7.5k to +3V3", "input": "5.1k", "series": "100 ohm", "adcShuntCap": "10nF", "optionalPulldown": "30k_NC, DNP=yes"},
            "pinNumberCaution": "Untouched ADC2/3 bias R149-151/R161-164 pin1 is +3V3 and pin2 is mix; updated ADC1 R137-139 pin1 is PRE and pin2 is ADC_BIAS_2V5. Do not copy logical pin numbers blindly."
        },
        "blockingUserChoices": [
            {"choice": "Channel scope", "reason": "User says remaining six, but seven ordinary unmodified ADC inputs exist. Confirm all seven or identify the excluded SMA/ADC port."},
            {"choice": "Source type and maximum output impedance", "reason": "Needed both for original transfer accuracy and to prevent connected high-Z input from being misclassified as OPEN. Also specify cable/leakage, peak range including DC and overshoot, operating temperature and acceptable error."}
        ],
        "qualifiedTopology": {
            "possibleWithoutNegativeRail": True,
            "description": "Existing DC-coupled level shift and OPA buffer remain. Comparator watches buffer BEFORE SPDT; switch selects buffered signal or GND; common output drives existing 47ohm and ADC2.2nF. Comparator normal=HIGH/fault=LOW; SEL0 selects GND. Monitor upstream so grounding ADC cannot latch the detector.",
            "normalConnectorRangeV": [-2, 2],
            "normalAdcRangeVNominalLowSourceZ": [0.25, 2.25],
            "openBufferVNominal": 2.5,
            "rawAdcFaultVNominalAfterSettling": 0,
            "notGuaranteedExactZero": "Switch resistance, ADC input current/sampling, leakage, ground noise and ADC offset remain. Hardware is a low-impedance GND selection, not a mathematical zero-code guarantee.",
            "doesNotPullSmaItselfToGround": True,
            "semantics": "Upper-out-of-range/open/high-Z fault discriminator, NOT a universal physical-connector detector and NOT complete bipolar overvoltage protection.",
            "seriesDcBlockingCapAdded": False,
            "nominalThresholdExampleOnly": {"faultAssertRisingV": 2.45, "normalReleaseFallingV": 2.40,
                "thresholdSource": "Ratio of same quiet2.5V reference, with externally designed hysteresis; exact values not frozen.",
                "mustBudget": ["Comparator offset and maximum internal hysteresis", "External hysteresis resistor ratio/tolerance and output swing", "Reference initial/drift/load errors", "OPA offset/drift", "6.8k ratio tolerances", "Noise/transients/source impedance"],
                "validSignalRule": "Highest valid buffered voltage must remain below MINIMUM release threshold in all tolerances, to recover after plugging in a valid DC source. Lowest open/fault buffer must exceed MAXIMUM assertion threshold."}
        },
        "independentSourceImpedanceAnalysis": {
            "voltageDefinition": "Vs is source Thevenin/open-circuit voltage; Rs is its output resistance. If VIN instead means actual already-loaded SMA terminal voltage, nominal divider formula applies to that terminal voltage but source loading still changes the intended measured source.",
            "formula": "Vbuffer=2.5-(2.5-Vs)*6800/(13600+Rs)",
            "gainFormula": "dVbuffer/dVs=6800/(13600+Rs)",
            "nominalGainLowZ": 0.5,
            "worstValidPositiveInputV": 2.0,
            "idealPositivePeakFaultTripRsOhmAt2V": {"threshold2.40V": rs_at(2, 2.40), "threshold2.45V": rs_at(2, 2.45)},
            "reconnectRsMustBeBelowLowerReleaseThresholdBoundaryOhm": rs_at(2, 2.40),
            "illustrative20mVReleaseErrorBudgetNotGuaranteed": {"minimumReleaseV": 2.38, "maximumRsOhmBeforeAdditionalMargin": rs_at(2, 2.38)},
            "uncalibratedGainLossOnlyLimits": {"lessThan1percentRsOhm": 13600*.01/.99, "lessThan0_1percentRsOhm": 13600*.001/.999},
            "gainLimitsDoNotIncludeOffsetError": True,
            "cases": [{"RsOhm": rs, "bufferAtSourceMinus2V": buffer_v(-2, rs), "bufferAtSource0V": buffer_v(0, rs),
                       "bufferAtSourcePlus2V": buffer_v(2, rs), "gain": 6800/(13600+rs)}
                      for rs in (0, 50, 1000, 10000, 100000)],
            "failureModes": ["High-Z connected DC may stay at GND after reconnection because release threshold is not crossed.",
                             "High-Z60Hz positive peaks may repeatedly switch ADC to GND, clipping/chopping valid signals.",
                             "Leaky disconnected cables can appear connected; sufficiently high-Z connected sources can appear disconnected.",
                             "Open detector cannot distinguish all possible source impedances/voltages from physical disconnection using this DC voltage alone."]
        },
        "verifiedPartCandidatesNotFinalSelections": {
            "comparator": {"family": "TLV7011/TLV7012 push-pull; TLV702x is open-drain",
                "tiPrimaryUrl": "https://www.ti.com/lit/ds/symlink/tlv7011.pdf",
                "singleSupplyRangeV": [1.6, 5.5], "inputCommonModeAt3V3V": [0, 3.4], "offsetAbsMaxV": 0.008,
                "internalHysteresisV": {"singleMinTypMax": [.0012, .0042, .014], "dualMinTypMax": [.002, .0072, .015]},
                "TLV7011DBV5Pins": {"1": "OUT", "2": "GND/VEE", "3": "IN+", "4": "IN-", "5": "VCC"},
                "TLV7012DGK8Pins": {"1": "OUTA", "2": "INA-", "3": "INA+", "4": "GND/VEE", "5": "INB+", "6": "INB-", "7": "OUTB", "8": "VCC"},
                "polarity": "Upstream buffered signal to IN-; hysteretic threshold to IN+.",
                "startup": "701x POR output LOW,20us power-up specification; this alone does not cover reference/filter settling."},
            "switch": {"wrongExamplePart": "TMUX1102 is SPST, not signal/GND SPDT",
                "TMUX1119": {"tiPrimaryUrl": "https://www.ti.com/lit/ds/symlink/tmux1119.pdf", "configuration": "1-channel2:1SPDT",
                    "supplyV": [1.08, 5.5], "signalRange": "GND throughVDD", "DBV6Pins": {"1": "SEL", "2": "VDD", "3": "GND", "4": "S1", "5": "D", "6": "S2"},
                    "select": "LOW:S1→D;HIGH:S2→D", "suggestedPolarity": "S1=GND,S2=buffer,D=47ohm→ADC",
                    "at3V3": {"RonTypOhm": 3.7, "RonMaxOhmThrough125C": 9.8, "onLeakageMaxATestedAt1or3V": 2e-9,
                        "chargeInjectionTypCNotMax": -6e-12, "transitionTypMaxNs": [14, 21], "breakBeforeMakeTypMinNs": [9, 1]},
                    "failSafeCaution": "Logic fail-safe is not powered-off analog protection or guaranteed default grounding below minimumVDD."},
                "TMUX1133": {"tiPrimaryUrl": "https://www.ti.com/product/TMUX1133", "configuration": "Three independently controlled SPDTs,TSSOP16",
                    "enableCaution": "EN=1 disconnects all paths(HI-Z), not GND. Do not confuse disabling with grounding ADC."}}
        },
        "startupAndTransientReview": {
            "openPreFilterTimeConstantSNominalNoCableCap": 6800*10e-9,
            "openRise0To2_45VTimeSNominalNoCableCap": -6800*10e-9*math.log((2.5-2.45)/2.5),
            "additionalCableCapacitanceChangesDetectionDelay": True,
            "typSwitchChargeStepInto2_2nFV": -6e-12/2.2e-9,
            "largestRonPlus47OhmRcTimeConstantS": (47+9.8)*2.2e-9,
            "idealFullStep17bitExponentialSettleSNotAcquisitionGuarantee": math.log(2**17)*(47+9.8)*2.2e-9,
            "requirements": ["Hold selection on GND until3.3V,reference,OPA and filters are stable; comparator POR20us alone is insufficient.",
                             "Keep comparator on unswitched buffer; otherwise GND forcing can cause self-release/chatter/latching.",
                             "After a fault/select transition, allow RC and front-end settling and mark/discard unsettled ADC samples; charge injection is typical, not a worst-case guarantee.",
                             "Review shared-rail sequencing, analog off-power injection/protection and local decoupling.",
                             "Expose/retain a fault-valid indication, or document raw-low sentinel processing; converting0V through the normal VIN formula gives−2.5V, not normal source0V.",
                             "PCB ECO,source/cable tests,ERC/DRC/netlist/CAM validation remain necessary after final circuit approval."]
        },
        "conclusion": "Do not implement universally reliableOPEN→raw0 or extend PCB until channel scope and source contract are answered. Qualified comparator+SPDT solution is technically plausible without negative rail when valid/open voltage windows, startup and errors are bounded."
    }
    out = HERE / "independent-adc10-openzero-feasibility-20261016.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                      "smaInputs": 10, "remainingInputs": 7,
                      "status": report["status"], "sourceLimits": report["independentSourceImpedanceAnalysis"]["uncalibratedGainLossOnlyLimits"]}, indent=2))


if __name__ == "__main__":
    main()
