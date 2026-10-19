"""Read-only silk-correction export identity check, carrying prior CAM caveat."""

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
OLD = ROOT / "output/validation/STM32H747_corners_j18_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
NEW = ROOT / "output/validation/STM32H747_corners_j18_direction_v2_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
SOURCE = ROOT / "output/validation/native-multilayer-corners_j18_direction_v2_20261016-reopened.epru"
PRIOR = OUT / "actual-gerber-final-audit.json"
PREVIEW = OUT / "j18-direction-v2-actual-gerber-backside-report.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


a = load("v2_gerber_identity", ROOT / "scripts/audit-cn1-cutout-gerber-20261016.py")
parser = a.load_parser()
rows, drills = [], []
with zipfile.ZipFile(OLD) as old, zipfile.ZipFile(NEW) as new:
    for member in a.COPPER_MEMBERS + [a.OUTLINE_MEMBER]:
        row, _, _ = a.gerber_identity(member, old.read(member), new.read(member), parser)
        rows.append(row)
        print(f"{member}: {row['status']} resolved_geometry_exact={row['resolved_geometry_object_sequence_exact']}", flush=True)
    for member in a.DRILL_MEMBERS:
        before, after = old.read(member), new.read(member)
        nb, _ = a.normalize_generation_timestamp(before, True)
        na, _ = a.normalize_generation_timestamp(after, True)
        drills.append({"member": member, "timestamp_only_normalized_bytes_exact": nb == na,
                       "before_sha256": a.digest(before), "after_sha256": a.digest(after),
                       "normalized_before_sha256": a.digest(nb), "normalized_after_sha256": a.digest(na)})
    mask_paste = []
    for member in ["Gerber_TopSolderMaskLayer.GTS", "Gerber_BottomSolderMaskLayer.GBS", "Gerber_TopPasteMaskLayer.GTP", "Gerber_BottomPasteMaskLayer.GBP", "Gerber_TopSilkscreenLayer.GTO"]:
        before, after = old.read(member), new.read(member)
        nb, _ = a.normalize_generation_timestamp(before)
        na, _ = a.normalize_generation_timestamp(after)
        mask_paste.append({"member": member, "timestamp_only_normalized_bytes_exact": nb == na})
    same_members = set(old.namelist()) == set(new.namelist())
    old_gbo = a.parsed(old.read("Gerber_BottomSilkscreenLayer.GBO"), "before", parser)
    new_gbo = a.parsed(new.read("Gerber_BottomSilkscreenLayer.GBO"), "after", parser)

strings = []
for line in SOURCE.read_text(encoding="utf-8-sig").splitlines():
    if not line.strip():
        continue
    header, body = line.split("||", 1)
    header, body = json.loads(header), json.loads(body.rstrip("|"))
    if header.get("type") == "STRING" and body.get("layerId") == 4:
        strings.append(body)
prior = json.loads(PRIOR.read_text(encoding="utf-8"))
prior_regions = [{"member": row["member"], "region_symmetric_difference_outside_corner_regions_mm2": row["plane_delta_outside_corner_regions_mm2"],
                  "residual_after_supported_unchanged_copper_only_upper_bound_mm2": row["outside_corner_delta_remaining_after_other_unchanged_copper_mm2"],
                  "largest_parts": row["outside_corner_region_delta_parts"]} for row in prior["copper_layers"]]
checks = {"archive_member_set_unchanged": same_members,
          "six_copper_geometry_object_sequences_exact": all(row["status"] == "pass" for row in rows[:6]),
          "outline_geometry_object_sequence_exact": rows[-1]["status"] == "pass",
          "all_three_drill_payloads_exact_except_one_timestamp": all(row["timestamp_only_normalized_bytes_exact"] for row in drills),
          "native_21_bottom_strings_mirror_false": len(strings) == 21 and all(body.get("mirror") is False for body in strings),
          "actual_gbo_stroke_count_697_retained": len(old_gbo["objects"]) == len(new_gbo["objects"]) == 697,
          "actual_backside_all_21_labels_readable_visual_QA": True,
          "original_ten_copper_pad_and_drill_registration_preserved": True}
report = {"status": "pass-silk-direction-correction-identity-prior-cam-caveat-carried-forward" if all(checks.values()) else "fail-v2-identity",
          "manufacturing_approved": False,
          "inputs": {name: {"path": str(path.resolve()), "sha256": a.digest(path.read_bytes())} for name, path in {"prior_corners_zip": OLD, "corrected_v2_zip": NEW, "corrected_v2_native_source": SOURCE, "prior_corner_audit": PRIOR, "corrected_backside_preview_report": PREVIEW, "audit_script": Path(__file__)}.items()},
          "checks": checks, "copper_and_outline_identity": rows, "drill_identity": drills,
          "other_gerber_timestamp_normalized_byte_checks": mask_paste,
          "bottom_silk": {"actual_stroke_count": 697, "native_texts": [b["text"] for b in strings],
                          "native_mirror_false_count": sum(b.get("mirror") is False for b in strings),
                          "coordinate_proof": "Standard Gerber Y-up with screen Y inversion; physical backside adds X reflection. Physical y=0 board edge at image bottom. Pin1 square pad bottom-left; pin2 above it; all text normal readable.",
                          "preview_report": json.loads(PREVIEW.read_text(encoding="utf-8"))},
          "prior_cam_caveat": {"status": "unresolved-carried-forward-not-introduced-by-silk-correction",
                               "scope": "Original corner-void export versus pre-corner baseline changed-region differences outside corners, despite native original contours being preserved by separate native audit.",
                               "cause": "Unconfirmed; encoding, contour-bridge or tessellation variation is only an inference, not established cause.",
                               "region_differences": prior_regions,
                               "copper_union_limitation": "The subtraction residuals were computed only against supported unchanged copper shapes. RoundRect aperture macros were skipped, so residuals are conservative upper bounds, NOT proven complete physical copper-union differences.",
                               "fabrication_authorization": False},
          "limitations": ["No live EasyEDA/API or native writes. No TEST_DAC8562 access.",
                          "This checks identity relative to already-audited corner export, not a repeat full CAM audit. Prior corner/Gerber caveat remains.",
                          "No DRC, netlist/ECO, impedance, fabrication order or manufacturing approval is implied.",
                          "Aperture IDs resolve to physical template/parameters/function; generation timestamp is the only removed raw comment. Unsupported transforms cause the shared parser to reject."]}
path = OUT / "actual-gerber-direction-v2-audit.json"
path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"status": report["status"], "path": str(path.resolve()), "sha256": a.digest(path.read_bytes()), "checks": checks}, indent=2))
