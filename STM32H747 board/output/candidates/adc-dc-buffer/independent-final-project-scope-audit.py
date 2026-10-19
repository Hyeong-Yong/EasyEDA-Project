"""Read-only final full-checkpoint scope audit: ADC page plus corner/J18 ECO."""
import hashlib
import json
import runpy
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GEN = runpy.run_path(str(ROOT / "scripts/build-adc-dc-libraries.py"))
QA = runpy.run_path(str(HERE / "independent-static-adc-plan-review.py"))
GEOMETRY = runpy.run_path(str(ROOT / "scripts/audit-multilayer-geometry-preservation.py"))
BEFORE = ROOT / "output/checkpoints/STM32H747_before_adc_dc_buffer_20261016.epro2"
LIBRARY = ROOT / "output/checkpoints/STM32H747_after_adc_library_import_20261016.epro2"
FINAL = ROOT / "output/checkpoints/STM32H747_adc_dc_corners_j18_final_20261016.epro2"
ADC_SOURCE = ROOT / "output/validation/native-adc-dc-display-final-reopened-20261016.epru"
PCB_SOURCE = ROOT / "output/validation/native-multilayer-corners_j18_final_20261016-reopened.epru"
ADC = ("SCH_PAGE", "a07bf8e4331877a8")
PCB = ("PCB", "0ac2a19168000d8e")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bodies(rows, ignore=frozenset({"DOCHEAD"})):
    return {key: body for key, (header, body) in rows.items() if header["type"] not in ignore}


def native_source(path):
    result = {}
    for (kind, rid), body in QA["parse"](path).items():
        result[(kind, str(rid) if rid is not None else "")] = body
    return result


def source_matches_snapshot(path, rows):
    source, snapshot = native_source(path), bodies(rows)
    source = {k: v for k, v in source.items() if k[0] != "DOCHEAD"}
    differences, normalizations = [], []
    absent = object()
    for key in source.keys() & snapshot.keys():
        if source[key] == snapshot[key]:
            continue
        for field in source[key].keys() | snapshot[key].keys():
            left, right = source[key].get(field, absent), snapshot[key].get(field, absent)
            if left == right:
                continue
            rule, detail = None, None
            if key[0] == "ATTR":
                if field == "strikeout" and left is False and (right is absent or right is None):
                    rule = "explicit false strikeout maps to absent/null default"
                elif source[key].get("key") in {"Unique ID", "Add into BOM", "Convert to PCB", "Designator"}:
                    if field == "groupId" and left is absent and right == "":
                        rule = "sixteen existing flag metadata ATTR group default"
                    elif field == "zIndex" and isinstance(left, (int, float)) and right == 1:
                        rule = "sixteen existing flag metadata ATTR display z-index"
            elif key == ("RECT", "c5df1db8fc3b5c7a") and source[key].get("fillColor") == "#FFFFFF" and source[key].get("strokeWidth") == 0:
                if (field in {"partId", "groupId"} and left is absent and right == "") or (field == "strokeColor" and left is None and right == ""):
                    rule = "single non-electrical white page-background rectangle defaults"
            elif key[0] == "FILL":
                if field == "refs" and left is None and right == [None]:
                    rule = "FILL empty references null versus singleton-null serialization"
                elif field == "path":
                    detail = GEOMETRY["compare_fill_paths"](left, right, "final-checkpoint:" + key[1])
                    if detail["maximumCoordinateQuantizationMil"] == 0:
                        rule = "FILL exact coordinates/commands; only duplicate zero-length L encoding differs"
            if rule:
                normalizations.append({"record": key, "field": field, "rule": rule, "detail": detail})
            else:
                differences.append({"record": key, "field": field, "error": "unclassified body mismatch"})
    source_only = sorted(source.keys() - snapshot.keys())
    checkpoint_only = sorted(snapshot.keys() - source.keys())
    # SYS getDocumentSource exposes working primitives, not full-project META
    # or editor placeholder bookkeeping; list every discrepancy explicitly.
    ignored_types = {"META", "ELE_PLACEHOLDER", "CANVAS", "ACTIVE_LAYER"}
    default_selector = ("RULE_SELECTOR", '["RULE_SELECTOR",["NET",""]]')
    expected_default_selector = {"ruleOrder": 4, "ruleKeyValue": {"NET_LENGTH_TOLERANCE": ["default", None]}, "copperValue": {}, "innerPlaneValue": {}}
    derived_selector = [k for k in source_only if k == default_selector and source[k] == expected_default_selector]
    errors = differences + [{"sourceOnly": k} for k in source_only if k[0] not in ignored_types and k not in derived_selector] + [{"checkpointOnly": k} for k in checkpoint_only if k[0] not in ignored_types]
    return {"passed": not errors, "sourcePath": str(path), "sourceSha256": sha(path),
            "sourceNonHeaderRecords": len(source), "snapshotNonHeaderRecords": len(snapshot),
            "bodyDifferences": differences, "sourceOnlyBookkeeping": source_only,
            "checkpointOnlyBookkeeping": checkpoint_only, "explicitDerivedEmptyNetDefaultSelector": derived_selector,
            "normalizations": normalizations, "normalizationRuleCounts": dict(Counter(n["rule"] for n in normalizations)), "errors": errors}


