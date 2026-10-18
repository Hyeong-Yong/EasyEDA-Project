#!/usr/bin/env python3
"""Build a guarded two-line dogleg for the U1_R17 clearance error.

This is an offline candidate only.  It rebases on the native board reopened
after the VIA-0.31/track-0.13 pass and preserves every net, width, layer,
object ID, and route endpoint outside the shared internal corner.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
SOURCE = ROOT / "output/validation/native-multilayer-via031_track013-reopened.epru"
PAD_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-via031_track013.json"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/u1-r17-dogleg-plan.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/u1-r17-dogleg-candidate.epru"
MM_PER_MIL = 0.0254
RULE_MM = 0.15200122
TARGET_ID = "b220b0b57fba3006"
HORIZONTAL_ID = "4928e024eebdd442"
UPSTREAM_ID = "f2b66b35c9d7309b"
DOWNSTREAM_ID = "bf7802f2ccefb5cb"
CONFLICT_PAD_ID = "a2d6b5393a9714c7e231"


def compact(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


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
        records.append({"header": header, "body": body, "raw": raw, "key": (header.get("type"), header.get("id"))})
    keys = [record["key"] for record in records]
    if not records or len(keys) != len(set(keys)):
        raise ValueError("invalid native inventory")
    return records


def line_geometry(body: dict[str, Any]):
    return LineString([
        (float(body["startX"]), float(body["startY"])),
        (float(body["endX"]), float(body["endY"])),
    ]).buffer(float(body["width"]) / 2.0, cap_style=1, join_style=1, resolution=48)


def pad_geometry(entry: dict[str, Any]):
    center = entry["native_board_center_mil"]
    shapes = []
    for flash in entry["source_flashes"]:
        if flash["layer"] != "F.Cu":
            continue
        params = [float(value) / MM_PER_MIL for value in flash["params_mm"]]
        if flash["shape"] == "C":
            shapes.append(Point(*center).buffer(params[0] / 2.0, resolution=64))
        elif flash["shape"] == "R" and len(params) >= 2:
            shapes.append(box(
                center[0] - params[0] / 2.0,
                center[1] - params[1] / 2.0,
                center[0] + params[0] / 2.0,
                center[1] + params[1] / 2.0,
            ))
    return unary_union(shapes) if shapes else None


def endpoint(body: dict[str, Any], prefix: str) -> tuple[float, float]:
    return float(body[prefix + "X"]), float(body[prefix + "Y"])


def main() -> int:
    records = parse_native(SOURCE)
    by_key = {record["key"]: record for record in records}
    lines = {
        record["header"]["id"]: record["body"]
        for record in records if record["header"].get("type") == "LINE"
    }
    vias = [record for record in records if record["header"].get("type") == "VIA"]
    for object_id in (TARGET_ID, HORIZONTAL_ID, UPSTREAM_ID, DOWNSTREAM_ID):
        if object_id not in lines:
            raise ValueError(f"missing LINE {object_id}")

    before_target = dict(lines[TARGET_ID])
    before_horizontal = dict(lines[HORIZONTAL_ID])
    upstream = lines[UPSTREAM_ID]
    downstream = lines[DOWNSTREAM_ID]
    net = before_target["netName"]
    if not all(lines[object_id]["netName"] == net for object_id in (HORIZONTAL_ID, UPSTREAM_ID, DOWNSTREAM_ID)):
        raise ValueError("route net mismatch")
    if not all(int(lines[object_id]["layerId"]) == 1 for object_id in (TARGET_ID, HORIZONTAL_ID, UPSTREAM_ID, DOWNSTREAM_ID)):
        raise ValueError("route layer mismatch")

    # Replace the original 45-degree segment with a vertical leg, and extend
    # the already-horizontal neighbour to the new corner.  The route's two
    # external endpoints remain byte-for-byte unchanged.
    a = endpoint(before_target, "start")
    b = endpoint(before_target, "end")
    d = endpoint(before_horizontal, "end")
    corner = (a[0], b[1])
    if endpoint(before_horizontal, "start") != b:
        raise ValueError("target/horizontal lines are not connected")
    if endpoint(upstream, "end") != a or endpoint(downstream, "start") != d:
        raise ValueError("external route topology changed")
    after_target = dict(before_target)
    after_target["endX"], after_target["endY"] = corner
    after_horizontal = dict(before_horizontal)
    after_horizontal["startX"], after_horizontal["startY"] = corner
    desired = {TARGET_ID: after_target, HORIZONTAL_ID: after_horizontal}

    candidate_parts = []
    changes = []
    for record in records:
        object_id = record["header"].get("id")
        if record["header"].get("type") != "LINE" or object_id not in desired:
            candidate_parts.append(record["raw"])
            continue
        before = dict(record["body"])
        after = desired[object_id]
        changed_fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        if not changed_fields or set(changed_fields) - {"startX", "startY", "endX", "endY"}:
            raise ValueError(f"unexpected fields for {object_id}: {changed_fields}")
        changes.append({"type": "LINE", "id": object_id, "before": before, "after": after, "changedFields": changed_fields})
        newline = b"\r\n" if record["raw"].endswith(b"\r\n") else b"\n"
        candidate_parts.append(compact(record["header"]) + b"||" + compact(after) + b"|" + newline)

    candidate = b"".join(candidate_parts)
    atomic_write(OUTPUT_CANDIDATE, candidate)
    candidate_records = parse_native(OUTPUT_CANDIDATE)
    candidate_by_key = {record["key"]: record for record in candidate_records}
    exact_differences = []
    for key in sorted(set(by_key) | set(candidate_by_key), key=str):
        before = by_key.get(key)
        after = candidate_by_key.get(key)
        if before is None or after is None or before["body"] != after["body"]:
            exact_differences.append(key)
    if exact_differences != [("LINE", HORIZONTAL_ID), ("LINE", TARGET_ID)]:
        raise ValueError(f"unexpected candidate differences: {exact_differences}")

    candidate_lines = {
        record["header"]["id"]: record["body"]
        for record in candidate_records if record["header"].get("type") == "LINE"
    }
    route_ids = {TARGET_ID, HORIZONTAL_ID, UPSTREAM_ID, DOWNSTREAM_ID}
    route_geometry = unary_union([line_geometry(candidate_lines[object_id]) for object_id in route_ids])
    obstacles = []
    for object_id, body in candidate_lines.items():
        if int(body["layerId"]) != 1 or object_id in route_ids or body["netName"].casefold() == net.casefold():
            continue
        obstacles.append({"id": object_id, "label": "LINE:" + object_id, "net": body["netName"], "geometry": line_geometry(body)})
    for record in vias:
        body = record["body"]
        if body["netName"].casefold() == net.casefold():
            continue
        obstacles.append({
            "id": record["header"]["id"],
            "label": "VIA:" + record["header"]["id"],
            "net": body["netName"],
            "geometry": Point(float(body["centerX"]), float(body["centerY"])).buffer(float(body["viaDiameter"]) / 2.0, resolution=64),
        })

    pad_audit = json.loads(PAD_AUDIT.read_text(encoding="utf-8"))
    conflict_pad_clearance = None
    for entry in pad_audit["matched_component_copper_centres"]:
        geometry = pad_geometry(entry)
        if geometry is None:
            continue
        pad_id = entry["component_id"] + entry["pad_id"]
        pad_net = entry["pcb_net"]
        if pad_net and pad_net.casefold() == net.casefold():
            continue
        obstacles.append({"id": pad_id, "label": entry["reference"] + "_" + entry["number"], "net": pad_net, "geometry": geometry})

    nearest = sorted(
        ((route_geometry.distance(obstacle["geometry"]) * MM_PER_MIL, obstacle) for obstacle in obstacles),
        key=lambda item: (item[0], item[1]["label"]),
    )[:20]
    for distance, obstacle in nearest:
        if obstacle["id"] == CONFLICT_PAD_ID:
            conflict_pad_clearance = distance
    if conflict_pad_clearance is None:
        conflict = next(obstacle for obstacle in obstacles if obstacle["id"] == CONFLICT_PAD_ID)
        conflict_pad_clearance = route_geometry.distance(conflict["geometry"]) * MM_PER_MIL
    if nearest[0][0] + 1e-7 < RULE_MM or conflict_pad_clearance + 1e-7 < RULE_MM:
        raise ValueError("dogleg still violates the selected clearance rule")

    drc = json.loads(DRC.read_text(encoding="utf-8"))
    matching_rows = []
    for top in drc["details"]:
        for category in top["list"]:
            for row in category["list"]:
                error = row["explanation"]["errData"]
                if set(error.get("objs", row.get("objs", []))) == {TARGET_ID, CONFLICT_PAD_ID} or set(row.get("objs", [])) == {TARGET_ID, CONFLICT_PAD_ID}:
                    matching_rows.append({"category": category["name"], "globalIndex": row["globalIndex"], "objects": row["objs"]})
    if len(matching_rows) != 1:
        raise ValueError(f"expected one native DRC row for U1_R17, got {matching_rows}")

    before_length = (
        LineString([endpoint(before_target, "start"), endpoint(before_target, "end")]).length
        + LineString([endpoint(before_horizontal, "start"), endpoint(before_horizontal, "end")]).length
    ) * MM_PER_MIL
    after_length = (
        LineString([endpoint(after_target, "start"), endpoint(after_target, "end")]).length
        + LineString([endpoint(after_horizontal, "start"), endpoint(after_horizontal, "end")]).length
    ) * MM_PER_MIL
    plan = {
        "schema": "stm32h747-u1-r17-clearance-plan-v1",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "nativeDrcEvidence": {"path": str(DRC.relative_to(ROOT)), "sha256": sha256(DRC), "matchingRows": matching_rows},
        "changes": changes,
        "changeCounts": {"LINE": 2, "total": 2},
        "topologyProof": {
            "net": net,
            "layerId": 1,
            "externalStart": a,
            "externalEnd": d,
            "oldSharedCorner": b,
            "newSharedCorner": corner,
            "externalEndpointsImmutable": True,
            "objectIdsWidthsNetsLayersImmutable": True,
            "beforeLengthMm": before_length,
            "afterLengthMm": after_length,
            "lengthDeltaMm": after_length - before_length,
        },
        "staticGeometryProof": {
            "selectedRuleMm": RULE_MM,
            "minimumDifferentNetClearanceMm": nearest[0][0],
            "conflictingU1R17PadClearanceMm": conflict_pad_clearance,
            "passesSelectedRule": nearest[0][0] + 1e-7 >= RULE_MM,
            "nearestDifferentNetObjects": [
                {"id": obstacle["id"], "label": obstacle["label"], "net": obstacle["net"], "clearanceMm": distance}
                for distance, obstacle in nearest
            ],
            "scope": "Top-layer straight LINE, VIA, and component-pad copper. ARC/FILL remain native-DRC and refill gates.",
        },
        "candidate": {"path": str(OUTPUT_CANDIDATE.relative_to(ROOT)), "sha256": sha256(OUTPUT_CANDIDATE), "bytes": len(candidate)},
        "applicationGate": {
            "nativeProjectWriteAuthorized": False,
            "requiresNativeDrc": True,
            "requiresFillReclip": True,
            "requiresElectricalConnectivityCheck": True,
            "manufacturingApproved": False,
        },
    }
    atomic_write(OUTPUT_PLAN, (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({
        "plan": str(OUTPUT_PLAN),
        "planSha256": sha256(OUTPUT_PLAN),
        "candidate": str(OUTPUT_CANDIDATE),
        "candidateSha256": sha256(OUTPUT_CANDIDATE),
        "changes": len(changes),
        "minimumClearanceMm": nearest[0][0],
        "u1R17ClearanceMm": conflict_pad_clearance,
        "lengthDeltaMm": after_length - before_length,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
