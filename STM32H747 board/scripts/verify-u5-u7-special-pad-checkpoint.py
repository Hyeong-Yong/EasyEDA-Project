"""Audit the applied U5/U7 per-layer thermal-pad repair.

This script never calls an EasyEDA API.  It has two read-only modes:

* ``--snapshot-baseline-only`` preserves the two known pre-fix DRC findings
  that are caused by the oversized U5/U7 default pad being repeated on Inner2;
* normal mode compares the authoritative before/after project checkpoints,
  the documented ``getState_SpecialPad()`` runtime capture, the reopened PCB
  source, the frozen Gerber-derived repair plan, and the post-fix DRC result.

The footprint comparison is deliberately strict: within U5 and U7, only the
target PAD's ``specialPad`` body field may change.  Ticket renumbering and the
normal DOCHEAD version/updateTime pair are the only accepted serialization
normalizations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_BEFORE = ROOT / "output/checkpoints/STM32H747_after_drl_slot_fix_20261014.epro2"
DEFAULT_PLAN = ROOT / "output/validation/u5-u7-special-pad-fix-plan.json"
DEFAULT_GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
DEFAULT_BASELINE_PCB = ROOT / "output/validation/native-final-pcb-after_drl_slot_fix-reopened.epru"
DEFAULT_BASELINE_DRC = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
DEFAULT_BASELINE_REPORT = ROOT / "output/validation/u5-u7-special-pad-pre-fix-drc.json"
DEFAULT_REPORT = ROOT / "output/validation/u5-u7-special-pad-checkpoint-audit.json"

FROZEN_PLAN_SHA256 = "b7837332340755c53a1da7588b973bb6a4716ed67fce097ea8c65ff8c02b5875"
MM_TO_MIL = 1000.0 / 25.4
NUMBER_TOLERANCE_MIL = 0.00016
# Installed EasyEDA 3.2 public pad getters quantize shape dimensions to one
# decimal mil (for example 23.622047 -> 23.6).  Keep the authoritative source
# comparison above at NUMBER_TOLERANCE_MIL; this wider tolerance applies only
# to values returned by the documented runtime getters.
RUNTIME_SHAPE_TOLERANCE_MIL = 0.051
RUNTIME_CENTER_TOLERANCE_MIL = 0.071


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number {value!r}")
    return result


def close(left: Any, right: Any, tolerance: float = NUMBER_TOLERANCE_MIL) -> bool:
    return abs(finite(left) - finite(right)) <= tolerance


def rounded(value: Any, digits: int = 9) -> int | float:
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


def compact_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def native_lines_hash(lines: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def input_record(path: Path) -> dict[str, Any]:
    return {"path": display_path(path), "sha256": sha256(path)}


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path}: top-level JSON value must be an object")
    return value


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        body_text = body_text[:-1] if body_text.endswith("|") else body_text
        return json.loads(header_text), json.loads(body_text)
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def read_native_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
    ]


def checkpoint_footprints(path: Path) -> dict[str, list[str]]:
    with zipfile.ZipFile(path) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current: list[str] = []
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, f"{path.name}:{MEMBER}", line_number)
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


def keyed_records(
    lines: Sequence[str], label: str
) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, label, line_number)
        key = (str(header.get("type")), str(header.get("id")))
        if key in result:
            raise AssertionError(f"{label}: duplicate record key {key}")
        result[key] = (header, body)
    return result


def native_component_map(path: Path) -> tuple[dict[str, str], Counter[str], str]:
    records = read_native_records(path)
    counts = Counter(str(header.get("type")) for header, _ in records)
    result: dict[str, str] = {}
    document_uuids = {
        str(body.get("uuid"))
        for header, body in records
        if header.get("type") == "DOCHEAD" and body.get("docType") == "PCB"
    }
    if len(document_uuids) != 1:
        raise AssertionError(f"{path}: expected one PCB DOCHEAD UUID, got {sorted(document_uuids)}")
    for header, body in records:
        if header.get("type") == "ATTR" and body.get("key") == "Designator":
            result[str(body.get("value"))] = str(body.get("parentId"))
    return result, counts, next(iter(document_uuids))


def assert_header_normalization(
    reference: str,
    key: tuple[str, str],
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any] | None:
    if before == after:
        return None
    differing = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    if differing != ["ticket"]:
        raise AssertionError(f"{reference} {key}: unsupported header changes {differing}")
    return {
        "type": key[0],
        "id": key[1],
        "before_ticket": before.get("ticket"),
        "after_ticket": after.get("ticket"),
    }


def shape_object_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if set(left) != set(right):
        return False
    for name in left:
        if name in {"width", "height", "radius"}:
            if not close(left[name], right[name]):
                return False
        elif left[name] != right[name]:
            return False
    return True


def special_pad_object_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return False
    for actual, expected in zip(left, right):
        if not isinstance(actual, dict) or not isinstance(expected, dict):
            return False
        if actual.get("startLayer") != expected.get("startLayer"):
            return False
        if actual.get("endLayer") != expected.get("endLayer"):
            return False
        if not shape_object_equal(actual.get("pad"), expected.get("pad")):
            return False
    return True


def verify_footprint(
    reference: str,
    before_lines: Sequence[str],
    after_lines: Sequence[str],
    planned: dict[str, Any],
) -> dict[str, Any]:
    before = keyed_records(before_lines, f"before:{reference}")
    after = keyed_records(after_lines, f"after:{reference}")
    if set(before) != set(after):
        missing = sorted(set(before) - set(after))
        unexpected = sorted(set(after) - set(before))
        raise AssertionError(f"{reference}: record identity/type set changed: missing={missing}, unexpected={unexpected}")

    type_counts = Counter(kind for kind, _ in after)
    if dict(sorted(type_counts.items())) != planned["record_type_counts"]:
        raise AssertionError(f"{reference}: record type counts changed: {dict(type_counts)}")

    modification = planned["modification"]
    target_key = ("PAD", str(modification["record_id"]))
    if target_key not in before:
        raise AssertionError(f"{reference}: planned target {target_key} missing")

    reticketed: list[dict[str, Any]] = []
    dochead_normalizations: list[str] = []
    changed_target_records = 0
    exact_body_records = 0
    for key in sorted(before):
        before_header, before_body = before[key]
        after_header, after_body = after[key]
        header_change = assert_header_normalization(reference, key, before_header, after_header)
        if header_change is not None:
            reticketed.append(header_change)

        if key[0] == "DOCHEAD":
            changed = sorted(
                name for name in set(before_body) | set(after_body)
                if before_body.get(name) != after_body.get(name)
            )
            if changed != ["updateTime", "version"]:
                raise AssertionError(f"{reference}: unsupported DOCHEAD normalization {changed}")
            if after_body.get("updateTime") != int(after_body["version"]):
                raise AssertionError(f"{reference}: DOCHEAD updateTime/version pair is inconsistent")
            left, right = dict(before_body), dict(after_body)
            for name in changed:
                left.pop(name, None)
                right.pop(name, None)
            if left != right:
                raise AssertionError(f"{reference}: protected DOCHEAD fields changed")
            dochead_normalizations = changed
            continue

        if key == target_key:
            changed_fields = sorted(
                name for name in set(before_body) | set(after_body)
                if before_body.get(name) != after_body.get(name)
            )
            if changed_fields != ["specialPad"]:
                raise AssertionError(f"{reference} {key[1]}: changed fields {changed_fields}")
            if before_body.get("specialPad") != modification["before_special_pad"]:
                raise AssertionError(f"{reference}: target before-specialPad differs from frozen plan")
            if not special_pad_object_equal(after_body.get("specialPad"), modification["after_special_pad"]):
                raise AssertionError(f"{reference}: persisted specialPad differs from frozen plan")
            for name in set(before_body) | set(after_body):
                if name != "specialPad" and before_body.get(name) != after_body.get(name):
                    raise AssertionError(f"{reference}: protected PAD field changed: {name}")
            if after_body.get("defaultPad") != modification["default_top_pad_preserved"]:
                raise AssertionError(f"{reference}: top defaultPad changed")
            if after_body.get("hole") != modification["hole_preserved"]:
                raise AssertionError(f"{reference}: plated drill changed")
            if after_body.get("plated") is not True:
                raise AssertionError(f"{reference}: target pad is no longer plated")
            if after_body.get("unusedInnerLayers") != modification["unused_inner_layers_preserved"]:
                raise AssertionError(f"{reference}: unusedInnerLayers changed")
            changed_target_records += 1
        elif before_body != after_body:
            raise AssertionError(f"{reference} {key}: non-target body changed")
        else:
            exact_body_records += 1

    if changed_target_records != 1:
        raise AssertionError(f"{reference}: expected one changed target PAD")
    return {
        "reference": reference,
        "footprint_uuid": planned["actual_project_library_uuid"],
        "record_count": len(after),
        "record_type_counts": dict(sorted(type_counts.items())),
        "record_identity_and_type_set_preserved": True,
        "changed_target_pad_id": modification["record_id"],
        "changed_fields": ["specialPad"],
        "non_target_body_changes": 0,
        "exact_non_dochead_non_target_bodies": exact_body_records,
        "top_default_pad_preserved": after[target_key][1]["defaultPad"],
        "round_plated_hole_preserved": after[target_key][1]["hole"],
        "unused_inner_layers_preserved": after[target_key][1]["unusedInnerLayers"],
        "special_pad": after[target_key][1]["specialPad"],
        "special_pad_hash": compact_hash(after[target_key][1]["specialPad"]),
        "serializer_normalization": {
            "reticketed_headers": reticketed,
            "dochead_changed_fields": dochead_normalizations,
        },
    }


def iter_drc_leaves(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        explanation = value.get("explanation")
        if isinstance(explanation, dict) and isinstance(explanation.get("errData"), dict):
            yield value
        for child in value.values():
            yield from iter_drc_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_drc_leaves(child)


def target_drc_findings(drc: dict[str, Any], target_ids: dict[str, str]) -> list[dict[str, Any]]:
    by_id = {primitive_id: reference for reference, primitive_id in target_ids.items()}
    findings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for leaf in iter_drc_leaves(drc.get("details", [])):
        err = leaf["explanation"]["errData"]
        objects = {str(value) for value in leaf.get("objs", [])}
        objects.update(str(err.get(name)) for name in ("obj1", "obj2") if err.get(name) is not None)
        matches = sorted(objects & set(by_id))
        if not matches:
            continue
        global_index = str(leaf.get("globalIndex") or err.get("globalIndex"))
        if global_index in seen:
            continue
        seen.add(global_index)
        primitive_id = matches[0]
        findings.append({
            "reference": by_id[primitive_id],
            "target_primitive_id": primitive_id,
            "global_index": global_index,
            "error_type": leaf.get("errorType"),
            "object_type": leaf.get("errorObjType"),
            "layer": leaf.get("layer"),
            "layer_ids": err.get("layerIds"),
            "obj1": leaf.get("obj1"),
            "obj2": leaf.get("obj2"),
            "min_distance_native": err.get("minDistance"),
            "clearance_native": err.get("clearance"),
            "position": err.get("position"),
        })
    return findings


def expected_runtime_shape(special_pad_object: list[dict[str, Any]]) -> list[list[Any]]:
    result: list[list[Any]] = []
    for item in special_pad_object:
        pad = item["pad"]
        shape = [pad["padType"], pad["width"], pad["height"]]
        if pad["padType"] == "RECT":
            shape.append(pad["radius"])
        result.append([item["startLayer"], item["endLayer"], shape])
    return result


def runtime_shape_equal(actual: Any, expected: Any) -> bool:
    if not isinstance(actual, list) or not isinstance(expected, list) or len(actual) != len(expected):
        return False
    for actual_item, expected_item in zip(actual, expected):
        if not isinstance(actual_item, list) or len(actual_item) != 3:
            return False
        if actual_item[0] != expected_item[0] or actual_item[1] != expected_item[1]:
            return False
        actual_shape, expected_shape = actual_item[2], expected_item[2]
        if not isinstance(actual_shape, list) or len(actual_shape) != len(expected_shape):
            return False
        if actual_shape[0] != expected_shape[0]:
            return False
        if not all(
            close(left, right, RUNTIME_SHAPE_TOLERANCE_MIL)
            for left, right in zip(actual_shape[1:], expected_shape[1:])
        ):
            return False
    return True


def runtime_rows(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    for name in ("selected", "pads", "specialPads"):
        value = runtime.get(name)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [item for item in value.values() if isinstance(item, dict)]
    raise AssertionError("runtime JSON must contain selected/pads/specialPads rows")


def find_runtime_row(
    rows: Sequence[dict[str, Any]], reference: str, pad_number: str, primitive_id: str
) -> dict[str, Any]:
    matches = [item for item in rows if str(item.get("id")) == primitive_id]
    if len(matches) != 1:
        raise AssertionError(
            f"runtime row {reference}.{pad_number}/{primitive_id}: expected one match, got {len(matches)}"
        )
    row = matches[0]
    if str(row.get("reference")) != reference:
        raise AssertionError(f"runtime row {primitive_id}: reference mismatch {row.get('reference')!r}")
    if str(row.get("padNumber") or row.get("pad_number")) != pad_number:
        raise AssertionError(f"runtime row {primitive_id}: pad number mismatch")
    return row


def verify_runtime(
    runtime: dict[str, Any],
    footprint_plans: dict[str, dict[str, Any]],
    component_ids: dict[str, str],
    gerber: dict[str, Any],
) -> list[dict[str, Any]]:
    if runtime.get("totalPads") != 1180:
        raise AssertionError(f"runtime totalPads changed: {runtime.get('totalPads')}")
    rows = runtime_rows(runtime)
    bounds = gerber["coordinateTransform"]["boardBoundsSourceMm"]
    board_min_x, board_min_y = finite(bounds[0]), finite(bounds[1])
    reports: list[dict[str, Any]] = []

    for reference in ("U5", "U7"):
        planned = footprint_plans[reference]
        modification = planned["modification"]
        pad_number = str(modification["pad_number"])
        primitive_id = component_ids[reference] + str(modification["record_id"])
        row = find_runtime_row(rows, reference, pad_number, primitive_id)
        actual_special = row.get("specialPad")
        expected_special = expected_runtime_shape(modification["after_special_pad"])
        if not runtime_shape_equal(actual_special, expected_special):
            raise AssertionError(
                f"{reference}: documented getState_SpecialPad() result mismatch: {actual_special!r}"
            )

        actual_pad = row.get("pad")
        expected_default = modification["default_top_pad_preserved"]
        expected_pad = [
            expected_default["padType"], expected_default["width"],
            expected_default["height"], expected_default["radius"],
        ]
        if not isinstance(actual_pad, list) or len(actual_pad) != 4:
            raise AssertionError(f"{reference}: runtime default pad is not a RECT tuple")
        if actual_pad[0] != expected_pad[0] or not all(
            close(left, right, RUNTIME_SHAPE_TOLERANCE_MIL)
            for left, right in zip(actual_pad[1:], expected_pad[1:])
        ):
            raise AssertionError(f"{reference}: runtime default pad changed: {actual_pad}")

        actual_hole = row.get("hole")
        expected_hole = modification["hole_preserved"]
        if (
            not isinstance(actual_hole, list) or len(actual_hole) != 3
            or actual_hole[0] != "ROUND"
            or not close(actual_hole[1], expected_hole["width"], RUNTIME_SHAPE_TOLERANCE_MIL)
            or not close(actual_hole[2], expected_hole["height"], RUNTIME_SHAPE_TOLERANCE_MIL)
        ):
            raise AssertionError(f"{reference}: runtime plated hole changed: {actual_hole}")
        if row.get("layer") != 12 or row.get("plated") is not True:
            raise AssertionError(f"{reference}: runtime target is not a plated multilayer PAD")
        if str(row.get("net")) != "GND":
            raise AssertionError(f"{reference}: runtime target net is not GND: {row.get('net')}")

        source_center = planned["gerber"]["pad_center_mm"]
        expected_world = [
            (finite(source_center[0]) - board_min_x) * MM_TO_MIL,
            (finite(source_center[1]) - board_min_y) * MM_TO_MIL,
        ]
        actual_world = [finite(row["x"]), finite(row["y"])]
        center_error = math.dist(expected_world, actual_world)
        if center_error > RUNTIME_CENTER_TOLERANCE_MIL:
            raise AssertionError(f"{reference}: runtime center differs from Gerber by {center_error} mil")
        reports.append({
            "reference": reference,
            "pad_number": pad_number,
            "runtime_primitive_id": primitive_id,
            "gerber_source_center_mm": source_center,
            "expected_world_center_mil_y_up": [rounded(value, 7) for value in expected_world],
            "runtime_world_center_mil_y_up": actual_world,
            "runtime_center_error_mil": rounded(center_error),
            "runtime_default_pad": actual_pad,
            "runtime_hole": actual_hole,
            "runtime_layer": row["layer"],
            "runtime_plated": row["plated"],
            "runtime_net": row["net"],
            "documented_getState_SpecialPad_result": actual_special,
        })
    return reports


def snapshot_baseline(args: argparse.Namespace) -> int:
    designators, counts, pcb_uuid = native_component_map(args.pcb_source)
    if any(reference not in designators for reference in ("U5", "U7")):
        raise AssertionError("baseline PCB source lacks U5/U7 Designator attributes")
    plan = read_json(args.plan)
    plans = {item["reference"]: item for item in plan["footprints"]}
    target_ids = {
        reference: designators[reference] + str(plans[reference]["modification"]["record_id"])
        for reference in ("U5", "U7")
    }
    drc = read_json(args.drc)
    if str(drc.get("pcbUuid")) != pcb_uuid:
        raise AssertionError(f"baseline PCB source/DRC UUID mismatch: {pcb_uuid} != {drc.get('pcbUuid')}")
    findings = target_drc_findings(drc, target_ids)
    if len(findings) != 2 or Counter(item["reference"] for item in findings) != Counter({"U5": 1, "U7": 1}):
        raise AssertionError(f"expected one pre-fix DRC finding per target, got {findings}")
    for item in findings:
        if (
            item["error_type"] != "Clearance Error"
            or item["object_type"] != "Fill Region to TH Pad"
            or item["layer"] != "Inner2"
            or item["layer_ids"] != [16]
            or not close(item["min_distance_native"], 0)
        ):
            raise AssertionError(f"unexpected target pre-fix DRC anatomy: {item}")
    report = {
        "status": "pass-baseline-snapshot",
        "purpose": "Preserve the two U5/U7 oversized-inner-pad DRC correlations before applying specialPad",
        "inputs": {
            "frozen_plan": input_record(args.plan),
            "reopened_pcb_source": input_record(args.pcb_source),
            "pre_fix_drc": input_record(args.drc),
        },
        "pcb_uuid": pcb_uuid,
        "pre_fix_drc_total": drc.get("violations"),
        "pre_fix_drc_counts": drc.get("counts"),
        "pcb_record_type_counts": dict(sorted(counts.items())),
        "component_ids": {reference: designators[reference] for reference in ("U5", "U7")},
        "target_primitive_ids": target_ids,
        "target_findings": findings,
        "target_finding_count": len(findings),
        "checks": {
            "one_inner2_layer16_zero_distance_finding_per_target": True,
            "target_ids_derived_from_reopened_pcb_designators": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": display_path(args.output),
        "sha256": sha256(args.output),
        "target_findings": len(findings),
        "drc_total": drc.get("violations"),
    }, ensure_ascii=False, indent=2))
    return 0


def verify_post_apply(args: argparse.Namespace) -> int:
    required = {"after": args.after, "runtime": args.runtime, "pcb_source": args.pcb_source, "drc": args.drc}
    missing = [name for name, path in required.items() if path is None]
    if missing:
        raise SystemExit(f"normal mode requires {', '.join('--' + name.replace('_', '-') for name in missing)}")

    if sha256(args.plan) != FROZEN_PLAN_SHA256:
        raise AssertionError("frozen U5/U7 repair plan hash changed")
    plan = read_json(args.plan)
    planned_checkpoint = plan.get("inputs", {}).get("checkpoint", {})
    if sha256(args.before) != planned_checkpoint.get("sha256"):
        raise AssertionError("--before is not the checkpoint pinned by the frozen repair plan")
    plans = {item["reference"]: item for item in plan["footprints"]}
    if set(plans) != {"U5", "U7"}:
        raise AssertionError(f"frozen plan footprint set changed: {sorted(plans)}")
    for planned in plans.values():
        candidate = ROOT / planned["candidate"]
        if sha256(candidate) != planned["candidate_sha256"]:
            raise AssertionError(f"frozen candidate hash changed: {candidate}")

    before_blocks = checkpoint_footprints(args.before)
    after_blocks = checkpoint_footprints(args.after)
    footprint_reports: list[dict[str, Any]] = []
    for reference in ("U5", "U7"):
        planned = plans[reference]
        uuid = planned["actual_project_library_uuid"]
        if uuid not in before_blocks or uuid not in after_blocks:
            raise AssertionError(f"{reference}: authoritative footprint block {uuid} missing")
        if native_lines_hash(before_blocks[uuid]) != planned["authoritative_checkpoint_block_sha256"]:
            raise AssertionError(f"{reference}: authoritative before-block hash changed")
        footprint_reports.append(
            verify_footprint(reference, before_blocks[uuid], after_blocks[uuid], planned)
        )

    component_ids, pcb_counts, pcb_uuid = native_component_map(args.pcb_source)
    if any(reference not in component_ids for reference in ("U5", "U7")):
        raise AssertionError("reopened PCB source lacks U5/U7 Designator attributes")
    protected_counts = {"COMPONENT": 330, "PAD_NET": 1176, "PAD": 4}
    for name, expected in protected_counts.items():
        if pcb_counts[name] != expected:
            raise AssertionError(f"reopened PCB {name} count {pcb_counts[name]} != {expected}")

    runtime = read_json(args.runtime)
    gerber = read_json(args.gerber)
    runtime_reports = verify_runtime(runtime, plans, component_ids, gerber)

    baseline = read_json(args.baseline_drc)
    if baseline.get("status") != "pass-baseline-snapshot" or baseline.get("target_finding_count") != 2:
        raise AssertionError("baseline report does not preserve two target DRC correlations")
    if str(baseline.get("pcb_uuid")) != pcb_uuid:
        raise AssertionError("reopened PCB UUID changed since baseline snapshot")
    baseline_findings = baseline.get("target_findings") or []
    if (
        len(baseline_findings) != 2
        or Counter(str(item.get("reference")) for item in baseline_findings) != Counter({"U5": 1, "U7": 1})
    ):
        raise AssertionError("baseline target finding identities changed")
    for item in baseline_findings:
        if (
            item.get("error_type") != "Clearance Error"
            or item.get("object_type") != "Fill Region to TH Pad"
            or item.get("layer") != "Inner2"
            or item.get("layer_ids") != [16]
            or not close(item.get("min_distance_native"), 0)
        ):
            raise AssertionError(f"baseline target finding anatomy changed: {item}")
    target_ids = {
        reference: component_ids[reference] + str(plans[reference]["modification"]["record_id"])
        for reference in ("U5", "U7")
    }
    if target_ids != baseline.get("target_primitive_ids"):
        raise AssertionError("target PCB primitive IDs changed since baseline snapshot")
    drc = read_json(args.drc)
    runtime_uuid = str(runtime.get("pcbUuid"))
    drc_uuid = str(drc.get("pcbUuid"))
    if runtime_uuid != pcb_uuid or drc_uuid != pcb_uuid:
        raise AssertionError(
            f"PCB source/runtime/DRC UUID mismatch: {pcb_uuid}, {runtime_uuid}, {drc_uuid}"
        )
    remaining_target_findings = target_drc_findings(drc, target_ids)
    if remaining_target_findings:
        raise AssertionError(f"post-fix DRC still contains U5/U7 target findings: {remaining_target_findings}")
    counts = drc.get("counts") or {}
    if any(name != "Clearance Error" and int(value) != 0 for name, value in counts.items()):
        raise AssertionError(f"post-fix DRC gained a non-clearance category: {counts}")
    if int(counts.get("Connection Error", 0)) != 0:
        raise AssertionError("post-fix DRC connection count is not zero")
    if int(drc.get("violations", -1)) != sum(int(value) for value in counts.values()):
        raise AssertionError("post-fix DRC total does not equal category counts")

    report = {
        "status": "pass",
        "purpose": "Post-apply proof for Gerber-exact U5.25/U7.33 per-layer copper shapes",
        "inputs": {
            "before_checkpoint": input_record(args.before),
            "after_checkpoint": input_record(args.after),
            "frozen_repair_plan": input_record(args.plan),
            "gerber_manifest": input_record(args.gerber),
            "runtime_public_getter_snapshot": input_record(args.runtime),
            "reopened_pcb_source": input_record(args.pcb_source),
            "pre_fix_drc_snapshot": input_record(args.baseline_drc),
            "post_fix_drc": input_record(args.drc),
        },
        "frozen_candidate_sources": {
            reference: {
                "path": plans[reference]["candidate"],
                "sha256": plans[reference]["candidate_sha256"],
            }
            for reference in ("U5", "U7")
        },
        "coordinate_contract": {
            "source": "Gerber absolute millimetres",
            "native_board": "mil, Y-up",
            "formula": "x=(sourceX-boardMinX)*1000/25.4; y=(sourceY-boardMinY)*1000/25.4",
        },
        "public_runtime_contract": {
            "getter": "IPCB_PrimitivePad.getState_SpecialPad()",
            "type": "Array<[startLayer, endLayer, TPCB_PrimitivePadShape]>",
            "undocumented_internal_properties_used": False,
            "frozen_plan_legacy_specialPadShapeAspect_gate_ignored": True,
        },
        "footprints": footprint_reports,
        "runtime_pads": runtime_reports,
        "reopened_pcb": {
            "pcb_uuid": pcb_uuid,
            "record_type_counts": dict(sorted(pcb_counts.items())),
            "component_ids": {reference: component_ids[reference] for reference in ("U5", "U7")},
            "runtime_total_pads": runtime["totalPads"],
        },
        "drc": {
            "before_total": baseline.get("pre_fix_drc_total"),
            "before_counts": baseline.get("pre_fix_drc_counts"),
            "before_target_findings": baseline["target_finding_count"],
            "after_total": drc["violations"],
            "after_counts": counts,
            "after_target_findings": 0,
            "target_finding_delta": -2,
            "connection_errors": int(counts.get("Connection Error", 0)),
        },
        "totals": {
            "footprints": 2,
            "protected_footprint_records": sum(item["record_count"] for item in footprint_reports),
            "changed_pad_records": 2,
            "changed_body_fields": ["specialPad"],
            "non_target_body_changes": 0,
            "runtime_special_pads_verified": len(runtime_reports),
            "gerber_copper_layers_proved_per_pad": 6,
            "max_runtime_center_error_mil": max(item["runtime_center_error_mil"] for item in runtime_reports),
        },
        "checks": {
            "frozen_plan_and_candidate_hashes_preserved": True,
            "full_checkpoint_record_identity_and_types_preserved": True,
            "only_two_target_specialPad_fields_changed": True,
            "all_other_u5_u7_footprint_bodies_preserved": True,
            "top_default_pad_hole_position_plating_and_unused_layers_preserved": True,
            "runtime_public_getter_matches_top_inner_bottom_gerber_shapes": True,
            "runtime_centers_and_gnd_nets_match_gerber": True,
            "reopened_board_has_330_components_and_1180_runtime_pads": True,
            "u5_u7_inner2_clearance_findings_two_to_zero": True,
            "connection_drc_remains_zero": True,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": display_path(args.output),
        "sha256": sha256(args.output),
        "totals": report["totals"],
        "drc": report["drc"],
    }, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-baseline-only", action="store_true")
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--pcb-source", type=Path, default=DEFAULT_BASELINE_PCB)
    parser.add_argument("--drc", type=Path, default=DEFAULT_BASELINE_DRC)
    parser.add_argument("--baseline-drc", type=Path, default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is None:
        args.output = DEFAULT_BASELINE_REPORT if args.snapshot_baseline_only else DEFAULT_REPORT
    for name in ("before", "plan", "gerber", "pcb_source", "drc"):
        path = getattr(args, name)
        if path is not None and not path.is_absolute():
            setattr(args, name, (Path.cwd() / path).resolve())
    for name in ("after", "runtime", "baseline_drc", "output"):
        path = getattr(args, name)
        if path is not None and not path.is_absolute():
            setattr(args, name, (Path.cwd() / path).resolve())
    return args


def main() -> int:
    args = parse_args()
    if args.snapshot_baseline_only:
        return snapshot_baseline(args)
    return verify_post_apply(args)


if __name__ == "__main__":
    raise SystemExit(main())