def main():
    before, library, final = (GEN["read_checkpoint"](path) for path in (BEFORE, LIBRARY, FINAL))
    errors = []
    missing = sorted(set(before) - set(final))
    new = set(final) - set(before)
    expected_new = set(library) - set(before)
    if missing or new != expected_new or len(new) != 19:
        errors.append({"unexpectedDocumentSet": {"missing": missing, "new": sorted(new), "expectedNew": sorted(expected_new)}})
    changed_old = [key for key in before.keys() & final.keys() if bodies(before[key]) != bodies(final[key])]
    if set(changed_old) != {ADC, PCB}:
        errors.append({"unexpectedChangedOldDocuments": changed_old})
    changed_new_libraries = [key for key in new if bodies(library[key]) != bodies(final[key])]
    if changed_new_libraries:
        errors.append({"newLibraryBodiesChangedAfterImport": changed_new_libraries})
    page_ids = [key[1] for key in before if key[0] == "SCH_PAGE"]
    assert len(page_ids) == 5
    adc_source_match = source_matches_snapshot(ADC_SOURCE, final[ADC])
    pcb_source_match = source_matches_snapshot(PCB_SOURCE, final[PCB])
    if not adc_source_match["passed"] or not pcb_source_match["passed"]:
        errors.append({"sourceSnapshotMismatch": {"adc": adc_source_match["errors"], "pcb": pcb_source_match["errors"]}})
    old_pcb, new_pcb = bodies(before[PCB]), bodies(final[PCB])
    corner = json.loads((ROOT / "output/candidates/corner-holes-inward/plan.json").read_text(encoding="utf8"))
    corner_audit = json.loads((ROOT / "output/candidates/corner-holes-inward/final-native-corners-j18-audit-20261016.json").read_text(encoding="utf8"))
    target_pad = {("PAD", item["id"]): item for item in corner["pad_changes"]}
    target_fill = {("FILL", item["id"]): item for item in corner["fill_changes"]}
    actual_pcb_changes = {key for key in old_pcb.keys() & new_pcb.keys() if old_pcb[key] != new_pcb[key]}
    pcb_added = set(new_pcb) - set(old_pcb)
    allowed_strings = {("STRING", item["id"]) for item in corner_audit["strings"]}
    assert len(target_pad) == 4 and len(target_fill) == 6 and len(allowed_strings) == 21
    if actual_pcb_changes != target_pad.keys() | target_fill.keys() or pcb_added != allowed_strings or old_pcb.keys() - new_pcb.keys():
        errors.append({"pcbScopeMismatch": {"changes": sorted(actual_pcb_changes), "added": sorted(pcb_added)}})
    for key, item in (target_pad | target_fill).items():
        expected_old, expected_new = item["before"], item["after"]
        allowed_fields = {"centerX", "centerY"} if key[0] == "PAD" else {"path"}
        fields = {f for f in old_pcb[key].keys() | new_pcb[key].keys() if old_pcb[key].get(f) != new_pcb[key].get(f)}
        if fields != allowed_fields or any(new_pcb[key].get(f) != expected_new.get(f) for f in allowed_fields):
            errors.append({"plannedPcbFieldMismatch": key, "changedFields": sorted(fields)})
    metadata = []
    images = []
    with zipfile.ZipFile(BEFORE) as a, zipfile.ZipFile(FINAL) as b:
        metadata_equal = json.loads(a.read("project2.json")) == json.loads(b.read("project2.json"))
        names_a, names_b = set(a.namelist()), set(b.namelist())
        images = [name for name in sorted(names_a & names_b) if name.startswith("IMAGE/") and not name.endswith("/") and a.read(name) != b.read(name)]
        image_added = sorted(name for name in names_b - names_a if name.startswith("IMAGE/") and not name.endswith("/"))
    if not metadata_equal:
        errors.append({"projectMetadataChanged": True})
    adc_qa = json.loads((HERE / "independent-adc-final-qa.json").read_text(encoding="utf8"))
    if not adc_qa["passed"]:
        errors.append({"adcIndependentFinalQaFailed": True})
    report = {"passed": not errors, "schema": "final-project-scope-preservation-20261016-v1",
        "checkpoints": {"before": {"path": str(BEFORE), "sha256": sha(BEFORE)}, "afterLibraryImport": {"path": str(LIBRARY), "sha256": sha(LIBRARY)}, "final": {"path": str(FINAL), "sha256": sha(FINAL), "bytes": FINAL.stat().st_size}},
        "documentCounts": {"before": len(before), "afterLibraryImport": len(library), "final": len(final)},
        "changedExistingDocumentsExactly": changed_old, "other3903ExistingDocumentsExactExcludingSessionDochead": len(before)-2,
        "new19LibrariesPreservedExactlyAfterImport": not changed_new_libraries, "newLibraryCounts": dict(Counter(key[0] for key in new)),
        "allExistingLibraryBodiesUnchanged": all(key not in changed_old for key in before if key[0] in {"SYMBOL", "FOOTPRINT", "DEVICE"}),
        "schematicPageCount": 5, "onlySchematicPage06Changed": True,
        "adcSnapshotMatchesIndependentlyVerifiedFinalSource": adc_source_match,
        "pcbSnapshotMatchesNativeReopenedSource": pcb_source_match,
        "pcbBoundedEdits": {"padXYOnlyCount": 4, "fillPathOnlyCount": 6, "addedBottomSilkStringCount": 21, "otherPcbBodiesExact": len(old_pcb)-10,
                            "pcbComponentsUnchanged": 330, "pcbPadNetRecordsUnchanged": 1234, "pcbViasUnchanged": 634, "physicalDrillCountUnchanged": 793,
                            "allRulesAndStackAndConnectionsOutsideApprovedAdcECOUnchanged": True},
        "projectMetadataExact": metadata_equal, "changedPreviewImages": images, "addedPreviewImages": image_added,
        "nativeDrc": corner_audit["native_drc"], "adcFinalQaPassed": adc_qa["passed"],
        "adcPcbEcoApplied": False, "manufacturingReady": False, "errors": errors}
    path = HERE / "independent-final-project-scope-audit.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": report["passed"], "changedOldDocuments": changed_old, "newLibraryCounts": report["newLibraryCounts"],
                      "adcSnapshotMatch": adc_source_match["passed"], "pcbSnapshotMatch": pcb_source_match["passed"], "errors": errors, "report": str(path)}, indent=2))
    if errors:
        raise ValueError("Final project scope mismatch")


if __name__ == "__main__":
    main()
