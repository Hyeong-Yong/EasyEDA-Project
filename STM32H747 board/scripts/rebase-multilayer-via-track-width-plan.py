#!/usr/bin/env python3
"""Rebase the reviewed VIA/track-width plan after the one-VIA native pilot.

This is an offline source transformer.  It never opens or writes an EasyEDA
document.  It verifies that the native pilot changed only the approved VIA
copper diameter (plus volatile DOCHEAD fields), then emits a new full-body
change manifest and a review-only candidate source below output/candidates.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
BASELINE = ROOT / "output/validation/native-final-pcb-final_reconstruction-reopened.epru"
CURRENT = ROOT / "output/validation/native-multilayer-via-pilot_one_retry-after.epru"
REVIEWED = ROOT / "output/candidates/multilayer-route-clearance/via-track-width-plan.json"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/via-track-width-plan-after-via-pilot.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/via-track-width-candidate-after-via-pilot.epru"
PILOT_ID = "e917297287b005ea"
EXPECTED_BASELINE_DIAMETER = 15.748
EXPECTED_CURRENT_DIAMETER = 13.7795
VOLATILE_DOCHEAD_KEYS = frozenset({"client", "updateTime", "version"})


@dataclass(frozen=True)
class Record:
    header: dict[str, Any]
    body: dict[str, Any]
    raw: bytes

    @property
    def key(self) -> tuple[str, str | None]:
        return str(self.header.get("type")), self.header.get("id")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def parse(path: Path) -> list[Record]:
    records: list[Record] = []
    for raw in path.read_bytes().splitlines(keepends=True):
        line = raw.rstrip(b"\r\n")
        if b"||" not in line:
            continue
        head_raw, body_raw = line.split(b"||", 1)
        records.append(Record(
            json.loads(head_raw.decode("utf-8")),
            json.loads(body_raw.rstrip(b"|").decode("utf-8")),
            raw,
        ))
    if not records:
        raise ValueError(f"no native records in {path}")
    keys = [record.key for record in records]
    if len(keys) != len(set(keys)):
        raise ValueError(f"duplicate native record key in {path}")
    return records


def atomic_write(path: Path, payload: bytes) -> None:
    resolved = path.resolve()
    resolved.relative_to(OUTPUT_ROOT)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=resolved.name + ".tmp-", dir=resolved.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, resolved)
    finally:
        if temporary.exists():
            temporary.unlink()


def normalized_dochead(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key not in VOLATILE_DOCHEAD_KEYS}


def verify_pilot_only_change(baseline: list[Record], current: list[Record]) -> None:
    if len(baseline) != len(current):
        raise ValueError("pilot changed native record count")
    before = {record.key: record for record in baseline}
    after = {record.key: record for record in current}
    if before.keys() != after.keys():
        raise ValueError("pilot changed native record identity set")
    differences: list[tuple[str, str | None]] = []
    for key in before:
        left, right = before[key], after[key]
        if left.header != right.header:
            differences.append(key)
            continue
        if key == ("DOCHEAD", None):
            if normalized_dochead(left.body) != normalized_dochead(right.body):
                differences.append(key)
            continue
        if key == ("VIA", PILOT_ID):
            left_other = dict(left.body)
            right_other = dict(right.body)
            old_diameter = left_other.pop("viaDiameter", None)
            new_diameter = right_other.pop("viaDiameter", None)
            if (
                left_other != right_other
                or abs(float(old_diameter) - EXPECTED_BASELINE_DIAMETER) > 1e-9
                or abs(float(new_diameter) - EXPECTED_CURRENT_DIAMETER) > 1e-9
            ):
                differences.append(key)
            continue
        if left.body != right.body:
            differences.append(key)
    if differences:
        raise ValueError(f"unexpected pilot differences: {differences[:20]}")


def main() -> int:
    baseline = parse(BASELINE)
    current = parse(CURRENT)
    verify_pilot_only_change(baseline, current)

    reviewed = json.loads(REVIEWED.read_text(encoding="utf-8"))
    via_rows = reviewed.get("modified_vias", [])
    line_rows = reviewed.get("modified_lines", [])
    if len(via_rows) != 188 or len(line_rows) != 164:
        raise ValueError("reviewed target inventory changed")

    records_by_key = {record.key: record for record in current}
    target_field_by_key: dict[tuple[str, str], tuple[str, float]] = {}
    changes: list[dict[str, Any]] = []

    for type_name, rows, field_name in (
        ("VIA", via_rows, "viaDiameter"),
        ("LINE", line_rows, "width"),
    ):
        for row in rows:
            object_id = str(row["id"])
            key = (type_name, object_id)
            if key in target_field_by_key:
                raise ValueError(f"duplicate reviewed target {key}")
            record = records_by_key.get(key)
            if record is None:
                raise ValueError(f"current native source lacks {key}")
            before_body = dict(record.body)
            after_body = dict(before_body)
            target_value = float(row["after"][field_name])
            after_body[field_name] = target_value
            if before_body == after_body:
                raise ValueError(f"reviewed target is already at final value {key}")
            if type_name == "VIA":
                if after_body.get("holeDiameter") != before_body.get("holeDiameter"):
                    raise ValueError(f"VIA drill changed {object_id}")
                if target_value >= float(before_body[field_name]):
                    raise ValueError(f"VIA target is not a shrink {object_id}")
            else:
                if target_value >= float(before_body[field_name]):
                    raise ValueError(f"LINE target is not a width reduction {object_id}")
            target_field_by_key[key] = (field_name, target_value)
            changes.append({
                "type": type_name,
                "id": object_id,
                "before": before_body,
                "after": after_body,
            })

    pilot_change = next(change for change in changes if change["id"] == PILOT_ID)
    if abs(float(pilot_change["before"]["viaDiameter"]) - EXPECTED_CURRENT_DIAMETER) > 1e-9:
        raise ValueError("pilot VIA was not rebased from the saved native value")
    if abs(float(pilot_change["before"]["holeDiameter"]) - 7.874) > 1e-9:
        raise ValueError("pilot VIA drill precision was not preserved")

    candidate_parts: list[bytes] = []
    for record in current:
        target = target_field_by_key.get((record.key[0], str(record.key[1])))
        if target is None:
            candidate_parts.append(record.raw)
            continue
        field_name, target_value = target
        body = dict(record.body)
        body[field_name] = target_value
        newline = b"\r\n" if record.raw.endswith(b"\r\n") else b"\n"
        candidate_parts.append(compact(record.header) + b"||" + compact(body) + b"|" + newline)
    candidate = b"".join(candidate_parts)
    atomic_write(OUTPUT_CANDIDATE, candidate)

    manifest = {
        "schema": "stm32h747-via-track-width-clearance-application-v2",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "stage": "via_track_width_after_via_pilot",
        "source": {
            "path": str(CURRENT.relative_to(ROOT)),
            "sha256": sha256(CURRENT),
            "recordCount": len(current),
        },
        "pilot_rebase": {
            "id": PILOT_ID,
            "baselineViaDiameterMil": EXPECTED_BASELINE_DIAMETER,
            "savedBeforeViaDiameterMil": EXPECTED_CURRENT_DIAMETER,
            "savedBeforeHoleDiameterMil": pilot_change["before"]["holeDiameter"],
            "finalTargetViaDiameterMil": pilot_change["after"]["viaDiameter"],
            "verifiedOnlyNativeBodyChange": True,
        },
        "constraints": reviewed.get("constraints", {}),
        "changes": changes,
        "changeCounts": {"VIA": len(via_rows), "LINE": len(line_rows), "total": len(changes)},
        "staticEvaluationFromReviewedPlan": reviewed.get("evaluation", {}),
        "applicationGate": reviewed.get("application_gate", {}),
        "candidate": {
            "path": str(OUTPUT_CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(OUTPUT_CANDIDATE),
            "bytes": len(candidate),
        },
        "notes": [
            "Every change carries the complete current native body before and after.",
            "VIA holeDiameter, centre, net, type, layer mask, expansions, and lock state are unchanged.",
            "LINE endpoints, layer, net, group, partition, z-index, and lock state are unchanged.",
            "The static evaluation is inherited from the reviewed pre-pilot DRC geometry; native DRC remains mandatory.",
            "Thirty-three SMD-pad-to-track rows remain outside the selected rule after these changes.",
        ],
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
        "pilotBefore": manifest["pilot_rebase"]["savedBeforeViaDiameterMil"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
