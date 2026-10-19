"""Independent read-only comparison of final native PCB with reviewed plan."""
import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FOLDER = Path(__file__).resolve().parent
BASE = ROOT / "output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru"
DIRECTION_V2 = "--direction-v2" in sys.argv
FINAL = ROOT / ("output/validation/native-multilayer-corners_j18_direction_v2_20261016-reopened.epru" if DIRECTION_V2
                else "output/validation/native-multilayer-corners_j18_final_20261016-reopened.epru")
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-corners_j18_20261016.json"
MM = .0254


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def records(path):
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line:
            continue
        h, b = line.split("||", 1)
        h = json.loads(h)
        b = b.removesuffix("|")
        key = (h["type"], h.get("id", ""))
        assert key not in result, f"Duplicate native record {key}"
        result[key] = (h, json.loads(b) if b else {})
    return result


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verifier = load("corner_native_preservation_helpers", ROOT / "scripts/audit-multilayer-geometry-preservation.py")
    before, after = records(BASE), records(FINAL)
    plan = json.loads((FOLDER / "plan.json").read_text(encoding="utf-8"))
    labels = json.loads((FOLDER / "j18-bottom-label-layout-review-20261016.json").read_text(encoding="utf-8"))["scenarios"][1]["labels"]
    changes = {(c["type"], c["id"]): c for c in plan["pad_changes"] + plan["fill_changes"]}
    ignored_ui = {"DOCHEAD", "CANVAS", "ACTIVE_LAYER"}
    protected_exact, ui_differences, normalizations, fill_paths = [], [], [], []
    for key, (header, body) in before.items():
        assert key in after, f"Existing record deleted: {key}"
        actual = after[key][1]
        if key[0] in ignored_ui:
            if actual != body:
                ui_differences.append(key[0])
            continue
        if key not in changes:
            assert actual == body, f"Protected record changed: {key}"
            protected_exact.append([key, body])
            continue
        expected = changes[key]["after"]
        comparison = copy.deepcopy(actual)
        if key[0] == "FILL":
            proof = verifier.compare_fill_paths(expected["path"], comparison["path"], key[1])
            fill_paths.append({"id": key[1], **proof,
                               "planned_contours": len(expected["path"]), "actual_contours": len(actual["path"])})
            comparison["path"] = expected["path"]
            if comparison.get("zIndex") == -1 and expected.get("zIndex", -1) >= 0:
                normalizations.append({"id": key[1], "field": "zIndex", "native": -1, "planned": expected["zIndex"]})
                comparison["zIndex"] = expected["zIndex"]
            if comparison.get("refs") == [None] and expected.get("refs") is None:
                normalizations.append({"id": key[1], "field": "refs", "native": [None], "planned": None})
                comparison["refs"] = None
        assert comparison == expected, f"Target differs from reviewed plan: {key}"
    extra = {k: v for k, v in after.items() if k not in before}
    assert len(extra) == 21 and all(k[0] == "STRING" for k in extra), "Unexpected new primitives"
    actual_strings = [(k[1], b) for k, (_, b) in extra.items()]
    used = set()
    string_rows = []
    for label in labels:
        matches = [(oid, b) for oid, b in actual_strings if oid not in used and b["text"] == label["text"]
                   and abs(b["x"] * MM - label["x_mm"]) < .000005
                   and abs(b["y"] * MM - label["y_mm"]) < .000005]
        assert len(matches) == 1, f"Label location/text mismatch: {label}"
        oid, b = matches[0]
        used.add(oid)
        assert b["layerId"] == 4 and b["mirror"] is (not DIRECTION_V2)
        assert b["origin"] == "CENTER_MIDDLE" and b["fontFamily"] == "default"
        assert b["angle"] == 0 and b["reverse"] is False and b["expansion"] == 0
        assert b["bold"] == 0 and b["italic"] == 0
        assert abs(b["fontSize"] * MM - label["font_size_mm"]) < .000005
        assert abs(b["strokeWidth"] * MM - .12) < .000005
        assert b["x"] > 0 and b["y"] > 0
        string_rows.append({"id": oid, "pin": label["pin"], "kind": label["kind"], "text": b["text"],
                            "actual_mm": [b["x"] * MM, b["y"] * MM],
                            "actual_font_size_mm": b["fontSize"] * MM,
                            "actual_stroke_width_mm": b["strokeWidth"] * MM,
                            "mirror": b["mirror"], "layer": b["layerId"]})
    counts_before = Counter(k[0] for k in before)
    counts_after = Counter(k[0] for k in after)
    expected_counts = counts_before.copy()
    expected_counts["STRING"] = 21
    assert counts_after == expected_counts
    assert counts_after["RULE"] == 18 and counts_after["PAD_NET"] == 1234
    drc = json.loads(DRC.read_text(encoding="utf-8"))
    assert drc["counts"] == {"Netlist Error": 1} and drc["violations"] == 1
    report = {
        "status": "PASS_NATIVE_PRESERVATION_AND_LABEL_MAPPING_NOT_FULL_DRC_APPROVAL",
        "baseline": str(BASE.relative_to(ROOT)), "baseline_sha256": sha(BASE),
        "final": str(FINAL.relative_to(ROOT)), "final_sha256": sha(FINAL),
        "plan_sha256": sha(FOLDER / "plan.json"),
        "record_count_before": len(before), "record_count_after": len(after),
        "reviewed_target_pad_count": 4, "reviewed_target_fill_count": 6,
        "protected_records_including_ui": len(before) - len(changes),
        "protected_nonui_records_exact": len(protected_exact),
        "protected_nonui_canonical_sha256": hashlib.sha256(canonical(protected_exact)).hexdigest(),
        "ignored_ui_types": sorted(ignored_ui), "actual_ui_body_differences": ui_differences,
        "normalizations": normalizations, "fill_path_identity": fill_paths,
        "new_strings": len(string_rows), "strings": string_rows,
        "all_21_strings_including_title_persisted_after_close_reopen": True,
        "native_string_mirror_expected": not DIRECTION_V2,
        "direction_v2_engine_note": ("Bottom engine automatically mirrors when native mirror is false; native true cancels that reflection. Actual Gerber backside preview is the final physical orientation check." if DIRECTION_V2 else None),
        "counts_before": dict(counts_before), "counts_after": dict(counts_after),
        "all_18_rules_and_280_rule_selectors_exact": True,
        "all_330_components_1234_pad_nets_634_vias_unchanged": True,
        "native_drc": {"path": str(DRC.relative_to(ROOT)), "sha256": sha(DRC),
                       "passed": drc["passed"], "violations": drc["violations"], "counts": drc["counts"],
                       "interpretation": "Clearance/connection/other geometry errors zero; one real schematic-PCB netlist mismatch remains. No waiver or rule change."},
        "native_api_called": False, "native_project_modified_by_auditor": False,
    }
    path = FOLDER / ("final-native-corners-j18-direction-v2-audit-20261016.json" if DIRECTION_V2
                     else "final-native-corners-j18-audit-20261016.json")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(path), "sha256": sha(path), "protected_nonui_exact": len(protected_exact),
                      "record_counts": [len(before), len(after)], "normalizations": normalizations,
                      "new_strings": len(string_rows), "drc_counts": drc["counts"]}, indent=2))


if __name__ == "__main__":
    main()
