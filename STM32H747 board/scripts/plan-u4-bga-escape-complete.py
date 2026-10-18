#!/usr/bin/env python3
"""Consolidate U4 land/escape centring and local power-neckdown geometry.

The emitted PCB candidate is based on the reviewed VIA-0.31/track-0.13
candidate.  It contains only endpoint-coordinate changes for the five centred
escape corridors and width-only reductions for twelve nearby copper stubs.
The 90-pad U4 land update remains a separately guarded footprint operation.
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
ROUTE_PLAN = ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-plan.json"
ANALYSIS = ROOT / "output/candidates/multilayer-route-clearance/plan.json"
PAD_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e-via031_track013.json"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-complete-plan.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-complete-candidate.epru"
MM_PER_MIL = 0.0254
RULE_MM = 0.15200122
STATIC_TARGET_MM = 0.1549
U4_COMPONENT_ID = "3de4fa6d5f5df65c"
U4_PAD_DIAMETER_MM = 0.36


# These widths are the 0.001-mm-floored result of the local static optimizer.
# They retain >=0.13 mm and make the five changed route groups at least
# 0.1549 mm from every different-net straight track considered here.
NECKDOWN_WIDTH_MM = {
    "08bab84c49139f9e": 0.360,
    "89b9b83ec57e92b3": 0.360,
    "8be795786edc5cae": 0.360,
    "950b2622ec5d71db": 0.360,
    "a4d99e5cae33d8f4": 0.340,
    "ba46ca6a0cf01552": 0.360,
    "bba52bee3ce149e6": 0.370,
    "c86ba01d59c2f57f": 0.360,
    "daf9f8125bbefc34": 0.360,
    "efa8ec8af5af8c4a": 0.360,
    "f56ae03bce7f86e0": 0.139,
    "fa8a5d0f113c3ada": 0.360,
}


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
    override = entry["reference"] == "U4"
    shapes = []
    for flash in entry["source_flashes"]:
        if flash["layer"] != "F.Cu":
            continue
        params = [float(value) / MM_PER_MIL for value in flash["params_mm"]]
        if override:
            params = [U4_PAD_DIAMETER_MM / MM_PER_MIL]
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


def line_length(body: dict[str, Any]) -> float:
    return LineString([
        (float(body["startX"]), float(body["startY"])),
        (float(body["endX"]), float(body["endY"])),
    ]).length * MM_PER_MIL


def main() -> int:
    source_records = parse_native(SOURCE)
    source_by_key = {record["key"]: record for record in source_records}
    route_plan = json.loads(ROUTE_PLAN.read_text(encoding="utf-8"))
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    pad_audit = json.loads(PAD_AUDIT.read_text(encoding="utf-8"))
    current_drc = json.loads(DRC.read_text(encoding="utf-8"))

    desired_bodies: dict[str, dict[str, Any]] = {}
    for change in route_plan["changes"]:
        if change["type"] != "LINE":
            raise ValueError("route plan contains a non-LINE change")
        source = source_by_key.get(("LINE", change["id"]))
        if source is None:
            raise ValueError(f"route baseline changed {change['id']}")
        # The native 3.2 serializer rounds an applied 0.13-mm width from
        # 5.11811 mil to 5.1181 mil.  Rebase coordinate-only escape edits on
        # the reopened body so the plan never rewrites that normalization or
        # any other live field.
        before = change["before"]
        current = source["body"]
        baseline_differences = {
            key for key in set(before) | set(current)
            if before.get(key) != current.get(key)
        }
        if baseline_differences - {"width"}:
            raise ValueError(f"route baseline changed {change['id']}: {sorted(baseline_differences)}")
        if "width" in baseline_differences and abs(float(before["width"]) - float(current["width"])) > 0.00002:
            raise ValueError(f"route width changed beyond native rounding {change['id']}")
        desired = dict(current)
        changed_coordinate_fields = {
            key for key in set(before) | set(change["after"])
            if before.get(key) != change["after"].get(key)
        }
        if not changed_coordinate_fields or changed_coordinate_fields - {"startX", "startY", "endX", "endY"}:
            raise ValueError(f"unexpected route edit fields {change['id']}: {sorted(changed_coordinate_fields)}")
        for key in changed_coordinate_fields:
            desired[key] = change["after"][key]
        desired_bodies[change["id"]] = desired

    neckdown_proof = []
    for object_id, target_width_mm in sorted(NECKDOWN_WIDTH_MM.items()):
        source = source_by_key.get(("LINE", object_id))
        if source is None:
            raise ValueError(f"missing neckdown LINE {object_id}")
        before = source["body"]
        after = dict(before)
        after["width"] = round(target_width_mm / MM_PER_MIL, 6)
        if after["width"] >= float(before["width"]) or target_width_mm < 0.13:
            raise ValueError(f"invalid neckdown width {object_id}")
        if object_id in desired_bodies:
            raise ValueError(f"neckdown overlaps a route-coordinate record {object_id}")
        desired_bodies[object_id] = after
        neckdown_proof.append({
            "id": object_id,
            "net": before["netName"],
            "layerId": before["layerId"],
            "lengthMm": line_length(before),
            "beforeWidthMm": float(before["width"]) * MM_PER_MIL,
            "afterWidthMm": float(after["width"]) * MM_PER_MIL,
            "centrelineEndpointsNetLayerImmutable": True,
        })

    if len(desired_bodies) != 27:
        raise ValueError(f"expected 27 changed LINEs, got {len(desired_bodies)}")

    changes = []
    candidate_parts = []
    for record in source_records:
        object_id = record["header"].get("id")
        if record["header"]["type"] != "LINE" or object_id not in desired_bodies:
            candidate_parts.append(record["raw"])
            continue
        before = dict(record["body"])
        after = desired_bodies[object_id]
        changed_fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        allowed = {"width"} if object_id in NECKDOWN_WIDTH_MM else {"startX", "startY", "endX", "endY"}
        if not changed_fields or any(field not in allowed for field in changed_fields):
            raise ValueError(f"unexpected change fields {object_id}: {changed_fields}")
        changes.append({"type": "LINE", "id": object_id, "before": before, "after": after, "changedFields": changed_fields})
        newline = b"\r\n" if record["raw"].endswith(b"\r\n") else b"\n"
        candidate_parts.append(compact(record["header"]) + b"||" + compact(after) + b"|" + newline)

    candidate = b"".join(candidate_parts)
    atomic_write(OUTPUT_CANDIDATE, candidate)
    candidate_records = parse_native(OUTPUT_CANDIDATE)
    candidate_lines = {
        record["header"]["id"]: record["body"]
        for record in candidate_records if record["header"]["type"] == "LINE"
    }
    candidate_vias = [record for record in candidate_records if record["header"]["type"] == "VIA"]

    pad_shapes = []
    u4_pads = 0
    for entry in pad_audit["matched_component_copper_centres"]:
        geometry = pad_geometry(entry)
        if geometry is None:
            continue
        if entry["reference"] == "U4":
            u4_pads += 1
        pad_shapes.append({
            "id": entry["component_id"] + entry["pad_id"],
            "label": entry["reference"] + "_" + entry["number"],
            "net": entry["pcb_net"],
            "geometry": geometry,
        })
    if u4_pads != 90:
        raise ValueError(f"expected 90 U4 pads, got {u4_pads}")

    via_shapes = [{
        "id": record["header"]["id"],
        "label": "VIA:" + record["header"]["id"],
        "net": record["body"]["netName"],
        "geometry": Point(float(record["body"]["centerX"]), float(record["body"]["centerY"])).buffer(
            float(record["body"]["viaDiameter"]) / 2.0, resolution=64
        ),
    } for record in candidate_vias]

    route_groups = []
    for proof in route_plan["targetProof"]:
        route_ids = {proof["targetId"], *proof["connectedNeighborIds"]}
        route_bodies = [candidate_lines[object_id] for object_id in route_ids]
        net = route_bodies[0]["netName"]
        route_geometry = unary_union([line_geometry(body) for body in route_bodies])
        obstacles = []
        for object_id, body in candidate_lines.items():
            if int(body["layerId"]) != 1 or object_id in route_ids or body["netName"] == net:
                continue
            obstacles.append({"id": object_id, "label": "LINE:" + object_id, "net": body["netName"], "geometry": line_geometry(body)})
        candidates = []
        for obstacle in pad_shapes + via_shapes + obstacles:
            if obstacle["net"] and obstacle["net"] == net:
                continue
            candidates.append((route_geometry.distance(obstacle["geometry"]) * MM_PER_MIL, obstacle))
        nearest = sorted(candidates, key=lambda value: (value[0], value[1]["label"]))[:12]
        before_length = sum(line_length(change["before"]) for change in route_plan["changes"] if change["id"] in route_ids)
        after_length = sum(line_length(candidate_lines[object_id]) for object_id in route_ids)
        route_groups.append({
            "targetId": proof["targetId"],
            "net": net,
            "routeIds": sorted(route_ids),
            "beforeLengthMm": before_length,
            "afterLengthMm": after_length,
            "lengthDeltaMm": after_length - before_length,
            "minimumDifferentNetClearanceMm": nearest[0][0],
            "passesSelectedRule": nearest[0][0] + 1e-7 >= RULE_MM,
            "passesStaticTarget": nearest[0][0] + 1e-7 >= STATIC_TARGET_MM,
            "nearestDifferentNetObjects": [
                {"id": obstacle["id"], "label": obstacle["label"], "net": obstacle["net"], "clearanceMm": distance}
                for distance, obstacle in nearest
            ],
        })

    u4_rows = []
    pad_by_id = {entry["id"]: entry for entry in pad_shapes}
    for row in analysis["all_rows"]:
        pad_ids = [object_id for object_id in row["ids"] if object_id.startswith(U4_COMPONENT_ID)]
        line_ids = [object_id for object_id in row["ids"] if object_id in candidate_lines]
        if row["pair"] != "SMD Pad to Track" or len(pad_ids) != 1 or len(line_ids) != 1:
            continue
        pad = pad_by_id[pad_ids[0]]
        distance = line_geometry(candidate_lines[line_ids[0]]).distance(pad["geometry"]) * MM_PER_MIL
        u4_rows.append({
            "globalIndex": row["global_index"],
            "lineId": line_ids[0],
            "padId": pad_ids[0],
            "clearanceMm": distance,
            "passesSelectedRule": distance + 1e-7 >= RULE_MM,
        })

    if not all(group["passesSelectedRule"] for group in route_groups):
        raise ValueError("complete U4 route group still violates selected rule in static geometry")
    if not all(row["passesSelectedRule"] for row in u4_rows):
        raise ValueError("complete U4 plan still has a known pad/track violation")

    # Re-evaluate the actual post-width native DRC rows as well.  The runtime
    # merged two collinear A12 records into one new ID, so this current-row
    # proof is deliberately independent of the pre-merge analysis inventory.
    current_u4_rows = []
    for top in current_drc["details"]:
        for category in top["list"]:
            if category["name"] != "SMD Pad to Track":
                continue
            for row in category["list"]:
                line_ids = [object_id for object_id in row["objs"] if object_id in candidate_lines]
                pad_ids = [object_id for object_id in row["objs"] if object_id in pad_by_id and object_id.startswith(U4_COMPONENT_ID)]
                if len(line_ids) != 1 or len(pad_ids) != 1:
                    continue
                distance = line_geometry(candidate_lines[line_ids[0]]).distance(pad_by_id[pad_ids[0]]["geometry"]) * MM_PER_MIL
                current_u4_rows.append({
                    "globalIndex": row["globalIndex"],
                    "lineId": line_ids[0],
                    "padId": pad_ids[0],
                    "clearanceMm": distance,
                    "passesSelectedRule": distance + 1e-7 >= RULE_MM,
                })
    if len(current_u4_rows) != 30 or not all(row["passesSelectedRule"] for row in current_u4_rows):
        raise ValueError("current post-width native U4 DRC rows did not all clear statically")

    plan = {
        "schema": "stm32h747-u4-bga-escape-complete-plan-v1",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "nativeDrcEvidence": {"path": str(DRC.relative_to(ROOT)), "sha256": sha256(DRC)},
        "officialEvidence": route_plan["officialComponentEvidence"],
        "footprintRequirement": route_plan["footprintRequirement"],
        "changes": changes,
        "changeCounts": {"routeCoordinateLines": 15, "localNeckdownLines": 12, "total": len(changes)},
        "localNeckdownProof": neckdown_proof,
        "staticGeometryProof": {
            "selectedRuleMm": RULE_MM,
            "staticTargetMm": STATIC_TARGET_MM,
            "u4OriginalPadTrackRows": len(u4_rows),
            "u4RowsPassing": sum(row["passesSelectedRule"] for row in u4_rows),
            "currentNativeU4PadTrackRows": len(current_u4_rows),
            "currentNativeU4RowsPassing": sum(row["passesSelectedRule"] for row in current_u4_rows),
            "minimumCurrentNativeU4ClearanceMm": min(row["clearanceMm"] for row in current_u4_rows),
            "routeGroups": route_groups,
            "allRouteGroupsPassRule": all(group["passesSelectedRule"] for group in route_groups),
            "allRouteGroupsPassStaticTarget": all(group["passesStaticTarget"] for group in route_groups),
            "scope": "All top-layer straight LINE, VIA, and component-pad copper against the five changed route groups. ARC and FILL shapes remain native-DRC/reclip gates.",
        },
        "candidate": {"path": str(OUTPUT_CANDIDATE.relative_to(ROOT)), "sha256": sha256(OUTPUT_CANDIDATE), "bytes": len(candidate)},
        "applicationGate": {
            "nativeProjectWriteAuthorized": False,
            "requiresFullU4LibraryPadUpdate": True,
            "requiresCurrentCapacityReviewForTwelveNeckdowns": True,
            "requiresImpedanceAndLengthReview": True,
            "requiresNativeDrc": True,
            "requiresFillReclip": True,
            "manufacturingApproved": False,
        },
        "limitations": [
            "The local power/GND neckdowns are geometry-feasible but not a power-integrity approval.",
            "The 0.13-mm SDRAM routing and length deltas require impedance and timing review against the actual stack-up.",
            "The fixed 6-mil native rule is weaker than ISSI's general inter-signal-group spacing guidance; passing native DRC is not SI approval.",
        ],
    }
    atomic_write(OUTPUT_PLAN, (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps({
        "plan": str(OUTPUT_PLAN),
        "planSha256": sha256(OUTPUT_PLAN),
        "candidate": str(OUTPUT_CANDIDATE),
        "candidateSha256": sha256(OUTPUT_CANDIDATE),
        "changes": plan["changeCounts"],
        "u4RowsPassing": plan["staticGeometryProof"]["u4RowsPassing"],
        "routeGroupsPassRule": plan["staticGeometryProof"]["allRouteGroupsPassRule"],
        "routeGroupsPassStaticTarget": plan["staticGeometryProof"]["allRouteGroupsPassStaticTarget"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
