#!/usr/bin/env python3
"""Build the 0.31-mm VIA / 0.13-mm track clearance alternative.

The input DRC measurements come from the immutable final reconstruction.
The emitted full-body application manifest is rebased on the saved one-VIA
pilot source.  This script is offline only and never touches an EasyEDA
document.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
ANALYSIS = ROOT / "output/candidates/multilayer-route-clearance/plan.json"
CURRENT = ROOT / "output/validation/native-multilayer-via-pilot_one_retry-after.epru"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/via031-track013-plan-after-via-pilot.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/via031-track013-candidate-after-via-pilot.epru"
MM_PER_MIL = 0.0254
VIA_DIAMETER_MM = 0.31
EXPECTED_VIA_HOLE_MM = 0.20
MIN_SELECTED_TRACK_WIDTH_MM = 0.13
MARGIN_MM = 0.003
VIA_PAIRS = frozenset({"Track to Via", "SMD Pad to Via", "Via to Via"})


def compact(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    target = path.resolve()
    target.relative_to(OUTPUT_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def parse_native(path: Path) -> list[dict[str, Any]]:
    records = []
    for raw in path.read_bytes().splitlines(keepends=True):
        line = raw.rstrip(b"\r\n")
        if b"||" not in line:
            continue
        header_raw, body_raw = line.split(b"||", 1)
        header = json.loads(header_raw.decode("utf-8"))
        body = json.loads(body_raw.rstrip(b"|").decode("utf-8"))
        records.append({
            "header": header,
            "body": body,
            "raw": raw,
            "key": (str(header.get("type")), header.get("id")),
        })
    keys = [record["key"] for record in records]
    if not records or len(keys) != len(set(keys)):
        raise ValueError("invalid or duplicate native records")
    return records


def main() -> int:
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    objects: dict[str, dict[str, Any]] = analysis["objects"]
    rows: list[dict[str, Any]] = [
        row for row in analysis["all_rows"]
        if row["pair"] != "Board Outline to TH Pad"
    ]
    current = parse_native(CURRENT)
    by_key = {record["key"]: record for record in current}

    via_ids = sorted({
        object_id
        for row in rows if row["pair"] in VIA_PAIRS
        for object_id in row["ids"] if objects[object_id]["type"] == "VIA"
    })
    if len(via_ids) != 188:
        raise ValueError(f"expected 188 implicated VIAs, got {len(via_ids)}")

    via_target_mil = VIA_DIAMETER_MM / MM_PER_MIL
    line_targets_mil = {
        object_id: float(descriptor["width_mil"])
        for object_id, descriptor in objects.items()
        if descriptor["type"] == "LINE"
    }
    constraints = []

    def radial_gain(row: dict[str, Any]) -> float:
        return sum(
            (float(objects[object_id]["diameter_mil"]) - via_target_mil)
            * MM_PER_MIL / 2.0
            for object_id in row["ids"]
            if objects[object_id]["type"] == "VIA"
        )

    for row in rows:
        line_ids = [
            object_id for object_id in row["ids"]
            if objects[object_id]["type"] == "LINE"
        ]
        if len(line_ids) != 1 or row["pair"] not in {"Track to Via", "SMD Pad to Track"}:
            continue
        line_id = line_ids[0]
        old_width_mm = float(objects[line_id]["width_mil"]) * MM_PER_MIL
        required_gain_mm = max(
            0.0,
            float(row["required_mm"]) + MARGIN_MM
            - float(row["actual_mm"]) - radial_gain(row),
        )
        maximum_width_mm = old_width_mm - 2.0 * required_gain_mm
        rounded_target_mm = math.floor((maximum_width_mm + 1e-12) * 1000.0) / 1000.0
        selected_mm = max(MIN_SELECTED_TRACK_WIDTH_MM, rounded_target_mm)
        if selected_mm < old_width_mm - 1e-12:
            line_targets_mil[line_id] = min(
                line_targets_mil[line_id], selected_mm / MM_PER_MIL
            )
        constraints.append({
            "globalIndex": row["global_index"],
            "pair": row["pair"],
            "lineId": line_id,
            "oldWidthMm": old_width_mm,
            "maximumWidthMmForMargin": maximum_width_mm,
            "selectedWidthMm": min(old_width_mm, selected_mm),
            "wouldRequireBelow013": maximum_width_mm < MIN_SELECTED_TRACK_WIDTH_MM,
        })

    def clearance(row: dict[str, Any]) -> float:
        gain = radial_gain(row)
        for object_id in row["ids"]:
            descriptor = objects[object_id]
            if descriptor["type"] == "LINE":
                gain += (
                    float(descriptor["width_mil"]) - line_targets_mil[object_id]
                ) * MM_PER_MIL / 2.0
        return float(row["actual_mm"]) + gain

    for row in [row for row in rows if row["pair"] == "Track to Track"]:
        needed_mm = float(row["required_mm"]) + MARGIN_MM - clearance(row)
        if needed_mm <= 0:
            continue
        line_ids = [object_id for object_id in row["ids"] if objects[object_id]["type"] == "LINE"]
        total_width_reduction_mm = 2.0 * needed_mm
        for line_id in sorted(
            line_ids,
            key=lambda object_id: (
                -(line_targets_mil[object_id] * MM_PER_MIL - MIN_SELECTED_TRACK_WIDTH_MM),
                object_id,
            ),
        ):
            current_width_mm = line_targets_mil[line_id] * MM_PER_MIL
            available_mm = max(0.0, current_width_mm - MIN_SELECTED_TRACK_WIDTH_MM)
            reduction_mm = min(available_mm, total_width_reduction_mm)
            line_targets_mil[line_id] = (current_width_mm - reduction_mm) / MM_PER_MIL
            total_width_reduction_mm -= reduction_mm
            if total_width_reduction_mm <= 1e-12:
                break

    evaluations = []
    for row in rows:
        candidate_mm = clearance(row)
        evaluations.append({
            "globalIndex": row["global_index"],
            "pair": row["pair"],
            "ids": row["ids"],
            "actualMm": row["actual_mm"],
            "requiredMm": row["required_mm"],
            "targetWithMarginMm": float(row["required_mm"]) + MARGIN_MM,
            "candidateMm": candidate_mm,
            "passesRule": candidate_mm + 1e-9 >= float(row["required_mm"]),
            "passesMargin": candidate_mm + 1e-9 >= float(row["required_mm"]) + MARGIN_MM,
        })

    changes = []
    target_fields: dict[tuple[str, str], tuple[str, float]] = {}
    for via_id in via_ids:
        record = by_key.get(("VIA", via_id))
        if record is None:
            raise ValueError(f"missing VIA {via_id}")
        before = dict(record["body"])
        if abs(float(before["holeDiameter"]) * MM_PER_MIL - EXPECTED_VIA_HOLE_MM) > 0.00001:
            raise ValueError(f"unexpected hole diameter {via_id}")
        after = dict(before)
        after["viaDiameter"] = round(via_target_mil, 6)
        if after["viaDiameter"] >= before["viaDiameter"]:
            raise ValueError(f"VIA is not a shrink {via_id}")
        changes.append({"type": "VIA", "id": via_id, "before": before, "after": after})
        target_fields[("VIA", via_id)] = ("viaDiameter", after["viaDiameter"])

    modified_line_ids = []
    for line_id, target_mil in sorted(line_targets_mil.items()):
        old_mil = float(objects[line_id]["width_mil"])
        if target_mil >= old_mil - 1e-9:
            continue
        record = by_key.get(("LINE", line_id))
        if record is None:
            raise ValueError(f"missing LINE {line_id}")
        before = dict(record["body"])
        after = dict(before)
        after["width"] = round(target_mil, 6)
        if after["width"] * MM_PER_MIL < MIN_SELECTED_TRACK_WIDTH_MM - 1e-7:
            raise ValueError(f"selected track below 0.13 mm {line_id}")
        changes.append({"type": "LINE", "id": line_id, "before": before, "after": after})
        target_fields[("LINE", line_id)] = ("width", after["width"])
        modified_line_ids.append(line_id)

    candidate_parts = []
    for record in current:
        target = target_fields.get(record["key"])
        if target is None:
            candidate_parts.append(record["raw"])
            continue
        field_name, target_value = target
        body = dict(record["body"])
        body[field_name] = target_value
        newline = b"\r\n" if record["raw"].endswith(b"\r\n") else b"\n"
        candidate_parts.append(compact(record["header"]) + b"||" + compact(body) + b"|" + newline)
    candidate = b"".join(candidate_parts)
    atomic_write(OUTPUT_CANDIDATE, candidate)

    pilot_change = next(change for change in changes if change["id"] == "e917297287b005ea")
    if (
        abs(float(pilot_change["before"]["viaDiameter"]) - 13.7795) > 1e-9
        or abs(float(pilot_change["before"]["holeDiameter"]) - 7.874) > 1e-9
    ):
        raise ValueError("saved VIA pilot was not preserved as the application baseline")

    failing_rule = [row for row in evaluations if not row["passesRule"]]
    failing_margin = [row for row in evaluations if not row["passesMargin"]]
    width_histogram = Counter(
        f"{change['before']['width'] * MM_PER_MIL:.6f}->{change['after']['width'] * MM_PER_MIL:.6f}"
        for change in changes if change["type"] == "LINE"
    )
    manifest = {
        "schema": "stm32h747-via031-track013-clearance-application-v1",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "stage": "via031_track013_after_via_pilot",
        "source": {
            "path": str(CURRENT.relative_to(ROOT)),
            "sha256": sha256(CURRENT),
            "recordCount": len(current),
        },
        "constraints": {
            "viaDiameterMm": VIA_DIAMETER_MM,
            "viaHoleMm": EXPECTED_VIA_HOLE_MM,
            "minimumSelectedTrackWidthMm": MIN_SELECTED_TRACK_WIDTH_MM,
            "clearanceMarginMm": MARGIN_MM,
            "centresDrillsNetsLayersEndpointsImmutable": True,
            "componentAndMechanicalHolesImmutable": True,
            "viaAnnulusRadialMm": (VIA_DIAMETER_MM - EXPECTED_VIA_HOLE_MM) / 2.0,
            "viaDiameterMinusHoleMm": VIA_DIAMETER_MM - EXPECTED_VIA_HOLE_MM,
        },
        "changes": changes,
        "changeCounts": {"VIA": len(via_ids), "LINE": len(modified_line_ids), "total": len(changes)},
        "lineWidthChangeHistogramMm": dict(sorted(width_histogram.items())),
        "widthConstraints": constraints,
        "staticEvaluation": {
            "rows": len(evaluations),
            "passingRule": sum(row["passesRule"] for row in evaluations),
            "passingMargin": sum(row["passesMargin"] for row in evaluations),
            "failingRule": failing_rule,
            "failingMargin": failing_margin,
            "pairCountsFailingRule": dict(sorted(Counter(row["pair"] for row in failing_rule).items())),
        },
        "applicationGate": {
            "nativeProjectWriteAuthorized": False,
            "staticGeometryOnly": True,
            "requiresNativeDrcAfterPilot": True,
            "requiresCurrentCapacityAndImpedanceReview": True,
            "requiresFillConnectivityReview": True,
            "requiresU4LandAndEscapeRepair": bool(failing_rule),
        },
        "manufacturingCaveat": (
            "The 0.31/0.20-mm VIA has 0.055-mm radial annulus and exceeds the cited "
            "0.05-mm minimum, but it does not meet the cited preferred 0.075-mm radial annulus."
        ),
        "candidate": {
            "path": str(OUTPUT_CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(OUTPUT_CANDIDATE),
            "bytes": len(candidate),
        },
    }
    atomic_write(
        OUTPUT_PLAN,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    print(json.dumps({
        "plan": str(OUTPUT_PLAN),
        "planSha256": sha256(OUTPUT_PLAN),
        "candidate": str(OUTPUT_CANDIDATE),
        "candidateSha256": sha256(OUTPUT_CANDIDATE),
        "changes": manifest["changeCounts"],
        "passingRule": manifest["staticEvaluation"]["passingRule"],
        "failingRule": len(failing_rule),
        "pairCountsFailingRule": manifest["staticEvaluation"]["pairCountsFailingRule"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
