#!/usr/bin/env python3
"""Build a guarded two-line reroute for the C23_2 clearance error.

The route is rebased on the native board reopened after the VIA-0.31 and
track-0.13 pass.  It moves one shared junction 0.04 mm normal to the old
diagonal, and necks the connected vertical segment from 0.15 to 0.13 mm.
No object, net, layer, or external endpoint is added or removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
SOURCE = ROOT / "output/validation/native-multilayer-via031_track013-reopened.epru"
PAD_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-via031_track013.json"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/c23-reroute-plan.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/c23-reroute-candidate.epru"
MM_PER_MIL = 0.0254
RULE_MM = 0.15200122
STATIC_TARGET_MM = 0.1549
TARGET_ID = "7b19bc3334960821"
UPSTREAM_ID = "2dcca472846cea0c"
CONFLICT_PAD_ID = "2530295bf058947de2"
NEW_CORNER = (2026.445546, 3661.546654)
NEW_WIDTH_MIL = 5.1181


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
    ]).buffer(float(body["width"]) / 2.0, cap_style=1, join_style=1, resolution=64)


def line_length(body: dict[str, Any]) -> float:
    return LineString([
        (float(body["startX"]), float(body["startY"])),
        (float(body["endX"]), float(body["endY"])),
    ]).length * MM_PER_MIL


def pad_geometry(entry: dict[str, Any]):
    center = entry["native_board_center_mil"]
    shapes = []
    for flash in entry["source_flashes"]:
        if flash["layer"] != "B.Cu":
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
        elif flash["shape"] == "O" and len(params) >= 2:
            width, height = params[:2]
            if width >= height:
                half_span = (width - height) / 2.0
                shapes.append(LineString([
                    (center[0] - half_span, center[1]),
                    (center[0] + half_span, center[1]),
                ]).buffer(height / 2.0, cap_style=1, resolution=64))
            else:
                half_span = (height - width) / 2.0
                shapes.append(LineString([
                    (center[0], center[1] - half_span),
                    (center[0], center[1] + half_span),
                ]).buffer(width / 2.0, cap_style=1, resolution=64))
        elif flash["shape"] == "RoundRect" and len(params) >= 9:
            # Gerber macro parameters contain corner coordinates after the
            # first rounding-radius field and before the final rotation.
            points = [
                (center[0] + params[index], center[1] + params[index + 1])
                for index in range(1, len(params) - 1, 2)
            ]
            shapes.append(Polygon(points).convex_hull)
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
    if TARGET_ID not in lines or UPSTREAM_ID not in lines:
        raise ValueError("required C23 route records are absent")

    before_target = dict(lines[TARGET_ID])
    before_upstream = dict(lines[UPSTREAM_ID])
    net = before_target["netName"]
    if before_upstream["netName"].casefold() != net.casefold() or int(before_target["layerId"]) != 2 or int(before_upstream["layerId"]) != 2:
        raise ValueError("route net/layer mismatch")
    old_corner = endpoint(before_target, "start")
    if endpoint(before_upstream, "end") != old_corner:
        raise ValueError("route records do not share the expected corner")
    external_start = endpoint(before_upstream, "start")
    external_end = endpoint(before_target, "end")
    if abs(float(before_target["width"]) - NEW_WIDTH_MIL) > 0.00002:
        raise ValueError("target is not the reopened 0.13-mm width")
    if abs(float(before_upstream["width"]) * MM_PER_MIL - 0.15) > 0.00001:
        raise ValueError("upstream width is not the expected 0.15 mm")

    after_target = dict(before_target)
    after_target["startX"], after_target["startY"] = NEW_CORNER
    after_upstream = dict(before_upstream)
    after_upstream["endX"], after_upstream["endY"] = NEW_CORNER
    after_upstream["width"] = NEW_WIDTH_MIL
    desired = {TARGET_ID: after_target, UPSTREAM_ID: after_upstream}

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
        allowed = {"startX", "startY"} if object_id == TARGET_ID else {"endX", "endY", "width"}
        if not changed_fields or set(changed_fields) - allowed:
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
    if exact_differences != [("LINE", UPSTREAM_ID), ("LINE", TARGET_ID)]:
        raise ValueError(f"unexpected candidate differences: {exact_differences}")

    route_ids = {TARGET_ID, UPSTREAM_ID}
    candidate_lines = {
        record["header"]["id"]: record["body"]
        for record in candidate_records if record["header"].get("type") == "LINE"
    }
    before_route = unary_union([line_geometry(before_target), line_geometry(before_upstream)])
    after_route = unary_union([line_geometry(candidate_lines[object_id]) for object_id in route_ids])
    obstacles = []
    for object_id, body in candidate_lines.items():
        if int(body["layerId"]) != 2 or object_id in route_ids or body["netName"].casefold() == net.casefold():
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
    for entry in pad_audit["matched_component_copper_centres"]:
        geometry = pad_geometry(entry)
        if geometry is None:
            continue
        pad_net = entry["pcb_net"]
        if pad_net and pad_net.casefold() == net.casefold():
            continue
        obstacles.append({
            "id": entry["component_id"] + entry["pad_id"],
            "label": entry["reference"] + "_" + entry["number"],
            "net": pad_net,
            "geometry": geometry,
        })
    if len(obstacles) != 2387:
        raise ValueError(f"unexpected B.Cu obstacle inventory: {len(obstacles)}")

    distances = []
    for obstacle in obstacles:
        distances.append({
            "id": obstacle["id"],
            "label": obstacle["label"],
            "net": obstacle["net"],
            "beforeClearanceMm": before_route.distance(obstacle["geometry"]) * MM_PER_MIL,
            "afterClearanceMm": after_route.distance(obstacle["geometry"]) * MM_PER_MIL,
        })
    nearest = sorted(distances, key=lambda item: (item["afterClearanceMm"], item["label"]))
    conflict = next(item for item in distances if item["id"] == CONFLICT_PAD_ID)
    newly_below_rule = [
        item for item in distances
        if item["afterClearanceMm"] + 1e-7 < RULE_MM and item["beforeClearanceMm"] + 1e-7 >= RULE_MM
    ]
    remaining_below_rule = [item for item in distances if item["afterClearanceMm"] + 1e-7 < RULE_MM]
    if nearest[0]["afterClearanceMm"] + 1e-7 < STATIC_TARGET_MM or conflict["afterClearanceMm"] + 1e-7 < STATIC_TARGET_MM:
        raise ValueError("C23 reroute does not meet the static target")
    if newly_below_rule or remaining_below_rule:
        raise ValueError("C23 reroute creates or retains a sub-rule obstacle")

    drc = json.loads(DRC.read_text(encoding="utf-8"))
    matching_rows = []
    for top in drc["details"]:
        for category in top["list"]:
            for row in category["list"]:
                if set(row.get("objs", [])) == {TARGET_ID, CONFLICT_PAD_ID}:
                    matching_rows.append({"category": category["name"], "globalIndex": row["globalIndex"], "objects": row["objs"]})
    if len(matching_rows) != 1:
        raise ValueError(f"expected one native C23 DRC row, got {matching_rows}")

    before_length = line_length(before_target) + line_length(before_upstream)
    after_length = line_length(after_target) + line_length(after_upstream)
    shift_mm = LineString([old_corner, NEW_CORNER]).length * MM_PER_MIL
    plan = {
        "schema": "stm32h747-c23-clearance-plan-v1",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "nativeDrcEvidence": {"path": str(DRC.relative_to(ROOT)), "sha256": sha256(DRC), "matchingRows": matching_rows},
        "changes": changes,
        "changeCounts": {"LINE": 2, "coordinateLines": 2, "widthLines": 1, "total": 2},
        "topologyProof": {
            "net": net,
            "layerId": 2,
            "externalStart": external_start,
            "externalEnd": external_end,
            "oldSharedCorner": old_corner,
            "newSharedCorner": NEW_CORNER,
            "sharedCornerShiftMm": shift_mm,
            "externalEndpointsImmutable": True,
            "objectIdsNetsLayersImmutable": True,
            "beforeLengthMm": before_length,
            "afterLengthMm": after_length,
            "lengthDeltaMm": after_length - before_length,
            "minimumWidthMm": NEW_WIDTH_MIL * MM_PER_MIL,
        },
        "staticGeometryProof": {
            "selectedRuleMm": RULE_MM,
            "staticTargetMm": STATIC_TARGET_MM,
            "differentNetOrUnknownBCuObstacleCount": len(obstacles),
            "minimumBeforeClearanceMm": min(item["beforeClearanceMm"] for item in distances),
            "minimumAfterClearanceMm": nearest[0]["afterClearanceMm"],
            "c23PadBeforeClearanceMm": conflict["beforeClearanceMm"],
            "c23PadAfterClearanceMm": conflict["afterClearanceMm"],
            "newBelowRuleCount": len(newly_below_rule),
            "remainingBelowRuleCount": len(remaining_below_rule),
            "nearestDifferentNetObjects": nearest[:20],
            "scope": "All bottom-layer straight LINE, VIA, and component-pad copper. ARC/FILL remain native-DRC and refill gates.",
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
        "minimumAfterClearanceMm": nearest[0]["afterClearanceMm"],
        "c23AfterClearanceMm": conflict["afterClearanceMm"],
        "lengthDeltaMm": after_length - before_length,
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
