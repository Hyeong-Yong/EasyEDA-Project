#!/usr/bin/env python3
"""Statically verify durable EasyEDA schematic-to-library bindings.

EasyEDA Pro 3.2.206 keeps a library UUID in two places: child ATTR records and
the JSON strings stored in COMPONENT.body.attrs.*Name.  Its installed decoder
copies DeviceName/FootprintName JSON.uuid back into the corresponding child
attribute block value during load, so an ATTR-only repair is not persistent.

This checker is read-only apart from its JSON report.  It verifies the chosen
five runtime page exports against the final imported library checkpoint and
the generated rebind plan; it never calls EasyEDA or touches the UI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_PLAN = ROOT / "output" / "validation" / "native-component-link-rebind-plan.json"
DEFAULT_CHECKPOINT = (
    ROOT / "output" / "checkpoints" / "STM32H747_final_imported_library_map_20261014.epro2"
)
DEFAULT_REPORT = ROOT / "output" / "validation" / "native-component-link-integrity-report.json"
DEFAULT_PAGES = {
    2: ROOT / "output" / "validation" / "native-u1-harmonized-page-2.epru",
    3: ROOT / "output" / "validation" / "native-u1-harmonized-page-3.epru",
    4: ROOT / "output" / "validation" / "native-durable-page-4.epru",
    5: ROOT / "output" / "validation" / "native-durable-page-5.epru",
    6: ROOT / "output" / "validation" / "native-durable-page-6.epru",
}


class LinkError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_lines(text: str, source: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    result: list[tuple[dict[str, Any], dict[str, Any]]] = []
    lines = text.splitlines()
    for line_number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        terminated = line.endswith("|")
        if not terminated and line_number != len(lines):
            raise LinkError(f"{source}:{line_number}: missing record terminator")
        record_text = line[:-1] if terminated else line
        if "||" not in record_text:
            raise LinkError(f"{source}:{line_number}: malformed record")
        head_text, body_text = record_text.split("||", 1)
        try:
            header = json.loads(head_text)
            body = {} if body_text == "" else json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise LinkError(f"{source}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(header, dict) or not isinstance(body, dict):
            raise LinkError(f"{source}:{line_number}: header/body must be objects")
        result.append((header, body))
    return result


def parse_path(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return parse_lines(path.read_text(encoding="utf-8-sig"), str(path))


def checkpoint_library(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".epru")]
        if len(names) != 1:
            raise LinkError(f"expected one .epru in checkpoint, found {names}")
        records = parse_lines(archive.read(names[0]).decode("utf-8-sig"), f"{path}!/{names[0]}")
    result: dict[str, dict[str, dict[str, Any]]] = {
        "SYMBOL": {}, "FOOTPRINT": {}, "DEVICE": {}
    }
    current: dict[str, Any] | None = None
    for header, body in records:
        if header.get("type") == "DOCHEAD":
            current = {"head": body, "meta": None}
            doc_type = str(body.get("docType") or "")
            uuid = str(body.get("uuid") or "")
            if doc_type in result and uuid:
                # Multiple checkpoint generations may share a UUID only if
                # they are literally the same document identity.  Keep the
                # latest stream occurrence; plan metadata is checked below.
                result[doc_type][uuid] = current
            continue
        if current is not None and header.get("type") == "META":
            current["meta"] = body
    return result


def page_indexes(
    records: list[tuple[dict[str, Any], dict[str, Any]]]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    components: dict[str, dict[str, Any]] = {}
    attrs: dict[str, dict[str, dict[str, Any]]] = {}
    for header, body in records:
        if header.get("type") == "COMPONENT":
            components[str(header.get("id") or "")] = body
    for header, body in records:
        if header.get("type") != "ATTR":
            continue
        parent = str(body.get("parentId") or "")
        if parent not in components:
            continue
        key = str(body.get("key") or "")
        attrs.setdefault(parent, {})[key] = {"header": header, "body": body}
    return components, attrs


def safe_report_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise LinkError(f"report must be below {OUTPUT_ROOT}: {resolved}") from exc
    if not relative.parts:
        raise LinkError("report cannot be the output root")
    return resolved


def atomic_write(path: Path, text: str) -> None:
    target = safe_report_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary_name, target)
    finally:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass


def parse_page_overrides(values: Sequence[str]) -> dict[int, Path]:
    result = dict(DEFAULT_PAGES)
    for value in values:
        if "=" not in value:
            raise LinkError(f"--page must be NUMBER=PATH, got {value!r}")
        number_text, path_text = value.split("=", 1)
        try:
            number = int(number_text)
        except ValueError as exc:
            raise LinkError(f"invalid page number {number_text!r}") from exc
        if number not in DEFAULT_PAGES:
            raise LinkError(f"page must be one of 2,3,4,5,6; got {number}")
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        result[number] = candidate
    return {number: path.resolve() for number, path in result.items()}


def validate(args: argparse.Namespace) -> dict[str, Any]:
    plan_path = args.plan.resolve()
    checkpoint_path = args.checkpoint.resolve()
    pages = parse_page_overrides(args.page)
    for path in [plan_path, checkpoint_path, *pages.values()]:
        if not path.exists():
            raise LinkError(f"missing input: {path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    library = checkpoint_library(checkpoint_path)
    errors: list[dict[str, Any]] = []
    checks = Counter()

    library_rows: dict[str, dict[str, Any]] = {}
    category_to_type = {"symbol": "SYMBOL", "footprint": "FOOTPRINT", "device": "DEVICE"}
    for category, doc_type in category_to_type.items():
        for row in (plan.get("library_map") or {}).get(category, []):
            actual_uuid = str(row.get("imported_uuid") or "")
            document = library[doc_type].get(actual_uuid)
            if document is None:
                errors.append({"kind": "missing_library_document", "doc_type": doc_type, "uuid": actual_uuid})
                continue
            meta = document.get("meta") or {}
            if meta.get("title") != row.get("title") or meta.get("source") != row.get("source"):
                errors.append({
                    "kind": "library_metadata_mismatch", "doc_type": doc_type,
                    "uuid": actual_uuid, "expected_title": row.get("title"),
                    "actual_title": meta.get("title"), "expected_source": row.get("source"),
                    "actual_source": meta.get("source"),
                })
            library_rows[actual_uuid] = {"doc_type": doc_type, **row}
            checks[f"library_{category}"] += 1

    plan_pages = {int(item["page"]): item for item in plan.get("pages", [])}
    page_reports: list[dict[str, Any]] = []
    for page_number in sorted(pages):
        page_path = pages[page_number]
        page_plan = plan_pages.get(page_number)
        if page_plan is None:
            raise LinkError(f"plan has no page {page_number}")
        records = parse_path(page_path)
        components, attrs = page_indexes(records)
        local = Counter()
        for instance in page_plan.get("instances", []):
            component_id = str(instance["component_id"])
            component = components.get(component_id)
            if component is None:
                errors.append({
                    "kind": "missing_component", "page": page_number,
                    "reference": instance["reference"], "component_id": component_id,
                })
                continue
            component_attrs = attrs.get(component_id, {})
            expected_by_key = {item["key"]: item for item in instance.get("changes", [])}
            for key, change in expected_by_key.items():
                child = component_attrs.get(key)
                if child is None:
                    errors.append({
                        "kind": "missing_child_attr", "page": page_number,
                        "reference": instance["reference"], "key": key,
                    })
                    continue
                if child["header"].get("id") != change.get("attribute_id"):
                    errors.append({
                        "kind": "child_attr_id_mismatch", "page": page_number,
                        "reference": instance["reference"], "key": key,
                        "expected": change.get("attribute_id"), "actual": child["header"].get("id"),
                    })
                actual_uuid = str(child["body"].get("value") or "")
                if actual_uuid != change.get("new_uuid"):
                    errors.append({
                        "kind": "child_uuid_mismatch", "page": page_number,
                        "reference": instance["reference"], "key": key,
                        "expected": change.get("new_uuid"), "actual": actual_uuid,
                    })
                expected_type = {"Device": "DEVICE", "Footprint": "FOOTPRINT", "Symbol": "SYMBOL"}[key]
                if (library_rows.get(actual_uuid) or {}).get("doc_type") != expected_type:
                    errors.append({
                        "kind": "child_library_target_missing", "page": page_number,
                        "reference": instance["reference"], "key": key, "uuid": actual_uuid,
                    })
                local[f"child_{key}"] += 1

            body_attrs = component.get("attrs") or {}
            if not isinstance(body_attrs, dict):
                errors.append({
                    "kind": "component_body_attrs_not_object", "page": page_number,
                    "reference": instance["reference"],
                })
                continue
            for body_change in instance.get("component_body_name_json", []):
                key = str(body_change["key"])
                raw = body_attrs.get(key)
                if raw in (None, ""):
                    if body_change.get("required_at_runtime"):
                        errors.append({
                            "kind": "missing_required_body_name", "page": page_number,
                            "reference": instance["reference"], "key": key,
                        })
                    else:
                        local[f"optional_{key}_absent"] += 1
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, json.JSONDecodeError) as exc:
                    errors.append({
                        "kind": "invalid_body_name_json", "page": page_number,
                        "reference": instance["reference"], "key": key, "error": str(exc),
                    })
                    continue
                actual_uuid = str(payload.get("uuid") or "")
                if actual_uuid != body_change.get("new_uuid"):
                    errors.append({
                        "kind": "body_uuid_mismatch", "page": page_number,
                        "reference": instance["reference"], "key": key,
                        "expected": body_change.get("new_uuid"), "actual": actual_uuid,
                    })
                if payload.get("name") != body_change.get("name") or payload.get("source") != body_change.get("source"):
                    errors.append({
                        "kind": "body_provenance_mismatch", "page": page_number,
                        "reference": instance["reference"], "key": key,
                        "expected_name": body_change.get("name"), "actual_name": payload.get("name"),
                        "expected_source": body_change.get("source"), "actual_source": payload.get("source"),
                    })
                child_key = key.removesuffix("Name")
                if child_key in expected_by_key:
                    child_uuid = str(component_attrs.get(child_key, {}).get("body", {}).get("value") or "")
                    if child_uuid != actual_uuid:
                        errors.append({
                            "kind": "body_child_disagreement", "page": page_number,
                            "reference": instance["reference"], "key": key,
                            "body_uuid": actual_uuid, "child_uuid": child_uuid,
                        })
                local[f"body_{key}"] += 1

            if instance.get("role") != "physical" and body_attrs.get("FootprintName") not in (None, ""):
                errors.append({
                    "kind": "nonphysical_footprint_name", "page": page_number,
                    "reference": instance["reference"], "value": body_attrs.get("FootprintName"),
                })
            local["instances"] += 1

        checks.update(local)
        page_reports.append({
            "page": page_number,
            "sheet_name": page_plan.get("sheet_name"),
            "path": str(page_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(page_path),
            "counts": dict(sorted(local.items())),
        })

    expected_checks = {
        "instances": 486,
        "child_Device": 486,
        "child_Footprint": 333,
        "child_Symbol": 486,
        "body_DeviceName": 486,
        "body_FootprintName": 333,
    }
    for key, expected in expected_checks.items():
        if checks[key] != expected:
            errors.append({"kind": "count_mismatch", "key": key, "expected": expected, "actual": checks[key]})

    report = {
        "schema": "stm32h747-native-component-link-integrity-v1",
        "status": "pass" if not errors else "fail",
        "read_only_inputs": True,
        "decoder_contract": (
            "EasyEDA Pro 3.2.206 overrideSchSymbolAttrsByNameSource requires "
            "DeviceName/FootprintName JSON.uuid to equal the imported library UUID; "
            "child ATTR repair alone is not durable."
        ),
        "sources": {
            "plan": {"path": str(plan_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(plan_path)},
            "checkpoint": {"path": str(checkpoint_path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(checkpoint_path)},
        },
        "counts": dict(sorted(checks.items())),
        "pages": page_reports,
        "errors": errors,
    }
    atomic_write(args.report, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--page", action="append", default=[], help="override one source as NUMBER=PATH")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--report-only", action="store_true", help="write failures but return exit status zero")
    args = parser.parse_args(argv)
    try:
        report = validate(args)
    except (OSError, KeyError, TypeError, ValueError, LinkError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps({"status": report["status"], "counts": report["counts"], "errors": len(report["errors"])}, ensure_ascii=False))
    return 0 if report["status"] == "pass" or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
