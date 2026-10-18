#!/usr/bin/env python3
"""Validate generated EasyEDA Pro native sources against the installed schema.

The EasyEDA source format stores records as ``head||body`` separated by ``|``
and newlines.  The 3.2 getter omits the separator after the final record.  This
tool deliberately validates the body with the schema shipped by the installed
editor instead of relying on older prose documentation.  EasyEDA's schema uses
TypeScript-style ``allOf`` inheritance where base types set
``additionalProperties: false``; the validator therefore flattens inherited
properties before checking an object.

No EasyEDA process or project is opened.  Inputs are read-only and the only
write is the requested JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "output" / "validation" / "native-source-schema-report.json"
SCHEMA_GLOBS = (
    Path("C:/Program Files/easyeda-pro/resources/app/assets/pro-api"),
    Path("C:/Program Files (x86)/easyeda-pro/resources/app/assets/pro-api"),
)
DEFAULT_INPUT_PATTERNS = (
    "output/native-schematics/*.epru",
    "output/native-libraries/symbols/*.esym",
    "output/native-libraries/footprints/*.efoo",
    "output/native-libraries/devices/*.edevice",
    "output/native-libraries/embedded-library.epru",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def discover_schema(explicit: Path | None) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"schema not found: {candidate}")
        return candidate

    candidates: list[Path] = []
    for base in SCHEMA_GLOBS:
        if base.is_dir():
            candidates.extend(base.glob("*/assets/format-types.schema-*.json"))
    if not candidates:
        raise FileNotFoundError(
            "installed EasyEDA format schema was not found; pass --schema explicitly"
        )
    return max(candidates, key=lambda item: (item.stat().st_mtime_ns, str(item)))


def merge_schema(left: dict[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Merge schema fragments as EasyEDA's TypeScript inheritance intends."""
    merged = dict(left)
    for key, value in right.items():
        if key in {"$ref", "allOf"} or key.startswith("x-") or key == "$comment":
            continue
        if key == "properties":
            properties = dict(merged.get("properties", {}))
            for property_name, property_schema in value.items():
                if property_name in properties and properties[property_name] != property_schema:
                    properties[property_name] = {
                        "allOf": [properties[property_name], property_schema]
                    }
                else:
                    properties[property_name] = property_schema
            merged["properties"] = properties
        elif key == "required":
            merged[key] = list(dict.fromkeys([*merged.get(key, []), *value]))
        elif key == "additionalProperties":
            previous = merged.get(key, True)
            if previous is False or value is False:
                merged[key] = False
            elif isinstance(value, Mapping):
                merged[key] = value
            else:
                merged[key] = previous if isinstance(previous, Mapping) else bool(value)
        elif key in merged and merged[key] != value and key in {"type", "enum", "const"}:
            merged.setdefault("allOfConstraints", []).append({key: value})
        else:
            merged[key] = value
    return merged


