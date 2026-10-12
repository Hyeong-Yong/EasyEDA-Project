"""Save a consistent native copy only after the actual EasyEDA checks pass."""
import hashlib
import importlib.util
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "output/pcb-two-zone"
load = lambda name: json.loads((out / name).read_text(encoding="utf8"))
pcb = load("after-apply-reopened-validation.json")
schematic = load("after-apply-schematic-validation.json")
comparison = load("after-apply-electrical-comparison.json")
apply = load("after-apply-change-audit.json")
dfm = load("gerber-dfm-processing.json")
gerber = load("gerber-dfm-audit.json")
assert pcb["saved"] and pcb["closed"] and pcb["reopened"]
assert pcb["passed"] is True and pcb["details"] == []
assert all(p["saved"] and p["reopened"] and p["passed"] is True and p["details"] == [] for p in schematic["pages"])
assert comparison["netDifferences"] == {}
assert comparison["counts"] == {"schematicComponents":154,"pcbComponents":154,"schematicNets":90,"pcbNets":90}
assert apply["changesByType"] == {"COMPONENT":154}
for c in apply["changes"]["COMPONENT"]:
    restored = json.loads(json.dumps(c["after"]))
    assert restored["attrs"].pop("Channel ID")
    assert restored == c["before"]
assert dfm["copperMasksOutlineDrillsByteIdentical"]
assert dfm["clearanceToMaskActuallyMeasuredMm"] >= 0.149
assert gerber["unsupportedRecords"] == 0
target = out / "DAC8562 module_two_zone_PCB_DRC_clean.eprj2"
spec = importlib.util.spec_from_file_location("cio",root / "scripts/correction-io.py")
io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)
docs = io.read_export(out / "DAC8562 module_two_zone_PCB_DRC_clean.epro2")
original = io.read_export(root / "backups/DAC8562_live_before_schematic_correction_2026-10-12.epro2")
panel_unchanged = io.data_hash(docs["458da9240aa63aad"]) == io.data_hash(original["458da9240aa63aad"])
assert panel_unchanged
doc = io.documents(pcb["source"])["4e08f91f9a2c4fe4"]
export_doc = docs["4e08f91f9a2c4fe4"]
export_normalization = Counter()
for key in set(doc["records"]) | set(export_doc["records"]):
    a = doc["records"].get(key,(None,None))[1]
    b = export_doc["records"].get(key,(None,None))[1]
    if a == b:
        continue
    kind = key[0]
    if kind == "LINE":
        assert a is None and b is not None
        assert math.hypot(b["startX"]-b["endX"],b["startY"]-b["endY"]) <= 0.101
    elif kind == "POURED":
        assert a is None and ("POUR",json.loads(key[1])[1]) not in doc["records"]
    elif kind == "RULE_SELECTOR":
        assert b is None and a["copperValue"] == a["innerPlaneValue"] == {}
        assert a["ruleKeyValue"] in ({},{"NET_LENGTH_TOLERANCE":["default",None]})
    elif kind == "LAYER":
        assert {k:v for k,v in a.items() if k != "inactiveColor"} == {k:v for k,v in b.items() if k != "inactiveColor"}
    elif kind in ("META","ELE_PLACEHOLDER"):
        assert a is None
    else:
        raise AssertionError(f"Unexpected exported PCB difference: {key}")
    export_normalization[kind] += 1
if target.exists() and "--resume-existing" not in sys.argv:
    raise FileExistsError(target)
if not target.exists():
    with sqlite3.connect((root / "DAC8562 module.eprj2").resolve().as_uri()+"?mode=ro",uri=True) as src:
        with sqlite3.connect(target) as dst:
            src.backup(dst)
with sqlite3.connect(target.resolve().as_uri()+"?mode=ro",uri=True) as dst:
    assert dst.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
counts = dict(Counter(key[0] for key in doc["records"]))
assert counts["COMPONENT"] == 154 and counts["PAD_NET"] == 489
previous = out / "verification-summary.json"
archive = out / "verification-summary-before-apply.json"
if previous.exists() and not archive.exists():
    archive.write_bytes(previous.read_bytes())
