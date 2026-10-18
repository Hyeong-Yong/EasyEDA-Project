#!/usr/bin/env python3
"""Build an offline EasyEDA Pro component-library UUID rebind plan.

EasyEDA Pro remaps project-local SYMBOL/FOOTPRINT/DEVICE DOCHEAD UUIDs when an
epro2 archive is imported.  In 3.2.206, schematic COMPONENT child ATTR records
and COMPONENT.body.attrs *Name JSON can retain different UUID generations.
The installed decoder then overwrites Device/Footprint ATTR block values from
DeviceName/FootprintName JSON, so changing child ATTR records alone is not a
durable repair.  This script derives the authoritative mapping from an
exported recovery checkpoint and emits a page-by-page, idempotent repair plan
for both representations.

It never talks to EasyEDA.  The generated JavaScript defines a helper but does
not invoke it; the application/API writer remains responsible for opening the
intended page, applying one page plan, validating, and saving.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


BOARD_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKPOINT = (
    BOARD_ROOT
    / "output"
    / "checkpoints"
    / "STM32H747_final_imported_library_map_20261014.epro2"
)
DEFAULT_SCHEMATICS = BOARD_ROOT / "output" / "native-schematics"
DEFAULT_DEVICES = BOARD_ROOT / "output" / "native-libraries" / "devices.json"
DEFAULT_OUTPUT = (
    BOARD_ROOT / "output" / "validation" / "native-component-link-rebind-plan.json"
)
DEFAULT_API_HELPER = (
    BOARD_ROOT / "output" / "validation" / "native-component-link-rebind-api.js"
)

HEX16 = re.compile(r"^[0-9a-f]{16}$")
PAGE_FILE = re.compile(r"^(\d{2})_(.+)\.epru$")


class PlanError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_record(line: str, source: str, line_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    text = line.rstrip("\r\n")
    if not text:
        raise PlanError(f"blank record in {source}:{line_number}")
    if text.endswith("|"):
        text = text[:-1]
    try:
        header_text, body_text = text.split("||", 1)
        # EasyEDA 3.2.206 may serialize body-less project records (for
        # example the empty NET and RULE_SELECTOR records in an exported
        # checkpoint) as ``<header>|||`` rather than ``<header>||{}|``.
        # They are irrelevant to this library/component mapping pass, but
        # accepting them keeps the archive parser faithful to the runtime
        # format instead of rejecting an otherwise valid checkpoint.
        body = {} if body_text == "" else json.loads(body_text)
        return json.loads(header_text), body
    except (ValueError, json.JSONDecodeError) as exc:
        raise PlanError(f"invalid epru record in {source}:{line_number}: {exc}") from exc


def parse_documents(lines: Iterable[str], source: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line_number, line in enumerate(lines, 1):
        header, body = parse_record(line, source, line_number)
        record_type = header.get("type")
        if record_type == "DOCHEAD":
            current = {
                "line": line_number,
                "head": body,
                "meta": None,
                "records": [],
                "counts": Counter(),
            }
            documents.append(current)
            continue
        if current is None:
            raise PlanError(f"record before DOCHEAD in {source}:{line_number}")
        current["records"].append((header, body))
        current["counts"][record_type] += 1
        if record_type == "META":
            current["meta"] = body
    return documents


def load_checkpoint_documents(path: Path) -> tuple[list[dict[str, Any]], str]:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".epru")]
        if len(names) != 1:
            raise PlanError(f"expected one .epru in {path}, found {names}")
        member = names[0]
        text = archive.read(member).decode("utf-8-sig")
    return parse_documents(text.splitlines(), f"{path}!/{member}"), member


def load_single_document(path: Path) -> dict[str, Any]:
    documents = parse_documents(path.read_text(encoding="utf-8-sig").splitlines(), str(path))
    if len(documents) != 1:
        raise PlanError(f"expected one document in {path}, found {len(documents)}")
    return documents[0]


def numeric_version(document: dict[str, Any]) -> int:
    value = document["head"].get("version", 0)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlanError(f"invalid document version {value!r} at line {document['line']}") from exc


def source_uuid(document: dict[str, Any]) -> str:
    meta = document.get("meta") or {}
    return str(meta.get("source", "")).split("|", 1)[0]


def select_latest_library_documents(
    documents: list[dict[str, Any]], expected_ids: dict[str, set[str]]
) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, Any]]:
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        doc_type = document["head"].get("docType")
        if doc_type not in expected_ids or document.get("meta") is None:
            continue
        old_uuid = source_uuid(document)
        if old_uuid in expected_ids[doc_type]:
            candidates[(doc_type, old_uuid)].append(document)

    selected: dict[str, dict[str, dict[str, Any]]] = {
        doc_type: {} for doc_type in expected_ids
    }
    candidate_histogram: Counter[int] = Counter()
    for doc_type, old_ids in expected_ids.items():
        for old_uuid in sorted(old_ids):
            options = candidates.get((doc_type, old_uuid), [])
            if not options:
                raise PlanError(f"checkpoint has no {doc_type} sourced from {old_uuid}")
            candidate_histogram[len(options)] += 1
            options = sorted(options, key=lambda item: (numeric_version(item), item["line"]))
            winner = options[-1]
            actual_uuid = winner["head"].get("uuid")
            if not isinstance(actual_uuid, str) or not HEX16.fullmatch(actual_uuid):
                raise PlanError(f"invalid imported {doc_type} UUID {actual_uuid!r}")
            if len(options) > 1 and numeric_version(options[-2]) == numeric_version(winner):
                raise PlanError(f"ambiguous latest {doc_type} for source {old_uuid}")
            selected[doc_type][old_uuid] = winner

    summary = {
        "candidate_count_histogram": {
            str(key): value for key, value in sorted(candidate_histogram.items())
        },
        "selected_counts": {
            doc_type: len(items) for doc_type, items in selected.items()
        },
        "selected_version_ranges": {
            doc_type: {
                "minimum": min(numeric_version(item) for item in items.values()),
                "maximum": max(numeric_version(item) for item in items.values()),
            }
            for doc_type, items in selected.items()
        },
    }
    return selected, summary


def component_index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for header, body in document["records"]:
        if header.get("type") == "COMPONENT":
            components[header["id"]] = {"header": header, "body": body, "attrs": {}}
    for header, body in document["records"]:
        if header.get("type") != "ATTR":
            continue
        parent_id = body.get("parentId")
        if parent_id in components:
            key = body.get("key")
            if key in components[parent_id]["attrs"]:
                raise PlanError(f"duplicate component ATTR key {key!r} for {parent_id}")
            components[parent_id]["attrs"][key] = {"header": header, "body": body}
    return components


def latest_checkpoint_pages(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    pages: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        if document["head"].get("docType") != "SCH_PAGE":
            continue
        if document["counts"].get("COMPONENT", 0) <= 1:
            continue
        title = str((document.get("meta") or {}).get("title", ""))
        if title:
            pages[title].append(document)
    return {
        title: max(items, key=lambda item: (numeric_version(item), item["line"]))
        for title, items in pages.items()
    }


def attr_change(
    component_id: str,
    attrs: dict[str, dict[str, Any]],
    key: str,
    expected_old: str,
    new_value: str,
) -> dict[str, Any]:
    item = attrs.get(key)
    if item is None:
        raise PlanError(f"component {component_id} lacks required {key} ATTR")
    body = item["body"]
    actual_old = body.get("value")
    if actual_old != expected_old:
        raise PlanError(
            f"component {component_id} {key} is {actual_old!r}, expected {expected_old!r}"
        )
    return {
        "attribute_id": item["header"]["id"],
        "key": key,
        "old_uuid": expected_old,
        "new_uuid": new_value,
    }


def body_name_change(
    component_id: str,
    component_body: dict[str, Any],
    key: str,
    expected_old: str,
    new_value: str,
    *,
    required_at_runtime: bool,
) -> dict[str, Any]:
    raw_value = (component_body.get("attrs") or {}).get(key)
    if raw_value in (None, ""):
        if required_at_runtime:
            raise PlanError(f"component {component_id} lacks required body.attrs.{key}")
        return {
            "key": key,
            "present_in_generated_source": False,
            "required_at_runtime": False,
            "old_uuid": expected_old,
            "new_uuid": new_value,
        }
    if not isinstance(raw_value, str):
        raise PlanError(f"component {component_id} body.attrs.{key} is not JSON text")
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise PlanError(
            f"component {component_id} body.attrs.{key} is invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PlanError(f"component {component_id} body.attrs.{key} is not a JSON object")
    if payload.get("uuid") != expected_old:
        raise PlanError(
            f"component {component_id} body.attrs.{key}.uuid is "
            f"{payload.get('uuid')!r}, expected {expected_old!r}"
        )
    return {
        "key": key,
        "present_in_generated_source": True,
        "required_at_runtime": required_at_runtime,
        "old_uuid": expected_old,
        "new_uuid": new_value,
        "name": payload.get("name", ""),
        "source": payload.get("source", ""),
    }


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    devices_payload = json.loads(args.devices.read_text(encoding="utf-8-sig"))
    all_instances = devices_payload.get("instances", [])
    # Canonicalize every project-local library reference, including 146 #PWR
    # net flags and the seven #FLG power drivers ported to native NET_FLAG.
    # A dangling Device UUID on either may not affect immediate PCB conversion,
    # but it breaks later SDK property/library reads.
    targets = list(all_instances)
    if len(targets) != 486:
        raise PlanError(f"expected 486 target symbol instances, found {len(targets)}")

    target_by_key: dict[tuple[int, str, str], dict[str, Any]] = {}
    for instance in targets:
        key = (
            int(instance["page"]),
            str(instance["base_reference"]),
            str(instance["native_part_id"]),
        )
        if key in target_by_key:
            raise PlanError(f"duplicate target instance key {key}")
        target_by_key[key] = instance

    expected_ids = {
        "DEVICE": {str(item["device_uuid"]) for item in targets},
        "SYMBOL": {str(item["symbol_uuid"]) for item in targets},
        "FOOTPRINT": {
            str(item["footprint_uuid"]) for item in targets if item.get("footprint_uuid")
        },
    }

    checkpoint_documents, checkpoint_member = load_checkpoint_documents(args.checkpoint)
    selected, selection_summary = select_latest_library_documents(
        checkpoint_documents, expected_ids
    )
    checkpoint_pages = latest_checkpoint_pages(checkpoint_documents)

    page_plans: list[dict[str, Any]] = []
    matched_keys: set[tuple[int, str, str]] = set()
    checkpoint_checks = Counter()

    for source_path in sorted(args.schematics_dir.glob("*.epru")):
        match = PAGE_FILE.match(source_path.name)
        if not match:
            continue
        page_number = int(match.group(1))
        source_document = load_single_document(source_path)
        sheet_name = str((source_document.get("meta") or {}).get("title", ""))
        if sheet_name not in checkpoint_pages:
            raise PlanError(f"no current checkpoint page found for {sheet_name}")
        checkpoint_page = checkpoint_pages[sheet_name]
        checkpoint_components = component_index(checkpoint_page)
        instances: list[dict[str, Any]] = []

        for component_id, component in component_index(source_document).items():
            attrs = component["attrs"]
            if "Designator" not in attrs:
                continue
            designator = str(attrs["Designator"]["body"].get("value", ""))
            part_id = str(component["body"].get("partId", ""))
            target_key = (page_number, designator, part_id)
            instance = target_by_key.get(target_key)
            if instance is None:
                continue
            matched_keys.add(target_key)

            old_device = str(instance["device_uuid"])
            old_symbol = str(instance["symbol_uuid"])
            old_footprint = instance.get("footprint_uuid")
            device_document = selected["DEVICE"][old_device]
            symbol_document = selected["SYMBOL"][old_symbol]
            device_meta = device_document["meta"]
            device_attributes = device_meta.get("attributes", {})
            new_device = str(device_document["head"]["uuid"])
            new_symbol = str(device_attributes.get("Symbol", ""))
            expected_new_symbol = str(symbol_document["head"]["uuid"])
            if new_symbol != expected_new_symbol:
                raise PlanError(
                    f"imported DEVICE {new_device} Symbol={new_symbol}, expected {expected_new_symbol}"
                )

            changes = [
                attr_change(component_id, attrs, "Device", old_device, new_device),
                attr_change(component_id, attrs, "Symbol", old_symbol, new_symbol),
            ]
            body_name_json = [
                body_name_change(
                    component_id,
                    component["body"],
                    "DeviceName",
                    old_device,
                    new_device,
                    required_at_runtime=True,
                ),
                # 3.2.206 exported runtime pages often omit SymbolName.  It
                # does not participate in the installed Device/Footprint
                # decoder override, but when present it must still refer to
                # the imported SYMBOL document.
                body_name_change(
                    component_id,
                    component["body"],
                    "SymbolName",
                    old_symbol,
                    new_symbol,
                    required_at_runtime=False,
                ),
            ]
            component_modify = {"Device": new_device, "Symbol": new_symbol}

            if old_footprint:
                footprint_document = selected["FOOTPRINT"][str(old_footprint)]
                new_footprint = str(device_attributes.get("Footprint", ""))
                expected_new_footprint = str(footprint_document["head"]["uuid"])
                if new_footprint != expected_new_footprint:
                    raise PlanError(
                        f"imported DEVICE {new_device} Footprint={new_footprint}, "
                        f"expected {expected_new_footprint}"
                    )
                changes.append(
                    attr_change(
                        component_id,
                        attrs,
                        "Footprint",
                        str(old_footprint),
                        new_footprint,
                    )
                )
                body_name_json.append(
                    body_name_change(
                        component_id,
                        component["body"],
                        "FootprintName",
                        str(old_footprint),
                        new_footprint,
                        required_at_runtime=True,
                    )
                )
                component_modify["Footprint"] = new_footprint
                role = "physical"
            else:
                if device_attributes.get("Footprint"):
                    raise PlanError(f"power driver {instance['reference']} unexpectedly has Footprint")
                if "Footprint" in attrs:
                    raise PlanError(f"power driver {instance['reference']} has a schematic Footprint ATTR")
                role = "power_driver" if instance.get("is_power_driver") else "net_flag"

            checkpoint_component = checkpoint_components.get(component_id)
            if checkpoint_component is None:
                raise PlanError(
                    f"current checkpoint page {sheet_name} lacks component {component_id}"
                )
            for change in changes:
                checkpoint_attr = checkpoint_component["attrs"].get(change["key"])
                if checkpoint_attr is None:
                    raise PlanError(
                        f"checkpoint component {component_id} lacks {change['key']} ATTR"
                    )
                if checkpoint_attr["header"].get("id") != change["attribute_id"]:
                    raise PlanError(
                        f"checkpoint {component_id} {change['key']} ATTR id changed"
                    )
                if checkpoint_attr["body"].get("value") != change["new_uuid"]:
                    raise PlanError(
                        f"checkpoint {component_id} {change['key']} did not remap to expected UUID"
                    )
                checkpoint_checks[change["key"]] += 1

            instances.append(
                {
                    "reference": instance["reference"],
                    "base_reference": instance["base_reference"],
                    "subpart": instance["subpart"],
                    "native_part_id": instance["native_part_id"],
                    "role": role,
                    "component_id": component_id,
                    "changes": changes,
                    "component_body_name_json": body_name_json,
                    "component_modify_other_property": component_modify,
                }
            )

        page_plans.append(
            {
                "page": page_number,
                "sheet_name": sheet_name,
                "source_file": str(source_path.relative_to(BOARD_ROOT)).replace("\\", "/"),
                "source_document_uuid": source_document["head"]["uuid"],
                "checkpoint_document_uuid": checkpoint_page["head"]["uuid"],
                "instances": sorted(
                    instances,
                    key=lambda item: (
                        item["base_reference"],
                        item["native_part_id"],
                        item["component_id"],
                    ),
                ),
            }
        )

    missing = sorted(set(target_by_key) - matched_keys)
    if missing:
        raise PlanError(f"target instances missing from generated pages: {missing}")

    role_counts = Counter(
        instance["role"] for page in page_plans for instance in page["instances"]
    )
    unique_physical_refs = {
        instance["base_reference"]
        for page in page_plans
        for instance in page["instances"]
        if instance["role"] == "physical"
    }
    unique_driver_refs = {
        instance["base_reference"]
        for page in page_plans
        for instance in page["instances"]
        if instance["role"] == "power_driver"
    }
    unique_net_flag_refs = {
        instance["base_reference"]
        for page in page_plans
        for instance in page["instances"]
        if instance["role"] == "net_flag"
    }
    change_counts = Counter(
        change["key"]
        for page in page_plans
        for instance in page["instances"]
        for change in instance["changes"]
    )

    summary = {
        "pages": len(page_plans),
        "component_instances": sum(len(page["instances"]) for page in page_plans),
        "physical_component_instances": role_counts["physical"],
        "unique_physical_references": len(unique_physical_refs),
        "power_driver_instances": role_counts["power_driver"],
        "unique_power_driver_references": len(unique_driver_refs),
        "net_flag_instances": role_counts["net_flag"],
        "unique_net_flag_references": len(unique_net_flag_refs),
        "attribute_changes": dict(sorted(change_counts.items())),
        "checkpoint_remap_checks": dict(sorted(checkpoint_checks.items())),
        "errors": 0,
    }
    expected_summary = {
        "pages": 5,
        "component_instances": 486,
        "physical_component_instances": 333,
        "unique_physical_references": 330,
        "power_driver_instances": 7,
        "unique_power_driver_references": 7,
        "net_flag_instances": 146,
        "unique_net_flag_references": 146,
        "attribute_changes": {"Device": 486, "Footprint": 333, "Symbol": 486},
        "checkpoint_remap_checks": {"Device": 486, "Footprint": 333, "Symbol": 486},
        "errors": 0,
    }
    if summary != expected_summary:
        raise PlanError(f"unexpected plan summary: {summary}")

    library_map: dict[str, list[dict[str, Any]]] = {}
    for doc_type, by_source in selected.items():
        rows = []
        for old_uuid, document in sorted(by_source.items()):
            meta = document["meta"]
            row = {
                "source_uuid": old_uuid,
                "imported_uuid": document["head"]["uuid"],
                "version": str(document["head"].get("version", "")),
                "title": meta.get("title", ""),
                "source": meta.get("source", ""),
            }
            if doc_type == "DEVICE":
                row["symbol_uuid"] = meta.get("attributes", {}).get("Symbol")
                row["footprint_uuid"] = meta.get("attributes", {}).get("Footprint")
            rows.append(row)
        library_map[doc_type.lower()] = rows

    return {
        "schemaVersion": 1,
        "purpose": (
            "Durably rebind imported project-local library DOCHEAD UUIDs in both schematic "
            "COMPONENT child ATTR records and COMPONENT body *Name JSON."
        ),
        "safety": {
            "generated_offline": True,
            "api_executed_by_generator": False,
            "idempotent": True,
            "allowed_current_values": ["old_uuid", "new_uuid"],
            "component_body_attrs": (
                "Required repair state: installed 3.2.206 decoder overrideSchSymbolAttrsByNameSource "
                "copies body.attrs.DeviceName/FootprintName JSON.uuid into child ATTR blockValue on "
                "load/refresh. DeviceName and physical FootprintName UUIDs therefore MUST equal the "
                "imported document UUIDs while preserving their name/source fields. SymbolName is "
                "optional in runtime exports; if present, its UUID must also be canonical."
            ),
        },
        "sources": {
            "checkpoint": str(args.checkpoint.relative_to(BOARD_ROOT)).replace("\\", "/"),
            "checkpoint_sha256": sha256_file(args.checkpoint),
            "checkpoint_epru_member": checkpoint_member,
            "devices_manifest": str(args.devices.relative_to(BOARD_ROOT)).replace("\\", "/"),
            "devices_manifest_sha256": sha256_file(args.devices),
        },
        "selection": selection_summary,
        "summary": summary,
        "library_map": library_map,
        "pages": sorted(page_plans, key=lambda item: item["page"]),
    }


def javascript_helper(plan: dict[str, Any]) -> str:
    compact_pages = json.dumps(plan["pages"], ensure_ascii=False, separators=(",", ":"))
    return f"""// Generated by scripts/build-native-component-rebind-plan.py.
