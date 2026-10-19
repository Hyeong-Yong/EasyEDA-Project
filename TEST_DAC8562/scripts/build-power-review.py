"""Generate an engineering review and a separate, editable EasyEDA circuit draft.

The existing DAC8562 project is read-only.  No old verification files are replaced.
Run with the Codex bundled Python, or any Python 3.11+ installation.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import html
import itertools
import json
import math
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "output" / "power-review"
MODULE = ROOT / "output" / "stm32h747-dac-sma"
REVIEW.mkdir(parents=True, exist_ok=True)
MODULE.mkdir(parents=True, exist_ok=True)
SOURCE = ROOT / "output" / "highz" / "DAC8562_highz_revision.epro2"
TITLE = "STM32H747 DAC SMA 2CH DRAFT"
SOURCES = {
    "tps": "https://www.ti.com/lit/ds/symlink/tps65130.pdf",
    "ldo": "https://www.ti.com/lit/ds/symlink/lp2985.pdf",
    "dac": "https://www.ti.com/lit/ds/symlink/dac8562t.pdf",
    "opa": "https://www.ti.com/lit/ds/symlink/opa2277.pdf",
    "stm": "https://www.st.com/resource/en/datasheet/stm32h747ig.pdf",
    "stm_errata": "https://www.st.com/resource/en/errata_sheet/es0445-stm32h745xig-stm32h755xi-stm32h747xig-stm32h757xi-device-errata-stmicroelectronics.pdf",
    "qnew": "https://www.vishay.com/docs/64004/si2323dds.pdf",
    "qold": "https://www.vishay.com/docs/72024/si2323ds.pdf",
    "ptn": "https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/6347/PTN-SIL-042-2024-REV-0.pdf",
    "cap": "https://product.samsungsem.com/mlcc/CL21A475KAQNNN.do",
    "ldo_upgrade": "https://www.ti.com/lit/ds/symlink/tps7a49.pdf",
}


def uid():
    return uuid.uuid4().hex[:16]


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def resistor_corners(ri, rg, rr, rf, tolerance, vdac, vref):
    values = []
    for factors in itertools.product([1 - tolerance, 1 + tolerance], repeat=4):
        a, b, c, d = (r * f for r, f in zip([ri, rg, rr, rf], factors))
        values.append((1 + d / c) * b / (a + b) * vdac - d / c * vref)
    return [min(values), max(values)]


g = 100000 / 24900
gp = 100000 / 24300
gm = 100000 / 14000
kmin = 10 * .99 / 1.01
kmax = 10 * 1.01 / .99
calculations = {
    "dateKst": "2026-10-12",
    "status": "datasheet-and-analytical-review; not-hardware-verified",
    "originalProjectSha256": hashlib.sha256((ROOT / "DAC8562 module.eprj2").read_bytes()).hexdigest(),
    "originalExportSha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    "sources": SOURCES,
    "tps65131": {
        "nominalPositiveV": 1.213 * (1 + 887000 / 100000),
        "nominalNegativeV": -1.213 * 1000000 / 100000,
        "positiveConservativeStaticV": [1.189 * (1 + 8.87 * .99 / 1.01), 1.237 * (1 + 8.87 * 1.01 / .99)],
        "negativeConservativeStaticV": [-.024 - (1.225 + .024) * kmax, .024 - (1.2 - .024) * kmin],
        "boundsMeaning": "Independent datasheet voltage extrema and 1% resistor endpoints. Not a statistical result or a transient/ripple bound. FBP/FBN errors already included; do not add the aggregate DC accuracy again.",
        "feedforwardRecommendedPf": {"C1": 6.8e-6 / 887000 * 1e12, "C2": 7.5e-6 / 1000000 * 1e12},
        "existingCnPf": 10000, "recommendedCnPf": 4700,
        "existingCpPf": 4700, "recommendedCpPf": 10000,
        "controlFilterTimeConstantUs": 100 * 100e-9 * 1e6,
        "notes": ["PSP/PSN are correctly grounded: power-save disabled.", "ENP/ENN tied to filtered VIN: automatic startup, no independent sequencing or power-good indication.", "About 1 ms soft-start current-limit ramp is not a guarantee of simultaneous settled +/-12 V rails.", "R5 RC filter is conditional: fast input edges >=275 mV/us require the datasheet ferrite-bead alternative."]
    },
    "lp2985": {
        "inputSource": "VPOS12, not VIN_RAW",
        "nominalOutputV": 5,
        "legacyStandardWorst1to50mAOverTemperatureV": [5 * .965, 5 * 1.035],
        "newChipWorstOverTemperatureV": [4.95, 5.05],
        "effectiveCapacitanceLegacyMinimumUf": 2.2,
        "effectiveCapacitanceNewMinimumUf": 1.0,
        "exampleRequiredBiasRetentionForC15": 2.2 / (4.7 * .9 * .85),
        "capacitanceExampleMeaning": "Illustrative 10% initial tolerance and 15% temperature loss, excluding aging. Requires supplier DC-bias data and ESR; not a measured capacitor guarantee.",
        "powerLossAt5mAApproxW": (1.213 * 9.87 - 5) * .005,
        "powerLossAt150mAApproxW": (1.213 * 9.87 - 5) * .15,
        "recommendation": "Retain for restricted-range prototype after chip/MLCC checks; use an adjustable low-noise 5.25 V regulator for the revised full-range design. TPS7A49 is a candidate requiring footprint and thermal redesign, not a drop-in replacement.",
    },
    "dac8562t": {
        "existingGain": g,
        "idealEndpointV": [-2.5 * g, (5 * 65535 / 65536 - 2.5) * g],
        "outputLsbV": 5 / 65536 * g,
        "maximumInlOutputV": 12 * 5 / 65536 * g,
        "offsetContributionOutputV": .004 * g,
        "gainErrorContributionAt5VOutputV": .0015 * 5 * g,
        "referenceContributionAt10VApproxV": .005 / 2.5 * 2.5 * g,
        "resistorOnlyZeroV": resistor_corners(24900, 100000, 24900, 100000, .001, 2.5, 2.5),
        "resistorOnlyNegativeEndpointV": resistor_corners(24900, 100000, 24900, 100000, .001, 0, 2.5),
        "resistorOnlyPositiveEndpointV": resistor_corners(24900, 100000, 24900, 100000, .001, 5, 2.5),
        "opaOffsetContribution25CV": 50e-6 * (1 + g),
        "opaInputOffsetCurrentContribution25CV": 2.8e-9 * 100000,
        "typicalDacLoadingOutputErrorAt5V": 5 / (24900+100000) * 5 * g,
        "errorBudgetMeaning": "Individual explanatory contributions, not summed: full-scale, gain, offset and INL definitions overlap. Datasheet DAC tests use an unloaded output; present loading/ripple/temperature must also be validated. Calibration removes affine error, not quantization or all INL.",
        "revisedGainWith24k3": gp,
        "revisedIdealDacVoltagesFor10V": [2.5 - 10 / gp, 2.5 + 10 / gp],
        "revisedIdealCodesFor10V": [(2.5 - 10 / gp) / 5 * 65536, (2.5 + 10 / gp) / 5 * 65536],
        "codeLinearityCharacterizationInterval": [512, 65024],
        "digitalPowerSequencing": "All digital inputs must be <=AVDD+0.3 V absolute, within 0..AVDD for operation. Move R8/R9/R10 to regulated DAC AVDD and add power-off isolation/enable for external MCU signals.",
        "onePullupPossibleClampCurrentMa": (5 - .3) / 10000 * 1000,
        "resetCommands": {"fullSoftwareReset": "0x280001", "writeAndUpdateBothMidscale": "0x1F8000", "enableInternalReference": "0x380001", "explicitBothGain2": "0x020000"},
        "porRequirement": "AVDD below 0.7 V for >=1 ms to guarantee POR; an excursion between 0.7 and 2.2 V does not guarantee reset.",
        "startupOrder": ["Hardware output mute asserted; MCU inputs isolated or Hi-Z until DAC AVDD is valid.", "Wait for positive/negative rails and DAC AVDD to be valid and stable; do not rely on a blind 1 ms delay.", "Full software reset 0x280001.", "Write and update BOTH channels to 0x8000, 0x1F8000, while reference remains off.", "Enable internal reference 0x380001, which also selects gain=2; optionally explicitly issue 0x020000.", "Wait for the loaded reference and DAC/amp outputs to settle; verify ~2.5 V DAC, ~0 V board output.", "Release output mute, then apply calibrated, limited commands and slow initial ramps."],
        "clrMeaning": "CLR or register reset with the reference enabled selects zero DAC code, corresponding to about -10.04 V at the current bipolar output. It is not a zero-output command.",
    },
    "q1Replacement": {
        "old": "Si2323DS-T1-E3", "new": "Si2323DDS-T1-GE3", "supplierPart": "C165449",
        "manufacturer": "Vishay", "manufacturerRecommended": True,
        "lastTimeBuy": "2025-01-21", "lastTimeShip": "2025-07-21",
        "vdsV": -20, "vgsAbsoluteV": 8,
        "pinMap": {"1": "Gate", "2": "Source", "3": "Drain"},
        "rdsMaxAtMinus4p5VOhm": {"old": .039, "new": .039},
        "gateChargeMaxAtMinus4p5VnC": {"old": 19, "new": 21},
        "qualification": "Electrical/pin replacement selected. The library footprints have different geometry names; compare actual pad/lead dimensions before retaining/replacing the existing footprint. BSW current and startup must be measured. Not silently substituted into the original project.",
    },
    "stm32h747Module": {
        "baselineVrefV": 3.3, "baselineVddaV": 3.3, "resolutionBits": 12,
        "bufferedDacRangeV": [.2, 3.1], "gain": gm,
        "reference": "MCU's actual VREF+ via J5. Half-reference buffered locally. Do not substitute an unrelated 3.3 V rail without recalibration.",
        "nominalInputFor10V": [1.65 - 10 / gm, 1.65 + 10 / gm],
        "outputLsbV": 3.3 / 4096 * gm,
        "maximumInlContributionV": 4 * 3.3 / 4096 * gm,
        "monotonicityGuaranteedBits": 10,
        "gainErrorPercentMax": 1,
        "nominalSafeCodeInterval4095Scaling": [math.ceil(.25 / 3.3 * 4095), math.floor(3.05 / 3.3 * 4095)],
        "codeScalingMeaning": "First estimate using ST's nominal DOR/4095 convention. Clamp again with measured per-channel calibration and actual VREF. LSB specification uses VREF/4096.",
        "schematicStatus": "editable schematic draft, separate project; relay footprint/procurement and analog transient validation pending",
        "sourceCableRequirement": "No 50 ohm termination. ST settling/accuracy conditions use CL<=50 pF: use a source-side buffer for ordinary coax; a resistor placed only at the receiver does not isolate the MCU from the cable capacitance.",
    },
}
save_json(REVIEW / "power-accuracy-calculations.json", calculations)


def parse_docs(source):
    docs, current = [], None
    for line in source.splitlines():
        if "||" not in line:
            continue
        a, b = line.split("||", 1)
        header = json.loads(a)
        try:
            payload = json.loads(b.rstrip("|"))
        except json.JSONDecodeError:
            # Deleted records have empty bodies; BLOB resources are not JSON.
            # The daughter circuit does not depend on the image resources.
            continue
        if header["type"] == "DOCHEAD":
            current = []
            docs.append(current)
        current.append((header, payload))
    return docs


with zipfile.ZipFile(SOURCE) as archive:
    original = parse_docs(archive.read("DAC8562 module.epru").decode("utf-8"))
doc_by_id = {d[0][1]["uuid"]: d for d in original}
old_page = next(d for d in original if d[0][1]["docType"] == "SCH_PAGE")
old_components = {h["id"]: p for h, p in old_page if h["type"] == "COMPONENT"}
old_attrs = {}
for h, p in old_page:
    if h["type"] == "ATTR" and p.get("parentId") in old_components:
        old_attrs.setdefault(p["parentId"], {})[p["key"]] = p["value"]
templates = {}
for component_id, attrs in old_attrs.items():
    name = attrs.get("Designator")
    if name:
        templates.setdefault(name, []).append((old_components[component_id], attrs))
libraries = [copy.deepcopy(d) for d in original if d[0][1]["docType"] in ["SYMBOL", "DEVICE", "FOOTPRINT"]]
library_ids = {d[0][1]["uuid"] for d in libraries}
page_uuid, sch_uuid, board_uuid = uid(), uid(), uid()
page = []
components, wires, texts, expected = [], [], [], {}


def record(kind, data, primitive_id=None, into=None):
    target = page if into is None else into
    header = {"type": kind, "ticket": len(target) + 1}
    if primitive_id is not None:
        header["id"] = primitive_id
    target.append((header, data))
    return primitive_id


def attr(parent, key, value, x=None, y=None, visible=False):
    record("ATTR", {"parentId": parent, "key": key, "value": value,
           "x": x, "y": y, "rotation": 0, "valueVisible": visible, "keyVisible": False,
           "fontFamily": "Arial", "fontSize": 7, "align": "LEFT_BOTTOM", "zIndex": len(page)}, uid())


def text(x, y, value, size=10):
    y = -y
    record("TEXT", {"x": x, "y": y, "value": value, "rotation": 0,
           "fontFamily": "Arial", "fontSize": size, "align": "LEFT_BOTTOM",
           "color": "#243746", "zIndex": len(page)}, uid())
    texts.append((x, y, value, size))


def wire(net, points, show=True):
    wid = uid()
    record("WIRE", {"zIndex": len(page)}, wid)
    for a, b in zip(points, points[1:]):
        if a != b:
            record("LINE", {"startX": a[0], "startY": a[1], "endX": b[0], "endY": b[1],
                   "lineGroup": wid, "strokeColor": None, "strokeStyle": None,
                   "strokeWidth": None, "fillColor": None, "fillStyle": None}, uid())
    attr(wid, "NET", net, points[-1][0], points[-1][1] + 3, show)
    wires.append((net, points, show))


def component(template, name, x, y, rotation=0, part=0, value=None, precise=False):
    y = -y
    base, props = templates[template][part]
    props = copy.deepcopy(props)
    cid = uid()
    data = {"partId": base["partId"], "x": x, "y": y, "rotation": rotation,
            "isMirror": False, "attrs": {}, "zIndex": len(page)}
    record("COMPONENT", data, cid)
    props["Designator"] = name
    props["Unique ID"] = "h747-" + name
    if template == "U4":
        props["Multi-Part Group"] = "h747-" + name
    if value is not None:
        props.update({"Name": value, "Value": value})
        old_device = copy.deepcopy(doc_by_id[props["Device"]])
        new_device_uuid = uid()
        old_device[0][1]["uuid"] = new_device_uuid
        metadata = next(p for h, p in old_device if h["type"] == "META")
        metadata["title"] = "GENERIC " + value + (" 0.01%" if precise else "")
        metadata["source"] = ""
        attributes = metadata["attributes"]
        for key in ["Supplier Part", "LCSC Part Name", "Manufacturer", "Manufacturer Part", "Datasheet", "Supplier"]:
            attributes[key] = ""
            props[key] = ""
        attributes.update({"Name": value, "Value": value, "Tolerance": "±0.01%" if precise else "±1%"})
        if precise:
            attributes["Temperature Coefficient"] = "<=10ppm/C; ratio tracking preferred"
            props.update({"Tolerance": "±0.01%", "Temperature Coefficient": "<=10ppm/C; ratio tracking preferred"})
        libraries.append(old_device)
        props["Device"] = new_device_uuid
    for key, val in props.items():
        if key == "Designator":
            attr(cid, key, val, x - 18, y + 27, True)
        elif key == "Name":
            attr(cid, key, val, x - 18, y - 32, True)
        elif key not in ["Reuse Block", "Group ID", "Channel ID", "Relevance"]:
            attr(cid, key, val)
    symbol = doc_by_id[props["Symbol"]]
    pin_names = {p["parentId"]: str(p["value"]) for h, p in symbol
                 if h["type"] == "ATTR" and p.get("key") == "Pin Number"}
    pins = {}
    radians = math.radians(rotation)
    for h, p in symbol:
        if h["type"] == "PIN" and p.get("partId") == base["partId"]:
            px = p["x"] * math.cos(radians) - p["y"] * math.sin(radians) + x
            py = p["x"] * math.sin(radians) + p["y"] * math.cos(radians) + y
            pins[pin_names[h["id"]]] = (round(px, 6), round(py, 6))
    obj = {"id": cid, "name": name, "template": template, "x": x, "y": y,
           "rotation": rotation, "pins": pins, "value": props.get("Name", ""), "precise": precise,
           "partId": base["partId"], "nets": {}}
    components.append(obj)
    return obj


def connect(obj, pin, net, end=None, show=True):
    point = obj["pins"][str(pin)]
    if end is None:
        direction = -1 if point[0] <= obj["x"] else 1
        end = (point[0] + direction * 25, point[1])
        if point[0] == obj["x"]:
            end = (point[0], point[1] + (25 if point[1] >= obj["y"] else -25))
    wire(net, [point, end], show)
    obj["nets"][str(pin)] = net
    key = obj["name"] + "." + str(pin)
    if key not in expected.setdefault(net, []):
        expected[net].append(key)


record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": page_uuid, "client": "codex-power-review",
       "editVersion": "3.2.149.88089769"})
record("META", {"title": "P1 - MCU DAC SMA module", "schematic": sch_uuid, "source": "", "zIndex": 1}, "META")
record("CANVAS", {"originX": 0, "originY": 0}, "CANVAS")
text(70, 0, "STM32H747 internal DAC -> SMA input -> bipolar SMA output | 2 channels | DRAFT", 15)
text(70, -32, "Separate analog daughter circuit. VREF+=3.3V baseline; +/-12V and common GND supplied by the reviewed power block.", 9)
text(70, -53, "No 50-ohm termination. Use an MCU/source-side buffer for coax; native MCU CL accuracy condition is <=50pF.", 9)

# The existing 2x5 connector footprint is retained as a clearly documented interface.
power = component("J1", "J5", 140, -150)
power_map = {"1": "VPOS12", "2": "GND", "3": "VNEG12", "4": "GND", "5": "MCU_VREF_PLUS",
             "6": "GND", "7": "MUTE_COIL_5V", "8": "MUTE_DRAIN_N", "9": "GND", "10": "GND"}
for pin, net in power_map.items():
    connect(power, pin, net)
text(70, -335, "J5: 1=+12V  2=GND  3=-12V  4=GND  5=MCU VREF+  6=GND", 8)
text(70, -351, "7=5V relay supply  8=external fail-off low-side coil driver  9/10=GND", 8)
text(70, -367, "J5.8 is NOT a GPIO input: drive only with a rated transistor + flyback diode, gated by power-good AND MCU enable.", 8)

rh = component("R8", "R31", 415, -145, 270, value="10k", precise=True)
rl = component("R8", "R32", 415, -270, 270, value="10k", precise=True)
for obj, pin, net in [(rh, 1, "MCU_VREF_PLUS"), (rh, 2, "BIAS_HALF"), (rl, 1, "BIAS_HALF"), (rl, 2, "GND")]:
    connect(obj, pin, net)
refbuf = component("U4", "U2", 620, -165, part=0)
for pin, net in {1: "VBIAS", 2: "VBIAS", 3: "BIAS_HALF", 4: "VNEG12", 8: "VPOS12"}.items():
    connect(refbuf, pin, net)
spare = component("U4", "U2", 870, -165, part=1)
for pin, net in {5: "GND", 6: "SPARE_OUT", 7: "SPARE_OUT"}.items():
    connect(spare, pin, net)
text(380, -90, "01 Reference tracking | VBIAS=MCU VREF+/2, buffered | spare amplifier terminated", 10)

for ch, y, part in [("A", -470, 0), ("B", -825, 1)]:
    base = 0 if ch == "A" else 10
    text(70, y + 90, "02 Channel " + ch + " | nominal Vout=(100k/14k)*(Vin - MCU VREF+/2)", 11)
    text(70, y + 68, "VREF+=3.3V: target input 0.25..3.05V for +/-10V; H747 buffered permitted range 0.2..3.1V.", 8)
    jack = component("J2", "J1" if ch == "A" else "J2", 105, y, 180)
    for pin in [1, 2, 3, 4]:
        connect(jack, pin, "GND", show=False)
    connect(jack, 5, "MCU_" + ch)
    rin = component("R8", "R" + str(base + 1), 225, y, value="1k")
    connect(rin, 1, "MCU_" + ch)
    connect(rin, 2, "IN_" + ch)
    rbias = component("R8", "R" + str(base + 2), 275, y - 100, 270, value="10M")
    connect(rbias, 1, "IN_" + ch)
    connect(rbias, 2, "VBIAS")
    buf = component("U4", "U1", 420, y, part=part)
    mapping = {1: "BUF_A", 2: "BUF_A", 3: "IN_A", 4: "VNEG12", 8: "VPOS12"} if ch == "A" else {5: "IN_B", 6: "BUF_B", 7: "BUF_B"}
    for pin, net in mapping.items():
        connect(buf, pin, net)
    ri = component("R12", "R" + str(base + 3), 565, y + 10, value="14k", precise=True)
    rg = component("R13", "R" + str(base + 4), 650, y - 80, 270, value="100k", precise=True)
    rr = component("R12", "R" + str(base + 5), 630, y - 180, value="14k", precise=True)
    rf = component("R13", "R" + str(base + 6), 875, y - 160, value="100k", precise=True)
    for obj, pin, net in [(ri, 1, "BUF_" + ch), (ri, 2, ch + "_PLUS"),
                          (rg, 1, ch + "_PLUS"), (rg, 2, "GND"),
                          (rr, 1, "VBIAS"), (rr, 2, ch + "_MINUS"),
                          (rf, 1, ch + "_SENSE"), (rf, 2, ch + "_MINUS")]:
        connect(obj, pin, net)
    amp = component("U4", "U3", 790, y, part=part)
    mapping = {1: "A_RAW", 2: "A_MINUS", 3: "A_PLUS", 4: "VNEG12", 8: "VPOS12"} if ch == "A" else {5: "B_PLUS", 6: "B_MINUS", 7: "B_RAW"}
    for pin, net in mapping.items():
        connect(amp, pin, net)
    iso = component("R16", "R" + str(base + 7), 975, y)
    connect(iso, 1, ch + "_RAW")
    connect(iso, 2, ch + "_SENSE")
    cf = component("C25", "C1" if ch == "A" else "C3", 875, y - 80)
    connect(cf, 1, ch + "_MINUS")
    connect(cf, 2, ch + "_RAW")
    co = component("C22", "C2" if ch == "A" else "C4", 1080, y - 95, 270)
    connect(co, 1, ch + "_SENSE")
    connect(co, 2, "GND")
    out = component("J2", "J3" if ch == "A" else "J4", 1470, y)
    connect(out, 5, "SMA_OUT_" + ch)
    for pin in [1, 2, 3, 4]:
        connect(out, pin, "GND", show=False)
    text(1015, y + 40, "100 ohm + 22pF local HF feedback; DC feedback senses BEFORE mute relay", 7)

# A generic DPDT relay is a deliberately explicit procurement item, not a falsely
# identified stock part. Its default contact position grounds both SMA outputs.
relay_symbol_uuid, relay_device_uuid = uid(), uid()
relay_symbol = []
record("DOCHEAD", {"docType": "SYMBOL", "uuid": relay_symbol_uuid, "client": "codex-power-review"}, into=relay_symbol)
record("META", {"title": "DPDT fail-off output mute", "type": 2, "source": ""}, "META", relay_symbol)
for suffix, pin_spec in [
    ("A", [(1, "NO_A", -55, 15), (2, "NC_A GND", -55, -15), (3, "COM_A", 55, 0)]),
    ("B", [(4, "NO_B", -55, 15), (5, "NC_B GND", -55, -15), (6, "COM_B", 55, 0)]),
    ("COIL", [(7, "COIL +5V", -55, 0), (8, "COIL DRAIN", 55, 0)]),
]:
    part_id = "DPDT." + suffix
    record("PART", {"BBOX": [-40, -25, 40, 25], "title": part_id}, part_id, relay_symbol)
    record("RECT", {"partId": part_id, "dotX1": -40, "dotY1": -25, "dotX2": 40, "dotY2": 25,
           "rotation": 0, "strokeWidth": 1, "fillColor": "", "strokeColor": None}, uid(), relay_symbol)
    for number, label, px, py in pin_spec:
        pid = uid()
        record("PIN", {"partId": part_id, "x": px, "y": py, "length": 15,
               "rotation": 0 if px < 0 else 180, "display": True, "pinShape": "NONE", "zIndex": number}, pid, relay_symbol)
        for key, val, vis in [("Pin Number", str(number), True), ("Pin Name", label, True), ("Pin Type", "Undefined", False)]:
            record("ATTR", {"partId": part_id, "parentId": pid, "key": key, "value": val,
                   "x": px + (17 if px < 0 else -17), "y": py + 3, "valueVisible": vis,
                   "keyVisible": False, "fontSize": 5, "align": "LEFT_BOTTOM"}, uid(), relay_symbol)
libraries.append(relay_symbol)
relay_device = []
record("DOCHEAD", {"docType": "DEVICE", "uuid": relay_device_uuid, "client": "codex-power-review"}, into=relay_device)
record("META", {"title": "DPDT 5V non-latching relay - procurement required", "source": "", "attributes": {
    "Symbol": relay_symbol_uuid, "Designator": "K?", "Name": "DPDT 5V FAIL-OFF",
    "Add into BOM": "yes", "Convert to PCB": "yes", "Manufacturer Part": "",
    "Supplier Part": "", "Footprint": "", "Description": "5V non-latching DPDT signal relay; coil <=50mA; break-before-make; actual MPN, footprint, release time and signal contact specs required. Generic logical pin numbers must be remapped to selected part."}}, "META", relay_device)
libraries.append(relay_device)
for suffix, x, y, mapping in [
    ("A", 1260, -470, {1: "A_SENSE", 2: "GND", 3: "SMA_OUT_A"}),
    ("B", 1260, -825, {4: "B_SENSE", 5: "GND", 6: "SMA_OUT_B"}),
    ("COIL", 1220, -1115, {7: "MUTE_COIL_5V", 8: "MUTE_DRAIN_N"}),
]:
    y = -y
    part_id, cid = "DPDT." + suffix, uid()
    record("COMPONENT", {"partId": part_id, "x": x, "y": y, "rotation": 0, "isMirror": False, "attrs": {}, "zIndex": len(page)}, cid)
    for key, val in {"Symbol": relay_symbol_uuid, "Device": relay_device_uuid, "Designator": "K1",
                     "Unique ID": "h747-K1", "Multi-Part Group": "h747-K1", "Name": "DPDT FAIL-OFF"}.items():
        attr(cid, key, val, x - 30 if key in ["Designator", "Name"] else None,
             y + 35 if key == "Designator" else y - 40, key in ["Designator", "Name"])
    symbol_pins = {str(p["value"]): p["parentId"] for h, p in relay_symbol if h["type"] == "ATTR" and p.get("key") == "Pin Number" and p.get("partId") == part_id}
    pins = {n: (x + p["x"], y + p["y"]) for n, pid in symbol_pins.items() for h, p in relay_symbol if h["type"] == "PIN" and h["id"] == pid}
    obj = {"id": cid, "name": "K1", "template": "RELAY", "x": x, "y": y, "rotation": 0,
           "pins": pins, "value": "DPDT FAIL-OFF", "precise": False, "partId": part_id, "nets": {}}
    components.append(obj)
    for pin, net in mapping.items():
        connect(obj, pin, net)

# Local supply bypass for all physical amplifier packages.
for i, (designator, x) in enumerate([("U1", 420), ("U2", 620), ("U3", 790)]):
    for j, (rail, y) in enumerate([("VPOS12", -1140), ("VNEG12", -1250)]):
        cap = component("C18", "C" + str(11 + i * 2 + j), x, y, 270)
        connect(cap, 1, rail)
        connect(cap, 2, "GND")
text(70, -1065, "03 Power / mute | 100nF on EACH supply at EACH IC; add local bulk capacitors during PCB integration.", 9)
text(930, -1065, "K1: unenergized -> both outputs GND; energized -> calibrated signal", 8)
text(930, -1083, "MCU enable AND hardware power-good must control the external coil driver.", 8)
text(70, -1370, "DRAFT: no PCB routing. Select precision resistor MPNs, relay footprint and external fail-off driver before manufacture.", 9)
text(70, -1390, "Validate cable stability and relay contact/release transients. Normal shutdown: mute first, wait for release, then remove analog rails.", 8)

def meta_doc(kind, document_uuid, data):
    return [({"type": "DOCHEAD", "ticket": 1}, {"docType": kind, "uuid": document_uuid, "client": "codex-power-review", "editVersion": "3.2.149.88089769"}),
            ({"type": "META", "ticket": 2, "id": "META"}, data)]

docs = libraries + [meta_doc("BOARD", board_uuid, {"title": "STM32H747 analog module", "zIndex": 1}),
                    meta_doc("SCH", sch_uuid, {"title": TITLE, "board": board_uuid, "source": "", "zIndex": 1}), page,
                    copy.deepcopy(next(d for d in original if d[0][1]["docType"] == "CONFIG"))]
native_source = "\n".join(json.dumps(h, ensure_ascii=False, separators=(",", ":")) + "||" +
                          json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "|" for d in docs for h, p in d) + "\n"
native_path = MODULE / "STM32H747_DAC_SMA_2CH_DRAFT.epro2"
with zipfile.ZipFile(native_path, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("project2.json", json.dumps({"title": TITLE, "cbb_project": 0, "editorVersion": "3.2.149.88089769", "description": "Separate 2-channel MCU DAC analog module. Engineering draft; not manufacturing approved."}))
    archive.writestr(TITLE + ".epru", native_source)
save_json(MODULE / "expected-connectivity.json", {"title": TITLE, "pageUuid": page_uuid, "schematicUuid": sch_uuid,
          "nets": {k: sorted(v) for k, v in expected.items()}, "components": components})

# A readable standalone SVG mirrors the same pin/net model; net labels connect
# repeated nodes. This is a real component-level schematic, not a block diagram.
def sx(x): return x + 25
def sy(y): return y + 70
svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1620" height="1520" viewBox="0 0 1620 1520">',
       '<rect width="1620" height="1520" fill="#fff"/>',
       '<style>text{font-family:Arial,sans-serif;fill:#203044} .wire{stroke:#15803d;stroke-width:1.3;fill:none}.symbol{stroke:#922b21;stroke-width:1.3;fill:white}.net{fill:#1d4ed8;font-size:7px}</style>']
for net, points, show in wires:
    svg.append('<polyline class="wire" points="' + ' '.join(f'{sx(x)},{sy(y)}' for x, y in points) + '"/>')
    if show:
        x, y = points[-1]
        svg.append(f'<text class="net" x="{sx(x)}" y="{sy(y)-3}">{html.escape(net)}</text>')
    elif net == "GND":
        x, y = points[-1]
        svg.append(f'<path class="wire" d="M{sx(x)},{sy(y)} v5 m-6,0 h12 m-9,3 h6 m-4,3 h2"/>')
for obj in components:
    x, y = sx(obj["x"]), sy(obj["y"])
    for pin, point in obj["pins"].items():
        px, py = sx(point[0]), sy(point[1])
        svg.append(f'<line class="symbol" x1="{px}" y1="{py}" x2="{x}" y2="{y}"/>')
        svg.append(f'<text x="{px+2}" y="{py-3}" font-size="6">{pin}</text>')
    if obj["template"] == "U4":
        svg.append(f'<polygon class="symbol" points="{x-20},{y-20} {x-20},{y+20} {x+20},{y}"/>')
        svg.append(f'<text x="{x-17}" y="{y+13}" font-size="9">+</text><text x="{x-17}" y="{y-7}" font-size="9">−</text>')
    elif obj["template"] == "RELAY":
        svg.append(f'<rect class="symbol" x="{x-40}" y="{y-25}" width="80" height="50"/>')
        if obj["partId"].endswith("COIL"):
            svg.append(f'<path class="symbol" d="M{x-28},{y} h5 a5,5 0 1,1 10,0 a5,5 0 1,1 10,0 a5,5 0 1,1 10,0 a5,5 0 1,1 10,0 h11"/>')
        else:
            svg.append(f'<path class="symbol" d="M{x-40},{y-15} h14 M{x-40},{y+15} h14 M{x+40},{y} h-16 L{x-23},{y-15}"/>')
            svg.append(f'<text x="{x-39}" y="{y-17}" font-size="5">NC</text><text x="{x-39}" y="{y+23}" font-size="5">NO</text>')
    elif obj["template"].startswith("R"):
        svg.append(f'<rect class="symbol" x="{x-10}" y="{y-5}" width="20" height="10" transform="rotate({obj["rotation"]} {x} {y})"/>')
    elif obj["template"].startswith("C"):
        svg.append(f'<g transform="rotate({obj["rotation"]} {x} {y})"><rect x="{x-7}" y="{y-12}" width="14" height="24" fill="white"/><line class="symbol" x1="{x-4}" y1="{y-9}" x2="{x-4}" y2="{y+9}"/><line class="symbol" x1="{x+4}" y1="{y-9}" x2="{x+4}" y2="{y+9}"/></g>')
    else:
        width = 80 if obj["template"] == "RELAY" else 30
        svg.append(f'<rect class="symbol" x="{x-width/2}" y="{y-25}" width="{width}" height="50"/>')
    svg.append(f'<text x="{x-18}" y="{y-28}" font-size="9" font-weight="bold">{obj["name"]}</text>')
    vx, vy = (x+14, y+3) if obj["rotation"] in [90, 270] and obj["template"].startswith(("R", "C")) else (x-18, y+40)
    svg.append(f'<text x="{vx}" y="{vy}" font-size="8">{html.escape(obj["value"])}</text>')
for x, y, value, size in texts:
    svg.append(f'<text x="{sx(x)}" y="{sy(y)}" font-size="{size}">{html.escape(value)}</text>')
svg.append('</svg>')
(MODULE / "STM32H747_DAC_SMA_2CH_DRAFT.svg").write_text("\n".join(svg), encoding="utf-8")

with (MODULE / "STM32H747_DAC_SMA_BOM_DRAFT.tsv").open("w", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream, delimiter="\t")
    writer.writerow(["Designator", "Value", "Procurement status", "Notes"])
    seen = set()
    for obj in components:
        if obj["name"] in seen:
            continue
        seen.add(obj["name"])
        pending = obj["precise"] or obj["template"] == "RELAY" or (obj["template"].startswith("R") and obj["value"] in ["1k", "10M"])
        writer.writerow([obj["name"], obj["value"], "MPN required" if pending else "Existing project library part", "Matched ratio / <=10ppm/C preferred" if obj["precise"] else ""])


def fmt(value, digits=3):
    return f"{value:.{digits}f}"


tps = calculations["tps65131"]
dac = calculations["dac8562t"]
mcu = calculations["stm32h747Module"]
report = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DAC8562 전원·출력 정확도 검토 및 STM32H747 분리 회로</title>
<style>body{{font-family:"Malgun Gothic",Arial,sans-serif;max-width:1120px;margin:36px auto;padding:0 24px;color:#172033;line-height:1.7;background:#f8fafc}}h1{{font-size:27px}}h2{{margin-top:34px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:10px;border:1px solid #cbd5e1;text-align:left;vertical-align:top}}.callout{{background:#fff4dc;border-left:4px solid #c08020;padding:16px}}.ok{{background:#e5f6ed;padding:16px}}code{{background:#e2e8f0;padding:2px 5px}}a{{color:#1d4ed8}}li{{margin:9px 0}}</style>
<h1>DAC8562 전원·출력 정확도 검토 / STM32H747 별도 SMA 회로</h1>
<p>2026-10-12 · 저장된 최종 프로젝트와 공식 데이터시트 대조 · 원본 설계는 변경하지 않음</p>
<div class="callout">검토서와 별도 회로 초안입니다. 원본 PCB의 제작 승인이 아닙니다. STM32H747 모듈은 MCU 본체를 포함하지 않고 외부 MCU DAC 신호를 받습니다. PCB 합치기·배선은 수행하지 않았습니다.</div>
<h2>1. 먼저 수정해야 하는 항목</h2><table><tr><th>우선순위</th><th>현재 근거</th><th>구체적인 수정안</th></tr>
<tr><td>필수</td><td>R8/R9/R10은 VIN_RAW 5V 풀업, DAC AVDD는 +12V 이후 LP2985에서 지연 생성</td><td>풀업을 DAC AVDD로 이동. MCU의 SCLK/DIN/LDAC/CLR/SYNC는 DAC 무전원 시 Hi-Z를 보장하는 전원 분리 버퍼와 기본 비활성 OE를 적용. 33Ω 직렬 저항은 전원 역급전 보호 대책이 아님.</td></tr>
<tr><td>필수</td><td>U1.18 CN에 C4=10nF / U1.21 CP에 C5=4.7nF</td><td>C4를 4.7nF, C5를 10nF로 교환. <a href="{SOURCES['tps']}">TPS65131 §8.2.2.6.2 및 Figure 8-1</a>. 값 수정 후 전원 안정성 재시험.</td></tr>
<tr><td>필수</td><td>Q1 Si2323DS-T1-E3는 제조사 단종 공지에 포함</td><td>Vishay 권장 Si2323DDS-T1-GE3 / LCSC C165449 선정. 핀 1G/2S/3D 동일, -20V 및 ±8V 동일, -4.5V에서 최대 Ron 39mΩ 동일. 최대 Qg는 19→21nC. 라이브러리 풋프린트 이름이 다르므로 실제 패드 치수 검토 후 교체.</td></tr>
<tr><td>필수</td><td>DAC 코드 0 및 CLR은 음의 최대 출력에 해당</td><td>전원·기준전압·초기화가 완료될 때까지 SMA를 차단/0V로 유지하는 하드웨어 mute 추가. 정상 종료는 mute→접점 해제 확인/지연→아날로그 전원 차단. 예기치 않은 급격한 전원 고장은 릴레이만으로 무과도를 보증할 수 없어 전원 유지 시간 또는 빠른 스위치를 추가 검토.</td></tr>
<tr><td>정확도 개선</td><td>5V LDO 공차와 DAC 출력 레일 근처 오차를 기존 모델이 제외</td><td>전체 ±10V를 사용하려면 AVDD 약 5.25V의 조정형 저잡음 LDO를 검토하고, 24.9kΩ 네 개를 24.3kΩ로 바꿔 유효 코드에 여유 확보. 100kΩ는 유지. 이 변경은 PCB 재설계와 재검증을 요구함.</td></tr>
</table>
<h2>2. TPS65131 전원</h2>
<p>현재 저항값의 공칭 레일은 +{fmt(tps['nominalPositiveV'],5)}V / {fmt(tps['nominalNegativeV'],5)}V입니다. VFBP, VFBN, VREF의 데이터시트 끝값과 분압 저항 1%를 독립적으로 조합하면 정적 계산 범위는 +{fmt(tps['positiveConservativeStaticV'][0])}~+{fmt(tps['positiveConservativeStaticV'][1])}V, {fmt(tps['negativeConservativeStaticV'][0])}~{fmt(tps['negativeConservativeStaticV'][1])}V입니다. 실제 기동/리플/온도 파형을 계산한 값은 아닙니다.</p>
<p>입력 5V와 L1/L2=4.7µH, VREF의 220nF, PSP/PSN=GND는 기본 권장 구성에 부합합니다. PSP/PSN을 GND로 둔 연속 PWM 모드는 유지합니다. ENP/ENN을 VIN_CTRL에 묶었으므로 레일 순서와 전원 양호 신호는 제공하지 않습니다. soft-start 약 1ms는 스위치 전류 제한의 램프 시간이며 출력의 동시 안정화 시간이 아닙니다.</p>
<p>C1 계산값은 {fmt(tps['feedforwardRecommendedPf']['C1'],2)}pF, C2는 7.50pF이므로 7.5pF C0G를 검토합니다. R5=100Ω와 C8=100nF의 시정수는 10µs입니다. 입력 상승률이 275mV/µs 이상인 빠른 핫플러그에서는 §8.2.3.2에 따라 R5를 저 DCR 페라이트 비드로 변경하고 안정성을 확인합니다. 모든 입력/출력 MLCC는 실제 DC 바이어스 유효 용량으로 평가합니다. 스위치 한계 1.95A를 출력 공급 가능 전류로 해석하지 않습니다.</p>
<h2>3. LP2985와 DAC 전원 여유</h2>
<p>LP2985의 IN/EN은 +12V 레일입니다. 입력 5V에서 바로 5V를 만드는 연결이 아니므로 정상 상태의 dropout은 주된 문제가 아닙니다. C14 BYPASS=10nF는 유지합니다. C15=4.7µF 25V X5R은 부품 리비전과 바이어스·온도·공차·ESR 확인을 조건으로 유지할 수 있습니다. legacy 칩 최소 유효 COUT는 2.2µF, new 칩은 1µF입니다. 입력 C13의 유효 용량도 확인합니다. new 칩의 EN 허용 범위는 16V이므로 현재 +12V 직결 자체가 과전압 오류는 아닙니다.</p>
<p>legacy 표준 등급은 1~50mA·전체 온도에서 5V±3.5%인 4.825~5.175V, new 칩은 ±1%인 4.95~5.05V입니다. 5V까지 출력하는 DAC에 충분한 양의 레일 여유가 항상 있다고 볼 수 없습니다. 5mA에서 LDO 손실은 약 {fmt(calculations['lp2985']['powerLossAt5mAApproxW']*1000,1)}mW이지만 150mA에서는 약 1.05W가 됩니다. MCU/릴레이를 이 LDO에 추가로 연결하지 않습니다.</p>
<p>정확도 개선 후보 <a href="{SOURCES['ldo_upgrade']}">TPS7A4901</a>은 5.25V로 설정할 수 있지만 SOT-23-5 직접 대체품이 아닙니다. 총 허용 오차 2.5%에 분압 0.1%를 보수적으로 더한 약 2.7%를 사용하면 DC 5.108~5.392V로 5.5V 이내입니다. 이는 기동 오버슈트를 포함하지 않으며 소자·분압 공차와 기동 최고값을 재확인해야 합니다. 새 LDO의 NR/SS, FB, 출력 MLCC와 역류 조건을 새 데이터시트대로 설계합니다. LP2985 그라운드를 들어 올려 5.25V를 만드는 방식은 채택하지 않습니다.</p>
<h2>4. DAC8562T 출력 정확도</h2>
<p>현재 이상적 전달식은 <code>Vout=(100k/24.9k)*(Vdac−Vref)</code>, DAC 내부 gain=2입니다. 공칭 코드 끝점은 {fmt(dac['idealEndpointV'][0],5)}~+{fmt(dac['idealEndpointV'][1],5)}V이고 SMA에서 1LSB는 {fmt(dac['outputLsbV']*1000,3)}mV입니다. 16비트 분해능과 절대 출력 정확도는 다릅니다.</p>
<table><tr><th>항목</th><th>현재 증폭비에서의 크기</th><th>해석</th></tr>
<tr><td>DAC INL 최대 ±12LSB</td><td>약 ±{fmt(dac['maximumInlOutputV']*1000,2)}mV</td><td>2점 보정으로 모두 제거되지 않음. 라이브러리의 1LSB 표기는 정확도 근거로 사용 금지.</td></tr>
<tr><td>내부 기준 초기 ±5mV</td><td>끝점에서 약 ±{fmt(dac['referenceContributionAt10VApproxV']*1000,2)}mV</td><td>gain 보정 가능. 최대 drift 10ppm/°C는 별도.</td></tr>
<tr><td>0.1% 저항 네 개의 독립 공차</td><td>제로 코드가 아닌 중간 코드의 영점 오차 약 ±{fmt(max(abs(v) for v in dac['resistorOnlyZeroV'])*1000,2)}mV</td><td>상대 비율 정합 및 추적 TCR 중요. 채널별 gain/offset 보정 권장.</td></tr>
<tr><td>DAC offset ±4mV / gain ±0.15%FSR</td><td>개별 환산 약 ±16.1mV / ±30.1mV</td><td>full-scale/offset/gain/INL 정의가 중복되므로 이 표를 단순 합산한 값을 총 보증 오차로 주장하지 않음.</td></tr>
<tr><td>OPA2277UA offset / 입력 오프셋 전류</td><td>25°C 개별 약 0.251mV / 0.280mV</td><td>온도와 저항 불일치 추가. 출력 rail 여유와 부하 조건 확인.</td></tr></table>
<p>고정밀 ±10V용 수정안: R12/R14/R17/R19=24.3kΩ, R13/R15/R18/R20=100kΩ, 가능한 정합 저항/낮은 추적 TCR 사용. 공칭 ±10V에 필요한 Vdac는 0.070~4.930V, 코드는 약 {fmt(dac['revisedIdealCodesFor10V'][0],0)}~{fmt(dac['revisedIdealCodesFor10V'][1],0)}로 선형성 기준 구간 512~65024 안에 여유가 생깁니다. AVDD 여유 확보와 함께 적용해야 하며 실제 기준전압, DAC gain/offset, 부하로 코드 제한을 다시 계산합니다.</p>
<p>2점 이상 채널별 보정, 필요 시 다점 LUT 및 온도 보정을 적용합니다. 1% 정착 시간 12.94µs는 16비트 정착 시간 보증이 아닙니다. precision 용도는 DAC8562T 경로를 우선 사용합니다.</p>
<p>현재 DAC 출력의 입력 저항 경로는 24.9kΩ+100kΩ 부하입니다. DAC 출력 임피던스의 전형값 5Ω을 단순 사용하면 5V 부근에서 SMA 환산 약 0.80mV의 부하 영향이 생길 수 있습니다. 5Ω은 중간 코드에서의 전형값이지 전체 코드의 최대 보증값이 아니므로 이 값은 예시이며 총 오차 보증에 넣지 않습니다. 더 작은 오차에는 DAC 출력 버퍼 추가, 외부 저드리프트 기준전압, 저항 정합 향상을 별도 검토합니다.</p>
<h2>5. DAC 초기화 / 전원 차단</h2><ol>
{''.join('<li>'+html.escape(s)+'</li>' for s in ['하드웨어 출력 mute 유지. DAC 전원이 안정되기 전 MCU 출력은 분리/Hi-Z.', '양·음 레일과 DAC AVDD의 정상 상태를 확인. 고정 1ms 지연만으로 판단하지 않음.', '전체 소프트웨어 리셋 0x280001.', '기준전압 OFF 상태에서 두 채널을 0x8000으로 기록 및 갱신: 0x1F8000.', '내부 기준전압 ON: 0x380001. 이 명령은 gain=2도 선택. 필요 시 0x020000으로 두 gain을 명시.', 'C17/C24가 연결된 기준전압과 출력의 정착 확인 후 mute 해제.', '보정·범위 제한된 명령으로 운전. MCU 재부팅/통신 실패 시 하드웨어 mute. CLR을 0V 출력 용도로 사용하지 않음.'])}
</ol><p>정상 종료는 먼저 mute, 실제 스위치/접점 해제 이후 레일을 내립니다. Brownout 후 POR은 AVDD&lt;0.7V가 1ms 이상 유지되어야 보증됩니다. 0.7~2.2V로만 떨어진 상태는 리셋을 보증하지 않습니다. 소프트웨어 reset은 하드웨어 출력 차단을 대체하지 않습니다.</p>
<h2>6. 분리된 STM32H747 SMA 모듈</h2>
<p><a href="../stm32h747-dac-sma/STM32H747_DAC_SMA_2CH_DRAFT.epro2">EasyEDA 회로 초안</a> · <a href="../stm32h747-dac-sma/STM32H747_DAC_SMA_2CH_DRAFT.svg">회로도 보기</a> · <a href="../stm32h747-dac-sma/STM32H747_DAC_SMA_BOM_DRAFT.tsv">초안 BOM</a></p>
<p>2채널 각각 SMA 입력→1kΩ 보호 저항/10MΩ 중간전압 바이어스→입력 버퍼→정합 차동 증폭기→100Ω 및 22pF 피드백→default-ground DPDT mute→SMA 출력입니다. 3개의 OPA2277 듀얼은 두 입력 버퍼, 기준전압 버퍼/정리된 미사용 증폭기, 두 출력 증폭기로 나눴습니다. 기준전압은 별도 J5를 통해 MCU의 실제 VREF+를 받아 절반으로 나눕니다. 외부 MCU나 GPIO는 이 회로에 포함하지 않았습니다.</p>
<p>H747: VDDA=1.8~3.6V, VREF+=1.8V~VDDA. 버퍼 ON 출력은 0.2V~VREF+−0.2V입니다. 3.3V 기준에서 증폭비 100k/14k={fmt(gm,4)}를 사용하여 입력 0.25~3.05V를 ±10V로 변환합니다. SMA 1LSB는 약 {fmt(mcu['outputLsbV']*1000,2)}mV, INL ±4LSB만 환산해도 약 ±{fmt(mcu['maximumInlContributionV']*1000,2)}mV입니다. 보정 후에도 16비트 외장 DAC의 분해능을 얻을 수 없습니다. 12비트 전체 monotonic 보증도 아니며 데이터시트는 10비트를 명시합니다.</p>
<p>STM32 DAC의 버퍼 보정(HAL_DACEx_SelfCalibrate 지원 여부를 실제 CubeH7 버전에서 확인), 정상 모드, 양 채널 중간 코드 preload, MCU 초기 출력 차단을 적용합니다. 초기 nominal 제한 코드는 {mcu['nominalSafeCodeInterval4095Scaling'][0]}~{mcu['nominalSafeCodeInterval4095Scaling'][1]}이지만 실제 VREF와 측정 보정에 맞춰 제한합니다. VREF가 2.5V나 2.048V라면 현재 3.3V 설계의 ±10V 범위를 그대로 적용하지 않습니다.</p>
<p>코액스 케이블을 50Ω 종단하지 않습니다. 수신 보드의 입력 버퍼만으로 MCU 핀의 케이블 용량이 사라지지 않으므로 일반적인 케이블에는 MCU/SMA 송신단에 별도 버퍼를 배치합니다. 간단한 송신단 직렬 저항은 부하·정착·DC 오차를 측정한 경우만 채택합니다. 릴레이는 구체 MPN/접점 핀/풋프린트와 외부 flyback 보호 드라이버가 아직 확정되지 않은 논리적 초안이며 이를 BOM에 명시했습니다.</p>
<p>모듈 아날로그 전원이 꺼진 동안 MCU 입력도 분리/Hi-Z 상태로 만들고, 송신단 버퍼에는 전원 OFF 입력 보호를 적용해야 합니다. 입력 1kΩ만으로 무전원 동작의 적합성을 보증하지 않습니다. 10MΩ 바이어스는 케이블 분리 시 부유 입력을 억제하지만 입력 바이어스 전류 때문에 정확한 0V 출력은 보장하지 않습니다. 케이블 분리 상태는 mute로 처리합니다.</p>
<p><a href="{SOURCES['stm_errata']}">STM32H747 ES0445 Rev.6 §2.11</a>도 초기화에 적용합니다. 해당 실리콘 리비전에서 데이터 레지스터 초기화 전에 MODE를 000 이외 값으로 설정하면 DAC 출력이 잘못될 수 있으므로 <strong>데이터 레지스터에 먼저 기록한 뒤 MODE를 설정</strong>합니다. 실제 CubeH7/HAL 순서를 확인하고, 출력 mute 상태에서 버퍼 보정·중간 코드 설정·enable·정착 확인을 마친 후 mute를 해제합니다. DMA 사용 시 소프트웨어/하드웨어 트리거를 동시에 쓰는 underrun 플래그 누락 조건도 피합니다. 내부 VREFBUF를 사용하는 경우 §2.12의 잔류 전압에 의한 기동 overshoot와 Hold 모드 제한을 추가 적용합니다. 현재 초안의 기준은 VDDA와 연결된 3.3V VREF+이며, 2.048V/2.5V 내부 VREFBUF용 설계는 아닙니다.</p>
<h2>7. 검증 범위와 다음 실행</h2>
<p>부품 핀/현재 넷/수식/저항 공차 끝값/제조사 단종 대체품을 확인했습니다. 새 파일은 별도 파서로 핀과 와이어의 실제 좌표, 부유 핀과 다른 넷의 교차를 검사합니다. EasyEDA 자동 가져오기가 완료 결과를 반환하지 않아 실제 가져오기와 ERC는 미확인입니다. TPS65131 기동·LP2985 안정성의 SPICE 또는 실측, 새 모듈의 케이블 과도 해석과 실제 PCB DRC도 아직 수행하지 않았습니다. 시뮬레이션과 실측을 먼저 수행한 후 PCB 한쪽에 새 모듈을 통합합니다. 양·음 레일 전류, 5V 전류, MCU VREF+와 두 출력의 기동/종료 파형을 동시에 측정합니다.</p>
<p>최악 전압을 넘는 STM32 입력 및 DAC 역급전을 우선 해소하고, CP/CN 수정·Q1 대체, 출력 mute/감독 회로, AVDD/증폭비 정밀도 변경을 순서대로 반영합니다. 원본의 과거 DRC 통과 기록은 수정 회로의 검증 결과로 재사용하지 않습니다.</p>
<p>2026-10-12 확인 기준 <a href="https://www.ti.com/product/TPS65131">TPS65131</a>, <a href="https://www.ti.com/product/LP2985">LP2985</a>, <a href="https://www.ti.com/product/DAC8562T">DAC8562T</a>는 제조사 ACTIVE 상태입니다. 단종이 확인된 Q1은 위 대체품을 선정했습니다. 나머지 BOM의 모든 수동소자·커넥터 주문 코드를 제조사 수명주기 문서로 전수 인증한 것은 아니며, 구매 전에 포장 단위·정확한 MPN·재고를 확인합니다. 저항값 변경 부품과 신규 릴레이를 기존 공급사 코드로 위장하지 않고 BOM에 MPN 미확정으로 표시했습니다.</p>
<h2>공식 근거</h2><ul>
<li><a href="{SOURCES['tps']}">TI TPS65131 SLVS493E</a>: pp.3–5,9–16, 보상·기동·부품 선정</li>
<li><a href="{SOURCES['ldo']}">TI LP2985 SLVS522S</a>: pp.4–7,20–24, 칩 리비전·MLCC·역류</li>
<li><a href="{SOURCES['dac']}">TI DAC8562T SLASE61A</a>: pp.5–7,30–38, 정확도·POR·명령</li>
<li><a href="{SOURCES['opa']}">TI OPA2277 SBOS079C</a>: pp.8–9, offset·입력 전류·출력 범위</li>
<li><a href="{SOURCES['stm']}">ST STM32H747 DS12930 Rev.3, January 2026</a>: Tables 92–93, pp.193–195</li>
<li><a href="{SOURCES['stm_errata']}">ST ES0445 Rev.6</a>: §2.11 DAC / §2.12 VREFBUF, p.25</li>
<li><a href="{SOURCES['ptn']}">Vishay PTN-SIL-042-2024-REV-0 (제조사 공지, DigiKey 보관본)</a>: 단종 및 권장 대체품</li>
<li><a href="{SOURCES['qnew']}">Vishay Si2323DDS</a> / <a href="{SOURCES['qold']}">Si2323DS</a>: pp.1–2, 핀·Ron·Qg</li>
</ul><p><a href="power-accuracy-calculations.json">계산값·가정·원본 해시 JSON</a></p></html>'''
(REVIEW / "power-accuracy-review.html").write_text(report, encoding="utf-8")
save_json(MODULE / "build-verification.json", {
    "status": "source-structure-and-pin-map-verified; live-import-and-ERC-pending",
    "nativeFile": native_path.name, "nativeSha256": hashlib.sha256(native_path.read_bytes()).hexdigest(),
    "physicalComponents": len({o["name"] for o in components}), "nets": len(expected),
    "connectedPins": sum(len(v) for v in expected.values()),
    "pageUuid": page_uuid, "schematicUuid": sch_uuid,
    "missingConnectedPins": [o["name"]+"."+p for o in components for p in o["pins"] if p not in o["nets"]],
    "liveImportResult": "Attempted through official EasyEDA API; no imported project returned. Live import/ERC are unconfirmed.",
    "pending": ["Generic relay procurement/footprint and external coil driver/dual-rail power-good", "Precision resistor MPNs", "Cable/analog transient checks", "PCB layout and manufacturing review"],
})
print(json.dumps({"review": str(REVIEW / "power-accuracy-review.html"), "module": str(native_path),
                  "physicalComponents": len({o["name"] for o in components}), "nets": len(expected)}, ensure_ascii=False))
