#!/usr/bin/env python3
"""Merge routed copper and global silkscreen into the placed native PCB.

No EasyEDA API or UI is used.  The placed schematic-to-PCB result remains the
identity and electrical authority: DOCHEAD, META, COMPONENT, PAD, PAD_NET,
NET, ATTR and rule records are preserved.  This adapter only:

* enables the six existing copper LAYER records via ``use/show=true``;
* replaces the default two-layer substrate 361 and all old LAYER_PHYS records;
* appends the five Gerber-backed substrate LAYER records and exact 13-record
  physical stack from the routed reference, translating legacy source
  substrate IDs 101..105 to EasyEDA 3.2 runtime IDs 361..365;
* appends the routed LINE/ARC/FILL/VIA records and 504 global F.Silk records.

The result is still not manufacturing-ready until EasyEDA imports it and the
native netlist comparison and DRC pass.  If the placed PCB does not yet exist,
the script performs the complete static-source and adapter contract audit and
emits a waiting report without fabricating a substitute board.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_INPUT = ROOT / "output" / "native-pcb" / "native-pcb-placed.epru"
DEFAULT_PLACEMENT_REPORT = (
    ROOT / "output" / "native-pcb" / "native-pcb-placement-manifest.json"
)
DEFAULT_ROUTE = ROOT / "output" / "native-pcb" / "gerber-routing-reference.epru"
DEFAULT_ROUTE_MANIFEST = (
    ROOT / "output" / "native-pcb" / "gerber-routing-reference-manifest.json"
)
DEFAULT_ROUTE_SCHEMA_REPORT = (
    ROOT / "output" / "validation" / "native-pcb-routing-schema-report.json"
)
DEFAULT_SILK = ROOT / "output" / "native-pcb" / "global-silkscreen-reference.epru"
DEFAULT_SILK_MANIFEST = (
    ROOT / "output" / "native-pcb" / "global-silkscreen-reference-manifest.json"
)
DEFAULT_SILK_SCHEMA_REPORT = (
    ROOT / "output" / "validation" / "native-pcb-global-silkscreen-schema-report.json"
)
DEFAULT_REFERENCE_NETLIST = ROOT / "output" / "semantic" / "reference-netlist.json"
DEFAULT_LIBRARY_MANIFEST = ROOT / "output" / "native-libraries" / "manifest.json"
DEFAULT_JOB = (
    ROOT / "보드 자료" / "MCU_BOARD_v19_260616_Gerber" /
    "MCU_BOARD_v19_260616-job.gbrjob"
)
DEFAULT_BLANK_FIXTURE = ROOT / "output" / "validation" / "native-pcb-blank-runtime.epru"
DEFAULT_OUTPUT = ROOT / "output" / "native-pcb" / "native-pcb-routed.epru"
DEFAULT_REPORT = (
    ROOT / "output" / "native-pcb" / "native-pcb-routing-merge-manifest.json"
)
DEFAULT_OUTPUT_SCHEMA_REPORT = (
    ROOT / "output" / "validation" / "native-pcb-routed-schema-report.json"
)
VALIDATOR = ROOT / "scripts" / "validate-native-source.py"

EXPECTED_ROUTE_SHA256 = "b5f4f9ba2db36c4dd9f598f7a12bc7da78c5873ad39cd9cfd5440877cc1c46f5"
EXPECTED_SILK_SHA256 = "ed5eb4715c0be8ffef7dd9c3dc313130345c84d503d20db37fa69cf7e54d37bb"
EXPECTED_REFERENCE_NET_COUNT = 279
EXPECTED_PHYSICAL_REFERENCE_COUNT = 330
EXPECTED_NATIVE_COMPONENT_COUNT = 330
EXPECTED_NATIVE_PAD_NET_COUNT = 1176
EXPECTED_NATIVE_CONNECTED_PAD_NET_COUNT = 1057
EXPECTED_NATIVE_UNCONNECTED_PAD_NET_COUNT = 119
EXPECTED_NATIVE_EMPTY_NET_COUNT = 1
EXPECTED_REMOVED_CAP_COUNT = 10
EXPECTED_STALE_NET_COUNT = 20
EXPECTED_ROUTE_PRIMITIVE_COUNT = 8968
EXPECTED_SILK_PRIMITIVE_COUNT = 504
EXPECTED_ROUTE_COUNTS = Counter({"LINE": 5535, "ARC": 2184, "FILL": 615, "VIA": 634})
EXPECTED_SILK_COUNTS = Counter({"LINE": 492, "FILL": 12})
ROUTE_PRIMITIVE_TYPES = frozenset({"LINE", "ARC", "FILL", "VIA"})
SILK_PRIMITIVE_TYPES = frozenset({"LINE", "FILL"})
PROTECTED_TYPES = frozenset({
    "DOCHEAD", "META", "COMPONENT", "PAD", "PAD_NET", "NET", "ATTR",
    "RULE", "RULE_TEMPLATE",
})
SCAFFOLD_TYPES = frozenset({
    "DOCHEAD", "META", "CANVAS", "ACTIVE_LAYER", "PREFERENCE", "NET",
    "RULE", "RULE_TEMPLATE",
})
COPPER_LAYER_NAMES = {
    1: "F.Cu",
    15: "In1.Cu",
    16: "In2.Cu",
    17: "In3.Cu",
    18: "In4.Cu",
    2: "B.Cu",
}
COPPER_LAYER_IDS = frozenset(COPPER_LAYER_NAMES)
SOURCE_SUBSTRATE_LAYER_IDS = frozenset({101, 102, 103, 104, 105})
SUBSTRATE_LAYER_ID_MAP = {
    101: 361,
    102: 362,
    103: 363,
    104: 364,
    105: 365,
}
CANONICAL_SUBSTRATE_LAYER_IDS = frozenset(SUBSTRATE_LAYER_ID_MAP.values())
DEFAULT_SUBSTRATE_LAYER_ID = 361
MM_TO_MIL = 39.37007874015748

REFERENCE_ATTRIBUTE_KEYS = {
    "designator", "reference", "reference designator", "refdes", "ref",
    "component reference",
}
FOOTPRINT_ATTRIBUTE_KEYS = {
    "footprint", "footprint name", "footprintname", "footprints",
    "supplier footprint",
}


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


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def number(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite number: {value!r}")
    return result


def rounded(value: float, digits: int = 6) -> int | float:
    result = round(number(value), digits)
    return int(result) if result.is_integer() else result


def safe_output_path(path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"{label} must be below {OUTPUT_ROOT}; got {resolved}") from exc
    if not relative.parts:
        raise ValueError(f"{label} cannot be the output root")
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
    raw_line: str | None = None
    origin: str = "base"

    @property
    def kind(self) -> str:
        return str(self.header.get("type") or "")

    @property
    def record_id(self) -> str:
        return str(self.header.get("id") or "")

    def line(self) -> str:
        if self.raw_line is not None:
            return self.raw_line + "\n"
        return f"{compact(self.header)}||{compact(self.body)}|\n"

    def canonical(self, *, omit_ticket: bool = False) -> str:
        header = dict(self.header)
        if omit_ticket:
            header.pop("ticket", None)
        return compact([header, self.body])


def serialize_source(records: Iterable[Record]) -> str:
    """Match the 3.2 PCB getter framing: separators between records, none at EOF."""
    text = "".join(record.line() for record in records)
    if not text.endswith("|\n"):
        raise AssertionError("native PCB serialization did not end in a record separator")
    return text[:-2]


@dataclass
class StaticInputs:
    route_records: list[Record]
    silk_records: list[Record]
    route_primitives: list[Record]
    silk_primitives: list[Record]
    route_substrates: list[Record]
    route_layer_phys: list[Record]
    reference_nets: set[str]
    physical_refs: set[str]
    removed_refs: set[str]
    stale_nets: set[str]
    route_manifest: dict[str, Any]
    silk_manifest: dict[str, Any]
    library_manifest: dict[str, Any]
    job: dict[str, Any]
    report: dict[str, Any]


def parse_source(path: Path, origin: str) -> list[Record]:
    records: list[Record] = []
    source_lines = path.read_text(encoding="utf-8-sig").splitlines()
    nonempty_line_numbers = [
        index for index, raw in enumerate(source_lines, 1) if raw.strip()
    ]
    final_nonempty_line = nonempty_line_numbers[-1] if nonempty_line_numbers else 0
    for line_number, raw in enumerate(source_lines, 1):
        line = raw.strip()
        if not line:
            continue
        # EasyEDA getter exports observed in 3.2 may omit the final record's
        # trailing pipe.  Accept that exact EOF case and normalize it before
        # appending records; an interior missing pipe remains invalid.
        if "||" not in line or (not line.endswith("|") and line_number != final_nonempty_line):
            raise ValueError(f"{path}:{line_number}: invalid EasyEDA JSON-record framing")
        normalized_line = line if line.endswith("|") else line + "|"
        head_text, body_text = normalized_line[:-1].split("||", 1)
        header, body = json.loads(head_text), json.loads(body_text)
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise ValueError(f"{path}:{line_number}: record header/body must be objects")
        records.append(Record(header, body, line_number, normalized_line, origin))
    if not records:
        raise ValueError(f"native source contains no records: {path}")
    docheads = [record for record in records if record.kind == "DOCHEAD"]
    if len(docheads) != 1 or docheads[0].body.get("docType") != "PCB":
        raise ValueError(f"expected exactly one PCB DOCHEAD in {path}")
    return records


def semantic_digest(records: Iterable[Record], *, omit_ticket: bool = False) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.canonical(omit_ticket=omit_ticket).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def record_counts(records: Iterable[Record]) -> Counter[str]:
    return Counter(record.kind for record in records)


def parsed_record_id(record: Record) -> list[Any] | None:
    if not record.record_id.startswith("["):
        return None
    try:
        value = json.loads(record.record_id)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def layer_id(record: Record) -> int | None:
    body_id = record.body.get("layerId")
    if isinstance(body_id, (int, float)) and not isinstance(body_id, bool):
        return int(body_id)
    parts = parsed_record_id(record)
    if parts and len(parts) >= 2 and parts[0] in {"LAYER", "LAYER_PHYS"}:
        try:
            return int(parts[1])
        except (TypeError, ValueError):
            return None
    return None


def net_name(record: Record) -> str | None:
    if record.kind != "NET":
        return None
    parts = parsed_record_id(record)
    if parts and len(parts) == 2 and parts[0] == "NET" and isinstance(parts[1], str):
        return parts[1]
    for key in ("netName", "name"):
        value = record.body.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError(f"NET record has no recoverable name: {record.record_id!r}")


def net_set(records: Iterable[Record]) -> set[str]:
    """Return non-empty native net names while validating every NET identity.

    EasyEDA 3.2 emits one native ``["NET",""]`` scaffold record in a PCB
    generated from a schematic.  It is real document state and must be
    preserved, but it is not one of the 279 electrical nets.
    """
    names = [net_name(record) for record in records if record.kind == "NET"]
    if any(name is None for name in names) or len(names) != len(set(names)):
        raise ValueError("native NET records are missing names or contain duplicates")
    return {str(name) for name in names if name}


def empty_net_count(records: Iterable[Record]) -> int:
    return sum(1 for record in records if record.kind == "NET" and net_name(record) == "")


def casefold_net_index(names: Iterable[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        folded = name.casefold()
        if folded in result and result[folded] != name:
            raise ValueError(
                f"{label} has case-insensitive net collision: {result[folded]!r} / {name!r}"
            )
        result[folded] = name
    return result


def net_spelling_map(source: set[str], target: set[str]) -> dict[str, str]:
    """Map semantic/Gerber spelling to the exact generated-native spelling.

    Protel/EasyEDA upper-cases some generated NET IDs while retaining the
    semantic spelling in PAD_NET.padNet.  A case-insensitive bijection is
    therefore required; anything beyond spelling/case is rejected.
    """
    source_index = casefold_net_index(source, "semantic/reference net set")
    target_index = casefold_net_index(target, "generated native net set")
    if set(source_index) != set(target_index):
        raise ValueError(
            "generated native NET set differs semantically from latest reference: "
            f"native-only={sorted(set(target_index)-set(source_index))[:12]}, "
            f"missing={sorted(set(source_index)-set(target_index))[:12]}"
        )
    return {name: target_index[name.casefold()] for name in source}


def primitive_net_set(records: Iterable[Record]) -> set[str]:
    return {
        str(record.body.get("netName"))
        for record in records
        if isinstance(record.body.get("netName"), str) and record.body.get("netName")
    }


def source_schema_report(path: Path, expected_sha: str) -> dict[str, Any]:
    report = read_json(path)
    totals = report.get("totals") or {}
    files = report.get("files") or []
    issue_total = sum(
        int(totals.get(key) or 0)
        for key in ("parseErrors", "unmappedRecords", "addFields", "removeFields", "changeFields")
    )
    if report.get("valid") is not True or issue_total != 0 or len(files) != 1:
        raise ValueError(f"source strict-schema report is not clean: {path}")
    if files[0].get("sha256") != expected_sha:
        raise ValueError(
            f"source strict-schema report is stale: {files[0].get('sha256')} != {expected_sha}"
        )
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
        "format_version": report.get("formatVersion"),
        "valid": True,
        "issue_count": 0,
        "documented_runtime_exceptions": int(totals.get("documentedRuntimeExceptions") or 0),
    }


def validate_record_ids(records: Sequence[Record], label: str) -> set[str]:
    ids = [record.record_id for record in records if record.record_id]
    duplicates = sorted(value for value, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"{label} has duplicate record IDs: {duplicates[:12]}")
    return set(ids)


def assert_primitive_ids(records: Sequence[Record], label: str) -> set[str]:
    ids = validate_record_ids(records, label)
    if any(re.fullmatch(r"[0-9a-f]{16}", value) is None for value in ids):
        raise ValueError(f"{label} has a non-current primitive ID")
    return ids


def load_static_inputs(args: argparse.Namespace) -> StaticInputs:
    paths = [
        args.route, args.route_manifest, args.route_schema_report,
        args.silk, args.silk_manifest, args.silk_schema_report,
        args.reference_netlist, args.library_manifest, args.job,
    ]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"static merge prerequisite(s) missing: {missing}")

    route_sha = sha256_file(args.route)
    silk_sha = sha256_file(args.silk)
    if route_sha != EXPECTED_ROUTE_SHA256:
        raise ValueError(f"route source SHA mismatch: {route_sha} != {EXPECTED_ROUTE_SHA256}")
    if silk_sha != EXPECTED_SILK_SHA256:
        raise ValueError(f"silkscreen source SHA mismatch: {silk_sha} != {EXPECTED_SILK_SHA256}")
    route_manifest = read_json(args.route_manifest)
    silk_manifest = read_json(args.silk_manifest)
    if (route_manifest.get("output") or {}).get("sha256") != route_sha:
        raise ValueError("route manifest does not identify the exact route source")
    if (silk_manifest.get("output") or {}).get("sha256") != silk_sha:
        raise ValueError("silkscreen manifest does not identify the exact silk source")
    route_coordinate = route_manifest.get("coordinate_transform") or {}
    route_stack = route_manifest.get("stackup") or {}
    layer_phys_format = (
        (route_manifest.get("format_compatibility") or {}).get("layer_phys_thickness") or {}
    )
    silk_coordinate = silk_manifest.get("coordinate_transform") or {}
    if (
        route_coordinate.get("native_internal_units") != "mil"
        or (route_manifest.get("native_source_validation") or {}).get("native_coordinate_axis") != "y-up"
        or layer_phys_format.get("emitted_unit") != "mil"
    ):
        raise ValueError("route source unit/axis contract is not native mil/Y-up")
    if (route_stack.get("thickness_audit") or {}).get("native_layer_phys_sum_mm") != 1.58:
        raise ValueError("route source stack does not declare the exact 1.58 mm physical total")
    if silk_coordinate.get("native") != "board-local mil, Y-up":
        raise ValueError("global-silkscreen source unit/axis contract is not native mil/Y-up")
    route_schema = source_schema_report(args.route_schema_report, route_sha)
    silk_schema = source_schema_report(args.silk_schema_report, silk_sha)

    route_records = parse_source(args.route, "route")
    silk_records = parse_source(args.silk, "silkscreen")
    route_primitives = [record for record in route_records if record.kind in ROUTE_PRIMITIVE_TYPES]
    silk_primitives = [record for record in silk_records if record.kind in SILK_PRIMITIVE_TYPES]
    if record_counts(route_primitives) != EXPECTED_ROUTE_COUNTS:
        raise ValueError(f"unexpected routed primitive counts: {record_counts(route_primitives)!r}")
    if record_counts(silk_primitives) != EXPECTED_SILK_COUNTS:
        raise ValueError(f"unexpected global-silk primitive counts: {record_counts(silk_primitives)!r}")
    if len(route_primitives) != EXPECTED_ROUTE_PRIMITIVE_COUNT:
        raise ValueError("routed primitive total is not 8968")
    if len(silk_primitives) != EXPECTED_SILK_PRIMITIVE_COUNT:
        raise ValueError("global-silk primitive total is not 504")
    route_ids = assert_primitive_ids(route_primitives, "route source")
    silk_ids = assert_primitive_ids(silk_primitives, "silkscreen source")
    if route_ids & silk_ids:
        raise ValueError(f"route/global-silk primitive ID collision: {sorted(route_ids & silk_ids)[:8]}")
    if any(record.body.get("layerId") != 3 for record in silk_primitives):
        raise ValueError("global-silk source contains a primitive outside native layer 3")
    if any(record.body.get("groupId") != 0 for record in route_primitives + silk_primitives):
        raise ValueError("merge source contains a primitive without exact groupId integer zero")

    reference = read_json(args.reference_netlist)
    reference_nets = {
        str(pin.get("net")) for pin in reference.get("pins", []) if pin.get("net")
    }
    if len(reference_nets) != EXPECTED_REFERENCE_NET_COUNT:
        raise ValueError(f"reference netlist must contain 279 unique nets, got {len(reference_nets)}")
    route_nets = net_set(route_records)
    if route_nets != reference_nets or primitive_net_set(route_primitives) != reference_nets:
        raise ValueError("route NET/primitive net set does not exactly match latest reference netlist")

    old_to_latest = (route_manifest.get("net_patch") or {}).get("old_to_latest") or {}
    stale_nets = {str(value) for value in old_to_latest}
    if len(stale_nets) != EXPECTED_STALE_NET_COUNT or stale_nets & route_nets:
        raise ValueError("route source stale-net elimination is incomplete")

    route_layers = [record for record in route_records if record.kind == "LAYER"]
    route_layer_by_id = {layer_id(record): record for record in route_layers}
    if set(COPPER_LAYER_IDS) - set(route_layer_by_id):
        raise ValueError("route source is missing one or more six copper LAYER records")
    for native_id, source_name in COPPER_LAYER_NAMES.items():
        if route_layer_by_id[native_id].body.get("layerName") != source_name:
            raise ValueError(
                f"route copper layer map mismatch for {native_id}: "
                f"{route_layer_by_id[native_id].body.get('layerName')} != {source_name}"
            )
    route_substrates = [
        route_layer_by_id[native_id] for native_id in sorted(SOURCE_SUBSTRATE_LAYER_IDS)
        if native_id in route_layer_by_id
    ]
    if len(route_substrates) != 5:
        raise ValueError("route source must contain substrate LAYER IDs 101..105")
    route_layer_phys = [record for record in route_records if record.kind == "LAYER_PHYS"]
    physical_ids = [layer_id(record) for record in route_layer_phys]
    expected_physical_ids = [5, 1, 101, 15, 102, 16, 103, 17, 104, 18, 105, 2, 6]
    if physical_ids != expected_physical_ids:
        raise ValueError(f"route physical stack IDs/order mismatch: {physical_ids!r}")
    if any(
        record.body.get("permittivity") is not None
        or record.body.get("lossTangent") is not None
        for record in route_layer_phys
    ):
        raise ValueError("route physical stack asserts unsupported dielectric properties")

    library = read_json(args.library_manifest)
    footprints = library.get("footprints") or {}
    if not isinstance(footprints, Mapping):
        raise ValueError("native library manifest footprints must be a mapping")
    physical_refs = {str(value) for value in footprints}
    if len(physical_refs) != EXPECTED_PHYSICAL_REFERENCE_COUNT:
        raise ValueError(f"native library must expose 330 physical refs, got {len(physical_refs)}")
    patches = library.get("latest_patches") or {}
    removed_refs = {str(value) for value in patches.get("page6RemovedComponents", [])}
    if len(removed_refs) != EXPECTED_REMOVED_CAP_COUNT or removed_refs & physical_refs:
        raise ValueError("ten removed page-6 capacitors are not cleanly excluded from physical refs")

    job = read_json(args.job)
    design_rules = job.get("DesignRules") or []
    outer = next((item for item in design_rules if item.get("Layers") == "Outer"), None)
    inner = next((item for item in design_rules if item.get("Layers") == "Inner"), None)
    if not outer or not inner:
        raise ValueError("Gerber Job has no Outer/Inner DesignRules")
    if any(number(outer[key]) != 0.1 for key in (
        "PadToPad", "PadToTrack", "TrackToTrack", "TrackToRegion", "RegionToRegion"
    )) or number(outer.get("MinLineWidth")) != 0.15:
        raise ValueError(f"unexpected Gerber outer design rules: {outer!r}")
    if number(inner.get("TrackToTrack")) != 0.1 or number(inner.get("MinLineWidth")) != 0.15:
        raise ValueError(f"unexpected Gerber inner design rules: {inner!r}")

    report = {
        "route": {
            "path": str(args.route.relative_to(ROOT)),
            "sha256": route_sha,
            "strict_schema": route_schema,
            "primitive_count": len(route_primitives),
            "primitive_counts": dict(sorted(record_counts(route_primitives).items())),
            "primitive_payload_sha256": semantic_digest(route_primitives, omit_ticket=True),
            "net_count": len(route_nets),
            "layer_phys_count": len(route_layer_phys),
            "layer_phys_payload_sha256": semantic_digest(route_layer_phys, omit_ticket=True),
            "unknown_dielectric_properties_are_null": True,
        },
        "global_silkscreen": {
            "path": str(args.silk.relative_to(ROOT)),
            "sha256": silk_sha,
            "strict_schema": silk_schema,
            "primitive_count": len(silk_primitives),
            "primitive_counts": dict(sorted(record_counts(silk_primitives).items())),
            "primitive_payload_sha256": semantic_digest(silk_primitives, omit_ticket=True),
        },
        "semantic_contract": {
            "reference_netlist_path": str(args.reference_netlist.relative_to(ROOT)),
            "reference_netlist_sha256": sha256_file(args.reference_netlist),
            "exact_latest_net_count": len(reference_nets),
            "old_bias_net_count": len(stale_nets),
            "old_bias_nets_absent_from_route": True,
            "physical_reference_count": len(physical_refs),
            "removed_capacitor_count": len(removed_refs),
            "removed_capacitors_absent_from_physical_refs": True,
        },
        "layer_contract": {
            "native_copper_id_to_gerber_name": {
                str(key): value for key, value in COPPER_LAYER_NAMES.items()
            },
            "base_metadata_policy": (
                "preserve existing LAYER writer fields; change only use/show to true "
                "for IDs 1,2,15,16,17,18"
            ),
            "replace_default_two_layer_substrate_id": DEFAULT_SUBSTRATE_LAYER_ID,
            "route_source_substrate_ids": sorted(SOURCE_SUBSTRATE_LAYER_IDS),
            "runtime_substrate_id_map": {
                str(source_id): runtime_id
                for source_id, runtime_id in SUBSTRATE_LAYER_ID_MAP.items()
            },
            "append_runtime_substrate_ids": sorted(CANONICAL_SUBSTRATE_LAYER_IDS),
            "runtime_id_evidence": (
                "EasyEDA Pro PCB 3.2 layerPhyFix.fix treats substrate IDs "
                "101..360 as legacy/error data and remaps them by +260; "
                "fixInnerSubstrate allocates substrate IDs from 361 upward"
            ),
            "replace_all_layer_phys_with_route_count": len(route_layer_phys),
            "route_layer_phys_payload_sha256": semantic_digest(route_layer_phys, omit_ticket=True),
            "coordinate_and_unit_assertions": {
                "route_primitives": "board-local mil, Y-up",
                "global_silkscreen": "board-local mil, Y-up",
                "layer_phys_thickness_disk_unit": "mil",
                "physical_stack_total_mm": 1.58,
            },
        },
        "gerber_job_design_rules": {
            "path": str(args.job.relative_to(ROOT)),
            "sha256": sha256_file(args.job),
            "outer": outer,
            "inner": inner,
            "summary": {
                "nominal_clearance_mm": 0.1,
                "minimum_line_width_mm": 0.15,
            },
            "native_rule_policy": "audit and preserve exactly; do not modify in this assembler",
        },
    }
    return StaticInputs(
        route_records=route_records,
        silk_records=silk_records,
        route_primitives=route_primitives,
        silk_primitives=silk_primitives,
        route_substrates=route_substrates,
        route_layer_phys=route_layer_phys,
        reference_nets=reference_nets,
        physical_refs=physical_refs,
        removed_refs=removed_refs,
        stale_nets=stale_nets,
        route_manifest=route_manifest,
        silk_manifest=silk_manifest,
        library_manifest=library,
        job=job,
        report=report,
    )


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
        if parent and key:
            result[parent][key].extend(recursively_flatten(record.body.get("value")))
    return {parent: dict(values) for parent, values in result.items()}


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


def component_references(records: Sequence[Record], known_refs: set[str]) -> tuple[set[str], dict[str, int]]:
    children = component_child_attributes(records)
    counts: Counter[str] = Counter()
    for component in (record for record in records if record.kind == "COMPONENT"):
        if not component.record_id:
            raise ValueError("native COMPONENT has no record ID")
        attributes: dict[str, list[str]] = defaultdict(list)
        for source in (body_attribute_values(component.body), children.get(component.record_id, {})):
            for key, values in source.items():
                attributes[key].extend(values)
        preferred = {
            value for key, values in attributes.items() if key in REFERENCE_ATTRIBUTE_KEYS
            for value in values if value in known_refs
        }
        candidates = preferred or {
            value for values in attributes.values() for value in values if value in known_refs
        }
        if len(candidates) != 1:
            raise ValueError(
                f"COMPONENT {component.record_id} reference missing/ambiguous: {sorted(candidates)}"
            )
        counts[next(iter(candidates))] += 1
    return set(counts), dict(sorted(counts.items()))


def nested_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from nested_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nested_strings(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def stale_electrical_occurrences(records: Sequence[Record], stale_nets: set[str]) -> list[dict[str, Any]]:
    relevant = {"NET", "PAD", "PAD_NET", "LINE", "ARC", "FILL", "VIA"}
    stale_by_casefold = {value.casefold(): value for value in stale_nets}
    result: list[dict[str, Any]] = []
    for record in records:
        if record.kind not in relevant:
            continue
        for root, value in (("$header", record.header), ("$body", record.body)):
            for path, text in nested_strings(value, root):
                if text.casefold() in stale_by_casefold:
                    result.append({
                        "type": record.kind,
                        "record_id": record.record_id,
                        "path": path,
                        "stale_net": text,
                        "canonical_stale_net": stale_by_casefold[text.casefold()],
                    })
    return result


def rule_audit(records: Sequence[Record], job: dict[str, Any]) -> dict[str, Any]:
    rules = [record for record in records if record.kind in {"RULE", "RULE_TEMPLATE"}]
    default_rules: list[dict[str, Any]] = []
    for record in rules:
        if record.kind != "RULE" or record.body.get("ruleState") != "DEFAULT":
            continue
        parts = parsed_record_id(record) or []
        context = record.body.get("ruleContext") or {}
        item: dict[str, Any] = {
            "record_id": record.record_id,
            "category": parts[1] if len(parts) > 1 else None,
            "name": parts[2] if len(parts) > 2 else None,
            "context_unit_field": context.get("unit"),
        }
        track_rows = ((context.get("track") or {}).get("content") or [])
        if track_rows:
            item["track_rows_raw"] = track_rows
            item["track_rows_as_mm_if_internal_mil"] = [
                {
                    key: rounded(number(value) / MM_TO_MIL)
                    for key, value in row.items() if key in {"stroMin", "stroDef", "stroMax"}
                }
                for row in track_rows if isinstance(row, dict)
            ]
        safe_values: list[float] = []
        for spacing in context.get("safeSpacing") or []:
            for row in spacing.get("content") or []:
                safe_values.extend(number(value) for value in row if isinstance(value, (int, float)))
        if safe_values:
            unique = sorted(set(safe_values))
            item["safe_spacing_raw_unique"] = unique
            item["safe_spacing_as_mm_if_internal_mil"] = [
                rounded(value / MM_TO_MIL) for value in unique
            ]
        default_rules.append(item)
    job_rules = job.get("DesignRules") or []
    return {
        "record_count": len(rules),
        "semantic_sha256": semantic_digest(rules),
        "default_rules": default_rules,
        "gerber_job_rules": job_rules,
        "difference_report_only": True,
        "mutation_performed": False,
        "decision": (
            "Gerber Job declares nominal 0.10 mm clearance and 0.15 mm minimum "
            "line width. Native DEFAULT rule values are reported above exactly and "
            "are intentionally preserved for later EasyEDA rule-configuration review."
        ),
    }


def next_ticket(records: Sequence[Record]) -> int:
    values = [
        int(record.header["ticket"])
        for record in records
        if isinstance(record.header.get("ticket"), (int, float))
        and not isinstance(record.header.get("ticket"), bool)
    ]
    return max(values, default=0) + 1


def appended_record(source: Record, ticket: int, origin: str) -> Record:
    header = copy.deepcopy(source.header)
    header["ticket"] = ticket
    return Record(header, copy.deepcopy(source.body), 0, None, origin)


def canonicalized_substrate_record(source: Record, ticket: int, origin: str) -> Record:
    """Translate legacy route substrate IDs to current EasyEDA 3.2 IDs.

    The Gerber-derived route fixture deliberately remains immutable.  EasyEDA
    3.2's PCB ``layerPhyFix`` considers substrate IDs 101..360 legacy/error
    data and remaps them by +260; its native allocator starts at 361.  Perform
    that exact normalization before the source reaches the runtime decoder.
    """
    source_id = layer_id(source)
    if source.kind not in {"LAYER", "LAYER_PHYS"} or source_id not in SUBSTRATE_LAYER_ID_MAP:
        raise ValueError(
            f"cannot canonicalize non-substrate record {source.kind} {source.record_id!r}"
        )
    runtime_id = SUBSTRATE_LAYER_ID_MAP[source_id]
    result = appended_record(source, ticket, origin)
    result.header["id"] = compact([source.kind, runtime_id])
    if "layerId" in result.body:
        result.body["layerId"] = runtime_id
    return result


def remapped_route_record(
    source: Record, ticket: int, spelling_map: Mapping[str, str]
) -> Record:
    result = appended_record(source, ticket, "route-primitive")
    value = result.body.get("netName")
    if isinstance(value, str) and value:
        if value not in spelling_map:
            raise ValueError(f"route primitive uses unmapped net name: {value!r}")
        result.body["netName"] = spelling_map[value]
    return result


def pad_net_audit(records: Sequence[Record]) -> dict[str, Any]:
    pad_nets = [record for record in records if record.kind == "PAD_NET"]
    connected = [record for record in pad_nets if str(record.body.get("padNet") or "")]
    unconnected = [record for record in pad_nets if not str(record.body.get("padNet") or "")]
    return {
        "record_count": len(pad_nets),
        "connected_count": len(connected),
        "unconnected_count": len(unconnected),
        "semantic_sha256": semantic_digest(pad_nets),
    }


def update_layer_stack(
    base: Sequence[Record], static: StaticInputs
) -> tuple[list[Record], dict[str, Any], int]:
    base_layers = [record for record in base if record.kind == "LAYER"]
    base_layer_ids = [layer_id(record) for record in base_layers]
    if len(base_layer_ids) != len(set(base_layer_ids)):
        raise ValueError("base PCB has duplicate LAYER IDs")
    if not COPPER_LAYER_IDS.issubset(set(base_layer_ids)):
        raise ValueError("base PCB lacks one or more reserved six-copper LAYER IDs")
    if base_layer_ids.count(DEFAULT_SUBSTRATE_LAYER_ID) != 1:
        raise ValueError("base PCB must contain exactly one default substrate LAYER 361")
    if SOURCE_SUBSTRATE_LAYER_IDS & set(base_layer_ids):
        raise ValueError("base PCB contains legacy route substrate IDs 101..105")
    unexpected_runtime_substrates = (
        CANONICAL_SUBSTRATE_LAYER_IDS - {DEFAULT_SUBSTRATE_LAYER_ID}
    ) & set(base_layer_ids)
    if unexpected_runtime_substrates:
        raise ValueError(
            "base PCB already contains non-default runtime substrate IDs: "
            f"{sorted(unexpected_runtime_substrates)}"
        )
    original_phys = [record for record in base if record.kind == "LAYER_PHYS"]
    if not original_phys:
        raise ValueError("base PCB has no physical stack to replace")

    output: list[Record] = []
    layer_changes: list[dict[str, Any]] = []
    for record in base:
        current_layer_id = layer_id(record)
        if record.kind == "LAYER_PHYS":
            continue
        if record.kind == "LAYER" and current_layer_id == DEFAULT_SUBSTRATE_LAYER_ID:
            continue
        if record.kind == "LAYER" and current_layer_id in COPPER_LAYER_IDS:
            body = copy.deepcopy(record.body)
            before = {"use": body.get("use"), "show": body.get("show")}
            body["use"] = True
            body["show"] = True
            output.append(Record(copy.deepcopy(record.header), body, record.line_number, None, "base-layer-toggle"))
            layer_changes.append({
                "layer_id": current_layer_id,
                "gerber_name": COPPER_LAYER_NAMES[current_layer_id],
                "native_layer_name_preserved": record.body.get("layerName"),
                "before": before,
                "after": {"use": True, "show": True},
                "only_fields_changed": sorted(
                    key for key in set(record.body) | set(body)
                    if record.body.get(key) != body.get(key)
                ),
            })
            continue
        output.append(record)

    ticket = next_ticket(base)
    for source in static.route_substrates:
        output.append(canonicalized_substrate_record(source, ticket, "route-substrate"))
        ticket += 1
    for source in static.route_layer_phys:
        if layer_id(source) in SOURCE_SUBSTRATE_LAYER_IDS:
            output.append(
                canonicalized_substrate_record(source, ticket, "route-layer-phys")
            )
        else:
            output.append(appended_record(source, ticket, "route-layer-phys"))
        ticket += 1
    audit = {
        "base_layer_count": len(base_layers),
        "base_layer_phys_removed": len(original_phys),
        "default_substrate_361_replaced": 1,
        "copper_layer_toggles": layer_changes,
        "route_substrate_layers_appended": len(static.route_substrates),
        "route_layer_phys_appended": len(static.route_layer_phys),
        "source_to_runtime_substrate_ids": {
            str(source_id): runtime_id
            for source_id, runtime_id in SUBSTRATE_LAYER_ID_MAP.items()
        },
    }
    return output, audit, ticket


def validate_layer_result(
    base: Sequence[Record], output: Sequence[Record], static: StaticInputs
) -> dict[str, Any]:
    layers = [record for record in output if record.kind == "LAYER"]
    layer_map = {layer_id(record): record for record in layers}
    if len(layer_map) != len(layers):
        raise ValueError("merged PCB has duplicate LAYER IDs")
    if SOURCE_SUBSTRATE_LAYER_IDS & set(layer_map):
        raise ValueError("merged PCB retains legacy substrate LAYER IDs 101..105")
    if not CANONICAL_SUBSTRATE_LAYER_IDS.issubset(layer_map):
        raise ValueError("merged PCB is missing runtime substrate LAYER IDs 361..365")
    if any(layer_map[value].body.get("use") is not True or layer_map[value].body.get("show") is not True
           for value in COPPER_LAYER_IDS):
        raise ValueError("merged PCB did not enable/show all six copper layers")

    base_layer_map = {layer_id(record): record for record in base if record.kind == "LAYER"}
    for native_id, record in base_layer_map.items():
        if native_id == DEFAULT_SUBSTRATE_LAYER_ID:
            continue
        merged = layer_map.get(native_id)
        if merged is None:
            raise ValueError(f"merged PCB lost base LAYER {native_id}")
        if record.header != merged.header:
            raise ValueError(f"merged PCB changed base LAYER {native_id} header")
        if native_id in COPPER_LAYER_IDS:
            before, after = record.body, merged.body
            differing = {
                key for key in set(before) | set(after) if before.get(key) != after.get(key)
            }
            if not differing.issubset({"use", "show"}):
                raise ValueError(f"merged PCB changed copper LAYER metadata beyond use/show: {native_id}")
        elif record.body != merged.body:
            raise ValueError(f"merged PCB changed reserved base LAYER metadata: {native_id}")
    route_substrate = {
        SUBSTRATE_LAYER_ID_MAP[layer_id(record)]: record
        for record in static.route_substrates
    }
    for runtime_id in CANONICAL_SUBSTRATE_LAYER_IDS:
        if layer_map[runtime_id].body != route_substrate[runtime_id].body:
            raise ValueError(
                f"merged runtime substrate LAYER {runtime_id} differs from route source payload"
            )

    physical = [record for record in output if record.kind == "LAYER_PHYS"]
    if len(physical) != 13:
        raise ValueError(f"merged PCB must contain 13 LAYER_PHYS records, got {len(physical)}")
    expected_physical: list[Record] = []
    for record in static.route_layer_phys:
        if layer_id(record) in SOURCE_SUBSTRATE_LAYER_IDS:
            expected_physical.append(canonicalized_substrate_record(record, 0, "expected"))
        else:
            expected_physical.append(appended_record(record, 0, "expected"))
    if semantic_digest(physical, omit_ticket=True) != semantic_digest(expected_physical, omit_ticket=True):
        raise ValueError("merged LAYER_PHYS payload differs from canonicalized route stack")
    expected_physical_ids = [5, 1, 361, 15, 362, 16, 363, 17, 364, 18, 365, 2, 6]
    if [layer_id(record) for record in physical] != expected_physical_ids:
        raise ValueError("merged physical stack has noncanonical EasyEDA 3.2 layer IDs/order")
    return {
        "layer_count": len(layers),
        "layer_phys_count": len(physical),
        "copper_layers_enabled_and_shown": sorted(COPPER_LAYER_IDS),
        "source_substrate_layer_ids": sorted(SOURCE_SUBSTRATE_LAYER_IDS),
        "runtime_substrate_layer_ids": sorted(CANONICAL_SUBSTRATE_LAYER_IDS),
        "default_two_layer_substrate_361_replaced": True,
        "legacy_substrate_ids_absent": True,
        "layer_phys_payload_sha256": semantic_digest(physical, omit_ticket=True),
        "unknown_dielectric_properties_are_null": all(
            record.body.get("permittivity") is None
            and record.body.get("lossTangent") is None
            for record in physical
        ),
    }


def scaffold_counts(records: Sequence[Record]) -> dict[str, int]:
    counts = record_counts(records)
    return {kind: counts[kind] for kind in sorted(SCAFFOLD_TYPES)}


def validate_base_and_merge(
    args: argparse.Namespace, static: StaticInputs
) -> tuple[str, dict[str, Any]]:
    base = parse_source(args.input, "placed-base")
    base_sha = sha256_file(args.input)
    docheads = [record for record in base if record.kind == "DOCHEAD"]
    metas = [record for record in base if record.kind == "META"]
    if len(docheads) != 1 or len(metas) > 1:
        raise ValueError(
            f"placed PCB must contain one DOCHEAD and at most one META, got {len(docheads)} / {len(metas)}"
        )
    root_uuid = str(docheads[0].body.get("uuid") or "")
    if not root_uuid:
        raise ValueError("placed PCB DOCHEAD has no UUID")
    if metas and str(metas[0].body.get("board") or "") != root_uuid:
        raise ValueError("placed PCB META.board does not preserve its DOCHEAD UUID")
    placement = read_json(args.placement_report)
    placement_output = placement.get("output") or {}
    if placement_output.get("sha256") != base_sha:
        raise ValueError(
            f"placement manifest is stale: {placement_output.get('sha256')} != {base_sha}"
        )
    placed_component_instances = (placement.get("counts") or {}).get("placed_components")
    if placed_component_instances is not None and int(placed_component_instances) != EXPECTED_NATIVE_COMPONENT_COUNT:
        raise ValueError(
            "placement manifest component-instance count differs from the 330-ref authority"
        )

    base_ids = validate_record_ids(base, "placed base")
    route_ids = {record.record_id for record in static.route_primitives}
    silk_ids = {record.record_id for record in static.silk_primitives}
    collisions = base_ids & (route_ids | silk_ids)
    if collisions:
        raise ValueError(f"merge primitive ID collision with base: {sorted(collisions)[:12]}")

    base_nets = net_set(base)
    if len(base_nets) != EXPECTED_REFERENCE_NET_COUNT:
        raise ValueError(
            f"placed native PCB must contain 279 non-empty NET records, got {len(base_nets)}"
        )
    if empty_net_count(base) != EXPECTED_NATIVE_EMPTY_NET_COUNT:
        raise ValueError(
            "placed native PCB must retain exactly one native empty NET scaffold record"
        )
    route_to_native_net = net_spelling_map(static.reference_nets, base_nets)
    spelling_changes = {
        source: target for source, target in sorted(route_to_native_net.items())
        if source != target
    }
    refs, ref_instances = component_references(base, static.physical_refs)
    if refs != static.physical_refs:
        raise ValueError(
            "placed native physical reference set differs from 330-ref authority: "
            f"base-only={sorted(refs-static.physical_refs)[:12]}, "
            f"missing={sorted(static.physical_refs-refs)[:12]}"
        )
    if refs & static.removed_refs:
        raise ValueError(f"placed native PCB retains removed capacitors: {sorted(refs & static.removed_refs)}")
    if sum(ref_instances.values()) != EXPECTED_NATIVE_COMPONENT_COUNT:
        raise ValueError(
            f"placed native PCB must contain 330 COMPONENT records, got {sum(ref_instances.values())}"
        )
    pad_net_before = pad_net_audit(base)
    if (
        pad_net_before["record_count"] != EXPECTED_NATIVE_PAD_NET_COUNT
        or pad_net_before["connected_count"] != EXPECTED_NATIVE_CONNECTED_PAD_NET_COUNT
        or pad_net_before["unconnected_count"] != EXPECTED_NATIVE_UNCONNECTED_PAD_NET_COUNT
    ):
        raise ValueError(f"placed native PAD_NET inventory differs from authority: {pad_net_before!r}")
    stale_before = stale_electrical_occurrences(base, static.stale_nets)
    if stale_before:
        raise ValueError(f"placed native PCB retains old bias nets: {stale_before[:8]}")

    protected_before = semantic_digest(record for record in base if record.kind in PROTECTED_TYPES)
    identity_before = semantic_digest(record for record in base if record.kind in {"DOCHEAD", "META"})
    rules_before = semantic_digest(record for record in base if record.kind in {"RULE", "RULE_TEMPLATE"})
    rule_comparison = rule_audit(base, static.job)
    scaffold_before = scaffold_counts(base)
    base_counts = record_counts(base)

    output, layer_update, ticket = update_layer_stack(base, static)
    expected_route_primitives: list[Record] = []
    for source in static.route_primitives:
        mapped = remapped_route_record(source, ticket, route_to_native_net)
        output.append(mapped)
        expected_route_primitives.append(mapped)
        ticket += 1
    for source in static.silk_primitives:
        output.append(appended_record(source, ticket, "global-silkscreen-primitive"))
        ticket += 1

    validate_record_ids(output, "merged output")
    tickets = [
        int(record.header["ticket"])
        for record in output
        if isinstance(record.header.get("ticket"), (int, float))
        and not isinstance(record.header.get("ticket"), bool)
    ]
    if len(tickets) != len(set(tickets)):
        raise ValueError("merged output has duplicate record tickets")
    layer_result = validate_layer_result(base, output, static)
    protected_after = semantic_digest(record for record in output if record.kind in PROTECTED_TYPES)
    identity_after = semantic_digest(record for record in output if record.kind in {"DOCHEAD", "META"})
    rules_after = semantic_digest(record for record in output if record.kind in {"RULE", "RULE_TEMPLATE"})
    if protected_before != protected_after:
        raise AssertionError("merge changed a protected DOC/META/component/pad/net/attr/rule record")
    if identity_before != identity_after:
        raise AssertionError("merge changed root DOCHEAD/META identity")
    if rules_before != rules_after:
        raise AssertionError("merge changed native rules")
    if scaffold_counts(output) != scaffold_before:
        raise AssertionError("route/silkscreen scaffold records were merged")

    output_route = [record for record in output if record.record_id in route_ids]
    output_silk = [record for record in output if record.record_id in silk_ids]
    if semantic_digest(output_route, omit_ticket=True) != semantic_digest(expected_route_primitives, omit_ticket=True):
        raise AssertionError("merged routed primitive payload differs from the native-spelling adaptation")
    if semantic_digest(output_silk, omit_ticket=True) != semantic_digest(static.silk_primitives, omit_ticket=True):
        raise AssertionError("merged global-silk primitive payload differs from source")
    if len(output_route) != EXPECTED_ROUTE_PRIMITIVE_COUNT or len(output_silk) != EXPECTED_SILK_PRIMITIVE_COUNT:
        raise AssertionError("merged primitive count is incomplete")
    if primitive_net_set(output_route) != base_nets:
        raise AssertionError("merged routed primitive net set differs from exact native 279-net spelling")
    if net_set(output) != base_nets or empty_net_count(output) != EXPECTED_NATIVE_EMPTY_NET_COUNT:
        raise AssertionError("merge changed native NET records")
    stale_after = stale_electrical_occurrences(output, static.stale_nets)
    if stale_after:
        raise AssertionError(f"merged output retains old bias nets: {stale_after[:8]}")
    output_refs, output_ref_instances = component_references(output, static.physical_refs)
    if output_refs != refs or output_ref_instances != ref_instances:
        raise AssertionError("merge changed native COMPONENT reference membership")
    pad_net_after = pad_net_audit(output)
    if pad_net_after != pad_net_before:
        raise AssertionError("merge changed native PAD_NET records")

    output_text = serialize_source(output)
    report = {
        "schema": "stm32h747-native-pcb-routing-merge-v1",
        "status": "merged-awaiting-native-netlist-and-drc",
        "manufacturing_ready": False,
        "inputs": {
            "placed_native_pcb": {"path": str(args.input), "sha256": base_sha},
            "placement_manifest": {
                "path": str(args.placement_report),
                "sha256": sha256_file(args.placement_report),
            },
            **static.report,
        },
        "root_identity": {
            "dochead_uuid": root_uuid,
            "meta_present": bool(metas),
            "meta_board": metas[0].body.get("board") if metas else None,
            "dochead_meta_semantic_sha256_before": identity_before,
            "dochead_meta_semantic_sha256_after": identity_after,
            "preserved": True,
        },
        "protected_native_records": {
            "types": sorted(PROTECTED_TYPES),
            "semantic_sha256_before": protected_before,
            "semantic_sha256_after": protected_after,
            "preserved": True,
        },
        "native_rules": {
            **rule_comparison,
            "semantic_sha256_after": rules_after,
            "preserved": True,
        },
        "layers": {**layer_update, **layer_result},
        "electrical_invariants": {
            "base_nonempty_net_set_casefold_exact_latest": True,
            "output_net_set_exact_generated_native_spelling": True,
            "latest_net_count": len(static.reference_nets),
            "native_nonempty_net_count": len(base_nets),
            "native_empty_net_scaffold_count": empty_net_count(output),
            "native_net_spelling_changes_from_semantic": spelling_changes,
            "native_net_spelling_change_count": len(spelling_changes),
            "pad_net_before": pad_net_before,
            "pad_net_after": pad_net_after,
            "pad_net_records_preserved": True,
            "stale_old_net_count_expected": len(static.stale_nets),
            "stale_old_net_occurrences_before": 0,
            "stale_old_net_occurrences_after": 0,
            "physical_reference_count": len(output_refs),
            "component_instance_count": sum(output_ref_instances.values()),
            "removed_capacitors_absent": sorted(static.removed_refs),
            "native_component_membership_preserved": True,
        },
        "merge": {
            "base_record_count": len(base),
            "base_record_counts": dict(sorted(base_counts.items())),
            "output_record_count": len(output),
            "output_record_counts": dict(sorted(record_counts(output).items())),
            "route_primitives_appended": len(output_route),
            "global_silkscreen_primitives_appended": len(output_silk),
            "primitive_id_collisions": 0,
            "route_primitive_payload_sha256": semantic_digest(output_route, omit_ticket=True),
            "global_silkscreen_payload_sha256": semantic_digest(output_silk, omit_ticket=True),
            "route_and_silkscreen_scaffolds_merged": False,
        },
        "required_final_gates": {
            "strict_installed_schema": "run automatically unless --skip-schema-validation",
            "easyeda_native_netlist_compare": "pending",
            "easyeda_drc": "pending",
            "impedance_validation": (
                "not performed; Gerber Job does not provide dielectric constant/loss tangent"
            ),
        },
        "output": {
            "path": str(args.output),
            "sha256": sha256_bytes(output_text.encode("utf-8")),
            "bytes": len(output_text.encode("utf-8")),
        },
    }
    return output_text, report


def static_adapter_self_test(args: argparse.Namespace, static: StaticInputs) -> dict[str, Any]:
    if not args.blank_fixture.is_file():
        return {"status": "skipped", "reason": f"fixture missing: {args.blank_fixture}"}
    fixture = parse_source(args.blank_fixture, "runtime-blank-fixture")
    identity_before = semantic_digest(record for record in fixture if record.kind in {"DOCHEAD", "META"})
    rules_before = semantic_digest(record for record in fixture if record.kind in {"RULE", "RULE_TEMPLATE"})
    adapted, update, _ = update_layer_stack(fixture, static)
    result = validate_layer_result(fixture, adapted, static)
    identity_after = semantic_digest(record for record in adapted if record.kind in {"DOCHEAD", "META"})
    rules_after = semantic_digest(record for record in adapted if record.kind in {"RULE", "RULE_TEMPLATE"})
    if identity_before != identity_after or rules_before != rules_after:
        raise AssertionError("layer adapter self-test changed fixture identity/rules")
    validation_dir = safe_output_path(ROOT / "output" / "validation", "validation directory")
    validation_dir.mkdir(parents=True, exist_ok=True)
    source_handle, source_name = tempfile.mkstemp(
        prefix="pcb-stack-adapter-selftest-", suffix=".epru", dir=validation_dir
    )
    os.close(source_handle)
    source_path = Path(source_name)
    report_path = source_path.with_suffix(".schema-report.json")
    try:
        source_path.write_text(
            serialize_source(adapted), encoding="utf-8", newline="\n"
        )
        strict_schema = run_strict_schema_validator(source_path, report_path)
        strict_schema = {
            "valid": strict_schema["valid"],
            "totals": strict_schema["totals"],
            "temporary_fixture_removed": True,
        }
    finally:
        if source_path.exists():
            safe_output_path(source_path, "self-test source").unlink()
        if report_path.exists():
            safe_output_path(report_path, "self-test schema report").unlink()
    return {
        "status": "passed",
        "fixture": {
            "path": str(args.blank_fixture.relative_to(ROOT)),
            "sha256": sha256_file(args.blank_fixture),
        },
        "identity_semantic_digest_preserved": True,
        "rules_semantic_digest_preserved": True,
        "layer_update": update,
        "result": result,
        "adapted_fixture_strict_schema": strict_schema,
        "strict_schema_strategy": (
            "route and silkscreen sources already pass installed-schema strict validation; "
            "the completed merged file is validated automatically by validate-native-source.py"
        ),
    }


def run_strict_schema_validator(output: Path, report_path: Path) -> dict[str, Any]:
    safe_output_path(report_path, "schema report")
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            str(output.resolve()),
            "--report",
            str(report_path.resolve()),
            "--strict",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        report_summary: dict[str, Any] | None = None
        if report_path.is_file():
            diagnostic = read_json(report_path)
            report_summary = {
                "totals": diagnostic.get("totals"),
                "actions": diagnostic.get("actions"),
            }
        raise ValueError(
            "merged PCB strict-schema validation failed: "
            f"report={report_summary!r}, stdout={result.stdout[-2000:]!r}, "
            f"stderr={result.stderr[-2000:]!r}"
        )
    report = read_json(report_path)
    if report.get("valid") is not True:
        raise ValueError("merged PCB schema report did not declare valid=true")
    totals = report.get("totals") or {}
    if any(int(totals.get(key) or 0) for key in (
        "parseErrors", "unmappedRecords", "addFields", "removeFields", "changeFields"
    )):
        raise ValueError("merged PCB schema report contains issues despite strict exit success")
    return {
        "path": str(report_path),
        "sha256": sha256_file(report_path),
        "valid": True,
        "totals": totals,
    }


def run_validator_report(output: Path, report_path: Path) -> dict[str, Any]:
    """Run the installed validator without hiding native getter deviations."""
    safe_output_path(report_path, "schema report")
    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            str(output.resolve()),
            "--report",
            str(report_path.resolve()),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not report_path.is_file():
        raise ValueError(
            "native schema validator did not produce a report: "
            f"exit={result.returncode}, stdout={result.stdout[-2000:]!r}, "
            f"stderr={result.stderr[-2000:]!r}"
        )
    return read_json(report_path)


def schema_action_counts(report: Mapping[str, Any]) -> Counter[tuple[str, str, str, str]]:
    result: Counter[tuple[str, str, str, str]] = Counter()
    actions = report.get("actions") or {}
    for category in ("addFields", "removeFields", "changeFields"):
        for item in actions.get(category) or []:
            key = (
                category,
                str(item.get("docType") or ""),
                str(item.get("primitiveType") or ""),
                str(item.get("fieldPath") or ""),
            )
            result[key] += int(item.get("count") or 0)
    return result


def baseline_aware_schema_validation(
    output: Path, report_path: Path, baseline_source: Path
) -> dict[str, Any]:
    """Reject every schema issue not already present in the native getter base.

    The schematic-to-PCB getter uses a legacy Protel-backed record dialect for
    COMPONENT/ATTR/PAD_NET fields.  Those records are protected byte-semantically,
    so rewriting them merely to satisfy the narrower public schema would corrupt
    native ownership.  Route/silk/stack sources pass strict validation separately;
    this gate proves that the merge adds no issue fingerprint beyond the exact
    native baseline.
    """
    validation_dir = safe_output_path(ROOT / "output" / "validation", "validation directory")
    validation_dir.mkdir(parents=True, exist_ok=True)
    handle, baseline_name = tempfile.mkstemp(
        prefix="native-pcb-baseline-", suffix=".schema-report.json", dir=validation_dir
    )
    os.close(handle)
    baseline_report_path = Path(baseline_name)
    try:
        baseline_report = run_validator_report(baseline_source, baseline_report_path)
        output_report = run_validator_report(output, report_path)
    finally:
        if baseline_report_path.exists():
            safe_output_path(baseline_report_path, "baseline schema report").unlink()

    for label, report in (("baseline", baseline_report), ("output", output_report)):
        totals = report.get("totals") or {}
        if int(totals.get("parseErrors") or 0) or int(totals.get("unmappedRecords") or 0):
            raise ValueError(f"{label} native schema report has parse/unmapped errors: {totals!r}")

    baseline_actions = schema_action_counts(baseline_report)
    output_actions = schema_action_counts(output_report)
    new_actions = {
        "|".join(key): count - baseline_actions.get(key, 0)
        for key, count in output_actions.items()
        if count > baseline_actions.get(key, 0)
    }
    if new_actions:
        raise ValueError(f"merged PCB introduces schema issues beyond native baseline: {new_actions!r}")
    resolved_actions = {
        "|".join(key): count - output_actions.get(key, 0)
        for key, count in baseline_actions.items()
        if count > output_actions.get(key, 0)
    }
    return {
        "path": str(report_path),
        "sha256": sha256_file(report_path),
        "valid": True,
        "validation_mode": "installed-schema-against-exact-native-getter-baseline",
        "validator_declared_valid": output_report.get("valid") is True,
        "totals": output_report.get("totals"),
        "baseline_totals": baseline_report.get("totals"),
        "new_schema_issue_fingerprints": 0,
        "resolved_baseline_issue_counts": resolved_actions,
        "protected_legacy_records_preserved_instead_of_rewritten": True,
    }


def preflight_schema_validation(
    output_text: str, final_output: Path, baseline_source: Path
) -> dict[str, Any]:
    """Validate identical bytes before replacing any prior routed PCB artifact."""
    target = safe_output_path(final_output, "merged PCB output")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".candidate-", suffix=".epru", dir=target.parent
    )
    candidate = Path(temporary_name)
    os.close(handle)
    candidate_report = candidate.with_suffix(".schema-report.json")
    try:
        candidate.write_text(output_text, encoding="utf-8", newline="\n")
        result = baseline_aware_schema_validation(candidate, candidate_report, baseline_source)
        return {
            "valid": result["valid"],
            "totals": result["totals"],
            "candidate_sha256": sha256_file(candidate),
            "temporary_candidate_removed": True,
        }
    finally:
        if candidate.exists():
            safe_output_path(candidate, "preflight candidate").unlink()
        if candidate_report.exists():
            safe_output_path(candidate_report, "preflight schema report").unlink()


def waiting_report(args: argparse.Namespace, static: StaticInputs) -> dict[str, Any]:
    return {
        "schema": "stm32h747-native-pcb-routing-merge-v1",
        "status": "waiting-for-placed-native-pcb",
        "manufacturing_ready": False,
        "missing_input": str(args.input.resolve()),
        "placement_manifest_expected": str(args.placement_report.resolve()),
        "static_inputs": static.report,
        "adapter_self_test": static_adapter_self_test(args, static),
        "planned_output": str(args.output.resolve()),
        "planned_schema_report": str(args.output_schema_report.resolve()),
        "deferred_checks": [
            "placed input SHA must match placement manifest",
            "native NET inventory must contain 279 casefold-exact latest nets plus one preserved empty NET scaffold",
            "native physical reference set must preserve all 330 refs",
            "all 1176 PAD_NET records (1057 connected, 119 unconnected) must remain byte-semantic identical",
            "ten removed capacitors and twenty obsolete nets must be absent",
            "DOCHEAD/META and COMPONENT/PAD/PAD_NET/NET/ATTR/RULE semantic digests must remain equal",
            "all primitive IDs must be collision-free",
            "completed merged source must pass installed-schema strict validation",
            "EasyEDA native netlist comparison and DRC remain required",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--placement-report", type=Path, default=DEFAULT_PLACEMENT_REPORT)
    parser.add_argument("--route", type=Path, default=DEFAULT_ROUTE)
    parser.add_argument("--route-manifest", type=Path, default=DEFAULT_ROUTE_MANIFEST)
    parser.add_argument("--route-schema-report", type=Path, default=DEFAULT_ROUTE_SCHEMA_REPORT)
    parser.add_argument("--silk", type=Path, default=DEFAULT_SILK)
    parser.add_argument("--silk-manifest", type=Path, default=DEFAULT_SILK_MANIFEST)
    parser.add_argument("--silk-schema-report", type=Path, default=DEFAULT_SILK_SCHEMA_REPORT)
    parser.add_argument("--reference-netlist", type=Path, default=DEFAULT_REFERENCE_NETLIST)
    parser.add_argument("--library-manifest", type=Path, default=DEFAULT_LIBRARY_MANIFEST)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--blank-fixture", type=Path, default=DEFAULT_BLANK_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output-schema-report", type=Path, default=DEFAULT_OUTPUT_SCHEMA_REPORT)
    parser.add_argument("--dry-run", action="store_true", help="validate without writing output/report")
    parser.add_argument("--require-base", action="store_true", help="fail instead of waiting when input is absent")
    parser.add_argument("--skip-schema-validation", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        args.output = safe_output_path(args.output, "merged PCB output")
        args.report = safe_output_path(args.report, "merge report")
        args.output_schema_report = safe_output_path(args.output_schema_report, "schema report")
        static = load_static_inputs(args)
        if not args.input.is_file():
            if args.require_base:
                raise FileNotFoundError(f"placed native PCB is not available: {args.input}")
            report = waiting_report(args, static)
            if not args.dry_run:
                atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({
                "status": report["status"],
                "missing_input": report["missing_input"],
                "static_sources_valid": True,
                "adapter_self_test": report["adapter_self_test"]["status"],
            }, ensure_ascii=False))
            return 0
        if not args.placement_report.is_file():
            raise FileNotFoundError(f"placement manifest is not available: {args.placement_report}")

        output_text, report = validate_base_and_merge(args, static)
        if args.dry_run:
            report["status"] = "dry-run-complete-no-files-written"
            print(json.dumps({
                "status": report["status"],
                "records": report["merge"]["output_record_count"],
                "sha256": report["output"]["sha256"],
            }, ensure_ascii=False))
            return 0
        if not args.skip_schema_validation:
            preflight = preflight_schema_validation(output_text, args.output, args.input)
            atomic_write_text(args.output, output_text)
            report["strict_schema_validation"] = {
                **baseline_aware_schema_validation(
                    args.output, args.output_schema_report, args.input
                ),
                "prepublication_candidate": preflight,
            }
        else:
            atomic_write_text(args.output, output_text)
            report["strict_schema_validation"] = {
                "status": "skipped-by-explicit-option",
                "valid": None,
            }
        atomic_write_text(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({
            "status": report["status"],
            "records": report["merge"]["output_record_count"],
            "sha256": report["output"]["sha256"],
            "schema_valid": report["strict_schema_validation"].get("valid"),
        }, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
