#!/usr/bin/env python3
"""Build a native EasyEDA Pro PCB routing-reference document.

This is deliberately a *reference draft*, not a fabrication-ready PCB.  It
converts the archived 260616 Gerber copper geometry into editable EasyEDA Pro
3.2 primitives, applies only the explicit 260827 page-6 net merge evidence,
and inserts the ten explicitly requested capacitor-gap bridge hints.  The
authoritative components/pads still have to be created by schematic-to-PCB
import and the resulting design must pass netlist comparison and DRC.
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
DEFAULT_ROUTES = ROOT / "output" / "semantic" / "gerber-copper-routes.json"
DEFAULT_FOOTPRINTS = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
DEFAULT_REFERENCE_NETLIST = ROOT / "output" / "semantic" / "reference-netlist.json"
DEFAULT_STACKUP = (
    ROOT / "보드 자료" / "MCU_BOARD_v19_260616_Gerber" /
    "MCU_BOARD_v19_260616-job.gbrjob"
)
DEFAULT_GERBER_DIR = ROOT / "보드 자료" / "MCU_BOARD_v19_260616_Gerber"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "native-pcb"
EDITOR_VERSION = "3.2.206"
DEFAULT_UPDATE_TIME = 1791928414106
MM_TO_MIL = 39.37007874015748
LAYER_PHYS_MIL_DECIMALS = 4


COPPER_LAYERS = [
    ("F.Cu", 1, "TOP", "#FF0000", "#7F0000"),
    ("In1.Cu", 15, "SIGNAL", "#CC6600", "#663300"),
    ("In2.Cu", 16, "SIGNAL", "#00A000", "#005000"),
    ("In3.Cu", 17, "SIGNAL", "#00A0A0", "#005050"),
    ("In4.Cu", 18, "SIGNAL", "#A000A0", "#500050"),
    ("B.Cu", 2, "BOTTOM", "#0000FF", "#00007F"),
]
COPPER_LAYER_ID = {name: layer_id for name, layer_id, *_ in COPPER_LAYERS}
SUBSTRATE_IDS = [101, 102, 103, 104, 105]
AUXILIARY_LAYERS = [
    (11, "OUTLINE", "Board Outline Layer", "#FF00FF", "#7F007F"),
    (12, "MULTI", "Multi-Layer", "#C0C0C0", "#606060"),
]


def stable_id(kind: str, key: str) -> str:
    return hashlib.sha256(f"stm32h747-v19\0{kind}\0{key}".encode()).hexdigest()[:16]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def rounded(value: float, digits: int = 6) -> int | float:
    value = round(float(value), digits)
    if value == 0:
        return 0
    return int(value) if value.is_integer() else value


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class NativeDocument:
    """Minimal deterministic EasyEDA Pro 3.2 JSON-record writer."""

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
        # Newly written PCB primitives use the current 3.2 ordinary-element
        # shape: exactly 16 lower-case hexadecimal characters.  Keep IDs
        # deterministic for reproducible reconstruction artifacts.
        record_id = stable_id("element", f"{self.uuid}:{kind}:{self.element}")
        return self.add(kind, body, record_id)

    def source(self) -> str:
        return "".join(f"{compact(header)}||{compact(body)}|\n" for header, body in self.records)


def local_point(source_mm: Sequence[float], bounds: Sequence[float]) -> tuple[int | float, int | float]:
    min_x, min_y, _, _ = map(number, bounds)
    x = (number(source_mm[0]) - min_x) * MM_TO_MIL
    y = (number(source_mm[1]) - min_y) * MM_TO_MIL
    return rounded(x), rounded(y)


def mm_value(value: float) -> int | float:
    return rounded(number(value) * MM_TO_MIL)


def layer_phys_thickness(value_mm: float) -> int | float:
    """Encode LAYER_PHYS thickness in the mil unit proven by the 3.2 getter."""
    return rounded(number(value_mm) * MM_TO_MIL, LAYER_PHYS_MIL_DECIMALS)


def signed_area(points: Sequence[Sequence[float]]) -> float:
    if len(points) < 3:
        return 0.0
    return 0.5 * sum(
        number(points[index][0]) * number(points[(index + 1) % len(points)][1])
        - number(points[(index + 1) % len(points)][0]) * number(points[index][1])
        for index in range(len(points))
    )


def line_path_points(path: Sequence[Any]) -> list[tuple[float, float]] | None:
    """Decode the straight-line TPcbSinglePolygon form used by this builder."""
    if len(path) < 3 or not isinstance(path[0], (int, float)) or path[2] != "L":
        return None
    values = path[3:]
    if len(values) % 2:
        raise ValueError(f"invalid native line polygon path: {path!r}")
    return [(number(path[0]), number(path[1]))] + [
        (number(values[index]), number(values[index + 1]))
        for index in range(0, len(values), 2)
    ]


def source_arc_angle_deg(item: dict[str, Any]) -> int | float:
    """Return the Gerber Y-up sweep unchanged for EasyEDA PCB's Y-up space."""
    start, end, center = item["startMm"], item["endMm"], item["centerMm"]
    a = math.atan2(number(start[1]) - number(center[1]), number(start[0]) - number(center[0]))
    b = math.atan2(number(end[1]) - number(center[1]), number(end[0]) - number(center[0]))
    if item.get("clockwise"):
        sweep = -((a - b) % (2 * math.pi))
    else:
        sweep = (b - a) % (2 * math.pi)
    angle = rounded(math.degrees(sweep))
    if (item.get("clockwise") and number(angle) >= 0) or (
        not item.get("clockwise") and number(angle) <= 0
    ):
        raise ValueError(f"Gerber arc sweep direction was lost: {item!r}")
    return angle


def layer_body(layer_type: str, name: str, active: str, inactive: str, show: bool = True) -> dict[str, Any]:
    return {
        "layerType": layer_type,
        "layerName": name,
        "use": True,
        "show": show,
        "locked": False,
        "activeColor": active,
        "activateTransparency": 1,
        "inactiveColor": inactive,
        "inactiveTransparency": 1,
    }