// This file defines PURE source-transform helpers only. It never calls EasyEDA.
const NATIVE_COMPONENT_LINK_REBIND_PAGES = {compact_pages};

function nativeComponentLinkRebindPage(pageNumber) {{
  const page = NATIVE_COMPONENT_LINK_REBIND_PAGES.find(item => item.page === pageNumber);
  if (!page) throw new Error(`No rebind plan for page ${{pageNumber}}`);
  return page;
}}

function patchNativeComponentLinkRebindSource(pageNumber, source) {{
  const page = nativeComponentLinkRebindPage(pageNumber);
  if (typeof source !== 'string' || !source) throw new Error('Source text is required');
  const parsed = [];
  const records = new Map();
  for (const rawLine of source.split(/\\r?\\n/)) {{
    if (!rawLine) continue;
    const line = rawLine.endsWith('|') ? rawLine.slice(0, -1) : rawLine;
    const separator = line.indexOf('||');
    if (separator < 0) throw new Error('Malformed EasyEDA record');
    const header = JSON.parse(line.slice(0, separator));
    const bodyText = line.slice(separator + 2);
    const body = bodyText ? JSON.parse(bodyText) : {{}};
    const record = {{ header, body }};
    parsed.push(record);
    if (header.id) records.set(header.id, record);
  }}

  const changedChildAttrs = [];
  const changedBodyNames = [];
  const alreadyCurrent = [];
  for (const instance of page.instances) {{
    for (const change of instance.changes) {{
      const record = records.get(change.attribute_id);
      if (!record || record.header.type !== 'ATTR')
        throw new Error(`Missing ATTR ${{change.attribute_id}} for ${{instance.reference}}`);
      if (record.body.parentId !== instance.component_id || record.body.key !== change.key)
        throw new Error(`ATTR identity mismatch for ${{instance.reference}} ${{change.key}}`);
      if (record.body.value === change.new_uuid) {{
        alreadyCurrent.push(change.attribute_id);
        continue;
      }}
      if (record.body.value !== change.old_uuid)
        throw new Error(`Unexpected current UUID for ${{instance.reference}} ${{change.key}}: ${{record.body.value}}`);
      record.body.value = change.new_uuid;
      changedChildAttrs.push(change.attribute_id);
    }}
    const component = records.get(instance.component_id);
    if (!component || component.header.type !== 'COMPONENT')
      throw new Error(`Missing COMPONENT ${{instance.component_id}} for ${{instance.reference}}`);
    if (!component.body.attrs || typeof component.body.attrs !== 'object')
      throw new Error(`COMPONENT ${{instance.component_id}} has no body attrs`);
    for (const change of instance.component_body_name_json) {{
      const raw = component.body.attrs[change.key];
      if (!raw) {{
        if (change.required_at_runtime)
          throw new Error(`Missing required body attrs ${{change.key}} for ${{instance.reference}}`);
        continue;
      }}
      const payload = JSON.parse(raw);
      if (payload.name !== change.name || payload.source !== change.source)
        throw new Error(`body attrs provenance changed for ${{instance.reference}} ${{change.key}}`);
      if (payload.uuid === change.new_uuid) continue;
      if (payload.uuid !== change.old_uuid)
        throw new Error(`Unexpected body UUID for ${{instance.reference}} ${{change.key}}: ${{payload.uuid}}`);
      payload.uuid = change.new_uuid;
      component.body.attrs[change.key] = JSON.stringify(payload);
      changedBodyNames.push(`${{instance.component_id}}:${{change.key}}`);
    }}
  }}
  const patchedSource = parsed.map(record =>
    `${{JSON.stringify(record.header)}}||${{JSON.stringify(record.body)}}|`
  ).join('\\n') + '\\n';
  return {{
    page: page.page,
    sheet_name: page.sheet_name,
    source: patchedSource,
    changed_child_attrs: changedChildAttrs,
    changed_body_names: changedBodyNames,
    already_current: alreadyCurrent,
  }};
}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--schematics-dir", type=Path, default=DEFAULT_SCHEMATICS)
    parser.add_argument("--devices", type=Path, default=DEFAULT_DEVICES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--api-helper", type=Path, default=DEFAULT_API_HELPER)
    args = parser.parse_args()
    for name in ("checkpoint", "schematics_dir", "devices"):
        value = getattr(args, name).resolve()
        setattr(args, name, value)
        if not value.exists():
            raise PlanError(f"missing input: {value}")
    args.output = args.output.resolve()
    args.api_helper = args.api_helper.resolve()

    plan = build_plan(args)
    atomic_write_text(args.output, json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(args.api_helper, javascript_helper(plan))
    print(json.dumps(plan["summary"], ensure_ascii=False, sort_keys=True))
    print(f"plan={args.output}")
    print(f"api_helper={args.api_helper}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
