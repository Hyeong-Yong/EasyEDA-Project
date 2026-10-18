"""Prepare a source-only fix for the eight USB-C Outline5P polygon pads.

EasyEDA Pro 3.2 stores polygon-pad paths in footprint/document coordinates.
The PCB runtime does not translate or rotate those paths from the PAD's
``centerX``, ``centerY`` and ``padAngle`` fields.  The first reconstruction
stored Gerber aperture-macro coordinates directly, so CN3/CN4's asymmetric
end pads appeared around the footprint origin and caused same-footprint DRC
collisions.

This script never calls EasyEDA.  It reads the captured, reopened footprint
sources with their actual project-library UUIDs, changes only the eight
``defaultPad.path`` values, and emits derived candidate sources plus a strict
JSON proof report for the root/UI writer to apply separately.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
GERBER = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
OUTPUT = ROOT / "output" / "validation"
CHECKPOINT = (
    ROOT / "output" / "checkpoints" /
    "STM32H747_after_final_pcb_association_20261014.epro2"
)
CHECKPOINT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
MM_TO_MIL = 1000.0 / 25.4
TOLERANCE_MIL = 0.00011

TARGETS = {
    "CN3": {
        "uuid": "8bd1ebd7c6524c9d",
        "getter": OUTPUT / "native-CN3-capsule-compatible-reopened.epru",
        "candidate": OUTPUT / "native-CN3-outline5p-absolute-candidate.epru",
    },
    "CN4": {
        "uuid": "ae37a0fb8459ebec",
        "getter": OUTPUT / "native-CN4-capsule-compatible-reopened.epru",
        "candidate": OUTPUT / "native-CN4-outline5p-absolute-candidate.epru",
    },
}


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite coordinate {value!r}")
    return result


def rounded(value: Any, digits: int = 6) -> int | float:
    result = round(number(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def close(left: Any, right: Any, tolerance: float = TOLERANCE_MIL) -> bool:
    return abs(number(left) - number(right)) <= tolerance


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_line(raw: str, label: Any, line_number: int) -> tuple[str, dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        # Live library getters omit the final record's otherwise customary
        # trailing pipe.  It is a serializer normalization, not a malformed
        # JSON body; preserve the original line byte-for-byte unless targeted.
        body_json = body_text[:-1] if body_text.endswith("|") else body_text
        # Aggregate project packages also retain deletion/tombstone rows as
        # ``header|||`` (an empty body).  They cannot occur in a live footprint
        # block, but tolerate them while scanning the whole package.
        return header_text, json.loads(header_text), (json.loads(body_json) if body_json else {})
    except Exception as exc:
        raise ValueError(f"invalid native record {label}:{line_number}: {exc}") from exc


def checkpoint_footprint_blocks() -> dict[str, list[str]]:
    """Extract exact FOOTPRINT blocks from the final full project package."""

    with zipfile.ZipFile(CHECKPOINT) as archive:
        member_bytes = archive.read(CHECKPOINT_MEMBER)
    all_lines = member_bytes.decode("utf-8-sig").splitlines()
    blocks: dict[str, list[str]] = {}
    current_uuid: str | None = None
    current_lines: list[str] = []
    for line_number, raw in enumerate(all_lines, 1):
        _, header, body = parse_line(
            raw, f"{CHECKPOINT.name}:{CHECKPOINT_MEMBER}", line_number
        )
        if header.get("type") == "DOCHEAD":
            if current_uuid is not None:
                blocks[current_uuid] = current_lines
            current_uuid = (
                str(body.get("uuid")) if body.get("docType") == "FOOTPRINT" else None
            )
            current_lines = [raw] if current_uuid is not None else []
        elif current_uuid is not None:
            current_lines.append(raw)
    if current_uuid is not None:
        blocks[current_uuid] = current_lines
    return blocks


def path_points(path: Any) -> list[tuple[float, float]]:
    if not isinstance(path, list) or len(path) < 2:
        raise ValueError(f"invalid polygon path {path!r}")
    result: list[tuple[float, float]] = []
    index = 0
    while index < len(path):
        if isinstance(path[index], str):
            if path[index] != "L":
                raise ValueError(f"unsupported polygon command {path[index]!r}")
            index += 1
            continue
        if index + 1 >= len(path) or isinstance(path[index + 1], str):
            raise ValueError(f"malformed polygon path {path!r}")
        result.append((number(path[index]), number(path[index + 1])))
        index += 2
    return result


def encode_line_path(points: Sequence[Sequence[Any]]) -> list[Any]:
    if not points:
        raise ValueError("cannot encode an empty polygon")
    result: list[Any] = [rounded(points[0][0]), rounded(points[0][1])]
    for point in points[1:]:
        result.extend(["L", rounded(point[0]), rounded(point[1])])
    return result


def rotate(point: Sequence[Any], angle_deg: Any) -> tuple[float, float]:
    angle = math.radians(number(angle_deg))
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = number(point[0]), number(point[1])
    return x * cosine - y * sine, x * sine + y * cosine


def signed_area(points: Sequence[Sequence[Any]]) -> float:
    return 0.5 * sum(
        number(points[index][0]) * number(points[(index + 1) % len(points)][1])
        - number(points[(index + 1) % len(points)][0]) * number(points[index][1])
        for index in range(len(points))
    )


def bbox(points: Sequence[Sequence[Any]]) -> list[int | float]:
    xs = [number(item[0]) for item in points]
    ys = [number(item[1]) for item in points]
    return [rounded(min(xs)), rounded(min(ys)), rounded(max(xs)), rounded(max(ys))]


def points_match(left: Sequence[Sequence[Any]], right: Sequence[Sequence[Any]]) -> bool:
    return len(left) == len(right) and all(
        close(a[0], b[0]) and close(a[1], b[1]) for a, b in zip(left, right)
    )


def target_evidence(gerber: dict[str, Any], reference: str) -> dict[str, dict[str, Any]]:
    component = gerber["components"][reference]
    anchor = component["estimatedAnchorMm"]
    result: dict[str, dict[str, Any]] = {}
    for pad_key, pad in component["pads"].items():
        number_value = str(pad.get("number") or pad_key)
        flash = next(
            (item for item in pad.get("flashes", []) if item.get("shape") == "Outline5P"),
            None,
        )
        if flash is None:
            continue
        params = [number(item) for item in flash["paramsMm"]]
        if len(params) != 11:
            raise ValueError(f"{reference} {number_value}: Outline5P needs 11 parameters")
        local_points = [
            (params[index] * MM_TO_MIL, params[index + 1] * MM_TO_MIL)
            for index in range(0, 10, 2)
        ]
        center = (
            (number(flash["atMm"][0]) - number(anchor[0])) * MM_TO_MIL,
            (number(flash["atMm"][1]) - number(anchor[1])) * MM_TO_MIL,
        )
        rotated = [rotate(point, params[10]) for point in local_points]
        absolute = [(center[0] + point[0], center[1] + point[1]) for point in rotated]
        result[number_value] = {
            "flash": flash,
            "center": center,
            "angle": params[10],
            "local_points": local_points,
            "absolute_points": absolute,
        }
    if len(result) != 4:
        raise ValueError(f"{reference}: expected 4 Outline5P flashes, got {len(result)}")
    return result


def prepare_one(reference: str, config: dict[str, Any], gerber: dict[str, Any],
                lines: list[str]) -> dict[str, Any]:
    candidate: Path = config["candidate"]
    source_label = f"{CHECKPOINT.name}:{CHECKPOINT_MEMBER}:{config['uuid']}"
    parsed = [parse_line(raw, source_label, index) for index, raw in enumerate(lines, 1)]
    docheads = [body for _, header, body in parsed if header.get("type") == "DOCHEAD"]
    if len(docheads) != 1 or docheads[0].get("uuid") != config["uuid"]:
        raise ValueError(f"{reference}: captured DOCHEAD UUID is not {config['uuid']}")

    evidence = target_evidence(gerber, reference)
    modified: list[dict[str, Any]] = []
    output_lines = list(lines)
    for line_index, (header_text, header, body) in enumerate(parsed):
        if header.get("type") != "PAD" or str(body.get("num")) not in evidence:
            continue
        pad_number = str(body["num"])
        expected = evidence[pad_number]
        definition = body.get("defaultPad") or {}
        if definition.get("padType") != "POLYGON":
            raise ValueError(f"{reference} {pad_number}: target is not a POLYGON pad")
        original_points = path_points(definition.get("path"))
        if not points_match(original_points, expected["local_points"]):
            raise ValueError(
                f"{reference} {pad_number}: captured path is not the Gerber macro-local path"
            )
        center = [body.get("centerX"), body.get("centerY")]
        if not (close(center[0], expected["center"][0]) and close(center[1], expected["center"][1])):
            raise ValueError(f"{reference} {pad_number}: captured center differs from Gerber flash")
        if not close(body.get("padAngle"), expected["angle"]):
            raise ValueError(f"{reference} {pad_number}: captured angle differs from Gerber macro")

        repaired = copy.deepcopy(body)
        repaired["defaultPad"]["path"] = encode_line_path(expected["absolute_points"])
        comparison_original = copy.deepcopy(body)
        comparison_repaired = copy.deepcopy(repaired)
        comparison_original["defaultPad"].pop("path")
        comparison_repaired["defaultPad"].pop("path")
        if comparison_original != comparison_repaired:
            raise AssertionError(f"{reference} {pad_number}: field outside defaultPad.path changed")
        repaired_points = path_points(repaired["defaultPad"]["path"])
        if not points_match(repaired_points, expected["absolute_points"]):
            raise AssertionError(f"{reference} {pad_number}: repaired path transform mismatch")
        inverse = [
            rotate((point[0] - number(center[0]), point[1] - number(center[1])), -number(body["padAngle"]))
            for point in repaired_points
        ]
        if not points_match(inverse, original_points):
            raise AssertionError(f"{reference} {pad_number}: inverse transform mismatch")
        if signed_area(original_points) >= 0 or signed_area(repaired_points) >= 0:
            raise AssertionError(f"{reference} {pad_number}: clockwise winding was not preserved")

        output_lines[line_index] = (
            f"{header_text}||{json.dumps(repaired, ensure_ascii=False, separators=(',', ':'))}|"
        )
        modified.append(
            {
                "pad": pad_number,
                "record_id": header.get("id"),
                "line": line_index + 1,
                "center_mil_y_up": [rounded(value) for value in center],
                "macro_rotation_ccw_deg": rounded(body["padAngle"]),
                "local_path": definition["path"],
                "absolute_path": repaired["defaultPad"]["path"],
                "local_bbox_mil": bbox(original_points),
                "absolute_bbox_mil": bbox(repaired_points),
                "signed_area_mil2": rounded(signed_area(repaired_points), 8),
                "source_flash": {
                    "layer": expected["flash"].get("layer"),
                    "aperture": expected["flash"].get("aperture"),
                    "atMm": expected["flash"].get("atMm"),
                    "paramsMm": expected["flash"].get("paramsMm"),
                },
            }
        )

    if len(modified) != 4:
        raise ValueError(f"{reference}: expected to modify 4 PAD records, got {len(modified)}")
    candidate.write_text("\n".join(output_lines) + "\n", encoding="utf-8", newline="\n")

    candidate_lines = candidate.read_text(encoding="utf-8").splitlines()
    changed_line_numbers = [
        index + 1 for index, (left, right) in enumerate(zip(lines, candidate_lines)) if left != right
    ]
    expected_changed = [item["line"] for item in modified]
    if changed_line_numbers != expected_changed or len(lines) != len(candidate_lines):
        raise AssertionError(
            f"{reference}: only target PAD lines may differ: {changed_line_numbers} != {expected_changed}"
        )

    # The prior live getter capture is intentionally not a source of truth: it
    # omits footprint-owned graphic primitives.  Record that difference so a
    # future caller cannot accidentally regress to the lossy input.
    getter: Path = config["getter"]
    getter_records = [
        parse_line(raw, getter, index)
        for index, raw in enumerate(getter.read_text(encoding="utf-8").splitlines(), 1)
    ]
    authority_ids = {
        (str(header.get("type")), str(header.get("id")))
        for _, header, _ in parsed if header.get("id") is not None
    }
    getter_ids = {
        (str(header.get("type")), str(header.get("id")))
        for _, header, _ in getter_records if header.get("id") is not None
    }
    missing_from_getter = sorted(authority_ids - getter_ids)
    type_counts = Counter(str(header.get("type")) for _, header, _ in parsed)
    candidate_parsed = [
        parse_line(raw, candidate, index)
        for index, raw in enumerate(candidate_lines, 1)
    ]
    candidate_ids = {
        (str(header.get("type")), str(header.get("id")))
        for _, header, _ in candidate_parsed if header.get("id") is not None
    }
    if candidate_ids != authority_ids:
        raise AssertionError(f"{reference}: candidate record identity set changed")
    return {
        "reference": reference,
        "actual_project_library_uuid": config["uuid"],
        "authoritative_source": {
            "checkpoint": str(CHECKPOINT.relative_to(ROOT)),
            "checkpoint_member": CHECKPOINT_MEMBER,
            "footprint_block_sha256": sha256_bytes(("\n".join(lines) + "\n").encode("utf-8")),
            "record_count": len(lines),
            "record_type_counts": dict(sorted(type_counts.items())),
        },
        "lossy_getter_rejected": {
            "path": str(getter.relative_to(ROOT)),
            "sha256": sha256(getter),
            "missing_authoritative_record_identities": [
                {"type": kind, "id": record_id} for kind, record_id in missing_from_getter
            ],
        },
        "candidate": str(candidate.relative_to(ROOT)),
        "candidate_sha256": sha256(candidate),
        "record_count": len(lines),
        "changed_lines": changed_line_numbers,
        "modified_pad_count": len(modified),
        "modified_pads": modified,
        "checks": {
            "dochead_uuid_exact": True,
            "source_left_unchanged": True,
            "authoritative_record_identity_set_preserved": True,
            "only_defaultPad_path_changed": True,
            "gerber_center_angle_and_local_vertices_exact": True,
            "rotate_then_translate_y_up_verified": True,
            "inverse_transform_verified": True,
            "clockwise_winding_preserved": True,
        },
    }


def main() -> int:
    gerber = json.loads(GERBER.read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    blocks = checkpoint_footprint_blocks()
    results = []
    for reference, config in TARGETS.items():
        uuid = str(config["uuid"])
        if uuid not in blocks:
            raise ValueError(f"final checkpoint has no FOOTPRINT block {uuid}")
        results.append(prepare_one(reference, config, gerber, blocks[uuid]))
    report = {
        "status": "pass",
        "purpose": "CN3/CN4 Outline5P polygon paths made absolute for EasyEDA Pro 3.2",
        "coordinate_contract": {
            "domain": "footprint-local mil, Y-up",
            "transform": "absolute = center + rotate_ccw(macro_local, macro_angle)",
            "runtime_evidence": (
                "Installed pro-pcb 3.2 polygon PadStyle.getShape uses the stored polygon path "
                "directly and applies neither the PAD center nor padAngle; parametric RECT/OVAL paths "
                "take both values."
            ),
            "installed_source": (
                "C:/Program Files/easyeda-pro/resources/app/assets/pro-pcb/"
                "3.2.193.682ed44e/js/pcb.js"
            ),
        },
        "gerber_source": str(GERBER.relative_to(ROOT)),
        "gerber_source_sha256": sha256(GERBER),
        "authoritative_checkpoint": {
            "path": str(CHECKPOINT.relative_to(ROOT)),
            "sha256": sha256(CHECKPOINT),
            "member": CHECKPOINT_MEMBER,
        },
        "footprints": results,
        "totals": {
            "footprints": len(results),
            "pads_modified": sum(item["modified_pad_count"] for item in results),
            "non_target_record_changes": 0,
        },
        "application_scope": (
            "Derived candidates only. EasyEDA library update, cache close/reopen, footprint digest, "
            "moved-instance proof and final PCB DRC remain root/UI-writer responsibilities."
        ),
    }
    report_path = OUTPUT / "outline5p-polygon-pad-fix-plan.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "report": str(report_path),
        "pads_modified": report["totals"]["pads_modified"],
        "candidates": [item["candidate"] for item in results],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
