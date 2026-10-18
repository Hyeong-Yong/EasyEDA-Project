#!/usr/bin/env python3
"""Statically audit the persisted project-symbol visual repairs.

This script never talks to EasyEDA.  It compares each reopened project-library
capture with its deterministic authoring SYMBOL, audits the batch manifests,
and checks the five saved schematic-page sources for the durable company-name
omission and hidden WIRE/NET font contract.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = ROOT / "output" / "native-libraries" / "symbols"
PLAN_PATH = ROOT / "output" / "validation" / "native-component-link-rebind-plan.json"
VISUAL_PLAN_PATH = ROOT / "output" / "validation" / "native-svg-overlay-repair-plan.json"
CONFIG_PATH = ROOT / "config" / "easyeda-project.json"
VALIDATION_DIR = ROOT / "output" / "validation"
DEFAULT_REPORT = VALIDATION_DIR / "symbol-visual-repair-static-report.json"
CAPTURE_RE = re.compile(r"^native-symbol-visual-repair-(\d{4})-([0-9a-f]{16})\.epru$")
EPSILON = 0.001
EXPECTED_SYMBOLS = 483
EXPECTED_PINS = 1312


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_native(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        divider = line.find("||")
        if divider < 0:
            raise ValueError(f"{rel(path)}:{line_number}: missing native record delimiter")
        head = json.loads(line[:divider])
        raw_body = line[divider + 2 :]
        if raw_body.endswith("|"):
            raw_body = raw_body[:-1]
        body = json.loads(raw_body) if raw_body else None
        records.append({"head": head, "body": body, "line": line_number})
    if not records:
        raise ValueError(f"{rel(path)}: empty native source")
    return records


def document_head(records: list[dict[str, Any]]) -> dict[str, Any]:
    heads = [record["body"] for record in records if record["head"].get("type") == "DOCHEAD"]
    if len(heads) != 1 or not isinstance(heads[0], dict):
        raise ValueError(f"expected exactly one DOCHEAD, found {len(heads)}")
    return heads[0]


def records_by_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        identity = record["head"].get("id")
        if identity is None:
            continue
        if identity in result:
            raise ValueError(f"duplicate native primitive id {identity}")
        result[identity] = record
    return result


def attr_map(records: list[dict[str, Any]], keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        body = record.get("body") or {}
        if record["head"].get("type") == "ATTR" and body.get("key") in keys:
            result[str(body.get("parentId") or "")].append(record)
    return result


def value_counter(records: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str((record.get("body") or {}).get("value") or "") for record in records)


def same_number(a: Any, b: Any) -> bool:
    try:
        return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return a == b


def author_fill_only_polys(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for record in records:
        body = record.get("body") or {}
        if record["head"].get("type") != "POLY" or body.get("fillStyle") != "SOLID" or not body.get("fillColor"):
            continue
        width = body.get("strokeWidth")
        if width is None or same_number(width, 0) or not body.get("strokeColor"):
            targets[record["head"]["id"]] = record
    return targets


def add_error(errors: list[dict[str, Any]], code: str, message: str, **context: Any) -> None:
    errors.append({"code": code, "message": message, **context})


def validate_symbol(
    index: int,
    entry: dict[str, Any],
    author_path: Path,
    capture_path: Path,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    source_uuid = entry["source_uuid"]
    imported_uuid = entry["imported_uuid"]
    context = {"index": index, "title": entry.get("title"), "importedUuid": imported_uuid}
    author = parse_native(author_path)
    capture = parse_native(capture_path)
    author_head = document_head(author)
    capture_head = document_head(capture)
    if author_head.get("docType") != "SYMBOL" or author_head.get("uuid") != source_uuid:
        add_error(errors, "author_dochead", "Author SYMBOL DOCHEAD does not match the rebind map", **context)
    if capture_head.get("docType") != "SYMBOL" or capture_head.get("uuid") != imported_uuid:
        add_error(errors, "capture_dochead", "Reopened SYMBOL DOCHEAD does not match the imported UUID", **context)

    author_ids = records_by_id(author)
    capture_ids = records_by_id(capture)
    author_pins = {identity: record for identity, record in author_ids.items() if record["head"].get("type") == "PIN"}
    capture_pins = {identity: record for identity, record in capture_ids.items() if record["head"].get("type") == "PIN"}
    if set(author_pins) != set(capture_pins):
        add_error(errors, "pin_ids", "PIN primitive IDs differ from the author SYMBOL", **context,
                  missing=sorted(set(author_pins) - set(capture_pins)),
                  extra=sorted(set(capture_pins) - set(author_pins)))

    author_numbers = attr_map(author, {"NUMBER", "Pin Number"})
    capture_numbers = attr_map(capture, {"NUMBER", "Pin Number"})
    author_types = attr_map(author, {"Pin Type"})
    capture_types = attr_map(capture, {"Pin Type"})
    author_names = attr_map(author, {"NAME", "Pin Name"})
    capture_names = attr_map(capture, {"NAME", "Pin Name"})
    preserved_names = 0
    fallback_names = 0

    for pin_id in sorted(set(author_pins) & set(capture_pins)):
        before = author_pins[pin_id]["body"] or {}
        after = capture_pins[pin_id]["body"] or {}
        for field in ("x", "y", "rotation"):
            if not same_number(before.get(field), after.get(field)):
                add_error(errors, "pin_geometry", f"PIN {pin_id} changed {field}", **context,
                          expected=before.get(field), actual=after.get(field))
        if before.get("pinShape") != after.get("pinShape"):
            add_error(errors, "pin_shape", f"PIN {pin_id} changed pinShape", **context,
                      expected=before.get("pinShape"), actual=after.get("pinShape"))
        if not same_number(after.get("length"), EPSILON):
            add_error(errors, "pin_visual_length", f"PIN {pin_id} is not persistence-safe EPS length", **context,
                      actual=after.get("length"))
        if value_counter(author_numbers.get(pin_id, [])) != value_counter(capture_numbers.get(pin_id, [])):
            add_error(errors, "pin_number", f"PIN {pin_id} number changed", **context)
        if value_counter(author_types.get(pin_id, [])) != value_counter(capture_types.get(pin_id, [])):
            add_error(errors, "pin_type", f"PIN {pin_id} electrical type changed", **context)

        before_names = author_names.get(pin_id, [])
        after_names = capture_names.get(pin_id, [])
        if len(before_names) != len(after_names) or not after_names:
            add_error(errors, "pin_name_records", f"PIN {pin_id} Pin Name ATTR identity/count changed", **context)
            continue
        after_by_id = {record["head"].get("id"): record for record in after_names}
        pin_numbers = [str((record.get("body") or {}).get("value") or "") for record in author_numbers.get(pin_id, [])]
        preferred_number = next((value for value in pin_numbers if value.strip()), "")
        for before_name in before_names:
            attr_id = before_name["head"].get("id")
            after_name = after_by_id.get(attr_id)
            if not after_name:
                add_error(errors, "pin_name_id", f"PIN {pin_id} Pin Name ATTR ID changed", **context, attrId=attr_id)
                continue
            original = str((before_name.get("body") or {}).get("value") or "")
            actual_body = after_name.get("body") or {}
            actual = str(actual_body.get("value") or "")
            if original.strip():
                preserved_names += 1
                if actual != original:
                    add_error(errors, "pin_name_preservation", f"PIN {pin_id} non-empty Pin Name changed", **context,
                              expected=original, actual=actual)
            else:
                fallback_names += 1
                valid_fallback = actual == preferred_number if preferred_number else bool(re.fullmatch(r"P\d+", actual))
                if not valid_fallback:
                    add_error(errors, "pin_name_fallback", f"PIN {pin_id} has an invalid empty-name fallback", **context,
                              pinNumber=preferred_number, actual=actual)
            if actual_body.get("keyVisible") is not False or actual_body.get("valueVisible") is not False:
                add_error(errors, "pin_name_visibility", f"PIN {pin_id} repaired Pin Name is not hidden", **context)

    fill_targets = author_fill_only_polys(author)
    for poly_id, before_record in fill_targets.items():
        after_record = capture_ids.get(poly_id)
        after_body = (after_record or {}).get("body") or {}
        if (after_record or {}).get("head", {}).get("type") != "POLY":
            add_error(errors, "filled_poly_id", f"Fill-only POLY {poly_id} is missing", **context)
            continue
        if not same_number(after_body.get("strokeWidth"), EPSILON) or after_body.get("strokeColor") != after_body.get("fillColor"):
            add_error(errors, "filled_poly_style", f"Fill-only POLY {poly_id} lacks the EPS same-color stroke", **context,
                      strokeWidth=after_body.get("strokeWidth"), strokeColor=after_body.get("strokeColor"),
                      fillColor=after_body.get("fillColor"))
        if after_body.get("fillColor") != (before_record.get("body") or {}).get("fillColor"):
            add_error(errors, "filled_poly_color", f"Fill-only POLY {poly_id} fillColor changed", **context)

    return {
        "index": index,
        "title": entry.get("title"),
        "sourceUuid": source_uuid,
        "importedUuid": imported_uuid,
        "author": rel(author_path),
        "capture": rel(capture_path),
        "pins": len(author_pins),
        "fillOnlyPolys": len(fill_targets),
        "preservedNonemptyPinNames": preserved_names,
        "repairedEmptyPinNames": fallback_names,
    }


def validate_pages(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    config = read_json(CONFIG_PATH)
    visual_plan = read_json(VISUAL_PLAN_PATH)
    plan_by_page = {entry["pdf_page"]: entry for entry in visual_plan["pages"]}
    results: list[dict[str, Any]] = []
    for page in config["pages"]:
        page_number = page["sourcePdfPage"]
        repaired_path = VALIDATION_DIR / f"native-root-visual-repair-page-{page_number}.epru"
        wire_path = VALIDATION_DIR / f"native-wire-font-page-{page_number}.epru"
        path = repaired_path if repaired_path.exists() else wire_path
        if not path.exists():
            add_error(errors, "page_capture_missing", f"No saved visual source for PDF page {page_number}")
            results.append({"pdfPage": page_number, "status": "missing"})
            continue
        records = parse_native(path)
        head = document_head(records)
        if head.get("docType") != "SCH_PAGE" or head.get("uuid") != page["uuid"]:
            add_error(errors, "page_dochead", f"PDF page {page_number} DOCHEAD mismatch", path=rel(path))
        by_id = records_by_id(records)
        evidence = plan_by_page[page_number]["strict_company_repair"]
        company_ids = set(evidence["target_ids"]) | set(evidence["already_absent_ids"])
        present_company = sorted(company_ids & set(by_id))
        if len(company_ids) != 15 or present_company:
            add_error(errors, "company_glyphs", f"PDF page {page_number} company glyph omission failed",
                      path=rel(path), contractIds=len(company_ids), present=present_company)
        wire_ids = {identity for identity, record in by_id.items() if record["head"].get("type") == "WIRE"}
        net_attrs = [record for record in records if record["head"].get("type") == "ATTR" and
                     (record.get("body") or {}).get("key") == "NET" and
                     (record.get("body") or {}).get("parentId") in wire_ids]
        expected_nets = int(plan_by_page[page_number]["native"]["wire_net_attr_count"])
        tiny_nets = sum(1 for record in net_attrs if same_number((record.get("body") or {}).get("fontSize"), EPSILON))
        if len(net_attrs) != expected_nets or tiny_nets != len(net_attrs):
            add_error(errors, "wire_net_visuals", f"PDF page {page_number} WIRE/NET EPS-font contract failed",
                      path=rel(path), expected=expected_nets, actual=len(net_attrs), tiny=tiny_nets)
        unrepaired_root_fills = []
        repaired_root_fills = 0
        for identity, record in by_id.items():
            body = record.get("body") or {}
            if record["head"].get("type") != "POLY" or body.get("partId") or body.get("fillStyle") != "SOLID" or not body.get("fillColor"):
                continue
            width = body.get("strokeWidth")
            if width is None or same_number(width, 0) or not body.get("strokeColor"):
                unrepaired_root_fills.append(identity)
            elif same_number(width, EPSILON) and body.get("strokeColor") == body.get("fillColor"):
                repaired_root_fills += 1
        if path == repaired_path and unrepaired_root_fills:
            add_error(errors, "root_filled_polys", f"PDF page {page_number} still has unrepaired root fill-only POLYs",
                      path=rel(path), count=len(unrepaired_root_fills), sample=unrepaired_root_fills[:20])
        results.append({
            "pdfPage": page_number,
            "pageUuid": page["uuid"],
            "source": rel(path),
            "status": "pass",
            "companyGlyphIdsAbsent": len(company_ids),
            "wireNetAttrs": len(net_attrs),
            "wireNetAttrsAtEpsilon": tiny_nets,
            "rootFillRepairCapturePresent": repaired_path.exists(),
            "rootFillPolysAtEpsilon": repaired_root_fills,
            "unrepairedRootFillPolys": len(unrepaired_root_fills),
        })
    return results


def manifest_coverage(plan: list[dict[str, Any]], errors: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {index: entry["imported_uuid"] for index, entry in enumerate(plan)}
    seen: dict[int, tuple[str, str]] = {}
    files = sorted(VALIDATION_DIR.glob("native-symbol-visual-repair-batch-*.json"))
    result_count = 0
    for path in files:
        data = read_json(path)
        for item in data.get("results", []):
            result_count += 1
            index = item.get("index")
            uuid = item.get("symbolUuid")
            if not isinstance(index, int) or expected.get(index) != uuid:
                add_error(errors, "batch_manifest_mapping", "Batch manifest result does not match the rebind plan",
                          path=rel(path), index=index, symbolUuid=uuid)
                continue
            previous = seen.get(index)
            if previous and previous[0] != uuid:
                add_error(errors, "batch_manifest_duplicate", "Batch manifests disagree for one index",
                          index=index, first=previous, second=[uuid, rel(path)])
            seen[index] = (uuid, rel(path))
    return {
        "files": len(files),
        "resultRows": result_count,
        "uniqueIndices": len(seen),
        "missingIndices": sorted(set(expected) - set(seen)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-all", action="store_true", help="fail unless all 483 captures and manifests are present")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    errors: list[dict[str, Any]] = []

    plan_document = read_json(PLAN_PATH)
    plan = plan_document.get("library_map", {}).get("symbol", [])
    if len(plan) != EXPECTED_SYMBOLS:
        add_error(errors, "plan_count", "Rebind plan does not contain exactly 483 symbols", actual=len(plan))
    source_uuids = [entry.get("source_uuid") for entry in plan]
    imported_uuids = [entry.get("imported_uuid") for entry in plan]
    if len(set(source_uuids)) != len(source_uuids) or len(set(imported_uuids)) != len(imported_uuids):
        add_error(errors, "plan_uniqueness", "Source/imported SYMBOL UUIDs are not unique")

    author_by_uuid: dict[str, Path] = {}
    author_pin_total = 0
    for path in sorted(LIBRARY_DIR.glob("*.esym")):
        try:
            records = parse_native(path)
            head = document_head(records)
            uuid = head.get("uuid")
            if uuid in author_by_uuid:
                add_error(errors, "author_duplicate", "Duplicate author SYMBOL UUID", uuid=uuid,
                          paths=[rel(author_by_uuid[uuid]), rel(path)])
            else:
                author_by_uuid[uuid] = path
            author_pin_total += sum(1 for record in records if record["head"].get("type") == "PIN")
        except Exception as exc:  # diagnostics must survive one malformed fixture
            add_error(errors, "author_parse", str(exc), path=rel(path))
    if len(author_by_uuid) != EXPECTED_SYMBOLS:
        add_error(errors, "author_count", "Author library does not contain 483 unique SYMBOL documents",
                  actual=len(author_by_uuid))
    if author_pin_total != EXPECTED_PINS:
        add_error(errors, "author_pin_count", "Author library PIN total changed", expected=EXPECTED_PINS, actual=author_pin_total)

    capture_by_index: dict[int, Path] = {}
    capture_by_uuid: dict[str, Path] = {}
    for path in sorted(VALIDATION_DIR.glob("native-symbol-visual-repair-*.epru")):
        match = CAPTURE_RE.fullmatch(path.name)
        if not match:
            continue
        index, uuid = int(match.group(1)), match.group(2)
        if index in capture_by_index:
            add_error(errors, "capture_duplicate_index", "Multiple reopened captures use one plan index",
                      index=index, paths=[rel(capture_by_index[index]), rel(path)])
        if uuid in capture_by_uuid:
            add_error(errors, "capture_duplicate_uuid", "Multiple reopened captures use one imported UUID",
                      uuid=uuid, paths=[rel(capture_by_uuid[uuid]), rel(path)])
        capture_by_index[index] = path
        capture_by_uuid[uuid] = path

    validated: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for index, entry in enumerate(plan):
        expected_name = f"native-symbol-visual-repair-{index:04d}-{entry['imported_uuid']}.epru"
        capture_path = VALIDATION_DIR / expected_name
        author_path = author_by_uuid.get(entry["source_uuid"])
        if not author_path:
            add_error(errors, "author_missing", "Author SYMBOL is absent for the rebind entry", index=index,
                      sourceUuid=entry["source_uuid"], title=entry.get("title"))
            continue
        if not capture_path.exists():
            missing.append({"index": index, "title": entry.get("title"), "importedUuid": entry["imported_uuid"]})
            continue
        try:
            validated.append(validate_symbol(index, entry, author_path, capture_path, errors))
        except Exception as exc:
            add_error(errors, "symbol_validation_exception", str(exc), index=index,
                      importedUuid=entry["imported_uuid"], capture=rel(capture_path))

    for index, path in capture_by_index.items():
        if index >= len(plan) or path.name != f"native-symbol-visual-repair-{index:04d}-{plan[index]['imported_uuid']}.epru":
            add_error(errors, "unexpected_capture", "Reopened capture filename does not match the rebind plan",
                      index=index, path=rel(path))

    batches = manifest_coverage(plan, errors)
    pages = validate_pages(errors)
    validated_pins = sum(item["pins"] for item in validated)
    validated_fill_polys = sum(item["fillOnlyPolys"] for item in validated)
    if args.require_all:
        if missing:
            add_error(errors, "incomplete_capture_set", "Not all 483 reopened SYMBOL captures are present", missing=len(missing))
        if batches["missingIndices"]:
            add_error(errors, "incomplete_manifest_set", "Batch manifests do not cover all 483 SYMBOL indices",
                      missing=len(batches["missingIndices"]))
        if len(validated) != EXPECTED_SYMBOLS or validated_pins != EXPECTED_PINS:
            add_error(errors, "incomplete_pin_validation", "Complete-set PIN totals are not exact",
                      symbols=len(validated), pins=validated_pins)

    status = "fail" if errors else ("partial_pass" if missing or batches["missingIndices"] else "pass")
    report = {
        "schema": "stm32h747-symbol-visual-repair-static-audit-v1",
        "status": status,
        "requireAll": args.require_all,
        "inputs": {
            "rebindPlan": rel(PLAN_PATH),
            "authorSymbolDirectory": rel(LIBRARY_DIR),
            "visualPlan": rel(VISUAL_PLAN_PATH),
        },
        "summary": {
            "plannedSymbols": len(plan),
            "uniqueSourceUuids": len(set(source_uuids)),
            "uniqueImportedUuids": len(set(imported_uuids)),
            "authorSymbols": len(author_by_uuid),
            "authorPins": author_pin_total,
            "capturedSymbols": len(capture_by_index),
            "validatedSymbols": len(validated),
            "validatedPins": validated_pins,
            "validatedFillOnlyPolys": validated_fill_polys,
            "missingCaptures": len(missing),
            "errors": len(errors),
        },
        "batchManifestCoverage": batches,
        "pageVisualChecks": pages,
        "missingCaptures": missing,
        "symbols": validated,
        "errors": errors,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "report": rel(args.report), **report["summary"]}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
