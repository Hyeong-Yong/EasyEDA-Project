#!/usr/bin/env python3
"""Build a read-only clearance-repair plan for non-FILL PCB objects.

The script deliberately does not alter an EasyEDA project.  It joins the
final native DRC report to the reopened native PCB source and the persisted
footprint documents, then evaluates a copper-diameter-only VIA candidate and
describes the remaining local track/outline work.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_DRC = ROOT / "output/validation/native-pcb-final-reconstruction-20261015-drc.json"
DEFAULT_SOURCE = ROOT / "output/validation/native-final-pcb-final_reconstruction-reopened.epru"
DEFAULT_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_final_reconstruction_20261015.epro2"
DEFAULT_PAD_AUDIT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"
DEFAULT_OUTPUT = ROOT / "output/candidates/multilayer-route-clearance/plan.json"
DEFAULT_VIA_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/via-diameter-candidate.epru"
DEFAULT_VIA_PLAN = ROOT / "output/candidates/multilayer-route-clearance/via-only-plan.json"
DEFAULT_VIA_PILOT = ROOT / "output/candidates/multilayer-route-clearance/via-pilot-one.json"
DEFAULT_COMBINED_PLAN = ROOT / "output/candidates/multilayer-route-clearance/via-track-width-plan.json"
DEFAULT_COMBINED_CANDIDATE = ROOT / "output/candidates/multilayer-route-clearance/via-track-width-candidate.epru"
MM_PER_MIL = 0.0254
DISPLAY_MIL_PER_RAW_UNIT = 10.0
TARGET_PAIRS = frozenset({
    "Track to Track",
    "Track to Via",
    "SMD Pad to Track",
    "SMD Pad to Via",
    "Via to Via",
    "Board Outline to TH Pad",
})
VIA_PAIRS = frozenset({"Track to Via", "SMD Pad to Via", "Via to Via"})
TRACK_PAIRS = frozenset({"Track to Track", "SMD Pad to Track"})
NET_REPAIR_MARGIN_MM = 0.001
COMBINED_MARGIN_MM = 0.003
MIN_TRACK_WIDTH_MM = 0.12


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


NATIVE = load_module(
    "multilayer_clearance_native_helpers",
    ROOT / "scripts/audit-native-pcb-staging-checkpoint.py",
)
PROJECT = load_module(
    "multilayer_clearance_project_helpers",
    ROOT / "scripts/audit-pcb-replacement-safety.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must remain below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def atomic_write(path: Path, payload: bytes) -> None:
    target = safe_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def iter_errors(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield value
            return
        for child in value.get("list", []):
            yield from iter_errors(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_errors(child)


def net_from_suffix(value: Any) -> str:
    text = str(value or "")
    return text[1:text.index("):")] if text.startswith("(") and "):" in text else ""


def qpoint(x: float, y: float, quantum: float = 0.001) -> tuple[int, int]:
    return round(x / quantum), round(y / quantum)


def endpoint_rows(record: Any) -> list[tuple[float, float]]:
    body = record.body
    if record.kind in {"LINE", "ARC"}:
        return [
            (float(body["startX"]), float(body["startY"])),
            (float(body["endX"]), float(body["endY"])),
        ]
    if record.kind == "VIA":
        return [(float(body["centerX"]), float(body["centerY"]))]
    return []


def record_geometry(record: Any) -> dict[str, Any]:
    body = record.body
    common = {
        "id": record.record_id,
        "type": record.kind,
        "net": str(body.get("netName") or ""),
        "layer_id": body.get("layerId"),
    }
    if record.kind == "LINE":
        start = [float(body["startX"]), float(body["startY"])]
        end = [float(body["endX"]), float(body["endY"])]
        common.update({
            "start_mil": start,
            "end_mil": end,
            "width_mil": float(body["width"]),
            "length_mil": math.dist(start, end),
        })
    elif record.kind == "ARC":
        common.update({
            "start_mil": [float(body["startX"]), float(body["startY"])],
            "end_mil": [float(body["endX"]), float(body["endY"])],
            "angle_deg": float(body["angle"]),
            "width_mil": float(body["width"]),
        })
    elif record.kind == "VIA":
        common.update({
            "center_mil": [float(body["centerX"]), float(body["centerY"])],
            "diameter_mil": float(body["viaDiameter"]),
            "hole_mil": float(body["holeDiameter"]),
            "unused_inner_layers": list(body.get("unusedInnerLayers") or []),
        })
    elif record.kind == "POLY":
        common.update({
            "width_mil": float(body.get("width") or 0),
            "path": body.get("path"),
            "poly_type": body.get("polyType"),
        })
    return common


def point_segment_closest(
    point: Sequence[float], start: Sequence[float], end: Sequence[float]
) -> tuple[list[float], float]:
    px, py = map(float, point)
    x1, y1 = map(float, start)
    x2, y2 = map(float, end)
    dx, dy = x2 - x1, y2 - y1
    denom = dx * dx + dy * dy
    if denom == 0:
        return [x1, y1], math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / denom))
    closest = [x1 + t * dx, y1 + t * dy]
    return closest, math.hypot(px - closest[0], py - closest[1])


def connected_components(edges: list[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        graph[left].add(right)
        graph[right].add(left)
    result = []
    seen: set[str] = set()
    for seed in sorted(graph):
        if seed in seen:
            continue
        queue = deque([seed])
        component = []
        seen.add(seed)
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbor in sorted(graph[current]):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        result.append(sorted(component))
    return sorted(result, key=lambda values: (-len(values), values))


def pad_maps(
    audit: dict[str, Any], checkpoint: Path
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    documents, _project2, _entries = PROJECT.parse_documents(checkpoint)
    footprint_pads: dict[tuple[str, str], dict[str, Any]] = {}
    for document in documents:
        uuid = str(document["uuid"])
        for record in document["records"]:
            if record.kind == "PAD":
                footprint_pads[(uuid, record.record_id)] = dict(record.body)
    result: dict[str, dict[str, Any]] = {}
    rows = list(audit.get("matched_component_copper_centres", []))
    rows.extend(audit.get("drill_derived_extra_footprint_pads", []))
    for row in rows:
        component_id = str(row["component_id"])
        pad_id = str(row["pad_id"])
        native_id = component_id + pad_id
        center = row.get("native_board_center_mil") or row.get("board_center_mil")
        footprint_uuid = str(row["footprint_uuid"])
        result[native_id] = {
            "id": native_id,
            "type": "PAD",
            "reference": row["reference"],
            "number": str(row.get("number") or ""),
            "component_id": component_id,
            "pad_id": pad_id,
            "footprint_uuid": footprint_uuid,
            "center_mil": [float(center[0]), float(center[1])],
            "net": str(row.get("pcb_net") or ""),
            "source_flashes": row.get("source_flashes", []),
            "plated": row.get("plated"),
            "hole": row.get("hole"),
            "footprint_body": footprint_pads.get((footprint_uuid, pad_id)),
        }
    return result, footprint_pads


def via_target_mm(hole_mm: float, profile: str) -> float:
    rounded = round(hole_mm, 3)
    if profile == "preferred":
        explicit = {0.2: 0.35, 0.25: 0.40, 0.3: 0.48, 0.4: 0.55, 0.5: 0.65}
    elif profile == "clearance":
        explicit = {0.2: 0.34, 0.25: 0.40, 0.3: 0.48, 0.4: 0.55, 0.5: 0.65}
    else:
        raise ValueError(profile)
    return explicit.get(rounded, rounded + 0.15)


def analyze(args: argparse.Namespace) -> tuple[dict[str, Any], bytes | None, bytes | None]:
    for path in (args.drc, args.source, args.checkpoint, args.pad_audit):
        if not path.is_file():
            raise FileNotFoundError(path)

    drc = json.loads(args.drc.read_text(encoding="utf-8-sig"))
    audit = json.loads(args.pad_audit.read_text(encoding="utf-8-sig"))
    records = NATIVE.parse_source(args.source)
    source_by_id = {record.record_id: record for record in records if record.record_id}
    pads, _footprint_pads = pad_maps(audit, args.checkpoint)

    endpoint_index: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.kind not in {"LINE", "ARC", "VIA"}:
            continue
        for endpoint_number, (x, y) in enumerate(endpoint_rows(record)):
            endpoint_index[qpoint(x, y)].append({
                "id": record.record_id,
                "type": record.kind,
                "net": str(record.body.get("netName") or ""),
                "layer_id": record.body.get("layerId"),
                "endpoint": endpoint_number,
                "point_mil": [x, y],
            })
    for pad in pads.values():
        x, y = pad["center_mil"]
        endpoint_index[qpoint(x, y)].append({
            "id": pad["id"],
            "type": "PAD",
            "net": pad["net"],
            "layer_id": None,
            "endpoint": 0,
            "point_mil": [x, y],
            "reference": pad["reference"],
            "number": pad["number"],
        })

    raw_rows = []
    for item in iter_errors(drc.get("details", [])):
        if item.get("errorType") != "Clearance Error":
            continue
        pair = str(item.get("errorObjType") or "")
        if pair not in TARGET_PAIRS:
            continue
        err = item["explanation"]["errData"]
        ids = [str(err.get("obj1") or ""), str(err.get("obj2") or "")]
        types = [str(err.get("obj1Type") or ""), str(err.get("obj2Type") or "")]
        suffixes = [str(err.get("obj1Suffix") or ""), str(err.get("obj2Suffix") or "")]
        actual_mm = float(err["minDistance"]) * DISPLAY_MIL_PER_RAW_UNIT * MM_PER_MIL
        required_mm = float(err["clearance"]) * DISPLAY_MIL_PER_RAW_UNIT * MM_PER_MIL
        raw_rows.append({
            "global_index": str(err.get("globalIndex") or ""),
            "pair": pair,
            "ids": ids,
            "reported_types": types,
            "suffixes": suffixes,
            "nets": [net_from_suffix(value) for value in suffixes],
            "layer": str(item.get("layer") or ""),
            "layer_ids": list(err.get("layerIds") or []),
            "drc_position_mil": [
                float(err["position"]["x"]) * DISPLAY_MIL_PER_RAW_UNIT,
                float(err["position"]["y"]) * DISPLAY_MIL_PER_RAW_UNIT,
            ],
            "actual_mm": actual_mm,
            "required_mm": required_mm,
            "deficit_mm": max(0.0, required_mm - actual_mm),
        })

    object_ids = sorted({object_id for row in raw_rows for object_id in row["ids"]})
    objects: dict[str, dict[str, Any]] = {}
    unresolved = []
    for object_id in object_ids:
        if object_id in source_by_id:
            objects[object_id] = record_geometry(source_by_id[object_id])
        elif object_id in pads:
            objects[object_id] = pads[object_id]
        else:
            unresolved.append(object_id)
    if unresolved:
        raise AssertionError(f"unresolved DRC objects: {unresolved[:12]}")

    for object_id, descriptor in objects.items():
        if descriptor["type"] not in {"LINE", "ARC", "VIA"}:
            continue
        contacts = []
        for x, y in endpoint_rows(source_by_id[object_id]):
            for candidate in endpoint_index[qpoint(x, y)]:
                if candidate["id"] == object_id:
                    continue
                if candidate["net"] != descriptor["net"]:
                    continue
                contacts.append(candidate)
        descriptor["same_net_endpoint_contacts"] = contacts

    line_records_by_net: dict[str, list[Any]] = defaultdict(list)
    for record in records:
        if record.kind == "LINE":
            line_records_by_net[str(record.body.get("netName") or "")].append(record)
    for via_id in sorted(
        object_id for object_id, value in objects.items() if value["type"] == "VIA"
    ):
        via = objects[via_id]
        center = via["center_mil"]
        copper_contacts = []
        for line in line_records_by_net.get(via["net"], []):
            closest, distance = point_segment_closest(
                center,
                [line.body["startX"], line.body["startY"]],
                [line.body["endX"], line.body["endY"]],
            )
            if distance <= (via["diameter_mil"] + float(line.body["width"])) / 2.0 + 0.001:
                copper_contacts.append({
                    "id": line.record_id,
                    "type": "LINE",
                    "layer_id": line.body.get("layerId"),
                    "width_mil": float(line.body["width"]),
                    "centerline_distance_mil": distance,
                    "closest_point_mil": closest,
                })
        via["same_net_line_copper_contacts"] = sorted(
            copper_contacts, key=lambda value: (value["centerline_distance_mil"], value["id"])
        )

    conflict_degree = Counter(object_id for row in raw_rows for object_id in row["ids"])
    track_plans = []
    for row in raw_rows:
        if row["pair"] not in TRACK_PAIRS:
            continue
        track_ids = [object_id for object_id in row["ids"] if objects[object_id]["type"] == "LINE"]
        if not track_ids:
            raise AssertionError(f"track violation has no LINE: {row}")
        selected_track = min(
            track_ids,
            key=lambda object_id: (
                conflict_degree[object_id],
                len(objects[object_id].get("same_net_endpoint_contacts", [])),
                objects[object_id].get("length_mil", math.inf),
                object_id,
            ),
        )
        track = objects[selected_track]
        required_shift_mm = row["deficit_mm"] + NET_REPAIR_MARGIN_MM
        direction = None
        pad_id = next((value for value in row["ids"] if objects[value]["type"] == "PAD"), None)
        if pad_id is not None:
            pad_center = objects[pad_id]["center_mil"]
            closest, distance = point_segment_closest(
                pad_center, track["start_mil"], track["end_mil"]
            )
            dx, dy = closest[0] - pad_center[0], closest[1] - pad_center[1]
            norm = math.hypot(dx, dy)
            if norm > 1e-9:
                direction = [dx / norm, dy / norm]
        track_plans.append({
            **row,
            "selected_track": selected_track,
            "selected_track_conflict_degree": conflict_degree[selected_track],
            "selected_track_endpoint_contact_count": len(track.get("same_net_endpoint_contacts", [])),
            "minimum_centerline_shift_mm_with_margin": required_shift_mm,
            "suggested_away_unit_vector": direction,
            "suggested_translation_mil": (
                [
                    direction[0] * required_shift_mm / MM_PER_MIL,
                    direction[1] * required_shift_mm / MM_PER_MIL,
                ] if direction else None
            ),
            "automation_status": "plan-only; preserve endpoints with checked doglegs and rerun full DRC",
        })

    via_rows = [row for row in raw_rows if row["pair"] in VIA_PAIRS]
    via_ids = sorted({
        object_id
        for row in via_rows
        for object_id in row["ids"]
        if objects[object_id]["type"] == "VIA"
    })
    via_profiles: dict[str, Any] = {}
    for profile in ("preferred", "clearance"):
        targets: dict[str, float] = {}
        for via_id in via_ids:
            via = objects[via_id]
            target_mm = via_target_mm(via["hole_mil"] * MM_PER_MIL, profile)
            target_mil = target_mm / MM_PER_MIL
            if target_mil >= via["diameter_mil"]:
                target_mil = via["diameter_mil"]
            targets[via_id] = target_mil
        evaluations = []
        for row in via_rows:
            radial_gain_mm = 0.0
            for object_id in row["ids"]:
                if objects[object_id]["type"] != "VIA":
                    continue
                old_diameter = objects[object_id]["diameter_mil"]
                radial_gain_mm += (old_diameter - targets[object_id]) * MM_PER_MIL / 2.0
            candidate_mm = row["actual_mm"] + radial_gain_mm
            evaluations.append({
                "global_index": row["global_index"],
                "pair": row["pair"],
                "ids": row["ids"],
                "actual_mm": row["actual_mm"],
                "required_mm": row["required_mm"],
                "radial_clearance_gain_mm": radial_gain_mm,
                "candidate_mm": candidate_mm,
                "passes": candidate_mm + 1e-9 >= row["required_mm"],
            })
        no_route_contact = [
            via_id for via_id in via_ids
            if not objects[via_id].get("same_net_line_copper_contacts")
            and not any(
                contact["type"] == "ARC"
                for contact in objects[via_id].get("same_net_endpoint_contacts", [])
            )
        ]
        via_profiles[profile] = {
            "targets_mil": targets,
            "targets_mm_by_hole_mm": sorted({
                (
                    round(objects[via_id]["hole_mil"] * MM_PER_MIL, 6),
                    round(targets[via_id] * MM_PER_MIL, 6),
                ) for via_id in via_ids
            }),
            "rows": len(evaluations),
            "passing_rows": sum(value["passes"] for value in evaluations),
            "failing_rows": [value for value in evaluations if not value["passes"]],
            "vias_without_same_net_track_or_arc_endpoint": no_route_contact,
            "evaluations": evaluations,
        }

    chosen_profile = "clearance"
    chosen = via_profiles[chosen_profile]
    candidate_bytes: bytes | None = None
    candidate_gate = not chosen["failing_rows"] and not chosen["vias_without_same_net_track_or_arc_endpoint"]
    if candidate_gate:
        output_lines = []
        targets = chosen["targets_mil"]
        for record in records:
            if record.record_id not in targets:
                output_lines.append(record.raw.rstrip(b"\r\n") + b"\n")
                continue
            body = dict(record.body)
            body["viaDiameter"] = round(targets[record.record_id], 6)
            line = compact(record.header).encode("utf-8") + b"||" + compact(body).encode("utf-8") + b"|\n"
            output_lines.append(line)
        candidate_bytes = b"".join(output_lines)

    via_only_plan = {
        "schema": "stm32h747-via-only-clearance-plan-v1",
        "status": "review-only-not-applied",
        "pcbUuid": str(drc.get("pcbUuid") or ""),
        "stage": "multilayer-via-clearance-preferred-annulus",
        "source": {
            "path": str(args.source.relative_to(ROOT)),
            "sha256": sha256_file(args.source),
        },
        "profile": "preferred",
        "manufacturing_basis": (
            "All implicated vias are 0.20 mm drill / 0.40 mm copper. The proposed "
            "0.35 mm copper diameter preserves a 0.15 mm diameter difference "
            "(0.075 mm radial annulus)."
        ),
        "modified_vias": [],
        "changes": [],
        "analytical_result": {
            "input_rows": via_profiles["preferred"]["rows"],
            "passing_rows": via_profiles["preferred"]["passing_rows"],
            "remaining_rows": len(via_profiles["preferred"]["failing_rows"]),
            "remaining_pair_counts": dict(sorted(Counter(
                value["pair"] for value in via_profiles["preferred"]["failing_rows"]
            ).items())),
        },
        "warning": (
            "VIA-only shrink is monotonic-safe for different-net spacing but does not "
            "clear all VIA rows. Apply only as a reviewed pilot and rerun native DRC."
        ),
    }
    preferred_targets = via_profiles["preferred"]["targets_mil"]
    for via_id in via_ids:
        body = source_by_id[via_id].body
        before = dict(body)
        after = dict(before)
        after["viaDiameter"] = round(preferred_targets[via_id], 6)
        change = {
            "id": via_id,
            "type": "VIA",
            "before": before,
            "after": after,
            "same_net_line_copper_contacts": objects[via_id].get("same_net_line_copper_contacts", []),
            "same_net_endpoint_contacts": objects[via_id].get("same_net_endpoint_contacts", []),
        }
        via_only_plan["modified_vias"].append(change)
        via_only_plan["changes"].append({
            "id": via_id,
            "type": "VIA",
            "before": before,
            "after": after,
        })

    pilot_id = "e917297287b005ea"
    pilot_change = next(
        value for value in via_only_plan["changes"] if value["id"] == pilot_id
    )
    pilot_evaluations = [
        value for value in via_profiles["preferred"]["evaluations"]
        if pilot_id in value["ids"]
    ]
    if (
        len(pilot_evaluations) != 1
        or not pilot_evaluations[0]["passes"]
        or len(objects[pilot_id].get("same_net_endpoint_contacts", [])) < 2
        or not objects[pilot_id].get("same_net_line_copper_contacts")
    ):
        raise AssertionError("selected VIA pilot no longer meets its static safety guards")
    via_pilot_plan = {
        "schema": "stm32h747-via-clearance-pilot-v1",
        "status": "review-only-not-applied",
        "pcbUuid": str(drc.get("pcbUuid") or ""),
        "stage": "multilayer-via-clearance-one-via-pilot",
        "source": {
            "path": str(args.source.relative_to(ROOT)),
            "sha256": sha256_file(args.source),
        },
        "changes": [pilot_change],
        "proof": {
            "net": objects[pilot_id]["net"],
            "same_net_endpoint_contacts": objects[pilot_id]["same_net_endpoint_contacts"],
            "same_net_line_copper_contacts": objects[pilot_id]["same_net_line_copper_contacts"],
            "affected_current_drc_rows": pilot_evaluations,
            "drill_center_net_layer_unchanged": True,
            "different_net_clearance_is_monotonic_non_decreasing": True,
            "full_native_drc_required_after_application": True,
        },
    }

    combined_via_targets_mil = {}
    smd_via_ids = {
        object_id
        for row in raw_rows if row["pair"] == "SMD Pad to Via"
        for object_id in row["ids"] if objects[object_id]["type"] == "VIA"
    }
    for via_id in via_ids:
        target_mm = 0.31 if via_id in smd_via_ids else 0.32
        combined_via_targets_mil[via_id] = target_mm / MM_PER_MIL

    line_targets_mil: dict[str, float] = {
        object_id: value["width_mil"]
        for object_id, value in objects.items() if value["type"] == "LINE"
    }
    width_constraints = []
    for row in raw_rows:
        line_ids = [object_id for object_id in row["ids"] if objects[object_id]["type"] == "LINE"]
        if len(line_ids) != 1 or row["pair"] not in {"Track to Via", "SMD Pad to Track"}:
            continue
        line_id = line_ids[0]
        radial_gain_mm = sum(
            (objects[object_id]["diameter_mil"] - combined_via_targets_mil[object_id])
            * MM_PER_MIL / 2.0
            for object_id in row["ids"] if objects[object_id]["type"] == "VIA"
        )
        remaining_gain_mm = max(
            0.0,
            row["required_mm"] + COMBINED_MARGIN_MM - row["actual_mm"] - radial_gain_mm,
        )
        maximum_width_mm = objects[line_id]["width_mil"] * MM_PER_MIL - 2.0 * remaining_gain_mm
        rounded_target_mm = math.floor((maximum_width_mm + 1e-12) * 1000.0) / 1000.0
        target_mm = max(MIN_TRACK_WIDTH_MM, rounded_target_mm)
        line_targets_mil[line_id] = min(line_targets_mil[line_id], target_mm / MM_PER_MIL)
        width_constraints.append({
            "global_index": row["global_index"],
            "pair": row["pair"],
            "line_id": line_id,
            "old_width_mm": objects[line_id]["width_mil"] * MM_PER_MIL,
            "maximum_width_mm_for_margin": maximum_width_mm,
            "selected_target_mm": target_mm,
            "requires_below_floor": maximum_width_mm < MIN_TRACK_WIDTH_MM,
        })

    def candidate_clearance(row: dict[str, Any]) -> float:
        gain_mm = 0.0
        for object_id in row["ids"]:
            descriptor = objects[object_id]
            if descriptor["type"] == "VIA":
                gain_mm += (
                    descriptor["diameter_mil"] - combined_via_targets_mil[object_id]
                ) * MM_PER_MIL / 2.0
            elif descriptor["type"] == "LINE":
                gain_mm += (
                    descriptor["width_mil"] - line_targets_mil[object_id]
                ) * MM_PER_MIL / 2.0
        return row["actual_mm"] + gain_mm

    for row in [value for value in raw_rows if value["pair"] == "Track to Track"]:
        current_mm = candidate_clearance(row)
        needed_mm = row["required_mm"] + COMBINED_MARGIN_MM - current_mm
        if needed_mm <= 0:
            continue
        line_ids = [object_id for object_id in row["ids"] if objects[object_id]["type"] == "LINE"]
        total_reduction_mm = 2.0 * needed_mm
        for line_id in sorted(
            line_ids,
            key=lambda value: (-(line_targets_mil[value] * MM_PER_MIL - MIN_TRACK_WIDTH_MM), value),
        ):
            current_width_mm = line_targets_mil[line_id] * MM_PER_MIL
            available_mm = max(0.0, current_width_mm - MIN_TRACK_WIDTH_MM)
            reduction_mm = min(available_mm, total_reduction_mm)
            line_targets_mil[line_id] = (current_width_mm - reduction_mm) / MM_PER_MIL
            total_reduction_mm -= reduction_mm
            if total_reduction_mm <= 1e-12:
                break

    combined_evaluations = []
    for row in [value for value in raw_rows if value["pair"] != "Board Outline to TH Pad"]:
        candidate_mm = candidate_clearance(row)
        combined_evaluations.append({
            "global_index": row["global_index"],
            "pair": row["pair"],
            "ids": row["ids"],
            "actual_mm": row["actual_mm"],
            "required_mm": row["required_mm"],
            "target_with_margin_mm": row["required_mm"] + COMBINED_MARGIN_MM,
            "candidate_mm": candidate_mm,
            "passes_rule": candidate_mm + 1e-9 >= row["required_mm"],
            "passes_margin": candidate_mm + 1e-9 >= row["required_mm"] + COMBINED_MARGIN_MM,
        })

    modified_lines = []
    for line_id, target_mil in sorted(line_targets_mil.items()):
        old_mil = objects[line_id]["width_mil"]
        if target_mil >= old_mil - 1e-9:
            continue
        body = source_by_id[line_id].body
        modified_lines.append({
            "id": line_id,
            "before": {
                key: body.get(key)
                for key in (
                    "netName", "layerId", "startX", "startY", "endX", "endY",
                    "width", "locked", "zIndex",
                )
            },
            "after": {
                **{
                    key: body.get(key)
                    for key in (
                        "netName", "layerId", "startX", "startY", "endX", "endY",
                        "width", "locked", "zIndex",
                    )
                },
                "width": round(target_mil, 6),
            },
            "target_width_mm": target_mil * MM_PER_MIL,
            "same_net_endpoint_contacts": objects[line_id].get("same_net_endpoint_contacts", []),
        })

    combined_modified_vias = []
    for via_id in via_ids:
        body = source_by_id[via_id].body
        before = {
            key: body.get(key)
            for key in (
                "netName", "centerX", "centerY", "holeDiameter", "viaDiameter",
                "viaType", "unusedInnerLayers", "topSolderExpansion",
                "bottomSolderExpansion", "locked",
            )
        }
        after = dict(before)
        after["viaDiameter"] = round(combined_via_targets_mil[via_id], 6)
        combined_modified_vias.append({
            "id": via_id,
            "before": before,
            "after": after,
            "target_diameter_mm": combined_via_targets_mil[via_id] * MM_PER_MIL,
            "same_net_line_copper_contacts": objects[via_id].get("same_net_line_copper_contacts", []),
        })

    combined_plan = {
        "schema": "stm32h747-via-track-width-clearance-plan-v1",
        "status": "review-only-not-applied",
        "source": {"path": str(args.source.relative_to(ROOT)), "sha256": sha256_file(args.source)},
        "constraints": {
            "minimum_track_width_mm": MIN_TRACK_WIDTH_MM,
            "clearance_margin_mm": COMBINED_MARGIN_MM,
            "ordinary_via": {"hole_mm": 0.2, "diameter_mm": 0.32},
            "smd_pad_conflicting_via": {"hole_mm": 0.2, "diameter_mm": 0.31},
            "centres_drills_nets_layers_endpoints_immutable": True,
        },
        "modified_vias": combined_modified_vias,
        "modified_lines": modified_lines,
        "width_constraints": width_constraints,
        "evaluation": {
            "rows": len(combined_evaluations),
            "passing_rule": sum(value["passes_rule"] for value in combined_evaluations),
            "passing_margin": sum(value["passes_margin"] for value in combined_evaluations),
            "failing_rule": [value for value in combined_evaluations if not value["passes_rule"]],
            "failing_margin": [value for value in combined_evaluations if not value["passes_margin"]],
            "pair_counts_failing_rule": dict(sorted(Counter(
                value["pair"] for value in combined_evaluations if not value["passes_rule"]
            ).items())),
        },
        "application_gate": {
            "native_project_write_authorized": False,
            "static_geometry_only": True,
            "requires_native_drc_after_pilot": True,
            "requires_current_capacity_and_impedance_review": True,
            "requires_fill_connectivity_review": True,
        },
    }

    combined_candidate_bytes = None
    via_rows_pass = all(
        value["passes_rule"]
        for value in combined_evaluations
        if value["pair"] in VIA_PAIRS
    )
    if via_rows_pass:
        via_target_map = {
            value["id"]: value["after"]["viaDiameter"] for value in combined_modified_vias
        }
        line_target_map = {
            value["id"]: value["after"]["width"] for value in modified_lines
        }
        output_lines = []
        for record in records:
            if record.record_id not in via_target_map and record.record_id not in line_target_map:
                output_lines.append(record.raw.rstrip(b"\r\n") + b"\n")
                continue
            body = dict(record.body)
            if record.record_id in via_target_map:
                body["viaDiameter"] = via_target_map[record.record_id]
            if record.record_id in line_target_map:
                body["width"] = line_target_map[record.record_id]
            output_lines.append(
                compact(record.header).encode("utf-8") + b"||"
                + compact(body).encode("utf-8") + b"|\n"
            )
        combined_candidate_bytes = b"".join(output_lines)

    outline_rows = [row for row in raw_rows if row["pair"] == "Board Outline to TH Pad"]
    outline_plan: dict[str, Any] = {"rows": outline_rows, "automation_status": "not-applicable"}
    if outline_rows:
        outline_ids = sorted({row["ids"][0] for row in outline_rows})
        pad_ids = sorted({row["ids"][1] for row in outline_rows})
        if len(pad_ids) == 1 and len(outline_ids) == 4:
            pad = objects[pad_ids[0]]
            hole = pad.get("hole") or {}
            hole_diameter_mm = float(hole.get("width") or 0) * MM_PER_MIL
            center_x, center_y = pad["center_mil"]
            required_mm = max(row["required_mm"] for row in outline_rows)
            outline_margin_mm = 0.01
            half_extent_mil = (
                hole_diameter_mm / 2.0 + required_mm + outline_margin_mm
            ) / MM_PER_MIL
            bounds = {
                "min_x": center_x - half_extent_mil,
                "max_x": center_x + half_extent_mil,
                "min_y": center_y - half_extent_mil,
                "max_y": center_y + half_extent_mil,
            }
            current_points = []
            for outline_id in outline_ids:
                path = objects[outline_id]["path"]
                current_points.extend([
                    [float(path[0]), float(path[1])],
                    [float(path[-2]), float(path[-1])],
                ])
            current_bounds = {
                "min_x": min(value[0] for value in current_points),
                "max_x": max(value[0] for value in current_points),
                "min_y": min(value[1] for value in current_points),
                "max_y": max(value[1] for value in current_points),
            }
            outline_plan.update({
                "automation_status": "plan-only; mechanical cutout approval required",
                "pad": pad,
                "outline_ids": outline_ids,
                "current_bounds_mil": current_bounds,
                "current_size_mm": [
                    (current_bounds["max_x"] - current_bounds["min_x"]) * MM_PER_MIL,
                    (current_bounds["max_y"] - current_bounds["min_y"]) * MM_PER_MIL,
                ],
                "minimum_rule_compliant_bounds_mil": bounds,
                "minimum_rule_compliant_size_mm": [
                    2 * half_extent_mil * MM_PER_MIL,
                    2 * half_extent_mil * MM_PER_MIL,
                ],
                "required_outward_change_per_edge_mm": max(
                    bounds["max_x"] - current_bounds["max_x"],
                    current_bounds["min_x"] - bounds["min_x"],
                    bounds["max_y"] - current_bounds["max_y"],
                    current_bounds["min_y"] - bounds["min_y"],
                ) * MM_PER_MIL,
                "extra_margin_mm": outline_margin_mm,
                "proposed_paths_mil": {
                    outline_id: [
                        bounds["min_x"] if abs(float(objects[outline_id]["path"][0]) - current_bounds["min_x"]) < 0.01 else bounds["max_x"],
                        bounds["min_y"] if abs(float(objects[outline_id]["path"][1]) - current_bounds["min_y"]) < 0.01 else bounds["max_y"],
                        "L",
                        bounds["min_x"] if abs(float(objects[outline_id]["path"][-2]) - current_bounds["min_x"]) < 0.01 else bounds["max_x"],
                        bounds["min_y"] if abs(float(objects[outline_id]["path"][-1]) - current_bounds["min_y"]) < 0.01 else bounds["max_y"],
                    ]
                    for outline_id in outline_ids
                },
                "recommendation": (
                    "Preserve the 1.3 mm NPTH and expand the internal square Board Outline "
                    "symmetrically; do not reduce the authoritative drill. This changes the "
                    "mechanical cutout from 1.8 mm to 1.92 mm, leaves about 0.31 mm to the "
                    "1.3 mm drill, and requires enclosure/fabricator review."
                ),
            })

    edges = [(row["ids"][0], row["ids"][1]) for row in raw_rows]
    components = connected_components(edges)
    component_rows = []
    for index, ids in enumerate(components, 1):
        rows = [row for row in raw_rows if any(value in ids for value in row["ids"])]
        component_rows.append({
            "cluster": index,
            "object_count": len(ids),
            "violation_count": len(rows),
            "object_ids": ids,
            "pair_counts": dict(sorted(Counter(row["pair"] for row in rows).items())),
            "layers": dict(sorted(Counter(row["layer"] for row in rows).items())),
            "nets": sorted({net for row in rows for net in row["nets"] if net}),
        })

    report = {
        "schema": "stm32h747-multilayer-nonfill-clearance-plan-v1",
        "status": "static-plan-not-applied",
        "read_only_inputs": True,
        "manufacturing_approved": False,
        "inputs": {
            "drc": {"path": str(args.drc.relative_to(ROOT)), "sha256": sha256_file(args.drc)},
            "source": {"path": str(args.source.relative_to(ROOT)), "sha256": sha256_file(args.source)},
            "checkpoint": {"path": str(args.checkpoint.relative_to(ROOT)), "sha256": sha256_file(args.checkpoint)},
            "pad_audit": {"path": str(args.pad_audit.relative_to(ROOT)), "sha256": sha256_file(args.pad_audit)},
        },
        "scope": {
            "drc_total": int(drc.get("violations") or 0),
            "selected_nonfill_plus_outline": len(raw_rows),
            "selected_nonfill": sum(row["pair"] != "Board Outline to TH Pad" for row in raw_rows),
            "outline": len(outline_rows),
            "pair_counts": dict(sorted(Counter(row["pair"] for row in raw_rows).items())),
            "unique_objects": len(objects),
            "unique_vias": len(via_ids),
            "conflict_clusters": len(components),
        },
        "objects": objects,
        "conflict_clusters": component_rows,
        "via_diameter_profiles": via_profiles,
        "via_only_plan": via_only_plan,
        "via_pilot_plan": via_pilot_plan,
        "via_track_width_plan": combined_plan,
        "chosen_via_profile": chosen_profile,
        "via_candidate_gate": {
            "write_candidate": candidate_gate,
            "all_current_via_clearance_rows_pass_analytically": not chosen["failing_rows"],
            "all_modified_vias_have_same_net_track_or_arc_endpoint": not chosen["vias_without_same_net_track_or_arc_endpoint"],
            "monotonic_safety": "Reducing only VIA copper diameter cannot create a new different-net spacing violation; drill positions and diameters remain unchanged.",
            "remaining_validation": [
                "run native DRC after application",
                "confirm same-net FILL/plane connectivity",
                "confirm manufacturer acceptance of each hole/diameter pair",
                "re-export and compare all 793 drill positions and diameters",
            ],
        },
        "track_reroute_plan": {
            "rows": len(track_plans),
            "pair_counts": dict(sorted(Counter(row["pair"] for row in track_plans).items())),
            "items": track_plans,
            "policy": (
                "Do not reduce track width below the selected rule minimum. Translate or locally "
                "dogleg the chosen segment, retain the original net/layer and both endpoint contacts, "
                "then rerun full DRC because FILL and adjacent-route constraints are coupled."
            ),
        },
        "outline_plan": outline_plan,
        "all_rows": raw_rows,
        "limitations": [
            "This is a static plan, not a native DRC result after repair.",
            "The VIA calculation is exact only for radial copper-diameter reduction at fixed centers.",
            "Track translations are suggestions only; no route candidate is emitted until whole-board geometry and endpoint connectivity are rechecked.",
            "The internal CN1 cutout change is mechanical and cannot be approved from electrical DRC alone.",
            "FILL-related violations are intentionally left to the separate fill-clearance plan.",
        ],
    }
    return report, candidate_bytes, combined_candidate_bytes


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drc", type=Path, default=DEFAULT_DRC)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--pad-audit", type=Path, default=DEFAULT_PAD_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--via-candidate", type=Path, default=DEFAULT_VIA_CANDIDATE)
    parser.add_argument("--via-plan", type=Path, default=DEFAULT_VIA_PLAN)
    parser.add_argument("--via-pilot", type=Path, default=DEFAULT_VIA_PILOT)
    parser.add_argument("--combined-plan", type=Path, default=DEFAULT_COMBINED_PLAN)
    parser.add_argument("--combined-candidate", type=Path, default=DEFAULT_COMBINED_CANDIDATE)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report, candidate, combined_candidate = analyze(args)
    via_only_plan = report["via_only_plan"]
    via_pilot_plan = report["via_pilot_plan"]
    combined_plan = report["via_track_width_plan"]
    atomic_write(
        args.via_plan,
        (json.dumps(via_only_plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    atomic_write(
        args.via_pilot,
        (json.dumps(via_pilot_plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    atomic_write(
        args.combined_plan,
        (json.dumps(combined_plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    report["via_only_plan_file"] = {
        "path": str(args.via_plan.relative_to(ROOT)),
        "sha256": sha256_file(args.via_plan),
    }
    report["via_pilot_plan_file"] = {
        "path": str(args.via_pilot.relative_to(ROOT)),
        "sha256": sha256_file(args.via_pilot),
    }
    report["via_track_width_plan_file"] = {
        "path": str(args.combined_plan.relative_to(ROOT)),
        "sha256": sha256_file(args.combined_plan),
    }
    if combined_candidate is not None:
        atomic_write(args.combined_candidate, combined_candidate)
        combined_plan["candidate"] = {
            "path": str(args.combined_candidate.relative_to(ROOT)),
            "sha256": sha256_file(args.combined_candidate),
            "bytes": len(combined_candidate),
        }
        atomic_write(
            args.combined_plan,
            (json.dumps(combined_plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        report["via_track_width_plan_file"] = {
            "path": str(args.combined_plan.relative_to(ROOT)),
            "sha256": sha256_file(args.combined_plan),
        }
        report["via_track_width_candidate"] = dict(combined_plan["candidate"])
    atomic_write(args.output, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if candidate is not None:
        atomic_write(args.via_candidate, candidate)
        report["via_candidate_gate"]["candidate_path"] = str(args.via_candidate.relative_to(ROOT))
        report["via_candidate_gate"]["candidate_sha256"] = hashlib.sha256(candidate).hexdigest()
        atomic_write(args.output, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(compact({
        "status": report["status"],
        "scope": report["scope"],
        "via_candidate": report["via_candidate_gate"],
        "output": str(args.output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
