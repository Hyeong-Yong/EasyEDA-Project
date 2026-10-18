#!/usr/bin/env python3
"""Build project-local EasyEDA Pro 3.2.206 library documents.

The inputs are evidence files produced by this repository's PDF and Gerber
extractors.  The output is deliberately a *project local* library bundle; the
script never talks to EasyEDA, never writes a personal/cloud library, and never
opens a document in the editor.

The Gerber is older than the authoritative schematic PDF.  Consequently the
generated footprints are reconstruction aids and the manifest always keeps the
project in a non-manufacturing-ready state until the normal schematic/PCB,
ERC/DRC and netlist checks have been completed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


FORMAT_NAME = "easyeda-pro-native-library"
FORMAT_VERSION = 1
EDITOR_VERSION = "3.2.206"
MM_TO_MIL = 39.37007874015748
PT_TO_EASYEDA = 100.0 / 72.0
# The installed renderer evaluates `strokeWidth || 1`, so zero/null creates a
# visible default outline.  A tiny positive width is the persistence-proven
# way to retain an electrically real PIN and a visually fill-only PDF path.
SYMBOL_VISUAL_EPSILON = 0.001
DEFAULT_UPDATE_TIME = 1791928414106
# EasyEDA stores imported library documents by UUID and version.  Keep UUIDs
# stable so schematic/device references remain deterministic, but make the
# version depend on the complete document content so a revised local import is
# never mistaken for the previously imported payload.  Increment this epoch
# whenever the versioning rule itself changes; each epoch occupies a disjoint
# numeric range and stays below JavaScript's MAX_SAFE_INTEGER.
NATIVE_CACHE_VERSION_EPOCH = 4
NATIVE_CACHE_VERSION_WIDTH = 1_000_000_000_000

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMATIC = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
DEFAULT_GERBER = ROOT / "output" / "semantic" / "gerber-component-footprints.json"
DEFAULT_OUTPUT = ROOT / "output" / "native-libraries"
DEFAULT_PDF = ROOT / "보드 자료" / "MCU_BOARD_v19_260827.pdf"
ALLOWED_OUTPUT_ROOT = (ROOT / "output").resolve()

# The exposed thermal pads on U5/U7 are compound plated pads in the archived
# manufacturing data: a large rectangular flash exists only on F.Cu, while a
# 0.6 mm circular GND annulus exists on B.Cu and every one of the four inner
# copper layers.  A plain multilayer defaultPad repeats the top rectangle on
# every layer, so preserve the top shape and use EasyEDA Pro's native
# top/inner/bottom specialPad contract for the lower layers.  The raw-object
# proof (including aperture indices and hashes) is emitted by
# prepare-u5-u7-special-pad-fix.py.
LAYERED_THERMAL_PAD_OVERRIDES: dict[tuple[str, str], dict[str, float]] = {
    ("U5", "25"): {"top_size_mm": 2.5, "annulus_diameter_mm": 0.6, "drill_diameter_mm": 0.3},
    ("U7", "33"): {"top_size_mm": 3.45, "annulus_diameter_mm": 0.6, "drill_diameter_mm": 0.3},
}

# The Gerber/Excellon X2 attributes associate four additional plated thermal
# drills with each exposed-pad number.  The footprint extractor originally
# collapsed these into the central pad because every drill carries the same
# component/pin attribution.  Preserve them as separate, component-owned PAD
# primitives with duplicate pad numbers; EasyEDA's PAD_NET identity includes
# the child primitive suffix, and its placed-footprint resolver intentionally
# supports several physical children for one logical pad number.
OWNED_THERMAL_PTH_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("U5", "25"): {
        "centers_mm": [
            [199.36, -182.16], [199.36, -180.76],
            [200.66, -182.16], [200.66, -180.76],
        ],
        "copper_diameter_mm": 0.6,
        "drill_diameter_mm": 0.3,
        "net": "GND",
    },
    ("U7", "33"): {
        "centers_mm": [
            [223.06, -153.335], [223.06, -151.235],
            [225.16, -153.335], [225.16, -151.235],
        ],
        "copper_diameter_mm": 0.6,
        "drill_diameter_mm": 0.3,
        "net": "GND",
    },
}

# Gerber copper is absent at these through-hole connector-pad centres on the
# listed internal layers.  Hiding only the absent copper keeps each plated
# drill and its outer-layer pads intact.  The mapping is frozen from the
# comprehensive all-dark-copper scan in
# output/validation/native-unused-inner-layer-pad-analysis.json.
UNUSED_INNER_LAYER_OVERRIDES: dict[tuple[str, str], tuple[int, ...]] = {
    **{(f"J{index}", "1"): (15, 16, 17, 18) for index in range(2, 12)},
    **{(f"J{index}", "1"): (15, 16, 18) for index in range(12, 18)},
    **{(f"J{index}", "2"): (16,) for index in range(2, 18)},
}


def stable_id(kind: str, key: str) -> str:
    """Return the 16-lowercase-hex UUID form used by the installed editor."""
    return hashlib.sha256(f"stm32h747-v19\0{kind}\0{key}".encode()).hexdigest()[:16]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def clean_name(value: str, fallback: str = "unnamed") -> str:
    value = re.sub(r"[^0-9A-Za-z._+-]+", "_", str(value or "")).strip("._")
    return value[:120] or fallback


def natural_key(value: Any) -> list[Any]:
    return [int(x) if x.isdigit() else x.casefold() for x in re.split(r"(\d+)", str(value))]


def num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def rounded(value: float, digits: int = 6) -> int | float:
    value = round(float(value), digits)
    if value == 0:
        return 0
    return int(value) if value.is_integer() else value


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def color_hex(value: Any) -> str | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    channels = [max(0, min(255, round(num(v) * 255))) for v in value[:3]]
    return "#" + "".join(f"{v:02X}" for v in channels)


class NativeDocument:
    """Small writer for the JSON-record source emitted by EasyEDA Pro 3.2.206."""

    def __init__(self, doc_type: str, uuid: str, title: str):
        self.doc_type = doc_type
        self.uuid = uuid
        self.title = title
        self.records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.ticket = 0
        self.element = 0
        self.add(
            "DOCHEAD",
            {
                "docType": doc_type,
                "client": stable_id("client", "STM32H747_MCU_BOARD_v19"),
                "uuid": uuid,
                "updateTime": DEFAULT_UPDATE_TIME,
                "version": str(DEFAULT_UPDATE_TIME),
                "editVersion": EDITOR_VERSION,
                "user": {"uuid": uuid, "username": "", "nickname": ""},
            },
        )

    def add(self, kind: str, body: dict[str, Any], primitive_id: str | None = None) -> str:
        self.ticket += 1
        outer: dict[str, Any] = {"type": kind, "ticket": self.ticket}
        if primitive_id is not None:
            outer["id"] = primitive_id
        self.records.append((outer, body))
        return primitive_id or ""

    def primitive(self, kind: str, body: dict[str, Any]) -> str:
        self.element += 1
        primitive_id = f"e{self.element}"
        self.add(kind, body, primitive_id)
        return primitive_id

    def source(self) -> str:
        # DOCHEAD is excluded from its own fingerprint only for the two values
        # derived below.  UUID, client, user, editVersion and every native
        # record/body still participate in the digest.
        fingerprint_records: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for outer, body in self.records:
            fingerprint_body = dict(body)
            if outer.get("type") == "DOCHEAD":
                fingerprint_body.pop("updateTime", None)
                fingerprint_body.pop("version", None)
            fingerprint_records.append((outer, fingerprint_body))
        content_digest = hashlib.sha256(json_compact(fingerprint_records).encode("utf-8")).hexdigest()
        content_bucket = int(content_digest[:16], 16) % NATIVE_CACHE_VERSION_WIDTH
        content_version = (
            (NATIVE_CACHE_VERSION_EPOCH + 1) * NATIVE_CACHE_VERSION_WIDTH + content_bucket
        )
        # Keep updateTime timestamp-shaped and strictly newer than the former
        # fixed header while `version` carries the strong content identity.
        content_update_time = (
            DEFAULT_UPDATE_TIME
            + NATIVE_CACHE_VERSION_EPOCH * 1_000_000
            + int(content_digest[16:24], 16) % 1_000_000
        )
        for outer, body in self.records:
            if outer.get("type") == "DOCHEAD":
                body["updateTime"] = content_update_time
                body["version"] = str(content_version)
                break
        return "".join(f"{json_compact(a)}||{json_compact(b)}|\n" for a, b in self.records)


FOOTPRINT_LAYERS = [
    (1, "TOP", "Top Layer", "#FF0000", "#7F0000"),
    (2, "BOTTOM", "Bottom Layer", "#0000FF", "#00007F"),
    (3, "TOP_SILK", "Top Silkscreen Layer", "#FFCC00", "#7F6600"),
    (4, "BOT_SILK", "Bottom Silkscreen Layer", "#66CC33", "#336619"),
    (7, "TOP_PASTE_MASK", "Top Paste Mask Layer", "#808080", "#404040"),
    (8, "BOT_PASTE_MASK", "Bottom Paste Mask Layer", "#800000", "#400000"),
    (5, "TOP_SOLDER_MASK", "Top Solder Mask Layer", "#800080", "#400040"),
    (6, "BOT_SOLDER_MASK", "Bottom Solder Mask Layer", "#AA00FF", "#55007F"),
    (13, "DOCUMENT", "Document Layer", "#FFFFFF", "#7F7F7F"),
    (11, "OUTLINE", "Board Outline Layer", "#FF00FF", "#7F007F"),
    (12, "MULTI", "Multi-Layer", "#C0C0C0", "#606060"),
    (9, "TOP_ASSEMBLY", "Top Assembly Layer", "#33CC99", "#19664C"),
    (10, "BOT_ASSEMBLY", "Bottom Assembly Layer", "#5555FF", "#2A2A7F"),
    (14, "MECHANICAL", "Mechanical Layer", "#F022F0", "#781178"),
    (52, "COMPONENT_MODEL", "Component Model Layer", "#FFFFFF", "#7F7F7F"),
    (48, "COMPONENT_SHAPE", "Component Shape Layer", "#00CCCC", "#006666"),
    (51, "PIN_FLOATING", "Pin Floating Layer", "#FF99FF", "#7F4C7F"),
    (49, "COMPONENT_MARKING", "Component Marking Layer", "#00CC66", "#006633"),
    (50, "PIN_SOLDERING", "Pin Soldering Layer", "#FF6666", "#7F3333"),
]


def doc_source(uuid: str) -> str:
    return f"{uuid}|project"


def component_groups(schematic: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    instances: list[dict[str, Any]] = []
    for page in schematic.get("pages", []):
        for component in page.get("components", []):
            c = dict(component)
            c["_pdf_page"] = page.get("pdf_page")
            c["_sheet_index"] = page.get("new_sheet_index")
            c["_sheet_name"] = page.get("sheet_name")
            base = str(c.get("base_reference") or c.get("reference") or "").strip()
            if not base:
                continue
            groups[base].append(c)
            instances.append(c)
    for base in groups:
        groups[base].sort(key=lambda c: (natural_key(c.get("unit") or ""), num(c.get("annotation_index"))))
    return dict(groups), instances


EXCLUDED_COMPONENT_VECTOR_COLORS = {"#009600", "#000084", "#0000C2", "#0000FF"}


def bbox_area(bbox: Sequence[float]) -> float:
    return max(0.0, num(bbox[2]) - num(bbox[0])) * max(0.0, num(bbox[3]) - num(bbox[1]))


def assign_pdf_vectors(groups: dict[str, list[dict[str, Any]]], pdf_path: Path) -> dict[str, Any]:
    """Attach each visible component-owned PDF path to exactly one symbol part.

    Green wires and blue bus/net geometry remain page-owned.  If annotation
    rectangles overlap, the smallest containing component rectangle owns the
    vector; reference/unit/annotation index provide a stable final tie-break.
    """
    try:
        from extract_page1_vectors import extract_vectors
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on caller runtime
        raise RuntimeError(
            "PDF vector dependencies are unavailable. Run this script with the Codex bundled Python runtime "
            "or install pypdf and pdfplumber; falling back to approximate symbol graphics is intentionally disabled."
        ) from exc

    reader = PdfReader(str(pdf_path))
    by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for components in groups.values():
        for component in components:
            component["_owned_vectors"] = []
            page = int(component.get("_pdf_page") or 0)
            bbox = (component.get("bbox") or {}).get("top_left_pt")
            if page and isinstance(bbox, list) and len(bbox) >= 4:
                by_page[page].append(component)

    stats: dict[str, Any] = {"source": str(pdf_path), "excluded_colors": sorted(EXCLUDED_COMPONENT_VECTOR_COLORS), "pages": {}}
    epsilon = 1.6  # annotation rectangles include approximately 1.512 pt padding
    for pdf_page, components in sorted(by_page.items()):
        vectors, _images = extract_vectors(reader, pdf_page - 1)
        excluded = assigned = 0
        for vector in vectors:
            colors = {str(vector.get("fill_hex") or "").upper(), str(vector.get("stroke_hex") or "").upper()}
            if colors & EXCLUDED_COMPONENT_VECTOR_COLORS:
                excluded += 1
                continue
            vb = vector.get("bounds_pt_top_left")
            if not isinstance(vb, list) or len(vb) < 4:
                continue
            vx0, vy0, vx1, vy1 = map(num, vb[:4])
            cx, cy = (vx0 + vx1) / 2.0, (vy0 + vy1) / 2.0
            candidates: list[tuple[float, str, str, int, dict[str, Any]]] = []
            for component in components:
                cb = (component.get("bbox") or {}).get("top_left_pt")
                x0, y0, x1, y1 = map(num, cb[:4])
                fully_contained = (
                    vx0 >= x0 - epsilon and vy0 >= y0 - epsilon
                    and vx1 <= x1 + epsilon and vy1 <= y1 + epsilon
                )
                if fully_contained:
                    candidates.append((
                        bbox_area(cb), str(component.get("base_reference") or ""),
                        str(component.get("unit") or ""), int(component.get("annotation_index") or 0), component,
                    ))
            if not candidates:
                continue
            candidates.sort(key=lambda item: (item[0], natural_key(item[1]), natural_key(item[2]), item[3]))
            candidates[0][4]["_owned_vectors"].append(vector)
            assigned += 1
        for component in components:
            component["_owned_vectors"].sort(key=lambda value: int(value.get("draw_order") or 0))
        stats["pages"][str(pdf_page)] = {
            "pdf_vectors": len(vectors), "excluded_green_or_bus": excluded,
            "component_owned": assigned, "page_owned_or_unassigned": len(vectors) - excluded - assigned,
        }
    stats["component_owned_total"] = sum(v["component_owned"] for v in stats["pages"].values())
    return stats


def field(component: dict[str, Any], *names: str) -> str:
    fields = component.get("fields") or {}
    folded = {str(k).casefold(): str(v) for k, v in fields.items()}
    for name in names:
        value = folded.get(name.casefold())
        if value:
            return value
    return ""


def point_from_local(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return num(value[0]), num(value[1])
    return None


def part_points(component: dict[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for pin in component.get("pins", []):
        p = point_from_local((pin.get("connection") or {}).get("local_easyeda"))
        if p:
            points.append(p)
        line = pin.get("line") or {}
        for key in ("p1_local_easyeda", "p2_local_easyeda"):
            p = point_from_local(line.get(key))
            if p:
                points.append(p)
    origin = point_from_local(component.get("origin_easyeda")) or (0.0, 0.0)
    owned_vectors = component.get("_owned_vectors", [])
    if not owned_vectors:
        # Kept only as a diagnostic fallback for evidence files without the
        # PDF vector layer.  Normal builds intentionally use exact PDF paths.
        graphics = component.get("graphics") or {}
        for line in graphics.get("lines", []):
            for key in ("p1_local_easyeda", "p2_local_easyeda"):
                p = point_from_local(line.get(key))
                if p:
                    points.append(p)
        for rect in graphics.get("rects", []):
            bbox = rect.get("bbox_local_easyeda")
            if isinstance(bbox, list) and len(bbox) >= 4:
                points.extend([(num(bbox[0]), num(bbox[1])), (num(bbox[2]), num(bbox[3]))])
        for curve in graphics.get("curves", []):
            for command in curve.get("path_top_left_pt", []):
                for p in command.get("points", []):
                    if isinstance(p, list) and len(p) >= 2:
                        points.append((num(p[0]) * PT_TO_EASYEDA - origin[0], num(p[1]) * PT_TO_EASYEDA - origin[1]))
    for vector in owned_vectors:
        for subpath in vector.get("subpaths", []):
            for segment in subpath.get("segments", []):
                raw = segment.get("pt_top_left")
                vector_points = raw if segment.get("op") == "C" else [raw]
                for p in vector_points or []:
                    if isinstance(p, list) and len(p) >= 2:
                        points.append((num(p[0]) * PT_TO_EASYEDA - origin[0], num(p[1]) * PT_TO_EASYEDA - origin[1]))
    if not points:
        bbox = (component.get("bbox") or {}).get("easyeda")
        if isinstance(bbox, list) and len(bbox) >= 4:
            points.extend([(0.0, 0.0), (num(bbox[2]) - num(bbox[0]), num(bbox[3]) - num(bbox[1]))])
    return points or [(-10.0, -10.0), (10.0, 10.0)]


class PartTransform:
    def __init__(self, component: dict[str, Any], y_axis: str):
        points = part_points(component)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self.cx = (min(xs) + max(xs)) / 2.0
        self.cy = (min(ys) + max(ys)) / 2.0
        self.y_sign = 1.0 if y_axis == "down" else -1.0
        transformed = [self.point(p) for p in points]
        tx = [p[0] for p in transformed]
        ty = [p[1] for p in transformed]
        self.bbox = [rounded(min(tx)), rounded(max(ty)), rounded(max(tx)), rounded(min(ty))]

    def point(self, p: Sequence[float]) -> tuple[int | float, int | float]:
        return rounded(num(p[0]) - self.cx), rounded((num(p[1]) - self.cy) * self.y_sign)


def rotation_for_pin(endpoint: tuple[float, float], inner: tuple[float, float]) -> int:
    dx, dy = inner[0] - endpoint[0], inner[1] - endpoint[1]
    if abs(dx) >= abs(dy):
        return 0 if dx >= 0 else 180
    return 90 if dy >= 0 else 270


def pin_electrical_type(pin: dict[str, Any]) -> str:
    name = str(pin.get("name") or "").upper()
    net = str(pin.get("net") or "").upper()
    if any(token in name for token in ("VSS", "GND", "VSSA")) or net == "GND":
        return "Ground"
    if any(token in name for token in ("VDD", "VCC", "VBAT", "VDDA", "VREF")):
        return "Power"
    if name.startswith(("NC", "N.C")) or pin.get("intrinsic_nc_pin"):
        return "Undefined"
    return "BI"


def is_power_driver_component(component: dict[str, Any]) -> bool:
    """Return true for KiCad PWR_FLAG, which is an ERC output driver.

    EasyEDA Pro 3.2.206 exposes no separate ``Power Output`` pin enum.  Its
    official ``ESCH_PrimitivePinType`` enum uses ``OUT`` for an output driver,
    while ``Power`` is the ordinary power-pin type.  A PWR_FLAG must therefore
    remain a docType-2 component with an ``OUT`` pin; making it a docType-18
    NET_FLAG would turn it into a global label and discard its ERC purpose.
    """
    reference = str(component.get("reference") or "").upper()
    value = str(component.get("value") or "").upper()
    return reference.startswith("#FLG") or value == "PWR_FLAG"


def pin_line_points(pin: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]] | None:
    line = pin.get("line") or {}
    p1 = point_from_local(line.get("p1_local_easyeda"))
    p2 = point_from_local(line.get("p2_local_easyeda"))
    connection = pin.get("connection") or {}
    endpoint = point_from_local(connection.get("local_easyeda"))
    if not endpoint:
        return None
    # Pin augmentation may carry absolute EasyEDA line coordinates while the
    # original geometric extractor carries local coordinates.  Recover the
    # latter from the connection's paired absolute/local point.
    absolute_endpoint = point_from_local(connection.get("easyeda"))
    if absolute_endpoint and (p1 is None or p2 is None):
        origin = (absolute_endpoint[0] - endpoint[0], absolute_endpoint[1] - endpoint[1])
        abs_p1 = point_from_local(line.get("p1_easyeda"))
        abs_p2 = point_from_local(line.get("p2_easyeda"))
        if abs_p1:
            p1 = (abs_p1[0] - origin[0], abs_p1[1] - origin[1])
        if abs_p2:
            p2 = (abs_p2[0] - origin[0], abs_p2[1] - origin[1])
    if p1 and p2:
        d1 = math.hypot(p1[0] - endpoint[0], p1[1] - endpoint[1])
        d2 = math.hypot(p2[0] - endpoint[0], p2[1] - endpoint[1])
        return endpoint, p2 if d1 <= d2 else p1
    side = str(pin.get("side") or "left").lower()
    delta = {"left": (10, 0), "right": (-10, 0), "top": (0, 10), "bottom": (0, -10)}.get(side, (10, 0))
    return endpoint, (endpoint[0] + delta[0], endpoint[1] + delta[1])


def common_symbol_body(part_id: str, z: int) -> dict[str, Any]:
    return {"partId": part_id, "groupId": "", "locked": False, "zIndex": z}


def native_symbol_points(points: Iterable[Sequence[float]]) -> list[dict[str, int | float]]:
    """Encode the in-memory point form actually consumed by Pro 3.2.206.

    The public format guide documents a flat number array.  A source round-trip
    in the installed 3.2.206 build instead emits point objects, and the renderer
    silently drops guide-style flat arrays.  The occasional runtime-only
    `hashed` cache is intentionally omitted; the importer computes it.
    """
    return [{"x": rounded(num(p[0])), "y": rounded(num(p[1]))} for p in points]


def add_symbol_pdf_vectors(doc: NativeDocument, part_id: str, component: dict[str, Any],
                           tr: PartTransform, z: int) -> int:
    """Add exact visible PDF paths owned by a component annotation rectangle."""
    origin = point_from_local(component.get("origin_easyeda")) or (0.0, 0.0)

    def local_point(p: Sequence[float]) -> tuple[float, float]:
        return num(p[0]) * PT_TO_EASYEDA - origin[0], num(p[1]) * PT_TO_EASYEDA - origin[1]

    for vector in component.get("_owned_vectors", []):
        fill = bool(vector.get("fill"))
        stroke = bool(vector.get("stroke"))
        dash = vector.get("dash") or [[], 0]
        stroke_style = "SHORT_DASH" if dash and dash[0] else "SOLID"
        for subpath in vector.get("subpaths", []):
            points: list[tuple[float, float]] = []
            start: tuple[float, float] | None = None
            current: tuple[float, float] | None = None
            for segment in subpath.get("segments", []):
                op = str(segment.get("op") or "").upper()
                raw = segment.get("pt_top_left")
                if op in ("M", "L") and isinstance(raw, list) and len(raw) >= 2:
                    p = local_point(raw)
                    if op == "M":
                        start = p
                    points.append(p)
                    current = p
                elif op == "C" and current is not None and isinstance(raw, list) and len(raw) >= 3:
                    p0, p1, p2, p3 = current, local_point(raw[0]), local_point(raw[1]), local_point(raw[2])
                    for step in range(1, 13):
                        t = step / 12.0
                        u = 1.0 - t
                        points.append((
                            u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                            u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
                        ))
                    current = p3
            if len(points) < 2:
                continue
            transformed = [tr.point(p) for p in points]
            closed = bool(subpath.get("closed") or fill)
            fill_color = str(vector.get("fill_hex") or "") if fill else ""
            stroke_color = str(vector.get("stroke_hex") or "") if stroke else (fill_color if fill else "")
            stroke_width = (rounded(max(0.01, num(vector.get("line_width_pt")) * PT_TO_EASYEDA))
                            if stroke else (SYMBOL_VISUAL_EPSILON if fill else None))
            z += 1
            doc.primitive("POLY", {
                **common_symbol_body(part_id, z), "points": native_symbol_points(transformed), "closed": closed,
                "startShape": None, "endShape": None,
                "strokeColor": stroke_color,
                "strokeStyle": stroke_style, "fillColor": fill_color,
                "strokeWidth": stroke_width,
                "fillStyle": "SOLID" if fill else "NONE",
            })
    return z


def add_symbol_graphics(doc: NativeDocument, part_id: str, component: dict[str, Any], tr: PartTransform, z: int) -> int:
    graphics = component.get("graphics") or {}
    pin_segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    for pin in component.get("pins", []):
        points = pin_line_points(pin)
        if points:
            p1, p2 = points
            pin_segments.add(tuple(sorted(((round(p1[0], 3), round(p1[1], 3)), (round(p2[0], 3), round(p2[1], 3))))))

    for rect in graphics.get("rects", []):
        bbox = rect.get("bbox_local_easyeda")
        if not isinstance(bbox, list) or len(bbox) < 4:
            continue
        p1, p2 = tr.point((bbox[0], bbox[1])), tr.point((bbox[2], bbox[3]))
        z += 1
        fill = bool(rect.get("fill"))
        doc.primitive("RECT", {
            **common_symbol_body(part_id, z), "dotX1": p1[0], "dotY1": p1[1], "dotX2": p2[0], "dotY2": p2[1],
            "radiusX": 0, "radiusY": 0, "rotation": 0,
            "strokeColor": color_hex(rect.get("stroking_color")) if rect.get("stroke") else "",
            "strokeStyle": "SOLID", "fillColor": color_hex(rect.get("non_stroking_color")) if fill else "",
            "strokeWidth": rounded(num(rect.get("line_width_pt")) * PT_TO_EASYEDA) if rect.get("stroke") else None,
            "fillStyle": "SOLID" if fill else "NONE",
        })

    for line in graphics.get("lines", []):
        p1 = point_from_local(line.get("p1_local_easyeda"))
        p2 = point_from_local(line.get("p2_local_easyeda"))
        if not p1 or not p2:
            continue
        segment = tuple(sorted(((round(p1[0], 3), round(p1[1], 3)), (round(p2[0], 3), round(p2[1], 3)))))
        if segment in pin_segments:
            continue
        a, b = tr.point(p1), tr.point(p2)
        z += 1
        doc.primitive("POLY", {
            **common_symbol_body(part_id, z), "points": native_symbol_points((a, b)), "closed": False,
            "startShape": None, "endShape": None,
            "strokeColor": color_hex(line.get("stroking_color")), "strokeStyle": "SOLID", "fillColor": "",
            "strokeWidth": rounded(max(0.1, num(line.get("line_width_pt")) * PT_TO_EASYEDA)), "fillStyle": "NONE",
        })

    origin = point_from_local(component.get("origin_easyeda")) or (0.0, 0.0)
    for curve in graphics.get("curves", []):
        commands = curve.get("path_top_left_pt", [])
        start: tuple[float, float] | None = None
        current: tuple[float, float] | None = None
        line_points: list[tuple[float, float]] = []
        fill = bool(curve.get("fill"))
        for command in commands:
            op = str(command.get("op") or "").lower()
            pts = [
                (num(p[0]) * PT_TO_EASYEDA - origin[0], num(p[1]) * PT_TO_EASYEDA - origin[1])
                for p in command.get("points", []) if isinstance(p, list) and len(p) >= 2
            ]
            if op == "m" and pts:
                current = start = pts[-1]
                line_points = [current]
            elif op == "l" and pts:
                current = pts[-1]
                line_points.append(current)
            elif op == "c" and current is not None and len(pts) >= 3:
                p0, p1, p2, p3 = current, pts[0], pts[1], pts[2]
                # Avoid BEZIER source-version ambiguity by sampling the cubic
                # into the renderer-proven POLY representation.
                for step in range(1, 13):
                    t = step / 12.0
                    u = 1.0 - t
                    line_points.append((
                        u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0],
                        u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1],
                    ))
                current = pts[2]
            elif op in ("h", "z") and start is not None:
                line_points.append(start)
                current = start
        if len(line_points) > 1:
            transformed = [tr.point(p) for p in line_points]
            closed = bool(start and current and math.hypot(start[0] - current[0], start[1] - current[1]) < 0.01)
            z += 1
            doc.primitive("POLY", {**common_symbol_body(part_id, z), "points": native_symbol_points(transformed),
                "closed": closed, "startShape": None, "endShape": None,
                "strokeColor": color_hex(curve.get("stroking_color")), "strokeStyle": "SOLID",
                "fillColor": color_hex(curve.get("non_stroking_color")) if fill else "",
                "strokeWidth": rounded(max(0.1, num(curve.get("line_width_pt")) * PT_TO_EASYEDA)),
                "fillStyle": "SOLID" if fill else "NONE"})
    return z


def add_pin(doc: NativeDocument, part_id: str, pin: dict[str, Any], tr: PartTransform, z: int,
            pin_type_override: str | None = None, fallback_pin_index: int = 1) -> tuple[int, dict[str, Any]]:
    points = pin_line_points(pin)
    if points is None:
        raise ValueError("pin has no connection coordinate")
    endpoint, inner = tr.point(points[0]), tr.point(points[1])
    rotation = rotation_for_pin((num(endpoint[0]), num(endpoint[1])), (num(inner[0]), num(inner[1])))
    z += 1
    pin_id = doc.primitive("PIN", {**common_symbol_body(part_id, z), "display": False, "x": endpoint[0], "y": endpoint[1],
        "length": SYMBOL_VISUAL_EPSILON, "rotation": rotation, "color": None, "pinShape": "NONE"})
    align_name = "LEFT_BOTTOM" if rotation in (0, 90) else "RIGHT_BOTTOM"
    align_number = "RIGHT_BOTTOM" if align_name == "LEFT_BOTTOM" else "LEFT_BOTTOM"
    raw_pin_number = str(pin.get("number") or "")
    raw_pin_name = str(pin.get("name") or "")
    pin_number = raw_pin_number if raw_pin_number.strip() else ""
    pin_name = raw_pin_name if raw_pin_name.strip() else (pin_number or f"P{fallback_pin_index}")
    for key, value, visible, align in (
        ("Pin Name", pin_name, False, align_name),
        ("Pin Number", pin_number, False, align_number),
        ("Pin Type", pin_type_override or pin_electrical_type(pin), False, "LEFT_BOTTOM"),
    ):
        z += 1
        doc.primitive("ATTR", {**common_symbol_body(part_id, z), "parentId": pin_id, "key": key, "value": value,
            "keyVisible": False, "valueVisible": visible, "x": None, "y": None, "rotation": 0, "color": None,
            "fillColor": None, "fontFamily": None, "fontSize": None, "strikeout": None,
            "underline": False if key != "Pin Type" else None, "italic": False if key != "Pin Type" else None,
            "fontWeight": False if key != "Pin Type" else None, "align": align, "version": "2.0"})
    return z, {"primitive_id": pin_id, "number": pin_number, "name": str(pin.get("name") or ""),
               "part": part_id, "x": endpoint[0], "y": endpoint[1], "length": SYMBOL_VISUAL_EPSILON,
               "rotation": rotation, "net": pin.get("net"), "confidence": pin.get("confidence")}


def build_symbol(base: str, components: list[dict[str, Any]], y_axis: str) -> tuple[str, str, dict[str, Any], list[str]]:
    value = str(components[0].get("value") or base)
    is_power_symbol = all(bool(component.get("is_power_symbol")) for component in components)
    is_power_driver = is_power_symbol and all(is_power_driver_component(component) for component in components)
    # EasyEDA Pro 3.2.206 still applies the missing-footprint ERC rule to an
    # ordinary component even when "Convert to PCB" is explicitly "no".
    # Translate both KiCad #PWR and its seven PWR_FLAG power-output drivers to
    # native NET_FLAG documents.  The latter retain an OUT electrical pin and
    # explicit is_power_driver metadata so the semantic port remains auditable.
    is_net_flag = is_power_symbol
    uuid = stable_id("symbol", base)
    doc = NativeDocument("SYMBOL", uuid, f"{base}_{value}")
    doc.add("CANVAS", {"originX": 0, "originY": 0}, "CANVAS")
    transforms: dict[str, PartTransform] = {}
    part_components: list[tuple[str, dict[str, Any]]] = []
    used_parts: set[str] = set()
    for index, component in enumerate(components):
        proposed = str(component.get("unit") or ("A" if len(components) == 1 else chr(65 + index))).upper()
        part_id = proposed
        suffix = 2
        while part_id in used_parts:
            part_id = f"{proposed}{suffix}"
            suffix += 1
        used_parts.add(part_id)
        tr = PartTransform(component, y_axis)
        transforms[part_id] = tr
        component["_native_part_id"] = part_id
        part_components.append((part_id, component))
        doc.add("PART", {"title": part_id}, part_id)
    doc.add("META", {"title": f"{base}_{value}", "description": field(components[0], "Description"),
        "tags": ["STM32H747_MCU_BOARD_v19", "PDF_RECONSTRUCTION"],
        "docType": 18 if is_net_flag else 2, "source": doc_source(uuid)}, "META")
    z = 0
    generated_pins: list[dict[str, Any]] = []
    hidden_nc_pins: list[dict[str, Any]] = []
    problems: list[str] = []
    if is_power_symbol:
        for component in components:
            semantic_pins = component.get("pins") or []
            if len(semantic_pins) != 1 or not semantic_pins[0].get("net"):
                problems.append(
                    f"{component.get('reference')}: power symbol requires exactly one pin with an actual net"
                )
    seen_numbers: set[str] = set()
    for part_id, component in part_components:
        tr = transforms[part_id]
        if component.get("_owned_vectors"):
            z = add_symbol_pdf_vectors(doc, part_id, component, tr, z)
        else:
            problems.append(f"{component.get('reference')}: no exact PDF vectors assigned")
            z = add_symbol_graphics(doc, part_id, component, tr, z)
        for pin_index, pin in enumerate(component.get("pins", []), start=1):
            number = str(pin.get("number") or "").strip()
            if not number:
                problems.append(f"{component.get('reference')}: pin number missing")
                continue
            if number in seen_numbers:
                problems.append(f"{base}: duplicate pin number {number!r} across parts")
                continue
            seen_numbers.add(number)
            if pin.get("hidden") and pin.get("intrinsic_nc_pin") and not pin_line_points(pin):
                # A package pad that is explicitly N/C is intentionally absent
                # from the drawn symbol.  Retain it in the device evidence so
                # strict pin/pad validation can distinguish it from an unknown.
                hidden_nc_pins.append({"number": number, "part": part_id, "provenance": pin.get("provenance"),
                                       "confidence": pin.get("confidence")})
                continue
            try:
                z, generated = add_pin(
                    doc, part_id, pin, tr, z,
                    pin_type_override="OUT" if is_power_driver else None,
                    fallback_pin_index=pin_index,
                )
                generated_pins.append(generated)
            except ValueError as exc:
                problems.append(f"{component.get('reference')} pin {number}: {exc}")
    part_transforms = {}
    for part_id, component in part_components:
        tr = transforms[part_id]
        origin = point_from_local(component.get("origin_easyeda")) or (0.0, 0.0)
        raw_part_origin = [rounded(tr.cx), rounded(tr.cy)]
        part_transforms[part_id] = {
            "source_reference": component.get("reference"), "source_unit": component.get("unit") or "A",
            "component_bbox": component.get("bbox"), "raw_part_origin_easyeda": raw_part_origin,
            "placement_easyeda": [rounded(origin[0] + tr.cx), rounded(origin[1] + tr.cy)],
            "symbol_bbox": tr.bbox,
            "owned_vector_orders": [int(v.get("draw_order") or 0) for v in component.get("_owned_vectors", [])],
        }
    info = {
        "uuid": uuid, "title": f"{base}_{value}", "base_reference": base,
        "is_power_symbol": is_power_symbol, "is_net_flag": is_net_flag,
        "is_power_driver": is_power_driver,
        "symbol_type": "NET_FLAG" if is_net_flag else ("POWER_DRIVER" if is_power_driver else "COMPONENT"),
        "symbol_doc_type": 18 if is_net_flag else 2,
        "parts": [p for p, _ in part_components], "pins": generated_pins, "hidden_intrinsic_nc_pins": hidden_nc_pins,
        "part_transforms": part_transforms,
        "source_pages": sorted({c.get("_pdf_page") for c in components if c.get("_pdf_page") is not None}),
        "coordinate_transform": {"input": "PDF top-left EasyEDA units", "raw_symbol_y_axis": y_axis,
                                 "part_origin": "center of clipped component graphics and pins"},
    }
    return uuid, doc.source(), info, problems


def aperture_width(gerber: dict[str, Any], layer: str, aperture: str) -> float:
    data = ((gerber.get("aperturesByLayer") or {}).get(layer) or {}).get(aperture) or {}
    params = data.get("paramsMm") or []
    return max(0.05, num(params[0], 0.1)) * MM_TO_MIL


def footprint_anchor(component: dict[str, Any]) -> tuple[float, float]:
    anchor = component.get("estimatedAnchorMm")
    if isinstance(anchor, list) and len(anchor) >= 2:
        return num(anchor[0]), num(anchor[1])
    points: list[tuple[float, float]] = []
    for pad in (component.get("pads") or {}).values():
        for flash in pad.get("flashes", []):
            at = flash.get("atMm")
            if isinstance(at, list) and len(at) >= 2:
                points.append((num(at[0]), num(at[1])))
    if not points:
        return 0.0, 0.0
    return sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)


def pcb_point(at: Sequence[float], anchor: tuple[float, float]) -> tuple[int | float, int | float]:
    # EasyEDA Pro 3.2.206 PCB and FOOTPRINT raw coordinates are Y-up.  This was
    # verified with two runtime PADs: raw/API y=200 renders above y=100.
    return rounded((num(at[0]) - anchor[0]) * MM_TO_MIL), rounded((num(at[1]) - anchor[1]) * MM_TO_MIL)


def preferred_flash(pad: dict[str, Any], side: str) -> dict[str, Any] | None:
    flashes = [f for f in pad.get("flashes", []) if f.get("layer") in ("F.Cu", "B.Cu")]
    preferred = "B.Cu" if side.upper().startswith("B") else "F.Cu"
    return next((f for f in flashes if f.get("layer") == preferred), flashes[0] if flashes else None)


def aperture_definition(gerber: dict[str, Any], flash: dict[str, Any]) -> dict[str, Any]:
    layer = str(flash.get("layer") or "")
    aperture = str(flash.get("aperture") or "")
    return ((gerber.get("aperturesByLayer") or {}).get(layer) or {}).get(aperture) or {}


def pad_shape(gerber: dict[str, Any], flash: dict[str, Any]) -> tuple[dict[str, Any], int | float, str]:
    aperture = aperture_definition(gerber, flash)
    template = str(aperture.get("template") or flash.get("shape") or "C")
    shape = template.upper()
    raw_params = aperture.get("paramsMm") or flash.get("paramsMm") or []
    params = [num(value) for value in raw_params]
    if shape == "C":
        diameter = max(0.001, params[0] if params else 1.0) * MM_TO_MIL
        return ({"padType": "ELLIPSE", "width": rounded(diameter), "height": rounded(diameter)}, 0, template)
    if shape == "ROUNDRECT":
        half_extent = aperture.get("halfExtentMm") or []
        if len(half_extent) < 2:
            raise ValueError(f"RoundRect aperture lacks halfExtentMm: {flash!r}")
        width = max(0.001, 2 * num(half_extent[0])) * MM_TO_MIL
        height = max(0.001, 2 * num(half_extent[1])) * MM_TO_MIL
        radius = max(0.0, params[0] if params else 0.0) * MM_TO_MIL
        angle = params[-1] if len(params) >= 10 else 0.0
        return ({"padType": "RECT", "width": rounded(width), "height": rounded(height),
                 "radius": rounded(radius)}, rounded(angle), "RoundRect")
    if shape == "OUTLINE5P":
        if len(params) < 11:
            raise ValueError(f"Outline5P aperture has fewer than 11 parameters: {flash!r}")
        path: list[Any] = [rounded(params[0] * MM_TO_MIL), rounded(params[1] * MM_TO_MIL)]
        for index in range(2, 10, 2):
            path.extend(["L", rounded(params[index] * MM_TO_MIL), rounded(params[index + 1] * MM_TO_MIL)])
        return ({"padType": "POLYGON", "path": path}, rounded(params[10]), "Outline5P")
    width = max(0.001, params[0] if params else 1.0) * MM_TO_MIL
    height = max(0.001, params[1] if len(params) > 1 else (params[0] if params else 1.0)) * MM_TO_MIL
    if shape in ("O", "OBROUND"):
        # EasyEDA Pro 3.2's footprint-library clone path rejected these OVAL
        # rows even though its pad renderer supports the nominal type.  A RECT
        # with radius=100 is the editor's canonical, geometry-identical capsule
        # representation and survives project-library placement/reload.
        return ({"padType": "RECT", "width": rounded(width), "height": rounded(height), "radius": 100}, 0, template)
    return ({"padType": "RECT", "width": rounded(width), "height": rounded(height), "radius": 0}, 0, template)


def place_polygon_pad_path(shape: dict[str, Any], center_x: Any, center_y: Any,
                           angle_deg: Any) -> dict[str, Any]:
    """Put a Gerber macro polygon into EasyEDA footprint coordinates.

    EasyEDA Pro 3.2's polygon-pad shape path is already in document/footprint
    coordinates.  Unlike RECT/OVAL pads, the PCB runtime does not apply the
    PAD's ``centerX``, ``centerY`` or ``padAngle`` to ``defaultPad.path``.
    Gerber aperture-macro vertices, however, are local to the flash and carry
    their own rotation.  Apply both operations here while retaining the PAD
    center/angle fields as source metadata.

    The current Gerber reconstruction emits only straight-line Outline5P pad
    paths.  Reject any other command instead of silently corrupting it.
    """

    if shape.get("padType") != "POLYGON":
        return shape
    path = shape.get("path")
    if not isinstance(path, list) or len(path) < 2:
        raise ValueError(f"polygon pad has no usable path: {shape!r}")

    angle = math.radians(num(angle_deg))
    cosine, sine = math.cos(angle), math.sin(angle)
    placed: list[Any] = []
    index = 0
    while index < len(path):
        token = path[index]
        if isinstance(token, str):
            if token != "L":
                raise ValueError(f"unsupported polygon-pad command {token!r}: {path!r}")
            placed.append(token)
            index += 1
            continue
        if index + 1 >= len(path) or isinstance(path[index + 1], str):
            raise ValueError(f"malformed polygon-pad coordinate pair: {path!r}")
        local_x, local_y = num(token), num(path[index + 1])
        placed.extend([
            rounded(num(center_x) + local_x * cosine - local_y * sine),
            rounded(num(center_y) + local_x * sine + local_y * cosine),
        ])
        index += 2
    return {**shape, "path": placed}


def pad_hole(flash: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, int | float]:
    holes = flash.get("holes") or []
    if not holes:
        return None, True, 0
    hole = holes[0]
    diameter = max(0.001, num(hole.get("diameterMm"))) * MM_TO_MIL
    if str(hole.get("kind") or "").lower() == "slot":
        overall_length_mm = num(hole.get("overallLengthMm"))
        if overall_length_mm <= 0:
            start, end = hole.get("startMm"), hole.get("endMm")
            if not (isinstance(start, list) and isinstance(end, list) and len(start) >= 2 and len(end) >= 2):
                raise ValueError(f"routed slot lacks length/endpoints: {hole!r}")
            overall_length_mm = math.hypot(num(end[0]) - num(start[0]), num(end[1]) - num(start[1])) + num(
                hole.get("diameterMm")
            )
        return (
            {
                "holeType": "SLOT",
                # EasyEDA Pro 3.2 PAD source stores SLOT width as the complete
                # round-capped slot length and height as the drill diameter.
                "width": rounded(overall_length_mm * MM_TO_MIL),
                "height": rounded(diameter),
            },
            bool(hole.get("plated", True)),
            rounded(hole.get("angleDeg", 0)),
        )
    return (
        {"holeType": "ROUND", "width": rounded(diameter), "height": rounded(diameter)},
        bool(hole.get("plated", True)),
        0,
    )


def layered_thermal_special_pad(
    base: str,
    pad_number: str,
    pad: dict[str, Any],
    flash: dict[str, Any],
    shape: dict[str, Any],
    hole: dict[str, Any] | None,
    plated: bool,
    layer: int,
) -> list[dict[str, Any]]:
    """Return the exact native top/inner/bottom shape override when required."""

    evidence = LAYERED_THERMAL_PAD_OVERRIDES.get((base, pad_number))
    if evidence is None:
        return []
    top_size = evidence["top_size_mm"] * MM_TO_MIL
    annulus = evidence["annulus_diameter_mm"] * MM_TO_MIL
    drill = evidence["drill_diameter_mm"] * MM_TO_MIL
    if (
        layer != 12
        or not plated
        or str(pad.get("netOld") or "").casefold() != "gnd"
        or flash.get("layer") != "F.Cu"
        or shape.get("padType") != "RECT"
        or shape.get("radius") != 0
        or not math.isclose(num(shape.get("width")), top_size, abs_tol=0.00016)
        or not math.isclose(num(shape.get("height")), top_size, abs_tol=0.00016)
        or not isinstance(hole, dict)
        or hole.get("holeType") != "ROUND"
        or not math.isclose(num(hole.get("width")), drill, abs_tol=0.00016)
        or not math.isclose(num(hole.get("height")), drill, abs_tol=0.00016)
    ):
        raise ValueError(
            f"{base} pad {pad_number}: layered thermal-pad evidence no longer matches "
            f"top copper/drill/net ({shape!r}, {hole!r}, {pad.get('netOld')!r})"
        )
    top = {
        "padType": "RECT",
        "width": rounded(top_size),
        "height": rounded(top_size),
        "radius": 0,
    }
    lower = {
        "padType": "ELLIPSE",
        "width": rounded(annulus),
        "height": rounded(annulus),
    }
    # This is the exact canonical mapping emitted by EasyEDA Pro 3.2's MSe
    # serializer: top, all inner copper layers, then bottom.
    return [
        {"startLayer": 1, "endLayer": 1, "pad": top},
        {"startLayer": 1, "endLayer": 2, "pad": dict(lower)},
        {"startLayer": 2, "endLayer": 2, "pad": dict(lower)},
    ]


def pad_unused_inner_layers(
    base: str,
    pad_number: str,
    hole: dict[str, Any] | None,
    plated: bool,
    layer: int,
) -> list[int]:
    """Return the frozen Gerber-proved internal-layer visibility override."""

    layers = UNUSED_INNER_LAYER_OVERRIDES.get((base, pad_number))
    if layers is None:
        return []
    if (
        layer != 12
        or not plated
        or not isinstance(hole, dict)
        or hole.get("holeType") != "ROUND"
        or any(item not in (15, 16, 17, 18) for item in layers)
    ):
        raise ValueError(
            f"{base} pad {pad_number}: unused-inner-layer evidence no longer matches "
            f"a plated multilayer round-hole PAD ({layer=}, {plated=}, {hole=!r})"
        )
    return list(layers)


def add_owned_thermal_pths(
    doc: NativeDocument,
    base: str,
    anchor: tuple[float, float],
    pad_manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit duplicate-number component PADs for the eight thermal PTHs."""

    matches = [
        (pad_number, evidence)
        for (reference, pad_number), evidence in OWNED_THERMAL_PTH_OVERRIDES.items()
        if reference == base
    ]
    if not matches:
        return []
    if len(matches) != 1:
        raise ValueError(f"{base}: expected one owned thermal-PTH evidence row, got {len(matches)}")

    pad_number, evidence = matches[0]
    logical = [item for item in pad_manifest if str(item.get("number")) == pad_number]
    if (
        len(logical) != 1
        or str(logical[0].get("net_old") or "").casefold() != str(evidence["net"]).casefold()
        or logical[0].get("layer") != 12
        or (logical[0].get("hole") or {}).get("holeType") != "ROUND"
        or len(logical[0].get("special_pad") or []) != 3
    ):
        raise ValueError(
            f"{base} pad {pad_number}: central exposed-pad contract changed before thermal-PTH expansion"
        )

    copper = rounded(num(evidence["copper_diameter_mm"]) * MM_TO_MIL)
    drill = rounded(num(evidence["drill_diameter_mm"]) * MM_TO_MIL)
    if not math.isclose(num(copper), 23.622047, abs_tol=0.00016) or not math.isclose(
        num(drill), 11.811024, abs_tol=0.00016
    ):
        raise ValueError(f"{base}: owned thermal-PTH diameter evidence changed")

    additions: list[dict[str, Any]] = []
    centers = evidence.get("centers_mm") or []
    if len(centers) != 4 or len({tuple(center) for center in centers}) != 4:
        raise ValueError(f"{base}: expected four unique owned thermal-PTH centres")
    for source_center in centers:
        if not isinstance(source_center, list) or len(source_center) != 2:
            raise ValueError(f"{base}: malformed owned thermal-PTH centre {source_center!r}")
        x, y = pcb_point(source_center, anchor)
        body = {
            "groupId": 0, "netName": "", "layerId": 12, "num": pad_number,
            "centerX": x, "centerY": y, "padAngle": 0,
            "hole": {"holeType": "ROUND", "width": drill, "height": drill},
            "defaultPad": {"padType": "ELLIPSE", "width": copper, "height": copper},
            "specialPad": [], "padOffsetX": 0, "padOffsetY": 0, "relativeAngle": 0,
            "plated": True, "padType": "NORMAL", "topSolderExpansion": None,
            "bottomSolderExpansion": None, "topPasteExpansion": None,
            "bottomPasteExpansion": None, "locked": False,
            "zIndex": len(pad_manifest) + 1,
            "connectMode": None, "spokeSpace": None, "spokeWidth": None,
            "spokeAngle": None, "unusedInnerLayers": [], "padLen": 0,
            "propagationDelay": 0,
        }
        primitive_id = doc.primitive("PAD", body)
        manifest_row = {
            "number": pad_number, "primitive_id": primitive_id, "x": x, "y": y,
            "layer": 12, "shape": body["defaultPad"], "hole": body["hole"],
            "special_pad": [], "unused_inner_layers": [], "pad_angle": 0,
            "hole_angle": 0, "aperture_template": "C",
            "exact_j1_top_openings": False, "net_old": evidence["net"],
            "pin_function_old": logical[0].get("pin_function_old"),
            "role": "Gerber/Excellon component-owned thermal PTH",
            "source_at_mm": list(source_center),
        }
        pad_manifest.append(manifest_row)
        additions.append(manifest_row)
    return additions


