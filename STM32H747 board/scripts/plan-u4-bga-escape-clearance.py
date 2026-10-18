#!/usr/bin/env python3
"""Plan the ISSI-aligned U4 BGA land and centred escape correction.

The route candidate starts from the offline VIA-0.31/track-0.13 candidate.
It changes only coordinates of five corridor tracks and their ten immediately
connected line segments.  The U4 footprint land reduction (0.4064 to 0.36 mm)
is described as a separate library requirement and is not embedded in the PCB
source because footprint children are library-owned.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
SOURCE = ROOT / "output/candidates/multilayer-route-clearance/via031-track013-candidate-after-via-pilot.epru"
ANALYSIS = ROOT / "output/candidates/multilayer-route-clearance/plan.json"
PAD_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
OUTPUT_PLAN = ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-plan.json"
OUTPUT_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/u4-bga-escape-route-candidate.epru"
MM_PER_MIL = 0.0254
RULE_MM = 0.15200122
U4_PAD_DIAMETER_MM = 0.36
U4_TRACK_WIDTH_MM = 0.13
U4_COMPONENT_ID = "3de4fa6d5f5df65c"
U4_FOOTPRINT_UUID = "a3627e2915fe61c1"


TARGETS = {
    # The target axis is the arithmetic midpoint of the adjacent 0.8-mm BGA
    # rows/columns reconstructed from the authoritative Gerber centres.
    "086d18a33e12fec7": {"axis": "y", "value": 4604.33075},
    "9812f461c9a5af9a": {"axis": "x", "value": 1692.91340},
    "a2a2c1fc45da3946": {"axis": "y", "value": 4415.35435},
    "6f2679c63ef53dfb": {"axis": "y", "value": 4572.83465},
    "ac014b365d587bca": {"axis": "y", "value": 4572.83465},
}


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
        raise ValueError("invalid native record inventory")
    return records


def endpoint(body: dict[str, Any], name: str) -> tuple[float, float]:
    return float(body[name + "X"]), float(body[name + "Y"])


def same_point(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return abs(left[0] - right[0]) <= 1e-6 and abs(left[1] - right[1]) <= 1e-6


def line_copper(body: dict[str, Any]):
    return LineString([
        (float(body["startX"]), float(body["startY"])),
        (float(body["endX"]), float(body["endY"])),
    ]).buffer(float(body["width"]) / 2.0, cap_style=1, join_style=1, resolution=48)


def pad_geometry(entry: dict[str, Any], u4_override: bool):
    center = entry["native_board_center_mil"]
    shapes = []
    for flash in entry["source_flashes"]:
        if flash["layer"] != "F.Cu":
            continue
        params = [float(value) / MM_PER_MIL for value in flash["params_mm"]]
        if u4_override:
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


def main() -> int:
    records = parse_native(SOURCE)
    by_key = {record["key"]: record for record in records}
    analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    pad_audit = json.loads(PAD_AUDIT.read_text(encoding="utf-8"))

    line_bodies = {
        record["header"]["id"]: dict(record["body"])
        for record in records
        if record["header"]["type"] == "LINE"
    }
    after_bodies: dict[str, dict[str, Any]] = {}
    target_proof = []

    for target_id, specification in TARGETS.items():
        target = line_bodies.get(target_id)
        if target is None or int(target["layerId"]) != 1:
            raise ValueError(f"missing top-layer target LINE {target_id}")
        if abs(float(target["width"]) * MM_PER_MIL - U4_TRACK_WIDTH_MM) > 1e-6:
            raise ValueError(f"target is not at reviewed 0.13-mm width {target_id}")
        old_start = endpoint(target, "start")
        old_end = endpoint(target, "end")
        axis = specification["axis"]
        value = float(specification["value"])
        new_target = dict(target)
        if axis == "x":
            if abs(old_start[0] - old_end[0]) > 1e-6:
                raise ValueError(f"expected vertical target {target_id}")
            new_target["startX"] = value
            new_target["endX"] = value
        else:
            if abs(old_start[1] - old_end[1]) > 1e-6:
                raise ValueError(f"expected horizontal target {target_id}")
            new_target["startY"] = value
            new_target["endY"] = value
        new_start = endpoint(new_target, "start")
        new_end = endpoint(new_target, "end")

        contacts = analysis["objects"][target_id]["same_net_endpoint_contacts"]
        line_contacts = [contact for contact in contacts if contact["type"] == "LINE"]
        if len(line_contacts) != 2:
            raise ValueError(f"target does not have exactly two LINE contacts {target_id}")
        changed_neighbors = []
        for contact in line_contacts:
            neighbor_id = contact["id"]
            neighbor = dict(line_bodies[neighbor_id])
            if neighbor["netName"] != target["netName"] or neighbor["layerId"] != target["layerId"]:
                raise ValueError(f"neighbor net/layer mismatch {target_id}/{neighbor_id}")
            point = tuple(float(value) for value in contact["point_mil"])
            replacement = new_start if same_point(point, old_start) else new_end if same_point(point, old_end) else None
            if replacement is None:
                raise ValueError(f"contact point is not a target endpoint {target_id}/{neighbor_id}")
            if same_point(endpoint(neighbor, "start"), point):
                neighbor["startX"], neighbor["startY"] = replacement
            elif same_point(endpoint(neighbor, "end"), point):
                neighbor["endX"], neighbor["endY"] = replacement
            else:
                raise ValueError(f"neighbor endpoint mismatch {target_id}/{neighbor_id}")
            if LineString([endpoint(neighbor, "start"), endpoint(neighbor, "end")]).length < 0.1:
                raise ValueError(f"neighbor would fall below native LINE length floor {neighbor_id}")
            if neighbor_id in after_bodies and after_bodies[neighbor_id] != neighbor:
                raise ValueError(f"neighbor modified inconsistently {neighbor_id}")
            after_bodies[neighbor_id] = neighbor
            changed_neighbors.append(neighbor_id)

        after_bodies[target_id] = new_target
        target_proof.append({
            "targetId": target_id,
            "net": target["netName"],
            "axis": axis,
            "oldAxisMil": old_start[0] if axis == "x" else old_start[1],
            "newAxisMil": value,
            "translationMm": abs(value - (old_start[0] if axis == "x" else old_start[1])) * MM_PER_MIL,
            "oldStartMil": list(old_start),
            "oldEndMil": list(old_end),
            "newStartMil": list(new_start),
            "newEndMil": list(new_end),
            "connectedNeighborIds": sorted(changed_neighbors),
        })

    if len(after_bodies) != 15:
        raise ValueError(f"expected 15 changed LINE bodies, got {len(after_bodies)}")

    changes = []
    candidate_parts = []
    for record in records:
        if record["header"]["type"] != "LINE" or record["header"].get("id") not in after_bodies:
            candidate_parts.append(record["raw"])
            continue
        object_id = record["header"]["id"]
        before = dict(record["body"])
        after = after_bodies[object_id]
        changed_fields = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
        if not changed_fields or any(key not in {"startX", "startY", "endX", "endY"} for key in changed_fields):
            raise ValueError(f"non-coordinate route change {object_id}: {changed_fields}")
        changes.append({
            "type": "LINE",
            "id": object_id,
            "before": before,
            "after": after,
            "changedFields": changed_fields,
        })
        newline = b"\r\n" if record["raw"].endswith(b"\r\n") else b"\n"
        candidate_parts.append(compact(record["header"]) + b"||" + compact(after) + b"|" + newline)

    candidate = b"".join(candidate_parts)
    atomic_write(OUTPUT_CANDIDATE, candidate)

    candidate_records = parse_native(OUTPUT_CANDIDATE)
    candidate_lines = {
        record["header"]["id"]: record["body"]
        for record in candidate_records if record["header"]["type"] == "LINE"
    }
    candidate_vias = [
        record for record in candidate_records if record["header"]["type"] == "VIA"
    ]

    pad_shapes = []
    u4_pad_count = 0
    for entry in pad_audit["matched_component_copper_centres"]:
        override = entry["reference"] == "U4"
        geometry = pad_geometry(entry, override)
        if geometry is None:
            continue
        if override:
            u4_pad_count += 1
        pad_shapes.append({
            "id": entry["component_id"] + entry["pad_id"],
            "label": entry["reference"] + "_" + entry["number"],
            "net": entry["pcb_net"],
            "geometry": geometry,
            "u4": override,
        })
    if u4_pad_count != 90:
        raise ValueError(f"expected 90 U4 pads, got {u4_pad_count}")

    obstacle_lines = []
    for object_id, body in candidate_lines.items():
        if int(body["layerId"]) != 1 or object_id in after_bodies:
            continue
        obstacle_lines.append({
            "id": object_id,
            "label": "LINE:" + object_id,
            "net": body["netName"],
            "geometry": line_copper(body),
        })
    obstacle_vias = []
    for record in candidate_vias:
        body = record["body"]
        obstacle_vias.append({
            "id": record["header"]["id"],
            "label": "VIA:" + record["header"]["id"],
            "net": body["netName"],
            "geometry": Point(float(body["centerX"]), float(body["centerY"])).buffer(
                float(body["viaDiameter"]) / 2.0, resolution=64
            ),
        })

    per_target_clearance = []
    for target_id in TARGETS:
        route_ids = {target_id}
        proof = next(item for item in target_proof if item["targetId"] == target_id)
        route_ids.update(proof["connectedNeighborIds"])
        route_bodies = [candidate_lines[object_id] for object_id in route_ids]
        route_geometry = unary_union([line_copper(body) for body in route_bodies])
        net = route_bodies[0]["netName"]
        candidates = []
        for obstacle in pad_shapes + obstacle_lines + obstacle_vias:
            if obstacle["net"] and obstacle["net"] == net:
                continue
            distance_mm = route_geometry.distance(obstacle["geometry"]) * MM_PER_MIL
            candidates.append((distance_mm, obstacle))
        nearest = sorted(candidates, key=lambda item: (item[0], item[1]["label"]))[:8]
        per_target_clearance.append({
            "targetId": target_id,
            "net": net,
            "routeIds": sorted(route_ids),
            "minimumDifferentNetClearanceMm": nearest[0][0],
            "passesSelectedRule": nearest[0][0] + 1e-7 >= RULE_MM,
            "nearestDifferentNetObjects": [
                {"id": obstacle["id"], "label": obstacle["label"], "net": obstacle["net"], "clearanceMm": distance}
                for distance, obstacle in nearest
            ],
        })

    u4_error_rows = []
    for row in analysis["all_rows"]:
        pad_ids = [object_id for object_id in row["ids"] if object_id.startswith(U4_COMPONENT_ID)]
        line_ids = [object_id for object_id in row["ids"] if object_id in candidate_lines]
        if row["pair"] != "SMD Pad to Track" or len(pad_ids) != 1 or len(line_ids) != 1:
            continue
        pad = next(item for item in pad_shapes if item["id"] == pad_ids[0])
        line = candidate_lines[line_ids[0]]
        distance_mm = line_copper(line).distance(pad["geometry"]) * MM_PER_MIL
        u4_error_rows.append({
            "globalIndex": row["global_index"],
            "lineId": line_ids[0],
            "padId": pad_ids[0],
            "pad": pad["label"],
            "clearanceMm": distance_mm,
            "passesSelectedRule": distance_mm + 1e-7 >= RULE_MM,
        })

    plan = {
        "schema": "stm32h747-u4-bga-escape-clearance-plan-v1",
        "status": "review-only-not-applied",
        "pcbUuid": "0ac2a19168000d8e",
        "source": {"path": str(SOURCE.relative_to(ROOT)), "sha256": sha256(SOURCE)},
        "officialComponentEvidence": {
            "part": "IS42S32160F-6BLI",
            "package": "90-ball TF-BGA, 8x13 mm, 0.8-mm pitch",
            "nominalBallDiameterMm": 0.45,
            "datasheet": "https://www.issi.com/WW/pdf/42-45R-S-32160F.pdf",
            "layoutGuide": "https://www.issi.com/WW/pdf/appnotes/dram/AN42S01.AN.pdf",
            "layoutGuideSummary": "Follow IPC-7351; BGA land is usually about 80% of nominal ball. General minimum trace width is 0.13 mm.",
        },
        "footprintRequirement": {
            "componentId": U4_COMPONENT_ID,
            "footprintUuid": U4_FOOTPRINT_UUID,
            "pads": 90,
            "beforeCopperDiameterMm": 0.4064,
            "afterCopperDiameterMm": U4_PAD_DIAMETER_MM,
            "centresNumbersIdsNetsAndNonCopperFieldsImmutable": True,
            "notEmbeddedInPcbCandidate": True,
        },
        "routeRequirement": {
            "trackWidthMm": U4_TRACK_WIDTH_MM,
            "changedLineRecords": len(changes),
            "changedTargets": len(TARGETS),
            "onlyEndpointCoordinatesChangeFromVia031Track013Source": True,
        },
        "changes": changes,
        "targetProof": target_proof,
        "staticGeometryProof": {
            "u4OriginalDrcRows": len(u4_error_rows),
            "u4RowsPassingAfterPadAndRoutePlan": sum(row["passesSelectedRule"] for row in u4_error_rows),
            "u4RowsFailing": [row for row in u4_error_rows if not row["passesSelectedRule"]],
            "perTargetNearestClearance": per_target_clearance,
            "allChangedRouteGroupsPassLineViaPadCheck": all(item["passesSelectedRule"] for item in per_target_clearance),
            "scope": "Top-layer LINE/VIA and component-pad copper; copper FILLs and ARC curves require native DRC/reclip verification.",
        },
        "candidate": {
            "path": str(OUTPUT_CANDIDATE.relative_to(ROOT)),
            "sha256": sha256(OUTPUT_CANDIDATE),
            "bytes": len(candidate),
        },
        "applicationGate": {
            "nativeProjectWriteAuthorized": False,
            "requiresFullU4LibrarySourceUpdate": True,
            "requiresNativeDrc": True,
            "requiresFillReclip": True,
            "requiresImpedanceAndLengthReview": True,
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
        "u4Rows": len(u4_error_rows),
        "u4RowsPassing": plan["staticGeometryProof"]["u4RowsPassingAfterPadAndRoutePlan"],
        "routeGroupsPassing": plan["staticGeometryProof"]["allChangedRouteGroupsPassLineViaPadCheck"],
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
