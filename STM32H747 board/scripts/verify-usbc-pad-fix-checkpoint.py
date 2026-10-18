"""Verify the applied USB-C polygon-pad repair without calling EasyEDA.

The report proves three independent contracts:

* the authoritative CN3/CN4 footprint blocks still contain the same 48
  records and differ only in the four intended ``defaultPad.path`` values;
* the reopened PCB still contains all 330 components and references the same
  CN3/CN4 component placements; and
* the eight runtime polygon paths coincide with the archived Gerber flashes
  in board-local mil coordinates (Y-up).

The script only reads checkpoint/capture files and writes a derived JSON QA
report.  It never opens or modifies an EasyEDA document.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "output/checkpoints/STM32H747_after_final_pcb_association_20261014.epro2"
AFTER = ROOT / "output/checkpoints/STM32H747_after_usbc_pad_fix_20261014.epro2"
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
GERBER = ROOT / "output/semantic/gerber-component-footprints.json"
RUNTIME = ROOT / "output/validation/native-usbc-runtime-pad-paths.json"
PCB_SOURCE = ROOT / "output/validation/native-final-pcb-after-usbc-pad-fix-reopened.epru"
DRC_BEFORE = ROOT / "output/validation/native-pcb-drc-multilayer-details.json"
DRC_AFTER = ROOT / "output/validation/native-pcb-drc-0ac2a19168000d8e.json"
REPORT = ROOT / "output/validation/usbc-pad-fix-checkpoint-audit.json"

MM_TO_MIL = 1000.0 / 25.4
PATH_TOLERANCE_MIL = 0.00016
CENTER_TOLERANCE_MIL = 0.051

TARGETS = {
    "CN3": {
        "footprint_uuid": "8bd1ebd7c6524c9d",
        "component_id": "1bb54a689e8b2f5b",
    },
    "CN4": {
        "footprint_uuid": "ae37a0fb8459ebec",
        "component_id": "3663918f8e6c2c4f",
    },
}
TARGET_PAD_IDS = {"e1", "e2", "e7", "e8"}
TARGET_PAD_NUMBERS = {"A1_B12", "A4_B9", "B1_A12", "B4_A9"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(lines: Sequence[str]) -> str:
    return hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite value {value!r}")
    return result


def rounded(value: Any, digits: int = 7) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        body_json = body_text[:-1] if body_text.endswith("|") else body_text
        return json.loads(header_text), json.loads(body_json) if body_json else {}
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def checkpoint_blocks(path: Path) -> dict[str, list[str]]:
    with zipfile.ZipFile(path) as archive:
        lines = archive.read(MEMBER).decode("utf-8-sig").splitlines()
    blocks: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current: list[str] = []
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, f"{path.name}:{MEMBER}", line_number)
        if header.get("type") == "DOCHEAD":
            if current_uuid is not None:
                blocks[current_uuid] = current
            current_uuid = str(body.get("uuid")) if body.get("uuid") else None
            current = [raw] if current_uuid is not None else []
        elif current_uuid is not None:
            current.append(raw)
    if current_uuid is not None:
        blocks[current_uuid] = current
    return blocks


def records(lines: Sequence[str], label: str) -> dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]]:
    result: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for line_number, raw in enumerate(lines, 1):
        header, body = parse_record(raw, label, line_number)
        key = (str(header.get("type")), str(header.get("id")))
        if key in result:
            raise ValueError(f"duplicate record identity {key!r} in {label}")
        result[key] = (header, body)
    return result


def read_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
    ]


def line_points(path: Any) -> list[tuple[float, float]]:
    if not isinstance(path, list) or len(path) < 2:
        raise ValueError(f"invalid line path {path!r}")
    result: list[tuple[float, float]] = []
    index = 0
    while index < len(path):
        if isinstance(path[index], str):
            if path[index] != "L":
                raise ValueError(f"unsupported path command {path[index]!r}")
            index += 1
            continue
        if index + 1 >= len(path) or isinstance(path[index + 1], str):
            raise ValueError(f"malformed line path {path!r}")
        result.append((finite(path[index]), finite(path[index + 1])))
        index += 2
    return result


def rotate(point: Sequence[Any], degrees: Any) -> tuple[float, float]:
    angle = math.radians(finite(degrees))
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = finite(point[0]), finite(point[1])
    return x * cosine - y * sine, x * sine + y * cosine


def transformed(points: Iterable[Sequence[Any]], origin: Sequence[Any], degrees: Any = 0) -> list[tuple[float, float]]:
    ox, oy = finite(origin[0]), finite(origin[1])
    return [(ox + rx, oy + ry) for rx, ry in (rotate(point, degrees) for point in points)]


def max_point_error(left: Sequence[Sequence[Any]], right: Sequence[Sequence[Any]]) -> float:
    if len(left) != len(right):
        return math.inf
    return max(
        math.hypot(finite(a[0]) - finite(b[0]), finite(a[1]) - finite(b[1]))
        for a, b in zip(left, right)
    ) if left else 0.0


def bbox(points: Sequence[Sequence[Any]]) -> list[int | float]:
    return [
        rounded(min(finite(point[0]) for point in points), 6),
        rounded(min(finite(point[1]) for point in points), 6),
        rounded(max(finite(point[0]) for point in points), 6),
        rounded(max(finite(point[1]) for point in points), 6),
    ]


def signed_area(points: Sequence[Sequence[Any]]) -> float:
    return 0.5 * sum(
        finite(points[index][0]) * finite(points[(index + 1) % len(points)][1])
        - finite(points[(index + 1) % len(points)][0]) * finite(points[index][1])
        for index in range(len(points))
    )


def semantic_pad_body(body: dict[str, Any], *, omit_polygon_path: bool = False) -> dict[str, Any]:
    """Remove serializer defaults and quantize geometry to runtime precision."""

    value = copy.deepcopy(body)
    if value.get("propagationDelay") in (None, 0):
        value.pop("propagationDelay", None)
    if value.get("attrsMap") in (None, {}):
        value.pop("attrsMap", None)
    if value.get("relativeAngle") in (None, 0):
        value["relativeAngle"] = 0
    if omit_polygon_path and isinstance(value.get("defaultPad"), dict):
        value["defaultPad"].pop("path", None)

    def normalize(item: Any) -> Any:
        if isinstance(item, bool) or item is None or isinstance(item, str):
            return item
        if isinstance(item, (int, float)):
            return rounded(item, 4)
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        return item

    return normalize(value)


def gerber_pad_evidence(component: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for pad_number, pad in component["pads"].items():
        flash = next((item for item in pad.get("flashes", []) if item.get("shape") == "Outline5P"), None)
        if flash is None:
            continue
        params = [finite(value) for value in flash["paramsMm"]]
        if len(params) != 11:
            raise ValueError(f"{pad_number}: expected 11 Outline5P parameters")
        local = [
            (params[index] * MM_TO_MIL, params[index + 1] * MM_TO_MIL)
            for index in range(0, 10, 2)
        ]
        result[str(pad_number)] = {
            "flash": flash,
            "macro_local": local,
            "macro_angle": params[10],
        }
    if set(result) != TARGET_PAD_NUMBERS:
        raise ValueError(f"unexpected Outline5P pad set {sorted(result)}")
    return result


def compare_footprint(
    reference: str,
    before_lines: Sequence[str],
    after_lines: Sequence[str],
    gerber_component: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[tuple[float, float]]]]:
    before = records(before_lines, f"before:{reference}")
    after = records(after_lines, f"after:{reference}")
    if set(before) != set(after):
        raise AssertionError(f"{reference}: footprint record identity set changed")
    types = Counter(kind for kind, _ in after)
    expected_types = {
        "ACTIVE_LAYER": 1, "ATTR": 1, "CANVAS": 1, "DOCHEAD": 1,
        "LAYER": 19, "LINE": 5, "META": 1, "NET": 1, "PAD": 18,
    }
    if dict(types) != expected_types:
        raise AssertionError(f"{reference}: protected record counts changed: {dict(types)}")

    evidence = gerber_pad_evidence(gerber_component)
    anchor = [finite(value) for value in gerber_component["estimatedAnchorMm"]]
    changed: list[dict[str, Any]] = []
    path_by_number: dict[str, list[tuple[float, float]]] = {}
    header_reticketed: list[dict[str, Any]] = []
    pad_default_normalized: list[str] = []
    dochead_version_updates = 0
    hidden_footprint_attr_value_removals = 0
    raw_unchanged_records = 0
    for key in sorted(before):
        before_header, before_body = before[key]
        after_header, after_body = after[key]
        if before_header != after_header:
            before_identity = {name: value for name, value in before_header.items() if name not in {"ticket", "firstTicket"}}
            after_identity = {name: value for name, value in after_header.items() if name not in {"ticket", "firstTicket"}}
            expected_first = before_header.get("firstTicket", before_header.get("ticket"))
            if (
                before_identity != after_identity
                or after_header.get("firstTicket") != expected_first
                or key[0] not in {"PAD", "ATTR"}
            ):
                raise AssertionError(f"{reference}: unsupported header change for {key}")
            header_reticketed.append({
                "type": key[0],
                "id": key[1],
                "before_ticket": before_header.get("ticket"),
                "after_ticket": after_header.get("ticket"),
                "preserved_first_ticket": after_header.get("firstTicket"),
            })
        if before_body == after_body:
            if before_header == after_header:
                raw_unchanged_records += 1
            continue
        kind, record_id = key
        if kind == "DOCHEAD":
            left = copy.deepcopy(before_body)
            right = copy.deepcopy(after_body)
            left.pop("updateTime", None)
            left.pop("version", None)
            right.pop("updateTime", None)
            right.pop("version", None)
            if left != right or after_body.get("updateTime") != int(after_body.get("version")):
                raise AssertionError(f"{reference}: unsupported DOCHEAD change")
            dochead_version_updates += 1
            continue
        if kind == "ATTR":
            left = copy.deepcopy(before_body)
            right = copy.deepcopy(after_body)
            before_value = left.pop("value", None)
            after_value = right.pop("value", None)
            if (
                left != right
                or before_body.get("key") != "Footprint"
                or before_body.get("valueVisible") is not False
                or before_value is None
                or after_value is not None
            ):
                raise AssertionError(f"{reference}: unsupported ATTR change")
            hidden_footprint_attr_value_removals += 1
            continue
        if kind != "PAD":
            raise AssertionError(f"{reference}: non-PAD record body changed: {key}")
        target_pad = record_id in TARGET_PAD_IDS
        if semantic_pad_body(before_body, omit_polygon_path=target_pad) != semantic_pad_body(
            after_body, omit_polygon_path=target_pad
        ):
            raise AssertionError(f"{reference}: non-path PAD semantics changed for {key}")
        if not target_pad:
            pad_default_normalized.append(record_id)
            continue
        pad_number = str(after_body.get("num"))
        if pad_number not in evidence:
            raise AssertionError(f"{reference}: unexpected target pad number {pad_number}")
        before_path = before_body["defaultPad"]["path"]
        after_path = after_body["defaultPad"]["path"]

        pad_evidence = evidence[pad_number]
        expected_center = [
            (finite(pad_evidence["flash"]["atMm"][0]) - anchor[0]) * MM_TO_MIL,
            (finite(pad_evidence["flash"]["atMm"][1]) - anchor[1]) * MM_TO_MIL,
        ]
        expected_path = transformed(
            pad_evidence["macro_local"], expected_center, pad_evidence["macro_angle"]
        )
        actual_path = line_points(after_path)
        footprint_error = max_point_error(actual_path, expected_path)
        if footprint_error > PATH_TOLERANCE_MIL:
            raise AssertionError(
                f"{reference} {pad_number}: footprint path differs from Gerber by {footprint_error} mil"
            )
        if signed_area(actual_path) >= 0:
            raise AssertionError(f"{reference} {pad_number}: winding is not clockwise")
        path_by_number[pad_number] = actual_path
        changed.append({
            "record_id": record_id,
            "pad_number": pad_number,
            "before_path": before_path,
            "after_path": after_path,
            "gerber_expected_local_bbox_mil": bbox(expected_path),
            "after_local_bbox_mil": bbox(actual_path),
            "max_local_vertex_error_mil": rounded(footprint_error, 9),
        })

    if len(changed) != 4 or {item["record_id"] for item in changed} != TARGET_PAD_IDS:
        raise AssertionError(f"{reference}: expected exactly four target PAD changes")
    return ({
        "reference": reference,
        "before_block_sha256": sha256_text(before_lines),
        "after_block_sha256": sha256_text(after_lines),
        "record_count": len(after_lines),
        "record_type_counts": dict(sorted(types.items())),
        "record_identity_set_preserved": True,
        "non_target_semantic_geometry_changes": 0,
        "changed_field": "defaultPad.path",
        "changed_pad_count": len(changed),
        "changed_pads": changed,
        "serializer_normalizations": {
            "record_headers_reticketed_with_firstTicket_preserved": header_reticketed,
            "dochead_updateTime_and_version_updates": dochead_version_updates,
            "hidden_footprint_attr_value_removals": hidden_footprint_attr_value_removals,
            "non_target_pad_default_or_numeric_normalizations": sorted(pad_default_normalized),
            "raw_byte_unchanged_records": raw_unchanged_records,
            "note": (
                "EasyEDA commit normalization re-tickets PAD/ATTR rows, rounds pad numbers to four "
                "decimals, removes explicit zero propagationDelay, adds empty attrsMap, and maps "
                "zero relativeAngle to null on copper pads. These normalize identically under the "
                "semantic comparison; the hidden library Footprint ATTR value is omitted in both "
                "updated footprint documents and is reported explicitly rather than ignored."
            ),
        },
    }, path_by_number)


def flatten_drc(path: Path) -> list[tuple[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: list[tuple[str, str]] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("errorType") and node.get("errorObjType") and node.get("explanation"):
            result.append((str(node["errorType"]), str(node["errorObjType"])))
        for child in node.get("list", []):
            walk(child)

    for detail in data.get("details", []):
        walk(detail)
    return result


def main() -> int:
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    before_blocks = checkpoint_blocks(BEFORE)
    after_blocks = checkpoint_blocks(AFTER)
    runtime = json.loads(RUNTIME.read_text(encoding="utf-8"))
    pcb_records = read_records(PCB_SOURCE)

    components = {
        str(header.get("id")): body
        for header, body in pcb_records if header.get("type") == "COMPONENT"
    }
    if len(components) != 330:
        raise AssertionError(f"reopened PCB component count is {len(components)}, expected 330")
    runtime_selected = {str(item["id"]): item for item in runtime.get("selected", [])}
    if runtime.get("totalPads") != 1180 or len(runtime_selected) != 8:
        raise AssertionError("runtime pad snapshot does not contain the expected 1180/8 pads")

    footprint_reports: list[dict[str, Any]] = []
    footprint_paths: dict[str, dict[str, list[tuple[float, float]]]] = {}
    runtime_reports: list[dict[str, Any]] = []
    bounds = gerber["coordinateTransform"]["boardBoundsSourceMm"]
    board_min_x, board_min_y = finite(bounds[0]), finite(bounds[1])

    for reference, target in TARGETS.items():
        footprint_uuid = target["footprint_uuid"]
        if footprint_uuid not in before_blocks or footprint_uuid not in after_blocks:
            raise AssertionError(f"{reference}: missing authoritative footprint block")
        report, paths = compare_footprint(
            reference,
            before_blocks[footprint_uuid],
            after_blocks[footprint_uuid],
            gerber["components"][reference],
        )
        footprint_reports.append(report)
        footprint_paths[reference] = paths

        component_id = target["component_id"]
        component = components.get(component_id)
        if component is None:
            raise AssertionError(f"{reference}: component {component_id} missing from reopened PCB")
        anchor = gerber["components"][reference]["estimatedAnchorMm"]
        expected_component = [
            (finite(anchor[0]) - board_min_x) * MM_TO_MIL,
            (finite(anchor[1]) - board_min_y) * MM_TO_MIL,
        ]
        actual_component = [finite(component["x"]), finite(component["y"])]
        placement_error = math.hypot(
            actual_component[0] - expected_component[0],
            actual_component[1] - expected_component[1],
        )
        if placement_error > PATH_TOLERANCE_MIL:
            raise AssertionError(f"{reference}: component placement differs from Gerber anchor")

        evidence = gerber_pad_evidence(gerber["components"][reference])
        for pad_number, pad_evidence in evidence.items():
            runtime_id = f"{component_id}{next(item['record_id'] for item in report['changed_pads'] if item['pad_number'] == pad_number)}"
            item = runtime_selected.get(runtime_id)
            if item is None:
                raise AssertionError(f"runtime snapshot missing {reference} {pad_number} ({runtime_id})")
            if item.get("pad", [None])[0] != "POLYGON":
                raise AssertionError(f"{reference} {pad_number}: runtime shape is not POLYGON")
            runtime_path = line_points(item["pad"][1])
            expected_world_direct = transformed(
                pad_evidence["macro_local"],
                [
                    (finite(pad_evidence["flash"]["atMm"][0]) - board_min_x) * MM_TO_MIL,
                    (finite(pad_evidence["flash"]["atMm"][1]) - board_min_y) * MM_TO_MIL,
                ],
                pad_evidence["macro_angle"],
            )
            expected_world_component = transformed(
                footprint_paths[reference][pad_number], actual_component, component.get("angle", 0)
            )
            direct_error = max_point_error(runtime_path, expected_world_direct)
            component_error = max_point_error(runtime_path, expected_world_component)
            if direct_error > PATH_TOLERANCE_MIL or component_error > PATH_TOLERANCE_MIL:
                raise AssertionError(
                    f"{reference} {pad_number}: runtime world path error "
                    f"direct={direct_error}, component={component_error} mil"
                )
            flash_center = [
                (finite(pad_evidence["flash"]["atMm"][0]) - board_min_x) * MM_TO_MIL,
                (finite(pad_evidence["flash"]["atMm"][1]) - board_min_y) * MM_TO_MIL,
            ]
            runtime_center = [finite(item["x"]), finite(item["y"])]
            center_error = math.hypot(
                runtime_center[0] - flash_center[0], runtime_center[1] - flash_center[1]
            )
            if center_error > CENTER_TOLERANCE_MIL:
                raise AssertionError(f"{reference} {pad_number}: runtime center error {center_error} mil")
            runtime_reports.append({
                "reference": reference,
                "pad_number": pad_number,
                "runtime_id": runtime_id,
                "component_id": component_id,
                "component_position_mil": [rounded(value, 6) for value in actual_component],
                "gerber_anchor_board_mil": [rounded(value, 6) for value in expected_component],
                "component_placement_error_mil": rounded(placement_error, 9),
                "gerber_flash_at_mm": pad_evidence["flash"]["atMm"],
                "gerber_flash_board_center_mil": [rounded(value, 6) for value in flash_center],
                "runtime_center_mil": [rounded(value, 6) for value in runtime_center],
                "runtime_center_error_mil": rounded(center_error, 9),
                "runtime_world_bbox_mil": bbox(runtime_path),
                "gerber_world_bbox_mil": bbox(expected_world_direct),
                "max_world_vertex_error_direct_gerber_mil": rounded(direct_error, 9),
                "max_world_vertex_error_component_transform_mil": rounded(component_error, 9),
            })

    before_drc = Counter(flatten_drc(DRC_BEFORE))
    after_drc = Counter(flatten_drc(DRC_AFTER))
    relevant_drc = {}
    for key in sorted(set(before_drc) | set(after_drc)):
        if before_drc[key] != after_drc[key]:
            relevant_drc[f"{key[0]} / {key[1]}"] = {
                "before": before_drc[key],
                "after": after_drc[key],
                "delta": after_drc[key] - before_drc[key],
            }

    report = {
        "status": "pass",
        "purpose": "Post-apply proof for CN3/CN4 Outline5P polygon pads",
        "coordinate_contract": {
            "board": "mil, Y-up",
            "component_placement": "(Gerber source mm - board source minimum mm) * 1000/25.4",
            "footprint_polygon": "pad center relative to component anchor + rotated macro-local vertices",
            "world_polygon": "component placement + component-angle rotation of footprint polygon",
        },
        "inputs": {
            "before_checkpoint": {"path": str(BEFORE.relative_to(ROOT)), "sha256": sha256(BEFORE)},
            "after_checkpoint": {"path": str(AFTER.relative_to(ROOT)), "sha256": sha256(AFTER)},
            "gerber_manifest": {"path": str(GERBER.relative_to(ROOT)), "sha256": sha256(GERBER)},
            "runtime_pad_snapshot": {"path": str(RUNTIME.relative_to(ROOT)), "sha256": sha256(RUNTIME)},
            "reopened_pcb_source": {"path": str(PCB_SOURCE.relative_to(ROOT)), "sha256": sha256(PCB_SOURCE)},
            "post_fix_drc": {"path": str(DRC_AFTER.relative_to(ROOT)), "sha256": sha256(DRC_AFTER)},
        },
        "reopened_pcb": {
            "component_count": len(components),
            "runtime_total_pad_count": runtime["totalPads"],
            "selected_runtime_polygon_pad_count": len(runtime_selected),
        },
        "footprints": footprint_reports,
        "runtime_world_geometry": runtime_reports,
        "drc_delta": relevant_drc,
        "totals": {
            "protected_footprint_records": sum(item["record_count"] for item in footprint_reports),
            "changed_footprint_records": sum(item["changed_pad_count"] for item in footprint_reports),
            "non_target_semantic_geometry_changes": sum(
                item["non_target_semantic_geometry_changes"] for item in footprint_reports
            ),
            "runtime_world_paths_verified": len(runtime_reports),
            "max_runtime_world_vertex_error_mil": rounded(
                max(item["max_world_vertex_error_direct_gerber_mil"] for item in runtime_reports), 9
            ),
            "max_runtime_center_error_mil": rounded(
                max(item["runtime_center_error_mil"] for item in runtime_reports), 9
            ),
        },
        "checks": {
            "authoritative_footprint_record_sets_preserved": True,
            "exactly_eight_defaultPad_path_fields_changed": True,
            "all_other_footprint_geometry_and_electrical_semantics_unchanged_after_known_serializer_normalization": True,
            "reopened_board_has_330_components": True,
            "runtime_has_all_eight_polygon_pads": True,
            "component_placements_match_gerber_anchors": True,
            "runtime_world_paths_match_gerber_flashes": True,
            "runtime_world_paths_match_component_plus_footprint_transform": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(REPORT),
        "report_sha256": sha256(REPORT),
        "totals": report["totals"],
        "drc_delta": relevant_drc,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
