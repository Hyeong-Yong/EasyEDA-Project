"""Read-only ten-SMA ADC inventory from actual native schematic and PCB."""
import hashlib
import json
import runpy
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PARSE = runpy.run_path(str(HERE / "independent-inline-wire-graph-audit.py"))["parse"]


def main():
    sch_path = ROOT / "output/validation/native-adc-inline-reopened-20261016.epru"
    pcb_path = ROOT / "output/validation/native-multilayer-corners_j18_direction_v2_20261016-reopened.epru"
    net_path = ROOT / "output/validation/native-adc-inline-after-Protel2-20261016.net"
    sch, pcb = PARSE(sch_path), PARSE(pcb_path)
    net = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))["parse_protel2"](net_path.read_text(encoding="utf8"))
    pin_nets = {(p["ref"], p["number"]): p["net"] for p in net}
    sch_attrs, pcb_attrs = defaultdict(dict), defaultdict(dict)
    for rows, target in ((sch, sch_attrs), (pcb, pcb_attrs)):
        for (kind, rid), b in rows.items():
            if kind == "ATTR":
                target[b.get("parentId")][b.get("key")] = b.get("value")
    sch_refs = {a["Designator"]: rid for rid, a in sch_attrs.items() if a.get("Designator")}
    pcb_refs = {a["Designator"]: rid for rid, a in pcb_attrs.items() if a.get("Designator")}
    # PCB names use the public API's Designator attribute, not generated hashes.
    assert "J11" in pcb_refs

    def detail(ref):
        rid = sch_refs[ref]
        b = sch[("COMPONENT", rid)]
        result = {"ref": ref, "schematicId": rid, "value": sch_attrs[rid].get("Value"),
                  "DNP": sch_attrs[rid].get("DNP"), "schematicXY": [b["x"], b["y"]],
                  "pinNets": {n: v for (r, n), v in sorted(pin_nets.items()) if r == ref}}
        if ref in pcb_refs:
            pid = pcb_refs[ref]
            pb = pcb[("COMPONENT", pid)]
            result["pcb"] = {"id": pid, "XYmil": [pb["x"], pb["y"]],
                             "XYmm": [round(pb["x"] * .0254, 6), round(pb["y"] * .0254, 6)],
                             "angle": pb["angle"], "layer": pb["layerId"], "padNets": {}}
            for (kind, nid), nbody in pcb.items():
                if kind != "PAD_NET":
                    continue
                identity = json.loads(nid)
                if identity[1] == pid:
                    result["pcb"]["padNets"].setdefault(identity[2], set()).add(nbody["padNet"])
            result["pcb"]["padNets"] = {k: sorted(v) for k, v in result["pcb"]["padNets"].items()}
        return result

    specs = [(1, 2, 137, 140, 141, None, 80, "ADC1_INP0", "PA0_C", "T1"),
             (1, 3, 138, 142, 143, None, 81, "ADC1_INP1", "PA1_C", "T2"),
             (1, 4, 139, 144, 145, None, 82, "ADC1_INP16", "PA0", "N5"),
             (2, 5, 149, 152, 153, 158, 86, "ADC2_INP3", "PA6", "R3"),
             (2, 6, 150, 154, 155, 159, 87, "ADC2_INP12", "PC2", "M3"),
             (2, 7, 151, 156, 157, 160, 88, "ADC2_INP13", "PC3", "M4"),
             (3, 8, 161, 165, 166, 173, 93, "ADC3_INP2", "PF9", "L4"),
             (3, 9, 162, 167, 168, 174, 94, "ADC3_INP6", "PF10", "L3"),
             (3, 10, 163, 169, 170, 175, 95, "ADC3_INP7", "PF8", "K4"),
             (3, 11, 164, 171, 172, 176, 96, "ADC3_INP8", "PF6", "K2")]
    inputs = []
    for bank, j, rb, ri, rs, dnp, c, port, gpio, ball in specs:
        sma, bias, input_r, series, cap = (detail(ref) for ref in (f"J{j}", f"R{rb}", f"R{ri}", f"R{rs}", f"C{c}"))
        assert pin_nets[(f"J{j}", "1")] == pin_nets[(f"R{ri}", "1")]
        assert pin_nets[(f"R{rs}", "2")] == port == pin_nets[(f"C{c}", "1")] == pin_nets[("U1", ball)]
        dp = detail(f"R{dnp}") if dnp else None
        if bank != 1:
            mix = pin_nets[(f"R{ri}", "2")]
            assert mix == pin_nets[(f"R{rb}", "2")] == pin_nets[(f"R{rs}", "1")] == pin_nets[(f"R{dnp}", "1")]
            assert pin_nets[(f"R{rb}", "1")] == "+3V3"
            assert pin_nets[(f"R{dnp}", "2")] == "GND" and dp["DNP"] == "yes"
        else:
            mix = f"ADC1_PRE{j-1}"
        inputs.append({"bank": f"ADC{bank}", "sma": sma, "biasResistor": bias,
                       "inputResistor": input_r, "seriesResistor": series,
                       "shuntDnpResistor": dp, "adcCapacitor": cap,
                       "mixNet": mix, "adcPort": port, "gpio": gpio, "mcuBall": ball,
                       "alreadyUpdatedDcBuffer": bank == 1,
                       "nativeEvidenceForSpecialOrTestOnlyConnector": False})
    report = {"schema": "independent-ten-adc-input-inventory-20261016-v1", "passed": True,
              "schematicSourcePath": str(sch_path), "schematicSourceSha256": hashlib.sha256(sch_path.read_bytes()).hexdigest(),
              "pcbSourcePath": str(pcb_path), "pcbSourceSha256": hashlib.sha256(pcb_path.read_bytes()).hexdigest(),
              "nativeNetlistPath": str(net_path), "nativeNetlistSha256": hashlib.sha256(net_path.read_bytes()).hexdigest(),
              "smaInputCount": 10, "countsByAdcBank": {"ADC1": 3, "ADC2": 3, "ADC3": 4},
              "alreadyUpdatedCount": 3, "remainingUnchangedInputCount": 7,
              "inputs": inputs,
              "scopeDecisionNeeded": "User says remaining six, but seven ordinary ADC inputs J5-J11 exist. Confirm whether to include all seven, or which one is intentionally excluded. No special/test-only evidence found for J11.",
              "notes": ["ADC1 physical MCU ports unchanged; labels one/two/three are input order, not ADC hardware channel numbers.",
                        "Current PCB still has pre-ADC-ECO passive inputs, including old ADC1 resistors/DNP footprints; this inventory does not authorize or implement ECO.",
                        "No live EasyEDA/API operations and no PCB or circuit mutations."]}
    out = HERE / "independent-adc-input-inventory.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": True, "report": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                      "smaCount": 10, "remainingCount": 7, "map": [{"sma": x["sma"]["ref"], "adc": x["adcPort"], "gpio": x["gpio"], "ball": x["mcuBall"], "pcbXYmm": x["sma"]["pcb"]["XYmm"]} for x in inputs]}, indent=2))


if __name__ == "__main__":
    main()
