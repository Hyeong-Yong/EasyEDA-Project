#!/usr/bin/env python3
"""Audit the user-approved CN1 internal cutout enlargement.

This verifier is static and read-only.  It compares a supplied final EasyEDA
checkpoint, reopened PCB source, and native DRC artifact with the frozen
post-copper-clearance baseline.  The only allowed design-body edits are the
paths of the four existing CN1 Board Outline POLY records.  They must remain a
closed clockwise square about the original centre and measure 1.92 x 1.92 mm
within 5 nm.

Passing this audit is not fabrication, enclosure-fit, SI/PI, or assembly
approval.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
TARGET_UUID = "0ac2a19168000d8e"
BASELINE_CHECKPOINT = (
    ROOT / "output/checkpoints/STM32H747_multilayer_copper_clearances_20261015.epro2"
)
BASELINE_PCB_SOURCE = (
    ROOT / "output/validation/native-multilayer-copper_clearances-reopened.epru"
)
BASELINE_DRC = (
    ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-copper_clearances.json"
)
MULTILAYER_AUDITOR = ROOT / "scripts/audit-multilayer-geometry-preservation.py"
DEFAULT_REPORT = ROOT / "output/validation/native-cn1-cutout-final-preservation-audit.json"

MM_PER_MIL = 0.0254
GEOMETRY_TOLERANCE_MM = 0.000005
EXPECTED_OLD_SIZE_MM = 1.8
EXPECTED_NEW_SIZE_MM = 1.92
EXPECTED_DRILL_COUNT = 793

TOP_ID = "f614cce4900c7115"
LEFT_ID = "6e8dd66b3e3db1b0"
RIGHT_ID = "e94386c2e1a58187"
BOTTOM_ID = "5b55024cb3a23233"
CUTOUT_IDS = {TOP_ID, LEFT_ID, RIGHT_ID, BOTTOM_ID}
EXPECTED_NATIVE_ZINDEX_NORMALIZATION = {
    TOP_ID: (8965, -1),
    LEFT_ID: (8966, -1),
    RIGHT_ID: (8967, -1),
    BOTTOM_ID: (8968, -1),
}

# These records describe editor/session state or native checkpoint bookkeeping,
# not board geometry/electrical data.  They are inventoried in the report but
# excluded from the exact non-UI body comparison.
UI_RECORD_TYPES = {"DOCHEAD", "CANVAS", "ACTIVE_LAYER", "META", "ELE_PLACEHOLDER"}


class AuditError(RuntimeError):
    pass


def load_multilayer_auditor() -> Any:
    spec = importlib.util.spec_from_file_location(
        "stm32h747_multilayer_preservation_helper", MULTILAYER_AUDITOR
    )
    if spec is None or spec.loader is None:
        raise AuditError("cannot load the static multilayer preservation helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label}: non-numeric value {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label}: non-finite value {value!r}")
    return result


def within(value: float, expected: float, tolerance: float = GEOMETRY_TOLERANCE_MM) -> bool:
    return abs(value - expected) <= tolerance


def keyed_non_ui(rows: Sequence[Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], Counter[str]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    ui_counts: Counter[str] = Counter()
    for record in rows:
        if record.kind in UI_RECORD_TYPES:
            ui_counts[record.kind] += 1
            continue
        key = (record.kind, record.record_id)
        if record.record_id == "None" or key in result:
            raise AuditError(f"invalid or duplicate non-UI record identity {key!r}")
        result[key] = record.body
    return result, ui_counts


def parse_line_path(body: dict[str, Any], object_id: str) -> tuple[tuple[float, float], tuple[float, float]]:
    path = body.get("path")
    if (
        not isinstance(path, list)
        or len(path) != 5
        or path[2] != "L"
        or isinstance(path[0], str)
        or isinstance(path[1], str)
        or isinstance(path[3], str)
        or isinstance(path[4], str)
    ):
        raise AuditError(f"CN1 POLY {object_id}: expected one explicit open L segment")
    return (
        (finite(path[0], f"{object_id}.path[0]"), finite(path[1], f"{object_id}.path[1]")),
        (finite(path[3], f"{object_id}.path[3]"), finite(path[4], f"{object_id}.path[4]")),
    )


def square_geometry(poly_bodies: dict[str, dict[str, Any]], label: str) -> dict[str, Any]:
    if set(poly_bodies) != CUTOUT_IDS:
        raise AuditError(f"{label}: incomplete CN1 cutout identity set")
    segments = {object_id: parse_line_path(body, object_id) for object_id, body in poly_bodies.items()}
    top_start, top_end = segments[TOP_ID]
    left_start, left_end = segments[LEFT_ID]
    right_start, right_end = segments[RIGHT_ID]
    bottom_start, bottom_end = segments[BOTTOM_ID]

    # Preserve the original directed closure: top east, right south, bottom
    # west, left north.  Exact shared tuples prove there are no open corners.
    if not (
        top_start == left_end
        and top_end == right_start
        and right_end == bottom_start
        and bottom_end == left_start
    ):
        raise AuditError(f"{label}: four CN1 POLY segments do not close exactly")
    if not (
        top_start[1] == top_end[1]
        and bottom_start[1] == bottom_end[1]
        and left_start[0] == left_end[0]
        and right_start[0] == right_end[0]
    ):
        raise AuditError(f"{label}: CN1 cutout edges are not axis-aligned")
    if not (
        top_start[0] < top_end[0]
        and right_start[1] > right_end[1]
        and bottom_start[0] > bottom_end[0]
        and left_start[1] < left_end[1]
    ):
        raise AuditError(f"{label}: CN1 cutout edge directions changed")

    vertices = [top_start, top_end, right_end, bottom_end]
    twice_area = sum(
        vertices[index][0] * vertices[(index + 1) % 4][1]
        - vertices[(index + 1) % 4][0] * vertices[index][1]
        for index in range(4)
    )
    if twice_area >= 0:
        raise AuditError(f"{label}: CN1 cutout winding is not the original clockwise winding")

    min_x = left_start[0]
    max_x = right_start[0]
    min_y = bottom_start[1]
    max_y = top_start[1]
    width_mm = (max_x - min_x) * MM_PER_MIL
    height_mm = (max_y - min_y) * MM_PER_MIL
    center_mm = [
        (min_x + max_x) * 0.5 * MM_PER_MIL,
        (min_y + max_y) * 0.5 * MM_PER_MIL,
    ]
    return {
        "ids": [TOP_ID, RIGHT_ID, BOTTOM_ID, LEFT_ID],
        "boundsMil": [min_x, min_y, max_x, max_y],
        "centerMm": center_mm,
        "widthMm": width_mm,
        "heightMm": height_mm,
        "clockwise": True,
        "closedExactly": True,
        "axisAligned": True,
        "directedSegments": {
            object_id: [list(start), list(end)] for object_id, (start, end) in segments.items()
        },
    }


def compare_cutout(
    baseline_rows: Sequence[Any], final_rows: Sequence[Any], representation: str
) -> dict[str, Any]:
    baseline_poly = {
        record.record_id: record.body
        for record in baseline_rows
        if record.kind == "POLY" and record.record_id in CUTOUT_IDS
    }
    final_poly = {
        record.record_id: record.body
        for record in final_rows
        if record.kind == "POLY" and record.record_id in CUTOUT_IDS
    }
    before = square_geometry(baseline_poly, f"{representation}:baseline")
    after = square_geometry(final_poly, f"{representation}:final")
    if not within(before["widthMm"], EXPECTED_OLD_SIZE_MM) or not within(
        before["heightMm"], EXPECTED_OLD_SIZE_MM
    ):
        raise AuditError(f"{representation}: frozen CN1 cutout is not 1.80 x 1.80 mm")
    if not within(after["widthMm"], EXPECTED_NEW_SIZE_MM) or not within(
        after["heightMm"], EXPECTED_NEW_SIZE_MM
    ):
        raise AuditError(f"{representation}: final CN1 cutout is not 1.92 x 1.92 mm")
    center_delta_mm = [
        after["centerMm"][index] - before["centerMm"][index] for index in range(2)
    ]
    if any(abs(value) > GEOMETRY_TOLERANCE_MM for value in center_delta_mm):
        raise AuditError(f"{representation}: CN1 cutout centre moved")

    for object_id in CUTOUT_IDS:
        baseline_body = dict(baseline_poly[object_id])
        final_body = dict(final_poly[object_id])
        baseline_path = baseline_body.pop("path", None)
        final_path = final_body.pop("path", None)
        baseline_zindex = baseline_body.pop("zIndex", None)
        final_zindex = final_body.pop("zIndex", None)
        expected_zindex = EXPECTED_NATIVE_ZINDEX_NORMALIZATION[object_id]
        if (baseline_zindex, final_zindex) != expected_zindex:
            raise AuditError(
                f"{representation}: CN1 POLY {object_id} zIndex normalization differs; "
                f"got {(baseline_zindex, final_zindex)!r}, expected {expected_zindex!r}"
            )
        if baseline_body != final_body:
            raise AuditError(f"{representation}: CN1 POLY {object_id} changed outside path")
        if baseline_path == final_path:
            raise AuditError(f"{representation}: CN1 POLY {object_id} path did not change")

    return {
        "representation": representation,
        "toleranceMm": GEOMETRY_TOLERANCE_MM,
        "before": before,
        "after": after,
        "centerDeltaMm": center_delta_mm,
        "onlyApprovedGeometryFieldChanged": "path",
        "sameIdsLayerWidthNetStyleAndLock": True,
        "nativeZIndexNormalization": {
            object_id: {"before": before_z, "after": after_z}
            for object_id, (before_z, after_z) in sorted(
                EXPECTED_NATIVE_ZINDEX_NORMALIZATION.items()
            )
        },
    }


def compare_pcb_non_ui_bodies(
    baseline_rows: Sequence[Any], final_rows: Sequence[Any], representation: str
) -> dict[str, Any]:
    before, before_ui = keyed_non_ui(baseline_rows)
    after, after_ui = keyed_non_ui(final_rows)
    if set(before) != set(after):
        removed = sorted(set(before) - set(after))[:8]
        added = sorted(set(after) - set(before))[:8]
        raise AuditError(
            f"{representation}: non-UI identity inventory changed; removed={removed}, added={added}"
        )
    changed: list[tuple[str, str]] = []
    for key in sorted(before):
        if before[key] == after[key]:
            continue
        if key[0] == "POLY" and key[1] in CUTOUT_IDS:
            before_body = dict(before[key])
            after_body = dict(after[key])
            before_body.pop("path", None)
            after_body.pop("path", None)
            before_zindex = before_body.pop("zIndex", None)
            after_zindex = after_body.pop("zIndex", None)
            if (before_zindex, after_zindex) != EXPECTED_NATIVE_ZINDEX_NORMALIZATION[key[1]]:
                raise AuditError(f"{representation}: unexpected CN1 POLY zIndex change {key}")
            if before_body == after_body and before[key].get("path") != after[key].get("path"):
                changed.append(key)
                continue
        raise AuditError(f"{representation}: unauthorized non-UI body change {key}")
    expected = {("POLY", object_id) for object_id in CUTOUT_IDS}
    if set(changed) != expected:
        raise AuditError(f"{representation}: changed body set is not exactly the four CN1 POLYs")
    type_counts = Counter(key[0] for key in after)
    return {
        "nonUiRecordCount": len(after),
        "nonUiTypeCounts": dict(sorted(type_counts.items())),
        "identitySetExact": True,
        "changedBodies": [list(key) for key in sorted(changed)],
        "onlyFourApprovedPolyPathsChanged": True,
        "onlyAdditionalBodyNormalization": "the same four POLY zIndex values, 8965..8968 to -1",
        "uiRecordCountsBefore": dict(sorted(before_ui.items())),
        "uiRecordCountsAfter": dict(sorted(after_ui.items())),
        "uiRecordTypesExcludedFromBodyGate": sorted(UI_RECORD_TYPES),
    }


def compare_project_documents(
    helper: Any,
    baseline_checkpoint: Path,
    final_checkpoint: Path,
) -> tuple[dict[str, Any], list[Any], list[Any]]:
    baseline_docs, baseline_capture, baseline_project, baseline_images = helper.scan_checkpoint(
        baseline_checkpoint, {TARGET_UUID}
    )
    final_docs, final_capture, final_project, final_images = helper.scan_checkpoint(
        final_checkpoint, {TARGET_UUID}
    )
    if baseline_project != final_project:
        raise AuditError("project2.json changed")
    if set(baseline_docs) != set(final_docs):
        raise AuditError("project document UUID inventory changed")
    changed_documents = []
    for uuid in sorted(baseline_docs):
        if baseline_docs[uuid] == final_docs[uuid]:
            continue
        if uuid == TARGET_UUID:
            changed_documents.append(uuid)
            continue
        raise AuditError(f"non-PCB project document changed: {uuid}")
    if changed_documents != [TARGET_UUID]:
        raise AuditError("target PCB is not the sole changed project document")

    if set(baseline_images) != set(final_images):
        raise AuditError("project IMAGE inventory changed")
    changed_images = [
        name for name in sorted(baseline_images) if baseline_images[name] != final_images[name]
    ]
    unexpected_images = [
        name for name in changed_images if name != f"IMAGE/{TARGET_UUID}.webp"
    ]
    if unexpected_images:
        raise AuditError(f"non-target preview images changed: {unexpected_images}")

    type_counts = Counter(meta["docType"] for meta in final_docs.values())
    if type_counts["SCH"] != 1 or type_counts["SCH_PAGE"] != 5:
        raise AuditError("schematic parent/five-page document inventory changed")
    if type_counts["FOOTPRINT"] != 991 or type_counts["SYMBOL"] != 1452 or type_counts["DEVICE"] != 1452:
        raise AuditError("native library document inventory changed")
    return (
        {
            "projectMetadataExact": True,
            "documentCount": len(final_docs),
            "documentTypeCounts": dict(sorted(type_counts.items())),
            "onlyChangedDocumentUuid": TARGET_UUID,
            "allSchematicAndLibraryBodiesExactExcludingDochead": True,
            "schematicParentCount": type_counts["SCH"],
            "schematicPageCount": type_counts["SCH_PAGE"],
            "libraryDocumentCount": (
                type_counts["FOOTPRINT"] + type_counts["SYMBOL"] + type_counts["DEVICE"]
            ),
            "previewImageCount": len(final_images),
            "changedPreviewImages": changed_images,
            "allNonTargetPreviewImagesExact": True,
        },
        baseline_capture[TARGET_UUID],
        final_capture[TARGET_UUID],
    )


def audit_drc(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("pcbUuid") != TARGET_UUID:
        raise AuditError("DRC artifact targets a different PCB")
    rows = []
    for group in payload.get("details") or []:
        for category in group.get("list") or []:
            rows.extend(category.get("list") or [])
    counts = {str(key): int(value) for key, value in (payload.get("counts") or {}).items()}
    violations = int(payload.get("violations", -1))
    if payload.get("passed") is not True or violations != 0 or rows or any(counts.values()):
        raise AuditError(
            f"native DRC is not clear: passed={payload.get('passed')!r}, "
            f"violations={violations}, rows={len(rows)}, counts={counts!r}"
        )
    return {
        "nativePassed": True,
        "violationCount": 0,
        "detailRowCount": 0,
        "topLevelCounts": counts,
        "drcClear": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--pcb-source", type=Path, required=True)
    parser.add_argument("--drc", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    checkpoint = args.checkpoint.resolve()
    pcb_source = args.pcb_source.resolve()
    drc_path = args.drc.resolve()
    report_path = args.report.resolve()
    required = [
        BASELINE_CHECKPOINT,
        BASELINE_PCB_SOURCE,
        BASELINE_DRC,
        MULTILAYER_AUDITOR,
        checkpoint,
        pcb_source,
        drc_path,
    ]
    for path in required:
        if not path.is_file():
            raise AuditError(f"required artifact missing: {path}")
    try:
        report_path.relative_to((ROOT / "output").resolve())
    except ValueError as exc:
        raise AuditError("--report must stay under STM32H747 board/output") from exc

    helper = load_multilayer_auditor()
    baseline_source = helper.read_source(BASELINE_PCB_SOURCE)
    final_source = helper.read_source(pcb_source)
    if helper.count_types(baseline_source) != helper.count_types(final_source):
        raise AuditError("PCB source record-type inventory changed")
    final_heads = [record for record in final_source if record.kind == "DOCHEAD"]
    if (
        len(final_heads) != 1
        or final_heads[0].body.get("uuid") != TARGET_UUID
        or final_heads[0].body.get("docType") != "PCB"
    ):
        raise AuditError("supplied source is not the target PCB")

    project_summary, baseline_checkpoint_pcb, final_checkpoint_pcb = compare_project_documents(
        helper, BASELINE_CHECKPOINT, checkpoint
    )
    source_body_summary = compare_pcb_non_ui_bodies(
        baseline_source, final_source, "reopened-source"
    )
    checkpoint_body_summary = compare_pcb_non_ui_bodies(
        baseline_checkpoint_pcb, final_checkpoint_pcb, "full-checkpoint"
    )
    source_cutout = compare_cutout(baseline_source, final_source, "reopened-source")
    checkpoint_cutout = compare_cutout(
        baseline_checkpoint_pcb, final_checkpoint_pcb, "full-checkpoint"
    )
    if source_cutout["after"]["directedSegments"] != checkpoint_cutout["after"]["directedSegments"]:
        raise AuditError("final source/checkpoint CN1 cutout paths differ")

    source_checkpoint_summary = helper.compare_source_checkpoint(
        final_source,
        final_checkpoint_pcb,
        baseline_source,
        baseline_checkpoint_pcb,
    )
    drill_summary = helper.audit_drills(checkpoint, pcb_source)
    if drill_summary.get("totalPhysicalDrills") != EXPECTED_DRILL_COUNT:
        raise AuditError("physical drill inventory changed")
    baseline_drc_summary = helper.audit_drc(BASELINE_DRC)
    if (
        baseline_drc_summary.get("fillClearancePendingCount") != 0
        or baseline_drc_summary.get("cn1MechanicalOutlinePendingCount") != 4
        or baseline_drc_summary.get("connectionErrorCount") != 0
    ):
        raise AuditError("frozen copper-clearance baseline is not the known CN1-only DRC state")
    drc_summary = audit_drc(drc_path)

    final_counts = helper.count_types(final_source)
    required_counts = {
        "RULE": 18,
        "NET": 280,
        "PAD_NET": 1234,
        "COMPONENT": 330,
        "LAYER": 64,
        "LAYER_PHYS": 17,
        "VIA": 634,
        "POLY": 500,
    }
    for kind, expected in required_counts.items():
        if final_counts[kind] != expected:
            raise AuditError(f"final {kind} count {final_counts[kind]} != {expected}")

    report = {
        "schema": "stm32h747-cn1-cutout-final-preservation-audit-v1",
        "status": "pass-static-cn1-cutout-preservation-native-drc-clear-not-manufacturing-approval",
        "manufacturingApproved": False,
        "userApprovedMechanicalChange": {
            "scope": "CN1 internal square cutout only",
            "requestedSizeMm": [EXPECTED_NEW_SIZE_MM, EXPECTED_NEW_SIZE_MM],
            "date": "2026-10-16",
        },
        "inputs": {
            "baselineCheckpoint": {
                "path": str(BASELINE_CHECKPOINT.relative_to(ROOT)),
                "sha256": sha256_file(BASELINE_CHECKPOINT),
            },
            "baselinePcbSource": {
                "path": str(BASELINE_PCB_SOURCE.relative_to(ROOT)),
                "sha256": sha256_file(BASELINE_PCB_SOURCE),
            },
            "baselineDrc": {
                "path": str(BASELINE_DRC.relative_to(ROOT)),
                "sha256": sha256_file(BASELINE_DRC),
            },
            "finalCheckpoint": {
                "path": str(checkpoint.relative_to(ROOT)),
                "sha256": sha256_file(checkpoint),
            },
            "finalPcbSource": {
                "path": str(pcb_source.relative_to(ROOT)),
                "sha256": sha256_file(pcb_source),
            },
            "finalNativeDrc": {
                "path": str(drc_path.relative_to(ROOT)),
                "sha256": sha256_file(drc_path),
            },
            "staticMultilayerHelper": {
                "path": str(MULTILAYER_AUDITOR.relative_to(ROOT)),
                "sha256": sha256_file(MULTILAYER_AUDITOR),
            },
        },
        "projectPreservation": project_summary,
        "pcbPreservation": {
            "source": source_body_summary,
            "checkpoint": checkpoint_body_summary,
            "sourceCheckpointPersistence": source_checkpoint_summary,
            "requiredCounts": required_counts,
            "all18RulesExact": True,
            "all280NetsExact": True,
            "all1234PadNetBindingsExact": True,
            "all330ComponentsAndPlacementsExact": True,
            "sixLayerStackExact": True,
        },
        "approvedCn1CutoutChange": {
            "polyIds": sorted(CUTOUT_IDS),
            "source": source_cutout,
            "checkpoint": checkpoint_cutout,
            "sourceCheckpointPathsExact": True,
            "finalSizeToleranceMm": GEOMETRY_TOLERANCE_MM,
        },
        "physicalDrills": drill_summary,
        "baselineNativeDrc": baseline_drc_summary,
        "nativeDrc": drc_summary,
        "checks": {
            "onlyFourCn1PolyRecordsChanged": True,
            "onlyApprovedGeometryChangeIsTheirPath": True,
            "onlyAdditionalChangeIsDocumentedNativeZIndexNormalization": True,
            "finalCutoutIs192By192MmWithin5Nm": True,
            "cutoutCentreWindingAndExactClosurePreserved": True,
            "allOtherPcbNonUiBodiesExact": True,
            "allSchematicAndLibraryDocumentsExact": True,
            "sixLayerStackExact": True,
            "all793PhysicalDrillsExact": True,
            "all18Rules280Nets1234PadNetsExact": True,
            "nativeDrcClear": True,
        },
        "limitations": [
            "This static preservation and native-DRC audit is not manufacturing approval.",
            "The user's 1.92-mm cutout authorization does not by itself validate enclosure fit or connector retention.",
            "Fabrication drawing review, board-house capability confirmation, assembly review, and SI/PI sign-off remain external gates.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(report_path.relative_to(ROOT)),
                "sha256": sha256_file(report_path),
                "cutoutSizeMm": [
                    source_cutout["after"]["widthMm"],
                    source_cutout["after"]["heightMm"],
                ],
                "cutoutCenterDeltaMm": source_cutout["centerDeltaMm"],
                "physicalDrills": drill_summary["totalPhysicalDrills"],
                "nativeDrcViolations": drc_summary["violationCount"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