class SchemaIndex:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document
        self.definitions: Mapping[str, Any] = document.get("$defs", {})
        if not self.definitions:
            raise ValueError("schema has no $defs")
        self.by_record: dict[tuple[str, str], str] = {}
        duplicates: dict[tuple[str, str], list[str]] = defaultdict(list)
        for name, definition in self.definitions.items():
            primitive = definition.get("x-primitiveType")
            for doc_type in definition.get("x-docType", []):
                if primitive:
                    duplicates[(doc_type, primitive)].append(name)
        ambiguous = {key: value for key, value in duplicates.items() if len(value) != 1}
        if ambiguous:
            raise ValueError(f"ambiguous docType/primitive mappings: {ambiguous}")
        self.by_record = {key: value[0] for key, value in duplicates.items()}
        self._expanded_definitions: dict[str, dict[str, Any]] = {}

    @staticmethod
    def ref_name(reference: str) -> str:
        prefix = "#/$defs/"
        if not reference.startswith(prefix):
            raise ValueError(f"unsupported external schema reference: {reference}")
        return reference[len(prefix) :].replace("~1", "/").replace("~0", "~")

    def expand(self, schema: Mapping[str, Any], trail: tuple[str, ...] = ()) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        reference = schema.get("$ref")
        if reference:
            name = self.ref_name(reference)
            if name not in self.definitions:
                raise KeyError(f"schema reference is missing: {name}")
            if name not in trail:
                merged = merge_schema(merged, self.expanded_definition(name, trail))
        for fragment in schema.get("allOf", []):
            merged = merge_schema(merged, self.expand(fragment, trail))
        merged = merge_schema(merged, schema)
        return merged

    def expanded_definition(
        self, name: str, trail: tuple[str, ...] = ()
    ) -> dict[str, Any]:
        if not trail and name in self._expanded_definitions:
            return self._expanded_definitions[name]
        if name in trail:
            return {}
        expanded = self.expand(self.definitions[name], (*trail, name))
        if not trail:
            self._expanded_definitions[name] = expanded
        return expanded

    def record_schema(self, doc_type: str, primitive: str) -> tuple[str, dict[str, Any]] | None:
        name = self.by_record.get((doc_type, primitive))
        return (name, self.expanded_definition(name)) if name else None


@dataclass(frozen=True)
class Issue:
    action: str
    path: str
    expected: str
    actual: str
    message: str


def json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


def is_documented_runtime_exception(
    doc_type: str | None,
    primitive_type: str | None,
    path: str,
    value: Any,
    expected_types: Sequence[str],
) -> bool:
    """Accept only directly observed installed-schema/runtime mismatches.

    The installed 3.2 schema declares ``TPcbBase.groupId`` as a string, while
    its own ``$comment`` records that an ungrouped PCB/FOOTPRINT primitive is
    written as the integer ``0`` (and that real samples contain thousands of
    those values and no string ``"0"`` values).  Keep this exception exact so
    it cannot mask other type or enum drift.
    """
    group_id_zero = (
        doc_type in {"PCB", "FOOTPRINT"}
        and path == "$body.groupId"
        and type(value) is int
        and value == 0
        and list(expected_types) == ["string"]
    )
    unknown_layer_property = (
        doc_type == "PCB"
        and primitive_type == "LAYER_PHYS"
        and path in {"$body.permittivity", "$body.lossTangent"}
        and value is None
        and list(expected_types) == ["number"]
    )
    return group_id_zero or unknown_layer_property


def is_documented_missing_runtime_exception(
    doc_type: str | None,
    primitive_type: str | None,
    path: str,
) -> bool:
    """Accept exact writer-omitted fields observed in EasyEDA 3.2 getters."""
    return (
        doc_type == "PCB"
        and (
            (primitive_type == "CANVAS" and path == "$body.layerBrightness")
            or (primitive_type == "PREFERENCE" and path == "$body.preferenceConfig")
            or (primitive_type == "PANELIZE" and path == "$body.panelizeVersion")
        )
    )


def json_equal(left: Any, right: Any) -> bool:
    return json_type(left) == json_type(right) and left == right


def describe_schema(schema_index: SchemaIndex, schema: Mapping[str, Any]) -> str:
    expanded = schema_index.expand(schema)
    if "enum" in expanded:
        return "enum " + json.dumps(expanded["enum"], ensure_ascii=False, separators=(",", ":"))
    if "const" in expanded:
        return "const " + json.dumps(expanded["const"], ensure_ascii=False)
    branch_types: list[str] = []
    for keyword in ("oneOf", "anyOf"):
        for branch in expanded.get(keyword, []):
            branch_expanded = schema_index.expand(branch)
            branch_type = branch_expanded.get("type")
            if isinstance(branch_type, str):
                branch_types.append(branch_type)
    expected_type = expanded.get("type")
    if isinstance(expected_type, list):
        branch_types.extend(expected_type)
    elif isinstance(expected_type, str):
        branch_types.append(expected_type)
    return " | ".join(dict.fromkeys(branch_types)) or "schema constraint"