report = {
    "status":"Schematic and PCB editing complete; native saved/reopened ERC and DRC passed",
    "nativeFile":str(root / "DAC8562 module.eprj2"),
    "validatedCopy":str(target),
    "validatedCopySha256":hashlib.sha256(target.read_bytes()).hexdigest(),
    "editableProjectExport":"DAC8562 module_two_zone_PCB_DRC_clean.epro2",
    "boardSizeMm":[100,100],"copperLayers":2,
    "zones":{"upper":{"page":"DAC8562","parts":106},"lower":{"page":"DAC_MCU","parts":48}},
    "commonNets":["GND","VIN_RAW","VPOS12","VNEG12","MCU_3V3","DAC_HW_PGOOD"],
    "electricallyIsolated":False,
    "schematicErcPassed":True,"schematicErcDetails":[],
    "pcbDrcPassed":True,"pcbDrcDetails":[],"savedAndReopened":True,
    "independentElectricalComparison":{"counts":comparison["counts"],"pinNetDifferences":{}},
    "applyEffect":{"channelIdAddedToParts":154,"layoutRoutingCopperChanged":False,"recoveryRequired":False},
    "nativePrimitiveCounts":counts,
    "exportNormalizationDifferences":dict(export_normalization),
    "exportNormalizationExplanation":"Native project export retains two orphan POURED caches without live POUR borders, nine sub-0.101mil degenerate segments, stream placeholders and META; live API supplies empty default net rule selectors and normalizes inactive colors. All components, pad-net assignments and meaningful physical geometry match. Live saved/reopened source and native Gerber are the fabrication reference, not flattening historical export caches.",
    "panelUnchanged":panel_unchanged,
    "geometryReference":"placement-audit.json (unchanged by Apply)",
    "gerberNativeExport":"DAC8562_DAC_MCU_100x100_Gerber.zip",
    "gerberDfmCopy":"DAC8562_DAC_MCU_100x100_Gerber_DFM.zip",
    "gerberDfmProcessing":dfm,
    "gerberOutlineMm":gerber["layers"]["GKO"]["coordinateBoundsMm"],
    "gerberNpthHolesMm":gerber["npthHolesMm"],
    "gerberViaDrillCount":gerber["viaDrillCount"],
    "nativeComparisonApiLimitation":"SYS_Tool.netlistComparison reports empty PCB net2 arrays in this runtime even after successful native DRC. Exported Protel pin/net comparison is independently exact; this inconsistent beta API is not reported as a successful comparison.",
    "gitPushRequested":True,
    "gitDeliveryEvidence":"Check the actual commit and origin/main HEAD; EDA evidence does not assert a future push.",
    "limitations":[
        "Ground copper is six calculated SOLID fills. Recompute after moving components or routing; POURED import is unsupported in this v3.2 source API.",
        "The DFM ZIP changes only the top-silkscreen file (mask opening + 0.15mm, board inset 0.15mm); copper, mask, outline and drills are byte-identical to the native export. Native CAD footprint silkscreen is preserved.",
        "Combined PTH drill includes all vias; Via-only DRL is redundant reference data, not an additional drilling pass.",
        "Board outline is 100x100mm; horizontal SMA connector bodies protrude beyond the edges.",
        "J1 retains the original generic 2x5 2.54mm female header; verify its actual mating geometry before procurement.",
        "Precision Susumu resistors require separate procurement; do not substitute generic library supplier resistors for the specified precision parts.",
        "High-impedance outputs only, not 50-ohm terminated load drivers; external STM32H747 source/cable capacitance may require a source-side buffer.",
        "No hardware has been built or tested. Prototype qualification remains: supply ramp/overshoot, DAC initialization, relay timing, output/cable stability and calibrated accuracy.",
        "Fabricator DFM/assembly review is still required before ordering. No fabrication or assembly order has been submitted.",
        "Older output/validated-revision and separate stm32h747-dac-sma artifacts are superseded; use only this project's existing DAC8562 and DAC_MCU pages."
    ]
}
previous.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
print(json.dumps({"validatedCopy":str(target),"schematicErcPassed":True,"pcbDrcPassed":True,"panelUnchanged":panel_unchanged,"sha256":report["validatedCopySha256"]},ensure_ascii=False,indent=2))
