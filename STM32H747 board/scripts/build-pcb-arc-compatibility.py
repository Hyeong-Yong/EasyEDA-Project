#!/usr/bin/env python3
"""Build an optional same-ID ARC-to-POLY PCB compatibility candidate offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "output" / "native-pcb" / "native-pcb-routed.epru"
DEFAULT_MERGE_MANIFEST = (
    ROOT / "output" / "native-pcb" / "native-pcb-routing-merge-manifest.json"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "native-pcb" / "native-pcb-routed-poly-compatible.epru"
)
DEFAULT_MANIFEST = (
    ROOT
    / "output"
    / "native-pcb"
    / "native-pcb-routed-poly-compatibility-manifest.json"
)
EXPECTED_ARCS = 2184
HEX16 = set("0123456789abcdef")
POLY_COPY_KEYS = (
    "partitionId",
    "groupId",
    "netName",
    "layerId",
    "width",
    "locked",
    "zIndex",
    "specialColor",
    "number",
)


class CompatibilityError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    return sha256_bytes(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    )


def parse_line(line: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    text = line[:-1] if line.endswith("|") else line
    divider = text.find("||")
    if divider < 0:
        raise CompatibilityError(f"missing || at line {line_number}")
    try:
        head = json.loads(text[:divider])
        body = json.loads(text[divider + 2 :])
    except json.JSONDecodeError as exc:
        raise CompatibilityError(f"invalid JSON at line {line_number}: {exc}") from exc
    if not isinstance(head, dict) or not isinstance(body, dict):
        raise CompatibilityError(f"non-object record at line {line_number}")
    return head, body


def serialize_record(head: dict[str, Any], body: dict[str, Any]) -> str:
    return (
        json.dumps(head, separators=(",", ":"), ensure_ascii=False)
        + "||"
        + json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        + "|"
    )


def build(args: argparse.Namespace) -> dict[str, Any]:
    source_path = args.input.resolve()
    merge_manifest_path = args.merge_manifest.resolve()
    output_path = args.output.resolve()
    manifest_path = args.manifest.resolve()
    merge_manifest = json.loads(merge_manifest_path.read_text(encoding="utf-8"))
    expected_source_hash = str(merge_manifest.get("output", {}).get("sha256", ""))
    source_hash = sha256_file(source_path)
    if not expected_source_hash or source_hash != expected_source_hash:
        raise CompatibilityError(
            f"routed source hash {source_hash} does not match merge manifest {expected_source_hash}"
        )

    source_text = source_path.read_text(encoding="utf-8-sig")
    source_lines = [line for line in source_text.splitlines() if line]
    output_lines: list[str] = []
    input_counts: Counter[str] = Counter()
    output_counts: Counter[str] = Counter()
    seen_ids: set[str] = set()
    arc_ids: list[str] = []
    layer_counts: Counter[str] = Counter()
    net_counts: Counter[str] = Counter()
    angles: list[float] = []
    widths: list[float] = []
    non_arc_input: list[str] = []
    non_arc_output: list[str] = []
    first_dochead: dict[str, Any] | None = None

    for line_number, line in enumerate(source_lines, 1):
        head, body = parse_line(line, line_number)
        record_type = str(head.get("type", ""))
        input_counts[record_type] += 1
        if record_type == "DOCHEAD":
            if first_dochead is not None:
                raise CompatibilityError("routed source contains more than one DOCHEAD")
            first_dochead = body
        record_id = head.get("id")
        if record_id:
            record_id = str(record_id)
            if record_id in seen_ids:
                raise CompatibilityError(f"duplicate record id {record_id}")
            seen_ids.add(record_id)

        if record_type != "ARC":
            output_lines.append(line)
            non_arc_input.append(line)
            non_arc_output.append(line)
            output_counts[record_type] += 1
            continue

        if not record_id or len(record_id) != 16 or any(char not in HEX16 for char in record_id):
            raise CompatibilityError(f"ARC at line {line_number} lacks a 16-hex id")
        required = (
            "layerId",
            "startX",
            "startY",
            "endX",
            "endY",
            "angle",
            "width",
            "locked",
            "zIndex",
        )
        missing = [key for key in required if key not in body]
        if missing:
            raise CompatibilityError(f"ARC {record_id} lacks fields {missing}")
        numeric = (
            body["startX"],
            body["startY"],
            body["endX"],
            body["endY"],
            body["angle"],
            body["width"],
        )
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in numeric):
            raise CompatibilityError(f"ARC {record_id} contains non-finite geometry")
        if float(body["angle"]) == 0.0 or float(body["width"]) <= 0.0:
            raise CompatibilityError(f"ARC {record_id} has zero angle or non-positive width")

        poly_head = dict(head)
        poly_head["type"] = "POLY"
        poly_body = {key: body[key] for key in POLY_COPY_KEYS if key in body}
        poly_body["path"] = [
            body["startX"],
            body["startY"],
            "ARC",
            body["angle"],
            body["endX"],
            body["endY"],
        ]
        poly_body["polyType"] = "NORMAL"
        output_lines.append(serialize_record(poly_head, poly_body))
        output_counts["POLY"] += 1
        arc_ids.append(record_id)
        layer_counts[str(body["layerId"])] += 1
        net_counts[str(body.get("netName", ""))] += 1
        angles.append(float(body["angle"]))
        widths.append(float(body["width"]))

    if first_dochead is None or first_dochead.get("docType") != "PCB":
        raise CompatibilityError("source is not a single PCB document")
    if input_counts.get("ARC", 0) != EXPECTED_ARCS:
        raise CompatibilityError(
            f"expected {EXPECTED_ARCS} routed ARC rows, found {input_counts.get('ARC', 0)}"
        )
    if input_counts.get("POLY", 0) != 0:
        raise CompatibilityError("baseline routed source unexpectedly contains POLY rows")
    if len(set(arc_ids)) != EXPECTED_ARCS:
        raise CompatibilityError("transformed ARC IDs are not unique")
    if output_counts.get("ARC", 0) != 0 or output_counts.get("POLY", 0) != EXPECTED_ARCS:
        raise CompatibilityError("output ARC/POLY totals failed")
    if len(output_lines) != len(source_lines):
        raise CompatibilityError("one-to-one conversion changed record count")
    if non_arc_input != non_arc_output:
        raise CompatibilityError("non-ARC records changed")

    output_text = "\n".join(output_lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8", newline="\n")
    output_hash = sha256_file(output_path)
    if output_path.read_text(encoding="utf-8") != output_text:
        raise CompatibilityError("written candidate does not round-trip byte-for-byte")

    manifest = {
        "schema": "stm32h747-pcb-arc-compatibility-plan-v1",
        "status": "PASS",
        "purpose": (
            "Optional installed-3.2 compatibility candidate: replace every routed top-level "
            "ARC with a same-ID NORMAL POLY open ARC without deleting or changing other rows."
        ),
        "notAppliedToEasyEda": True,
        "fallbackOnly": True,
        "semanticCaveat": (
            "Installed 3.2 parses NORMAL POLY as a Polygon model whose type is Line. "
            "Net, layer, and stroke geometry fields are retained, but the runtime model class "
            "is Polygon rather than ArcTrack. Track-only connectivity, ratline completion, "
            "length/equal-length rules, shove routing, and IPC-2581 net export can exclude it."
        ),
        "requiredBeforeUse": [
            "Try the canonical routed ARC source first.",
            "Use this fallback only if the canonical source fails specifically on routed ARC records.",
            "After import, require zero rejected records, 2184 loaded Polygon replacements, exact endpoint checks, live connectivity/net-length validation, full native DRC, and manufacturing-export verification.",
            "Do not treat static geometric equivalence or retained netName fields as electrical/manufacturing approval.",
        ],
        "input": {
            "path": source_path.relative_to(ROOT).as_posix(),
            "sha256": source_hash,
            "bytes": source_path.stat().st_size,
            "mergeManifest": merge_manifest_path.relative_to(ROOT).as_posix(),
            "mergeManifestSha256": sha256_file(merge_manifest_path),
        },
        "output": {
            "path": output_path.relative_to(ROOT).as_posix(),
            "sha256": output_hash,
            "bytes": output_path.stat().st_size,
        },
        "identity": {
            "docType": first_dochead.get("docType"),
            "uuid": first_dochead.get("uuid"),
            "client": first_dochead.get("client"),
        },
        "invariants": {
            "sameRecordCount": len(output_lines) == len(source_lines),
            "sameIdSet": True,
            "sameArcIdToPolyId": True,
            "nonArcLinesByteIdentical": True,
            "recordsDeleted": 0,
            "unitConversion": False,
            "sourceCoordinatesPreserved": True,
            "sourceAnglesPreserved": True,
            "sourceWidthsPreserved": True,
            "sourceLayersPreserved": True,
            "sourceNetsPreserved": True,
        },
        "counts": {
            "inputRecords": len(source_lines),
            "outputRecords": len(output_lines),
            "inputTypes": dict(sorted(input_counts.items())),
            "outputTypes": dict(sorted(output_counts.items())),
            "convertedArcs": len(arc_ids),
            "outputArcs": output_counts.get("ARC", 0),
            "outputPolys": output_counts.get("POLY", 0),
            "layers": dict(sorted(layer_counts.items(), key=lambda item: int(item[0]))),
            "uniqueNets": len(net_counts),
        },
        "geometry": {
            "polyType": "NORMAL",
            "path": ["startX", "startY", "ARC", "angle", "endX", "endY"],
            "angleMin": min(angles),
            "angleMax": max(angles),
            "widthMin": min(widths),
            "widthMax": max(widths),
            "convertedIdDigest": canonical_digest(sorted(arc_ids)),
        },
        "nonArcLineDigest": sha256_bytes("\n".join(non_arc_input).encode("utf-8")),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--merge-manifest", type=Path, default=DEFAULT_MERGE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build(args)
    print(json.dumps({"manifest": str(args.manifest), **manifest["counts"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