def validate_value(
    schema_index: SchemaIndex,
    raw_schema: Mapping[str, Any],
    value: Any,
    path: str,
    doc_type: str | None = None,
    primitive_type: str | None = None,
) -> list[Issue]:
    schema = schema_index.expand(raw_schema)
    issues: list[Issue] = []

    base_schema = {key: item for key, item in schema.items() if key not in {"oneOf", "anyOf"}}
    for keyword in ("oneOf", "anyOf"):
        branches = schema.get(keyword)
        if branches:
            candidates = [
                validate_value(schema_index, branch, value, path, doc_type, primitive_type)
                for branch in branches
            ]
            if not any(not candidate for candidate in candidates):
                issues.extend(min(candidates, key=len))
    schema = base_schema

    expected_type = schema.get("type")
    if expected_type:
        expected_types = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if (
            not any(type_matches(value, candidate) for candidate in expected_types)
            and not is_documented_runtime_exception(
                doc_type, primitive_type, path, value, expected_types
            )
        ):
            return [
                Issue(
                    "change",
                    path,
                    " | ".join(expected_types),
                    json_type(value),
                    f"expected {' | '.join(expected_types)}, got {json_type(value)}",
                )
            ]

    if "const" in schema and not json_equal(value, schema["const"]):
        issues.append(
            Issue("change", path, f"const {schema['const']!r}", repr(value), "const mismatch")
        )
    if "enum" in schema and not any(json_equal(value, item) for item in schema["enum"]):
        issues.append(
            Issue(
                "change",
                path,
                "enum " + json.dumps(schema["enum"], ensure_ascii=False),
                repr(value),
                "enum mismatch",
            )
        )

    for constraint in schema.get("allOfConstraints", []):
        issues.extend(
            validate_value(schema_index, constraint, value, path, doc_type, primitive_type)
        )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                expected = describe_schema(schema_index, properties.get(field, {}))
                child_path = f"{path}.{field}" if path else field
                if is_documented_missing_runtime_exception(
                    doc_type, primitive_type, child_path
                ):
                    continue
                issues.append(
                    Issue("add", child_path, expected, "missing", f"required field {field!r} is missing")
                )
        additional = schema.get("additionalProperties", True)
        for field, child in value.items():
            child_path = f"{path}.{field}" if path else field
            if field in properties:
                issues.extend(
                    validate_value(
                        schema_index, properties[field], child, child_path,
                        doc_type, primitive_type,
                    )
                )
            elif additional is False:
                issues.append(
                    Issue(
                        "remove",
                        child_path,
                        "field absent",
                        json_type(child),
                        f"field {field!r} is not allowed",
                    )
                )
            elif isinstance(additional, Mapping):
                issues.extend(
                    validate_value(
                        schema_index, additional, child, child_path,
                        doc_type, primitive_type,
                    )
                )
    elif isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                issues.extend(
                    validate_value(
                        schema_index,
                        item_schema,
                        child,
                        f"{path}[{index}]",
                        doc_type,
                        primitive_type,
                    )
                )
        if "minItems" in schema and len(value) < schema["minItems"]:
            issues.append(Issue("change", path, f"at least {schema['minItems']} items", str(len(value)), "array too short"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            issues.append(Issue("change", path, f"at most {schema['maxItems']} items", str(len(value)), "array too long"))
    elif isinstance(value, str):
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            issues.append(Issue("change", path, f"pattern {pattern}", repr(value), "pattern mismatch"))
        if "minLength" in schema and len(value) < schema["minLength"]:
            issues.append(Issue("change", path, f"length >= {schema['minLength']}", str(len(value)), "string too short"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            issues.append(Issue("change", path, f"length <= {schema['maxLength']}", str(len(value)), "string too long"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(Issue("change", path, f">= {schema['minimum']}", repr(value), "below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(Issue("change", path, f"<= {schema['maximum']}", repr(value), "above maximum"))
    return issues


def normalized_issue_path(path: str) -> str:
    return re.sub(r"\[\d+\]", "[]", path)


def contract_for(schema_index: SchemaIndex, name: str) -> dict[str, Any]:
    schema = schema_index.expanded_definition(name)
    properties = schema.get("properties", {})
    property_types = {
        key: describe_schema(schema_index, value) for key, value in sorted(properties.items())
    }
    return {
        "schemaDefinition": name,
        "requiredFields": sorted(schema.get("required", [])),
        "allowedFields": sorted(properties),
        "additionalProperties": schema.get("additionalProperties", True),
        "propertyTypes": property_types,
    }


def resolve_inputs(explicit: Sequence[str]) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        for raw in explicit:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            if candidate.is_dir():
                paths.extend(
                    child
                    for child in candidate.rglob("*")
                    if child.is_file() and child.suffix.lower() in {".epru", ".esym", ".efoo", ".edevice"}
                )
            elif candidate.is_file():
                paths.append(candidate)
            else:
                matches = list(ROOT.glob(raw))
                if not matches:
                    raise FileNotFoundError(f"input not found: {raw}")
                paths.extend(item for item in matches if item.is_file())
    else:
        for pattern in DEFAULT_INPUT_PATTERNS:
            paths.extend(ROOT.glob(pattern))
    unique = {item.resolve(): item.resolve() for item in paths}
    return sorted(unique.values(), key=lambda item: str(item).casefold())


def classify_input(path: Path) -> str:
    posix = display_path(path)
    if "/native-schematics/" in f"/{posix}":
        return "schematic-pages"
    if posix.endswith("embedded-library.epru"):
        return "embedded-library-bundle"
    if "/symbols/" in f"/{posix}":
        return "symbols"
    if "/footprints/" in f"/{posix}":
        return "footprints"
    if "/devices/" in f"/{posix}":
        return "devices"
    return "other"


def validate_files(
    paths: Sequence[Path],
    schema_index: SchemaIndex,
    max_examples: int,
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    action_groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    runtime_exception_groups: dict[tuple[str, str], dict[str, Any]] = {}
    file_results: list[dict[str, Any]] = []
    encountered: set[tuple[str, str]] = set()
    totals: Counter[str] = Counter()

    def add_group(
        *,
        action: str,
        doc_type: str,
        primitive: str,
        issue: Issue,
        file_path: Path,
        line_number: int,
        record_id: str | None,
    ) -> None:
        normalized_path = normalized_issue_path(issue.path)
        key = (action, doc_type, primitive, normalized_path, issue.expected)
        group = action_groups.setdefault(
            key,
            {
                "action": action,
                "docType": doc_type,
                "primitiveType": primitive,
                "fieldPath": normalized_path,
                "expected": issue.expected,
                "actualKinds": Counter(),
                "count": 0,
                "examples": [],
            },
        )
        group["count"] += 1
        group["actualKinds"][issue.actual] += 1
        if len(group["examples"]) < max_examples:
            group["examples"].append(
                {
                    "file": display_path(file_path),
                    "line": line_number,
                    "recordId": record_id,
                    "message": issue.message,
                }
            )

    for path in paths:
        current_doc_type: str | None = None
        file_counts: Counter[str] = Counter()
        file_primitives: Counter[str] = Counter()
        file_doc_types: Counter[str] = Counter()
        parse_examples: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig") as stream:
            source_lines = stream.readlines()
            final_nonempty_line = max(
                (index for index, value in enumerate(source_lines, 1) if value.strip()),
                default=0,
            )
            for line_number, source_line in enumerate(source_lines, 1):
                line = source_line.rstrip("\r\n")
                if not line:
                    continue
                file_counts["records"] += 1
                totals["records"] += 1
                head_text, separator, body_with_pipe = line.partition("||")
                if not separator:
                    file_counts["parseErrors"] += 1
                    totals["parseErrors"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": "missing || separator"})
                    continue
                has_terminator = body_with_pipe.endswith("|")
                if not has_terminator and line_number != final_nonempty_line:
                    file_counts["parseErrors"] += 1
                    totals["parseErrors"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": "missing trailing |"})
                    continue
                try:
                    head = json.loads(head_text)
                    body = json.loads(body_with_pipe[:-1] if has_terminator else body_with_pipe)
                except json.JSONDecodeError as error:
                    file_counts["parseErrors"] += 1
                    totals["parseErrors"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": str(error)})
                    continue
                if not isinstance(head, dict) or not isinstance(body, dict):
                    file_counts["parseErrors"] += 1
                    totals["parseErrors"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": "head and body must be objects"})
                    continue

                primitive = head.get("type")
                record_id = head.get("id")
                if not isinstance(primitive, str):
                    file_counts["parseErrors"] += 1
                    totals["parseErrors"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": "head.type must be a string"})
                    continue
                file_primitives[primitive] += 1
                if primitive == "DOCHEAD":
                    doc_type = body.get("docType")
                    if not isinstance(doc_type, str):
                        file_counts["parseErrors"] += 1
                        totals["parseErrors"] += 1
                        if len(parse_examples) < max_examples:
                            parse_examples.append({"line": line_number, "message": "DOCHEAD body.docType must be a string"})
                    else:
                        current_doc_type = doc_type
                        file_doc_types[doc_type] += 1
                    continue

                if current_doc_type is None:
                    file_counts["unmappedRecords"] += 1
                    totals["unmappedRecords"] += 1
                    if len(parse_examples) < max_examples:
                        parse_examples.append({"line": line_number, "message": "record appears before DOCHEAD"})
                    continue
                file_doc_types[current_doc_type] += 0
                mapped = schema_index.record_schema(current_doc_type, primitive)
                if mapped is None:
                    file_counts["unmappedRecords"] += 1
                    totals["unmappedRecords"] += 1
                    issue = Issue(
                        "change",
                        "$record",
                        "known installed-schema primitive",
                        primitive,
                        f"no installed schema mapping for {current_doc_type}/{primitive}",
                    )
                    add_group(
                        action="change",
                        doc_type=current_doc_type,
                        primitive=primitive,
                        issue=issue,
                        file_path=path,
                        line_number=line_number,
                        record_id=record_id,
                    )
                    continue

                schema_name, schema = mapped
                encountered.add((current_doc_type, primitive))
                group_id_schema = schema.get("properties", {}).get("groupId")
                if group_id_schema is not None:
                    expanded_group_id = schema_index.expand(group_id_schema)
                    raw_expected_types = expanded_group_id.get("type")
                    expected_types = (
                        [raw_expected_types]
                        if isinstance(raw_expected_types, str)
                        else list(raw_expected_types or [])
                    )
                    if is_documented_runtime_exception(
                        current_doc_type,
                        primitive,
                        "$body.groupId",
                        body.get("groupId"),
                        expected_types,
                    ):
                        file_counts["documentedRuntimeExceptions"] += 1
                        totals["documentedRuntimeExceptions"] += 1
                        key = (current_doc_type, primitive, "$body.groupId")
                        group = runtime_exception_groups.setdefault(
                            key,
                            {
                                "docType": current_doc_type,
                                "primitiveType": primitive,
                                "fieldPath": "$body.groupId",
                                "schemaExpected": "string",
                                "runtimeAccepted": "integer 0",
                                "count": 0,
                                "examples": [],
                            },
                        )
                        group["count"] += 1
                        if len(group["examples"]) < max_examples:
                            group["examples"].append(
                                {
                                    "file": display_path(path),
                                    "line": line_number,
                                    "recordId": record_id,
                                }
                            )

                if current_doc_type == "PCB" and primitive == "LAYER_PHYS":
                    for field in ("permittivity", "lossTangent"):
                        property_schema = schema.get("properties", {}).get(field)
                        if property_schema is None:
                            continue
                        expanded_property = schema_index.expand(property_schema)
                        raw_expected_types = expanded_property.get("type")
                        expected_types = (
                            [raw_expected_types]
                            if isinstance(raw_expected_types, str)
                            else list(raw_expected_types or [])
                        )
                        field_path = f"$body.{field}"
                        if is_documented_runtime_exception(
                            current_doc_type,
                            primitive,
                            field_path,
                            body.get(field),
                            expected_types,
                        ):
                            file_counts["documentedRuntimeExceptions"] += 1
                            totals["documentedRuntimeExceptions"] += 1
                            key = (current_doc_type, primitive, field_path)
                            group = runtime_exception_groups.setdefault(
                                key,
                                {
                                    "docType": current_doc_type,
                                    "primitiveType": primitive,
                                    "fieldPath": field_path,
                                    "schemaExpected": "number",
                                    "runtimeAccepted": "null (unknown)",
                                    "count": 0,
                                    "examples": [],
                                },
                            )
                            group["count"] += 1
                            if len(group["examples"]) < max_examples:
                                group["examples"].append(
                                    {
                                        "file": display_path(path),
                                        "line": line_number,
                                        "recordId": record_id,
                                    }
                                )

                for field in schema.get("required", []):
                    field_path = f"$body.{field}"
                    if field not in body and is_documented_missing_runtime_exception(
                        current_doc_type, primitive, field_path
                    ):
                        file_counts["documentedRuntimeExceptions"] += 1
                        totals["documentedRuntimeExceptions"] += 1
                        key = (current_doc_type, primitive, field_path)
                        group = runtime_exception_groups.setdefault(
                            key,
                            {
                                "docType": current_doc_type,
                                "primitiveType": primitive,
                                "fieldPath": field_path,
                                "schemaExpected": describe_schema(
                                    schema_index,
                                    schema.get("properties", {}).get(field, {}),
                                ),
                                "runtimeAccepted": "field omitted by getter",
                                "count": 0,
                                "examples": [],
                            },
                        )
                        group["count"] += 1
                        if len(group["examples"]) < max_examples:
                            group["examples"].append(
                                {
                                    "file": display_path(path),
                                    "line": line_number,
                                    "recordId": record_id,
                                }
                            )

                issues = validate_value(
                    schema_index,
                    schema,
                    body,
                    "$body",
                    current_doc_type,
                    primitive,
                )
                for issue in issues:
                    file_counts[f"{issue.action}Fields"] += 1
                    totals[f"{issue.action}Fields"] += 1
                    add_group(
                        action=issue.action,
                        doc_type=current_doc_type,
                        primitive=primitive,
                        issue=issue,
                        file_path=path,
                        line_number=line_number,
                        record_id=record_id,
                    )

        file_issue_count = sum(
            file_counts[key] for key in ("parseErrors", "unmappedRecords", "addFields", "removeFields", "changeFields")
        )
        file_results.append(
            {
                "file": display_path(path),
                "category": classify_input(path),
                "sha256": sha256_file(path),
                "sizeBytes": path.stat().st_size,
                "valid": file_issue_count == 0,
                "counts": {
                    key: file_counts[key]
                    for key in (
                        "records",
                        "parseErrors",
                        "unmappedRecords",
                        "addFields",
                        "removeFields",
                        "changeFields",
                        "documentedRuntimeExceptions",
                    )
                },
                "docTypes": dict(sorted(file_doc_types.items())),
                "primitiveCounts": dict(sorted(file_primitives.items())),
                "parseOrMappingExamples": parse_examples,
            }
        )

    serialized_actions: dict[str, list[dict[str, Any]]] = {
        "addFields": [],
        "removeFields": [],
        "changeFields": [],
    }
    action_key = {"add": "addFields", "remove": "removeFields", "change": "changeFields"}
    for group in sorted(
        action_groups.values(),
        key=lambda item: (item["action"], item["docType"], item["primitiveType"], item["fieldPath"]),
    ):
        group["actualKinds"] = dict(group["actualKinds"].most_common())
        serialized_actions[action_key[group["action"]]].append(group)

    return (
        {
            "totals": {
                "files": len(paths),
                "validFiles": sum(1 for result in file_results if result["valid"]),
                "invalidFiles": sum(1 for result in file_results if not result["valid"]),
                **{
                    key: totals[key]
                    for key in (
                        "records",
                        "parseErrors",
                        "unmappedRecords",
                        "addFields",
                        "removeFields",
                        "changeFields",
                        "documentedRuntimeExceptions",
                    )
                },
            },
            "documentedRuntimeExceptions": {
                "policy": {
                    "rules": [
                        {
                            "scope": "PCB/FOOTPRINT top-level $body.groupId only",
                            "schemaExpected": "string",
                            "runtimeAccepted": "exact integer 0 only",
                            "basis": (
                                "The installed TPcbBase $comment states that the writer "
                                "emits numeric 0 for ungrouped primitives."
                            ),
                        },
                        {
                            "scope": (
                                "PCB/LAYER_PHYS top-level $body.permittivity and "
                                "$body.lossTangent only"
                            ),
                            "schemaExpected": "number",
                            "runtimeAccepted": "exact null only",
                            "basis": (
                                "EasyEDA Pro 3.2 getter output directly contains null for "
                                "unknown LAYER_PHYS dielectric properties."
                            ),
                        },
                        {
                            "scope": (
                                "PCB/CANVAS $body.layerBrightness and PCB/PREFERENCE "
                                "$body.preferenceConfig and PCB/PANELIZE "
                                "$body.panelizeVersion only"
                            ),
                            "schemaExpected": "required field",
                            "runtimeAccepted": "field omitted by getter",
                            "basis": (
                                "EasyEDA Pro 3.2 getter output directly omits these three "
                                "fields from otherwise valid blank/native PCB documents."
                            ),
                        },
                    ],
                    "otherExceptionsAccepted": False,
                },
                "count": totals["documentedRuntimeExceptions"],
                "groups": sorted(
                    runtime_exception_groups.values(),
                    key=lambda item: (
                        item["docType"], item["primitiveType"], item["fieldPath"]
                    ),
                ),
            },
            "actions": serialized_actions,
            "files": file_results,
        },
        encountered,
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="*", help="files, directories, or STM-folder-relative globs")
    parser.add_argument("--schema", type=Path, help="installed format-types.schema-*.json")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-examples", type=int, default=5)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when validation finds issues")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    schema_path = discover_schema(args.schema)
    schema_document = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    schema_index = SchemaIndex(schema_document)
    input_paths = resolve_inputs(args.inputs)
    if not input_paths:
        raise FileNotFoundError("no native-source fixtures matched")

    validation, encountered = validate_files(input_paths, schema_index, args.max_examples)
    contracts: dict[str, Any] = {}
    for doc_type, primitive in sorted(encountered):
        name = schema_index.by_record[(doc_type, primitive)]
        contracts[f"{doc_type}/{primitive}"] = contract_for(schema_index, name)

    issue_total = sum(
        validation["totals"][key]
        for key in ("parseErrors", "unmappedRecords", "addFields", "removeFields", "changeFields")
    )
    semantic_runtime_overrides: list[dict[str, Any]] = []
    if ("PCB", "LAYER_PHYS") in encountered:
        probe_path = ROOT / "output" / "validation" / "native-pcb-coordinate-probe.epru"
        semantic_runtime_overrides.append({
            "docType": "PCB",
            "primitiveType": "LAYER_PHYS",
            "fieldPath": "$body.thickness",
            "installedSchemaCommentUnit": "disk value = internal mm * 10 (0.1 mm unit)",
            "runtimeUnit": "mil",
            "evidence": {
                "path": display_path(probe_path),
                "sha256": sha256_file(probe_path) if probe_path.is_file() else None,
                "observation": (
                    "Getter values mask=0.394, copper=1.379, dielectric=59.449, "
                    "copper=1.378, mask=0.394 total 62.994 mil (about 1.600 mm); "
                    "the schema comment would instead imply an impossible 6.2994 mm."
                ),
            },
            "validationBehavior": (
                "Validate the installed numeric field type, but interpret emitted physical "
                "thickness in mil according to direct EasyEDA 3.2 getter evidence."
            ),
        })
    if any(
        primitive in encountered
        for primitive in (("PCB", "CANVAS"), ("PCB", "PREFERENCE"), ("PCB", "PANELIZE"))
    ):
        probe_path = ROOT / "output" / "validation" / "native-pcb-coordinate-probe.epru"
        semantic_runtime_overrides.append({
            "docType": "PCB",
            "primitiveFields": [
                "CANVAS/$body.layerBrightness",
                "PREFERENCE/$body.preferenceConfig",
                "PANELIZE/$body.panelizeVersion",
            ],
            "installedSchemaConstraint": "required",
            "runtimeGetterBehavior": "field omitted",
            "evidence": {
                "path": display_path(probe_path),
                "sha256": sha256_file(probe_path) if probe_path.is_file() else None,
                "observation": (
                    "EasyEDA Pro 3.2 getter output omits all three fields in both the "
                    "native blank and coordinate-probe PCB documents."
                ),
            },
            "validationBehavior": (
                "Accept omission only for these exact PCB primitive/field pairs; do not "
                "synthesize values or relax any other required field."
            ),
        })
        semantic_runtime_overrides.append({
            "docType": "PCB",
            "primitiveType": "LAYER_PHYS",
            "fieldPaths": ["$body.permittivity", "$body.lossTangent"],
            "installedSchemaType": "number",
            "runtimeUnknownValue": None,
            "evidence": {
                "path": display_path(probe_path),
                "sha256": sha256_file(probe_path) if probe_path.is_file() else None,
                "observation": (
                    "EasyEDA Pro 3.2 getter output uses null for unknown copper-layer "
                    "permittivity and lossTangent values."
                ),
            },
            "validationBehavior": (
                "Accept exact null only for these two PCB/LAYER_PHYS fields; all other "
                "installed-schema type constraints remain strict."
            ),
        })
    report = {
        "format": "easyeda-installed-schema-validation-report",
        "formatVersion": 6,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "valid": issue_total == 0,
        "readOnlyInputs": True,
        "schema": {
            "path": str(schema_path.resolve()),
            "sha256": sha256_file(schema_path),
            "draft": schema_document.get("$schema"),
            "definitionCount": len(schema_index.definitions),
            "recordMappingCount": len(schema_index.by_record),
            "note": "DOCHEAD is checked structurally; record bodies use installed x-docType/x-primitiveType mappings.",
        },
        "contracts": contracts,
        "documentedSemanticRuntimeOverrides": semantic_runtime_overrides,
        **validation,
    }
    report_path = args.report
    if not report_path.is_absolute():
        report_path = ROOT / report_path
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    totals = report["totals"]
    print(f"Schema: {schema_path}")
    print(f"Inputs: {totals['files']} files, {totals['records']} records")
    print(
        "Issues: "
        f"add={totals['addFields']} remove={totals['removeFields']} "
        f"change={totals['changeFields']} unmapped={totals['unmappedRecords']} "
        f"parse={totals['parseErrors']}"
    )
    print(f"Documented runtime exceptions: total={totals['documentedRuntimeExceptions']}")
    print(f"Report: {report_path.resolve()}")
    return 1 if args.strict and not report["valid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