def load_stackup(
    path: Path,
) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    job = json.loads(path.read_text(encoding="utf-8"))
    material_stack = job.get("MaterialStackup") or []
    copper = {
        str(item.get("Name")): number(item.get("Thickness"))
        for item in material_stack if item.get("Type") == "Copper"
    }
    expected_names = [name for name, *_ in COPPER_LAYERS]
    if list(copper) != expected_names:
        raise ValueError(f"Gerber job copper stack is not the expected six layers: {list(copper)}")
    dielectrics = [item for item in material_stack if item.get("Type") == "Dielectric"]
    if len(dielectrics) != 5:
        raise ValueError(f"Gerber job needs five dielectric layers, found {len(dielectrics)}")
    for item in dielectrics:
        if number(item.get("Thickness")) <= 0:
            raise ValueError(f"invalid dielectric thickness: {item!r}")
        if not str(item.get("Material") or "").strip():
            raise ValueError(f"Gerber job dielectric has no explicit material: {item!r}")
    solder_masks = [item for item in material_stack if item.get("Type") == "SolderMask"]
    if [str(item.get("Name")) for item in solder_masks] != [
        "Top Solder Mask", "Bottom Solder Mask"
    ]:
        raise ValueError(f"Gerber job does not have the expected two solder masks: {solder_masks!r}")
    if [number(item.get("Thickness")) for item in solder_masks] != [0.02, 0.02]:
        raise ValueError(f"Gerber job solder-mask thickness is not explicitly 0.02 mm each: {solder_masks!r}")
    declared = number((job.get("GeneralSpecs") or {}).get("BoardThickness"))
    conductor_dielectric = sum(copper.values()) + sum(number(item.get("Thickness")) for item in dielectrics)
    mask_total = sum(number(item.get("Thickness")) for item in solder_masks)
    material_total = conductor_dielectric + mask_total
    if declared <= 0:
        raise ValueError("Gerber job has no positive GeneralSpecs.BoardThickness")
    if abs(material_total - declared) > 1e-9:
        raise ValueError(
            "Gerber job material stack does not reconcile with declared board thickness: "
            f"{material_total} != {declared}"
        )
    thickness_audit = {
        "declared_board_thickness_mm": rounded(declared, 6),
        "copper_and_dielectric_sum_mm": rounded(conductor_dielectric, 6),
        "solder_mask_sum_mm": rounded(mask_total, 6),
        "material_stack_total_including_mask_mm": rounded(material_total, 6),
        "native_layer_phys_sum_mm": rounded(material_total, 6),
        "interpretation": (
            "Gerber job explicitly declares Top/Bottom Solder Mask as 0.02 mm each; "
            "native LAYER_PHYS emits both masks plus six copper and five dielectric "
            "layers, totaling the declared 1.58 mm."
        ),
    }
    return copper, dielectrics, solder_masks, thickness_audit


