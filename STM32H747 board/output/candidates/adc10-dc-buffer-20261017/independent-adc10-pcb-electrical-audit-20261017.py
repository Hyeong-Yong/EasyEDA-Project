"""Read-only ADC10 PCB ECO ref/pin/net and component-membership audit.

Uses native Protel2 export AND PCB PAD_NET source records independently.
Does not assess routing completion, DRC, copper connectivity, or fabrication.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import runpy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALIDATION = ROOT / "output/validation"
BASE = VALIDATION / "native-adc10-pcb-before-20261017.epru"
SCH_NET = VALIDATION / "native-adc10-reopened-Protel2-20261017.net"
CONTRACT = HERE / "independent-adc10-expected-full-pin-contract-20261017.json"
parse_protel2 = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))["parse_protel2"]
DNP = {"R146", "R147", "R148", "R158", "R159", "R160", "R173", "R174", "R175", "R176"}
NEW = {f"C{i}" for i in range(97, 120)} | {f"U{i}" for i in range(9, 20)}
REPLACED = ({f"R{i}" for i in range(137, 146)} |
            {f"R{i}" for i in range(149, 158)} |
            {f"R{i}" for i in range(161, 173)} |
            {f"C{i}" for i in [80, 81, 82, 86, 87, 88, 93, 94, 95, 96]})
CHANNELS = [
    ("J2", "T1", "ADC1_INP0", "PA0_C"),
    ("J3", "T2", "ADC1_INP1", "PA1_C"),
    ("J4", "N5", "ADC1_INP16", "PA0"),
    ("J5", "R3", "ADC2_INP3", "PA6"),
    ("J6", "M3", "ADC2_INP12", "PC2"),
    ("J7", "M4", "ADC2_INP13", "PC3"),
    ("J8", "L4", "ADC3_INP2", "PF9"),
    ("J9", "L3", "ADC3_INP6", "PF10"),
    ("J10", "K4", "ADC3_INP7", "PF8"),
    ("J11", "K2", "ADC3_INP8", "PF6"),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_source(path):
    rows, raw_rows = {}, {}
    attrs = defaultdict(dict)
    for raw in path.read_text(encoding="utf8").splitlines():
        if not raw.strip():
            continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], h.get("id")
        assert key not in rows, (path, key)
        rows[key], raw_rows[key] = b, raw
        if h["type"] == "ATTR":
            assert b["key"] not in attrs[b["parentId"]], (path, b)
            attrs[b["parentId"]][b["key"]] = b["value"]
    refs = {a["Designator"]: cid for cid, a in attrs.items() if "Designator" in a}
    assert len(refs) == sum(k[0] == "COMPONENT" for k in rows), path
    return rows, raw_rows, attrs, refs


def pad_assignments(rows, refs):
    inverse = {cid: ref for ref, cid in refs.items()}
    by_pin = defaultdict(list)
    for (kind, rid), body in rows.items():
        if kind != "PAD_NET":
            continue
        identity = json.loads(rid)
        assert len(identity) == 4 and identity[0] == "PAD_NET", identity
        ref = inverse[identity[1]]
        by_pin[ref, str(identity[2])].append({"pad_id": identity[3], "net": body.get("padNet") or ""})
    conflicts = [{"ref": k[0], "pin": k[1], "physical_pads": values}
                 for k, values in by_pin.items() if len({r["net"] for r in values}) != 1]
    connected = {k: v[0]["net"] for k, v in by_pin.items() if v[0]["net"]}
    return by_pin, connected, conflicts


def protel(path):
    text = path.read_text(encoding="utf-8-sig")
    pins = parse_protel2(text)
    by_pin = {(r["ref"], str(r["number"])): r["net"] for r in pins}
    assert len(pins) == len(by_pin), (path, "duplicate exporter nodes")
    refs = set(re.findall(r"(?m)^\[\r?\nDESIGNATOR\r?\n([^\r\n]+)", text))
    return by_pin, refs


def mismatches(expected, actual):
    return [{"ref": key[0], "pin": key[1], "expected": expected.get(key), "actual": actual.get(key)}
            for key in sorted(expected.keys() | actual.keys()) if expected.get(key) != actual.get(key)]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", default=str(VALIDATION / "native-adc10-pcb-eco_applied-20261017.epru"))
    p.add_argument("--netlist", default=str(VALIDATION / "native-pcb-Protel2_adc10_eco_20261017.net"))
    p.add_argument("--tag", default="eco-applied")
    args = p.parse_args()
    source, netlist = Path(args.source).resolve(), Path(args.netlist).resolve()
    contract = json.loads(CONTRACT.read_text(encoding="utf8"))
    expected = {(r["ref"], str(r["number"])): r["net"] for r in contract["expectedPins"]}
    pcb_pins, pcb_parts = protel(netlist)
    sch_pins, sch_parts = protel(SCH_NET)
    before, before_raw, before_attrs, before_refs = read_source(BASE)
    after, after_raw, after_attrs, after_refs = read_source(source)
    before_by_pin, before_pad_nets, before_conflicts = pad_assignments(before, before_refs)
    by_pin, pad_nets, conflicts = pad_assignments(after, after_refs)
    checks, errors = [], []

    def check(ok, name, detail=None):
        row = {"name": name, "passed": bool(ok)}
        if detail is not None:
            row["detail"] = detail
        checks.append(row)
        if not ok:
            errors.append(row)

    check(len(expected) == len(pcb_pins) == len(sch_pins) == 1136,
          "Independent contract, PCB export and saved SCH export each have 1136 unique connected pins")
    check(pcb_pins == expected, "PCB Protel2 all ref/pin/net identities exactly match independent contract", mismatches(expected, pcb_pins))
    check(pcb_pins == sch_pins, "PCB Protel2 all ref/pin/net identities exactly match saved SCH", mismatches(sch_pins, pcb_pins))
    check(pad_nets == expected, "Actual PCB PAD_NET all unique connected ref/pins exactly match independent contract", mismatches(expected, pad_nets))
    check(not conflicts, "Repeated physical pads with same pin number have consistent net assignments", conflicts)
    check(pcb_parts == sch_parts == set(after_refs) and len(pcb_parts) == 354,
          "PCB source and both native exports contain identical 354 physical reference identities")
    added, deleted = set(after_refs) - set(before_refs), set(before_refs) - set(after_refs)
    footprint_changes = {ref for ref in set(before_refs) & set(after_refs)
                         if before_attrs[before_refs[ref]].get("Footprint") != after_attrs[after_refs[ref]].get("Footprint")}
    device_changes = {ref for ref in set(before_refs) & set(after_refs)
                      if before_attrs[before_refs[ref]].get("Device") != after_attrs[after_refs[ref]].get("Device")}
    check(len(before_refs) == 330 and added == NEW and deleted == DNP,
          "Component delta is exactly 330 minus ten DNP plus 34 additions equals 354",
          {"added": sorted(added), "deleted": sorted(deleted)})
    check(footprint_changes == device_changes == REPLACED,
          "Exactly forty approved existing ADC resistor/capacitor devices and footprints replaced",
          {"footprint_changes": sorted(footprint_changes), "device_changes": sorted(device_changes)})
    old_u1 = {k: v for k, v in before_pad_nets.items() if k[0] == "U1"}
    new_u1 = {k: v for k, v in pad_nets.items() if k[0] == "U1"}
    check(old_u1 == new_u1, "All original MCU U1 pad-to-net assignments unchanged", mismatches(old_u1, new_u1))
    u1id = before_refs["U1"]
    check(u1id == after_refs["U1"] and before["COMPONENT", u1id] == after["COMPONENT", u1id],
          "MCU U1 instance identity and complete COMPONENT body unchanged")
    channel_report = []
    for sma, ball, net, gpio in CHANNELS:
        ok = pad_nets.get(("U1", ball)) == expected.get(("U1", ball)) == net
        check(ok, f"{sma} MCU {gpio} ball {ball} stays on {net}")
        channel_report.append({"sma": sma, "mcu": "U1", "gpio": gpio,
                               "ball": ball, "adc_net": net, "passed": ok})
    repeated = [{"ref": key[0], "pin": key[1], "net": values[0]["net"],
                 "physical_pad_count": len(values), "physical_pads": values}
                for key, values in sorted(by_pin.items()) if len(values) > 1]
    report = {
        "schema": "stm32h747-adc10-independent-pcb-electrical-audit-20261017-v1",
        "passed": not errors, "errors": errors,
        "source": {"path": str(source), "bytes": source.stat().st_size, "sha256": sha(source)},
        "baselinePCB": {"path": str(BASE), "sha256": sha(BASE)},
        "pcbNetlist": {"path": str(netlist), "bytes": netlist.stat().st_size, "sha256": sha(netlist)},
        "savedSCHNetlist": {"path": str(SCH_NET), "sha256": sha(SCH_NET)},
        "independentContract": {"path": str(CONTRACT), "sha256": sha(CONTRACT)},
        "connectedUniquePins": len(pad_nets), "physicalParts": len(after_refs),
        "physicalPadNetRecords": sum(len(v) for v in by_pin.values()),
        "netlessPhysicalPadRecords": sum(len(v) for v in by_pin.values() if not v[0]["net"]),
        "consistentRepeatedPinPhysicalPads": repeated,
        "addedReferences": sorted(added), "deletedDNPReferences": sorted(deleted),
        "replacedExistingFootprints": sorted(footprint_changes),
        "mcuConnectedPinCount": len(new_u1), "channels": channel_report,
        "allPinAssignments": [{"ref": ref, "pin": pin, "net": net}
                              for (ref, pin), net in sorted(pad_nets.items())],
        "checks": checks,
        "method": "Electrical identity is the exact reference, physical pin number, net name triple. Protel metadata fields (footprint/device text, pin-type description) are not electrical identity. Native source PAD_NET records separately confirm exporter output. Duplicate SMA shield pad numbers are allowed only when every physical pad has exactly the same net.",
        "limitations": ["Net assignment is not routed copper continuity. Routing, placement, DRC, power/signal integrity and fabrication are not approved by this audit.",
                        "Source and native export snapshots are the explicit supplied files. Re-run after any further ECO, placement, routing, or save/reopen that changes electrical records."],
        "liveAPICalls": 0, "nativeFilesWritten": 0,
    }
    out = HERE / f"independent-adc10-pcb-{args.tag}-electrical-audit-20261017.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": sha(out), "passed": not errors,
                      "connectedPins": len(pad_nets), "physicalParts": len(after_refs),
                      "added": len(added), "deleted": len(deleted),
                      "replacedFootprints": len(footprint_changes), "errors": errors}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
