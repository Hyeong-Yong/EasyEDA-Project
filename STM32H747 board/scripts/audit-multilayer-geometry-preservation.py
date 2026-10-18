#!/usr/bin/env python3
"""Audit preservation around the JLCPCB multilayer-clearance geometry pass.

This verifier is static and read-only.  It compares a supplied final full
checkpoint, reopened PCB source and native DRC result with the frozen
pre-clearance checkpoint.  Intentional copper edits are narrowly classified:

* 188 routing VIA copper diameters: 0.40 mm -> 0.31 mm; drills stay 0.20 mm.
* U4's 90 BGA lands: 0.4064 mm -> 0.36 mm; centres and bindings stay fixed.
* reviewed LINE endpoint/width edits and FILL path clipping.

Schematic pages, electrical identities, component placements, six-layer
stack, rules and all 793 physical drills must remain unchanged.  Remaining
FILL clearance findings and the four user-decision-dependent CN1 outline
findings are reported as pending, never as manufacturing approval.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
TARGET_UUID = "0ac2a19168000d8e"
U4_FOOTPRINT_UUID = "a3627e2915fe61c1"
BASELINE_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_multilayer_clearance_20261015.epro2"
BASELINE_PCB_SOURCE = ROOT / "output/validation/native-final-pcb-final_reconstruction-reopened.epru"
GERBER_MANIFEST = ROOT / "output/semantic/gerber-component-footprints.json"
DRILL_HELPER = ROOT / "scripts/audit-final-native-drill-inventory.py"
DEFAULT_REPORT = ROOT / "output/validation/native-multilayer-geometry-preservation-audit.json"
ROUTE_PLAN_PATHS = [
    ROOT / "output/candidates/multilayer-route-clearance/via031-track013-plan-after-via-pilot.json",
    ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-complete-plan.json",
    ROOT / "output/candidates/multilayer-route-clearance/u1-r17-dogleg-plan.json",
    ROOT / "output/candidates/multilayer-route-clearance/c23-reroute-plan.json",
]
FILL_PLAN_PATHS = [
    ROOT / "output/candidates/multilayer-fill-clearance/multilayer-fill-clearance-pilot.json",
    ROOT / "output/candidates/multilayer-fill-clearance/multilayer-fill-clearance-multicontour-pilot.json",
    ROOT / "output/candidates/multilayer-fill-clearance/multilayer-fill-clearance-local-routes-plan.json",
]

MM_PER_MIL = 0.0254
NUMERIC_TOLERANCE_MIL = 0.000051
EXPECTED_SOURCE_COUNTS = {
    "COMPONENT": 330,
    "ATTR": 990,
    "PAD_NET": 1234,
    "NET": 280,
    "RULE": 18,
    "RULE_TEMPLATE": 1,
    "RULE_SELECTOR": 280,
    "LAYER": 64,
    "LAYER_PHYS": 17,
    "VIA": 634,
    "PAD": 4,
    "LINE": 5422,
    "ARC": 2184,
    "FILL": 730,
    "POLY": 500,
}
EXPECTED_CHECKPOINT_RULE_SELECTORS = 279
EXPECTED_ENABLED_COPPER_LAYERS = [1, 15, 16, 17, 18, 2]
EXPECTED_LIBRARY_DOCUMENTS = {"FOOTPRINT": 991, "SYMBOL": 1452, "DEVICE": 1452}

KNOWN_LINE_REMOVED = {
    "08bab84c49139f9e",  # redundant +3V3 stub covered by 8be795786edc5cae
    "17a45052b21ce627",  # native A12 collinear merge
    "272823de64ecd339",  # native A12 collinear merge
    "700050f0e30addc3",  # native +3V3 line identity normalization
}
KNOWN_LINE_ADDED = {
    "3f727c217afd695d",  # normalized +3V3 replacement
    "86f8fbd8f121b11b",  # merged A12 line
}
KNOWN_U4_EMPTY_ATTR_ID = "e0a8672cdac74e947"
CN1_OUTLINE_IDS = {
    "f614cce4900c7115",
    "6e8dd66b3e3db1b0",
    "e94386c2e1a58187",
    "5b55024cb3a23233",
}
CN1_NPTH_OBJECT_ID = "8dfdc04036ba85c3e6"
FILL_DRC_PREFIX = "Fill Region to "


class AuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    header: dict[str, Any]
    body: dict[str, Any]

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"non-finite value {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float = NUMERIC_TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def parse_record(text: str, label: str) -> Record:
    try:
        header_text, body_text = text.split("||", 1)
        return Record(json.loads(header_text), json.loads(body_text.rstrip("|")))
    except Exception as exc:  # pragma: no cover - keep source context
        raise AuditError(f"invalid native record at {label}: {exc}") from exc


def read_source(path: Path) -> list[Record]:
    return [
        parse_record(line, f"{path.name}:{number}")
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
        if line.strip()
    ]


def record_digest_row(record: Record) -> bytes:
    return canonical({
        "type": record.kind,
        "id": record.header.get("id"),
        "body": record.body,
    }) + b"\n"


def scan_checkpoint(
    path: Path, capture_uuids: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, list[Record]], dict[str, Any], dict[str, str]]:
    documents: dict[str, dict[str, Any]] = {}
    captured: dict[str, list[Record]] = defaultdict(list)
    image_hashes: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if MEMBER not in names or "project2.json" not in names:
            raise AuditError(f"{path.name}: incomplete EasyEDA archive")
        project = json.loads(archive.read("project2.json").decode("utf-8-sig"))
        current_uuid: str | None = None
        current_type = ""
        current_count = 0
        current_digest: hashlib._Hash | None = None

        def finish() -> None:
            nonlocal current_uuid, current_type, current_count, current_digest
            if current_uuid is None or current_digest is None:
                return
            documents[current_uuid] = {
                "docType": current_type,
                "recordCountExcludingDochead": current_count,
                "semanticSha256ExcludingDochead": current_digest.hexdigest(),
            }

        with archive.open(MEMBER) as stream:
            for line_number, raw in enumerate(stream, 1):
                line = raw.decode("utf-8-sig").rstrip("\r\n")
                if not line:
                    continue
                record = parse_record(line, f"{path.name}:{MEMBER}:{line_number}")
                if record.kind == "DOCHEAD":
                    finish()
                    current_uuid = str(record.body.get("uuid") or "")
                    current_type = str(record.body.get("docType") or "")
                    if not current_uuid or current_uuid in documents:
                        raise AuditError(f"{path.name}: duplicate/empty document UUID {current_uuid!r}")
                    current_count = 0
                    current_digest = hashlib.sha256()
                    if current_uuid in capture_uuids:
                        captured[current_uuid].append(record)
                    continue
                if current_uuid is None or current_digest is None:
                    raise AuditError(f"{path.name}: record before first DOCHEAD")
                current_count += 1
                current_digest.update(record_digest_row(record))
                if current_uuid in capture_uuids:
                    captured[current_uuid].append(record)
        finish()
        for name in names:
            if not name.startswith("IMAGE/") or name.endswith("/"):
                continue
            image_hashes[name] = hashlib.sha256(archive.read(name)).hexdigest()
    return documents, dict(captured), project, image_hashes


def count_types(rows: Sequence[Record]) -> Counter[str]:
    return Counter(record.kind for record in rows)


def map_type(rows: Sequence[Record], kind: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in rows:
        if record.kind != kind:
            continue
        key = record.record_id
        if key == "None" or key in result:
            raise AuditError(f"{kind}: invalid/duplicate identity {key!r}")
        result[key] = record.body
    return result


def assert_exact_type(
    baseline: Sequence[Record], final: Sequence[Record], kind: str
) -> dict[str, Any]:
    before = map_type(baseline, kind)
    after = map_type(final, kind)
    if set(before) != set(after):
        raise AuditError(f"{kind}: record identity set changed")
    differences = [key for key in before if before[key] != after[key]]
    if differences:
        raise AuditError(f"{kind}: {len(differences)} protected bodies changed: {differences[:8]}")
    return {"count": len(before), "idSetExact": True, "bodiesExact": True}


def child_attributes(rows: Sequence[Record]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for record in rows:
        if record.kind != "ATTR":
            continue
        parent = str(record.body.get("parentId") or "")
        key = str(record.body.get("key") or "")
        value = record.body.get("value")
        if value is None:
            value = record.body.get("blockValue")
        if parent and key:
            result[parent][key] = "" if value is None else str(value)
    return result


def component_footprint_uuids(rows: Sequence[Record]) -> tuple[set[str], dict[str, str]]:
    attrs = child_attributes(rows)
    footprints: set[str] = set()
    references: dict[str, str] = {}
    components = [record for record in rows if record.kind == "COMPONENT"]
    for record in components:
        component_id = record.record_id
        reference = attrs.get(component_id, {}).get("Designator", "")
        footprint = attrs.get(component_id, {}).get("Footprint", "")
        if not reference or not footprint or reference in references:
            raise AuditError(f"COMPONENT {component_id}: invalid Designator/Footprint binding")
        references[reference] = component_id
        footprints.add(footprint)
    if len(components) != 330 or len(references) != 330:
        raise AuditError("native PCB does not contain 330 uniquely referenced components")
    return footprints, references


def planned_change_ids(paths: Sequence[Path], kind: str) -> set[str]:
    result: set[str] = set()
    for path in paths:
        plan = json.loads(path.read_text(encoding="utf-8"))
        if plan.get("pcbUuid") != TARGET_UUID:
            raise AuditError(f"{path.name}: plan targets a different PCB")
        changes = plan.get("changes")
        if not isinstance(changes, list):
            raise AuditError(f"{path.name}: missing changes list")
        for change in changes:
            if not isinstance(change, dict) or change.get("type") not in {"VIA", "LINE", "FILL"}:
                raise AuditError(f"{path.name}: malformed geometry change")
            if change.get("type") != kind:
                continue
            object_id = str(change.get("id") or "")
            if not object_id:
                raise AuditError(f"{path.name}: empty {kind} identity")
            result.add(object_id)
    return result


def compare_document_sets(
    baseline: dict[str, dict[str, Any]], final: dict[str, dict[str, Any]], doc_types: set[str],
    exceptions: set[str] | None = None,
) -> dict[str, Any]:
    exceptions = exceptions or set()
    before_ids = {uuid for uuid, meta in baseline.items() if meta["docType"] in doc_types}
    after_ids = {uuid for uuid, meta in final.items() if meta["docType"] in doc_types}
    if before_ids != after_ids:
        raise AuditError(f"document identity set changed for {sorted(doc_types)}")
    changed = [
        uuid for uuid in sorted(before_ids - exceptions)
        if baseline[uuid]["semanticSha256ExcludingDochead"] != final[uuid]["semanticSha256ExcludingDochead"]
        or baseline[uuid]["recordCountExcludingDochead"] != final[uuid]["recordCountExcludingDochead"]
    ]
    if changed:
        raise AuditError(f"protected document bodies changed for {sorted(doc_types)}: {changed[:8]}")
    return {
        "documentCount": len(before_ids),
        "documentIdsExact": True,
        "semanticBodiesExactExcludingDochead": True,
        "exceptions": sorted(exceptions),
    }


def compare_u4_footprint(baseline: Sequence[Record], final: Sequence[Record]) -> dict[str, Any]:
    before_pads = map_type(baseline, "PAD")
    after_pads = map_type(final, "PAD")
    expected_ids = {f"e{number}" for number in range(1, 91)}
    if set(before_pads) != expected_ids or set(after_pads) != expected_ids:
        raise AuditError("U4 footprint does not contain the exact e1..e90 pad inventory")
    pad_changes = []
    for pad_id in sorted(expected_ids, key=lambda value: int(value[1:])):
        before = before_pads[pad_id]
        after = after_pads[pad_id]
        before_default = dict(before.get("defaultPad") or {})
        after_default = dict(after.get("defaultPad") or {})
        if before_default.get("padType") != "ELLIPSE" or after_default.get("padType") != "ELLIPSE":
            raise AuditError(f"U4 {pad_id}: pad type changed")
        if not close(before_default.get("width"), 16) or not close(before_default.get("height"), 16):
            raise AuditError(f"U4 {pad_id}: baseline land is not 0.4064 mm")
        expected_mil = 0.36 / MM_PER_MIL
        if not close(after_default.get("width"), expected_mil) or not close(after_default.get("height"), expected_mil):
            raise AuditError(f"U4 {pad_id}: final land is not 0.36 mm")
        before_copy = json.loads(json.dumps(before))
        after_copy = json.loads(json.dumps(after))
        before_copy["defaultPad"].pop("width", None)
        before_copy["defaultPad"].pop("height", None)
        after_copy["defaultPad"].pop("width", None)
        after_copy["defaultPad"].pop("height", None)
        if before_copy != after_copy:
            raise AuditError(f"U4 {pad_id}: non-land PAD fields changed")
        pad_changes.append({
            "id": pad_id,
            "number": before.get("num"),
            "centerMil": [before.get("centerX"), before.get("centerY")],
            "beforeDiameterMm": round(16 * MM_PER_MIL, 7),
            "afterDiameterMm": round(finite(after_default["width"]) * MM_PER_MIL, 7),
        })

    before_other = {(record.kind, record.record_id): record.body for record in baseline if record.kind not in {"DOCHEAD", "PAD"}}
    after_other = {(record.kind, record.record_id): record.body for record in final if record.kind not in {"DOCHEAD", "PAD"}}
    if set(before_other) != set(after_other):
        raise AuditError("U4 non-PAD footprint record identity set changed")
    normalizations = []
    for key in sorted(before_other):
        before = before_other[key]
        after = after_other[key]
        if before == after:
            continue
        if key == ("ATTR", KNOWN_U4_EMPTY_ATTR_ID):
            normalized = dict(before)
            if normalized.get("value") == "":
                normalized.pop("value")
            if normalized == after:
                normalizations.append({
                    "record": list(key),
                    "field": "value",
                    "before": "",
                    "after": "omitted-empty-hidden-library-attribute",
                })
                continue
        raise AuditError(f"U4 protected non-PAD record changed: {key}")
    if len(normalizations) != 1:
        raise AuditError(f"U4 expected hidden ATTR normalization missing: {normalizations!r}")
    return {
        "footprintUuid": U4_FOOTPRINT_UUID,
        "padCount": len(pad_changes),
        "allCentresNumbersIdsAndNonCopperFieldsExact": True,
        "beforeDiameterMm": 0.4064,
        "afterDiameterMm": 0.36,
        "nativeNormalizations": normalizations,
        "pads": pad_changes,
    }


def compare_vias(
    baseline: Sequence[Record], final: Sequence[Record], expected_changed_ids: set[str]
) -> dict[str, Any]:
    before = map_type(baseline, "VIA")
    after = map_type(final, "VIA")
    if set(before) != set(after) or len(before) != 634:
        raise AuditError("VIA identity inventory changed")
    changed = []
    for object_id in sorted(before):
        if before[object_id] == after[object_id]:
            continue
        fields = sorted(key for key in set(before[object_id]) | set(after[object_id]) if before[object_id].get(key) != after[object_id].get(key))
        if fields != ["viaDiameter"]:
            raise AuditError(f"VIA {object_id}: protected fields changed: {fields}")
        if not close(before[object_id]["viaDiameter"] * MM_PER_MIL, 0.4, 0.000002):
            raise AuditError(f"VIA {object_id}: baseline diameter is not 0.40 mm")
        if not close(after[object_id]["viaDiameter"] * MM_PER_MIL, 0.31, 0.000002):
            raise AuditError(f"VIA {object_id}: final diameter is not 0.31 mm")
        if not close(after[object_id]["holeDiameter"] * MM_PER_MIL, 0.2, 0.000002):
            raise AuditError(f"VIA {object_id}: drill is not 0.20 mm")
        changed.append(object_id)
    if len(changed) != 188:
        raise AuditError(f"expected 188 VIA copper changes, got {len(changed)}")
    if set(changed) != expected_changed_ids:
        raise AuditError("changed VIA identity set differs from the reviewed route plan")
    return {
        "viaCount": len(before),
        "changedCopperDiameterCount": len(changed),
        "unchangedViaCount": len(before) - len(changed),
        "beforeCopperDiameterMm": 0.4,
        "afterCopperDiameterMm": 0.31,
        "drillDiameterMm": 0.2,
        "allIdsCentresNetsDrillsAndOtherFieldsExact": True,
        "changedIds": changed,
    }


def compare_lines(
    baseline: Sequence[Record], final: Sequence[Record], expected_changed_ids: set[str]
) -> dict[str, Any]:
    before = map_type(baseline, "LINE")
    after = map_type(final, "LINE")
    removed = set(before) - set(after)
    added = set(after) - set(before)
    if removed != KNOWN_LINE_REMOVED or added != KNOWN_LINE_ADDED:
        raise AuditError(f"LINE native identity changes differ: removed={sorted(removed)}, added={sorted(added)}")
    changed = []
    field_counts: Counter[str] = Counter()
    for object_id in sorted(set(before) & set(after)):
        if before[object_id] == after[object_id]:
            continue
        fields = sorted(key for key in set(before[object_id]) | set(after[object_id]) if before[object_id].get(key) != after[object_id].get(key))
        if set(fields) - {"startX", "startY", "endX", "endY", "width"}:
            raise AuditError(f"LINE {object_id}: protected fields changed: {fields}")
        if int(after[object_id].get("layerId", 0)) not in set(EXPECTED_ENABLED_COPPER_LAYERS):
            raise AuditError(f"LINE {object_id}: changed outside the enabled six copper layers")
        if finite(after[object_id]["width"]) * MM_PER_MIL < 0.12999:
            raise AuditError(f"LINE {object_id}: changed width below 0.13-mm floor")
        for coordinate in ("startX", "startY", "endX", "endY"):
            if abs(finite(after[object_id][coordinate]) - finite(before[object_id][coordinate])) > 20.0:
                raise AuditError(f"LINE {object_id}: endpoint displacement exceeds 20 mil")
        field_counts.update(fields)
        changed.append(object_id)
    expected_common = expected_changed_ids - KNOWN_LINE_REMOVED
    if set(changed) != expected_common:
        raise AuditError("changed LINE identity set differs from the reviewed route plans")
    return {
        "baselineCount": len(before),
        "finalCount": len(after),
        "changedCommonCount": len(changed),
        "changedFieldCounts": dict(sorted(field_counts.items())),
        "removedNativeNormalizedIds": sorted(removed),
        "addedNativeNormalizedIds": sorted(added),
        "protectedNetLayerAndOtherFieldsExact": True,
        "changedWidthFloorMm": 0.13,
        "changedIds": changed,
    }


def compare_fills(
    baseline: Sequence[Record], final: Sequence[Record], expected_changed_ids: set[str]
) -> dict[str, Any]:
    before = map_type(baseline, "FILL")
    after = map_type(final, "FILL")
    if set(before) != set(after) or len(before) != 730:
        raise AuditError("FILL ID inventory changed")
    changed = []
    field_counts: Counter[str] = Counter()
    for object_id in sorted(before):
        if before[object_id] == after[object_id]:
            continue
        fields = sorted(key for key in set(before[object_id]) | set(after[object_id]) if before[object_id].get(key) != after[object_id].get(key))
        if set(fields) - {"path", "zIndex", "refs"}:
            raise AuditError(f"FILL {object_id}: protected net/layer/style fields changed: {fields}")
        field_counts.update(fields)
        changed.append(object_id)
    if set(changed) != expected_changed_ids:
        raise AuditError("changed FILL identity set differs from the reviewed clipping plans")
    return {
        "count": len(before),
        "idSetExact": True,
        "changedPathCount": len(changed),
        "changedFieldCounts": dict(sorted(field_counts.items())),
        "protectedNetLayerWidthStyleAndOtherFieldsExact": True,
        "changedIds": changed,
    }


def canonical_fill_path(path: Any, label: str) -> tuple[list[list[tuple[Any, ...]]], int]:
    """Parse a native FILL path, dropping only exact zero-length L segments."""
    if not isinstance(path, list):
        raise AuditError(f"{label}: FILL path is not a contour list")
    result: list[list[tuple[Any, ...]]] = []
    removed_exact_duplicate_lines = 0
    for contour_number, contour in enumerate(path):
        contour_label = f"{label}:contour{contour_number}"
        if not isinstance(contour, list) or not contour:
            raise AuditError(f"{contour_label}: invalid empty/non-list contour")
        if contour[0] == "CIRCLE":
            if len(contour) != 4 or any(isinstance(value, str) for value in contour[1:]):
                raise AuditError(f"{contour_label}: malformed CIRCLE contour")
            result.append([("CIRCLE", *contour[1:])])
            continue
        if len(contour) < 2 or isinstance(contour[0], str) or isinstance(contour[1], str):
            raise AuditError(f"{contour_label}: missing numeric start point")
        current = (contour[0], contour[1])
        segments: list[tuple[Any, ...]] = [("M", *current)]
        index = 2
        while index < len(contour):
            token = contour[index]
            if isinstance(token, str):
                if token == "L":
                    index += 1
                    continue
                if token == "ARC":
                    if index + 3 >= len(contour):
                        raise AuditError(f"{contour_label}: truncated ARC command")
                    sweep, end_x, end_y = contour[index + 1:index + 4]
                    if any(isinstance(value, str) for value in (sweep, end_x, end_y)):
                        raise AuditError(f"{contour_label}: malformed ARC operands")
                    segments.append(("ARC", sweep, end_x, end_y))
                    current = (end_x, end_y)
                    index += 4
                    continue
                raise AuditError(f"{contour_label}: unsupported path token {token!r}")
            if index + 1 >= len(contour) or isinstance(contour[index + 1], str):
                raise AuditError(f"{contour_label}: incomplete L coordinate pair")
            end = (token, contour[index + 1])
            if end == current:
                removed_exact_duplicate_lines += 1
            else:
                segments.append(("L", *end))
                current = end
            index += 2
        result.append(segments)
    return result, removed_exact_duplicate_lines


def compare_fill_paths(left: Any, right: Any, label: str) -> dict[str, Any]:
    left_contours, left_removed = canonical_fill_path(left, f"{label}:source")
    right_contours, right_removed = canonical_fill_path(right, f"{label}:checkpoint")
    if len(left_contours) != len(right_contours):
        raise AuditError(f"{label}: FILL contour count changed during checkpoint serialization")
    maximum_coordinate_delta = 0.0
    for contour_number, (left_segments, right_segments) in enumerate(zip(left_contours, right_contours)):
        if len(left_segments) != len(right_segments):
            raise AuditError(
                f"{label}: FILL segment count changed after exact duplicate-L removal "
                f"in contour {contour_number}"
            )
        for segment_number, (left_segment, right_segment) in enumerate(zip(left_segments, right_segments)):
            if left_segment[0] != right_segment[0] or len(left_segment) != len(right_segment):
                raise AuditError(
                    f"{label}: FILL command changed at contour {contour_number}, segment {segment_number}"
                )
            command = str(left_segment[0])
            if command == "ARC" and finite(left_segment[1]) != finite(right_segment[1]):
                raise AuditError(
                    f"{label}: FILL ARC sweep changed at contour {contour_number}, segment {segment_number}"
                )
            numeric_start = 2 if command == "ARC" else 1
            for left_value, right_value in zip(
                left_segment[numeric_start:], right_segment[numeric_start:]
            ):
                delta = abs(finite(left_value) - finite(right_value))
                maximum_coordinate_delta = max(maximum_coordinate_delta, delta)
                if delta > NUMERIC_TOLERANCE_MIL:
                    raise AuditError(
                        f"{label}: FILL coordinate quantization {delta} mil exceeds "
                        f"{NUMERIC_TOLERANCE_MIL} mil"
                    )
    return {
        "sourceExactDuplicateLineSegmentsRemoved": left_removed,
        "checkpointExactDuplicateLineSegmentsRemoved": right_removed,
        "maximumCoordinateQuantizationMil": maximum_coordinate_delta,
    }


def compare_source_checkpoint(
    source: Sequence[Record], checkpoint: Sequence[Record], baseline_source: Sequence[Record], baseline_checkpoint: Sequence[Record]
) -> dict[str, Any]:
    exact_types = {
        "COMPONENT", "ATTR", "PAD_NET", "NET", "RULE", "RULE_TEMPLATE",
        "LAYER", "LAYER_PHYS", "VIA", "PAD", "LINE", "ARC", "POLY",
        "PRIMITIVE", "SILK_OPTS", "PREFERENCE", "PANELIZE",
    }
    summaries = {}
    for kind in sorted(exact_types):
        summaries[kind] = assert_exact_type(source, checkpoint, kind)

    source_fills = map_type(source, "FILL")
    checkpoint_fills = map_type(checkpoint, "FILL")
    if set(source_fills) != set(checkpoint_fills):
        raise AuditError("source/checkpoint FILL identity set differs")
    fill_path_normalizations = 0
    source_duplicate_lines_removed = 0
    checkpoint_duplicate_lines_removed = 0
    maximum_fill_coordinate_quantization = 0.0
    for object_id in source_fills:
        serialization_fields = {"path", "refs", "zIndex"}
        left = {key: value for key, value in source_fills[object_id].items() if key not in serialization_fields}
        right = {key: value for key, value in checkpoint_fills[object_id].items() if key not in serialization_fields}
        if left != right:
            raise AuditError(f"source/checkpoint FILL protected body differs: {object_id}")
        if source_fills[object_id].get("path") != checkpoint_fills[object_id].get("path"):
            equivalence = compare_fill_paths(
                source_fills[object_id].get("path"), checkpoint_fills[object_id].get("path"), object_id
            )
            fill_path_normalizations += 1
            source_duplicate_lines_removed += equivalence["sourceExactDuplicateLineSegmentsRemoved"]
            checkpoint_duplicate_lines_removed += equivalence["checkpointExactDuplicateLineSegmentsRemoved"]
            maximum_fill_coordinate_quantization = max(
                maximum_fill_coordinate_quantization,
                equivalence["maximumCoordinateQuantizationMil"],
            )

    base_source_selectors = map_type(baseline_source, "RULE_SELECTOR")
    base_checkpoint_selectors = map_type(baseline_checkpoint, "RULE_SELECTOR")
    source_selectors = map_type(source, "RULE_SELECTOR")
    checkpoint_selectors = map_type(checkpoint, "RULE_SELECTOR")
    baseline_missing = set(base_source_selectors) - set(base_checkpoint_selectors)
    final_missing = set(source_selectors) - set(checkpoint_selectors)
    if (
        len(source_selectors) != 280
        or len(checkpoint_selectors) != EXPECTED_CHECKPOINT_RULE_SELECTORS
        or baseline_missing != final_missing
        or set(checkpoint_selectors) - set(source_selectors)
        or any(source_selectors[key] != checkpoint_selectors[key] for key in checkpoint_selectors)
    ):
        raise AuditError("source/checkpoint RULE_SELECTOR persistence differs from baseline")
    return {
        "exactTypes": summaries,
        "fillIdsExact": True,
        "fillProtectedBodiesExact": True,
        "fillPathSerializationDifferences": fill_path_normalizations,
        "fillPathEquivalence": {
            "onlyExactConsecutiveDuplicateLineRemovalAndCoordinateQuantization": True,
            "sourceExactDuplicateLineSegmentsRemoved": source_duplicate_lines_removed,
            "checkpointExactDuplicateLineSegmentsRemoved": checkpoint_duplicate_lines_removed,
            "maximumCoordinateQuantizationMil": maximum_fill_coordinate_quantization,
            "coordinateToleranceMil": NUMERIC_TOLERANCE_MIL,
            "nonLineCommandSequenceAndArcSweepsExact": True,
        },
        "ruleSelectorSourceCount": len(source_selectors),
        "ruleSelectorCheckpointCount": len(checkpoint_selectors),
        "baselineKnownCheckpointOmissionIds": sorted(baseline_missing),
    }


def load_drill_helper() -> Any:
    spec = importlib.util.spec_from_file_location("stm32h747_final_drill_helper", DRILL_HELPER)
    if spec is None or spec.loader is None:
        raise AuditError("cannot load final drill helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_drills(checkpoint: Path, pcb_source: Path) -> dict[str, Any]:
    helper = load_drill_helper()
    manifest = json.loads(GERBER_MANIFEST.read_text(encoding="utf-8"))
    expected = helper.expected_drills(manifest)
    actual, native_summary = helper.native_inventory(checkpoint, pcb_source)
    counts = {key: len(value) for key, value in actual.items()}
    wanted = {
        "via_round": 634,
        "component_round": 133,
        "component_slot": 13,
        "component_npth": 9,
        "board_npth": 4,
    }
    if counts != wanted:
        raise AuditError(f"native drill inventory differs: {counts!r}")
    matches = {
        "via_round": helper.match_round("via_round", expected["via_round"], actual["via_round"]),
        "component_round": helper.match_round("component_round", expected["component_round"], actual["component_round"]),
        "component_slot": helper.match_slots(expected["component_slot"], actual["component_slot"]),
        "npth": helper.match_round("npth", expected["npth"], [*actual["component_npth"], *actual["board_npth"]]),
    }
    total = sum(counts.values())
    if total != 793:
        raise AuditError(f"physical drill total {total} != 793")
    return {
        "totalPhysicalDrills": total,
        "nativeCounts": counts,
        "sourceCounts": {key: len(value) for key, value in expected.items()},
        "matchSummary": {key: helper.summarize_errors(value) for key, value in matches.items()},
        "allCentresHoleSizesSlotAnglesAndOwnershipMatchOriginalExcellon": True,
        "nativeSummary": native_summary,
    }


def audit_drc(path: Path) -> dict[str, Any]:
    drc = json.loads(path.read_text(encoding="utf-8"))
    if drc.get("pcbUuid") != TARGET_UUID:
        raise AuditError("DRC artifact targets a different PCB")
    category_counts: Counter[str] = Counter()
    rows_by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in drc.get("details") or []:
        for category in group.get("list") or []:
            name = str(category.get("name") or "")
            rows = list(category.get("list") or [])
            category_counts[name] += len(rows)
            rows_by_category[name].extend(rows)
    connection_count = int((drc.get("counts") or {}).get("Connection Error", 0))
    if connection_count != 0:
        raise AuditError(f"DRC has {connection_count} Connection Error findings")
    unexpected = {
        name: count for name, count in category_counts.items()
        if count and not name.startswith(FILL_DRC_PREFIX) and name != "Board Outline to TH Pad"
    }
    if unexpected:
        raise AuditError(f"unexpected non-FILL DRC categories remain: {unexpected!r}")
    outline_rows = rows_by_category.get("Board Outline to TH Pad", [])
    if len(outline_rows) not in {0, 4}:
        raise AuditError(f"unexpected board-outline finding count {len(outline_rows)}")
    if outline_rows:
        observed_pairs = {frozenset(row.get("objs") or []) for row in outline_rows}
        expected_pairs = {frozenset({outline_id, CN1_NPTH_OBJECT_ID}) for outline_id in CN1_OUTLINE_IDS}
        if observed_pairs != expected_pairs:
            raise AuditError("board-outline findings are not the four known CN1 cutout rows")
    fill_count = sum(count for name, count in category_counts.items() if name.startswith(FILL_DRC_PREFIX))
    detail_total = sum(category_counts.values())
    top_counts = {str(key): int(value) for key, value in (drc.get("counts") or {}).items()}
    violation_count = int(drc.get("violations", -1))
    if detail_total != violation_count or sum(top_counts.values()) != violation_count:
        raise AuditError(
            f"DRC count mismatch: details={detail_total}, top={sum(top_counts.values())}, "
            f"violations={violation_count}"
        )
    positive_top = {key: value for key, value in top_counts.items() if value}
    expected_top = {} if violation_count == 0 else {"Clearance Error": violation_count}
    if positive_top != expected_top:
        raise AuditError(f"unexpected top-level DRC categories: {positive_top!r}")
    if bool(drc.get("passed")) != (violation_count == 0):
        raise AuditError("native DRC passed flag disagrees with its finding count")
    return {
        "nativePassed": bool(drc.get("passed")),
        "violationCount": violation_count,
        "topLevelCounts": top_counts,
        "categoryCounts": dict(sorted(category_counts.items())),
        "connectionErrorCount": connection_count,
        "unexpectedNonFillFindingCount": sum(unexpected.values()),
        "fillClearancePendingCount": fill_count,
        "cn1MechanicalOutlinePendingCount": len(outline_rows),
        "onlyAllowedPendingCategoriesRemain": True,
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
    required_paths = (
        BASELINE_CHECKPOINT, BASELINE_PCB_SOURCE, GERBER_MANIFEST, DRILL_HELPER,
        *ROUTE_PLAN_PATHS, *FILL_PLAN_PATHS, checkpoint, pcb_source, drc_path,
    )
    for path in required_paths:
        if not path.is_file():
            raise AuditError(f"required artifact missing: {path}")
    try:
        report_path.relative_to((ROOT / "output").resolve())
    except ValueError as exc:
        raise AuditError("--report must stay under STM32H747 board/output") from exc

    baseline_source = read_source(BASELINE_PCB_SOURCE)
    final_source = read_source(pcb_source)
    planned_via_ids = planned_change_ids(ROUTE_PLAN_PATHS, "VIA")
    planned_line_ids = planned_change_ids(ROUTE_PLAN_PATHS, "LINE")
    planned_fill_ids = planned_change_ids(FILL_PLAN_PATHS, "FILL")
    if len(planned_via_ids) != 188 or len(planned_line_ids) != 187 or len(planned_fill_ids) != 107:
        raise AuditError(
            "reviewed plan inventories changed: "
            f"VIA={len(planned_via_ids)}, LINE={len(planned_line_ids)}, FILL={len(planned_fill_ids)}"
        )
    final_counts = count_types(final_source)
    for kind, expected in EXPECTED_SOURCE_COUNTS.items():
        if final_counts[kind] != expected:
            raise AuditError(f"final source {kind} count {final_counts[kind]} != {expected}")
    final_head = [record for record in final_source if record.kind == "DOCHEAD"]
    if len(final_head) != 1 or final_head[0].body.get("uuid") != TARGET_UUID or final_head[0].body.get("docType") != "PCB":
        raise AuditError("final source is not the dedicated target PCB")

    footprint_uuids, references = component_footprint_uuids(final_source)
    capture = {TARGET_UUID, U4_FOOTPRINT_UUID, *footprint_uuids}
    baseline_docs, baseline_captured, baseline_project, baseline_images = scan_checkpoint(BASELINE_CHECKPOINT, capture)
    final_docs, final_captured, final_project, final_images = scan_checkpoint(checkpoint, capture)
    if baseline_project != final_project:
        raise AuditError("project2.json metadata changed")
    if TARGET_UUID not in baseline_captured or TARGET_UUID not in final_captured:
        raise AuditError("target PCB block absent from a checkpoint")
    if U4_FOOTPRINT_UUID not in baseline_captured or U4_FOOTPRINT_UUID not in final_captured:
        raise AuditError("U4 footprint block absent from a checkpoint")

    baseline_pcb = baseline_captured[TARGET_UUID]
    final_pcb_checkpoint = final_captured[TARGET_UUID]
    checkpoint_counts = count_types(final_pcb_checkpoint)
    for kind, expected in EXPECTED_SOURCE_COUNTS.items():
        checkpoint_expected = EXPECTED_CHECKPOINT_RULE_SELECTORS if kind == "RULE_SELECTOR" else expected
        if checkpoint_counts[kind] != checkpoint_expected:
            raise AuditError(f"checkpoint PCB {kind} count {checkpoint_counts[kind]} != {checkpoint_expected}")

    schematic_docs = compare_document_sets(baseline_docs, final_docs, {"SCH", "SCH_PAGE"})
    schematic_page_ids = sorted(uuid for uuid, meta in final_docs.items() if meta["docType"] == "SCH_PAGE")
    if len(schematic_page_ids) != 5:
        raise AuditError(f"expected five schematic pages, got {len(schematic_page_ids)}")
    schematic_images = {}
    for uuid in schematic_page_ids:
        name = f"IMAGE/{uuid}.webp"
        if name not in baseline_images or name not in final_images or baseline_images[name] != final_images[name]:
            raise AuditError(f"schematic page preview changed or absent: {uuid}")
        schematic_images[uuid] = final_images[name]

    library_summary = compare_document_sets(
        baseline_docs, final_docs, set(EXPECTED_LIBRARY_DOCUMENTS), {U4_FOOTPRINT_UUID}
    )
    final_doc_type_counts = Counter(meta["docType"] for meta in final_docs.values())
    for kind, expected in EXPECTED_LIBRARY_DOCUMENTS.items():
        if final_doc_type_counts[kind] != expected:
            raise AuditError(f"checkpoint {kind} document count changed")

    protected_types = [
        "COMPONENT", "ATTR", "PAD_NET", "NET", "RULE", "RULE_TEMPLATE", "RULE_SELECTOR",
        "LAYER", "LAYER_PHYS", "ARC", "POLY", "PAD", "PRIMITIVE", "SILK_OPTS", "PREFERENCE", "PANELIZE",
    ]
    protected_summary = {kind: assert_exact_type(baseline_source, final_source, kind) for kind in protected_types}
    via_summary = compare_vias(baseline_source, final_source, planned_via_ids)
    line_summary = compare_lines(baseline_source, final_source, planned_line_ids)
    fill_summary = compare_fills(baseline_source, final_source, planned_fill_ids)
    u4_summary = compare_u4_footprint(
        baseline_captured[U4_FOOTPRINT_UUID], final_captured[U4_FOOTPRINT_UUID]
    )
    source_checkpoint_summary = compare_source_checkpoint(
        final_source, final_pcb_checkpoint, baseline_source, baseline_pcb
    )

    layers = map_type(final_source, "LAYER")
    for layer_id in EXPECTED_ENABLED_COPPER_LAYERS:
        key = json.dumps(["LAYER", layer_id], separators=(",", ":"))
        # EasyEDA serializes the ID string with optional spaces; use decoded lookup.
        matching = [body for raw_id, body in layers.items() if json.loads(raw_id) == ["LAYER", layer_id]]
        if len(matching) != 1 or matching[0].get("use") is not True:
            raise AuditError(f"copper layer {layer_id} is not enabled")
    templates = list(map_type(final_source, "RULE_TEMPLATE").values())
    if [body.get("name") for body in templates] != ["JLCPCB Capability(Multiple Layers Board)"]:
        raise AuditError("selected multilayer rule template changed")

    board_outline = {
        object_id: body for object_id, body in map_type(final_source, "POLY").items()
        if int(body.get("layerId", 0)) == 11
    }
    baseline_outline = {
        object_id: body for object_id, body in map_type(baseline_source, "POLY").items()
        if int(body.get("layerId", 0)) == 11
    }
    if board_outline != baseline_outline or len(board_outline) != 8:
        raise AuditError("mechanical board-outline geometry changed")

    drill_summary = audit_drills(checkpoint, pcb_source)
    drc_summary = audit_drc(drc_path)
    pending = drc_summary["fillClearancePendingCount"] + drc_summary["cn1MechanicalOutlinePendingCount"]
    status = (
        "pass-static-preservation-drc-pending-not-manufacturing-approval"
        if pending else
        "pass-static-preservation-native-drc-clear-not-manufacturing-approval"
    )
    report = {
        "schema": "stm32h747-multilayer-geometry-preservation-audit-v1",
        "status": status,
        "manufacturingApproved": False,
        "inputs": {
            "baselineCheckpoint": {"path": str(BASELINE_CHECKPOINT.relative_to(ROOT)), "sha256": sha256_file(BASELINE_CHECKPOINT)},
            "baselinePcbSource": {"path": str(BASELINE_PCB_SOURCE.relative_to(ROOT)), "sha256": sha256_file(BASELINE_PCB_SOURCE)},
            "finalCheckpoint": {"path": str(checkpoint.relative_to(ROOT)), "sha256": sha256_file(checkpoint)},
            "finalPcbSource": {"path": str(pcb_source.relative_to(ROOT)), "sha256": sha256_file(pcb_source)},
            "nativeDrc": {"path": str(drc_path.relative_to(ROOT)), "sha256": sha256_file(drc_path)},
            "gerberDrillManifest": {"path": str(GERBER_MANIFEST.relative_to(ROOT)), "sha256": sha256_file(GERBER_MANIFEST)},
            "reviewedRoutePlans": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in ROUTE_PLAN_PATHS
            ],
            "reviewedFillPlans": [
                {"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in FILL_PLAN_PATHS
            ],
        },
        "projectIdentity": {
            "projectMetadataExact": True,
            "targetPcbUuid": TARGET_UUID,
            "componentCount": len(references),
            "componentReferences": sorted(references),
            "documentTypeCounts": dict(sorted(final_doc_type_counts.items())),
        },
        "schematicPreservation": {
            **schematic_docs,
            "schematicPageCount": len(schematic_page_ids),
            "schematicPageIds": schematic_page_ids,
            "pagePreviewHashesExact": True,
            "pagePreviewSha256": schematic_images,
        },
        "libraryPreservation": {
            **library_summary,
            "expectedDocumentCounts": EXPECTED_LIBRARY_DOCUMENTS,
            "onlyIntentionalException": "U4 footprint land diameter",
            "u4": u4_summary,
        },
        "pcbPreservation": {
            "finalSourceCounts": dict(sorted(final_counts.items())),
            "checkpointCounts": dict(sorted(checkpoint_counts.items())),
            "protectedTypesAgainstBaseline": protected_summary,
            "sourceCheckpointPersistence": source_checkpoint_summary,
            "viaCopper": via_summary,
            "lineRouting": line_summary,
            "fillClipping": fill_summary,
            "mechanicalOutline": {
                "polyCount": len(board_outline),
                "ids": sorted(board_outline),
                "bodiesExactAgainstBaseline": True,
                "cn1ClearanceDecisionPending": drc_summary["cn1MechanicalOutlinePendingCount"] == 4,
            },
            "sixLayerStack": {
                "logicalLayerCount": final_counts["LAYER"],
                "physicalLayerCount": final_counts["LAYER_PHYS"],
                "enabledCopperLayerIds": EXPECTED_ENABLED_COPPER_LAYERS,
                "allLayerBodiesExactAgainstBaseline": True,
            },
            "electrical": {
                "netCount": final_counts["NET"],
                "padNetCount": final_counts["PAD_NET"],
                "componentCount": final_counts["COMPONENT"],
                "allBodiesExactAgainstBaseline": True,
            },
            "selectedRuleTemplate": templates[0].get("name"),
            "ruleCount": final_counts["RULE"],
        },
        "physicalDrills": drill_summary,
        "nativeDrc": drc_summary,
        "checks": {
            "fiveSchematicPagesAndParentSourceUnchanged": True,
            "allNonU4LibraryDocumentsUnchanged": True,
            "all18RulesAnd280NetsUnchanged": True,
            "all1234PadNetBindingsUnchanged": True,
            "all330ComponentPlacementsAndLibraryBindingsUnchanged": True,
            "sixCopperLayerStackUnchanged": True,
            "all793PhysicalDrillCentresAndSizesMatchOriginal": True,
            "exactly188ViaCopperDiametersAre031Mm": True,
            "exactly90U4LandDiametersAre036Mm": True,
            "mechanicalOutlineGeometryUnchanged": True,
            "drcConnectionErrorCountIsZero": True,
            "noUnexpectedNonFillDrcCategoryRemains": True,
        },
        "limitations": [
            "This is a preservation and native-DRC-category audit, not fabrication or signal/power-integrity approval.",
            "FILL clearance findings, when nonzero, remain unresolved work rather than waived errors.",
            "The four CN1 internal-cutout outline findings remain pending the user's mechanical-dimension decision; the outline was not changed by this phase.",
            "U4's 0.36-mm land follows the reviewed ISSI nominal-ball guidance, but assembly process and SI/PI sign-off remain external gates.",
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": status,
        "report": str(report_path.relative_to(ROOT)),
        "sha256": sha256_file(report_path),
        "drc": drc_summary,
        "physicalDrills": {key: drill_summary[key] for key in ("totalPhysicalDrills", "nativeCounts")},
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
