#!/usr/bin/env python3
"""Prove that an EasyEDA PCB rule-profile change preserved board data."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = (ROOT / "output").resolve()
DEFAULT_BEFORE = ROOT / "output" / "validation" / "native-staging-pcb-stack-ui-reopened.epru"
DEFAULT_AFTER = (
    ROOT / "output" / "validation" /
    "native-staging-pcb-multilayer-rules-reopened.epru"
)
DEFAULT_OUTPUT = (
    ROOT / "output" / "validation" / "native-pcb-multilayer-rule-change-audit.json"
)
GEOMETRY_TYPES = frozenset({"LINE", "ARC", "POLY", "FILL", "VIA", "PAD"})
ELECTRICAL_TYPES = frozenset({"COMPONENT", "ATTR", "PAD_NET", "NET"})
STACK_TYPES = frozenset({"LAYER", "LAYER_PHYS"})
RULE_TYPES = frozenset({"RULE", "RULE_TEMPLATE", "RULE_SELECTOR"})
ALLOWED_CHANGED_TYPES = RULE_TYPES | {"DOCHEAD"}


def load_helpers() -> Any:
    path = ROOT / "scripts" / "audit-native-pcb-staging-checkpoint.py"
    spec = importlib.util.spec_from_file_location("pcb_rule_audit_helpers", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load source helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPERS = load_helpers()


def compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(OUTPUT_ROOT)
    except ValueError as exc:
        raise ValueError(f"output must be below {OUTPUT_ROOT}: {resolved}") from exc
    return resolved


def atomic_write_text(path: Path, value: str) -> None:
    target = safe_output_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=target.name + ".tmp-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def record_key(record: Any) -> tuple[str, str]:
    return record.kind, record.record_id


def record_map(records: Iterable[Any], label: str) -> dict[tuple[str, str], Any]:
    result: dict[tuple[str, str], Any] = {}
    for record in records:
        key = record_key(record)
        if key in result:
            raise ValueError(f"{label}: duplicate record key {key}")
        result[key] = record
    return result


def digest(records: Iterable[Any], kinds: frozenset[str]) -> str:
    rows = sorted(
        (record.kind, record.record_id, record.body)
        for record in records if record.kind in kinds
    )
    return hashlib.sha256(compact(rows).encode("utf-8")).hexdigest()


def inventory(records: Iterable[Any], kinds: frozenset[str]) -> dict[str, Any]:
    selected = [record for record in records if record.kind in kinds]
    return {
        "count": len(selected),
        "counts_by_type": dict(sorted(Counter(record.kind for record in selected).items())),
        "body_digest": digest(selected, kinds),
    }


def rule_summary(records: Iterable[Any]) -> dict[str, Any]:
    records = list(records)
    templates = [record.body for record in records if record.kind == "RULE_TEMPLATE"]
    rules = [record for record in records if record.kind == "RULE"]
    selectors = [record for record in records if record.kind == "RULE_SELECTOR"]
    auto_router = [
        record.body for record in rules
        if record.record_id == '["RULE","AUTO_ROUTER","Common"]'
    ]
    return {
        "templates": templates,
        "rule_count": len(rules),
        "selector_count": len(selectors),
        "auto_router_common": auto_router,
        "rule_digest": digest(records, RULE_TYPES),
    }


def audit(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.before, args.after):
        if not path.is_file():
            raise FileNotFoundError(path)
    before = HELPERS.parse_source(args.before)
    after = HELPERS.parse_source(args.after)
    before_map = record_map(before, "before")
    after_map = record_map(after, "after")
    before_keys = set(before_map)
    after_keys = set(after_map)
    added = after_keys - before_keys
    removed = before_keys - after_keys
    changed = {
        key for key in before_keys & after_keys
        if before_map[key].body != after_map[key].body
    }
    changed_types = Counter(key[0] for key in changed)
    added_types = Counter(key[0] for key in added)
    removed_types = Counter(key[0] for key in removed)
    disallowed = {
        key for key in added | removed | changed
        if key[0] not in ALLOWED_CHANGED_TYPES
    }

    protected = {
        "geometry": GEOMETRY_TYPES,
        "electrical": ELECTRICAL_TYPES,
        "stack": STACK_TYPES,
    }
    protected_results: dict[str, Any] = {}
    for label, kinds in protected.items():
        before_inventory = inventory(before, kinds)
        after_inventory = inventory(after, kinds)
        before_ids = {
            record_key(record) for record in before if record.kind in kinds
        }
        after_ids = {
            record_key(record) for record in after if record.kind in kinds
        }
        exact = before_inventory == after_inventory and before_ids == after_ids
        if not exact:
            raise AssertionError(f"protected {label} data changed")
        protected_results[label] = {
            "before": before_inventory,
            "after": after_inventory,
            "id_sets_and_bodies_exact": True,
        }

    if disallowed:
        raise AssertionError(f"non-rule data changed: {sorted(disallowed)[:20]}")
    before_rule = rule_summary(before)
    after_rule = rule_summary(after)
    after_names = [str(item.get("name") or "") for item in after_rule["templates"]]
    if args.expected_rule_name not in after_names:
        raise AssertionError(
            f"expected rule profile {args.expected_rule_name!r} not found: {after_names}"
        )

    body_changes = []
    for key in sorted(changed):
        body_changes.append({
            "type": key[0],
            "id": key[1],
            "before": before_map[key].body,
            "after": after_map[key].body,
        })
    changed_record_types = set(changed_types) | set(added_types) | set(removed_types)
    status = (
        "dochead-identity-only-changed; all-board-record-ids-and-bodies-exact"
        if changed_record_types <= {"DOCHEAD"} else
        "only-rule-and-dochead-bodies-changed; geometry-electrical-stack-exact"
    )
    return {
        "schema": "stm32h747-native-pcb-rule-change-audit-v1",
        "status": status,
        "read_only": True,
        "inputs": {
            "before": {"path": str(args.before), "sha256": sha256_file(args.before)},
            "after": {"path": str(args.after), "sha256": sha256_file(args.after)},
        },
        "record_counts": {
            "before": dict(sorted(Counter(record.kind for record in before).items())),
            "after": dict(sorted(Counter(record.kind for record in after).items())),
        },
        "diff": {
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
            "added_types": dict(sorted(added_types.items())),
            "removed_types": dict(sorted(removed_types.items())),
            "changed_types": dict(sorted(changed_types.items())),
            "added": [{"type": kind, "id": record_id} for kind, record_id in sorted(added)],
            "removed": [{"type": kind, "id": record_id} for kind, record_id in sorted(removed)],
            "body_changes": body_changes,
            "disallowed_change_count": 0,
        },
        "protected_data": protected_results,
        "rules": {"before": before_rule, "after": after_rule},
        "manufacturing_ready": False,
        "remaining_gates": [
            "native DRC result review",
            "netlist comparison",
            "final copied/board-linked checkpoint verification",
            "manufacturing export comparison",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    parser.add_argument(
        "--expected-rule-name",
        default="JLCPCB Capability(Multiple Layers Board)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = audit(args)
        atomic_write_text(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(compact({
            "status": report["status"],
            "after_sha256": report["inputs"]["after"]["sha256"],
            "changed_types": report["diff"]["changed_types"],
            "added_types": report["diff"]["added_types"],
            "removed_types": report["diff"]["removed_types"],
            "rule_template": report["rules"]["after"]["templates"],
        }))
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
