#!/usr/bin/env python3
"""Place an EasyEDA Pro PCB generated from the verified schematic.

This tool is deliberately independent from the EasyEDA API.  It accepts the
raw PCB JSON-record source captured *after* schematic-to-PCB conversion,
matches all physical COMPONENT records to the project-local footprint
manifest, and moves them to the archived Gerber anchors.  Footprint geometry
already contains the archived orientation, so every matched component is
placed with zero rotation.

The archived Gerber uses absolute millimetres with negative Y.  Native PCB
source uses mil and an upward-positive board-local Y axis, as verified against
EasyEDA Pro 3.2.206 runtime PAD coordinates::

    x_mil = (source_x_mm - board_min_x_mm) * 39.37007874015748
    y_mil = (source_y_mm - board_min_y_mm) * 39.37007874015748

The thirteen Gerber NPTH drills are also preserved.  Existing matching
non-plated PAD records are retained; missing holes are appended as unnumbered
MULTI-layer PAD records.  Nine X2-attributed mechanical holes are component
children and four REF** mounting holes remain top-level.  Component-owned ATTR
coordinates are translated by the same placement delta so visible designators
retain their original local offsets.  PAD, PAD_NET and net data are otherwise
left semantically unchanged so the latest converted netlist remains
authoritative.

This is still reconstruction evidence, not manufacturing-ready PCB output.
The resulting source must be re-imported by the main workflow and pass native
netlist comparison plus DRC before fabrication use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_INPUT = ROOT / "output" / "validation" / "native-pcb-generated.epru"
DEFAULT_LIBRARY_MANIFEST = ROOT / "output" / "native-libraries" / "manifest.json"
DEFAULT_REBIND_PLAN = ROOT / "output" / "validation" / "native-component-link-rebind-plan.json"
DEFAULT_GERBER = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
DEFAULT_OUTPUT = ROOT / "output" / "native-pcb" / "native-pcb-placed.epru"
DEFAULT_REPORT = ROOT / "output" / "native-pcb" / "native-pcb-placement-manifest.json"
MM_TO_MIL = 39.37007874015748
COORDINATE_TOLERANCE_MIL = 0.05
DIAMETER_TOLERANCE_MIL = 0.05

# Gerber X2 mask attributes assign nine mechanical NPTH holes to their
# components.  The remaining four 3.2 mm REF** holes are board mounting holes.
# The extraction manifest is authoritative when it carries componentRef; this
# exact coordinate map is retained as a strict board-specific cross-check.
NPTH_COMPONENT_BY_SOURCE_MM = {
    (204.150000, -71.680000): "CN4", (209.930000, -71.680000): "CN4",
    (240.820000, -151.305000): "CN3", (240.820000, -157.085000): "CN3",
    (223.125000, -69.900000): "J1", (229.475000, -69.900000): "J1",
    (243.100000, -202.400000): "CN1",
    (241.478000, -175.100000): "CN2", (241.478000, -187.800000): "CN2",
}

REFERENCE_ATTRIBUTE_KEYS = {
    "designator", "reference", "reference designator", "refdes", "ref", "component reference",
}
FOOTPRINT_ATTRIBUTE_KEYS = {
    "footprint", "footprint name", "footprintname", "footprints", "supplier footprint",
}


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def rounded(value: float, digits: int = 6) -> int | float:
    result = round(float(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def natural_key(value: Any) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value)))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(kind: str, key: str) -> str:
    return hashlib.sha256(f"stm32h747-v19\0{kind}\0{key}".encode()).hexdigest()[:16]


def safe_output_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must be below {OUTPUT_ROOT}; got {resolved}") from exc
    if not relative.parts:
        raise ValueError(f"{label} cannot be the board output root itself")
    return resolved


def atomic_write_text(path: Path, text: str) -> None:
    target = safe_output_path(path, "output file")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            safe_output_path(temporary, "temporary output file").unlink()


@dataclass
class Record:
    header: dict[str, Any]
    body: dict[str, Any]
    line_number: int

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")

    def line(self) -> str:
        return f"{compact(self.header)}||{compact(self.body)}|\n"


def serialize_source(records: Iterable[Record]) -> str:
    """Match the 3.2 PCB getter framing: separators between records, none at EOF."""
    text = "".join(record.line() for record in records)
    if not text.endswith("|\n"):
        raise AssertionError("native PCB serialization did not end in a record separator")
    return text[:-2]


def parse_source(path: Path) -> list[Record]:
    records: list[Record] = []
    source_lines = path.read_text(encoding="utf-8-sig").splitlines()
    for line_number, raw in enumerate(source_lines, 1):
        line = raw.strip()
        if not line:
            continue
        # 3.2.206 getDocumentSource() may omit the record terminator from the
        # final line even though every preceding line ends in ``|``.  Accept
        # that one serialization variant, but keep rejecting a missing
        # terminator anywhere else so a truncated middle record cannot pass.
        has_terminator = line.endswith("|")
        if not has_terminator and line_number != len(source_lines):
            raise ValueError(f"line {line_number}: missing EasyEDA record terminator")
        if "||" not in line:
            raise ValueError(f"line {line_number}: not an EasyEDA JSON-record line")
        record_text = line[:-1] if has_terminator else line
        head_text, body_text = record_text.split("||", 1)
        header = json.loads(head_text)
        body = json.loads(body_text)
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise ValueError(f"line {line_number}: record header/body must be objects")
        records.append(Record(header, body, line_number))
    if not records:
        raise ValueError("native PCB source contains no records")
    heads = [record for record in records if record.kind == "DOCHEAD"]
    if len(heads) != 1 or heads[0].body.get("docType") != "PCB":
        raise ValueError(f"expected exactly one PCB DOCHEAD, found {[item.body.get('docType') for item in heads]}")
    return records


def semantic_digest(records: Iterable[Record]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.line().encode("utf-8"))
    return digest.hexdigest()


def recursively_flatten(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            result.append(str(key))
            result.extend(recursively_flatten(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(recursively_flatten(item))
    elif value is not None:
        text = str(value).strip()
        if text:
            result.append(text)
            if text[:1] in "[{" and text[-1:] in "]}":
                try:
                    result.extend(recursively_flatten(json.loads(text)))
                except json.JSONDecodeError:
                    pass
    return result


def component_child_attributes(records: Sequence[Record]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        if record.kind != "ATTR":
            continue
        parent = str(record.body.get("parentId") or "")
        key = str(record.body.get("key") or "").strip().casefold()
        value = record.body.get("value")
        if parent and key:
            result[parent][key].extend(recursively_flatten(value))
    return {parent: dict(values) for parent, values in result.items()}


def component_child_attribute_records(records: Sequence[Record]) -> dict[str, list[Record]]:
    result: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.kind != "ATTR":
            continue
        parent = str(record.body.get("parentId") or "")
        if parent:
            result[parent].append(record)
    return dict(result)


def finite_coordinate(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def body_attribute_values(body: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    attrs = body.get("attrs")
    if isinstance(attrs, dict):
        for key, value in attrs.items():
            result[str(key).strip().casefold()].extend(recursively_flatten(value))
    for raw_key, value in body.items():
        key = str(raw_key).strip().casefold()
        if key in REFERENCE_ATTRIBUTE_KEYS | FOOTPRINT_ATTRIBUTE_KEYS:
            result[key].extend(recursively_flatten(value))
    return dict(result)


def merged_attributes(component: Record, children: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for source in (body_attribute_values(component.body), children.get(component.record_id, {})):
        for key, values in source.items():
            result[key].extend(values)
    return dict(result)


def component_reference(attributes: dict[str, list[str]], known_refs: set[str]) -> str:
    preferred: set[str] = set()
    for key, values in attributes.items():
        if key in REFERENCE_ATTRIBUTE_KEYS:
            preferred.update(value for value in values if value in known_refs)
    if len(preferred) == 1:
        return preferred.pop()
    if len(preferred) > 1:
        raise ValueError(f"component has ambiguous designator attributes: {sorted(preferred, key=natural_key)}")
    fallback = {value for values in attributes.values() for value in values if value in known_refs}
    if len(fallback) == 1:
        return fallback.pop()
    raise ValueError(f"component reference is missing or ambiguous; known candidates={sorted(fallback, key=natural_key)}")


def verify_footprint_evidence(
    reference: str,
    attributes: dict[str, list[str]],
    footprint: dict[str, Any],
    imported_uuid: str,
) -> list[str]:
    evidence: list[str] = []
    for key, values in attributes.items():
        if key in FOOTPRINT_ATTRIBUTE_KEYS or "footprint" in key:
            evidence.extend(values)
    expected = {
        str(footprint.get("uuid") or ""), str(footprint.get("title") or ""),
        str(footprint.get("schematic_footprint") or ""), imported_uuid,
    } - {""}
    haystack = "\n".join(evidence)
    if not evidence or not any(value in haystack for value in expected):
        raise ValueError(
            f"{reference}: native COMPONENT does not expose the expected footprint evidence; "
            f"expected one of {sorted(expected)!r}, saw {evidence[:12]!r}"
        )
    return sorted(set(evidence))


def board_point(anchor_mm: Sequence[float], bounds_mm: Sequence[float]) -> tuple[int | float, int | float]:
    min_x, min_y, _, _ = map(number, bounds_mm)
    return (
        rounded((number(anchor_mm[0]) - min_x) * MM_TO_MIL),
        rounded((number(anchor_mm[1]) - min_y) * MM_TO_MIL),
    )


def validate_coordinate_transform(bounds_mm: Sequence[float]) -> dict[str, Any]:
    min_x, min_y, max_x, max_y = map(number, bounds_mm)
    bottom_left = board_point((min_x, min_y), bounds_mm)
    top_right = board_point((max_x, max_y), bounds_mm)
    expected = ((0, 0), (
        rounded((max_x - min_x) * MM_TO_MIL),
        rounded((max_y - min_y) * MM_TO_MIL),
    ))
    if (bottom_left, top_right) != expected:
        raise AssertionError(
            f"Gerber-to-native direction check failed: {(bottom_left, top_right)} != {expected}"
        )
    if top_right[0] <= 0 or top_right[1] <= 0:
        raise ValueError(f"invalid Gerber board bounds ordering: {list(bounds_mm)}")
    return {
        "source_bottom_left_mm": [min_x, min_y], "native_bottom_left_mil": list(bottom_left),
        "source_top_right_mm": [max_x, max_y], "native_top_right_mil": list(top_right),
        "x_direction": "source +X -> native +X", "y_direction": "source +Y -> native +Y",
    }


def imported_footprint_map(
    plan: dict[str, Any], footprints: dict[str, Any]
) -> dict[str, str]:
    by_source: dict[str, str] = {}
    for row in (plan.get("library_map") or {}).get("footprint", []):
        source_uuid = str(row.get("source_uuid") or "")
        imported_uuid = str(row.get("imported_uuid") or "")
        if not re.fullmatch(r"[0-9a-f]{16}", source_uuid) or not re.fullmatch(
            r"[0-9a-f]{16}", imported_uuid
        ):
            raise ValueError(f"invalid footprint UUID map row: {row!r}")
        if source_uuid in by_source:
            raise ValueError(f"duplicate footprint source UUID in rebind plan: {source_uuid}")
        by_source[source_uuid] = imported_uuid
    result: dict[str, str] = {}
    for reference, footprint in footprints.items():
        source_uuid = str(footprint.get("uuid") or "")
        if source_uuid not in by_source:
            raise ValueError(f"{reference}: no imported footprint mapping for {source_uuid}")
        result[reference] = by_source[source_uuid]
    if len(result) != 330 or len(set(result.values())) != 330:
        raise ValueError(
            f"expected 330 one-to-one imported footprint mappings, got "
            f"{len(result)} refs / {len(set(result.values()))} UUIDs"
        )
    return result


def load_npth_holes(gerber: dict[str, Any]) -> list[dict[str, Any]]:
    holes: list[dict[str, Any]] = []
    for drill_file in gerber.get("drills", []):
        for hole in drill_file.get("holes", []):
            function = str(hole.get("function") or "")
            if hole.get("plated") is False or "NonPlated" in function or "NPTH" in function:
                at = hole.get("atMm")
                if not isinstance(at, list) or len(at) < 2:
                    raise ValueError(f"NPTH entry has no coordinate: {hole!r}")
                coordinate = (round(number(at[0]), 6), round(number(at[1]), 6))
                extracted_reference = (
                    hole.get("componentRef") or hole.get("componentReference")
                    or hole.get("attributedComponent") or hole.get("reference")
                )
                ownership = str(hole.get("ownership") or "")
                expected_reference = NPTH_COMPONENT_BY_SOURCE_MM.get(coordinate)
                if ownership == "boardMountingHole":
                    if str(extracted_reference or "") not in ("", "REF**"):
                        raise ValueError(f"board mounting NPTH has unexpected componentRef: {hole!r}")
                    component_reference = None
                else:
                    component_reference = str(extracted_reference or expected_reference or "").strip() or None
                if component_reference and expected_reference and component_reference != expected_reference:
                    raise ValueError(
                        f"NPTH component attribution conflicts at {coordinate}: "
                        f"{component_reference!r} != {expected_reference!r}"
                    )
                holes.append({
                    "at_mm": [number(at[0]), number(at[1])], "diameter_mm": number(hole.get("diameterMm")),
                    "tool": hole.get("tool"), "function": function, "source_file": drill_file.get("file"),
                    "component_reference": component_reference, "source_component_ref": extracted_reference,
                    "ownership": ownership or ("componentMechanicalHole" if component_reference else "boardMountingHole"),
                    "ownership_evidence": hole.get("ownershipEvidence") or [],
                })
    holes.sort(key=lambda item: (item["at_mm"][0], item["at_mm"][1], item["diameter_mm"]))
    if len(holes) != 13:
        raise ValueError(f"expected exactly 13 Gerber NPTH holes, found {len(holes)}")
    component_holes = [hole for hole in holes if hole["component_reference"]]
    global_holes = [hole for hole in holes if not hole["component_reference"]]
    if len(component_holes) != 9 or len(global_holes) != 4:
        raise ValueError(
            f"expected 9 component NPTH + 4 global mounting holes, found "
            f"{len(component_holes)} + {len(global_holes)}"
        )
    for hole in global_holes:
        if abs(hole["diameter_mm"] - 3.2) > 0.000001:
            raise ValueError(f"global REF** mounting hole is not 3.2 mm: {hole!r}")
    return holes


def native_hole_diameter(body: dict[str, Any]) -> float | None:
    if body.get("plated") is not False:
        return None
    hole = body.get("hole")
    if not isinstance(hole, dict):
        return None
    diameter = max(number(hole.get("width")), number(hole.get("height")))
    return diameter if diameter > 0 else None


def native_npth_candidates(record: Record, components: dict[str, Record]) -> list[tuple[float, float]]:
    center = (number(record.body.get("centerX")), number(record.body.get("centerY")))
    result = [center]
    record_id = record.record_id
    for component_id, component in components.items():
        if record_id.startswith(component_id) and record_id != component_id:
            result.append((number(component.body.get("x")) + center[0], number(component.body.get("y")) + center[1]))
            break
    return list(dict.fromkeys(result))


def native_npth_owner(record: Record, components_by_reference: dict[str, Record]) -> str | None:
    for reference, component in components_by_reference.items():
        if record.record_id.startswith(component.record_id) and record.record_id != component.record_id:
            return reference
    return None


def distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.hypot(number(left[0]) - number(right[0]), number(left[1]) - number(right[1]))


def close_number(left: Any, right: Any, tolerance: float = COORDINATE_TOLERANCE_MIL) -> bool:
    return abs(number(left) - number(right)) <= tolerance


def assert_shape_subset(expected: Any, actual: Any, context: str) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"{context}: expected object, got {actual!r}")
        for key, value in expected.items():
            if key not in actual:
                raise ValueError(f"{context}: missing key {key!r}")
            assert_shape_subset(value, actual[key], f"{context}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise ValueError(f"{context}: list mismatch {actual!r} != {expected!r}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            assert_shape_subset(left, right, f"{context}[{index}]")
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or not close_number(expected, actual):
            raise ValueError(f"{context}: numeric mismatch {actual!r} != {expected!r}")
        return
    if actual != expected:
        raise ValueError(f"{context}: value mismatch {actual!r} != {expected!r}")


def parse_record_file(path: Path) -> list[Record]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    result: list[Record] = []
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        terminated = line.endswith("|")
        if not terminated and line_number != len(lines):
            raise ValueError(f"{path}:{line_number}: missing record terminator")
        text = line[:-1] if terminated else line
        if "||" not in text:
            raise ValueError(f"{path}:{line_number}: not a JSON-record line")
        head_text, body_text = text.split("||", 1)
        header = json.loads(head_text)
        body = {} if body_text == "" else json.loads(body_text)
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise ValueError(f"{path}:{line_number}: record header/body must be objects")
        result.append(Record(header, body, line_number))
    return result


def footprint_source_path(library_manifest_path: Path, source_uuid: str) -> Path:
    directory = library_manifest_path.parent / "footprints"
    matches = sorted(directory.glob(f"*_{source_uuid}.efoo"))
    if len(matches) != 1:
        raise ValueError(
            f"expected one project-local footprint source for {source_uuid}, found {matches}"
        )
    return matches[0]


def pad_net_identity(record: Record) -> tuple[str, str, str]:
    try:
        payload = json.loads(record.record_id)
    except json.JSONDecodeError as exc:
        raise ValueError(f"PAD_NET at line {record.line_number} has invalid composite id") from exc
    if not isinstance(payload, list) or len(payload) != 4 or payload[0] != "PAD_NET":
        raise ValueError(f"PAD_NET at line {record.line_number} has unexpected id {payload!r}")
    return str(payload[1]), str(payload[2]), str(payload[3])


def preferred_copper_flash(pad: dict[str, Any], side_hint: str) -> dict[str, Any]:
    flashes = [
        item for item in pad.get("flashes", [])
        if item.get("layer") in {"F.Cu", "B.Cu"}
    ]
    if not flashes:
        raise ValueError(f"Gerber pad {pad.get('number')!r} has no copper flash")
    preferred_layer = "B.Cu" if side_hint.upper().startswith("B") else "F.Cu"
    return next((item for item in flashes if item.get("layer") == preferred_layer), flashes[0])


def verify_footprint_geometry_and_padnets(
    records: Sequence[Record],
    footprints: dict[str, Any],
    gerber: dict[str, Any],
    bounds: Sequence[float],
    library_manifest_path: Path,
    components_by_reference: dict[str, Record],
) -> dict[str, Any]:
    padnets_by_component: dict[str, list[tuple[str, str, Record]]] = defaultdict(list)
    for record in records:
        if record.kind != "PAD_NET":
            continue
        component_id, pad_number, local_id = pad_net_identity(record)
        padnets_by_component[component_id].append((pad_number, local_id, record))

    aggregate = hashlib.sha256()
    numbered_total = 0
    implicit_npth_total = 0
    absolute_centers_checked = 0
    refs_checked = 0
    for reference in sorted(footprints, key=natural_key):
        footprint = footprints[reference]
        component = components_by_reference[reference]
        path = footprint_source_path(library_manifest_path, str(footprint.get("uuid") or ""))
        aggregate.update(path.name.encode("utf-8"))
        aggregate.update(sha256_file(path).encode("ascii"))
        footprint_records = parse_record_file(path)
        docheads = [item for item in footprint_records if item.kind == "DOCHEAD"]
        if len(docheads) != 1 or docheads[0].body.get("docType") != "FOOTPRINT":
            raise ValueError(f"{reference}: invalid footprint DOCHEAD in {path}")
        native_pads = [item for item in footprint_records if item.kind == "PAD"]
        expected_numbered = {str(item["number"]): item for item in footprint.get("pads", [])}
        if len(expected_numbered) != len(footprint.get("pads", [])):
            raise ValueError(f"{reference}: duplicate numbered pads in library manifest")
        native_numbered: dict[str, Record] = {}
        native_npth: list[Record] = []
        for pad in native_pads:
            pad_number = str(pad.body.get("num") or "")
            if pad_number:
                if pad_number in native_numbered:
                    raise ValueError(f"{reference}: duplicate native footprint pad {pad_number}")
                native_numbered[pad_number] = pad
            elif native_hole_diameter(pad.body) is not None:
                native_npth.append(pad)
            else:
                raise ValueError(f"{reference}: unnumbered footprint PAD is not a mechanical NPTH")
        expected_holes = list(footprint.get("mechanical_npth") or [])
        if set(native_numbered) != set(expected_numbered):
            raise ValueError(
                f"{reference}: numbered footprint PAD set mismatch; "
                f"missing={sorted(set(expected_numbered) - set(native_numbered), key=natural_key)}, "
                f"extra={sorted(set(native_numbered) - set(expected_numbered), key=natural_key)}"
            )
        if len(native_npth) != len(expected_holes):
            raise ValueError(
                f"{reference}: mechanical NPTH count {len(native_npth)} != {len(expected_holes)}"
            )

        for pad_number, expected in expected_numbered.items():
            actual = native_numbered[pad_number].body
            if not close_number(actual.get("centerX"), expected["x"]) or not close_number(
                actual.get("centerY"), expected["y"]
            ):
                raise ValueError(
                    f"{reference} pad {pad_number}: local center mismatch "
                    f"{[actual.get('centerX'), actual.get('centerY')]} != {[expected['x'], expected['y']]}"
                )
            if actual.get("layerId") != expected.get("layer"):
                raise ValueError(f"{reference} pad {pad_number}: layer mismatch")
            if not close_number(actual.get("padAngle"), expected.get("pad_angle")):
                raise ValueError(f"{reference} pad {pad_number}: angle mismatch")
            assert_shape_subset(
                expected.get("shape"), actual.get("defaultPad"),
                f"{reference} pad {pad_number}.defaultPad",
            )
            assert_shape_subset(
                expected.get("hole"), actual.get("hole"),
                f"{reference} pad {pad_number}.hole",
            )
            gerber_component = (gerber.get("components") or {}).get(reference)
            if not isinstance(gerber_component, dict):
                raise ValueError(f"{reference}: missing Gerber component")
            gerber_pad = (gerber_component.get("pads") or {}).get(pad_number)
            if not isinstance(gerber_pad, dict):
                raise ValueError(f"{reference} pad {pad_number}: missing Gerber pad")
            flash = preferred_copper_flash(gerber_pad, str(gerber_component.get("sideHint") or "F"))
            expected_absolute = board_point(flash["atMm"], bounds)
            actual_absolute = (
                number(component.body.get("x")) + number(actual.get("centerX")),
                number(component.body.get("y")) + number(actual.get("centerY")),
            )
            if distance(actual_absolute, expected_absolute) > COORDINATE_TOLERANCE_MIL:
                raise ValueError(
                    f"{reference} pad {pad_number}: placed center mismatch "
                    f"{actual_absolute} != {expected_absolute}"
                )
            absolute_centers_checked += 1

        unmatched_npth = set(range(len(native_npth)))
        for expected in expected_holes:
            candidates = [
                index for index in unmatched_npth
                if close_number(native_npth[index].body.get("centerX"), expected.get("x"))
                and close_number(native_npth[index].body.get("centerY"), expected.get("y"))
                and close_number(
                    native_hole_diameter(native_npth[index].body),
                    number(expected.get("diameter_mm")) * MM_TO_MIL,
                    DIAMETER_TOLERANCE_MIL,
                )
            ]
            if len(candidates) != 1:
                raise ValueError(f"{reference}: could not uniquely match mechanical NPTH {expected!r}")
            index = candidates[0]
            unmatched_npth.remove(index)
            actual = native_npth[index]
            expected_absolute = board_point(expected["source_at_mm"], bounds)
            actual_absolute = (
                number(component.body.get("x")) + number(actual.body.get("centerX")),
                number(component.body.get("y")) + number(actual.body.get("centerY")),
            )
            if distance(actual_absolute, expected_absolute) > COORDINATE_TOLERANCE_MIL:
                raise ValueError(
                    f"{reference} mechanical NPTH placed center mismatch: "
                    f"{actual_absolute} != {expected_absolute}"
                )
            absolute_centers_checked += 1
        if unmatched_npth:
            raise ValueError(f"{reference}: unmatched native mechanical NPTH records")

        expected_padnet = sorted(
            [(str(item.body.get("num") or ""), item.record_id) for item in native_pads]
        )
        actual_entries = padnets_by_component.get(component.record_id, [])
        actual_padnet = sorted((number_text, local_id) for number_text, local_id, _ in actual_entries)
        if actual_padnet != expected_padnet:
            raise ValueError(
                f"{reference}: PAD_NET-to-footprint child mapping mismatch; "
                f"expected={expected_padnet!r}, actual={actual_padnet!r}"
            )
        for number_text, _, padnet in actual_entries:
            if not number_text and str(padnet.body.get("padNet") or ""):
                raise ValueError(f"{reference}: mechanical NPTH PAD_NET unexpectedly has a net")

        numbered_total += len(native_numbered)
        implicit_npth_total += len(native_npth)
        refs_checked += 1

    if len(padnets_by_component) != 330:
        raise ValueError(f"PAD_NET records refer to {len(padnets_by_component)} components, expected 330")
    if numbered_total != 1167 or implicit_npth_total != 9:
        raise ValueError(
            f"expected 1167 numbered footprint pads + 9 implicit component NPTH, "
            f"found {numbered_total} + {implicit_npth_total}"
        )
    return {
        "footprints_checked": refs_checked,
        "numbered_pads_checked": numbered_total,
        "implicit_component_npth_checked": implicit_npth_total,
        "pad_net_records_checked": numbered_total + implicit_npth_total,
        "absolute_centers_checked": absolute_centers_checked,
        "footprint_sources_digest": aggregate.hexdigest(),
    }


def next_ticket(records: Sequence[Record]) -> int:
    return max((int(record.header.get("ticket") or 0) for record in records), default=0) + 1


def next_z_index(records: Sequence[Record]) -> int:
    values = [record.body.get("zIndex") for record in records]
    numeric = [int(value) for value in values if isinstance(value, (int, float)) and math.isfinite(value)]
    return max(numeric, default=0) + 1


def make_npth_record(hole: dict[str, Any], bounds: Sequence[float], ticket: int, z_index: int,
                     occupied_ids: set[str], components_by_reference: dict[str, Record]) -> Record:
    board_x, board_y = board_point(hole["at_mm"], bounds)
    diameter = rounded(hole["diameter_mm"] * MM_TO_MIL)
    component_reference = hole.get("component_reference")
    identity = (
        f"{component_reference or 'GLOBAL'}:"
        f"{hole['at_mm'][0]:.6f},{hole['at_mm'][1]:.6f},{hole['diameter_mm']:.6f}"
    )
    local_id = stable_id("pcb-npth", identity)
    if component_reference:
        component = components_by_reference.get(str(component_reference))
        if component is None:
            raise ValueError(f"NPTH refers to missing native COMPONENT {component_reference}")
        record_id = component.record_id + local_id
        x = rounded(number(board_x) - number(component.body.get("x")))
        y = rounded(number(board_y) - number(component.body.get("y")))
    else:
        record_id = local_id
        x, y = board_x, board_y
    if record_id in occupied_ids:
        raise ValueError(f"deterministic NPTH id collides with existing record: {record_id}")
    occupied_ids.add(record_id)
    # Installed 3.2.206 runtime sources consistently encode an ungrouped PCB
    # PAD as numeric 0.  The bundled schema narrows this to string even though
    # its own comment records zero string occurrences; using "0" would create
    # a real group identifier rather than the runtime's ungrouped sentinel.
    return Record(
        {"type": "PAD", "ticket": ticket, "id": record_id},
        {
            "partitionId": None, "groupId": 0, "netName": "", "layerId": 12, "num": "",
            "centerX": x, "centerY": y, "padAngle": 0,
            "hole": {"holeType": "ROUND", "width": diameter, "height": diameter},
            "defaultPad": {"padType": "ELLIPSE", "width": diameter, "height": diameter},
            "specialPad": [], "padOffsetX": 0, "padOffsetY": 0, "relativeAngle": 0,
            "plated": False, "padType": "NORMAL", "topSolderExpansion": None,
            "bottomSolderExpansion": None, "topPasteExpansion": None, "bottomPasteExpansion": None,
            "locked": False, "zIndex": z_index, "connectMode": None, "spokeSpace": None,
            "spokeWidth": None, "spokeAngle": None, "unusedInnerLayers": [],
            "padLen": 0, "propagationDelay": 0,
            "attrsMap": {
                "Gerber NPTH Source": identity,
                "Gerber Component Reference": str(component_reference or "REF**"),
            },
        },
        0,
    )


def place_components(
    records: list[Record],
    footprints: dict[str, Any],
    imported_footprint_uuids: dict[str, str],
    bounds: Sequence[float],
    removed: set[str],
) -> tuple[dict[str, Record], dict[str, Record], list[dict[str, Any]]]:
    native_components = [record for record in records if record.kind == "COMPONENT"]
    children = component_child_attributes(records)
    child_records = component_child_attribute_records(records)
    known_refs = set(footprints) | removed
    by_reference: dict[str, Record] = {}
    evidence_by_reference: dict[str, list[str]] = {}
    for component in native_components:
        if not re.fullmatch(r"[0-9a-f]{16}", component.record_id):
            raise ValueError(
                f"COMPONENT at line {component.line_number} has unsupported id {component.record_id!r}; "
                "expected a native 16-lowercase-hex element id"
            )
        attributes = merged_attributes(component, children)
        try:
            reference = component_reference(attributes, known_refs)
        except ValueError as exc:
            preview = {key: values[:4] for key, values in sorted(attributes.items())}
            raise ValueError(
                f"COMPONENT {component.record_id} at line {component.line_number}: {exc}; "
                f"attribute preview={preview!r}"
            ) from exc
        if reference in by_reference:
            raise ValueError(f"duplicate native COMPONENT reference {reference}")
        by_reference[reference] = component
        if reference in footprints:
            try:
                evidence_by_reference[reference] = verify_footprint_evidence(
                    reference, attributes, footprints[reference], imported_footprint_uuids[reference]
                )
            except ValueError as exc:
                raise ValueError(
                    f"COMPONENT {component.record_id} at line {component.line_number}: {exc}"
                ) from exc

    present = set(by_reference)
    expected = set(footprints)
    if present & removed:
        raise ValueError(f"removed page-6 capacitors still exist in generated PCB: {sorted(present & removed, key=natural_key)}")
    if present != expected:
        raise ValueError(
            f"native COMPONENT set does not equal the 330 latest physical refs: "
            f"missing={sorted(expected - present, key=natural_key)[:30]}, "
            f"unexpected={sorted(present - expected, key=natural_key)[:30]}"
        )

    placements: list[dict[str, Any]] = []
    board_width = (number(bounds[2]) - number(bounds[0])) * MM_TO_MIL
    board_height = (number(bounds[3]) - number(bounds[1])) * MM_TO_MIL
    for reference in sorted(expected, key=natural_key):
        component = by_reference[reference]
        footprint = footprints[reference]
        anchor = footprint.get("anchor_mm")
        if not isinstance(anchor, list) or len(anchor) < 2:
            raise ValueError(f"{reference}: footprint manifest has no anchor_mm")
        x, y = board_point(anchor, bounds)
        if not (-COORDINATE_TOLERANCE_MIL <= number(x) <= board_width + COORDINATE_TOLERANCE_MIL
                and -COORDINATE_TOLERANCE_MIL <= number(y) <= board_height + COORDINATE_TOLERANCE_MIL):
            raise ValueError(f"{reference}: Gerber anchor maps outside the board: anchor={anchor}, mil={[x, y]}")
        old = {
            "x": component.body.get("x"), "y": component.body.get("y"),
            "angle": component.body.get("angle"), "rotation": component.body.get("rotation"),
            "isMirror": component.body.get("isMirror"),
        }
        old_x = component.body.get("x")
        old_y = component.body.get("y")
        if not finite_coordinate(old_x) or not finite_coordinate(old_y):
            raise ValueError(f"{reference}: native COMPONENT has invalid source placement {old!r}")
        for field in ("angle", "rotation"):
            value = component.body.get(field)
            if value is not None and (not finite_coordinate(value) or abs(float(value)) > 1e-9):
                raise ValueError(
                    f"{reference}: native COMPONENT {field}={value!r}; "
                    "placement geometry is baked and only zero-orientation translation is supported"
                )
        if component.body.get("isMirror") not in (None, False):
            raise ValueError(
                f"{reference}: native COMPONENT isMirror={component.body.get('isMirror')!r}; "
                "placement geometry is baked and mirrored source components are unsupported"
            )

        delta_x = number(x) - number(old_x)
        delta_y = number(y) - number(old_y)
        translated_attributes: list[dict[str, Any]] = []
        for attribute in child_records.get(component.record_id, []):
            attr_x = attribute.body.get("x")
            attr_y = attribute.body.get("y")
            if attr_x is None and attr_y is None:
                continue
            if not finite_coordinate(attr_x) or not finite_coordinate(attr_y):
                raise ValueError(
                    f"{reference}: child ATTR {attribute.record_id} has partial/invalid coordinates "
                    f"x={attr_x!r}, y={attr_y!r}"
                )
            offset_before = [number(attr_x) - number(old_x), number(attr_y) - number(old_y)]
            attribute.body["x"] = rounded(number(attr_x) + delta_x)
            attribute.body["y"] = rounded(number(attr_y) + delta_y)
            offset_after = [number(attribute.body["x"]) - number(x), number(attribute.body["y"]) - number(y)]
            if distance(offset_before, offset_after) > 0.000002:
                raise AssertionError(
                    f"{reference}: child ATTR {attribute.record_id} local offset changed: "
                    f"{offset_before!r} != {offset_after!r}"
                )
            translated_attributes.append({
                "record_id": attribute.record_id,
                "key": attribute.body.get("key"),
                "old_mil": [attr_x, attr_y],
                "new_mil": [attribute.body["x"], attribute.body["y"]],
                "local_offset_mil": [rounded(offset_before[0]), rounded(offset_before[1])],
            })
        component.body["x"] = x
        component.body["y"] = y
        component.body["angle"] = 0
        if "rotation" in component.body:
            component.body["rotation"] = 0
        if "isMirror" in component.body:
            component.body["isMirror"] = False
        placements.append({
            "reference": reference, "component_id": component.record_id,
            "footprint_uuid": footprint.get("uuid"), "footprint_title": footprint.get("title"),
            "imported_footprint_uuid": imported_footprint_uuids[reference],
            "footprint_evidence": evidence_by_reference[reference], "anchor_mm": anchor,
            "placed_mil": [x, y], "old_placement": old,
            "translated_child_attributes": translated_attributes,
            "orientation": {
                "angle": 0,
                "rotation": 0 if "rotation" in component.body else "field_absent",
                "isMirror": False if "isMirror" in component.body else "field_absent",
            },
        })
    if len(placements) != 330:
        raise ValueError(f"expected 330 placed physical refs, found {len(placements)}")
    return {record.record_id: record for record in native_components}, by_reference, placements


def preserve_npth(
    records: list[Record],
    components: dict[str, Record],
    components_by_reference: dict[str, Record],
    footprints: dict[str, Any],
    holes: list[dict[str, Any]],
    bounds: Sequence[float],
) -> list[dict[str, Any]]:
    native_npth = [record for record in records if record.kind == "PAD" and native_hole_diameter(record.body) is not None]
    unused_records = set(range(len(native_npth)))
    occupied_ids = {record.record_id for record in records if record.record_id}
    ticket = next_ticket(records)
    z_index = next_z_index(records)
    results: list[dict[str, Any]] = []

    for hole in holes:
        target = board_point(hole["at_mm"], bounds)
        target_diameter = hole["diameter_mm"] * MM_TO_MIL
        matches: list[tuple[float, int, tuple[float, float]]] = []
        for index in unused_records:
            record = native_npth[index]
            if abs(number(native_hole_diameter(record.body)) - target_diameter) > DIAMETER_TOLERANCE_MIL:
                continue
            for candidate in native_npth_candidates(record, components):
                separation = distance(candidate, target)
                if separation <= COORDINATE_TOLERANCE_MIL:
                    matches.append((separation, index, candidate))
        matched_indices = {item[1] for item in matches}
        if len(matched_indices) > 1:
            raise ValueError(f"duplicate native NPTH records at {target}: {[native_npth[i].record_id for i in matched_indices]}")
        if matched_indices:
            index = next(iter(matched_indices))
            record = native_npth[index]
            expected_owner = hole.get("component_reference")
            actual_owner = native_npth_owner(record, components_by_reference)
            if actual_owner != expected_owner:
                raise ValueError(
                    f"NPTH at {target} has wrong native ownership: "
                    f"expected {expected_owner or 'top-level REF**'}, got {actual_owner or 'top-level'}"
                )
            unused_records.remove(index)
            results.append({
                **hole, "board_mil": list(target), "status": "existing", "record_id": record.record_id,
                "native_num": record.body.get("num"),
                "storage": "component_child" if actual_owner else "top_level",
            })
            continue
        if hole.get("component_reference"):
            reference = str(hole["component_reference"])
            embedded = [
                item for item in footprints[reference].get("mechanical_npth", [])
                if distance(item.get("source_at_mm", ()), hole["at_mm"]) <= 0.000001
                and abs(number(item.get("diameter_mm")) - number(hole["diameter_mm"])) <= 0.000001
            ]
            if len(embedded) != 1:
                raise ValueError(
                    f"{reference}: Gerber component NPTH is not uniquely present in the "
                    f"project-local footprint manifest: {hole!r}"
                )
            results.append({
                **hole,
                "board_mil": list(target),
                "status": "library_implicit",
                "record_id": None,
                "native_num": "",
                "storage": "project_local_footprint",
            })
            continue
        appended = make_npth_record(hole, bounds, ticket, z_index, occupied_ids, components_by_reference)
        records.append(appended)
        ticket += 1
        z_index += 1
        results.append({
            **hole, "board_mil": list(target), "status": "appended", "record_id": appended.record_id,
            "native_num": "", "storage": "component_child" if hole.get("component_reference") else "top_level",
        })

    if unused_records:
        unexpected = [native_npth[index].record_id for index in sorted(unused_records)]
        raise ValueError(f"native PCB contains non-Gerber or unmatchable NPTH records: {unexpected}")
    return results


def transform(args: argparse.Namespace) -> dict[str, Any]:
    input_path = args.input.resolve()
    library_path = args.library_manifest.resolve()
    rebind_plan_path = args.rebind_plan.resolve()
    gerber_path = args.gerber.resolve()
    output_path = safe_output_path(args.output, "placed PCB output")
    report_path = safe_output_path(args.report, "placement report")
    if input_path == output_path:
        raise ValueError("input and output PCB source paths must differ")

    records = parse_source(input_path)
    source_counts = Counter(record.kind for record in records)
    expected_source_counts = {
        "COMPONENT": 330,
        "ATTR": 990,
        "PAD": 0,
        "PAD_NET": 1176,
        "NET": 280,
    }
    actual_source_counts = {key: source_counts.get(key, 0) for key in expected_source_counts}
    if actual_source_counts != expected_source_counts:
        raise ValueError(
            f"unexpected schematic-to-PCB base structure: {actual_source_counts}; "
            f"expected {expected_source_counts}"
        )
    original_count = len(records)
    component_ids = {record.record_id for record in records if record.kind == "COMPONENT"}
    original_nonplacement = semantic_digest(
        record for record in records
        if record.kind != "COMPONENT"
        and not (record.kind == "ATTR" and str(record.body.get("parentId") or "") in component_ids)
    )
    original_pad_net = semantic_digest(record for record in records if record.kind in {"PAD", "PAD_NET", "NET"})
    library = json.loads(library_path.read_text(encoding="utf-8"))
    rebind_plan = json.loads(rebind_plan_path.read_text(encoding="utf-8"))
    gerber = json.loads(gerber_path.read_text(encoding="utf-8"))
    footprints = library.get("footprints") or {}
    if len(footprints) != 330:
        raise ValueError(f"library manifest must contain 330 physical footprint refs, found {len(footprints)}")
    imported_uuids = imported_footprint_map(rebind_plan, footprints)
    bounds = (gerber.get("coordinateTransform") or {}).get("boardBoundsSourceMm")
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError("Gerber boardBoundsSourceMm is missing")
    direction_check = validate_coordinate_transform(bounds)
    removed = set((gerber.get("latestPatches") or {}).get("page6RemovedComponents") or [])
    if len(removed) != 10:
        raise ValueError(f"expected ten removed page-6 capacitors, found {len(removed)}")
    if removed & set(footprints):
        raise ValueError(f"removed capacitors unexpectedly have generated footprints: {sorted(removed & set(footprints))}")

    components, components_by_reference, placements = place_components(
        records, footprints, imported_uuids, bounds, removed
    )
    footprint_geometry = verify_footprint_geometry_and_padnets(
        records, footprints, gerber, bounds, library_path, components_by_reference
    )
    holes = load_npth_holes(gerber)
    npth = preserve_npth(
        records, components, components_by_reference, footprints, holes, bounds
    )
    original_records_after = records[:original_count]
    preserved_nonplacement = semantic_digest(
        record for record in original_records_after
        if record.kind != "COMPONENT"
        and not (record.kind == "ATTR" and str(record.body.get("parentId") or "") in component_ids)
    )
    preserved_pad_net = semantic_digest(record for record in original_records_after if record.kind in {"PAD", "PAD_NET", "NET"})
    if original_nonplacement != preserved_nonplacement or original_pad_net != preserved_pad_net:
        raise AssertionError("placement unexpectedly changed an existing non-placement record")

    translated_attribute_count = sum(
        len(item["translated_child_attributes"]) for item in placements
    )
    visible_designator_count = sum(
        1 for item in placements for attribute in item["translated_child_attributes"]
        if str(attribute.get("key") or "").casefold() == "designator"
    )
    if translated_attribute_count != 330 or visible_designator_count != 330:
        raise ValueError(
            "expected exactly one positioned Designator ATTR per placed component; "
            f"translated={translated_attribute_count}, designators={visible_designator_count}"
        )

    output_text = serialize_source(records)
    output_sha = hashlib.sha256(output_text.encode("utf-8")).hexdigest()
    report = {
        "schema": "stm32h747-native-pcb-placement-v1",
        "status": "placed-not-manufacturing-ready",
        "inputs": {
            "native_pcb": {"path": str(input_path), "sha256": sha256_file(input_path)},
            "library_manifest": {"path": str(library_path), "sha256": sha256_file(library_path)},
            "component_rebind_plan": {
                "path": str(rebind_plan_path), "sha256": sha256_file(rebind_plan_path)
            },
            "gerber_footprints": {"path": str(gerber_path), "sha256": sha256_file(gerber_path)},
        },
        "output": {"path": str(output_path), "sha256": output_sha},
        "coordinate_transform": {
            "board_bounds_source_mm": bounds,
            "formula": {
                "x_mil": "(sourceX - boardMinX) * 39.37007874015748",
                "y_mil": "(sourceY - boardMinY) * 39.37007874015748",
            },
            "board_size_mm": [rounded(number(bounds[2]) - number(bounds[0])),
                              rounded(number(bounds[3]) - number(bounds[1]))],
            "board_size_mil": [rounded((number(bounds[2]) - number(bounds[0])) * MM_TO_MIL),
                               rounded((number(bounds[3]) - number(bounds[1])) * MM_TO_MIL)],
            "direction_check": direction_check,
            "footprint_orientation": "baked into project-local footprint geometry; component angle/rotation is zero and mirror is false",
        },
        "counts": {
            "input_records": original_count, "output_records": len(records),
            "placed_components": len(placements), "removed_components_absent": len(removed),
            "translated_component_attributes": translated_attribute_count,
            "translated_designators": visible_designator_count,
            "gerber_npth": len(npth), "existing_npth": sum(item["status"] == "existing" for item in npth),
            "implicit_library_npth": sum(item["status"] == "library_implicit" for item in npth),
            "appended_npth": sum(item["status"] == "appended" for item in npth),
            "component_npth": sum(bool(item["component_reference"]) for item in npth),
            "global_mounting_npth": sum(not item["component_reference"] for item in npth),
        },
        "invariants": {
            "physical_reference_set_exact": True, "latest_net_records_semantically_unchanged": True,
            "existing_nonplacement_records_semantically_unchanged": True,
            "component_attribute_local_offsets_preserved": True,
            "removed_page6_capacitors_not_placed": sorted(removed, key=natural_key),
            "manufacturing_ready": False,
        },
        "semantic_hashes": {
            "existing_nonplacement_before": original_nonplacement,
            "existing_nonplacement_after": preserved_nonplacement,
            "existing_pad_padnet_net_before": original_pad_net,
            "existing_pad_padnet_net_after": preserved_pad_net,
        },
        "base_structure": {
            "record_counts": dict(sorted(source_counts.items())),
            "referenced_footprint_geometry": footprint_geometry,
        },
        "placements": placements,
        "npth": npth,
    }
    if not args.dry_run:
        atomic_write_text(output_path, output_text)
        atomic_write_text(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="raw PCB JSON-record source captured after schematic-to-PCB conversion")
    parser.add_argument("--library-manifest", type=Path, default=DEFAULT_LIBRARY_MANIFEST,
                        help="project-local native library manifest containing per-ref anchor_mm")
    parser.add_argument("--rebind-plan", type=Path, default=DEFAULT_REBIND_PLAN,
                        help="final imported project-library UUID map")
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER,
                        help="Gerber footprint evidence with board bounds and 13 NPTH drills")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="placed native PCB JSON-record output")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="machine-readable placement report")
    parser.add_argument("--dry-run", action="store_true", help="validate and report to stdout without writing files")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        report = transform(parse_args(argv))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], **report["counts"],
                      "output": report["output"]["path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
