"""Adapt the locally exported Layer Manager JSON to the Gerber job stack."""
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/validation/native-physical-stack-before-ui.json"
OUTPUT = ROOT / "output/validation/native-physical-stack-v19-6l-ui.json"
REPORT = ROOT / "output/validation/native-physical-stack-v19-6l-ui-plan.json"
JOB = ROOT / "보드 자료/MCU_BOARD_v19_260616_Gerber/MCU_BOARD_v19_260616-job.gbrjob"
original = json.loads(SOURCE.read_text(encoding="utf-8"))
job = json.loads(JOB.read_text(encoding="utf-8"))
if set(original) != {"layerManagement", "physicalStacking"}:
    raise SystemExit("Unexpected UI layer configuration schema")
ordered_ids = [3, 7, 5, 1, 361, 15, 362, 16, 363, 17, 364, 18, 365, 2, 6, 8, 4]
if [row["values"]["Layer Id"] for row in original["physicalStacking"]] != ordered_ids:
    raise SystemExit("Expected the current six-layer Layer Manager order")
if len(job["MaterialStackup"]) != len(ordered_ids):
    raise SystemExit("Gerber stack layer inventory mismatch")
adapted = copy.deepcopy(original)
changes = []
for row, evidence in zip(adapted["physicalStacking"], job["MaterialStackup"]):
    values = row["values"]
    thickness = evidence.get("Thickness", 0)
    before = {"Thickness": values["Thickness"], "Material": values["Material"]}
    values["Thickness"] = thickness
    if evidence["Type"] == "Dielectric":
        if evidence.get("Material") != "FR4":
            raise SystemExit("Unexpected source dielectric material")
        values["Material"] = evidence["Material"]
    changes.append({"layerId": values["Layer Id"], "before": before,
                    "after": {"Thickness": values["Thickness"], "Material": values["Material"]}})
if adapted["layerManagement"] != original["layerManagement"]:
    raise SystemExit("Unrelated layer colors/display/lock configuration changed")
for old, new in zip(original["physicalStacking"], adapted["physicalStacking"]):
    old_copy, new_copy = copy.deepcopy(old), copy.deepcopy(new)
    for value in (old_copy["values"], new_copy["values"]):
        value.pop("Thickness")
        value.pop("Material")
    if old_copy != new_copy:
        raise SystemExit("Unrelated physical layer field changed")
thickness_mm = sum(row["values"]["Thickness"] for row in adapted["physicalStacking"])
if abs(thickness_mm - 1.58) > 1e-12:
    raise SystemExit("Expected 1.58-mm stack")
OUTPUT.write_text(json.dumps(adapted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
report = {"status": "awaiting-ui-import-and-durable-checkpoint-verification", "thickness_mm": thickness_mm,
          "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
          "job_sha256": hashlib.sha256(JOB.read_bytes()).hexdigest(),
          "output_sha256": hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), "changes": changes,
          "layer_management_unchanged": True,
          "permittivity_loss_note": "Gerber job does not specify Dk/Df. Existing UI placeholders remain unchanged; do not use as verified impedance parameters.",
          "global_default_profile_modified": False, "manufacturing_ready": False}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": str(OUTPUT), "thickness_mm": thickness_mm,
                  "output_sha256": report["output_sha256"]}, indent=2))
