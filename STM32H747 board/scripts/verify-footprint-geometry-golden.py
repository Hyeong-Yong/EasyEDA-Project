"""Verify Gerber-derived native footprint geometry against strict golden data.

This checker is deliberately independent from ``build-native-libraries.py``.
It reads the archived-Gerber extraction and the emitted native ``.efoo`` files,
then verifies the two aperture families that cannot be represented by the old
generic rectangle fallback:

* 115 RoundRect pads, including their true bbox, corner radius and area;
* 8 USB-C Outline5P pads, including macro rotation, polygon vertices, winding,
  area and the PCB-domain Y-up coordinate transform.
* 13 plated routed slots, including drill width/height, orientation, layer and
  the copper capsule that surrounds each routed hole.

It also records and checks the J1 mask/paste exceptions.  Those exceptions are
important because null PAD expansions delegate the result to user design rules
and therefore cannot prove equality with the supplied manufacturing artwork.
Use ``--report-only`` to emit the full diagnostic JSON without returning a
failure exit status while the native generator is being repaired.
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
DEFAULT_GERBER = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
DEFAULT_LIBRARY = ROOT / "output" / "native-libraries" / "manifest.json"
DEFAULT_FOOTPRINTS = ROOT / "output" / "native-libraries" / "footprints"
DEFAULT_OUTPUT = ROOT / "output" / "validation" / "footprint-geometry-golden.json"
MM_TO_MIL = 1000.0 / 25.4
TOLERANCE_MIL = 0.00002


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number: {value!r}")
    return result


def rounded(value: Any, digits: int = 6) -> int | float:
    result = round(number(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def natural_key(value: Any) -> list[Any]:
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value))]


def close(left: Any, right: Any, tolerance: float = TOLERANCE_MIL) -> bool:
    return abs(number(left) - number(right)) <= tolerance


def point_close(left: Sequence[Any], right: Sequence[Any], tolerance: float = TOLERANCE_MIL) -> bool:
    return len(left) >= 2 and len(right) >= 2 and close(left[0], right[0], tolerance) and close(left[1], right[1], tolerance)


def signed_area(points: Sequence[Sequence[Any]]) -> float:
    return 0.5 * sum(
        number(points[index][0]) * number(points[(index + 1) % len(points)][1])
        - number(points[(index + 1) % len(points)][0]) * number(points[index][1])
        for index in range(len(points))
    )


def rotate(point: Sequence[Any], angle_deg: Any) -> tuple[float, float]:
    angle = math.radians(number(angle_deg))
    cosine, sine = math.cos(angle), math.sin(angle)
    x, y = number(point[0]), number(point[1])
    return x * cosine - y * sine, x * sine + y * cosine


def local_mil(point_mm: Sequence[Any], anchor_mm: Sequence[Any]) -> tuple[int | float, int | float]:
    """Gerber and EasyEDA PCB are both Y-up; no sign inversion is allowed."""

    return (
        rounded((number(point_mm[0]) - number(anchor_mm[0])) * MM_TO_MIL),
        rounded((number(point_mm[1]) - number(anchor_mm[1])) * MM_TO_MIL),
    )


def native_records(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw:
            continue
        try:
            header_text, body_text = raw.split("||", 1)
            if not body_text.endswith("|"):
                raise ValueError("missing record terminator")
            records.append((json.loads(header_text), json.loads(body_text[:-1])))
        except Exception as exc:  # pragma: no cover - diagnostic context
            raise ValueError(f"Invalid native record {path}:{line_number}: {exc}") from exc
    return records


def footprint_source(footprints_dir: Path, uuid: str) -> Path:
    matches = sorted(footprints_dir.glob(f"*_{uuid}.efoo"))
    if len(matches) != 1:
        raise ValueError(f"Expected one footprint source for UUID {uuid}, found {matches}")
    return matches[0]


def preferred_flash(pad: dict[str, Any], side: str) -> dict[str, Any] | None:
    flashes = [item for item in pad.get("flashes", []) if item.get("layer") in ("F.Cu", "B.Cu")]
    preferred = "B.Cu" if side.upper().startswith("B") else "F.Cu"
    return next((item for item in flashes if item.get("layer") == preferred), flashes[0] if flashes else None)


def line_polygon(path: Any) -> list[tuple[float, float]] | None:
    if not isinstance(path, list) or len(path) < 5 or path[2] != "L":
        return None
    points = [(number(path[0]), number(path[1]))]
    command: str | None = None
    index = 2
    while index < len(path):
        if isinstance(path[index], str):
            command = path[index]
            index += 1
            continue
        if command != "L" or index + 1 >= len(path) or isinstance(path[index + 1], str):
            return None
        points.append((number(path[index]), number(path[index + 1])))
        index += 2
    if len(points) > 1 and point_close(points[0], points[-1]):
        points.pop()
    return points


def polygons_match(expected: Sequence[Sequence[Any]], actual: Sequence[Sequence[Any]]) -> bool:
    if len(expected) != len(actual):
        return False
    count = len(expected)
    return any(
        all(point_close(expected[index], actual[(index + offset) % count]) for index in range(count))
        for offset in range(count)
    )


def actual_pads(
    library: dict[str, Any], footprints_dir: Path, reference: str
) -> tuple[Path, list[dict[str, Any]]]:
    info = library["footprints"][reference]
    path = footprint_source(footprints_dir, str(info["uuid"]))
    pads = [body for header, body in native_records(path) if header.get("type") == "PAD"]
    return path, pads


def aperture(
    gerber: dict[str, Any], flash: dict[str, Any]
) -> dict[str, Any]:
    layer, code = str(flash["layer"]), str(flash["aperture"])
    result = gerber["aperturesByLayer"][layer][code]
    if result.get("template") != flash.get("shape") or result.get("paramsMm") != flash.get("paramsMm"):
        raise ValueError(f"Aperture/flash disagreement on {layer} {code}: {result!r} != {flash!r}")
    return result


def actual_polygon_vertices(body: dict[str, Any]) -> list[tuple[float, float]] | None:
    definition = body.get("defaultPad") or {}
    # EasyEDA Pro 3.2 consumes polygon-pad paths in footprint coordinates; it
    # does not apply PAD center/rotation as it does for parametric pad shapes.
    return line_polygon(definition.get("path"))


def verify_problem_pads(
    gerber: dict[str, Any], library: dict[str, Any], footprints_dir: Path
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    owners: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    source_cache: dict[str, tuple[Path, dict[str, dict[str, Any]]]] = {}

    for reference, component in sorted(gerber["components"].items(), key=lambda item: natural_key(item[0])):
        if not component.get("presentInLatest") or reference not in library.get("footprints", {}):
            continue
        side = str(component.get("sideHint") or "F")
        anchor = component["estimatedAnchorMm"]
        for pad_number, pad in sorted(component.get("pads", {}).items(), key=lambda item: natural_key(item[0])):
            flash = preferred_flash(pad, side)
            if not flash or flash.get("shape") not in ("RoundRect", "Outline5P"):
                continue
            if reference not in source_cache:
                path, pads = actual_pads(library, footprints_dir, reference)
                numbered = {str(item.get("num")): item for item in pads if str(item.get("num"))}
                source_cache[reference] = path, numbered
            path, numbered = source_cache[reference]
            actual = numbered.get(str(pad_number))
            errors: list[str] = []
            if actual is None:
                errors.append("native PAD missing")
                actual = {}
            expected_center = local_mil(flash["atMm"], anchor)
            actual_center = [actual.get("centerX"), actual.get("centerY")]
            if None in actual_center or not point_close(expected_center, actual_center):
                errors.append(f"Y-up center mismatch: expected {expected_center}, got {actual_center}")

            source_aperture = aperture(gerber, flash)
            params = [number(item) for item in source_aperture["paramsMm"]]
            expected: dict[str, Any]
            actual_summary: dict[str, Any]
            definition = actual.get("defaultPad") or {}
            if flash["shape"] == "RoundRect":
                if len(params) != 10:
                    errors.append(f"RoundRect requires 10 macro parameters, got {len(params)}")
                half = [number(item) for item in source_aperture["halfExtentMm"]]
                width_mm, height_mm, radius_mm = 2 * half[0], 2 * half[1], params[0]
                expected_area_mm2 = width_mm * height_mm - (4.0 - math.pi) * radius_mm * radius_mm
                expected = {
                    "pad_type": "RECT",
                    "width_mm": rounded(width_mm),
                    "height_mm": rounded(height_mm),
                    "radius_mm": rounded(radius_mm),
                    "bbox_mil": [rounded(-half[0] * MM_TO_MIL), rounded(-half[1] * MM_TO_MIL),
                                 rounded(half[0] * MM_TO_MIL), rounded(half[1] * MM_TO_MIL)],
                    "area_mm2": rounded(expected_area_mm2, 9),
                }
                actual_summary = {
                    "pad_type": definition.get("padType"),
                    "width_mil": definition.get("width"),
                    "height_mil": definition.get("height"),
                    "radius_mil": definition.get("radius"),
                }
                expected_native = [width_mm * MM_TO_MIL, height_mm * MM_TO_MIL, radius_mm * MM_TO_MIL]
                actual_native = [definition.get("width"), definition.get("height"), definition.get("radius")]
                if definition.get("padType") != "RECT" or any(value is None for value in actual_native):
                    errors.append(f"expected rounded RECT, got {definition!r}")
                elif not all(close(want, got) for want, got in zip(expected_native, actual_native)):
                    errors.append(f"RoundRect bbox/radius mismatch: expected {expected_native}, got {actual_native}")
                else:
                    actual_area_mil2 = (
                        number(actual_native[0]) * number(actual_native[1])
                        - (4.0 - math.pi) * number(actual_native[2]) ** 2
                    )
                    if abs(actual_area_mil2 / (MM_TO_MIL * MM_TO_MIL) - expected_area_mm2) > 0.0000001:
                        errors.append("RoundRect area mismatch")
            else:
                if len(params) != 11:
                    errors.append(f"Outline5P requires 11 macro parameters, got {len(params)}")
                raw_points = [(params[index], params[index + 1]) for index in range(0, 10, 2)]
                rotated_mm = [rotate(point, params[10]) for point in raw_points]
                expected_points = [
                    (number(expected_center[0]) + x * MM_TO_MIL,
                     number(expected_center[1]) + y * MM_TO_MIL)
                    for x, y in rotated_mm
                ]
                expected_area_mm2 = signed_area(rotated_mm)
                if expected_area_mm2 >= 0:
                    errors.append(f"source Outline5P is not clockwise in Y-up space: area={expected_area_mm2}")
                actual_points = actual_polygon_vertices(actual)
                expected = {
                    "pad_type": "POLYGON",
                    "macro_rotation_ccw_deg": rounded(params[10]),
                    "vertices_mm_y_up": [[rounded(x, 9), rounded(y, 9)] for x, y in rotated_mm],
                    "absolute_vertices_mil_y_up": [[rounded(x), rounded(y)] for x, y in expected_points],
                    "signed_area_mm2": rounded(expected_area_mm2, 9),
                    "winding": "clockwise" if expected_area_mm2 < 0 else "counterclockwise",
                }
                actual_summary = {
                    "pad_type": definition.get("padType"),
                    "pad_angle_ccw_deg": actual.get("padAngle"),
                    "absolute_path_vertices_mil": (
                        [[rounded(x), rounded(y)] for x, y in actual_points]
                        if actual_points is not None else None
                    ),
                }
                if definition.get("padType") != "POLYGON" or actual_points is None:
                    errors.append(f"expected POLYGON, got {definition!r}")
                else:
                    area = signed_area(actual_points)
                    if area >= 0:
                        errors.append(f"native Outline5P is not clockwise in Y-up space: area={area}")
                    if not polygons_match(expected_points, actual_points):
                        errors.append("Outline5P rotated vertices do not match Gerber macro")
                    if abs(area / (MM_TO_MIL * MM_TO_MIL) - expected_area_mm2) > 0.0000001:
                        errors.append("Outline5P area mismatch")

            shape_counts[str(flash["shape"])] += 1
            owners[reference] += 1
            rows.append(
                {
                    "reference": reference,
                    "pad": str(pad_number),
                    "shape": flash["shape"],
                    "source_layer": flash["layer"],
                    "source_aperture": flash["aperture"],
                    "source_at_mm": flash["atMm"],
                    "expected_center_mil_y_up": list(expected_center),
                    "native_source": str(path.relative_to(ROOT)),
                    "expected": expected,
                    "actual": actual_summary,
                    "errors": errors,
                    "status": "pass" if not errors else "fail",
                }
            )

    failed = [item for item in rows if item["status"] != "pass"]
    structural_errors: list[str] = []
    if shape_counts != Counter({"RoundRect": 115, "Outline5P": 8}):
        structural_errors.append(f"expected RoundRect=115 and Outline5P=8, got {dict(shape_counts)}")
    if len(rows) != 123:
        structural_errors.append(f"expected 123 special pads, got {len(rows)}")
    return {
        "coordinate_contract": "x=(sourceX-anchorX)*39.37007874; y=(sourceY-anchorY)*39.37007874; PCB Y-up",
        "shape_counts": dict(sorted(shape_counts.items())),
        "owner_counts": dict(sorted(owners.items(), key=lambda item: natural_key(item[0]))),
        "total": len(rows),
        "passed": len(rows) - len(failed),
        "failed": len(failed),
        "structural_errors": structural_errors,
        "status": "pass" if not failed and not structural_errors else "fail",
        "pads": rows,
    }


def verify_plated_routed_slots(
    gerber: dict[str, Any], library: dict[str, Any], footprints_dir: Path
) -> dict[str, Any]:
    """Independently prove every routed PTH slot survives as a native SLOT.

    Excellon encodes these holes as G00/M15/G01/M16 routes rather than ordinary
    point hits.  The slot's overall length is the route centreline plus the tool
    diameter; EasyEDA Pro 3.2's native PAD schema stores that overall length in
    ``hole.width`` and the tool diameter in ``hole.height``.
    """

    expected_owners = {"CN1": {"1", "2", "3", "5", "6"}, "CN3": {"S1", "S2", "S3", "S4"},
                       "CN4": {"S1", "S2", "S3", "S4"}}
    rows: list[dict[str, Any]] = []
    observed_owners: dict[str, set[str]] = {}
    source_cache: dict[str, tuple[Path, dict[str, dict[str, Any]]]] = {}

    for reference, component in sorted(gerber["components"].items(), key=lambda item: natural_key(item[0])):
        if not component.get("presentInLatest") or reference not in library.get("footprints", {}):
            continue
        side = str(component.get("sideHint") or "F")
        anchor = component["estimatedAnchorMm"]
        for pad_number, pad in sorted(component.get("pads", {}).items(), key=lambda item: natural_key(item[0])):
            flash = preferred_flash(pad, side)
            slots = [hole for hole in (flash or {}).get("holes", []) if hole.get("kind") == "slot"]
            if not slots:
                continue
            errors: list[str] = []
            if len(slots) != 1:
                errors.append(f"expected one routed slot, got {len(slots)}")
            source = slots[0]
            observed_owners.setdefault(reference, set()).add(str(pad_number))

            if reference not in source_cache:
                native_path, pads = actual_pads(library, footprints_dir, reference)
                source_cache[reference] = native_path, {
                    str(item.get("num")): item for item in pads if str(item.get("num"))
                }
            native_path, numbered = source_cache[reference]
            actual = numbered.get(str(pad_number), {})
            if not actual:
                errors.append("native PAD missing")

            expected_center = local_mil(flash["atMm"], anchor)
            actual_center = [actual.get("centerX"), actual.get("centerY")]
            if None in actual_center or not point_close(expected_center, actual_center):
                errors.append(f"Y-up center mismatch: expected {expected_center}, got {actual_center}")

            expected_hole = {
                "holeType": "SLOT",
                "width": number(source["overallLengthMm"]) * MM_TO_MIL,
                "height": number(source["diameterMm"]) * MM_TO_MIL,
            }
            actual_hole = actual.get("hole") or {}
            if actual_hole.get("holeType") != "SLOT":
                errors.append(f"holeType must be SLOT, got {actual_hole.get('holeType')!r}")
            for key in ("width", "height"):
                if actual_hole.get(key) is None or not close(expected_hole[key], actual_hole[key]):
                    errors.append(
                        f"hole.{key} mismatch: expected {rounded(expected_hole[key])}, "
                        f"got {actual_hole.get(key)!r}"
                    )
            expected_angle = number(source["angleDeg"])
            if actual.get("relativeAngle") is None or not close(expected_angle, actual["relativeAngle"]):
                errors.append(
                    f"relativeAngle mismatch: expected {rounded(expected_angle)}, "
                    f"got {actual.get('relativeAngle')!r}"
                )
            if actual.get("layerId") != 12:
                errors.append(f"plated slot must be multilayer layerId=12, got {actual.get('layerId')!r}")
            if actual.get("plated") is not True:
                errors.append(f"plated slot must have plated=true, got {actual.get('plated')!r}")

            definition = actual.get("defaultPad") or {}
            params = [number(value) for value in flash.get("paramsMm", [])]
            expected_copper = {
                "padType": "RECT",
                "width": params[0] * MM_TO_MIL if len(params) >= 2 else None,
                "height": params[1] * MM_TO_MIL if len(params) >= 2 else None,
                "radius": 100,
            }
            if flash.get("shape") != "O" or len(params) < 2:
                errors.append(f"expected obround copper aperture, got {flash!r}")
            elif (
                definition.get("padType") != "RECT"
                or definition.get("radius") != 100
                or not close(expected_copper["width"], definition.get("width"))
                or not close(expected_copper["height"], definition.get("height"))
            ):
                errors.append(f"copper capsule mismatch: expected {expected_copper}, got {definition}")

            rows.append(
                {
                    "reference": reference,
                    "pad": str(pad_number),
                    "native_source": str(native_path.relative_to(ROOT)),
                    "source_flash_at_mm": flash["atMm"],
                    "source_route_start_mm": source["startMm"],
                    "source_route_end_mm": source["endMm"],
                    "source_tool": source["tool"],
                    "expected_center_mil_y_up": list(expected_center),
                    "expected_hole": {key: rounded(value) if key != "holeType" else value
                                      for key, value in expected_hole.items()},
                    "actual_hole": actual_hole,
                    "expected_relative_angle_deg": rounded(expected_angle),
                    "actual_relative_angle_deg": actual.get("relativeAngle"),
                    "expected_copper": {
                        key: rounded(value) if isinstance(value, (int, float)) else value
                        for key, value in expected_copper.items()
                    },
                    "actual_copper": definition,
                    "errors": errors,
                    "status": "pass" if not errors else "fail",
                }
            )

    structural_errors: list[str] = []
    if observed_owners != expected_owners:
        printable = {key: sorted(value, key=natural_key) for key, value in observed_owners.items()}
        expected_printable = {key: sorted(value, key=natural_key) for key, value in expected_owners.items()}
        structural_errors.append(f"expected routed-slot ownership {expected_printable}, got {printable}")
    if len(rows) != 13:
        structural_errors.append(f"expected 13 routed plated slots, got {len(rows)}")
    failed = [item for item in rows if item["status"] != "pass"]
    return {
        "schema_contract": {
            "hole": "{holeType:'SLOT', width:overallLengthMil, height:toolDiameterMil}",
            "angle": "relativeAngle is CCW degrees in PCB Y-up coordinates",
            "layer": "layerId=12 with plated=true",
        },
        "owner_counts": dict(Counter(item["reference"] for item in rows)),
        "total": len(rows),
        "passed": len(rows) - len(failed),
        "failed": len(failed),
        "structural_errors": structural_errors,
        "status": "pass" if not failed and not structural_errors else "fail",
        "pads": rows,
    }


def items_of_kind(component: dict[str, Any], layer: str, kind: str) -> list[dict[str, Any]]:
    return [item for item in component.get("layerGeometry", {}).get(layer, []) if item.get("kind") == kind]


def aperture_diameter(gerber: dict[str, Any], layer: str, code: str) -> float:
    source = gerber["aperturesByLayer"][layer][code]
    if source.get("template") != "C":
        raise ValueError(f"Expected circular aperture {layer}/{code}, got {source!r}")
    return number(source["paramsMm"][0])


def bbox_of_contour(contour: Sequence[dict[str, Any]]) -> list[float]:
    points: list[Sequence[Any]] = []
    for segment in contour:
        points.extend((segment["startMm"], segment["endMm"]))
    return [
        min(number(point[0]) for point in points),
        min(number(point[1]) for point in points),
        max(number(point[0]) for point in points),
        max(number(point[1]) for point in points),
    ]


def source_arc_angle(item: dict[str, Any]) -> float:
    start, end, centre = item["startMm"], item["endMm"], item["centerMm"]
    a = math.atan2(number(start[1]) - number(centre[1]), number(start[0]) - number(centre[0]))
    b = math.atan2(number(end[1]) - number(centre[1]), number(end[0]) - number(centre[0]))
    if item.get("clockwise"):
        return math.degrees(-((a - b) % (2 * math.pi)))
    return math.degrees((b - a) % (2 * math.pi))


def fill_polygon(body: dict[str, Any]) -> list[tuple[float, float]] | None:
    path = body.get("path")
    if not isinstance(path, list) or len(path) != 1:
        return None
    return line_polygon(path[0])


def source_npth(gerber: dict[str, Any], reference: str) -> list[dict[str, Any]]:
    result = []
    for drill_file in gerber.get("drills", []):
        for hole in drill_file.get("holes", []):
            if hole.get("componentRef") == reference and hole.get("ownership") == "componentMechanicalHole":
                result.append(hole)
    return sorted(result, key=lambda item: (number(item["atMm"][0]), number(item["atMm"][1])))


def exact_expansion(actual: Any, expected: float) -> bool:
    return actual is not None and close(actual, expected)


def verify_j1_mask_paste(
    gerber: dict[str, Any], library: dict[str, Any], footprints_dir: Path
) -> dict[str, Any]:
    reference = "J1"
    component = gerber["components"][reference]
    anchor = component["estimatedAnchorMm"]
    path, pads = actual_pads(library, footprints_dir, reference)
    records = native_records(path)
    numbered = {str(item.get("num")): item for item in pads if str(item.get("num"))}
    mechanical = [item for item in pads if not str(item.get("num"))]
    native_paste_lines = [
        body for header, body in records
        if header.get("type") == "LINE" and body.get("layerId") == 7
    ]
    native_paste_fills = [
        body for header, body in records
        if header.get("type") == "FILL" and body.get("layerId") == 7
    ]
    native_bottom_mask_arcs = [
        body for header, body in records
        if header.get("type") == "ARC" and body.get("layerId") == 6
    ]
    source_pads = component["pads"]

    line_items = items_of_kind(component, "F.Paste", "line")
    regions = items_of_kind(component, "F.Paste", "region")
    paste_flashes = items_of_kind(component, "F.Paste", "flash")
    fmask_flashes = items_of_kind(component, "F.Mask", "flash")
    bmask_flashes = items_of_kind(component, "B.Mask", "flash")
    bmask_arcs = items_of_kind(component, "B.Mask", "arc")
    structural_errors: list[str] = []
    expected_counts = {
        "F.Paste.flash": 14,
        "F.Paste.line": 40,
        "F.Paste.region": 10,
        "F.Mask.flash": 16,
        "B.Mask.flash": 2,
        "B.Mask.arc": 4,
    }
    actual_counts = {
        "F.Paste.flash": len(paste_flashes),
        "F.Paste.line": len(line_items),
        "F.Paste.region": len(regions),
        "F.Mask.flash": len(fmask_flashes),
        "B.Mask.flash": len(bmask_flashes),
        "B.Mask.arc": len(bmask_arcs),
    }
    if actual_counts != expected_counts:
        structural_errors.append(f"J1 source geometry counts changed: {actual_counts} != {expected_counts}")

    region_by_pad: dict[str, dict[str, Any]] = {}
    region_rows: list[dict[str, Any]] = []
    for region in regions:
        contours = region.get("contours") or []
        if len(contours) != 1 or len(contours[0]) != 4:
            structural_errors.append(f"unexpected J1 paste region topology: {region!r}")
            continue
        contour_bbox = bbox_of_contour(contours[0])
        stroke_diameter = aperture_diameter(gerber, "F.Paste", str(region["aperture"]))
        effective_bbox = [
            contour_bbox[0] - stroke_diameter / 2,
            contour_bbox[1] - stroke_diameter / 2,
            contour_bbox[2] + stroke_diameter / 2,
            contour_bbox[3] + stroke_diameter / 2,
        ]
        centre = [(contour_bbox[0] + contour_bbox[2]) / 2, (contour_bbox[1] + contour_bbox[3]) / 2]
        matches = []
        for pad_number, pad in source_pads.items():
            flash = preferred_flash(pad, "F")
            if flash and abs(number(flash["atMm"][0]) - centre[0]) <= 0.005 and abs(number(flash["atMm"][1]) - centre[1]) <= 0.005:
                matches.append(str(pad_number))
        if len(matches) != 1:
            structural_errors.append(f"paste region centre {centre} maps to pads {matches}")
            continue
        pad_number = matches[0]
        pad_flash = preferred_flash(source_pads[pad_number], "F")
        pad_at = [number(value) for value in pad_flash["atMm"]]
        copper_size = [number(value) for value in pad_flash["paramsMm"][:2]]
        copper_bbox = [
            pad_at[0] - copper_size[0] / 2,
            pad_at[1] - copper_size[1] / 2,
            pad_at[0] + copper_size[0] / 2,
            pad_at[1] + copper_size[1] / 2,
        ]
        symmetric_bbox = [
            copper_bbox[0] - stroke_diameter / 2,
            copper_bbox[1] - stroke_diameter / 2,
            copper_bbox[2] + stroke_diameter / 2,
            copper_bbox[3] + stroke_diameter / 2,
        ]
        bbox_delta = [effective_bbox[index] - symmetric_bbox[index] for index in range(4)]
        region_by_pad[pad_number] = {
            "contour_bbox_source_mm": [rounded(value, 9) for value in contour_bbox],
            "boundary_stroke_diameter_mm": rounded(stroke_diameter),
            "effective_union_bbox_source_mm": [rounded(value, 9) for value in effective_bbox],
            "paste_region_centre_offset_from_pad_mm": [
                rounded(centre[0] - pad_at[0], 9), rounded(centre[1] - pad_at[1], 9)
            ],
            "symmetric_pad_expansion_bbox_source_mm": [rounded(value, 9) for value in symmetric_bbox],
            "source_minus_symmetric_bbox_mm": [rounded(value, 9) for value in bbox_delta],
            "scalar_pad_expansion_exact": all(abs(value) <= 0.0000001 for value in bbox_delta),
            "effective_union_bbox_local_mil_y_up": [
                *local_mil(effective_bbox[:2], anchor),
                *local_mil(effective_bbox[2:], anchor),
            ],
        }
        region_rows.append({"pad": pad_number, **region_by_pad[pad_number]})

    expected_region_pads = {str(value) for value in range(5, 15)}
    if set(region_by_pad) != expected_region_pads:
        structural_errors.append(
            f"expected extra paste regions on J1 pads 5-14, got {sorted(region_by_pad, key=natural_key)}"
        )

    pad_rows: list[dict[str, Any]] = []
    for pad_number in sorted(source_pads, key=natural_key):
        source_flash = preferred_flash(source_pads[pad_number], "F")
        if source_flash is None:
            structural_errors.append(f"J1 pad {pad_number} has no F.Cu flash")
            continue
        copper_params = [number(item) for item in source_flash["paramsMm"]]
        if source_flash.get("shape") != "R" or len(copper_params) < 2:
            structural_errors.append(f"J1 pad {pad_number} copper is not rectangular: {source_flash!r}")
            continue
        at = source_flash["atMm"]
        matching_mask = [item for item in fmask_flashes if point_close(item.get("atMm", []), at, 0.00001)]
        matching_paste = [item for item in paste_flashes if point_close(item.get("atMm", []), at, 0.00001)]
        if len(matching_mask) != 1 or len(matching_paste) != 1:
            structural_errors.append(f"J1 pad {pad_number} mask/paste flash mapping failed")
            continue
        mask_ap = gerber["aperturesByLayer"]["F.Mask"][matching_mask[0]["aperture"]]
        paste_ap = gerber["aperturesByLayer"]["F.Paste"][matching_paste[0]["aperture"]]
        mask_size = [number(item) for item in mask_ap["paramsMm"][:2]]
        paste_size = [number(item) for item in paste_ap["paramsMm"][:2]]
        if any(abs(mask_size[index] - copper_params[index]) > 0.000001 for index in (0, 1)):
            structural_errors.append(f"J1 pad {pad_number} F.Mask flash differs from copper unexpectedly")
        if any(abs(paste_size[index] - copper_params[index]) > 0.000001 for index in (0, 1)):
            structural_errors.append(f"J1 pad {pad_number} F.Paste flash differs from copper unexpectedly")
        actual = numbered.get(str(pad_number), {})
        expected_mask_mil = 0.0
        # The pad-generated F.Paste flash equals copper.  Pads 5-14 also have
        # separately drawn regions whose centres are shifted by +/-0.003 mm,
        # so no scalar PAD expansion can reproduce them exactly.  Keep the
        # flash expansion at zero and require the explicit layer-7 primitives.
        expected_paste_mil = 0.0
        errors: list[str] = []
        if not exact_expansion(actual.get("topSolderExpansion"), expected_mask_mil):
            errors.append(f"topSolderExpansion must be explicit {rounded(expected_mask_mil)} mil")
        if not exact_expansion(actual.get("topPasteExpansion"), expected_paste_mil):
            errors.append(f"topPasteExpansion must be explicit {rounded(expected_paste_mil)} mil")
        pad_rows.append(
            {
                "pad": str(pad_number),
                "source_at_mm": at,
                "expected_local_center_mil_y_up": list(local_mil(at, anchor)),
                "copper_size_mm": [rounded(value) for value in copper_params[:2]],
                "mask_aperture_size_mm": [rounded(value) for value in mask_size],
                "paste_flash_size_mm": [rounded(value) for value in paste_size],
                "extra_paste_region": region_by_pad.get(str(pad_number)),
                "expected_expansions_mil": {
                    "topSolderExpansion": rounded(expected_mask_mil),
                    "topPasteExpansion": rounded(expected_paste_mil),
                },
                "actual_expansions_mil": {
                    "topSolderExpansion": actual.get("topSolderExpansion"),
                    "topPasteExpansion": actual.get("topPasteExpansion"),
                },
                "errors": errors,
                "status": "pass" if not errors else "fail",
            }
        )

    holes = source_npth(gerber, reference)
    if len(holes) != 2:
        structural_errors.append(f"expected two J1 mechanical NPTH holes, got {len(holes)}")
    mechanical_rows: list[dict[str, Any]] = []
    for hole in holes:
        at, diameter_mm = hole["atMm"], number(hole["diameterMm"])
        expected_center = local_mil(at, anchor)
        matches = [item for item in mechanical if point_close([item.get("centerX"), item.get("centerY")], expected_center)]
        if len(matches) != 1:
            structural_errors.append(f"J1 NPTH {at} maps to {len(matches)} native PADs")
            actual = {}
        else:
            actual = matches[0]
        top_matches = [item for item in fmask_flashes if point_close(item.get("atMm", []), at, 0.00001)]
        bottom_flashes = [item for item in bmask_flashes if point_close(item.get("atMm", []), at, 0.00001)]
        bottom_arcs = [item for item in bmask_arcs if point_close(item.get("centerMm", []), at, 0.00001)]
        if len(top_matches) != 1 or len(bottom_flashes) != 1 or len(bottom_arcs) != 2:
            structural_errors.append(f"J1 NPTH {at} mask geometry mapping failed")
            continue
        top_diameter = aperture_diameter(gerber, "F.Mask", str(top_matches[0]["aperture"]))
        bottom_flash_diameter = aperture_diameter(gerber, "B.Mask", str(bottom_flashes[0]["aperture"]))
        stroke = aperture_diameter(gerber, "B.Mask", str(bottom_arcs[0]["aperture"]))
        radius = math.dist(
            [number(value) for value in bottom_arcs[0]["startMm"]],
            [number(value) for value in bottom_arcs[0]["centerMm"]],
        )
        bottom_effective_diameter = 2 * (radius + stroke / 2)
        expected_top = (top_diameter - diameter_mm) / 2 * MM_TO_MIL
        # Preserve the 1.02 mm B.Mask flash through zero PAD expansion and the
        # four source arcs as explicit layer-6 primitives.  A +0.126 mm scalar
        # expansion happens to have the same outer bbox, but loses the actual
        # source construction and cannot be audited arc-for-arc.
        expected_bottom = (bottom_flash_diameter - diameter_mm) / 2 * MM_TO_MIL
        equivalent_scalar_bottom = (
            max(bottom_flash_diameter, bottom_effective_diameter) - diameter_mm
        ) / 2 * MM_TO_MIL
        errors: list[str] = []
        if not exact_expansion(actual.get("topSolderExpansion"), expected_top):
            errors.append(f"topSolderExpansion must be explicit {rounded(expected_top)} mil")
        if not exact_expansion(actual.get("bottomSolderExpansion"), expected_bottom):
            errors.append(f"bottomSolderExpansion must be explicit {rounded(expected_bottom)} mil")
        mechanical_rows.append(
            {
                "source_at_mm": at,
                "expected_local_center_mil_y_up": list(expected_center),
                "npth_diameter_mm": rounded(diameter_mm),
                "top_mask_flash_diameter_mm": rounded(top_diameter),
                "bottom_mask_flash_diameter_mm": rounded(bottom_flash_diameter),
                "bottom_mask_arc_records": bottom_arcs,
                "bottom_mask_arc_stroke_mm": rounded(stroke),
                "bottom_mask_arc_path_radius_mm": rounded(radius),
                "bottom_mask_effective_diameter_mm": rounded(bottom_effective_diameter),
                "equivalent_outer_bbox_bottom_expansion_mil": rounded(equivalent_scalar_bottom),
                "expected_expansions_mil": {
                    "topSolderExpansion": rounded(expected_top),
                    "bottomSolderExpansion": rounded(expected_bottom),
                },
                "actual_expansions_mil": {
                    "topSolderExpansion": actual.get("topSolderExpansion"),
                    "bottomSolderExpansion": actual.get("bottomSolderExpansion"),
                },
                "errors": errors,
                "status": "pass" if not errors else "fail",
            }
        )

    paste_line_rows: list[dict[str, Any]] = []
    unused_native_lines = set(range(len(native_paste_lines)))
    for source in line_items:
        expected_start = local_mil(source["startMm"], anchor)
        expected_end = local_mil(source["endMm"], anchor)
        width = aperture_diameter(gerber, "F.Paste", str(source["aperture"])) * MM_TO_MIL
        match_index = None
        for index in sorted(unused_native_lines):
            candidate = native_paste_lines[index]
            candidate_start = [candidate.get("startX"), candidate.get("startY")]
            candidate_end = [candidate.get("endX"), candidate.get("endY")]
            same = point_close(expected_start, candidate_start) and point_close(expected_end, candidate_end)
            reverse = point_close(expected_start, candidate_end) and point_close(expected_end, candidate_start)
            if (same or reverse) and close(width, candidate.get("width")):
                match_index = index
                break
        if match_index is not None:
            unused_native_lines.remove(match_index)
        paste_line_rows.append(
            {
                "source_start_mm": source["startMm"],
                "source_end_mm": source["endMm"],
                "expected_start_mil_y_up": list(expected_start),
                "expected_end_mil_y_up": list(expected_end),
                "expected_width_mil": rounded(width),
                "matched_native_index": match_index,
                "status": "pass" if match_index is not None else "fail",
            }
        )
    if unused_native_lines or any(item["status"] == "fail" for item in paste_line_rows):
        structural_errors.append(
            f"J1 F.Paste LINE mismatch: expected 40 exact, native={len(native_paste_lines)}, "
            f"missing={sum(item['status'] == 'fail' for item in paste_line_rows)}, "
            f"unexpected={len(unused_native_lines)}"
        )

    paste_fill_rows: list[dict[str, Any]] = []
    unused_native_fills = set(range(len(native_paste_fills)))
    for source in regions:
        contour = source["contours"][0]
        source_points = [contour[0]["startMm"], *[segment["endMm"] for segment in contour]]
        if point_close(source_points[0], source_points[-1], 0.000001):
            source_points.pop()
        expected_points = [local_mil(point, anchor) for point in source_points]
        if signed_area(expected_points) >= 0:
            structural_errors.append(f"J1 source F.Paste region is not clockwise Y-up: {source!r}")
        match_index = None
        for index in sorted(unused_native_fills):
            candidate_points = fill_polygon(native_paste_fills[index])
            if candidate_points is not None and signed_area(candidate_points) < 0 and polygons_match(expected_points, candidate_points):
                match_index = index
                break
        if match_index is not None:
            unused_native_fills.remove(match_index)
        paste_fill_rows.append(
            {
                "source_points_mm": source_points,
                "expected_points_mil_y_up": [list(point) for point in expected_points],
                "expected_signed_area_mil2": rounded(signed_area(expected_points)),
                "matched_native_index": match_index,
                "status": "pass" if match_index is not None else "fail",
            }
        )
    if unused_native_fills or any(item["status"] == "fail" for item in paste_fill_rows):
        structural_errors.append(
            f"J1 F.Paste FILL mismatch: expected 10 exact, native={len(native_paste_fills)}, "
            f"missing={sum(item['status'] == 'fail' for item in paste_fill_rows)}, "
            f"unexpected={len(unused_native_fills)}"
        )

    bottom_arc_rows: list[dict[str, Any]] = []
    unused_native_arcs = set(range(len(native_bottom_mask_arcs)))
    for source in bmask_arcs:
        expected_start = local_mil(source["startMm"], anchor)
        expected_end = local_mil(source["endMm"], anchor)
        expected_width = aperture_diameter(gerber, "B.Mask", str(source["aperture"])) * MM_TO_MIL
        expected_angle = source_arc_angle(source)
        match_index = None
        for index in sorted(unused_native_arcs):
            candidate = native_bottom_mask_arcs[index]
            if (
                point_close(expected_start, [candidate.get("startX"), candidate.get("startY")])
                and point_close(expected_end, [candidate.get("endX"), candidate.get("endY")])
                and close(expected_width, candidate.get("width"))
                and close(expected_angle, candidate.get("angle"))
            ):
                match_index = index
                break
        if match_index is not None:
            unused_native_arcs.remove(match_index)
        bottom_arc_rows.append(
            {
                "source_start_mm": source["startMm"],
                "source_end_mm": source["endMm"],
                "source_center_mm": source["centerMm"],
                "expected_start_mil_y_up": list(expected_start),
                "expected_end_mil_y_up": list(expected_end),
                "expected_width_mil": rounded(expected_width),
                "expected_angle_ccw_positive_deg": rounded(expected_angle),
                "matched_native_index": match_index,
                "status": "pass" if match_index is not None else "fail",
            }
        )
    if unused_native_arcs or any(item["status"] == "fail" for item in bottom_arc_rows):
        structural_errors.append(
            f"J1 B.Mask ARC mismatch: expected 4 exact, native={len(native_bottom_mask_arcs)}, "
            f"missing={sum(item['status'] == 'fail' for item in bottom_arc_rows)}, "
            f"unexpected={len(unused_native_arcs)}"
        )

    failed = [item for item in [*pad_rows, *mechanical_rows] if item["status"] != "pass"]
    explicit_failed = sum(
        item["status"] != "pass"
        for item in [*paste_line_rows, *paste_fill_rows, *bottom_arc_rows]
    )
    return {
        "native_source": str(path.relative_to(ROOT)),
        "source_geometry_counts": actual_counts,
        "expected_source_geometry_counts": expected_counts,
        "paste_regions": sorted(region_rows, key=lambda item: natural_key(item["pad"])),
        "numbered_pads": pad_rows,
        "mechanical_npth": mechanical_rows,
        "explicit_native_geometry": {
            "F.Paste.LINE": paste_line_rows,
            "F.Paste.FILL": paste_fill_rows,
            "B.Mask.ARC": bottom_arc_rows,
            "failed": explicit_failed,
        },
        "structural_errors": structural_errors,
        "checked": len(pad_rows) + len(mechanical_rows),
        "failed": len(failed),
        "status": "pass" if not failed and not structural_errors else "fail",
        "rule_note": "Zero PAD expansions preserve the Gerber flashes. J1's shifted paste regions and bottom-mask arcs must be explicit native layer geometry; null delegates to mutable design rules and is not exact evidence.",
    }


def layer_audit(gerber: dict[str, Any]) -> dict[str, Any]:
    current: Counter[str] = Counter()
    removed: Counter[str] = Counter()
    global_graphics: list[dict[str, Any]] = []
    for reference, component in gerber["components"].items():
        target = current if component.get("presentInLatest") else removed
        for layer, items in component.get("layerGeometry", {}).items():
            for item in items:
                target[f"{layer}.{item.get('kind')}"] += 1
        if reference.startswith("G") and not component.get("presentInLatest"):
            counts = Counter(
                f"{layer}.{item.get('kind')}"
                for layer, items in component.get("layerGeometry", {}).items()
                for item in items
            )
            global_graphics.append({"gerber_component_key": reference, "counts": dict(sorted(counts.items()))})
    u2_regions = items_of_kind(gerber["components"]["U2"], "F.SilkS", "region")
    return {
        "current_component_geometry": dict(sorted(current.items())),
        "removed_or_global_geometry": dict(sorted(removed.items())),
        "global_silkscreen": global_graphics,
        "u2_missing_filled_triangle_source_regions": u2_regions,
        "interpretation": {
            "global_graphics": "The archived PCB artwork is KOPTi plus a barrel-polarity mark; no TECHLABS/CO.,LTD geometry was identified.",
            "assembly_courtyard": "No assembly/Fab or courtyard Gerber was supplied, so those layers cannot be reconstructed from this source set.",
            "mask_paste": "Gerber contains explicit mask/paste apertures; null native PAD expansions do not prove equality.",
        },
    }


def build_report(
    gerber_path: Path,
    library_path: Path,
    footprints_dir: Path,
) -> dict[str, Any]:
    gerber = json.loads(gerber_path.read_text(encoding="utf-8"))
    library = json.loads(library_path.read_text(encoding="utf-8"))
    pad_geometry = verify_problem_pads(gerber, library, footprints_dir)
    plated_slots = verify_plated_routed_slots(gerber, library, footprints_dir)
    j1 = verify_j1_mask_paste(gerber, library, footprints_dir)
    status = "pass" if all(
        item["status"] == "pass" for item in (pad_geometry, plated_slots, j1)
    ) else "fail"
    return {
        "schema": "stm32h747-footprint-geometry-golden-v1",
        "purpose": "Independent exact-geometry check for Gerber-derived native EasyEDA footprints",
        "sources": {
            "gerber_component_footprints": {"path": str(gerber_path), "sha256": sha256_file(gerber_path)},
            "native_library_manifest": {"path": str(library_path), "sha256": sha256_file(library_path)},
            "native_footprints_directory": str(footprints_dir),
        },
        "pad_geometry": pad_geometry,
        "plated_routed_slots": plated_slots,
        "j1_mask_paste": j1,
        "layer_audit": layer_audit(gerber),
        "validation": {
            "status": status,
            "pad_geometry_status": pad_geometry["status"],
            "plated_routed_slots_status": plated_slots["status"],
            "j1_mask_paste_status": j1["status"],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--footprints", type=Path, default=DEFAULT_FOOTPRINTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-only", action="store_true", help="write diagnostics but do not fail the process")
    args = parser.parse_args()
    report = build_report(args.gerber, args.library, args.footprints)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    args.output.write_bytes(payload.encode("utf-8"))
    summary = {
        "output": str(args.output),
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "validation": report["validation"],
        "special_pad_counts": report["pad_geometry"]["shape_counts"],
        "special_pad_failed": report["pad_geometry"]["failed"],
        "plated_routed_slots": {
            "total": report["plated_routed_slots"]["total"],
            "failed": report["plated_routed_slots"]["failed"],
            "status": report["plated_routed_slots"]["status"],
        },
        "j1_failed": report["j1_mask_paste"]["failed"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if report["validation"]["status"] != "pass" and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
