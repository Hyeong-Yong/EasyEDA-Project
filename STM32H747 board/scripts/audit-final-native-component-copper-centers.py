#!/usr/bin/env python3
"""Audit every Gerber component copper-pad centre in the final native PCB.

This is a static/read-only companion to ``audit-final-native-drill-inventory.py``.
It proves that every physical F.Cu/B.Cu component-pad centre extracted from the
June Gerber has a same-number native FOOTPRINT PAD and an exact PCB PAD_NET
child.  The full-checkpoint footprint geometry is transformed through each of
the 330 native COMPONENT placements and compared with the Gerber board frame.

The expected final inventory is deliberately split into independent evidence:

* 1,217 unique component copper centres from Gerber flashes;
* 8 U5/U7 plated thermal holes that are drill-derived rather than separate
  component-pad flashes; and
* 9 component-owned mechanical NPTHs.

Together these are 1,234 footprint PAD instances and 1,234 PCB PAD_NET rows.
A passing result is a reconstruction-integrity check, never manufacturing
approval.  Drill diameters/slots are checked by the separate drill auditor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_CHECKPOINT = (
    ROOT / "output/checkpoints/STM32H747_after_missing_pad_children_created_20261014.epro2"
)
DEFAULT_PCB = (
    ROOT / "output/validation/native-final-pcb-after_thermal_pth_restore-reopened.epru"
)
DEFAULT_MANIFEST = ROOT / "output/semantic/gerber-component-footprints.json"
DEFAULT_REPORT = ROOT / "output/validation/native-final-component-copper-centres-audit.json"

MM_TO_MIL = 1000.0 / 25.4
LOCAL_TOLERANCE_MIL = 0.001
BOARD_TOLERANCE_MIL = 0.002

EXPECTED_COMPONENTS = 330
EXPECTED_LOGICAL_PADS = 1167
EXPECTED_COPPER_CENTRES = 1217
EXPECTED_FOOTPRINT_PADS = 1234
EXPECTED_EXTRA_THERMAL_PTH = 8
EXPECTED_EXTRA_COMPONENT_NPTH = 9


class AuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"non-finite numeric value {value!r}")
    return result


def clean(value: Any, digits: int = 7) -> int | float:
    result = round(finite(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def natural_key(value: Any) -> list[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value))]


def distance(left: Sequence[Any], right: Sequence[Any]) -> float:
    return math.dist((finite(left[0]), finite(left[1])), (finite(right[0]), finite(right[1])))


def parse_record(raw: str, label: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        header_text, body_text = raw.split("||", 1)
        if body_text.endswith("|"):
            body_text = body_text[:-1]
        return json.loads(header_text), json.loads(body_text)
    except Exception as exc:  # pragma: no cover - diagnostic context matters
        raise AuditError(f"invalid native record {label}:{line_number}: {exc}") from exc


def read_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        parse_record(raw, path.name, line_number)
        for line_number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
        if raw.strip()
    ]


def read_checkpoint_blocks(
    path: Path,
) -> tuple[dict[str, list[tuple[dict[str, Any], dict[str, Any]]]], dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        raw = archive.read(MEMBER).decode("utf-8-sig")
    blocks: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    types: dict[str, str] = {}
    current_uuid: str | None = None
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        header, body = parse_record(line, f"{path.name}:{MEMBER}", line_number)
        if header.get("type") == "DOCHEAD":
            current_uuid = str(body.get("uuid") or "")
            if not current_uuid:
                raise AuditError(f"DOCHEAD at line {line_number} has no uuid")
            if current_uuid in blocks:
                raise AuditError(f"duplicate checkpoint document uuid {current_uuid}")
            blocks[current_uuid] = [(header, body)]
            types[current_uuid] = str(body.get("docType") or "")
        elif current_uuid is not None:
            blocks[current_uuid].append((header, body))
    return blocks, types


def child_attributes(
    records: Iterable[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = defaultdict(dict)
    for header, body in records:
        if header.get("type") != "ATTR":
            continue
        parent = str(body.get("parentId") or "")
        key = str(body.get("key") or "")
        value = body.get("value")
        if value is None:
            value = body.get("blockValue")
        if parent and key:
            result[parent][key] = "" if value is None else str(value)
    return result


def pad_net_identity(header: dict[str, Any]) -> tuple[str, str, str]:
    try:
        value = json.loads(str(header.get("id")))
    except Exception as exc:
        raise AuditError(f"invalid PAD_NET identity {header.get('id')!r}") from exc
    if not isinstance(value, list) or len(value) != 4 or value[0] != "PAD_NET":
        raise AuditError(f"invalid PAD_NET tuple {value!r}")
    return str(value[1]), str(value[2]), str(value[3])


def unique_copper_centres(component: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pad_number, pad in sorted(component.get("pads", {}).items(), key=lambda item: natural_key(item[0])):
        by_position: dict[tuple[float, float], dict[str, Any]] = {}
        for flash in pad.get("flashes", []):
            layer = str(flash.get("layer") or "")
            if layer not in {"F.Cu", "B.Cu"}:
                continue
            at = (finite(flash["atMm"][0]), finite(flash["atMm"][1]))
            # Source coordinates are serialized to six decimal millimetres.
            key = (round(at[0], 6), round(at[1], 6))
            item = by_position.setdefault(
                key,
                {
                    "number": str(pad_number),
                    "source_center_mm": [clean(at[0], 6), clean(at[1], 6)],
                    "layers": [],
                    "flashes": [],
                    "old_net": pad.get("netOld"),
                },
            )
            item["layers"].append(layer)
            item["flashes"].append(
                {
                    "layer": layer,
                    "aperture": flash.get("aperture"),
                    "shape": flash.get("shape"),
                    "params_mm": flash.get("paramsMm"),
                }
            )
        rows.extend(by_position.values())
    for row in rows:
        row["layers"] = sorted(set(row["layers"]))
    return rows


def canonical_rows_digest(rows: Sequence[dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def audit(checkpoint: Path, pcb_path: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_components = {
        str(reference): component
        for reference, component in manifest.get("components", {}).items()
        if component.get("presentInLatest")
    }
    if len(source_components) != EXPECTED_COMPONENTS:
        raise AuditError(
            f"latest Gerber component set changed: {len(source_components)} != {EXPECTED_COMPONENTS}"
        )

    blocks, doc_types = read_checkpoint_blocks(checkpoint)
    footprints = {uuid: rows for uuid, rows in blocks.items() if doc_types.get(uuid) == "FOOTPRINT"}
    pcb = read_records(pcb_path)
    counts = Counter(str(header.get("type")) for header, _ in pcb)
    attrs = child_attributes(pcb)

    components_by_ref: dict[str, dict[str, Any]] = {}
    for header, body in pcb:
        if header.get("type") != "COMPONENT":
            continue
        component_id = str(header.get("id") or "")
        reference = attrs.get(component_id, {}).get("Designator", "")
        footprint_uuid = attrs.get(component_id, {}).get("Footprint", "")
        if not reference or not footprint_uuid:
            raise AuditError(f"COMPONENT {component_id} lacks Designator/Footprint")
        if reference in components_by_ref:
            raise AuditError(f"duplicate native reference {reference}")
        if footprint_uuid not in footprints:
            raise AuditError(f"{reference}: checkpoint lacks footprint {footprint_uuid}")
        if int(body.get("layerId", -1)) != 1 or abs(finite(body.get("angle", 0))) > 0.0001:
            raise AuditError(f"{reference}: placement is not the baked top-side zero-angle contract")
        components_by_ref[reference] = {
            "component_id": component_id,
            "footprint_uuid": footprint_uuid,
            "x": finite(body.get("x")),
            "y": finite(body.get("y")),
        }

    if set(components_by_ref) != set(source_components):
        missing = sorted(set(source_components) - set(components_by_ref), key=natural_key)
        extra = sorted(set(components_by_ref) - set(source_components), key=natural_key)
        raise AuditError(f"native/source reference mismatch: missing={missing}, extra={extra}")

    pad_nets: dict[tuple[str, str], dict[str, Any]] = {}
    for header, body in pcb:
        if header.get("type") != "PAD_NET":
            continue
        component_id, number, local_id = pad_net_identity(header)
        key = (component_id, local_id)
        if key in pad_nets:
            raise AuditError(f"duplicate PAD_NET child {key!r}")
        pad_nets[key] = {
            "number": number,
            "net": str(body.get("padNet") or ""),
            "id": str(header.get("id")),
        }

    bounds = manifest["coordinateTransform"]["boardBoundsSourceMm"]
    board_min_x, board_min_y = finite(bounds[0]), finite(bounds[1])
    matches: list[dict[str, Any]] = []
    extras: list[dict[str, Any]] = []
    all_footprint_keys: set[tuple[str, str]] = set()
    max_local_error = 0.0
    max_board_error = 0.0
    logical_pad_count = 0
    per_reference: list[dict[str, Any]] = []

    for reference in sorted(source_components, key=natural_key):
        source = source_components[reference]
        component = components_by_ref[reference]
        anchor = (finite(source["estimatedAnchorMm"][0]), finite(source["estimatedAnchorMm"][1]))
        expected = unique_copper_centres(source)
        logical_pad_count += len(source.get("pads", {}))
        footprint_rows = footprints[component["footprint_uuid"]]
        native_pads = [
            {"id": str(header.get("id") or ""), "body": body}
            for header, body in footprint_rows
            if header.get("type") == "PAD"
        ]
        if any(not item["id"] for item in native_pads):
            raise AuditError(f"{reference}: footprint PAD with empty identity")
        if len({item['id'] for item in native_pads}) != len(native_pads):
            raise AuditError(f"{reference}: duplicate footprint PAD identity")
        used: set[str] = set()

        for want in expected:
            number = want["number"]
            source_center = want["source_center_mm"]
            expected_local = (
                (finite(source_center[0]) - anchor[0]) * MM_TO_MIL,
                (finite(source_center[1]) - anchor[1]) * MM_TO_MIL,
            )
            candidates = [
                item
                for item in native_pads
                if item["id"] not in used and str(item["body"].get("num") or "") == number
            ]
            if not candidates:
                raise AuditError(f"{reference}.{number} {source_center}: no unused same-number native PAD")
            chosen = min(
                candidates,
                key=lambda item: distance(
                    expected_local,
                    (item["body"].get("centerX"), item["body"].get("centerY")),
                ),
            )
            actual_local = (finite(chosen["body"].get("centerX")), finite(chosen["body"].get("centerY")))
            local_error = distance(expected_local, actual_local)
            if local_error > LOCAL_TOLERANCE_MIL:
                raise AuditError(
                    f"{reference}.{number} {source_center}: local centre error {local_error:.9f} mil"
                )
            used.add(chosen["id"])
            key = (component["component_id"], chosen["id"])
            binding = pad_nets.get(key)
            if binding is None:
                raise AuditError(f"{reference}.{number}/{chosen['id']}: PAD_NET child missing")
            if binding["number"] != number:
                raise AuditError(
                    f"{reference}/{chosen['id']}: PAD number {number!r} != PAD_NET {binding['number']!r}"
                )
            all_footprint_keys.add(key)
            actual_board = (component["x"] + actual_local[0], component["y"] + actual_local[1])
            expected_board = (
                (finite(source_center[0]) - board_min_x) * MM_TO_MIL,
                (finite(source_center[1]) - board_min_y) * MM_TO_MIL,
            )
            board_error = distance(expected_board, actual_board)
            if board_error > BOARD_TOLERANCE_MIL:
                raise AuditError(
                    f"{reference}.{number}/{chosen['id']}: board centre error {board_error:.9f} mil"
                )
            max_local_error = max(max_local_error, local_error)
            max_board_error = max(max_board_error, board_error)
            matches.append(
                {
                    "reference": reference,
                    "number": number,
                    "footprint_uuid": component["footprint_uuid"],
                    "component_id": component["component_id"],
                    "pad_id": chosen["id"],
                    "source_center_mm": source_center,
                    "source_layers": want["layers"],
                    "source_flashes": want["flashes"],
                    "native_local_center_mil": [clean(actual_local[0]), clean(actual_local[1])],
                    "native_board_center_mil": [clean(actual_board[0]), clean(actual_board[1])],
                    "expected_board_center_mil": [clean(expected_board[0]), clean(expected_board[1])],
                    "local_error_mil": clean(local_error, 9),
                    "board_error_mil": clean(board_error, 9),
                    "pcb_net": binding["net"],
                    "old_gerber_net": want["old_net"],
                }
            )

        for item in native_pads:
            key = (component["component_id"], item["id"])
            if key in all_footprint_keys:
                continue
            binding = pad_nets.get(key)
            if binding is None:
                raise AuditError(f"{reference}/{item['id']}: extra footprint PAD lacks PAD_NET")
            body = item["body"]
            actual_local = (finite(body.get("centerX")), finite(body.get("centerY")))
            all_footprint_keys.add(key)
            extras.append(
                {
                    "reference": reference,
                    "number": str(body.get("num") or ""),
                    "footprint_uuid": component["footprint_uuid"],
                    "component_id": component["component_id"],
                    "pad_id": item["id"],
                    "local_center_mil": [clean(actual_local[0]), clean(actual_local[1])],
                    "board_center_mil": [
                        clean(component["x"] + actual_local[0]),
                        clean(component["y"] + actual_local[1]),
                    ],
                    "plated": body.get("plated"),
                    "hole": body.get("hole"),
                    "unused_inner_layers": body.get("unusedInnerLayers"),
                    "pcb_net": binding["net"],
                }
            )

        per_reference.append(
            {
                "reference": reference,
                "footprint_uuid": component["footprint_uuid"],
                "logical_pad_numbers": len(source.get("pads", {})),
                "source_physical_copper_centres": len(expected),
                "native_footprint_pads": len(native_pads),
                "matched_source_centres": len(expected),
                "extra_drill_derived_pads": len(native_pads) - len(expected),
            }
        )

    unmatched_pad_nets = sorted(set(pad_nets) - all_footprint_keys)
    if unmatched_pad_nets:
        raise AuditError(f"PCB has PAD_NET children absent from footprint blocks: {unmatched_pad_nets[:10]!r}")

    if logical_pad_count != EXPECTED_LOGICAL_PADS:
        raise AuditError(f"logical pad count {logical_pad_count} != {EXPECTED_LOGICAL_PADS}")
    if len(matches) != EXPECTED_COPPER_CENTRES:
        raise AuditError(f"copper centre count {len(matches)} != {EXPECTED_COPPER_CENTRES}")
    if len(all_footprint_keys) != EXPECTED_FOOTPRINT_PADS:
        raise AuditError(f"footprint PAD instances {len(all_footprint_keys)} != {EXPECTED_FOOTPRINT_PADS}")
    if counts["PAD_NET"] != EXPECTED_FOOTPRINT_PADS or len(pad_nets) != EXPECTED_FOOTPRINT_PADS:
        raise AuditError(
            f"PCB PAD_NET count {counts['PAD_NET']}/{len(pad_nets)} != {EXPECTED_FOOTPRINT_PADS}"
        )

    thermal = [
        item
        for item in extras
        if item["plated"] is True
        and (item["reference"], item["number"]) in {("U5", "25"), ("U7", "33")}
    ]
    mechanical = [item for item in extras if item["plated"] is False and item["number"] == ""]
    unclassified = [item for item in extras if item not in thermal and item not in mechanical]
    if len(thermal) != EXPECTED_EXTRA_THERMAL_PTH:
        raise AuditError(f"thermal PTH extras {len(thermal)} != {EXPECTED_EXTRA_THERMAL_PTH}")
    if len(mechanical) != EXPECTED_EXTRA_COMPONENT_NPTH:
        raise AuditError(f"component NPTH extras {len(mechanical)} != {EXPECTED_EXTRA_COMPONENT_NPTH}")
    if unclassified:
        raise AuditError(f"unclassified footprint PAD extras: {unclassified!r}")
    if any(item["pcb_net"] != "GND" for item in thermal):
        raise AuditError("one or more U5/U7 thermal PTH extras are not bound to GND")

    sma_matches = [
        item
        for item in matches
        if item["reference"] in {f"J{index}" for index in range(2, 18)} and item["number"] == "2"
    ]
    if len(sma_matches) != 64:
        raise AuditError(f"SMA J2-J17 physical pad2 centres {len(sma_matches)} != 64")
    sw1_matches = [item for item in matches if item["reference"] == "SW1"]
    if len(sw1_matches) != 4 or Counter(item["number"] for item in sw1_matches) != {"1": 2, "2": 2}:
        raise AuditError(f"SW1 duplicate-pad reconstruction differs: {sw1_matches!r}")

    match_rows = sorted(matches, key=lambda item: (natural_key(item["reference"]), natural_key(item["number"]), item["source_center_mm"]))
    extra_rows = sorted(extras, key=lambda item: (natural_key(item["reference"]), natural_key(item["number"]), item["local_center_mil"]))
    return {
        "schema": "stm32h747-final-native-component-copper-centres-audit-v1",
        "status": "pass-static-component-centres-not-manufacturing-approval",
        "manufacturing_approved": False,
        "inputs": {
            "checkpoint": {"path": str(checkpoint.resolve()), "sha256": sha256(checkpoint), "bytes": checkpoint.stat().st_size},
            "pcb_source": {"path": str(pcb_path.resolve()), "sha256": sha256(pcb_path), "bytes": pcb_path.stat().st_size},
            "gerber_manifest": {"path": str(manifest_path.resolve()), "sha256": sha256(manifest_path), "bytes": manifest_path.stat().st_size},
        },
        "tolerances_mil": {"footprint_local": LOCAL_TOLERANCE_MIL, "board_absolute": BOARD_TOLERANCE_MIL},
        "counts": {
            "components": len(components_by_ref),
            "logical_pad_numbers": logical_pad_count,
            "unique_source_component_copper_centres": len(match_rows),
            "native_footprint_pad_instances": len(all_footprint_keys),
            "pcb_pad_net_records": len(pad_nets),
            "drill_derived_extra_thermal_pth": len(thermal),
            "drill_derived_extra_component_npth": len(mechanical),
            "sma_j2_j17_pad2_physical_centres": len(sma_matches),
            "sw1_physical_centres": len(sw1_matches),
        },
        "maximum_error_mil": {"footprint_local": clean(max_local_error, 9), "board_absolute": clean(max_board_error, 9)},
        "digests": {
            "all_1217_match_rows_sha256": canonical_rows_digest(match_rows),
            "all_17_extra_rows_sha256": canonical_rows_digest(extra_rows),
        },
        "per_reference": per_reference,
        "matched_component_copper_centres": match_rows,
        "drill_derived_extra_footprint_pads": extra_rows,
        "checks": {
            "all_330_latest_references_present": True,
            "all_1217_source_component_copper_centres_match_same_number_native_pads": True,
            "all_1234_footprint_pads_have_exact_child_pad_net_rows": True,
            "sma_j2_j17_four_physical_ground_post_centres_per_reference_present": True,
            "sw1_duplicate_number_smd_centres_present": True,
            "u5_u7_eight_drill_derived_thermal_pths_present_and_gnd": True,
            "nine_component_owned_mechanical_npths_present": True,
        },
        "limitations": [
            "This report validates centre identity and child binding, not every pad outline/mask/paste detail.",
            "Drill diameters, slot endpoints, and one-to-one Excellon identity are delegated to audit-final-native-drill-inventory.py.",
            "The June Gerber is older than the August schematic; net authority remains the latest schematic and the dedicated netlist/ten-bridge audits.",
            "A pass is not manufacturing approval; final DRC and diagnostic fabrication-output review remain mandatory.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--pcb", type=Path, default=DEFAULT_PCB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = audit(args.checkpoint, args.pcb, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "counts": report["counts"], "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
