"""Read-only v2 checkpoint audit; preserves all historical v1 reports."""
import json
import runpy
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = runpy.run_path(str(HERE / "independent-final-project-scope-audit.py"))
ROOT = BASE["ROOT"]
FINAL = ROOT / "output/checkpoints/STM32H747_adc_dc_corners_j18_direction_v2_20261016.epro2"
PCB_SOURCE = ROOT / "output/validation/native-multilayer-corners_j18_direction_v2_20261016-reopened.epru"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-corners_j18_direction_v2_20261016.json"
REPORT = HERE / "independent-final-project-direction-v2-audit.json"


def main():
    read, bodies, sha = BASE["GEN"]["read_checkpoint"], BASE["bodies"], BASE["sha"]
    before, imported, v1, final = map(read, (BASE["BEFORE"], BASE["LIBRARY"], BASE["FINAL"], FINAL))
    errors = []
    added = set(final) - set(before)
    if set(before) - set(final) or added != set(imported) - set(before) or len(added) != 19:
        errors.append("Unexpected final project document set")
    changed_existing = [k for k in before.keys() & final.keys() if bodies(before[k]) != bodies(final[k])]
    if set(changed_existing) != {BASE["ADC"], BASE["PCB"]}:
        errors.append({"unexpectedChangedExistingDocuments": changed_existing})
    new_changed = [k for k in added if bodies(imported[k]) != bodies(final[k])]
    if new_changed:
        errors.append({"importedLibraryChanged": new_changed})

    historical = json.loads((HERE / "independent-final-project-scope-audit.json").read_text(encoding="utf8"))
    if not historical["passed"] or historical["checkpoints"]["final"]["sha256"] != sha(BASE["FINAL"]):
        errors.append("Historical v1 proof is missing, failed, or not bound to the compared checkpoint")
    if set(v1) != set(final):
        errors.append("v1/v2 document sets differ")
    changed_v1 = [k for k in v1.keys() & final.keys() if bodies(v1[k]) != bodies(final[k])]
    if changed_v1 != [BASE["PCB"]]:
        errors.append({"v1ToV2ChangedDocuments": changed_v1})
    v1_pcb, final_pcb = bodies(v1[BASE["PCB"]]), bodies(final[BASE["PCB"]])
    if v1_pcb.keys() != final_pcb.keys():
        errors.append("v1/v2 PCB record sets differ")
    old_corner = json.loads((ROOT / "output/candidates/corner-holes-inward/final-native-corners-j18-audit-20261016.json").read_text(encoding="utf8"))
    expected_strings = {("STRING", s["id"]) for s in old_corner["strings"]}
    changed_records = {k for k in v1_pcb.keys() & final_pcb.keys() if v1_pcb[k] != final_pcb[k]}
    mirror_changes = []
    if changed_records != expected_strings or len(changed_records) != 21:
        errors.append({"unexpectedChangedPCBRecords": sorted(changed_records)})
    for key in sorted(changed_records):
        a, b = v1_pcb[key], final_pcb[key]
        fields = {f for f in a.keys() | b.keys() if a.get(f) != b.get(f)}
        if fields != {"mirror"} or a.get("mirror") is not True or b.get("mirror") is not False or b.get("layerId") != 4:
            errors.append({"unexpectedStringChange": key, "fields": sorted(fields), "final": b})
        mirror_changes.append({"record": key, "fields": sorted(fields), "before": a.get("mirror"), "after": b.get("mirror"), "layerId": b.get("layerId")})

    adc = BASE["source_matches_snapshot"](BASE["ADC_SOURCE"], final[BASE["ADC"]])
    pcb = BASE["source_matches_snapshot"](PCB_SOURCE, final[BASE["PCB"]])
    if not adc["passed"] or not pcb["passed"]:
        errors.append({"nativeSourceMismatch": {"adc": adc["errors"], "pcb": pcb["errors"]}})
    drc = json.loads(DRC.read_text(encoding="utf8"))
    if drc.get("violations") != 1 or drc.get("counts") != {"Netlist Error": 1}:
        errors.append("Unexpected latest native DRC result")
    with zipfile.ZipFile(BASE["FINAL"]) as a, zipfile.ZipFile(FINAL) as b:
        meta_equal = json.loads(a.read("project2.json")) == json.loads(b.read("project2.json"))
        changed_images = [n for n in sorted(set(a.namelist()) & set(b.namelist())) if n.startswith("IMAGE/") and not n.endswith("/") and a.read(n) != b.read(n)]
    if not meta_equal:
        errors.append("v1/v2 project metadata differs")

    report = {
        "passed": not errors,
        "schema": "final-project-scope-preservation-20261016-direction-v2",
        "finalCheckpoint": {"path": str(FINAL), "sha256": sha(FINAL), "bytes": FINAL.stat().st_size},
        "priorCheckpoint": {"path": str(BASE["FINAL"]), "sha256": sha(BASE["FINAL"])},
        "historicalV1Audit": {"path": str(HERE / "independent-final-project-scope-audit.json"), "sha256": sha(HERE / "independent-final-project-scope-audit.json"), "passed": historical["passed"]},
        "documentCounts": {"beforeADC": len(before), "afterLibraryImport": len(imported), "v1": len(v1), "v2": len(final)},
        "changedExistingDocumentsFromBeforeADC": changed_existing,
        "other3903ExistingDocumentBodiesExactExcludingSessionDochead": len(before) - len(changed_existing),
        "new19LibrariesExactAfterImport": not new_changed,
        "newLibraryCounts": dict(Counter(k[0] for k in added)),
        "allExistingLibraryBodiesUnchanged": all(bodies(before[k]) == bodies(final[k]) for k in before if k[0] in {"DEVICE", "SYMBOL", "FOOTPRINT"}),
        "schematicPageCount": len([k for k in final if k[0] == "SCH_PAGE"]),
        "allFiveSchematicPagesUnchangedFromV1": all(bodies(v1[k]) == bodies(final[k]) for k in v1 if k[0] == "SCH_PAGE"),
        "adcSnapshotMatchesIndependentlyVerifiedFinalSource": adc,
        "pcbSnapshotMatchesLatestReopenedSource": pcb,
        "v1ToV2": {"changedDocumentBodiesExactly": changed_v1, "changedPcbRecordsExactly": mirror_changes, "only21TrueToFalseMirrorFlags": len(mirror_changes) == 21 and not errors, "allOtherNativeDocumentBodiesExact": True},
        "pcbBoundedEditsFromBeforeADC": {**historical["pcbBoundedEdits"], "addedBottomSilkStringsNativeMirror": False},
        "bottomAutoReflectionEvidence": {"path": str(HERE / "installed-pcb-bottom-text-mirror-audit.json"), "effectiveReflection": "isBottomLayer XOR text.mirror", "defaultGerberLayerIsMirror": False},
        "projectMetadataExactV1ToV2": meta_equal,
        "changedPreviewImagesV1ToV2": changed_images,
        "nativeDrc": {"path": str(DRC), "sha256": sha(DRC), "passed": drc["passed"], "violations": drc["violations"], "counts": drc["counts"]},
        "adcPcbEcoApplied": False,
        "manufacturingReady": False,
        "errors": errors,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": report["passed"], "report": str(REPORT), "finalSha256": sha(FINAL), "only21MirrorFlagsChanged": not errors, "adcSourceMatch": adc["passed"], "pcbSourceMatch": pcb["passed"], "errors": errors}, indent=2))
    if errors:
        raise ValueError("Direction v2 scope audit failed")


if __name__ == "__main__":
    main()