def audit_gerber_polarity_files(routes: dict[str, Any], gerber_dir: Path) -> dict[str, Any]:
    """Verify exact copper inputs and reject unsupported negative Gerber polarity."""
    sources = {
        str(item.get("layer")): item
        for item in routes.get("source", {}).get("sourceFiles", [])
        if item.get("layer") in COPPER_LAYER_ID
    }
    files = []
    for layer_name, *_ in COPPER_LAYERS:
        source = sources.get(layer_name)
        if not source:
            raise ValueError(f"route manifest has no source file for {layer_name}")
        path = gerber_dir / str(source.get("file") or "")
        if not path.is_file():
            raise ValueError(f"Gerber copper source is unavailable: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != source.get("sha256"):
            raise ValueError(f"Gerber copper source hash mismatch for {path.name}")
        text = path.read_text(encoding="utf-8", errors="replace")
        lpc_count = text.count("%LPC*%")
        lpd_count = text.count("%LPD*%")
        file_positive_count = text.count("%TF.FilePolarity,Positive*%")
        file_negative_count = text.count("%TF.FilePolarity,Negative*%")
        legacy_image_negative_count = text.count("%IPNEG*%")
        macro_bodies = re.findall(r"%AM[^*]+\*(.*?)\*%", text, flags=re.DOTALL)
        macro_primitives = [
            command.strip()
            for body in macro_bodies
            for command in body.replace("\r", "").replace("\n", "").split("*")
            if command.strip() and not command.lstrip().startswith("$")
        ]
        macro_clear_count = sum(
            re.match(r"^(?:1|2|4|5|20|21|22),0(?:,|$)", command) is not None
            for command in macro_primitives
        )
        macro_dark_count = sum(
            re.match(r"^(?:1|2|4|5|20|21|22),1(?:,|$)", command) is not None
            for command in macro_primitives
        )
        composite_clear_capable_count = sum(
            re.match(r"^(?:6|7),", command) is not None
            for command in macro_primitives
        )
        standard_hole_count = 0
        for match in re.finditer(r"%ADD\d+(C|R|O|P),([^*]+)\*%", text):
            shape, raw_parameters = match.groups()
            parameter_count = len(raw_parameters.split("X"))
            # A standard C aperture has one base parameter, R/O have two.
            # Any remaining modifier is an aperture hole.  Polygon apertures
            # are not used by this source and remain unsupported here because
            # their optional rotation/hole positions are ambiguous by count.
            if (shape == "C" and parameter_count > 1) or (
                shape in {"R", "O"} and parameter_count > 2
            ):
                standard_hole_count += 1
            if shape == "P":
                raise ValueError(
                    f"{path.name} uses a standard polygon aperture; audit its optional "
                    "rotation/hole modifiers before native FILL conversion"
                )
        if lpc_count:
            raise ValueError(
                f"{path.name} contains {lpc_count} LPC negative-polarity directive(s); "
                "FILL cannot safely reproduce subtractive copper without boolean decomposition"
            )
        if file_negative_count or legacy_image_negative_count or file_positive_count != 1:
            raise ValueError(
                f"{path.name} does not declare one unambiguous positive image "
                f"(X2 positive={file_positive_count}, X2 negative={file_negative_count}, "
                f"legacy IPNEG={legacy_image_negative_count})"
            )
        if macro_clear_count or composite_clear_capable_count or standard_hole_count:
            raise ValueError(
                f"{path.name} contains subtractive/aperture-hole geometry "
                f"(macro clear={macro_clear_count}, composite macro={composite_clear_capable_count}, "
                f"standard holes={standard_hole_count}); boolean decomposition is required"
            )
        if lpd_count != 1:
            raise ValueError(f"{path.name} expected one initial LPD directive, found {lpd_count}")
        files.append({
            "layer": layer_name,
            "file": path.name,
            "sha256": actual_hash,
            "lpd_directives": lpd_count,
            "lpc_directives": lpc_count,
            "file_polarity_positive_attributes": file_positive_count,
            "file_polarity_negative_attributes": file_negative_count,
            "legacy_negative_image_polarity_directives": legacy_image_negative_count,
            "aperture_macro_definitions": len(macro_bodies),
            "aperture_macro_dark_primitives": macro_dark_count,
            "aperture_macro_clear_primitives": macro_clear_count,
            "aperture_macro_composite_clear_capable_primitives": composite_clear_capable_count,
            "standard_aperture_hole_modifiers": standard_hole_count,
            "region_begin_directives": text.count("G36*"),
            "region_end_directives": text.count("G37*"),
        })
    macro_clear_total = sum(item["aperture_macro_clear_primitives"] for item in files)
    composite_total = sum(
        item["aperture_macro_composite_clear_capable_primitives"] for item in files
    )
    standard_hole_total = sum(item["standard_aperture_hole_modifiers"] for item in files)
    return {
        "status": "additive_only_no_clear_apertures_verified",
        "negative_lpc_directives": sum(item["lpc_directives"] for item in files),
        "negative_file_polarity_attributes": sum(
            item["file_polarity_negative_attributes"] for item in files
        ),
        "legacy_negative_image_polarity_directives": sum(
            item["legacy_negative_image_polarity_directives"] for item in files
        ),
        "aperture_macro_clear_primitives": macro_clear_total,
        "aperture_macro_composite_clear_capable_primitives": composite_total,
        "standard_aperture_hole_modifiers": standard_hole_total,
        "files": files,
    }


def add_stackup(
    doc: NativeDocument,
    copper_mm: dict[str, float],
    dielectrics: list[dict[str, Any]],
    solder_masks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit layer records in physical top-to-bottom order."""
    top_mask, bottom_mask = solder_masks
    doc.add(
        "LAYER",
        layer_body("TOP_SOLDER_MASK", str(top_mask["Name"]), "#800080", "#400040"),
        compact(["LAYER", 5]),
    )
    stack_manifest: list[dict[str, Any]] = [{
        "id": 5,
        "type": "SolderMask",
        "name": str(top_mask["Name"]),
        "thickness_mm": number(top_mask["Thickness"]),
    }]
    for index, (name, layer_id, layer_type, active, inactive) in enumerate(COPPER_LAYERS):
        doc.add("LAYER", layer_body(layer_type, name, active, inactive), compact(["LAYER", layer_id]))
        stack_manifest.append({
            "id": layer_id, "type": "Copper", "name": name,
            "thickness_mm": copper_mm[name],
        })
        if index < len(dielectrics):
            substrate_id = SUBSTRATE_IDS[index]
            item = dielectrics[index]
            substrate_name = str(item.get("Name") or f"Dielectric {index + 1}")
            doc.add("LAYER", layer_body("SUBSTRATE", substrate_name, "#999966", "#4C4C33", False),
                    compact(["LAYER", substrate_id]))
            stack_manifest.append({
                "id": substrate_id, "type": "Dielectric", "name": substrate_name,
                "material": item.get("Material"), "thickness_mm": number(item.get("Thickness")),
            })
    doc.add(
        "LAYER",
        layer_body("BOT_SOLDER_MASK", str(bottom_mask["Name"]), "#AA00FF", "#55007F"),
        compact(["LAYER", 6]),
    )
    stack_manifest.append({
        "id": 6,
        "type": "SolderMask",
        "name": str(bottom_mask["Name"]),
        "thickness_mm": number(bottom_mask["Thickness"]),
    })
    for layer_id, layer_type, name, active, inactive in AUXILIARY_LAYERS:
        doc.add("LAYER", layer_body(layer_type, name, active, inactive), compact(["LAYER", layer_id]))

    for z_index, item in enumerate(stack_manifest, 1):
        is_copper = item["type"] == "Copper"
        doc.add("LAYER_PHYS", {
            "material": (
                "COPPER" if is_copper
                else "SOLDER_MASK" if item["type"] == "SolderMask"
                else str(item["material"])
            ),
            "thickness": layer_phys_thickness(item["thickness_mm"]),
            # The Gerber Job explicitly supplies material and thickness only.
            # Null preserves "unknown" instead of asserting physically false
            # zero-valued dielectric properties.
            "permittivity": None,
            "lossTangent": None,
            "isKeepIsland": False,
            "zIndex": z_index,
        }, compact(["LAYER_PHYS", item["id"]]))
    return stack_manifest


def patch_map(routes: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    channels = routes.get("latestPatches", {}).get("page6BiasChannels", [])
    mapping: dict[str, str] = {}
    for channel in channels:
        latest = str(channel.get("latestNet") or "").strip()
        old_nets = [str(net).strip() for net in channel.get("oldNets", []) if str(net).strip()]
        if not latest or len(old_nets) != 2:
            raise ValueError(f"invalid page-6 bias-channel patch: {channel!r}")
        for old in old_nets:
            if old in mapping and mapping[old] != latest:
                raise ValueError(f"conflicting latest net patch for {old}")
            mapping[old] = latest
    if len(channels) != 10 or len(mapping) != 20:
        raise ValueError(f"expected 10 capacitor-gap channels / 20 old nets, got {len(channels)} / {len(mapping)}")
    return mapping, channels


def latest_net(old_net: Any, mapping: dict[str, str]) -> str:
    old = str(old_net or "").strip()
    return mapping.get(old, old)


def require_additive_polarity(item: dict[str, Any], label: str) -> None:
    polarity = item.get("polarity")
    if polarity != "dark":
        raise ValueError(
            f"{label} uses Gerber polarity {polarity!r}; subtractive copper must be "
            "boolean-decomposed before it can be represented as a native FILL/track"
        )


def polygon_path(points: Iterable[Sequence[float]], bounds: Sequence[float]) -> list[Any]:
    converted: list[tuple[int | float, int | float]] = []
    for point in points:
        value = local_point(point, bounds)
        if not converted or value != converted[-1]:
            converted.append(value)
    if len(converted) > 1 and converted[0] == converted[-1]:
        converted.pop()
    if len(converted) < 3:
        raise ValueError(f"polygon has fewer than three unique points: {converted!r}")
    area = signed_area(converted)
    if abs(area) <= 1e-12:
        raise ValueError("polygon has zero signed area")
    # EasyEDA's canonical TPcbSinglePolygon convention is clockwise for each
    # independent FILL outline.  PCB disk/API coordinates are Y-up, confirmed
    # by the two-pad runtime probe, so a clockwise outline has negative
    # shoelace area.  Retain the first vertex while reversing only when needed.
    if area > 0:
        converted = [converted[0], *reversed(converted[1:])]
    path: list[Any] = [converted[0][0], converted[0][1], "L"]
    for x, y in converted[1:]:
        path.extend((x, y))
    return path


def region_path(region: dict[str, Any], bounds: Sequence[float]) -> list[list[Any]]:
    result: list[list[Any]] = []
    for contour in region.get("contours", []):
        points: list[Sequence[float]] = []
        for index, segment in enumerate(contour):
            if segment.get("kind") != "line":
                raise ValueError(f"unexpected non-linear compact region segment: {segment!r}")
            if index == 0:
                points.append(segment["startMm"])
            points.append(segment["endMm"])
        result.append(polygon_path(points, bounds))
    if not result:
        raise ValueError("region has no contours")
    return result


def rounded_rectangle_points(cx: float, cy: float, width: float, height: float, radius: float,
                             rotation_deg: float = 0.0, steps: int = 8) -> list[tuple[float, float]]:
    radius = max(0.0, min(radius, width / 2, height / 2))
    corners = [
        (cx + width / 2 - radius, cy + height / 2 - radius, 0.0),
        (cx - width / 2 + radius, cy + height / 2 - radius, 90.0),
        (cx - width / 2 + radius, cy - height / 2 + radius, 180.0),
        (cx + width / 2 - radius, cy - height / 2 + radius, 270.0),
    ]
    points = []
    for corner_x, corner_y, start_deg in corners:
        for step in range(steps + 1):
            angle = math.radians(start_deg + 90.0 * step / steps)
            points.append((corner_x + radius * math.cos(angle), corner_y + radius * math.sin(angle)))
    if rotation_deg:
        angle = math.radians(rotation_deg)
        cosine, sine = math.cos(angle), math.sin(angle)
        points = [
            (cx + (x - cx) * cosine - (y - cy) * sine,
             cy + (x - cx) * sine + (y - cy) * cosine)
            for x, y in points
        ]
    return points


def capsule_points(cx: float, cy: float, width: float, height: float, steps: int = 16) -> list[tuple[float, float]]:
    if width >= height:
        radius = height / 2
        offset = (width - height) / 2
        result = []
        for index in range(steps + 1):
            angle = math.radians(-90 + 180 * index / steps)
            result.append((cx + offset + radius * math.cos(angle), cy + radius * math.sin(angle)))
        for index in range(steps + 1):
            angle = math.radians(90 + 180 * index / steps)
            result.append((cx - offset + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return result
    radius = width / 2
    offset = (height - width) / 2
    result = []
    for index in range(steps + 1):
        angle = math.radians(0 + 180 * index / steps)
        result.append((cx + radius * math.cos(angle), cy + offset + radius * math.sin(angle)))
    for index in range(steps + 1):
        angle = math.radians(180 + 180 * index / steps)
        result.append((cx + radius * math.cos(angle), cy - offset + radius * math.sin(angle)))
    return result


def flash_path(flash: dict[str, Any], bounds: Sequence[float]) -> list[list[Any]]:
    shape = flash.get("shape")
    params = [number(value) for value in flash.get("paramsMm", [])]
    cx, cy = map(number, flash["atMm"])
    if shape == "C" and params:
        x, y = local_point((cx, cy), bounds)
        # Current 3.2 TPcbSinglePolygon CIRCLE has exactly four entries; the
        # legacy fifth isCCW flag is no longer part of the native disk shape.
        return [["CIRCLE", x, y, mm_value(params[0] / 2)]]
    if shape == "R" and len(params) >= 2:
        width, height = params[:2]
        points = [
            (cx - width / 2, cy - height / 2), (cx + width / 2, cy - height / 2),
            (cx + width / 2, cy + height / 2), (cx - width / 2, cy + height / 2),
        ]
        return [polygon_path(points, bounds)]
    if shape == "O" and len(params) >= 2:
        return [polygon_path(capsule_points(cx, cy, params[0], params[1]), bounds)]
    if shape == "RoundRect" and len(params) >= 10:
        radius = abs(params[0])
        xs, ys = params[1:9:2], params[2:9:2]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        width, height = max_x - min_x + 2 * radius, max_y - min_y + 2 * radius
        local_cx, local_cy = (min_x + max_x) / 2, (min_y + max_y) / 2
        points = rounded_rectangle_points(cx + local_cx, cy + local_cy, width, height, radius, params[9])
        return [polygon_path(points, bounds)]
    raise ValueError(f"unsupported conductor flash {shape!r} params={params!r}")


def primitive_common(net: str, layer_id: int, z_index: int) -> dict[str, Any]:
    return {
        "partitionId": None,
        "groupId": 0,
        "locked": False,
        "zIndex": z_index,
        "netName": net,
        "layerId": layer_id,
    }


def validate_reference_inputs(routes: dict[str, Any], reference: dict[str, Any], mapping: dict[str, str]) -> set[str]:
    embedded = routes.get("source", {}).get("latestSchematicSemanticJoin", {})
    reference_source_hash = reference.get("source", {}).get("sha256")
    if embedded.get("sha256") != reference_source_hash:
        raise ValueError(
            "Gerber extraction is not joined to the semantic revision used by reference-netlist.json: "
            f"{embedded.get('sha256')} != {reference_source_hash}"
        )
    reference_nets = {str(pin["net"]) for pin in reference.get("pins", []) if pin.get("net")}
    route_nets: set[str] = set()
    for layer in routes["copper"]["layers"].values():
        for category in ("tracks", "regions", "conductorFlashes"):
            route_nets.update(latest_net(item.get("netOld"), mapping) for item in layer[category] if item.get("netOld"))
    route_nets.update(latest_net(item.get("netOld"), mapping) for item in routes["copper"]["vias"] if item.get("netOld"))
    route_nets.discard("")
    if route_nets != reference_nets:
        raise ValueError(
            "patched route net set does not exactly equal latest schematic net set: "
            f"route-only={sorted(route_nets - reference_nets)[:12]}, "
            f"schematic-only={sorted(reference_nets - route_nets)[:12]}"
        )
    return reference_nets


def build_document(routes: dict[str, Any], footprints: dict[str, Any], reference: dict[str, Any],
                   copper_mm: dict[str, float], dielectrics: list[dict[str, Any]],
                   solder_masks: list[dict[str, Any]],
                   thickness_audit: dict[str, Any],
                   raw_polarity_audit: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    bounds = routes["coordinateTransform"]["boardBoundsSourceMm"]
    if len(bounds) != 4:
        raise ValueError("board bounds are missing")
    lower_left = local_point((bounds[0], bounds[1]), bounds)
    upper_right = local_point((bounds[2], bounds[3]), bounds)
    expected_upper_right = (
        mm_value(number(bounds[2]) - number(bounds[0])),
        mm_value(number(bounds[3]) - number(bounds[1])),
    )
    if lower_left != (0, 0) or upper_right != expected_upper_right:
        raise ValueError(
            "Gerber-to-native Y-up corner transform failed: "
            f"lower-left={lower_left}, upper-right={upper_right}, expected={expected_upper_right}"
        )
    mapping, channels = patch_map(routes)
    reference_nets = validate_reference_inputs(routes, reference, mapping)
    document_uuid = stable_id("pcb", "gerber-routing-reference")
    doc = NativeDocument(document_uuid)
    stack_manifest = add_stackup(doc, copper_mm, dielectrics, solder_masks)
    doc.add("META", {
        "board": document_uuid,
        "parent": "",
        "title": "STM32H747_MCU_BOARD_v19 routing reference",
        "source": f"{document_uuid}|project",
        "zIndex": None,
    }, "META")
    doc.add("CANVAS", {
        "originX": 0, "originY": 0, "unit": "mm",
        "gridXSize": 10, "gridYSize": 10,
        # PCB CANVAS grid/snap fields remain in mil even when unit="mm";
        # only the alternate-snap fields follow the display unit.
        "snapXSize": 1, "snapYSize": 1,
        "altSnapXSize": 0.1, "altSnapYSize": 0.1,
        "gridType": "NONE", "multiGridType": "NONE", "multiGridRatio": 10,
        "highlightValue": 0.5, "layerBrightness": "NORMAL",
    }, "CANVAS")
    doc.add("ACTIVE_LAYER", {"layerId": 1}, "ACTIVE_LAYER")
    doc.add("PREFERENCE", {
        "startTrackWidthFollowLast": False, "lastTrackWidth": mm_value(0.2),
        "startViaSizeFollowLast": False, "lastViaInnerDiameter": mm_value(0.3),
        "lastViaDiameter": mm_value(0.6), "snap": True, "routingMode": "NONE",
        "routingCorner": "L45", "removeLoop": True, "rotatingObject": False,
        "trackFollow": False, "stretchTrackMinCorner": 1, "preferenceConfig": "project",
        "realTimeUpdateUnusedLayers": False, "unusedPadRange": "ALL",
        "pushVia": "OPTIMIZA_OPEN", "pathOptimization4BePushed": "NONE",
        "currentPathOptimization4BePushed": "OPTIMIZA_WEAK",
        "removeCircuitsContainingVias": True, "removeAntenna": True,
    }, "PREFERENCE")
    for net in sorted(reference_nets):
        doc.add("NET", {
            "netType": None, "specialColor": None, "retLine": True,
            "differentialName": None, "isPositiveNet": False, "equalLengthGroupName": None,
        }, compact(["NET", net]))

    counters: Counter[str] = Counter()
    patch_counts: Counter[str] = Counter()
    skipped: list[dict[str, Any]] = []
    expected_fill_paths: list[list[list[Any]]] = []
    region_area_relative_errors: list[float] = []
    polarity_object_counts: Counter[str] = Counter()
    multi_contour_regions = 0
    z_index = 0
    for layer_name, layer_data in routes["copper"]["layers"].items():
        layer_id = COPPER_LAYER_ID[layer_name]
        for source_index, item in enumerate(layer_data["tracks"]):
            require_additive_polarity(item, f"{layer_name} track {source_index}")
            polarity_object_counts["track.dark"] += 1
            old_net = str(item.get("netOld") or "")
            net = latest_net(old_net, mapping)
            if not net:
                if (item.get("kind") == "line" and
                        math.dist(item["startMm"], item["endMm"]) <= 1e-9):
                    skipped.append({"layer": layer_name, "category": "track", "index": source_index,
                                    "reason": "unattributed zero-length Gerber object"})
                    continue
                raise ValueError(f"attributed net missing for {layer_name} track {source_index}")
            z_index += 1
            common = primitive_common(net, layer_id, z_index)
            if item["kind"] == "line":
                start, end = local_point(item["startMm"], bounds), local_point(item["endMm"], bounds)
                primitive_id = doc.primitive("LINE", {
                    **common, "startX": start[0], "startY": start[1],
                    "endX": end[0], "endY": end[1], "width": mm_value(item["widthMm"]),
                })
                counters[f"track.LINE.{layer_name}"] += 1
            elif item["kind"] == "arc":
                start, end = local_point(item["startMm"], bounds), local_point(item["endMm"], bounds)
                primitive_id = doc.primitive("ARC", {
                    **common, "startX": start[0], "startY": start[1],
                    "endX": end[0], "endY": end[1], "angle": source_arc_angle_deg(item),
                    "width": mm_value(item["widthMm"]), "arcType": "DOT",
                })
                counters[f"track.ARC.{layer_name}"] += 1
            else:
                raise ValueError(f"unsupported track kind {item.get('kind')!r}")
            if old_net in mapping:
                patch_counts[f"renamed_track.{layer_name}"] += 1
                patch_counts[f"renamed_to.{net}"] += 1

        for source_index, item in enumerate(layer_data["regions"]):
            require_additive_polarity(item, f"{layer_name} region {source_index}")
            polarity_object_counts["region.dark"] += 1
            contour_count = len(item.get("contours", []))
            if contour_count != 1:
                multi_contour_regions += 1
                raise ValueError(
                    f"{layer_name} region {source_index} has {contour_count} contours; "
                    "native FILL treats subpaths as parallel outlines, not subtractive holes"
                )
            old_net = str(item.get("netOld") or "")
            net = latest_net(old_net, mapping)
            if not net:
                raise ValueError(f"attributed net missing for {layer_name} region {source_index}")
            fill_path = region_path(item, bounds)
            source_contour = item["contours"][0]
            source_points = [source_contour[0]["startMm"], *[segment["endMm"] for segment in source_contour]]
            expected_area = abs(signed_area(source_points)) * MM_TO_MIL * MM_TO_MIL
            native_points = line_path_points(fill_path[0])
            if native_points is None:
                raise ValueError(f"{layer_name} region {source_index} did not produce a line polygon")
            actual_area = abs(signed_area(native_points))
            if expected_area <= 0:
                raise ValueError(f"{layer_name} region {source_index} has zero source area")
            region_area_relative_errors.append(abs(actual_area - expected_area) / expected_area)
            z_index += 1
            doc.primitive("FILL", {
                **primitive_common(net, layer_id, z_index),
                "width": 0, "fillStyle": "SOLID", "path": fill_path,
                "isBridgingCopper": False, "networkList": [], "refs": [],
            })
            expected_fill_paths.append(fill_path)
            counters[f"region.FILL.{layer_name}"] += 1
            if old_net in mapping:
                patch_counts[f"renamed_region.{layer_name}"] += 1
                patch_counts[f"renamed_to.{net}"] += 1

        for source_index, item in enumerate(layer_data["conductorFlashes"]):
            require_additive_polarity(item, f"{layer_name} conductor flash {source_index}")
            polarity_object_counts["conductor_flash.dark"] += 1
            old_net = str(item.get("netOld") or "")
            net = latest_net(old_net, mapping)
            if not net:
                raise ValueError(f"attributed net missing for {layer_name} conductor flash {source_index}")
            fill_path = flash_path(item, bounds)
            z_index += 1
            doc.primitive("FILL", {
                **primitive_common(net, layer_id, z_index),
                "width": 0, "fillStyle": "SOLID", "path": fill_path,
                "isBridgingCopper": False, "networkList": [], "refs": [],
            })
            expected_fill_paths.append(fill_path)
            counters[f"flash.FILL.{layer_name}"] += 1
            if old_net in mapping:
                patch_counts[f"renamed_flash.{layer_name}"] += 1
                patch_counts[f"renamed_to.{net}"] += 1

    for index, item in enumerate(routes["copper"]["vias"]):
        old_net = str(item.get("netOld") or "")
        net = latest_net(old_net, mapping)
        if not net:
            raise ValueError(f"via {index} has no net")
        if len(item.get("layers", [])) != 6 or len(item.get("holes", [])) != 1:
            raise ValueError(f"via {index} does not have one drill and all six copper flashes")
        center = local_point(item["atMm"], bounds)
        hole = item["holes"][0]
        pad_diameters = [number(layer.get("diameterMm")) for layer in item["layers"]]
        z_index += 1
        doc.primitive("VIA", {
            "partitionId": None, "groupId": 0, "locked": False, "zIndex": z_index,
            "netName": net, "ruleName": "", "centerX": center[0], "centerY": center[1],
            "holeDiameter": mm_value(hole["diameterMm"]),
            "viaDiameter": mm_value(max(pad_diameters)), "viaType": "NORMAL",
            "topSolderExpansion": None, "bottomSolderExpansion": None,
            "unusedInnerLayers": [], "propagationDelay": 0,
        })
        counters["via.VIA"] += 1
        if old_net in mapping:
            patch_counts["renamed_via"] += 1
            patch_counts[f"renamed_to.{net}"] += 1

    bridge_manifest = []
    for channel in channels:
        hint = channel.get("replacementCopperHint") or {}
        if hint.get("kind") != "line" or not hint.get("advisoryOnly"):
            raise ValueError(f"missing advisory bridge evidence for {channel.get('removedComponent')}")
        net = str(hint["netLatest"])
        if net != channel["latestNet"] or net not in reference_nets:
            raise ValueError(f"bridge net does not match latest schematic for {channel.get('removedComponent')}")
        start, end = local_point(hint["startMm"], bounds), local_point(hint["endMm"], bounds)
        z_index += 1
        primitive_id = doc.primitive("LINE", {
            **primitive_common(net, COPPER_LAYER_ID["F.Cu"], z_index),
            "startX": start[0], "startY": start[1], "endX": end[0], "endY": end[1],
            "width": mm_value(0.25),
        })
        counters["patch_bridge.LINE.F.Cu"] += 1
        patch_counts["added_bridge"] += 1
        bridge_manifest.append({
            "primitive_id": primitive_id,
            "removed_component": channel["removedComponent"],
            "net": net,
            "start_mm": hint["startMm"], "end_mm": hint["endMm"],
            "width_mm": 0.25,
            "status": "explicit_advisory_patch_requires_final_drc",
        })

    edge_apertures = footprints.get("aperturesByLayer", {}).get("Edge.Cuts", {})
    outline_ids = []
    for index, item in enumerate(routes["edgeCuts"]):
        if item.get("kind") != "line":
            raise ValueError(f"unsupported outline item {item!r}")
        aperture = edge_apertures.get(item.get("aperture"), {})
        params = aperture.get("paramsMm") or []
        if aperture.get("template") != "C" or not params:
            raise ValueError(f"outline aperture unavailable for item {index}: {item.get('aperture')}")
        start, end = local_point(item["startMm"], bounds), local_point(item["endMm"], bounds)
        z_index += 1
        outline_ids.append(doc.primitive("LINE", {
            **primitive_common("", 11, z_index),
            "startX": start[0], "startY": start[1], "endX": end[0], "endY": end[1],
            "width": mm_value(params[0]),
        }))
        counters["outline.LINE"] += 1

    source = doc.source()
    manifest = {
        "schema": "stm32h747-native-pcb-routing-reference-v1",
        "status": "editable_reference_draft_not_manufacturing_ready",
        "document_uuid": document_uuid,
        "editor_format": EDITOR_VERSION,
        "coordinate_transform": {
            "gerber_source": {
                "coordinate_system": routes["coordinateTransform"]["sourceCoordinateSystem"],
                "board_bounds_source_mm": bounds,
            },
            "native": "x=(sourceX-boardMinX)*39.37007874; y=(sourceY-boardMinY)*39.37007874",
            "native_axis_direction": "x-right, y-up",
            "runtime_evidence": (
                "output/validation/native-pcb-coordinate-probe.epru: API pads at y=100/200 "
                "round-trip to raw centerY=100/200, and y=200 renders above y=100"
            ),
            "input_preview_transform_ignored": (
                "The semantic input's toBoardLocalMm.yDown preview is not an EasyEDA PCB "
                "disk/API transform and must not be applied here."
            ),
            "corner_check_mil": {
                "source_min_xy_to_native": list(lower_left),
                "source_max_xy_to_native": list(upper_right),
            },
            "native_internal_units": "mil",
            "board_local_size_mm": [number(bounds[2]) - number(bounds[0]), number(bounds[3]) - number(bounds[1])],
        },
        "stackup": {
            "source": "archived 260616 Gerber job MaterialStackup",
            "layers_top_to_bottom": stack_manifest,
            "copper_layer_count": 6,
            "permittivity_and_loss_tangent": (
                "unspecified in Gerber Job; native values are null (unknown), not physical zero"
            ),
            "impedance_validation": (
                "not performed; dielectric constant and loss tangent are unavailable"
            ),
            "thickness_audit": thickness_audit,
        },
        "gerber_polarity_and_fill_audit": {
            "raw_files": raw_polarity_audit,
            "object_polarities": dict(sorted(polarity_object_counts.items())),
            "multi_contour_regions": multi_contour_regions,
            "native_fill_subpath_semantics": "parallel independent outlines; input contains no explicit hole contours",
            "expected_fill_count": len(expected_fill_paths),
            "expected_fill_path_sha256": hashlib.sha256(compact(expected_fill_paths).encode()).hexdigest(),
            "max_region_area_relative_error_after_transform": max(region_area_relative_errors, default=0.0),
        },
        "format_compatibility": {
            "group_id": {
                "emitted_for_ungrouped_primitives": 0,
                "runtime_type": "integer",
                "installed_schema_declared_type": "string",
                "scope": "PCB/FOOTPRINT TPcbBase.groupId only",
                "basis": (
                    "The installed EasyEDA 3.2 TPcbBase $comment explicitly states that "
                    "the writer emits numeric 0 for ungrouped primitives and that its "
                    "string schema is intentionally narrower than observed runtime data."
                ),
                "validator_policy": (
                    "Accept exact integer zero only at top-level $body.groupId in PCB or "
                    "FOOTPRINT records; no other type or enum exception is accepted."
                ),
            },
            "layer_phys_thickness": {
                "emitted_unit": "mil",
                "installed_schema_comment_claim": "disk value = internal mm * 10 (0.1 mm unit)",
                "runtime_probe_observation": (
                    "EasyEDA 3.2 getter emitted mask=0.394, copper=1.379, "
                    "dielectric=59.449, copper=1.378, mask=0.394; their sum is "
                    "62.994 mil (about 1.600 mm), proving the live disk unit is mil."
                ),
                "evidence": "output/validation/native-pcb-coordinate-probe.epru",
                "policy": (
                    "Runtime getter evidence overrides the contradictory installed-schema "
                    "unit comment; numeric schema type remains satisfied."
                ),
            },
        },
        "net_patch": {
            "source": "latestPatches.page6BiasChannels in gerber-copper-routes.json",
            "old_to_latest": dict(sorted(mapping.items())),
            "renamed_object_counts": dict(sorted(patch_counts.items())),
            "bridges": bridge_manifest,
        },
        "counts": dict(sorted(counters.items())),
        "skipped_source_objects": skipped,
        "outline_primitive_ids": outline_ids,
        "validation": {
            "route_net_set_equals_latest_reference_netlist": True,
            "latest_unique_net_count": len(reference_nets),
            "via_count_matches_source": counters["via.VIA"] == len(routes["copper"]["vias"]) == 634,
            "explicit_bridge_count": len(bridge_manifest),
            "outline_item_count": len(outline_ids),
            "physical_components_intentionally_absent": True,
            "gerber_negative_lpc_directives": raw_polarity_audit["negative_lpc_directives"],
            "gerber_negative_file_polarity_attributes": raw_polarity_audit[
                "negative_file_polarity_attributes"
            ],
            "gerber_legacy_negative_image_polarity_directives": raw_polarity_audit[
                "legacy_negative_image_polarity_directives"
            ],
            "gerber_aperture_macro_clear_primitives": raw_polarity_audit[
                "aperture_macro_clear_primitives"
            ],
            "gerber_aperture_macro_composite_clear_capable_primitives": raw_polarity_audit[
                "aperture_macro_composite_clear_capable_primitives"
            ],
            "gerber_standard_aperture_hole_modifiers": raw_polarity_audit[
                "standard_aperture_hole_modifiers"
            ],
            "all_route_objects_additive_dark": True,
            "multi_contour_regions": multi_contour_regions,
        },
        "release_gates": {
            "native_schema_validation": "pending",
            "schematic_to_pcb_netlist_match": "not_run_route_only",
            "pcb_drc": "not_run_route_only",
            "manufacturing_output_authorized": False,
        },
        "limitations": [
            "The archived Gerber is revision 260616; only explicit 260827 net changes in latestPatches are applied.",
            "The ten added F.Cu bridge lines are explicit reconstruction hints across removed capacitors, not released routing.",
            "Conductor flashes on inner layers are reference copper and may overlap pads after schematic-to-PCB import; deduplicate before release.",
            "No components or footprint pads are present in this route-only document.",
            "Run schematic-native netlist comparison, placement review, ERC and full PCB DRC before manufacturing output.",
        ],
        "native_record_counts": dict(Counter(header["type"] for header, _ in doc.records)),
    }
    return source, manifest


def validate_native_source(source: str, manifest: dict[str, Any], reference_nets: set[str]) -> dict[str, Any]:
    records = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if not line.endswith("|") or "||" not in line:
            raise ValueError(f"malformed native record at line {line_number}")
        header_text, body_text = line[:-1].split("||", 1)
        records.append((json.loads(header_text), json.loads(body_text)))
    primitive_types = {"LINE", "ARC", "FILL", "VIA"}
    primitive_records = [(header, body) for header, body in records if header["type"] in primitive_types]
    ids = [header.get("id") for header, _ in primitive_records]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("native primitive IDs are missing or duplicated")
    if any(re.fullmatch(r"[0-9a-f]{16}", str(record_id)) is None for record_id in ids):
        raise ValueError("new native PCB primitive IDs must use the current 16-hex shape")
    allowed_layer_ids = set(COPPER_LAYER_ID.values()) | {11}
    bad_layers = [body.get("layerId") for header, body in primitive_records
                  if header["type"] != "VIA" and body.get("layerId") not in allowed_layer_ids]
    if bad_layers:
        raise ValueError(f"native primitives reference unknown layers: {bad_layers[:12]}")
    used_nets = {str(body.get("netName")) for _, body in primitive_records if body.get("netName")}
    if used_nets != reference_nets:
        raise ValueError("native output net set differs from reference netlist")
    if any(value in used_nets for value in manifest["net_patch"]["old_to_latest"]):
        raise ValueError("obsolete page-6 split net remains in native output")
    counts = Counter(header["type"] for header, _ in records)
    if counts != Counter(manifest["native_record_counts"]):
        raise ValueError("native record reparse count differs from manifest")
    if counts["VIA"] != 634 or manifest["net_patch"]["renamed_object_counts"].get("added_bridge") != 10:
        raise ValueError("strict via or bridge count failed")
    fill_records = [body for header, body in records if header["type"] == "FILL"]
    fill_audit = manifest["gerber_polarity_and_fill_audit"]
    raw_fill_audit = fill_audit["raw_files"]
    subtractive_counts = {
        key: raw_fill_audit[key]
        for key in (
            "negative_lpc_directives",
            "negative_file_polarity_attributes",
            "legacy_negative_image_polarity_directives",
            "aperture_macro_clear_primitives",
            "aperture_macro_composite_clear_capable_primitives",
            "standard_aperture_hole_modifiers",
        )
    }
    if any(subtractive_counts.values()):
        raise ValueError(
            f"subtractive Gerber geometry cannot be emitted as independent native FILL: "
            f"{subtractive_counts}"
        )
    if len(fill_records) != fill_audit["expected_fill_count"]:
        raise ValueError("native FILL count differs from additive Gerber source")
    if any(body.get("fillStyle") != "SOLID" for body in fill_records):
        raise ValueError("native FILL uses a non-canonical or non-solid fillStyle")
    if any(len(body.get("path") or []) != 1 for body in fill_records):
        raise ValueError("native FILL must have exactly one independent outline for this additive-only source")
    actual_paths = [body["path"] for body in fill_records]
    actual_path_hash = hashlib.sha256(compact(actual_paths).encode()).hexdigest()
    if actual_path_hash != fill_audit["expected_fill_path_sha256"]:
        raise ValueError("native FILL paths differ from transformed Gerber paths")
    circle_count = 0
    clockwise_polygon_count = 0
    for body in fill_records:
        path = body["path"][0]
        if path and path[0] == "CIRCLE":
            if len(path) != 4 or number(path[3]) <= 0:
                raise ValueError(f"invalid current-format CIRCLE fill path: {path!r}")
            circle_count += 1
            continue
        points = line_path_points(path)
        if points is None or signed_area(points) >= 0:
            raise ValueError("native FILL polygon is not a canonical clockwise outline")
        clockwise_polygon_count += 1
    via_records = [body for header, body in records if header["type"] == "VIA"]
    if any(body.get("viaType") != "NORMAL" or body.get("propagationDelay") != 0 for body in via_records):
        raise ValueError("native VIA does not use current NORMAL/zero-delay fields")
    net_headers = [header for header, _ in records if header["type"] == "NET"]
    if any(not str(header.get("id", "")).startswith('["NET",') for header in net_headers):
        raise ValueError("native NET does not use keyed [NET,name] record id")
    layer_phys = [body for header, body in records if header["type"] == "LAYER_PHYS"]
    physical_sum_mil = sum(number(body.get("thickness")) for body in layer_phys)
    physical_sum_mm = physical_sum_mil / MM_TO_MIL
    expected_physical_sum = manifest["stackup"]["thickness_audit"]["native_layer_phys_sum_mm"]
    # Each encoded layer is independently rounded in the runtime's mil unit.
    # Bound the aggregate decode error by half an LSB per LAYER_PHYS record.
    physical_sum_tolerance_mm = (
        len(layer_phys) * 0.5 * 10 ** (-LAYER_PHYS_MIL_DECIMALS) / MM_TO_MIL
    ) + 1e-12
    if abs(physical_sum_mm - expected_physical_sum) > physical_sum_tolerance_mm:
        raise ValueError("native LAYER_PHYS thickness sum differs from Gerber copper/dielectric stack")
    return {
        "status": "complete",
        "record_count": len(records),
        "primitive_count": len(primitive_records),
        "record_counts": dict(sorted(counts.items())),
        "unique_primitive_ids": len(set(ids)),
        "current_16_hex_primitive_ids": len(ids),
        "native_coordinate_axis": "y-up",
        "unique_routed_nets": len(used_nets),
        "obsolete_patch_nets_remaining": 0,
        "fill_count": len(fill_records),
        "fill_path_sha256": actual_path_hash,
        "solid_fill_count": sum(body.get("fillStyle") == "SOLID" for body in fill_records),
        "circle_path_count": circle_count,
        "clockwise_polygon_path_count": clockwise_polygon_count,
        "gerber_subtractive_geometry_counts": subtractive_counts,
        "native_layer_phys_sum_mil": rounded(physical_sum_mil, LAYER_PHYS_MIL_DECIMALS),
        "native_layer_phys_sum_mm": rounded(physical_sum_mm, 6),
        "native_layer_phys_decode_tolerance_mm": rounded(physical_sum_tolerance_mm, 9),
        "documented_runtime_group_id_zero": all(
            body.get("groupId") == 0 for _, body in primitive_records
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument("--footprints", type=Path, default=DEFAULT_FOOTPRINTS)
    parser.add_argument("--reference-netlist", type=Path, default=DEFAULT_REFERENCE_NETLIST)
    parser.add_argument("--stackup", type=Path, default=DEFAULT_STACKUP)
    parser.add_argument("--gerber-dir", type=Path, default=DEFAULT_GERBER_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    routes = json.loads(args.routes.read_text(encoding="utf-8"))
    footprints = json.loads(args.footprints.read_text(encoding="utf-8"))
    reference = json.loads(args.reference_netlist.read_text(encoding="utf-8"))
    copper_mm, dielectrics, solder_masks, thickness_audit = load_stackup(args.stackup)
    raw_polarity_audit = audit_gerber_polarity_files(routes, args.gerber_dir)
    source, manifest = build_document(
        routes, footprints, reference, copper_mm, dielectrics, solder_masks,
        thickness_audit, raw_polarity_audit,
    )
    reference_nets = {str(pin["net"]) for pin in reference["pins"] if pin.get("net")}
    manifest["native_source_validation"] = validate_native_source(source, manifest, reference_nets)
    manifest["release_gates"]["builder_native_contracts"] = "pass"
    manifest["sources"] = {
        "gerber_copper_routes": {"path": str(args.routes.relative_to(ROOT)), "sha256": sha256_file(args.routes)},
        "gerber_component_footprints": {"path": str(args.footprints.relative_to(ROOT)), "sha256": sha256_file(args.footprints)},
        "reference_netlist": {"path": str(args.reference_netlist.relative_to(ROOT)), "sha256": sha256_file(args.reference_netlist)},
        "gerber_job_stackup": {"path": str(args.stackup.relative_to(ROOT)), "sha256": sha256_file(args.stackup)},
        "gerber_copper_directory": {
            "path": str(args.gerber_dir.relative_to(ROOT)),
            "polarity_audit": "see gerber_polarity_and_fill_audit.raw_files",
        },
    }

    output_dir = args.output_dir.resolve()
    allowed = (ROOT / "output").resolve()
    if output_dir != allowed and allowed not in output_dir.parents:
        raise ValueError(f"output directory must remain under {allowed}")
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "gerber-routing-reference.epru"
    manifest_path = output_dir / "gerber-routing-reference-manifest.json"
    source_path.write_text(source, encoding="utf-8")
    manifest["output"] = {
        "path": str(source_path.relative_to(ROOT)),
        "sha256": sha256_file(source_path),
        "bytes": source_path.stat().st_size,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {source_path}")
    print(f"Wrote {manifest_path}")
    print(json.dumps({
        "status": manifest["status"],
        "counts": manifest["counts"],
        "validation": manifest["validation"],
        "native_source_validation": manifest["native_source_validation"],
        "output": manifest["output"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
