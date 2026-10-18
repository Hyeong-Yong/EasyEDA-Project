"""Prepare (but do not apply) the eight omitted U5/U7 thermal-PTH pads.

The archived fabrication data proves four extra plated component drills around
each exposed pad.  Every drill is 0.3 mm, and every one of the six copper
Gerbers carries a dark 0.6 mm ``ComponentPad`` flash on GND.  These are not
routing vias semantically: F/B copper identifies pad 25 or 33 and the drill
file identifies ``Plated,PTH,ComponentDrill``.

This read-only/static tool builds complete U5/U7 FOOTPRINT candidate sources
with four additional, duplicate-number multilayer PAD records.  It starts from
the exact normalized FOOTPRINT blocks in the post-inner-pad-shape checkpoint,
protects every existing record body byte-for-byte at the JSON value level, and
records the installed EasyEDA 3.2 duplicate-number PAD_NET inheritance path.
No EasyEDA API is called.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from extract_gerber_reconstruction import parse_drill, parse_gerber


ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "output/validation"
GERBER_DIR = ROOT / "보드 자료/MCU_BOARD_v19_260616_Gerber"
ROUTES = ROOT / "output/semantic/gerber-copper-routes.json"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_u5_pth_attempt_20261014.epro2"
CHECKPOINT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
PCB_SOURCE = ROOT / "output/validation/native-final-pcb-after_inner_pad_shapes-reopened.epru"
POST_SPECIAL_DRC = ROOT / "output/validation/u5-u7-thermal-pth-pre-fix-drc.json"
SPECIAL_PLAN = ROOT / "output/validation/u5-u7-special-pad-fix-plan.json"
REPORT = VALIDATION / "u5-u7-thermal-pth-pad-fix-plan.json"
PCB_JS = Path(r"C:\Program Files\easyeda-pro\resources\app\assets\pro-pcb\3.2.193.682ed44e\js\pcb.js")

MM_TO_MIL = 1000.0 / 25.4
COORD_TOLERANCE_MM = 0.00001
COORD_TOLERANCE_MIL = 0.001
COPPER_FILES = {
    "F.Cu": "MCU_BOARD_v19_260616-F_Cu.gbr",
    "In1.Cu": "MCU_BOARD_v19_260616-In1_Cu.gbr",
    "In2.Cu": "MCU_BOARD_v19_260616-In2_Cu.gbr",
    "In3.Cu": "MCU_BOARD_v19_260616-In3_Cu.gbr",
    "In4.Cu": "MCU_BOARD_v19_260616-In4_Cu.gbr",
    "B.Cu": "MCU_BOARD_v19_260616-B_Cu.gbr",
}
INNER_LAYER_IDS = {"In1.Cu": 15, "In2.Cu": 16, "In3.Cu": 17, "In4.Cu": 18}
TARGETS = {
    "U5": {
        "pad_number": "25",
        "uuid": "b098cceac55eab69",
        "center_mm": [200.01, -181.46],
        "top_size_mm": 2.5,
        "output": "native-U5-thermal-pth-pad-candidate.epru",
    },
    "U7": {
        "pad_number": "33",
        "uuid": "15077d1eac66847c",
        "center_mm": [224.085, -152.31],
        "top_size_mm": 3.45,
        "output": "native-U7-thermal-pth-pad-candidate.epru",
    },
}


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def clean(value: Any, digits: int = 6) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_text(lines: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        body_text = body_text[:-1] if body_text.endswith("|") else body_text
        return json.loads(header_text), json.loads(body_text)
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def native_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
    ]


def checkpoint_footprints() -> dict[str, list[str]]:
    with zipfile.ZipFile(CHECKPOINT) as archive:
        lines = archive.read(CHECKPOINT_MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current: list[str] = []
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, CHECKPOINT.name, line_number)
        if header.get("type") == "DOCHEAD":
            if current_uuid is not None:
                result[current_uuid] = current
            current_uuid = str(body.get("uuid")) if body.get("docType") == "FOOTPRINT" else None
            current = [raw] if current_uuid is not None else []
        elif current_uuid is not None:
            current.append(raw)
    if current_uuid is not None:
        result[current_uuid] = current
    return result


def duplicate_pad_binding_evidence() -> dict[str, Any]:
    source = PCB_JS.read_text(encoding="utf-8", errors="replace")
    needles = {
        "resolver_constructor": "this.newFootIds=i;this.built=!1;this.itemByFootId=new Map;this.footIdsByNum=new Map",
        "from_cache": "static fromCache(t,e){let r=[...t.getPads(),...t.getVias()];return new o(t.globalIndex,t.getPadNetRecords(),r,e)}",
        "new_child_number_inheritance": "l&&this.keepNumRep(r,s,t)",
        "multi_pad_stat": "numInheritMultiCount",
        "footprint_update_resolve": "a_.fromCache(s,n.get(s)).resolve()",
        "padnet_materialization": "h.parentModel=s,h.model=c,h.netModifyInter=this,h.load()",
    }
    matches: dict[str, Any] = {}
    for name, needle in needles.items():
        offset = source.find(needle)
        if offset < 0:
            raise AssertionError(f"installed duplicate PAD_NET evidence missing: {name}")
        matches[name] = {"character_offset": offset, "needle": needle}
    return {
        "installed_pcb_runtime": {"path": str(PCB_JS), "sha256": sha256(PCB_JS)},
        "matches": matches,
        "contract": [
            "The footprint-update path passes the set of newly added child IDs to a_.fromCache(component,newFootIds).",
            "The resolver indexes all child pads by num and, when a newly added child shares an existing numbered pad, keeps the existing PAD_NET as the number representative.",
            "resolve() assigns that representative to every same-number child and counts the event as numInheritMultiCount.",
            "The update loop calls load() with each assigned child model, materializing a child-specific PAD_NET record.",
            "A cold reopen binds PAD_NET by component ID, pad number, and unique child suffix; number inheritance during update is not a substitute for persisted child-specific rows.",
        ],
        "required_runtime_proof": "After the scoped U5 pilot, central e25 plus e36-e39 must each report GND and the reopened board source must contain one child-specific PAD_NET row for every suffix.",
    }


def dark_flashes_at(layer: dict[str, Any], point: Sequence[float]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, item in enumerate(layer["objects"]):
        if item.get("kind") != "flash" or item.get("polarity") != "dark":
            continue
        if math.dist([finite(v) for v in item.get("atMm", [])], [finite(v) for v in point]) > COORD_TOLERANCE_MM:
            continue
        aperture = layer["apertures"][item["aperture"]]
        result.append({
            "object_index": index,
            "aperture": item["aperture"],
            "polarity": item["polarity"],
            "template": aperture.get("template"),
            "params_mm": aperture.get("paramsMm"),
            "aperture_function": aperture.get("function"),
            "attrs": item.get("attrs") or {},
            "at_mm": item["atMm"],
        })
    return result


def circle_path(body: dict[str, Any]) -> tuple[float, float, float] | None:
    path = body.get("path")
    if (
        not isinstance(path, list) or len(path) != 1
        or not isinstance(path[0], list) or len(path[0]) != 4
        or path[0][0] != "CIRCLE"
    ):
        return None
    return finite(path[0][1]), finite(path[0][2]), finite(path[0][3])


def drc_leaves(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield value
        for child in value.values():
            yield from drc_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from drc_leaves(child)


def add_candidate_pads(
    reference: str,
    config: dict[str, Any],
    base_lines: list[str],
    extras: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed = [parse_record(raw, reference, i) for i, raw in enumerate(base_lines, 1)]
    target = [
        (header, body) for header, body in parsed
        if header.get("type") == "PAD" and str(body.get("num")) == config["pad_number"]
    ]
    if len(target) != 1:
        raise AssertionError(f"{reference}: expected exactly one existing central pad")
    target_header, target_body = target[0]
    if target_body.get("centerX") != 0 or target_body.get("centerY") != 0:
        raise AssertionError(f"{reference}: exposed pad is not at footprint origin")
    if len(target_body.get("specialPad") or []) != 3:
        raise AssertionError(f"{reference}: central specialPad repair is absent")

    existing_pad_centers = [
        [finite(body["centerX"]), finite(body["centerY"])]
        for header, body in parsed if header.get("type") == "PAD"
    ]
    max_element_id = max(
        int(match.group(1))
        for header, _ in parsed
        if (match := re.fullmatch(r"e(\d+)", str(header.get("id"))))
    )
    max_ticket = max(int(header["ticket"]) for header, _ in parsed if isinstance(header.get("ticket"), int))
    # firstTicket is the immutable document-order key, not a second revision
    # counter.  Administrative ATTR/NET records may have very large order
    # values and must not be used for a new primitive.  Preserve the existing
    # e<number> primitive sequence: U5 e35 ends at 58 and U7 e43 at 66.
    primitive_first_tickets = [
        int(header.get("firstTicket", header["ticket"]))
        for header, _ in parsed
        if re.fullmatch(r"e\d+", str(header.get("id")))
        and isinstance(header.get("ticket"), int)
    ]
    max_first_ticket = max(primitive_first_tickets)
    max_z = max(int(body["zIndex"]) for _, body in parsed if isinstance(body.get("zIndex"), int))

    new_records: list[str] = []
    additions: list[dict[str, Any]] = []
    center_mm = [finite(value) for value in config["center_mm"]]
    for index, evidence in enumerate(sorted(extras, key=lambda item: tuple(item["source_at_mm"])), 1):
        source_at = [finite(value) for value in evidence["source_at_mm"]]
        local = [
            clean((source_at[0] - center_mm[0]) * MM_TO_MIL, 4),
            clean((source_at[1] - center_mm[1]) * MM_TO_MIL, 4),
        ]
        if any(math.dist(local, prior) <= COORD_TOLERANCE_MIL for prior in existing_pad_centers):
            raise AssertionError(f"{reference}: extra PTH already exists as a footprint PAD at {local}")
        header = {
            "type": "PAD",
            "ticket": max_ticket + index,
            "id": f"e{max_element_id + index}",
            "firstTicket": max_first_ticket + index,
        }
        body = copy.deepcopy(target_body)
        body.update({
            "netName": "",
            "num": config["pad_number"],
            "centerX": local[0],
            "centerY": local[1],
            "hole": {"holeType": "ROUND", "width": 11.811, "height": 11.811},
            "defaultPad": {"padType": "ELLIPSE", "width": 23.622047, "height": 23.622047},
            "specialPad": [],
            "zIndex": max_z + index,
            "unusedInnerLayers": [],
        })
        new_records.append(f"{compact(header)}||{compact(body)}|")
        additions.append({
            "record_id": header["id"],
            "ticket": header["ticket"],
            "first_ticket": header["firstTicket"],
            "pad_number": body["num"],
            "source_at_mm": evidence["source_at_mm"],
            "footprint_local_center_mil_y_up": local,
            "layer_id": body["layerId"],
            "net_name_in_library_source": body["netName"],
            "hole": body["hole"],
            "default_pad": body["defaultPad"],
            "plated": body["plated"],
            "unused_inner_layers": body["unusedInnerLayers"],
        })

    insert_at = next(
        index for index, raw in enumerate(base_lines)
        if parse_record(raw, reference, index + 1)[0].get("type") == "META"
    )
    output_lines = [*base_lines[:insert_at], *new_records, *base_lines[insert_at:]]
    output = VALIDATION / config["output"]
    output.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")

    output_parsed = [parse_record(raw, output.name, i) for i, raw in enumerate(output_lines, 1)]
    counts_before = Counter(str(header.get("type")) for header, _ in parsed)
    counts_after = Counter(str(header.get("type")) for header, _ in output_parsed)
    if counts_after != counts_before + Counter({"PAD": 4}):
        raise AssertionError(f"{reference}: candidate type counts changed unexpectedly")
    base_by_key = {(str(header.get("type")), str(header.get("id"))): body for header, body in parsed}
    output_by_key = {(str(header.get("type")), str(header.get("id"))): body for header, body in output_parsed}
    for key, body in base_by_key.items():
        if output_by_key.get(key) != body:
            raise AssertionError(f"{reference}: protected existing body changed: {key}")
    element_headers = [
        header for header, _ in output_parsed
        if re.fullmatch(r"e\d+", str(header.get("id")))
    ]
    element_ids = [str(header["id"]) for header in element_headers]
    if len(element_ids) != len(set(element_ids)):
        raise AssertionError(f"{reference}: candidate has duplicate element IDs")
    order_keys = [int(header.get("firstTicket", header["ticket"])) for header, _ in output_parsed[1:]]
    if order_keys != sorted(order_keys) or len(order_keys) != len(set(order_keys)):
        raise AssertionError(f"{reference}: native firstTicket/ticket document order is not strict")
    expected_new_first_tickets = list(range(max_first_ticket + 1, max_first_ticket + 5))
    actual_new_first_tickets = [item["first_ticket"] for item in additions]
    if actual_new_first_tickets != expected_new_first_tickets:
        raise AssertionError(f"{reference}: new primitive firstTicket sequence changed")
    return {
        "candidate": str(output.relative_to(ROOT)),
        "candidate_sha256": sha256(output),
        "base_source": {
            "checkpoint": str(CHECKPOINT.relative_to(ROOT)),
            "checkpoint_member": CHECKPOINT_MEMBER,
            "footprint_uuid": config["uuid"],
            "footprint_block_sha256": sha256_text(base_lines),
        },
        "record_counts_before": dict(sorted(counts_before.items())),
        "record_counts_after": dict(sorted(counts_after.items())),
        "protected_existing_record_bodies_changed": 0,
        "element_ids_unique": True,
        "native_document_order_strict": True,
        "previous_primitive_order_max": max_first_ticket,
        "added_primitive_first_tickets": actual_new_first_tickets,
        "central_special_pad_record_id": target_header["id"],
        "central_special_pad_preserved": target_body["specialPad"],
        "added_pad_records": additions,
    }


def main() -> int:
    special_plan = json.loads(SPECIAL_PLAN.read_text(encoding="utf-8"))
    special_by_ref = {item["reference"]: item for item in special_plan["footprints"]}
    copper = {
        layer: parse_gerber(GERBER_DIR / filename, layer)
        for layer, filename in COPPER_FILES.items()
    }
    pth_path = GERBER_DIR / "MCU_BOARD_v19_260616-PTH.drl"
    pth = parse_drill(pth_path, True)
    routes = json.loads(ROUTES.read_text(encoding="utf-8"))
    pcb = native_records(PCB_SOURCE)
    pcb_counts = Counter(str(header.get("type")) for header, _ in pcb)
    drc = json.loads(POST_SPECIAL_DRC.read_text(encoding="utf-8"))
    authoritative_footprints = checkpoint_footprints()
    duplicate_binding = duplicate_pad_binding_evidence()

    bounds = routes["coordinateTransform"]["boardBoundsSourceMm"]
    board_min_x, board_min_y = finite(bounds[0]), finite(bounds[1])
    existing_vias = [body for header, body in pcb if header.get("type") == "VIA"]
    top_level_pads = [body for header, body in pcb if header.get("type") == "PAD"]
    existing_fills = [
        (str(header.get("id")), body)
        for header, body in pcb if header.get("type") == "FILL"
    ]
    route_vias = routes["copper"]["vias"]
    drc_rows = list(drc_leaves(drc.get("details", [])))
    reports: list[dict[str, Any]] = []
    all_extra_world: list[list[float]] = []

    for reference, config in TARGETS.items():
        center = [finite(value) for value in config["center_mm"]]
        size = finite(config["top_size_mm"])
        holes_in_exposed_pad = [
            hole for hole in pth["holes"]
            if hole.get("kind") != "slot"
            and abs(finite(hole["atMm"][0]) - center[0]) <= size / 2 + COORD_TOLERANCE_MM
            and abs(finite(hole["atMm"][1]) - center[1]) <= size / 2 + COORD_TOLERANCE_MM
        ]
        if len(holes_in_exposed_pad) != 5:
            raise AssertionError(f"{reference}: expected central + four extra PTHs")
        central = [hole for hole in holes_in_exposed_pad if math.dist(hole["atMm"], center) <= COORD_TOLERANCE_MM]
        extras = [hole for hole in holes_in_exposed_pad if math.dist(hole["atMm"], center) > COORD_TOLERANCE_MM]
        if len(central) != 1 or len(extras) != 4:
            raise AssertionError(f"{reference}: exposed-pad PTH split is not 1+4")

        extra_reports: list[dict[str, Any]] = []
        for hole in sorted(extras, key=lambda item: tuple(item["atMm"])):
            if (
                hole.get("tool") != "T4" or not close(hole.get("diameterMm"), 0.3, 0.000001)
                or hole.get("function") != "Plated,PTH,ComponentDrill" or hole.get("plated") is not True
            ):
                raise AssertionError(f"{reference}: extra drill contract changed: {hole}")
            same_drill_hits = [
                candidate for candidate in pth["holes"]
                if candidate.get("kind") != "slot"
                and math.dist(candidate["atMm"], hole["atMm"]) <= COORD_TOLERANCE_MM
            ]
            if len(same_drill_hits) != 1:
                raise AssertionError(f"{reference}: duplicated PTH source coordinate {hole['atMm']}")

            layer_evidence: dict[str, dict[str, Any]] = {}
            for layer, data in copper.items():
                flashes = dark_flashes_at(data, hole["atMm"])
                matches = [
                    item for item in flashes
                    if item["template"] == "C"
                    and item["params_mm"] == [0.6]
                    and item["aperture_function"] == "ComponentPad"
                    and item["attrs"].get("N") == "GND"
                ]
                if len(matches) != 1:
                    raise AssertionError(f"{reference} {hole['atMm']}: {layer} ComponentPad mismatch {flashes}")
                if layer in {"F.Cu", "B.Cu"} and matches[0]["attrs"].get("P") != f",{config['pad_number']}":
                    raise AssertionError(f"{reference}: outer-layer pin attribute changed")
                layer_evidence[layer] = matches[0]

            if any(math.dist(via["atMm"], hole["atMm"]) <= COORD_TOLERANCE_MM for via in route_vias):
                raise AssertionError(f"{reference}: extra PTH already exists in Gerber route VIA manifest")
            world = [
                clean((finite(hole["atMm"][0]) - board_min_x) * MM_TO_MIL, 4),
                clean((finite(hole["atMm"][1]) - board_min_y) * MM_TO_MIL, 4),
            ]
            all_extra_world.append(world)
            matching_native_vias = [
                body for body in existing_vias
                if math.dist([finite(body["centerX"]), finite(body["centerY"])], world) <= COORD_TOLERANCE_MIL
            ]
            matching_top_pads = [
                body for body in top_level_pads
                if math.dist([finite(body["centerX"]), finite(body["centerY"])], world) <= COORD_TOLERANCE_MIL
            ]
            if matching_native_vias or matching_top_pads:
                raise AssertionError(f"{reference}: board already has VIA/PAD at {world}")

            fill_evidence: dict[str, dict[str, Any]] = {}
            for layer, layer_id in INNER_LAYER_IDS.items():
                matches = []
                for primitive_id, body in existing_fills:
                    circle = circle_path(body)
                    if circle is None or body.get("layerId") != layer_id or body.get("netName") != "GND":
                        continue
                    if math.dist([circle[0], circle[1]], world) <= COORD_TOLERANCE_MIL and close(circle[2], 11.811, 0.001):
                        matches.append({"primitive_id": primitive_id, "layer_id": layer_id, "circle_mil": list(circle)})
                if len(matches) != 1:
                    raise AssertionError(f"{reference}: expected one preserved inner FILL on {layer} at {world}")
                fill_evidence[layer] = matches[0]

            drc_matches = []
            inner_fill_ids = {item["primitive_id"] for item in fill_evidence.values()}
            for row in drc_rows:
                err = row["explanation"]["errData"]
                objects = {str(value) for value in row.get("objs", [])}
                if objects & inner_fill_ids:
                    drc_matches.append({
                        "global_index": row.get("globalIndex"),
                        "error_type": row.get("errorType"),
                        "object_type": row.get("errorObjType"),
                        "layer": row.get("layer"),
                        "layer_ids": err.get("layerIds"),
                        "objects": row.get("objs"),
                        "net": err.get("net"),
                    })
            extra_reports.append({
                "source_at_mm": hole["atMm"],
                "native_world_center_mil_y_up": world,
                "drill": hole,
                "copper_by_layer": layer_evidence,
                "existing_route_via_matches": 0,
                "existing_native_via_matches": 0,
                "existing_top_level_pad_matches": 0,
                "preserved_inner_fill_primitives": fill_evidence,
                "post_special_pad_connection_findings": drc_matches,
            })

        frozen = special_by_ref[reference]
        base_lines = authoritative_footprints.get(config["uuid"])
        if base_lines is None:
            raise AssertionError(f"{reference}: authoritative checkpoint lacks footprint {config['uuid']}")
        candidate = add_candidate_pads(reference, config, base_lines, extra_reports)
        reports.append({
            "reference": reference,
            "actual_project_library_uuid": frozen["actual_project_library_uuid"],
            "pad_number": config["pad_number"],
            "top_exposed_pad_center_mm": center,
            "top_exposed_pad_size_mm": size,
            "central_pth": central[0],
            "extra_thermal_pths": extra_reports,
            **candidate,
        })

    connection_rows = [row for row in drc_rows if row.get("errorType") == "Connection Error"]
    if drc.get("counts", {}).get("Connection Error") != 16 or len(connection_rows) != 16:
        raise AssertionError("post-special-pad DRC no longer preserves the 16 missing-PTH correlations")
    target_fill_ids = {
        item["primitive_id"]
        for report in reports
        for extra in report["extra_thermal_pths"]
        for layer, item in extra["preserved_inner_fill_primitives"].items()
        if layer in {"In1.Cu", "In2.Cu"}
    }
    connection_object_ids = {
        str(obj)
        for row in connection_rows
        for obj in row.get("objs", [])
    }
    if connection_object_ids != target_fill_ids:
        raise AssertionError("Connection16 is not exactly the eight missing PTHs on In1/In2")

    report = {
        "status": "pass-candidates-approved-for-scoped-u5-pilot-not-applied",
        "purpose": "Restore eight Gerber-proved U5/U7 thermal component PTH pads",
        "inputs": {
            "authoritative_checkpoint": {
                "path": str(CHECKPOINT.relative_to(ROOT)),
                "sha256": sha256(CHECKPOINT),
                "member": CHECKPOINT_MEMBER,
            },
            "special_pad_plan": {"path": str(SPECIAL_PLAN.relative_to(ROOT)), "sha256": sha256(SPECIAL_PLAN)},
            "pth_drill": {"path": str(pth_path.relative_to(ROOT)), "sha256": sha256(pth_path)},
            "raw_copper_gerbers": {
                layer: {"path": str((GERBER_DIR / filename).relative_to(ROOT)), "sha256": sha256(GERBER_DIR / filename)}
                for layer, filename in COPPER_FILES.items()
            },
            "route_manifest": {"path": str(ROUTES.relative_to(ROOT)), "sha256": sha256(ROUTES)},
            "reopened_pcb_source": {"path": str(PCB_SOURCE.relative_to(ROOT)), "sha256": sha256(PCB_SOURCE)},
            "post_special_pad_drc": {"path": str(POST_SPECIAL_DRC.relative_to(ROOT)), "sha256": sha256(POST_SPECIAL_DRC)},
        },
        "coordinate_contract": {
            "native_board": "mil, Y-up",
            "world_formula": "(sourceMm - boardMinMm) * 1000/25.4",
            "footprint_local_formula": "(sourceMm - exposedPadCenterMm) * 1000/25.4",
        },
        "source_semantics": {
            "drill_function": "Plated,PTH,ComponentDrill",
            "copper_aperture_function_all_six_layers": "ComponentPad",
            "outer_copper_pin_attributes": [",25", ",33"],
            "net": "GND",
            "copper_diameter_mm": 0.6,
            "hole_diameter_mm": 0.3,
            "preferred_model": "four additional duplicate-number plated multilayer PADs in each owning footprint",
            "via_fallback": "physically/electrically exact but semantically weaker because it does not move with U5/U7",
        },
        "installed_duplicate_number_padnet_binding": duplicate_binding,
        "footprints": reports,
        "native_board_before_repair": {
            "record_type_counts": dict(sorted(pcb_counts.items())),
            "via_count": pcb_counts["VIA"],
            "top_level_pad_count": pcb_counts["PAD"],
            "extra_target_via_or_pad_matches": 0,
            "post_special_pad_drc_counts": drc["counts"],
            "connection_findings_exactly_explained": 16,
        },
        "totals": {
            "raw_pth_round_hits": pth["summary"]["roundHits"],
            "raw_pth_routed_slots": pth["summary"]["routedSlots"],
            "existing_route_vias": len(route_vias),
            "target_footprints": 2,
            "existing_central_component_pths": 2,
            "omitted_extra_component_pths": len(all_extra_world),
            "raw_copper_flashes_proved": len(all_extra_world) * 6,
            "candidate_added_pad_records": 8,
            "post_special_pad_connection_findings": 16,
        },
        "checks": {
            "eight_unique_t4_0_3mm_plated_component_drills": True,
            "all_48_copper_flashes_are_dark_0_6mm_component_pads_on_gnd": True,
            "f_b_pin_attributes_tie_holes_to_pad25_or_pad33": True,
            "no_existing_route_or_native_via_or_top_level_pad_at_centers": True,
            "all_32_inner_flash_fills_preserved_in_native_board": True,
            "connection16_equals_in1_in2_flashes_for_exact_eight_centers": True,
            "candidate_adds_only_eight_new_pad_records": True,
            "all_existing_footprint_record_bodies_preserved": True,
            "central_specialPad_repairs_preserved": True,
        },
        "application_gate": {
            "approved": "U5 scoped pilot only",
            "reason": "Installed 3.2 footprint-update code explicitly inherits an existing same-number PAD_NET to new child IDs; runtime persistence remains the mandatory pilot check.",
            "sequence": [
                "Apply only the complete U5 candidate with LIB_Footprint.updateDocumentSource; never set the full PCB source.",
                "Close and reopen the final PCB cache, then require total runtime pads 1184 and five U5 pad-25 children (central plus four new), all GND.",
                "Require child-specific PAD_NET records for all four new U5 suffixes after reopen and Connection Error count to fall from 16 to 8.",
                "Only then apply U7; after reopen require total runtime pads 1188, five U7 pad-33 children all GND, and Connection Error count 0.",
                "Do not use global routing VIAs for component-owned thermal drills.",
            ],
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT.relative_to(ROOT)),
        "sha256": sha256(REPORT),
        "candidates": [
            {"reference": item["reference"], "path": item["candidate"], "sha256": item["candidate_sha256"]}
            for item in reports
        ],
        "totals": report["totals"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