def add_duplicate_flash_pads(
    doc: NativeDocument,
    base: str,
    component: dict[str, Any],
    gerber: dict[str, Any],
    anchor: tuple[float, float],
    side: str,
    pad_manifest: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit every additional physical flash sharing a logical pad number.

    X2 component/pin attributes legitimately assign one logical pin number to
    several copper pads (the four grounded SMA posts and both sides of SW1).
    The first preferred-side flash is emitted by the normal logical-pad loop;
    this helper preserves every other unique centre as an owned PAD child.
    """

    additions: list[dict[str, Any]] = []
    preferred_layer = "B.Cu" if side.upper().startswith("B") else "F.Cu"
    for raw_number, pad in sorted((component.get("pads") or {}).items(), key=lambda item: natural_key(item[0])):
        pad_number = str(pad.get("number") or raw_number).strip()
        preferred = [
            flash for flash in pad.get("flashes", [])
            if flash.get("layer") == preferred_layer and isinstance(flash.get("atMm"), list)
        ]
        if not preferred:
            preferred = [
                flash for flash in pad.get("flashes", [])
                if flash.get("layer") in ("F.Cu", "B.Cu") and isinstance(flash.get("atMm"), list)
            ]
        unique: list[dict[str, Any]] = []
        centers: set[tuple[float, float]] = set()
        for flash in preferred:
            center = (round(num(flash["atMm"][0]), 9), round(num(flash["atMm"][1]), 9))
            if center not in centers:
                centers.add(center)
                unique.append(flash)
        if len(unique) <= 1:
            continue

        logical = [
            item for item in pad_manifest
            if str(item.get("number")) == pad_number and item.get("role") is None
        ]
        if len(logical) != 1:
            raise ValueError(f"{base} pad {pad_number}: expected one primary PAD before duplicate expansion")
        for flash in unique[1:]:
            x, y = pcb_point(flash["atMm"], anchor)
            hole, plated, hole_angle = pad_hole(flash)
            layer = 12 if hole else (2 if str(flash.get("layer")) == "B.Cu" else 1)
            shape, pad_angle, aperture_template = pad_shape(gerber, flash)
            shape = place_polygon_pad_path(shape, x, y, pad_angle)
            special_pad = layered_thermal_special_pad(
                base, pad_number, pad, flash, shape, hole, plated, layer
            )
            unused_inner_layers = pad_unused_inner_layers(base, pad_number, hole, plated, layer)
            body = {
                "groupId": 0, "netName": "", "layerId": layer, "num": pad_number,
                "centerX": x, "centerY": y, "padAngle": pad_angle,
                "hole": hole, "defaultPad": shape, "specialPad": special_pad,
                "padOffsetX": 0, "padOffsetY": 0, "relativeAngle": hole_angle,
                "plated": plated, "padType": "NORMAL", "topSolderExpansion": None,
                "bottomSolderExpansion": None, "topPasteExpansion": None,
                "bottomPasteExpansion": None, "locked": False,
                "zIndex": len(pad_manifest) + 1, "connectMode": None,
                "spokeSpace": None, "spokeWidth": None, "spokeAngle": None,
                "unusedInnerLayers": unused_inner_layers, "padLen": 0,
                "propagationDelay": 0,
            }
            primitive_id = doc.primitive("PAD", body)
            manifest_row = {
                "number": pad_number, "primitive_id": primitive_id, "x": x, "y": y,
                "layer": layer, "shape": shape, "hole": hole,
                "special_pad": special_pad, "unused_inner_layers": unused_inner_layers,
                "pad_angle": pad_angle, "hole_angle": hole_angle,
                "aperture_template": aperture_template,
                "exact_j1_top_openings": False, "net_old": pad.get("netOld"),
                "pin_function_old": pad.get("pinFunctionOld"),
                "role": "Gerber duplicate-number physical pad",
                "source_at_mm": list(flash["atMm"]),
            }
            pad_manifest.append(manifest_row)
            additions.append(manifest_row)
    return additions


def gerber_npth_inventory(gerber: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Split the X2-attributed NPTH drill inventory into footprint and board holes."""
    by_reference: dict[str, list[dict[str, Any]]] = defaultdict(list)
    board_mounting: list[dict[str, Any]] = []
    for drill_file in gerber.get("drills", []):
        for raw_hole in drill_file.get("holes", []):
            function = str(raw_hole.get("function") or "")
            if raw_hole.get("plated") is not False and "NonPlated" not in function and "NPTH" not in function:
                continue
            hole = dict(raw_hole)
            hole["sourceFile"] = drill_file.get("file")
            ownership = str(hole.get("ownership") or "")
            reference = str(hole.get("componentRef") or "").strip()
            if ownership == "componentMechanicalHole" and reference and reference != "REF**":
                by_reference[reference].append(hole)
            elif ownership == "boardMountingHole" and reference in ("", "REF**"):
                board_mounting.append(hole)
            else:
                raise ValueError(f"NPTH hole lacks authoritative component/board ownership: {hole!r}")
    for reference in by_reference:
        by_reference[reference].sort(key=lambda item: tuple(num(value) for value in item.get("atMm", [])))
    board_mounting.sort(key=lambda item: tuple(num(value) for value in item.get("atMm", [])))
    component_count = sum(len(holes) for holes in by_reference.values())
    if component_count != 9 or len(board_mounting) != 4:
        raise ValueError(
            f"expected 9 component mechanical NPTH and 4 board mounting NPTH; "
            f"found {component_count} and {len(board_mounting)}"
        )
    return dict(by_reference), board_mounting


def add_footprint_layers(doc: NativeDocument) -> None:
    for layer_id, layer_type, name, active, inactive in FOOTPRINT_LAYERS:
        doc.add("LAYER", {"layerType": layer_type, "layerName": name, "use": True, "show": True, "locked": False,
            "activeColor": active, "activateTransparency": 1, "inactiveColor": inactive, "inactiveTransparency": 1},
            json_compact(["LAYER", layer_id]))


def arc_angle_deg(start: Sequence[float], end: Sequence[float], center: Sequence[float], clockwise: bool) -> float:
    a = math.atan2(num(start[1]) - num(center[1]), num(start[0]) - num(center[0]))
    b = math.atan2(num(end[1]) - num(center[1]), num(end[0]) - num(center[0]))
    if clockwise:
        sweep = -((a - b) % (2 * math.pi))
    else:
        sweep = (b - a) % (2 * math.pi)
    return math.degrees(sweep)  # Gerber and EasyEDA Pro PCB coordinates are both Y-up/CCW-positive.


def geometry_key(item: dict[str, Any]) -> tuple[Any, ...] | None:
    """Return a stable key for a Gerber line/arc, independent of its wrapper."""
    kind = str(item.get("kind") or "")
    if kind == "line" and all(isinstance(item.get(key), list) for key in ("startMm", "endMm")):
        return (kind, tuple(item["startMm"]), tuple(item["endMm"]))
    if kind == "arc" and all(isinstance(item.get(key), list) for key in ("startMm", "endMm", "centerMm")):
        return (kind, tuple(item["startMm"]), tuple(item["endMm"]), tuple(item["centerMm"]),
                bool(item.get("clockwise")))
    return None


def region_paths(item: dict[str, Any], anchor: tuple[float, float]) -> list[list[Any]]:
    """Convert Gerber region contours into EasyEDA single-polygon paths."""
    paths: list[list[Any]] = []
    for contour in item.get("contours") or []:
        if not contour or any(segment.get("kind") != "line" for segment in contour):
            raise ValueError(f"only line-segment Gerber regions are supported: {item!r}")
        first = contour[0].get("startMm")
        if not isinstance(first, list):
            raise ValueError(f"Gerber region contour has no start point: {item!r}")
        x, y = pcb_point(first, anchor)
        path: list[Any] = [x, y]
        current = (x, y)
        for segment in contour:
            start = segment.get("startMm")
            end = segment.get("endMm")
            if not isinstance(start, list) or not isinstance(end, list):
                raise ValueError(f"Gerber region segment lacks endpoints: {segment!r}")
            start_point = pcb_point(start, anchor)
            if start_point != current:
                path.extend(["L", start_point[0], start_point[1]])
            end_point = pcb_point(end, anchor)
            path.extend(["L", end_point[0], end_point[1]])
            current = end_point
        paths.append(path)
    return paths


def build_footprint(base: str, component: dict[str, Any], gerber: dict[str, Any],
                    mechanical_holes: Sequence[dict[str, Any]]) -> tuple[str, str, dict[str, Any], list[str]]:
    latest = component.get("latestSchematic") or {}
    footprint_name = str(latest.get("footprint") or base)
    uuid = stable_id("footprint", base)
    doc = NativeDocument("FOOTPRINT", uuid, f"{base}_{footprint_name}")
    add_footprint_layers(doc)
    doc.add("META", {"title": f"{base}_{footprint_name}",
        "description": "Per-reference geometry reconstructed from the archived 260616 Gerber; verify against the new PCB.",
        "tags": ["GERBER_RECONSTRUCTION", "REV_260616"], "source": doc_source(uuid)}, "META")
    doc.add("CANVAS", {"originX": 0, "originY": 0, "unit": "mm", "gridXSize": 10, "gridYSize": 10,
        "snapXSize": 0.03937, "snapYSize": 0.03937, "altSnapXSize": 0.1, "altSnapYSize": 0.1,
        "gridType": "NONE", "multiGridType": "NONE", "multiGridRatio": 10, "highlightValue": 0.5,
        "layerBrightness": "NORMAL"}, "CANVAS")
    doc.add("ACTIVE_LAYER", {"layerId": 1}, "ACTIVE_LAYER")
    anchor = footprint_anchor(component)
    side = str(component.get("sideHint") or "F")
    problems: list[str] = []
    pad_manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pad_number, pad in sorted((component.get("pads") or {}).items(), key=lambda item: natural_key(item[0])):
        pad_number = str(pad.get("number") or pad_number).strip()
        if not pad_number:
            problems.append(f"{base}: footprint pad without number")
            continue
        if pad_number in seen:
            problems.append(f"{base}: duplicate footprint pad {pad_number}")
            continue
        seen.add(pad_number)
        flash = preferred_flash(pad, side)
        if not flash or not isinstance(flash.get("atMm"), list):
            problems.append(f"{base}: pad {pad_number} has no copper flash")
            continue
        x, y = pcb_point(flash["atMm"], anchor)
        hole, plated, hole_angle = pad_hole(flash)
        layer = 12 if hole else (2 if str(flash.get("layer")) == "B.Cu" else 1)
        shape, pad_angle, aperture_template = pad_shape(gerber, flash)
        shape = place_polygon_pad_path(shape, x, y, pad_angle)
        special_pad = layered_thermal_special_pad(
            base, pad_number, pad, flash, shape, hole, plated, layer
        )
        unused_inner_layers = pad_unused_inner_layers(base, pad_number, hole, plated, layer)
        # J1's fourteen signal pads have exact Gerber mask/paste flashes equal
        # to their copper apertures.  Use zero expansion instead of an unknown
        # project rule; the additional shield paste windows are emitted below
        # from their original dark regions.
        exact_j1_top_openings = base == "J1" and hole is None and layer == 1
        doc.primitive("PAD", {
            "groupId": 0, "netName": "", "layerId": layer, "num": pad_number, "centerX": x, "centerY": y,
            "padAngle": pad_angle, "hole": hole, "defaultPad": shape, "specialPad": special_pad, "padOffsetX": 0, "padOffsetY": 0,
            "relativeAngle": hole_angle, "plated": plated, "padType": "NORMAL", "topSolderExpansion": None,
            "bottomSolderExpansion": None, "topPasteExpansion": None, "bottomPasteExpansion": None,
            "locked": False, "zIndex": len(pad_manifest) + 1, "connectMode": None, "spokeSpace": None,
            "spokeWidth": None, "spokeAngle": None, "unusedInnerLayers": unused_inner_layers,
            "padLen": 0, "propagationDelay": 0,
        })
        if exact_j1_top_openings:
            pad_record = doc.records[-1][1]
            pad_record["topSolderExpansion"] = 0
            pad_record["topPasteExpansion"] = 0
        pad_manifest.append({"number": pad_number, "x": x, "y": y, "layer": layer, "shape": shape, "hole": hole,
                             "special_pad": special_pad,
                             "unused_inner_layers": unused_inner_layers,
                             "pad_angle": pad_angle, "hole_angle": hole_angle, "aperture_template": aperture_template,
                             "exact_j1_top_openings": exact_j1_top_openings,
                             "net_old": pad.get("netOld"), "pin_function_old": pad.get("pinFunctionOld")})

    duplicate_flash_pads = add_duplicate_flash_pads(
        doc, base, component, gerber, anchor, side, pad_manifest
    )
    owned_thermal_pths = add_owned_thermal_pths(doc, base, anchor, pad_manifest)

    mechanical_hole_manifest: list[dict[str, Any]] = []
    for hole_index, mechanical_hole in enumerate(mechanical_holes, 1):
        at = mechanical_hole.get("atMm")
        diameter_mm = num(mechanical_hole.get("diameterMm"))
        if not isinstance(at, list) or len(at) < 2 or diameter_mm <= 0:
            problems.append(f"{base}: invalid component mechanical NPTH evidence {mechanical_hole!r}")
            continue
        x, y = pcb_point(at, anchor)
        diameter = rounded(diameter_mm * MM_TO_MIL)
        doc.primitive("PAD", {
            "groupId": 0, "netName": "", "layerId": 12, "num": "", "centerX": x, "centerY": y,
            "padAngle": 0, "hole": {"holeType": "ROUND", "width": diameter, "height": diameter},
            "defaultPad": {"padType": "ELLIPSE", "width": diameter, "height": diameter},
            "specialPad": [], "padOffsetX": 0, "padOffsetY": 0, "relativeAngle": 0,
            "plated": False, "padType": "NORMAL", "topSolderExpansion": None,
            "bottomSolderExpansion": None, "topPasteExpansion": None, "bottomPasteExpansion": None,
            "locked": False, "zIndex": len(pad_manifest) + hole_index, "connectMode": None,
            "spokeSpace": None, "spokeWidth": None, "spokeAngle": None, "unusedInnerLayers": [], "padLen": 0,
            "propagationDelay": 0,
        })
        if base == "J1":
            # Both Gerber mask flashes equal the 1.02 mm NPTH drill.  Preserve
            # that exact zero expansion; the additional bottom-mask rings are
            # emitted as their four original ARC primitives below.
            pad_record = doc.records[-1][1]
            pad_record["topSolderExpansion"] = 0
            pad_record["bottomSolderExpansion"] = 0
        mechanical_hole_manifest.append({
            "number": "", "x": x, "y": y, "diameter_mm": diameter_mm, "plated": False,
            "source_at_mm": at, "ownership": mechanical_hole.get("ownership"),
            "ownership_evidence": mechanical_hole.get("ownershipEvidence") or [],
        })

    explicit_regions: list[dict[str, Any]] = []
    layer_geometry = component.get("layerGeometry") or {}
    for gerber_layer, layer_id in (("F.SilkS", 3), ("B.SilkS", 4)):
        items = layer_geometry.get(gerber_layer, [])
        region_boundaries = {
            key
            for region in items if region.get("kind") == "region"
            for contour in (region.get("contours") or [])
            for segment in contour
            if (key := geometry_key(segment)) is not None
        }
        for item in items:
            kind = item.get("kind")
            if kind == "region":
                if str(item.get("polarity") or "dark").lower() != "dark":
                    problems.append(f"{base}: clear Gerber region cannot be represented as an additive footprint fill")
                    continue
                paths = region_paths(item, anchor)
                doc.primitive("FILL", {"partitionId": None, "groupId": 0, "locked": False,
                    "zIndex": len(doc.records), "netName": "", "layerId": layer_id, "width": 0,
                    "fillStyle": "SOLID", "path": paths, "isBridgingCopper": False,
                    "networkList": [], "refs": []})
                explicit_regions.append({"layer": gerber_layer, "layer_id": layer_id,
                                         "path_count": len(paths), "role": "filled-silkscreen-region"})
                continue
            if geometry_key(item) in region_boundaries:
                # Region contour commands are not independent stroked Gerber
                # primitives; the extractor retains them both for provenance.
                continue
            width = rounded(aperture_width(gerber, gerber_layer, str(item.get("aperture") or "")))
            if kind == "line" and isinstance(item.get("startMm"), list) and isinstance(item.get("endMm"), list):
                start, end = pcb_point(item["startMm"], anchor), pcb_point(item["endMm"], anchor)
                doc.primitive("LINE", {"groupId": 0, "netName": "", "layerId": layer_id, "startX": start[0],
                    "startY": start[1], "endX": end[0], "endY": end[1], "width": width, "locked": False,
                    "zIndex": len(doc.records)})
            elif kind == "arc" and all(isinstance(item.get(k), list) for k in ("startMm", "endMm", "centerMm")):
                start, end = pcb_point(item["startMm"], anchor), pcb_point(item["endMm"], anchor)
                angle = rounded(arc_angle_deg(item["startMm"], item["endMm"], item["centerMm"], bool(item.get("clockwise"))))
                doc.primitive("ARC", {"groupId": 0, "netName": "", "layerId": layer_id, "startX": start[0],
                    "startY": start[1], "endX": end[0], "endY": end[1], "angle": angle, "width": width,
                    "arcType": "DOT", "locked": False, "zIndex": len(doc.records)})

    # J1 carries ten dark F.Paste shield windows that do not correspond to
    # numbered electrical pads.  Preserve them as exact project-local fills.
    for item in layer_geometry.get("F.Paste", []):
        kind = item.get("kind")
        if kind not in ("line", "region"):
            continue
        if base != "J1" or str(item.get("polarity") or "dark").lower() != "dark":
            problems.append(f"{base}: unexpected footprint paste {kind} in Gerber evidence")
            continue
        if kind == "line":
            if not isinstance(item.get("startMm"), list) or not isinstance(item.get("endMm"), list):
                problems.append(f"{base}: paste line lacks endpoints")
                continue
            start, end = pcb_point(item["startMm"], anchor), pcb_point(item["endMm"], anchor)
            width = rounded(aperture_width(gerber, "F.Paste", str(item.get("aperture") or "")))
            doc.primitive("LINE", {"groupId": 0, "netName": "", "layerId": 7,
                "startX": start[0], "startY": start[1], "endX": end[0], "endY": end[1],
                "width": width, "locked": False, "zIndex": len(doc.records)})
            explicit_regions.append({"layer": "F.Paste", "layer_id": 7,
                                     "path_count": 0, "role": "J1-shield-paste-boundary-line"})
        else:
            paths = region_paths(item, anchor)
            doc.primitive("FILL", {"partitionId": None, "groupId": 0, "locked": False,
                "zIndex": len(doc.records), "netName": "", "layerId": 7, "width": 0,
                "fillStyle": "SOLID", "path": paths, "isBridgingCopper": False,
                "networkList": [], "refs": []})
            explicit_regions.append({"layer": "F.Paste", "layer_id": 7,
                                     "path_count": len(paths), "role": "J1-shield-paste-window"})

    for item in layer_geometry.get("B.Mask", []):
        if item.get("kind") != "arc":
            continue
        if base != "J1" or not all(isinstance(item.get(key), list) for key in ("startMm", "endMm", "centerMm")):
            problems.append(f"{base}: unexpected bottom-mask arc in Gerber evidence")
            continue
        start, end = pcb_point(item["startMm"], anchor), pcb_point(item["endMm"], anchor)
        width = rounded(aperture_width(gerber, "B.Mask", str(item.get("aperture") or "")))
        angle = rounded(arc_angle_deg(item["startMm"], item["endMm"], item["centerMm"], bool(item.get("clockwise"))))
        doc.primitive("ARC", {"groupId": 0, "netName": "", "layerId": 6,
            "startX": start[0], "startY": start[1], "endX": end[0], "endY": end[1],
            "angle": angle, "width": width, "arcType": "DOT", "locked": False,
            "zIndex": len(doc.records)})
        explicit_regions.append({"layer": "B.Mask", "layer_id": 6,
                                 "path_count": 0, "role": "J1-bottom-mask-ring-arc"})
    info = {"uuid": uuid, "title": f"{base}_{footprint_name}", "base_reference": base,
            "schematic_footprint": footprint_name, "gerber_revision": component.get("gerberRevision"),
            "side_hint": side, "anchor_mm": list(anchor), "pads": pad_manifest,
            "duplicate_flash_pads": duplicate_flash_pads,
            "owned_thermal_pths": owned_thermal_pths,
            "mechanical_npth": mechanical_hole_manifest, "explicit_regions": explicit_regions,
            "coordinate_transform": "x=(sourceX-anchorX)*39.37007874; y=(sourceY-anchorY)*39.37007874; native Y-up"}
    return uuid, doc.source(), info, problems


def designator_for(reference: str) -> str:
    match = re.match(r"([^0-9]+)", reference)
    return (match.group(1) if match else "U") + "?"


def build_device(base: str, components: list[dict[str, Any]], symbol_uuid: str, footprint_uuid: str | None) -> tuple[str, str, dict[str, Any]]:
    component = components[0]
    value = str(component.get("value") or base)
    uuid = stable_id("device", base)
    title = f"{base}_{value}"
    doc = NativeDocument("DEVICE", uuid, title)
    is_power = all(bool(c.get("is_power_symbol")) for c in components)
    is_power_driver = is_power and all(is_power_driver_component(c) for c in components)
    is_net_flag = is_power
    dnp = any(bool(c.get("dnp")) for c in components)
    attributes = {
        "Convert to PCB": "yes" if footprint_uuid else "no",
        "Add into BOM": "no" if (is_power or dnp) else "yes",
        "Designator": designator_for(base), "Symbol": symbol_uuid, "Value": value, "Name": "={Value}",
        "Description": field(component, "Description"), "Part Number": field(component, "Part Number", "MPN"),
        "Package": field(component, "Package"), "DNP": "yes" if dnp else "no",
    }
    if footprint_uuid:
        attributes["Footprint"] = footprint_uuid
        attributes["Supplier Footprint"] = str(component.get("footprint") or "")
    doc.add("META", {"title": title, "tags": ["STM32H747_MCU_BOARD_v19", "PROJECT_LOCAL"],
        "source": doc_source(uuid), "images": [""], "attributes": attributes}, "META")
    return uuid, doc.source(), {
        "uuid": uuid, "title": title, "base_reference": base, "attributes": attributes,
        "is_power_symbol": is_power, "is_net_flag": is_net_flag,
        "is_power_driver": is_power_driver,
    }


def instance_record(component: dict[str, Any], symbol: dict[str, Any], footprint: dict[str, Any] | None,
                    device: dict[str, Any]) -> dict[str, Any]:
    part_id = str(component.get("_native_part_id") or component.get("unit") or "A")
    part_transform = (symbol.get("part_transforms") or {}).get(part_id) or {}
    raw_part_origin = part_transform.get("raw_part_origin_easyeda") or [0, 0]
    origin = point_from_local(component.get("origin_easyeda")) or (0.0, 0.0)
    placement = [rounded(origin[0] + num(raw_part_origin[0])), rounded(origin[1] + num(raw_part_origin[1]))]
    is_power_symbol = bool(component.get("is_power_symbol"))
    is_net_flag = bool(symbol.get("is_net_flag"))
    is_power_driver = bool(symbol.get("is_power_driver"))
    semantic_pins = component.get("pins") or []
    actual_power_net = semantic_pins[0].get("net") if is_power_symbol and semantic_pins else None
    global_net_name = actual_power_net if is_net_flag else None
    return {
        "page": component.get("_pdf_page"), "sheet_index": component.get("_sheet_index"),
        "sheet_name": component.get("_sheet_name"), "reference": component.get("reference"),
        "base_reference": component.get("base_reference"), "subpart": component.get("unit") or "A",
        "native_part_id": part_id,
        "value": component.get("value"), "footprint": component.get("footprint"),
        "component_bbox": component.get("bbox"), "origin_easyeda": component.get("origin_easyeda"),
        "raw_part_origin_easyeda": raw_part_origin, "placement_easyeda": placement,
        "owned_vector_orders": part_transform.get("owned_vector_orders", []),
        "is_power_symbol": is_power_symbol, "is_net_flag": is_net_flag,
        "is_power_driver": is_power_driver, "global_net_name": global_net_name,
        "power_driver_net": actual_power_net if is_power_driver else None,
        "dnp": bool(component.get("dnp")), "symbol_uuid": symbol["uuid"],
        "footprint_uuid": footprint["uuid"] if footprint else None, "device_uuid": device["uuid"],
    }


def validate_link(base: str, symbol: dict[str, Any], footprint: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    symbol_pins = {p["number"] for p in symbol.get("pins", []) if p.get("number")}
    hidden_nc_pins = {p["number"] for p in symbol.get("hidden_intrinsic_nc_pins", []) if p.get("number")}
    if not symbol_pins:
        errors.append(f"{base}: symbol has no numbered pins")
    if footprint:
        pad_numbers = {p["number"] for p in footprint.get("pads", []) if p.get("number")}
        if not pad_numbers:
            errors.append(f"{base}: footprint has no numbered pads")
        missing_pads = sorted(symbol_pins - pad_numbers, key=natural_key)
        missing_pins = sorted(pad_numbers - symbol_pins - hidden_nc_pins, key=natural_key)
        if missing_pads:
            errors.append(f"{base}: symbol pins without footprint pads: {', '.join(missing_pads[:30])}")
        if missing_pins:
            errors.append(f"{base}: footprint pads without symbol pins: {', '.join(missing_pins[:30])}")
    else:
        warnings.append(f"{base}: no Gerber footprint; schematic-only device")
    return errors, warnings


def require_safe_generated_path(path: Path, label: str) -> Path:
    """Return a resolved path only when it is below this board's output tree."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ALLOWED_OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"{label} must be a strict descendant of {ALLOWED_OUTPUT_ROOT}; got {resolved}"
        ) from exc
    if not relative.parts:
        raise ValueError(f"{label} cannot be the board output root itself: {resolved}")
    return resolved


def remove_generated_tree(path: Path, *, ignore_errors: bool = False) -> None:
    """Remove one generated directory after resolving and bounding its target."""
    safe = require_safe_generated_path(path, "generated directory removal target")
    if safe.exists():
        if safe.is_symlink() or not safe.is_dir():
            raise ValueError(f"refusing recursive removal of non-directory target: {safe}")
        shutil.rmtree(safe, ignore_errors=ignore_errors)


def atomic_replace_directory(staging: Path, destination: Path) -> None:
    staging = require_safe_generated_path(staging, "staging directory")
    destination = require_safe_generated_path(destination, "output directory")
    backup = destination.with_name(destination.name + ".previous")
    backup = require_safe_generated_path(backup, "backup directory")
    if backup.exists():
        remove_generated_tree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staging.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        remove_generated_tree(backup)


def build(args: argparse.Namespace) -> int:
    schematic_path = args.schematic.resolve()
    gerber_path = args.gerber.resolve()
    pdf_path = args.pdf.resolve()
    output_path = require_safe_generated_path(args.output, "output directory")
    schematic = json.loads(schematic_path.read_text(encoding="utf-8"))
    gerber = json.loads(gerber_path.read_text(encoding="utf-8"))
    groups, all_instances = component_groups(schematic)
    vector_assignment = assign_pdf_vectors(groups, pdf_path)
    gerber_components = gerber.get("components") or {}
    mechanical_holes_by_ref, board_mounting_holes = gerber_npth_inventory(gerber)

    staging_parent = output_path.parent
    staging_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output_path.name + ".staging-", dir=staging_parent))
    symbols_dir, footprints_dir, devices_dir = staging / "symbols", staging / "footprints", staging / "devices"
    symbols_dir.mkdir(); footprints_dir.mkdir(); devices_dir.mkdir()

    errors: list[str] = []
    warnings: list[str] = []
    symbol_infos: dict[str, dict[str, Any]] = {}
    footprint_infos: dict[str, dict[str, Any]] = {}
    device_infos: dict[str, dict[str, Any]] = {}
    symbol_sources: list[str] = []
    footprint_sources: list[str] = []
    device_sources: list[str] = []
    instance_manifest: list[dict[str, Any]] = []
    try:
        for base in sorted(groups, key=natural_key):
            uuid, source, info, problems = build_symbol(base, groups[base], args.symbol_y_axis)
            symbol_infos[base] = info
            errors.extend(problems)
            symbol_sources.append(source)
            (symbols_dir / f"{clean_name(base)}_{uuid}.esym").write_text(source, encoding="utf-8", newline="\n")

        for base in sorted(gerber_components, key=natural_key):
            if base not in groups:
                continue
            component = gerber_components[base]
            if not component.get("presentInLatest", True):
                continue
            uuid, source, info, problems = build_footprint(
                base, component, gerber, mechanical_holes_by_ref.get(base, [])
            )
            footprint_infos[base] = info
            errors.extend(problems)
            footprint_sources.append(source)
            (footprints_dir / f"{clean_name(base)}_{uuid}.efoo").write_text(source, encoding="utf-8", newline="\n")

        footprint_geometry_audit = {
            "roundrect_pads": sum(
                pad.get("aperture_template") == "RoundRect"
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "outline5p_polygon_pads": sum(
                pad.get("aperture_template") == "Outline5P"
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "obround_capsules_as_rect_radius_100": sum(
                pad.get("aperture_template") in ("O", "OBROUND")
                and pad.get("shape", {}).get("padType") == "RECT"
                and pad.get("shape", {}).get("radius") == 100
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "plated_routed_slot_pads": sum(
                (pad.get("hole") or {}).get("holeType") == "SLOT"
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "layered_thermal_special_pads": sum(
                len(pad.get("special_pad") or []) == 3
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "owned_thermal_pth_pads": sum(
                pad.get("role") == "Gerber/Excellon component-owned thermal PTH"
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "duplicate_flash_physical_pads": sum(
                pad.get("role") == "Gerber duplicate-number physical pad"
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "unused_inner_layer_pad_overrides": sum(
                bool(pad.get("unused_inner_layers"))
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "j1_zero_expansion_signal_pads": sum(
                bool(pad.get("exact_j1_top_openings"))
                for info in footprint_infos.values() for pad in info.get("pads", [])
            ),
            "filled_silkscreen_regions": sum(
                region.get("role") == "filled-silkscreen-region"
                for info in footprint_infos.values() for region in info.get("explicit_regions", [])
            ),
            "j1_shield_paste_windows": sum(
                region.get("role") == "J1-shield-paste-window"
                for info in footprint_infos.values() for region in info.get("explicit_regions", [])
            ),
            "j1_shield_paste_boundary_lines": sum(
                region.get("role") == "J1-shield-paste-boundary-line"
                for info in footprint_infos.values() for region in info.get("explicit_regions", [])
            ),
            "j1_bottom_mask_ring_arcs": sum(
                region.get("role") == "J1-bottom-mask-ring-arc"
                for info in footprint_infos.values() for region in info.get("explicit_regions", [])
            ),
            "j1_exact_mask_npth": sum(
                info.get("base_reference") == "J1" and hole.get("plated") is False
                for info in footprint_infos.values() for hole in info.get("mechanical_npth", [])
            ),
        }
        expected_geometry_audit = {
            "roundrect_pads": 115,
            "outline5p_polygon_pads": 8,
            "obround_capsules_as_rect_radius_100": 13,
            "plated_routed_slot_pads": 13,
            "layered_thermal_special_pads": 2,
            "owned_thermal_pth_pads": 8,
            "duplicate_flash_physical_pads": 50,
            "unused_inner_layer_pad_overrides": 80,
            "j1_zero_expansion_signal_pads": 14,
            "filled_silkscreen_regions": 1,
            "j1_shield_paste_windows": 10,
            "j1_shield_paste_boundary_lines": 40,
            "j1_bottom_mask_ring_arcs": 4,
            "j1_exact_mask_npth": 2,
        }
        if footprint_geometry_audit != expected_geometry_audit:
            errors.append(
                f"special footprint geometry counts differ from Gerber audit: "
                f"{footprint_geometry_audit!r} != {expected_geometry_audit!r}"
            )

        for base in sorted(groups, key=natural_key):
            footprint_uuid = footprint_infos.get(base, {}).get("uuid")
            uuid, source, info = build_device(base, groups[base], symbol_infos[base]["uuid"], footprint_uuid)
            device_infos[base] = info
            device_sources.append(source)
            (devices_dir / f"{clean_name(base)}_{uuid}.edevice").write_text(source, encoding="utf-8", newline="\n")
            link_errors, link_warnings = validate_link(base, symbol_infos[base], footprint_infos.get(base))
            if all(bool(c.get("is_power_symbol")) for c in groups[base]):
                link_errors = [e for e in link_errors if "no numbered pins" not in e]
                link_warnings = [w for w in link_warnings if "schematic-only" not in w]
            errors.extend(link_errors)
            warnings.extend(link_warnings)
            for component in groups[base]:
                instance_manifest.append(instance_record(component, symbol_infos[base], footprint_infos.get(base), info))

        # Native project import order required by EasyEDA Pro: SYMBOL -> FOOTPRINT -> DEVICE.
        bundle = "".join(symbol_sources + footprint_sources + device_sources)
        (staging / "embedded-library.epru").write_text(bundle, encoding="utf-8", newline="\n")
        write_json(staging / "devices.json", {"schemaVersion": 1, "instances": instance_manifest})
        manifest = {
            "schema": FORMAT_NAME, "schema_version": FORMAT_VERSION, "editor_compatibility": EDITOR_VERSION,
            "project": "STM32H747_MCU_BOARD_v19",
            "inputs": {
                "schematic": {"path": str(schematic_path), "sha256": sha256_file(schematic_path),
                              "authority": "MCU_BOARD_v19_260827.pdf"},
                "pdf": {"path": str(pdf_path), "sha256": sha256_file(pdf_path),
                        "role": "authoritative exact visible symbol vectors for pages 2-6"},
                "gerber": {"path": str(gerber_path), "sha256": sha256_file(gerber_path),
                           "role": "old 260616 geometry reference only"},
            },
            "pdf_vector_assignment": vector_assignment,
            "semantic_porting_notes": [
                {
                    "source": "KiCad PWR_FLAG (#FLG)",
                    "target": "EasyEDA Pro NET_FLAG (docType 18) with OUT pin and Global Net Name",
                    "instances": 7,
                    "reason": (
                        "EasyEDA Pro 3.2.206 applies missing-footprint ERC to ordinary components even when "
                        "Convert to PCB is no; NET_FLAG preserves the actual global net without a fabricated footprint"
                    ),
                    "preserved_metadata": ["is_power_driver", "power_driver_net", "original PDF vector appearance"],
                }
            ],
            "native_record_order": ["SYMBOL", "FOOTPRINT", "DEVICE"],
            "native_cache_identity": {
                "uuid_policy": "stable per document kind and base reference",
                "version_policy": "content SHA-256 bucket within a monotonic generator epoch",
                "version_epoch": NATIVE_CACHE_VERSION_EPOCH,
                "version_width": NATIVE_CACHE_VERSION_WIDTH,
                "reason": "force EasyEDA project-local import to refresh changed native documents without breaking UUID references",
            },
            "counts": {"schematic_instances": len(all_instances), "physical_base_references": len(footprint_infos),
                       "symbols": len(symbol_infos), "footprints": len(footprint_infos), "devices": len(device_infos),
                       "net_flag_symbols": sum(bool(info.get("is_net_flag")) for info in symbol_infos.values()),
                       "power_driver_symbols": sum(bool(info.get("is_power_driver")) for info in symbol_infos.values()),
                       "net_flag_instances": sum(bool(item.get("is_net_flag")) for item in instance_manifest),
                       "power_driver_instances": sum(bool(item.get("is_power_driver")) for item in instance_manifest),
                       "component_mechanical_npth": sum(
                           len(info.get("mechanical_npth", [])) for info in footprint_infos.values()
                       ), "board_mounting_npth_deferred_to_pcb": len(board_mounting_holes)},
            "symbols": symbol_infos, "footprints": footprint_infos, "devices": device_infos,
            "footprint_geometry_audit": footprint_geometry_audit,
            "board_mounting_npth": board_mounting_holes,
            "validation": {
                "strict": not args.allow_incomplete, "errors": errors, "warnings": warnings,
                "manufacturing_ready": False,
                "reason": "Footprints come from an older Gerber and require schematic-to-PCB regeneration, ERC/DRC and netlist verification.",
            },
            "limitations": gerber.get("limitations", []), "latest_patches": gerber.get("latestPatches", {}),
        }
        write_json(staging / "manifest.json", manifest)
        write_json(staging / "validation.json", manifest["validation"])
        atomic_replace_directory(staging, output_path)
    except Exception:
        remove_generated_tree(staging, ignore_errors=True)
        raise

    print(json.dumps({"output": str(output_path), "symbols": len(symbol_infos), "footprints": len(footprint_infos),
                      "devices": len(device_infos), "errors": len(errors), "warnings": len(warnings)}, ensure_ascii=False))
    if errors and not args.allow_incomplete:
        print("Strict validation failed; outputs were retained for inspection. Use --allow-incomplete only for a draft import.", file=sys.stderr)
        return 2
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic project-local EasyEDA Pro native library documents.")
    parser.add_argument("--schematic", type=Path, default=DEFAULT_SCHEMATIC, help="schematic-pages-2-6.json")
    parser.add_argument("--gerber", type=Path, default=DEFAULT_GERBER, help="gerber-component-footprints.json")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="authoritative schematic PDF for exact vectors")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="output directory")
    parser.add_argument("--symbol-y-axis", choices=("down", "up"), default="down",
                        help="raw symbol coordinate convention (3.2.206 portable-source default: down)")
    parser.add_argument("--allow-incomplete", action="store_true",
                        help="return success despite unresolved/unknown pin-to-pad mappings; manifest remains non-ready")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return build(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
