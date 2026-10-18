#!/usr/bin/env python3
"""Build the omitted global front-silkscreen geometry as native PCB records.

This generator is deliberately independent of the copper-routing builder.  It
recovers only the archived Gerber objects owned by KiCad's escaped ``G***``
component attribute: the KOPTi artwork and four barrel-polarity fills.  The
result is an editable merge reference, not a complete or manufacturing-ready
PCB document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GEOMETRY = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
DEFAULT_GERBER = (
    ROOT / "보드 자료" / "MCU_BOARD_v19_260616_Gerber" /
    "MCU_BOARD_v19_260616-F_Silkscreen.gbr"
)
DEFAULT_OUTPUT = ROOT / "output" / "native-pcb" / "global-silkscreen-reference.epru"
DEFAULT_MANIFEST = (
    ROOT / "output" / "native-pcb" / "global-silkscreen-reference-manifest.json"
)
EDITOR_VERSION = "3.2.206"
DEFAULT_UPDATE_TIME = 1791928414106
MM_TO_MIL = 39.37007874015748
FRONT_SILK_LAYER_ID = 3
GLOBAL_REFERENCE = r"G\u002A\u002A\u002A"
EXPECTED_GERBER_SHA256 = "051feda41f96daf298919e49161d10f20c64c13a4435f5ac3df04c2d52a761f5"
EXPECTED_GEOMETRY_SHA256 = "e857c9855c1ce97ed3aec792878d0339c9a855522e744c9defcd78269adac304"
EXPECTED_LINE_COUNT = 492
EXPECTED_KOPTI_REGION_COUNT = 8
EXPECTED_BARREL_REGION_COUNT = 4


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(kind: str, key: str) -> str:
    return hashlib.sha256(f"stm32h747-v19\0{kind}\0{key}".encode()).hexdigest()[:16]


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite numeric value: {value!r}")
    return result


def rounded(value: float, digits: int = 6) -> int | float:
    result = round(number(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


class NativeDocument:
    """Deterministic EasyEDA Pro 3.2 JSON-record writer."""

    def __init__(self, uuid: str):
        self.uuid = uuid
        self.ticket = 0
        self.element = 0
        self.records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.add("DOCHEAD", {
            "docType": "PCB",
            "client": stable_id("client", "STM32H747_MCU_BOARD_v19"),
            "uuid": uuid,
            "updateTime": DEFAULT_UPDATE_TIME,
            "version": str(DEFAULT_UPDATE_TIME),
            "editVersion": EDITOR_VERSION,
            "user": {"uuid": uuid, "username": "", "nickname": ""},
        })

    def add(self, kind: str, body: dict[str, Any], record_id: str | None = None) -> str:
        self.ticket += 1
        header: dict[str, Any] = {"type": kind, "ticket": self.ticket}
        if record_id is not None:
            header["id"] = record_id
        self.records.append((header, body))
        return record_id or ""

    def primitive(self, kind: str, body: dict[str, Any]) -> str:
        self.element += 1
        record_id = stable_id("element", f"{self.uuid}:{kind}:{self.element}")
        return self.add(kind, body, record_id)

    def source(self) -> str:
        return "".join(
            f"{compact(header)}||{compact(body)}|\n" for header, body in self.records
        )


def signed_area(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        number(points[index][0]) * number(points[(index + 1) % len(points)][1])
        - number(points[(index + 1) % len(points)][0]) * number(points[index][1])
        for index in range(len(points))
    )


def local_point(
    source_mm: Sequence[float], bounds_mm: Sequence[float]
) -> tuple[int | float, int | float]:
    """Map Gerber absolute millimetres into EasyEDA PCB Y-up mil space."""
    min_x, min_y, _, _ = map(number, bounds_mm)
    return (
        rounded((number(source_mm[0]) - min_x) * MM_TO_MIL),
        rounded((number(source_mm[1]) - min_y) * MM_TO_MIL),
    )


def mm_value(value_mm: float) -> int | float:
    return rounded(number(value_mm) * MM_TO_MIL)


def polygon_path(
    points_mm: Iterable[Sequence[float]], bounds_mm: Sequence[float]
) -> list[Any]:
    converted: list[tuple[int | float, int | float]] = []
    for point in points_mm:
        value = local_point(point, bounds_mm)
        if not converted or value != converted[-1]:
            converted.append(value)
    if len(converted) > 1 and converted[0] == converted[-1]:
        converted.pop()
    if len(converted) < 3:
        raise ValueError(f"silkscreen polygon has fewer than three unique points: {converted!r}")
    area = signed_area(converted)
    if abs(area) <= 1e-12:
        raise ValueError("silkscreen polygon has zero signed area")
    # EasyEDA PCB coordinates are Y-up.  Canonical independent FILL outlines
    # are clockwise, hence negative shoelace area.
    if area > 0:
        converted = [converted[0], *reversed(converted[1:])]
    path: list[Any] = [converted[0][0], converted[0][1], "L"]
    for x, y in converted[1:]:
        path.extend((x, y))
    return path


def line_path_points(path: Sequence[Any]) -> list[tuple[float, float]]:
    if len(path) < 7 or path[2] != "L" or len(path[3:]) % 2:
        raise ValueError(f"invalid native straight polygon path: {path!r}")
    return [(number(path[0]), number(path[1]))] + [
        (number(path[index]), number(path[index + 1]))
        for index in range(3, len(path), 2)
    ]


def region_path(region: dict[str, Any], bounds_mm: Sequence[float]) -> list[list[Any]]:
    contours = region.get("contours") or []
    if len(contours) != 1:
        raise ValueError(f"global silkscreen region must have one contour: {len(contours)}")
    contour = contours[0]
    if not contour:
        raise ValueError("global silkscreen region has an empty contour")
    points: list[Sequence[float]] = []
    for index, segment in enumerate(contour):
        if segment.get("kind") != "line":
            raise ValueError(f"global silkscreen region has a non-line segment: {segment!r}")
        if index == 0:
            points.append(segment["startMm"])
        elif segment["startMm"] != contour[index - 1]["endMm"]:
            raise ValueError(f"discontinuous region contour at segment {index}")
        points.append(segment["endMm"])
    if points[-1] != points[0]:
        raise ValueError("global silkscreen region contour is not closed")
    return [polygon_path(points, bounds_mm)]


def primitive_common(z_index: int) -> dict[str, Any]:
    return {
        "partitionId": None,
        "groupId": 0,
        "locked": False,
        "zIndex": z_index,
        "netName": "",
        "layerId": FRONT_SILK_LAYER_ID,
    }


def validate_raw_gerber(path: Path, geometry: dict[str, Any]) -> dict[str, Any]:
    actual_hash = sha256_file(path)
    source_entry = next(
        (
            item for item in geometry.get("source", {}).get("sourceFiles", [])
            if item.get("layer") == "F.SilkS"
        ),
        None,
    )
    if not source_entry:
        raise ValueError("geometry manifest has no F.SilkS source entry")
    if source_entry.get("file") != path.name:
        raise ValueError(f"F.SilkS filename mismatch: {source_entry.get('file')} != {path.name}")
    if actual_hash != source_entry.get("sha256") or actual_hash != EXPECTED_GERBER_SHA256:
        raise ValueError(
            f"F.SilkS Gerber hash mismatch: actual={actual_hash}, "
            f"manifest={source_entry.get('sha256')}, expected={EXPECTED_GERBER_SHA256}"
        )
    text = path.read_text(encoding="utf-8", errors="strict")
    escaped_attribute = f"%TO.C,{GLOBAL_REFERENCE}*%"
    checks = {
        "component_attribute_occurrences": text.count(escaped_attribute),
        "file_polarity_positive_attributes": text.count("%TF.FilePolarity,Positive*%"),
        "file_polarity_negative_attributes": text.count("%TF.FilePolarity,Negative*%"),
        "dark_polarity_directives": text.count("%LPD*%"),
        "clear_polarity_directives": text.count("%LPC*%"),
    }
    expected = {
        "component_attribute_occurrences": 2,
        "file_polarity_positive_attributes": 1,
        "file_polarity_negative_attributes": 0,
        "dark_polarity_directives": 1,
        "clear_polarity_directives": 0,
    }
    if checks != expected:
        raise ValueError(f"unexpected raw F.SilkS polarity/attribute evidence: {checks!r}")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": actual_hash,
        **checks,
    }


def load_global_geometry(
    path: Path, gerber_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    geometry_bytes = path.read_bytes()
    geometry = json.loads(geometry_bytes.decode("utf-8"))
    raw_audit = validate_raw_gerber(gerber_path, geometry)
    component = geometry.get("components", {}).get(GLOBAL_REFERENCE)
    if not component:
        raise ValueError(f"geometry manifest has no escaped {GLOBAL_REFERENCE!r} component")
    layers = component.get("layerGeometry") or {}
    if set(layers) != {"F.SilkS"}:
        raise ValueError(f"global component has unexpected layers: {sorted(layers)}")
    objects = layers["F.SilkS"]
    canonical_geometry_hash = sha256_bytes(compact(objects).encode("utf-8"))
    if canonical_geometry_hash != EXPECTED_GEOMETRY_SHA256:
        raise ValueError(
            "global geometry canonical hash mismatch: "
            f"{canonical_geometry_hash} != {EXPECTED_GEOMETRY_SHA256}"
        )
    if any(item.get("polarity") != "dark" for item in objects):
        raise ValueError("global silkscreen contains non-dark extracted geometry")
    if any((item.get("attrs") or {}).get("C") != GLOBAL_REFERENCE for item in objects):
        raise ValueError("global silkscreen object lost the escaped G*** owner attribute")
    lines = [item for item in objects if item.get("kind") == "line"]
    regions = [item for item in objects if item.get("kind") == "region"]
    other = [item for item in objects if item.get("kind") not in {"line", "region"}]
    if other:
        raise ValueError(f"unsupported global silkscreen object kinds: {Counter(i.get('kind') for i in other)}")
    region_apertures = Counter(str(item.get("aperture")) for item in regions)
    if (
        len(lines) != EXPECTED_LINE_COUNT
        or any(item.get("aperture") != "D10" for item in lines)
        or region_apertures != Counter({
            "D10": EXPECTED_KOPTI_REGION_COUNT,
            "D19": EXPECTED_BARREL_REGION_COUNT,
        })
    ):
        raise ValueError(
            f"global geometry count/aperture mismatch: lines={len(lines)}, "
            f"regions={dict(region_apertures)}"
        )
    apertures = geometry.get("aperturesByLayer", {}).get("F.SilkS", {})
    if apertures.get("D10", {}).get("template") != "C" or apertures["D10"].get("paramsMm") != [0.1]:
        raise ValueError(f"unexpected D10 global-line aperture: {apertures.get('D10')!r}")
    if apertures.get("D19", {}).get("template") != "C" or apertures["D19"].get("paramsMm") != [0.0]:
        raise ValueError(f"unexpected D19 zero-width region aperture: {apertures.get('D19')!r}")
    bounds = geometry.get("coordinateTransform", {}).get("boardBoundsSourceMm")
    if bounds != [147.46, -218.96, 247.46, -64.96]:
        raise ValueError(f"unexpected Gerber board bounds: {bounds!r}")
    audit = {
        "geometry_manifest": {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256_bytes(geometry_bytes),
            "canonical_global_geometry_sha256": canonical_geometry_hash,
        },
        "raw_gerber": raw_audit,
        "global_owner_attribute": GLOBAL_REFERENCE,
        "board_bounds_source_mm": bounds,
        "source_object_counts": {
            "line_D10_KOPTi": len(lines),
            "region_D10_KOPTi": region_apertures["D10"],
            "region_D19_barrel_polarity": region_apertures["D19"],
            "total": len(objects),
        },
    }
    return geometry, lines, regions, audit


def add_document_scaffold(doc: NativeDocument) -> None:
    doc.add("META", {
        "board": doc.uuid,
        "parent": "",
        "title": "STM32H747_MCU_BOARD_v19 global front silkscreen reference",
        "source": f"{doc.uuid}|project",
        "zIndex": None,
    }, "META")
    doc.add("LAYER", {
        "layerId": FRONT_SILK_LAYER_ID,
        "layerType": "TOP_SILK",
        "layerName": "Top Silkscreen Layer",
        "use": True,
        "show": True,
        "locked": False,
        "activeColor": "#ffcc00",
        "activateTransparency": 1,
        "inactiveColor": "#7f6600",
        "inactiveTransparency": 0.5,
    }, compact(["LAYER", FRONT_SILK_LAYER_ID]))
    doc.add("CANVAS", {
        "originX": 0,
        "originY": 0,
        "unit": "mm",
        "gridXSize": 10,
        "gridYSize": 10,
        "snapXSize": 1,
        "snapYSize": 1,
        "altSnapXSize": 0.1,
        "altSnapYSize": 0.1,
        "gridType": "NONE",
        "multiGridType": "NONE",
        "multiGridRatio": 10,
        "highlightValue": 0.5,
        "layerBrightness": "NORMAL",
    }, "CANVAS")
    doc.add("ACTIVE_LAYER", {"layerId": FRONT_SILK_LAYER_ID}, "ACTIVE_LAYER")
    doc.add("PREFERENCE", {
        "startTrackWidthFollowLast": False,
        "lastTrackWidth": mm_value(0.2),
        "startViaSizeFollowLast": False,
        "lastViaInnerDiameter": mm_value(0.3),
        "lastViaDiameter": mm_value(0.6),
        "snap": True,
        "routingMode": "NONE",
        "routingCorner": "L45",
        "removeLoop": True,
        "rotatingObject": False,
        "trackFollow": False,
        "stretchTrackMinCorner": 1,
        "preferenceConfig": "project",
        "realTimeUpdateUnusedLayers": False,
        "unusedPadRange": "ALL",
        "pushVia": "OPTIMIZA_OPEN",
        "pathOptimization4BePushed": "NONE",
        "currentPathOptimization4BePushed": "OPTIMIZA_WEAK",
        "removeCircuitsContainingVias": True,
        "removeAntenna": True,
    }, "PREFERENCE")


def build_source(
    geometry: dict[str, Any],
    lines: list[dict[str, Any]],
    regions: list[dict[str, Any]],
    source_audit: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    bounds = geometry["coordinateTransform"]["boardBoundsSourceMm"]
    lower_left = local_point((bounds[0], bounds[1]), bounds)
    upper_right = local_point((bounds[2], bounds[3]), bounds)
    expected_upper_right = (mm_value(bounds[2] - bounds[0]), mm_value(bounds[3] - bounds[1]))
    if lower_left != (0, 0) or upper_right != expected_upper_right:
        raise ValueError(
            f"Gerber-to-native Y-up corner mismatch: {lower_left}, {upper_right}, "
            f"expected {expected_upper_right}"
        )
    uuid = stable_id("pcb", "global-silkscreen-reference")
    doc = NativeDocument(uuid)
    add_document_scaffold(doc)
    primitive_manifest: list[dict[str, Any]] = []
    source_line_geometry: list[dict[str, Any]] = []
    source_fill_paths: list[list[list[Any]]] = []
    area_relative_errors: list[float] = []
    z_index = 0
    line_width_mm = geometry["aperturesByLayer"]["F.SilkS"]["D10"]["paramsMm"][0]
    for index, item in enumerate(lines):
        z_index += 1
        start = local_point(item["startMm"], bounds)
        end = local_point(item["endMm"], bounds)
        body = {
            **primitive_common(z_index),
            "startX": start[0],
            "startY": start[1],
            "endX": end[0],
            "endY": end[1],
            "width": mm_value(line_width_mm),
        }
        primitive_id = doc.primitive("LINE", body)
        source_line_geometry.append({
            "start": list(start),
            "end": list(end),
            "width": body["width"],
        })
        primitive_manifest.append({
            "id": primitive_id,
            "type": "LINE",
            "source_index": index,
            "role": "KOPTi_logo_stroke",
        })
    region_roles = Counter()
    for index, item in enumerate(regions):
        z_index += 1
        paths = region_path(item, bounds)
        path_points = line_path_points(paths[0])
        if signed_area(path_points) >= 0:
            raise ValueError(f"region {index} did not become a clockwise Y-up native path")
        contour = item["contours"][0]
        source_points = [contour[0]["startMm"], *[segment["endMm"] for segment in contour]]
        expected_area = abs(signed_area(source_points)) * MM_TO_MIL * MM_TO_MIL
        actual_area = abs(signed_area(path_points))
        if expected_area <= 0:
            raise ValueError(f"region {index} has zero source area")
        area_relative_errors.append(abs(actual_area - expected_area) / expected_area)
        role = "KOPTi_logo_fill" if item["aperture"] == "D10" else "barrel_polarity_fill"
        region_roles[role] += 1
        primitive_id = doc.primitive("FILL", {
            **primitive_common(z_index),
            "width": 0,
            "fillStyle": "SOLID",
            "path": paths,
            "isBridgingCopper": False,
            "networkList": [],
            "refs": [],
        })
        source_fill_paths.append(paths)
        primitive_manifest.append({
            "id": primitive_id,
            "type": "FILL",
            "source_index": index,
            "source_aperture": item["aperture"],
            "role": role,
        })
    source = doc.source()
    line_hash = sha256_bytes(compact(source_line_geometry).encode("utf-8"))
    fill_hash = sha256_bytes(compact(source_fill_paths).encode("utf-8"))
    manifest = {
        "schemaVersion": 1,
        "status": "editable_merge_reference_not_complete_pcb",
        "description": (
            "Native EasyEDA Pro PCB records for the archived global front-silkscreen "
            "G*** geometry omitted from per-component footprints."
        ),
        "source": source_audit,
        "coordinate_transform": {
            "source": "Gerber absolute millimetres, Y-up",
            "native": "board-local mil, Y-up",
            "formula": {
                "x": "(sourceX - boardMinX) * 39.37007874015748",
                "y": "(sourceY - boardMinY) * 39.37007874015748",
            },
            "corner_check_mil": {
                "source_min_xy_to_native": list(lower_left),
                "source_max_xy_to_native": list(upper_right),
            },
        },
        "native_document": {
            "doc_type": "PCB",
            "uuid": uuid,
            "target_layer_id": FRONT_SILK_LAYER_ID,
            "target_layer_type": "TOP_SILK",
            "group_id": 0,
            "primitive_id_format": "16 lower-case hexadecimal characters",
        },
        "geometry": {
            "expected_source_counts": {
                "line_D10_KOPTi": EXPECTED_LINE_COUNT,
                "region_D10_KOPTi": EXPECTED_KOPTI_REGION_COUNT,
                "region_D19_barrel_polarity": EXPECTED_BARREL_REGION_COUNT,
                "total": EXPECTED_LINE_COUNT + EXPECTED_KOPTI_REGION_COUNT + EXPECTED_BARREL_REGION_COUNT,
            },
            "emitted_counts": {
                "LINE": len(lines),
                "FILL_KOPTi": region_roles["KOPTi_logo_fill"],
                "FILL_barrel_polarity": region_roles["barrel_polarity_fill"],
                "FILL_total": len(regions),
                "primitive_total": len(primitive_manifest),
            },
            "source_to_output_complete": len(primitive_manifest) == (
                EXPECTED_LINE_COUNT + EXPECTED_KOPTI_REGION_COUNT + EXPECTED_BARREL_REGION_COUNT
            ),
            "all_source_objects_dark": True,
            "all_fill_paths_single_contour": True,
            "all_fill_paths_clockwise_y_up": True,
            "line_geometry_sha256": line_hash,
            "fill_paths_sha256": fill_hash,
            "max_fill_area_relative_error_after_transform": max(area_relative_errors, default=0.0),
        },
        "primitive_map": primitive_manifest,
        "merge_contract": {
            "scope": "Merge the 504 LINE/FILL primitives only into the final native PCB.",
            "do_not_duplicate": "Do not merge this document scaffold or duplicate per-component silkscreen.",
            "manufacturing_gate": (
                "Final board still requires complete component placement, mask/paste recovery, "
                "native netlist comparison and DRC before fabrication."
            ),
        },
    }
    return source, manifest


def parse_native_source(source: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.endswith("|") or "||" not in line:
            raise ValueError(f"invalid native record framing at line {line_number}")
        header_text, body_text = line[:-1].split("||", 1)
        records.append((json.loads(header_text), json.loads(body_text)))
    return records


def validate_serialized_source(source: str, manifest: dict[str, Any]) -> dict[str, Any]:
    records = parse_native_source(source)
    counts = Counter(header.get("type") for header, _ in records)
    expected_counts = Counter({
        "DOCHEAD": 1,
        "META": 1,
        "LAYER": 1,
        "CANVAS": 1,
        "ACTIVE_LAYER": 1,
        "PREFERENCE": 1,
        "LINE": EXPECTED_LINE_COUNT,
        "FILL": EXPECTED_KOPTI_REGION_COUNT + EXPECTED_BARREL_REGION_COUNT,
    })
    if counts != expected_counts:
        raise ValueError(f"serialized native record counts mismatch: {counts!r}")
    primitives = [
        (header, body) for header, body in records if header.get("type") in {"LINE", "FILL"}
    ]
    ids = [str(header.get("id") or "") for header, _ in primitives]
    if len(set(ids)) != len(ids) or any(re.fullmatch(r"[0-9a-f]{16}", value) is None for value in ids):
        raise ValueError("native primitive IDs are not unique current 16-lowercase-hex IDs")
    if any(body.get("groupId") != 0 or body.get("layerId") != FRONT_SILK_LAYER_ID for _, body in primitives):
        raise ValueError("native global silkscreen primitive lost groupId=0 or layerId=3")
    if any(body.get("netName") != "" or body.get("locked") is not False for _, body in primitives):
        raise ValueError("native global silkscreen primitive has unexpected electrical/lock state")
    fills = [body for header, body in primitives if header["type"] == "FILL"]
    if any(body.get("fillStyle") != "SOLID" or len(body.get("path") or []) != 1 for body in fills):
        raise ValueError("native global silkscreen FILL is not a single SOLID outline")
    fill_hash = sha256_bytes(compact([body["path"] for body in fills]).encode("utf-8"))
    lines = [body for header, body in primitives if header["type"] == "LINE"]
    line_geometry = [
        {
            "start": [body["startX"], body["startY"]],
            "end": [body["endX"], body["endY"]],
            "width": body["width"],
        }
        for body in lines
    ]
    line_hash = sha256_bytes(compact(line_geometry).encode("utf-8"))
    expected_geometry = manifest["geometry"]
    if fill_hash != expected_geometry["fill_paths_sha256"]:
        raise ValueError("serialized global FILL paths differ from transformed source")
    if line_hash != expected_geometry["line_geometry_sha256"]:
        raise ValueError("serialized global LINE geometry differs from transformed source")
    return {
        "status": "complete",
        "record_count": len(records),
        "record_counts": dict(sorted(counts.items())),
        "primitive_count": len(primitives),
        "unique_current_16_hex_primitive_ids": len(set(ids)),
        "group_id_zero_count": sum(body.get("groupId") == 0 for _, body in primitives),
        "layer_3_primitive_count": sum(body.get("layerId") == 3 for _, body in primitives),
        "line_geometry_sha256": line_hash,
        "fill_paths_sha256": fill_hash,
        "missing_source_objects": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=DEFAULT_GEOMETRY)
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    geometry, lines, regions, source_audit = load_global_geometry(args.geometry, args.gerber)
    source, manifest = build_source(geometry, lines, regions, source_audit)
    manifest["native_source_validation"] = validate_serialized_source(source, manifest)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8", newline="\n")
    output_bytes = args.output.read_bytes()
    manifest["output"] = {
        "path": str(args.output.relative_to(ROOT)),
        "sha256": sha256_bytes(output_bytes),
        "bytes": len(output_bytes),
    }
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote {args.output}")
    print(f"Wrote {args.manifest}")
    print(json.dumps({
        "status": manifest["status"],
        "source": manifest["source"],
        "geometry": manifest["geometry"],
        "native_source_validation": manifest["native_source_validation"],
        "output": manifest["output"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
