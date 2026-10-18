#!/usr/bin/env python3
"""Read-only drill audit for a diagnostic EasyEDA Gerber ZIP.

The candidate ZIP is compared one-to-one with the authoritative June drill
inventory stored in ``output/semantic/gerber-component-footprints.json``.
The comparison covers every round drill and routed slot, including positions,
tool diameters, and slot endpoints.  A single translation plus one of the eight
axis-preserving/reflection transforms is inferred so that harmless Gerber-origin
and Y-axis-convention differences do not hide real geometry differences.

This tool is deliberately diagnostic only.  A passing report is never a
manufacturing approval.  It does not call EasyEDA or modify a project.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = ROOT / "output/semantic/gerber-component-footprints.json"
DEFAULT_SOURCE_ZIP = ROOT / "보드 자료/MCU_BOARD_v19_260616_Gerber.zip"
DEFAULT_REPORT = ROOT / "output/validation/native-diagnostic-gerber-drill-audit.json"

DEFAULT_POSITION_TOLERANCE_MM = 0.002
DEFAULT_SIZE_TOLERANCE_MM = 0.002
MAX_DRILL_MEMBER_BYTES = 20 * 1024 * 1024

EXPECTED_BOARD_PROFILE = {
    "pth_round": 767,
    "pth_slot": 13,
    "npth_round": 13,
    "npth_slot": 0,
}
EXPECTED_PTH_SEMANTICS = {"via": 634, "component": 133}

COORD_RE = re.compile(r"([XY])([+-]?(?:\d+(?:\.\d*)?|\.\d+))", re.IGNORECASE)
TOOL_DEF_RE = re.compile(
    r"^T(?P<tool>\d+)C(?P<diameter>[+-]?(?:\d+(?:\.\d*)?|\.\d+))",
    re.IGNORECASE,
)
TOOL_SELECT_RE = re.compile(r"^T(\d+)$", re.IGNORECASE)
FORMAT_RE = re.compile(r"(?:FILE_FORMAT|FORMAT)\s*[=:]\s*(\d+)\s*[:.]\s*(\d+)", re.I)
UNIT_FORMAT_RE = re.compile(r"\b(?:METRIC|INCH)[^\r\n]*?(\d+)\.(\d+)\b", re.I)


class AuditError(RuntimeError):
    """Input is unsafe, unsupported, or internally inconsistent."""


@dataclass(frozen=True)
class NumberFormat:
    unit: str
    integer_digits: int | None
    decimal_digits: int | None
    zero_suppression: str | None

    @property
    def factor_to_mm(self) -> float:
        return 25.4 if self.unit == "inch" else 1.0


@dataclass
class Tool:
    name: str
    diameter_mm: float
    function: str | None


@dataclass
class DrillItem:
    kind: str
    center_mm: tuple[float, float]
    diameter_mm: float
    plated_class: str
    function: str | None
    member: str
    line: int
    tool: str
    start_mm: tuple[float, float] | None = None
    end_mm: tuple[float, float] | None = None

    @property
    def category(self) -> str:
        return f"{self.plated_class}_{self.kind}"

    @property
    def centerline_length_mm(self) -> float:
        if self.kind != "slot" or self.start_mm is None or self.end_mm is None:
            return 0.0
        return math.dist(self.start_mm, self.end_mm)

    @property
    def semantic(self) -> str | None:
        text = (self.function or "").lower()
        if "viadrill" in text:
            return "via"
        if "componentdrill" in text:
            return "component"
        return None


@dataclass(frozen=True)
class Transform:
    name: str
    matrix: tuple[tuple[int, int], tuple[int, int]]
    offset_mm: tuple[float, float]

    def point(self, point: Sequence[float]) -> tuple[float, float]:
        (a, b), (c, d) = self.matrix
        return (
            a * float(point[0]) + b * float(point[1]) + self.offset_mm[0],
            c * float(point[0]) + d * float(point[1]) + self.offset_mm[1],
        )


ORTHOGONAL_MATRICES: tuple[tuple[str, tuple[tuple[int, int], tuple[int, int]]], ...] = (
    ("identity", ((1, 0), (0, 1))),
    ("reflect-x", ((-1, 0), (0, 1))),
    ("reflect-y", ((1, 0), (0, -1))),
    ("rotate-180", ((-1, 0), (0, -1))),
    ("swap-xy", ((0, 1), (1, 0))),
    ("rotate-90", ((0, -1), (1, 0))),
    ("rotate-270", ((0, 1), (-1, 0))),
    ("swap-neg-xy", ((0, -1), (-1, 0))),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuditError(f"{label}: invalid number {value!r}") from exc
    if not math.isfinite(result):
        raise AuditError(f"{label}: non-finite number {value!r}")
    return result


def round_clean(value: float, digits: int = 9) -> int | float:
    result = round(float(value), digits)
    if result == 0:
        return 0
    return int(result) if result.is_integer() else result


def decode_ascii(data: bytes, member: str) -> str:
    if b"\x00" in data:
        raise AuditError(f"{member}: NUL byte found; not a text Excellon member")
    for encoding in ("utf-8-sig", "ascii", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise AuditError(f"{member}: cannot decode Excellon text")


def detect_number_format(lines: Sequence[str], member: str) -> NumberFormat:
    unit: str | None = None
    zero_suppression: str | None = None
    integer_digits: int | None = None
    decimal_digits: int | None = None

    for raw in lines:
        upper = raw.upper()
        if re.search(r"(?:^|[^A-Z])METRIC(?:[^A-Z]|$)", upper) or "M71" in upper:
            unit = "metric"
        if re.search(r"(?:^|[^A-Z])INCH(?:[^A-Z]|$)", upper) or "M72" in upper:
            unit = "inch"
        if re.search(r"(?:METRIC|INCH)\s*,\s*LZ\b", upper):
            zero_suppression = "LZ"
        elif re.search(r"(?:METRIC|INCH)\s*,\s*TZ\b", upper):
            zero_suppression = "TZ"
        match = FORMAT_RE.search(upper)
        if match:
            integer_digits, decimal_digits = int(match.group(1)), int(match.group(2))
        elif (match := UNIT_FORMAT_RE.search(upper)):
            integer_digits = len(match.group(1))
            decimal_digits = len(match.group(2))

    if unit is None:
        raise AuditError(f"{member}: missing METRIC/INCH (or M71/M72) declaration")
    return NumberFormat(unit, integer_digits, decimal_digits, zero_suppression)


def parse_coordinate_number(raw: str, fmt: NumberFormat, member: str, line: int) -> float:
    if "." in raw:
        value = finite(raw, f"{member}:{line}")
    else:
        if fmt.integer_digits is None or fmt.decimal_digits is None:
            raise AuditError(
                f"{member}:{line}: implicit coordinate {raw!r} has no FILE_FORMAT declaration"
            )
        sign = -1.0 if raw.startswith("-") else 1.0
        digits = raw.lstrip("+-")
        width = fmt.integer_digits + fmt.decimal_digits
        if len(digits) > width:
            raise AuditError(f"{member}:{line}: coordinate {raw!r} exceeds {width} digits")
        if fmt.zero_suppression == "TZ":
            digits = digits.ljust(width, "0")
        else:
            # LZ and unspecified suppression both use the conventional
            # right-aligned fixed-point interpretation.
            digits = digits.rjust(width, "0")
        value = sign * int(digits) / (10**fmt.decimal_digits)
    return value * fmt.factor_to_mm


def coordinate_groups(text: str) -> list[list[tuple[str, str]]]:
    """Split ordered X/Y words when an axis repeats (used by G85 dialects)."""
    result: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    used: set[str] = set()
    for match in COORD_RE.finditer(text):
        axis, value = match.group(1).upper(), match.group(2)
        if axis in used:
            result.append(current)
            current = []
            used = set()
        current.append((axis, value))
        used.add(axis)
    if current:
        result.append(current)
    return result


def target_from_words(
    words: Sequence[tuple[str, str]],
    base: tuple[float, float],
    fmt: NumberFormat,
    absolute: bool,
    member: str,
    line: int,
) -> tuple[float, float]:
    values = {
        axis: parse_coordinate_number(raw, fmt, member, line) for axis, raw in words
    }
    if absolute:
        return (values.get("X", base[0]), values.get("Y", base[1]))
    return (base[0] + values.get("X", 0.0), base[1] + values.get("Y", 0.0))


def function_class(function: str | None) -> str | None:
    text = re.sub(r"[\s_-]+", "", (function or "").lower())
    if "nonplated" in text or "npth" in text:
        return "npth"
    if "plated" in text or re.search(r"(?:^|,)pth(?:,|$)", text):
        return "pth"
    return None


def file_name_class(name: str) -> str | None:
    text = Path(name).name.lower().replace("_", "").replace("-", "")
    if "npth" in text or "nonplated" in text:
        return "npth"
    if "pth" in text or "plated" in text:
        return "pth"
    return None


def parse_attribute_payload(line: str, attribute: str) -> str | None:
    match = re.search(rf"\b{re.escape(attribute)}\s*,\s*(.+?)\s*$", line, re.I)
    return match.group(1).strip().rstrip("*") if match else None


def parse_excellon(member: str, data: bytes) -> tuple[list[DrillItem], dict[str, Any]]:
    text = decode_ascii(data, member)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not any(line.strip().upper().startswith("M48") for line in lines[:40]):
        raise AuditError(f"{member}: missing M48 Excellon header")
    fmt = detect_number_format(lines, member)

    file_function: str | None = None
    legacy_type: str | None = None
    pending_tool_function: str | None = None
    tools: dict[str, Tool] = {}
    in_header = True
    for line_number, raw in enumerate(lines, 1):
        stripped = raw.strip().rstrip("*")
        if (payload := parse_attribute_payload(stripped, "TF.FileFunction")) is not None:
            file_function = payload
        if (match := re.search(r"(?:^|;)\s*TYPE\s*=\s*(NON[_ -]?PLATED|PLATED)\b", stripped, re.I)):
            legacy_type = match.group(1)
        if (payload := parse_attribute_payload(stripped, "TA.AperFunction")) is not None:
            pending_tool_function = payload
        match = TOOL_DEF_RE.match(stripped)
        if match:
            tool_name = f"T{int(match.group('tool'))}"
            diameter_mm = finite(match.group("diameter"), f"{member}:{line_number}")
            diameter_mm *= fmt.factor_to_mm
            if tool_name in tools:
                raise AuditError(f"{member}:{line_number}: duplicate tool {tool_name}")
            tools[tool_name] = Tool(tool_name, diameter_mm, pending_tool_function)
            pending_tool_function = None
        if stripped in ("%", "M95"):
            in_header = False
        if not in_header and match:
            raise AuditError(f"{member}:{line_number}: tool definition found after header")
    if not tools:
        raise AuditError(f"{member}: no Excellon tool definitions")

    declared_class = (
        function_class(file_function) or function_class(legacy_type) or file_name_class(member)
    )
    items: list[DrillItem] = []
    current_tool: Tool | None = None
    current = (0.0, 0.0)
    absolute = True
    route_on = False
    header_done = False

    def item_class(tool: Tool, line_number: int) -> str:
        result = function_class(tool.function) or declared_class
        if result not in ("pth", "npth"):
            raise AuditError(
                f"{member}:{line_number}: cannot classify drill as PTH/NPTH from attributes or name"
            )
        return result

    def require_tool(line_number: int) -> Tool:
        if current_tool is None:
            raise AuditError(f"{member}:{line_number}: coordinate occurs before tool selection")
        return current_tool

    def append_round(center: tuple[float, float], line_number: int) -> None:
        tool = require_tool(line_number)
        items.append(
            DrillItem(
                "round",
                center,
                tool.diameter_mm,
                item_class(tool, line_number),
                tool.function,
                member,
                line_number,
                tool.name,
            )
        )

    def append_slot(
        start: tuple[float, float], end: tuple[float, float], line_number: int
    ) -> None:
        tool = require_tool(line_number)
        if math.dist(start, end) <= 1e-12:
            raise AuditError(f"{member}:{line_number}: zero-length routed slot")
        items.append(
            DrillItem(
                "slot",
                ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2),
                tool.diameter_mm,
                item_class(tool, line_number),
                tool.function,
                member,
                line_number,
                tool.name,
                start,
                end,
            )
        )

    for line_number, raw in enumerate(lines, 1):
        line = raw.strip().upper().replace(" ", "").rstrip("*")
        if not line:
            continue
        if line in ("%", "M95"):
            header_done = True
            continue
        if not header_done:
            continue
        if line.startswith(";"):
            continue
        line = re.sub(r"^N\d+", "", line)
        if line in ("M30", "M00"):
            break
        if "R" in line and re.search(r"(?:^|[^A-Z])R\d+", line):
            raise AuditError(f"{member}:{line_number}: repeat drilling is unsupported: {line}")
        if "G02" in line or "G03" in line:
            raise AuditError(f"{member}:{line_number}: arc routing is unsupported: {line}")
        if "G90" in line:
            absolute = True
        if "G91" in line:
            absolute = False
        if line == "M15":
            route_on = True
            continue
        if line == "M16":
            route_on = False
            continue

        if (match := TOOL_SELECT_RE.fullmatch(line)) is not None:
            tool_name = f"T{int(match.group(1))}"
            if tool_name not in tools:
                raise AuditError(f"{member}:{line_number}: undefined tool {tool_name}")
            current_tool = tools[tool_name]
            continue

        if "G85" in line:
            before, after = line.split("G85", 1)
            before_groups = coordinate_groups(before)
            after_groups = coordinate_groups(after)
            if len(before_groups) > 1 or len(after_groups) > 2:
                raise AuditError(f"{member}:{line_number}: unsupported G85 coordinate form: {line}")
            if before_groups:
                start = target_from_words(
                    before_groups[0], current, fmt, absolute, member, line_number
                )
            else:
                start = current
            if len(after_groups) == 2 and not before_groups:
                start = target_from_words(
                    after_groups[0], current, fmt, absolute, member, line_number
                )
                end_words = after_groups[1]
            elif len(after_groups) == 1:
                end_words = after_groups[0]
            else:
                raise AuditError(f"{member}:{line_number}: G85 has no slot endpoint: {line}")
            end = target_from_words(end_words, start, fmt, absolute, member, line_number)
            append_slot(start, end, line_number)
            current = end
            continue

        words = coordinate_groups(line)
        if not words:
            continue
        if len(words) != 1:
            raise AuditError(f"{member}:{line_number}: repeated axis outside G85: {line}")
        target = target_from_words(words[0], current, fmt, absolute, member, line_number)
        if "G00" in line:
            current = target
            continue
        if "G01" in line:
            if not route_on:
                raise AuditError(f"{member}:{line_number}: G01 route without M15 tool-down")
            append_slot(current, target, line_number)
            current = target
            continue
        append_round(target, line_number)
        current = target

    if route_on:
        raise AuditError(f"{member}: EOF reached while routing tool is down")
    if not items:
        raise AuditError(f"{member}: no drill hits or routed slots")

    return items, {
        "member": member,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
        "unit": fmt.unit,
        "format": [fmt.integer_digits, fmt.decimal_digits],
        "zeroSuppression": fmt.zero_suppression,
        "fileFunction": file_function,
        "legacyType": legacy_type,
        "declaredClass": declared_class,
        "toolCount": len(tools),
        "itemCounts": dict(sorted(Counter(item.category for item in items).items())),
        "tools": [
            {
                "name": tool.name,
                "diameterMm": round_clean(tool.diameter_mm),
                "function": tool.function,
            }
            for tool in tools.values()
        ],
    }


def looks_like_drill_member(name: str, data: bytes) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix in (".drl", ".xln", ".exc", ".tap"):
        return True
    if suffix in (".txt", ".nc"):
        return b"M48" in data[:4096].upper()
    return False


def round_item_key(item: DrillItem) -> tuple[str, float, float, float]:
    """Stable key for proving an exporter-emitted via file is a true subset."""

    return (
        item.category,
        round(item.center_mm[0], 6),
        round(item.center_mm[1], 6),
        round(item.diameter_mm, 6),
    )


def read_candidate_zip(path: Path) -> tuple[list[DrillItem], list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.is_file():
        raise AuditError(f"candidate ZIP does not exist: {path}")
    parsed: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    member_groups: list[tuple[str, list[DrillItem], dict[str, Any]]] = []
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise AuditError(f"candidate ZIP CRC failure: {bad_member}")
            for info in archive.infolist():
                entries.append(
                    {
                        "member": info.filename,
                        "bytes": info.file_size,
                        "compressedBytes": info.compress_size,
                        "crc32": f"{info.CRC:08x}",
                    }
                )
                if info.is_dir():
                    continue
                if info.file_size > MAX_DRILL_MEMBER_BYTES and Path(info.filename).suffix.lower() in (
                    ".drl",
                    ".xln",
                    ".exc",
                    ".tap",
                ):
                    raise AuditError(
                        f"{info.filename}: drill member exceeds {MAX_DRILL_MEMBER_BYTES} bytes"
                    )
                data = archive.read(info)
                if not looks_like_drill_member(info.filename, data):
                    continue
                member_items, metadata = parse_excellon(info.filename, data)
                parsed.append(metadata)
                member_groups.append((info.filename, member_items, metadata))
    except zipfile.BadZipFile as exc:
        raise AuditError(f"invalid candidate ZIP {path}: {exc}") from exc
    if not parsed:
        raise AuditError("candidate ZIP contains no recognizable Excellon drill members")
    # EasyEDA 3.2 emits both a complete plated-through file and a second
    # via-only file.  Counting both would double-count the same 634 physical
    # holes.  Exclude the via-only member only after proving, by a duplicate-
    # aware multiset comparison, that every round item is already present in
    # one other PTH member.  Any non-subset or slot-bearing file remains part
    # of the canonical inventory and will fail the fixed board profile if it
    # is genuinely extra geometry.
    canonical: list[DrillItem] = []
    for member, member_items, metadata in member_groups:
        redundant_of: str | None = None
        if (
            "via" in Path(member).stem.casefold()
            and member_items
            and all(item.category == "pth_round" for item in member_items)
        ):
            child_counts = Counter(round_item_key(item) for item in member_items)
            for parent_member, parent_items, _ in member_groups:
                if parent_member == member:
                    continue
                parent_counts = Counter(round_item_key(item) for item in parent_items)
                if sum(parent_counts.values()) <= sum(child_counts.values()):
                    continue
                if all(parent_counts[key] >= count for key, count in child_counts.items()):
                    redundant_of = parent_member
                    break
        metadata["includedInCanonicalInventory"] = redundant_of is None
        if redundant_of is not None:
            metadata["redundantExactSubsetOf"] = redundant_of
            metadata["redundantItemCount"] = len(member_items)
        else:
            canonical.extend(member_items)
    return canonical, parsed, entries


def expected_from_manifest(manifest: dict[str, Any]) -> list[DrillItem]:
    result: list[DrillItem] = []
    for drill in manifest.get("drills", []):
        member = str(drill.get("file") or "")
        if not member:
            raise AuditError("manifest drill entry lacks file")
        for index, hole in enumerate(drill.get("holes", []), 1):
            function = str(hole.get("function") or "") or None
            plated = hole.get("plated")
            cls = "pth" if plated is True else "npth" if plated is False else function_class(function)
            if cls not in ("pth", "npth"):
                raise AuditError(f"manifest {member} hole {index}: cannot classify plating")
            center = hole.get("atMm")
            if not isinstance(center, list) or len(center) != 2:
                raise AuditError(f"manifest {member} hole {index}: invalid atMm")
            kind = "slot" if hole.get("kind") == "slot" else "round"
            start = hole.get("startMm") if kind == "slot" else None
            end = hole.get("endMm") if kind == "slot" else None
            if kind == "slot" and (
                not isinstance(start, list)
                or len(start) != 2
                or not isinstance(end, list)
                or len(end) != 2
            ):
                raise AuditError(f"manifest {member} hole {index}: invalid slot endpoints")
            result.append(
                DrillItem(
                    kind,
                    (finite(center[0], "manifest atMm"), finite(center[1], "manifest atMm")),
                    finite(hole.get("diameterMm"), "manifest diameterMm"),
                    cls,
                    function,
                    member,
                    index,
                    str(hole.get("tool") or ""),
                    None if start is None else (finite(start[0], "startMm"), finite(start[1], "startMm")),
                    None if end is None else (finite(end[0], "endMm"), finite(end[1], "endMm")),
                )
            )
    if not result:
        raise AuditError("manifest contains no drills")
    counts = Counter(item.category for item in result)
    profile_counts = {key: counts[key] for key in EXPECTED_BOARD_PROFILE}
    if profile_counts != EXPECTED_BOARD_PROFILE:
        raise AuditError(
            f"authoritative manifest inventory changed: {profile_counts} != {EXPECTED_BOARD_PROFILE}"
        )
    semantics = Counter(item.semantic for item in result if item.category == "pth_round")
    if {key: semantics[key] for key in EXPECTED_PTH_SEMANTICS} != EXPECTED_PTH_SEMANTICS:
        raise AuditError(
            "authoritative manifest PTH semantics changed: "
            f"{dict(semantics)} != {EXPECTED_PTH_SEMANTICS}"
        )
    return result


def verify_authoritative_source(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        raise AuditError(f"authoritative source ZIP does not exist: {path}")
    checks: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        by_basename: dict[str, list[str]] = defaultdict(list)
        for name in archive.namelist():
            by_basename[Path(name).name].append(name)
        for drill in manifest.get("drills", []):
            basename = Path(str(drill.get("file") or "")).name
            candidates = by_basename.get(basename, [])
            if len(candidates) != 1:
                raise AuditError(
                    f"authoritative source ZIP expected exactly one {basename!r}, found {candidates!r}"
                )
            data = archive.read(candidates[0])
            actual = sha256_bytes(data)
            expected = str(drill.get("sha256") or "")
            if actual != expected:
                raise AuditError(
                    f"authoritative source hash mismatch for {basename}: {actual} != {expected}"
                )
            checks.append(
                {
                    "member": candidates[0],
                    "sha256": actual,
                    "matchesManifest": True,
                }
            )
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "drillMembers": checks,
        "status": "pass",
    }


def inventory(items: Iterable[DrillItem]) -> dict[str, int]:
    counts = Counter(item.category for item in items)
    return {key: counts[key] for key in EXPECTED_BOARD_PROFILE}


def histogram(items: Iterable[DrillItem]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items:
        if item.kind == "slot":
            key = (
                f"{item.category}:diameter={item.diameter_mm:.6f}:"
                f"centerline={item.centerline_length_mm:.6f}"
            )
        else:
            key = f"{item.category}:diameter={item.diameter_mm:.6f}"
        counts[key] += 1
    return dict(sorted(counts.items()))


def size_close(left: DrillItem, right: DrillItem, tolerance: float) -> bool:
    return (
        left.category == right.category
        and abs(left.diameter_mm - right.diameter_mm) <= tolerance
        and abs(left.centerline_length_mm - right.centerline_length_mm) <= tolerance
    )


def geometry_error(candidate: DrillItem, expected: DrillItem, transform: Transform) -> float:
    if candidate.kind == "round":
        return math.dist(transform.point(candidate.center_mm), expected.center_mm)
    assert candidate.start_mm is not None and candidate.end_mm is not None
    assert expected.start_mm is not None and expected.end_mm is not None
    start = transform.point(candidate.start_mm)
    end = transform.point(candidate.end_mm)
    direct = max(math.dist(start, expected.start_mm), math.dist(end, expected.end_mm))
    reverse = max(math.dist(start, expected.end_mm), math.dist(end, expected.start_mm))
    return min(direct, reverse)


def match_items(
    candidate: Sequence[DrillItem],
    expected: Sequence[DrillItem],
    transform: Transform,
    position_tolerance: float,
    size_tolerance: float,
) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
    remaining = set(range(len(candidate)))
    pairs: list[tuple[int, int, float]] = []

    # Rare tool sizes first makes the deterministic greedy match equivalent to
    # a one-to-one exact match for this drill set (minimum hole pitch is orders
    # of magnitude larger than the tolerance).
    rarity = Counter(
        (
            item.category,
            round(item.diameter_mm, 5),
            round(item.centerline_length_mm, 5),
        )
        for item in expected
    )
    expected_order = sorted(
        range(len(expected)),
        key=lambda index: (
            rarity[
                (
                    expected[index].category,
                    round(expected[index].diameter_mm, 5),
                    round(expected[index].centerline_length_mm, 5),
                )
            ],
            expected[index].category,
            expected[index].center_mm,
        ),
    )
    unmatched_expected: list[int] = []
    for expected_index in expected_order:
        target = expected[expected_index]
        possibilities: list[tuple[float, int]] = []
        for candidate_index in remaining:
            source = candidate[candidate_index]
            if not size_close(source, target, size_tolerance):
                continue
            error = geometry_error(source, target, transform)
            if error <= position_tolerance:
                possibilities.append((error, candidate_index))
        if not possibilities:
            unmatched_expected.append(expected_index)
            continue
        error, candidate_index = min(possibilities, key=lambda value: (value[0], value[1]))
        remaining.remove(candidate_index)
        pairs.append((candidate_index, expected_index, error))
    return pairs, sorted(remaining), unmatched_expected


def anchor_frequency(item: DrillItem, expected: Sequence[DrillItem], size_tolerance: float) -> int:
    return sum(size_close(other, item, size_tolerance) for other in expected)


def infer_transform(
    candidate: Sequence[DrillItem],
    expected: Sequence[DrillItem],
    position_tolerance: float,
    size_tolerance: float,
) -> tuple[Transform | None, list[tuple[int, int, float]], list[int], list[int], dict[str, Any]]:
    if not candidate or not expected:
        return None, [], list(range(len(candidate))), list(range(len(expected))), {
            "hypothesesTested": 0
        }
    anchor_expected_index = min(
        range(len(expected)),
        key=lambda index: (
            anchor_frequency(expected[index], expected, size_tolerance),
            expected[index].category,
            expected[index].diameter_mm,
            expected[index].centerline_length_mm,
            expected[index].center_mm,
        ),
    )
    anchor_expected = expected[anchor_expected_index]
    candidate_anchors = [
        (index, item)
        for index, item in enumerate(candidate)
        if size_close(item, anchor_expected, size_tolerance)
    ]
    best: tuple[int, float, Transform, list[tuple[int, int, float]], list[int], list[int]] | None = None
    hypotheses = 0
    for matrix_name, matrix in ORTHOGONAL_MATRICES:
        for _, anchor_candidate in candidate_anchors:
            (a, b), (c, d) = matrix
            transformed_anchor = (
                a * anchor_candidate.center_mm[0] + b * anchor_candidate.center_mm[1],
                c * anchor_candidate.center_mm[0] + d * anchor_candidate.center_mm[1],
            )
            offset = (
                anchor_expected.center_mm[0] - transformed_anchor[0],
                anchor_expected.center_mm[1] - transformed_anchor[1],
            )
            transform = Transform(matrix_name, matrix, offset)
            pairs, unmatched_candidate, unmatched_expected = match_items(
                candidate, expected, transform, position_tolerance, size_tolerance
            )
            hypotheses += 1
            max_error = max((pair[2] for pair in pairs), default=float("inf"))
            score = (len(pairs), -max_error)
            if best is None or score > (best[0], best[1]):
                best = (
                    len(pairs),
                    -max_error,
                    transform,
                    pairs,
                    unmatched_candidate,
                    unmatched_expected,
                )
            if len(pairs) == len(candidate) == len(expected):
                return transform, pairs, [], [], {
                    "hypothesesTested": hypotheses,
                    "anchorExpected": item_summary(anchor_expected),
                    "anchorCandidateCount": len(candidate_anchors),
                }
    if best is None:
        return None, [], list(range(len(candidate))), list(range(len(expected))), {
            "hypothesesTested": hypotheses,
            "anchorExpected": item_summary(anchor_expected),
            "anchorCandidateCount": len(candidate_anchors),
        }
    return best[2], best[3], best[4], best[5], {
        "hypothesesTested": hypotheses,
        "anchorExpected": item_summary(anchor_expected),
        "anchorCandidateCount": len(candidate_anchors),
    }


def item_summary(item: DrillItem) -> dict[str, Any]:
    result: dict[str, Any] = {
        "category": item.category,
        "centerMm": [round_clean(value) for value in item.center_mm],
        "diameterMm": round_clean(item.diameter_mm),
        "function": item.function,
        "member": item.member,
        "line": item.line,
        "tool": item.tool,
    }
    if item.kind == "slot":
        assert item.start_mm is not None and item.end_mm is not None
        result.update(
            {
                "startMm": [round_clean(value) for value in item.start_mm],
                "endMm": [round_clean(value) for value in item.end_mm],
                "centerlineLengthMm": round_clean(item.centerline_length_mm),
            }
        )
    return result


def candidate_is_source_fixture(parsed: Sequence[dict[str, Any]], manifest: dict[str, Any]) -> bool:
    expected_hashes = {str(item.get("sha256") or "") for item in manifest.get("drills", [])}
    actual_hashes = {str(item.get("sha256") or "") for item in parsed}
    return bool(expected_hashes) and actual_hashes == expected_hashes


def build_report(
    candidate_zip: Path,
    manifest_path: Path,
    source_zip: Path,
    position_tolerance: float,
    size_tolerance: float,
) -> tuple[dict[str, Any], bool]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    expected = expected_from_manifest(manifest)
    source_integrity = verify_authoritative_source(source_zip, manifest)
    candidate, parsed_members, zip_entries = read_candidate_zip(candidate_zip)
    fixture = candidate_is_source_fixture(parsed_members, manifest)

    expected_inventory = inventory(expected)
    candidate_inventory = inventory(candidate)
    inventory_matches = candidate_inventory == expected_inventory
    transform, pairs, unmatched_candidate, unmatched_expected, inference = infer_transform(
        candidate, expected, position_tolerance, size_tolerance
    )
    geometry_matches = (
        transform is not None
        and len(pairs) == len(candidate) == len(expected)
        and not unmatched_candidate
        and not unmatched_expected
    )

    semantic_candidate = [item for item in candidate if item.category == "pth_round"]
    semantic_coverage = sum(item.semantic is not None for item in semantic_candidate)
    semantic_mismatches: list[dict[str, Any]] = []
    if geometry_matches and transform is not None:
        for candidate_index, expected_index, _ in pairs:
            source = candidate[candidate_index]
            target = expected[expected_index]
            if source.category != "pth_round" or source.semantic is None:
                continue
            if source.semantic != target.semantic:
                semantic_mismatches.append(
                    {
                        "candidate": item_summary(source),
                        "expected": item_summary(target),
                    }
                )
    if semantic_coverage == len(semantic_candidate):
        semantic_status = "pass" if not semantic_mismatches else "fail"
    elif semantic_coverage == 0:
        semantic_status = "not-available-from-candidate-excellon"
    else:
        semantic_status = "partial-coverage"

    max_error = max((pair[2] for pair in pairs), default=None)
    inventory_ok = inventory_matches and candidate_inventory == EXPECTED_BOARD_PROFILE
    passed = inventory_ok and geometry_matches and not semantic_mismatches
    if passed and fixture:
        status = "pass-authoritative-source-fixture-only"
    elif passed:
        status = "pass-diagnostic-not-manufacturing-approved"
    else:
        status = "fail-diagnostic"

    report = {
        "schemaVersion": 1,
        "status": status,
        "manufacturingApproved": False,
        "approvalScope": "diagnostic-only-never-manufacturing-approval",
        "candidateKind": "authoritative-source-fixture" if fixture else "diagnostic-native-export",
        "disclaimer": (
            "This static drill identity check does not validate all Gerber layers, fabrication "
            "rules, net connectivity, stackup, clearances, or manufacturability. Passing is not "
            "authorization to order or fabricate boards."
        ),
        "inputs": {
            "candidateZip": {
                "path": str(candidate_zip.resolve()),
                "sha256": sha256_file(candidate_zip),
                "bytes": candidate_zip.stat().st_size,
            },
            "authoritativeManifest": {
                "path": str(manifest_path.resolve()),
                "sha256": sha256_file(manifest_path),
            },
            "authoritativeSourceZip": source_integrity,
        },
        "tolerancesMm": {
            "positionAndSlotEndpoint": position_tolerance,
            "toolDiameterAndSlotLength": size_tolerance,
        },
        "candidateZipEntries": zip_entries,
        "parsedDrillMembers": parsed_members,
        "redundantSupplementalDrillMembers": [
            {
                "member": item["member"],
                "exactSubsetOf": item["redundantExactSubsetOf"],
                "itemCount": item["redundantItemCount"],
            }
            for item in parsed_members
            if item.get("includedInCanonicalInventory") is False
        ],
        "inventory": {
            "expected": expected_inventory,
            "candidate": candidate_inventory,
            "fixedBoardProfile": EXPECTED_BOARD_PROFILE,
            "matches": inventory_matches,
            "authoritativePthRoundSemantics": EXPECTED_PTH_SEMANTICS,
        },
        "sizeHistogram": {
            "expected": histogram(expected),
            "candidate": histogram(candidate),
            "matchesExactlyAtSixDecimals": histogram(expected) == histogram(candidate),
        },
        "coordinateIdentity": {
            "matches": geometry_matches,
            "matchedItems": len(pairs),
            "candidateItems": len(candidate),
            "expectedItems": len(expected),
            "maximumMatchedErrorMm": None if max_error is None else round_clean(max_error, 12),
            "transform": None
            if transform is None
            else {
                "name": transform.name,
                "matrix": [list(row) for row in transform.matrix],
                "candidateToAuthoritativeOffsetMm": [
                    round_clean(value, 12) for value in transform.offset_mm
                ],
            },
            "inference": inference,
            "unmatchedCandidateSample": [
                item_summary(candidate[index]) for index in unmatched_candidate[:20]
            ],
            "unmatchedExpectedSample": [
                item_summary(expected[index]) for index in unmatched_expected[:20]
            ],
        },
        "pthRoundViaVsComponentSemantics": {
            "status": semantic_status,
            "candidateCoverage": semantic_coverage,
            "candidatePthRoundCount": len(semantic_candidate),
            "mismatchCount": len(semantic_mismatches),
            "mismatchSample": semantic_mismatches[:20],
            "note": (
                "Some Excellon exporters omit ViaDrill/ComponentDrill attributes. In that case "
                "all 767 PTH round geometries are still checked, but ZIP-only semantic ownership "
                "cannot be claimed; use the separate native PCB inventory audit for ownership."
            ),
        },
        "checks": {
            "authoritativeSourceHashesMatchManifest": source_integrity["status"] == "pass",
            "inventoryMatches": inventory_matches,
            "allCoordinatesDiametersAndSlotEndpointsMatch": geometry_matches,
            "availablePthSemanticsHaveNoMismatch": not semantic_mismatches,
        },
    }
    return report, passed


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gerber-zip", required=True, type=Path, help="candidate Gerber ZIP")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--authoritative-source-zip", type=Path, default=DEFAULT_SOURCE_ZIP)
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=f"optional JSON report path (suggested: {DEFAULT_REPORT})",
    )
    parser.add_argument(
        "--position-tolerance-mm", type=float, default=DEFAULT_POSITION_TOLERANCE_MM
    )
    parser.add_argument("--size-tolerance-mm", type=float, default=DEFAULT_SIZE_TOLERANCE_MM)
    parser.add_argument("--compact", action="store_true", help="emit compact JSON to stdout")
    args = parser.parse_args(argv)
    if args.position_tolerance_mm <= 0 or args.size_tolerance_mm <= 0:
        parser.error("tolerances must be positive")
    return args


def emit_report(report: dict[str, Any], report_path: Path | None, compact: bool) -> None:
    text = json.dumps(
        report,
        ensure_ascii=False,
        indent=None if compact else 2,
        sort_keys=False,
    )
    print(text)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report, passed = build_report(
            args.gerber_zip.resolve(),
            args.manifest.resolve(),
            args.authoritative_source_zip.resolve(),
            args.position_tolerance_mm,
            args.size_tolerance_mm,
        )
    except (AuditError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "schemaVersion": 1,
            "status": "error-diagnostic",
            "manufacturingApproved": False,
            "approvalScope": "diagnostic-only-never-manufacturing-approval",
            "error": str(exc),
        }
        emit_report(report, args.report, args.compact)
        return 2
    emit_report(report, args.report, args.compact)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
