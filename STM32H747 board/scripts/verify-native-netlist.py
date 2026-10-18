"""Compare an exported native EasyEDA netlist with reference-netlist.json.

Native EasyEDA Pro ``Protel2``/Altium netlist text is accepted directly.  Its
documented shape is a sequence of line-delimited net blocks::

    (
    GND
    R2-2 0603WAF1002T5E-2 Input
    C1-2 CC0603KRX7R9BB104-2 Passive
    )

Only the first token of each node line is electrical identity; it is split at
the final hyphen into designator and pin number.  The format omits explicit NC
pins and page identity, so those limitations are declared in the report rather
than silently weakening net-name or pin-number matching.

The alternate capture contract is canonical JSON with a top-level ``pins``
array::

    {"pins": [
      {"ref": "C1", "number": "1", "net": "+3V3",
       "page": 2, "no_connect": false}
    ]}

The adapter also accepts a top-level list, ``records`` instead of ``pins``,
component objects containing pin arrays, page objects, and net objects
containing node/pin arrays.  Never weaken comparison rules to hide a mismatch.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE = ROOT / "output" / "semantic" / "reference-netlist.json"


REF_KEYS = ("ref", "reference", "designator", "componentRef", "component_reference")
NUMBER_KEYS = ("number", "pin", "pinNumber", "pin_number", "pad", "padNumber", "pad_number")
NET_KEYS = ("net", "netName", "net_name", "network", "networkName")
PAGE_KEYS = ("page", "sheet", "sheetIndex", "sheet_index", "sheetPage", "sheet_page")
NC_KEYS = ("no_connect", "noConnect", "nc", "isNC", "is_nc")


def first(mapping: dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().casefold()
    if text in {
        "true", "yes", "y", "1", "nc", "n/c", "no_connect", "no-connect",
        "no_connect_marker", "intrinsic_nc", "dnp_disconnected",
    }:
        return True
    if text in {"false", "no", "n", "0", "", "connected"}:
        return False
    raise ValueError(f"cannot interpret boolean value {value!r}")


def normalize_page(value: Any, page_by_name: dict[str, int]) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid page {value!r}")
    if isinstance(value, (int, float)) and int(value) == value:
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if text.casefold() in page_by_name:
        return page_by_name[text.casefold()]
    raise ValueError(f"cannot map candidate page/sheet {value!r}")


def looks_like_pin(record: Any) -> bool:
    return isinstance(record, dict) and first(record, NUMBER_KEYS) is not None


def inherit(record: dict[str, Any], **values: Any) -> dict[str, Any]:
    result = dict(record)
    for key, value in values.items():
        if value is not None and key not in result:
            result[key] = value
    return result


def extract_candidate_records(payload: Any, inherited_page: Any = None) -> list[dict[str, Any]]:
    """Flatten supported JSON shapes into candidate pin records."""
    if isinstance(payload, list):
        if all(looks_like_pin(item) for item in payload):
            return [inherit(item, page=inherited_page) for item in payload]
        records: list[dict[str, Any]] = []
        for item in payload:
            records.extend(extract_candidate_records(item, inherited_page))
        return records
    if not isinstance(payload, dict):
        return []
    if looks_like_pin(payload) and first(payload, REF_KEYS) is not None:
        return [inherit(payload, page=inherited_page)]

    page = first(payload, PAGE_KEYS, inherited_page)
    for key in ("pins", "records"):
        value = payload.get(key)
        if isinstance(value, list) and all(looks_like_pin(item) for item in value):
            return [inherit(item, page=page) for item in value]

    components = payload.get("components")
    if isinstance(components, list):
        records = []
        for component in components:
            if not isinstance(component, dict):
                continue
            reference = first(component, REF_KEYS)
            component_page = first(component, PAGE_KEYS, page)
            component_pins = component.get("pins") or component.get("pads") or []
            for pin in component_pins:
                if isinstance(pin, dict):
                    records.append(inherit(pin, ref=reference, page=component_page))
        if records:
            return records

    nets = payload.get("nets")
    if isinstance(nets, list):
        records = []
        for net_object in nets:
            if not isinstance(net_object, dict):
                continue
            net_name = first(net_object, NET_KEYS, net_object.get("name"))
            nodes = net_object.get("pins") or net_object.get("nodes") or net_object.get("members") or []
            for node in nodes:
                if isinstance(node, dict):
                    records.append(inherit(node, net=net_name, page=page))
        if records:
            return records

    pages = payload.get("pages") or payload.get("sheets")
    if isinstance(pages, list):
        records = []
        for page_object in pages:
            records.extend(extract_candidate_records(page_object, page))
        if records:
            return records

    for wrapper in ("result", "data", "netlist"):
        if wrapper in payload:
            records = extract_candidate_records(payload[wrapper], page)
            if records:
                return records
    return []


def normalize_record(record: dict[str, Any], page_by_name: dict[str, int]) -> dict[str, Any]:
    reference = str(first(record, REF_KEYS, "")).strip()
    number = str(first(record, NUMBER_KEYS, "")).strip()
    if not reference or not number:
        raise ValueError(f"candidate record lacks ref or pin number: {record!r}")
    net_value = first(record, NET_KEYS)
    net = None if net_value is None else str(net_value).strip()
    if net == "":
        net = None
    no_connect_value = first(record, NC_KEYS)
    if no_connect_value is None and "electrical_state" in record:
        no_connect_value = record["electrical_state"]
    no_connect = boolean(no_connect_value)
    page = normalize_page(first(record, PAGE_KEYS), page_by_name)
    if no_connect and net is not None:
        raise ValueError(f"candidate {reference}.{number} is NC but has net {net!r}")
    if not no_connect and net is None:
        raise ValueError(f"candidate {reference}.{number} has neither net nor NC state")
    return {"ref": reference, "number": number, "net": net, "page": page, "no_connect": no_connect}


def load_json(path_text: str) -> Any:
    if path_text == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path_text).read_text(encoding="utf-8"))


def parse_protel2(text: str) -> list[dict[str, Any]]:
    """Parse EasyEDA's documented Protel2/Altium line netlist format.

    Parenthesized characters are legal inside generated net names, so blocks
    are deliberately recognized only by lines whose complete stripped value is
    ``(`` or ``)``.  Component library/footprint/pin-type fields after the first
    node token are not electrical identity and are intentionally ignored.
    """

    records: list[dict[str, Any]] = []
    in_net = False
    net_name: str | None = None
    block_count = 0
    for line_number, raw_line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw_line.strip()
        if not in_net:
            if line == "(":
                in_net = True
                net_name = None
                block_count += 1
            continue
        if line == ")":
            if net_name is None:
                raise ValueError(f"Protel2 net block {block_count} has no net name")
            in_net = False
            net_name = None
            continue
        if not line:
            continue
        if net_name is None:
            net_name = line
            continue

        node = line.split(None, 1)[0]
        if "-" not in node:
            raise ValueError(
                f"Protel2 line {line_number} has an invalid node token {node!r}"
            )
        reference, number = node.rsplit("-", 1)
        if not reference or not number:
            raise ValueError(
                f"Protel2 line {line_number} has an invalid node token {node!r}"
            )
        records.append(
            {
                "ref": reference,
                "number": number,
                "net": net_name,
                "page": None,
                "no_connect": False,
            }
        )
    if in_net:
        raise ValueError("unterminated Protel2 net block")
    if not block_count:
        raise ValueError("no line-delimited Protel2 net blocks found")
    if not records:
        raise ValueError("Protel2 netlist contains no component pin nodes")
    return records


def _embedded_netlist_text(payload: Any) -> str | None:
    """Find a full netlist string in a JSON wrapper returned by a bridge/API."""

    if isinstance(payload, str):
        return payload if "\n(" in "\n" + payload else None
    if isinstance(payload, list):
        for value in payload:
            result = _embedded_netlist_text(value)
            if result is not None:
                return result
        return None
    if not isinstance(payload, dict):
        return None
    for key in ("base64", "dataBase64", "contentBase64"):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8-sig")
        except (ValueError, UnicodeDecodeError):
            continue
        if "\n(" in "\n" + decoded:
            return decoded
    for key in ("netlist", "text", "content", "data", "value", "result"):
        if key in payload:
            result = _embedded_netlist_text(payload[key])
            if result is not None:
                return result
    return None


def load_candidate(path_text: str, format_name: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load canonical JSON pins or native Protel2 text plus capabilities."""

    if path_text == "-":
        text = sys.stdin.read()
    else:
        text = Path(path_text).read_text(encoding="utf-8-sig")

    payload: Any = None
    selected = format_name
    if selected in {"auto", "json"}:
        try:
            payload = json.loads(text)
            selected = "json"
        except json.JSONDecodeError:
            if format_name == "json":
                raise
            selected = "protel2"

    if selected == "json":
        flattened = extract_candidate_records(payload)
        if flattened:
            return flattened, {
                "format": "json-pins",
                "includes_no_connect": True,
                "includes_page": any(first(item, PAGE_KEYS) is not None for item in flattened),
            }
        embedded = _embedded_netlist_text(payload)
        if embedded is None:
            raise ValueError(
                "no candidate pins or full embedded netlist string found in JSON capture"
            )
        return parse_protel2(embedded), {
            "format": "protel2-in-json",
            "includes_no_connect": False,
            "includes_page": False,
        }

    if selected != "protel2":
        raise ValueError(f"unsupported candidate format {selected!r}")
    return parse_protel2(text), {
        "format": "protel2",
        "includes_no_connect": False,
        "includes_page": False,
    }


def key(record: dict[str, Any]) -> tuple[str, str]:
    return record["ref"], record["number"]


def comparable(record: dict[str, Any], ignore_page: bool) -> tuple[Any, ...]:
    fields: tuple[Any, ...] = (record["net"], record["no_connect"])
    return fields if ignore_page else fields + (record["page"],)


def sorted_keys(values: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    def natural(value: str) -> tuple[Any, ...]:
        return tuple(int(part) if part.isdigit() else part.casefold()
                     for part in re.split(r"(\d+)", value))
    return sorted(values, key=lambda value: (natural(value[0]), natural(value[1])))


def summarize_record(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in ("ref", "number", "net", "page", "no_connect")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "candidate",
        help="native Protel2 .net text, captured/normalized JSON, or - for stdin",
    )
    parser.add_argument(
        "--format",
        choices=("auto", "json", "protel2"),
        default="auto",
        help="candidate format; auto tries JSON first and otherwise parses Protel2",
    )
    parser.add_argument("--reference", default=str(DEFAULT_REFERENCE), help="reference-netlist.json path")
    parser.add_argument("--report", help="optional path for the full machine-readable comparison report")
    parser.add_argument("--ignore-page", action="store_true",
                        help="compare ref/pin/net/NC only (for an API export that cannot expose sheet identity)")
    parser.add_argument("--max-display", type=int, default=20, help="mismatches printed per category")
    args = parser.parse_args()

    try:
        reference = load_json(args.reference)
        if reference.get("schema") != "stm32h747-reference-netlist-v1":
            raise ValueError(f"unsupported reference schema {reference.get('schema')!r}")
        page_by_name = {
            str(item["sheet_name"]).casefold(): int(item["page"])
            for item in reference.get("page_map", [])
        }
        expected = [normalize_record(item, page_by_name) for item in reference["pins"]]
        flattened, capabilities = load_candidate(args.candidate, args.format)
        actual = [normalize_record(item, page_by_name) for item in flattened]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    effective_ignore_page = args.ignore_page or not capabilities["includes_page"]
    expected_counts = Counter(key(item) for item in expected)
    actual_counts = Counter(key(item) for item in actual)
    expected_duplicates = sorted_keys(item for item, count in expected_counts.items() if count > 1)
    actual_duplicates = sorted_keys(item for item, count in actual_counts.items() if count > 1)
    expected_by_key = {key(item): item for item in expected}
    actual_by_key = {key(item): item for item in actual}
    expected_keys_all = set(expected_by_key)
    actual_keys = set(actual_by_key)
    expected_nc_keys = {
        identity for identity, item in expected_by_key.items() if item["no_connect"]
    }
    if capabilities["includes_no_connect"]:
        expected_keys = expected_keys_all
        omitted_expected_nc: list[tuple[str, str]] = []
        nc_connected: list[dict[str, Any]] = []
    else:
        expected_keys = expected_keys_all - expected_nc_keys
        omitted_expected_nc = sorted_keys(expected_nc_keys)
        nc_connected = [
            {
                "ref": identity[0],
                "number": identity[1],
                "expected": summarize_record(expected_by_key[identity]),
                "actual": summarize_record(actual_by_key[identity]),
                "differences": ["no_connect", "net"],
            }
            for identity in sorted_keys(expected_nc_keys & actual_keys)
        ]
    missing = sorted_keys(expected_keys - actual_keys)
    unexpected = sorted_keys(actual_keys - expected_keys - expected_nc_keys)
    mismatches = []
    for identity in sorted_keys(expected_keys & actual_keys):
        expected_record = expected_by_key[identity]
        actual_record = actual_by_key[identity]
        if comparable(expected_record, effective_ignore_page) != comparable(actual_record, effective_ignore_page):
            mismatches.append({
                "ref": identity[0],
                "number": identity[1],
                "expected": summarize_record(expected_record),
                "actual": summarize_record(actual_record),
                "differences": [
                    field for field in ("net", "no_connect", *([] if effective_ignore_page else ["page"]))
                    if expected_record[field] != actual_record[field]
                ],
            })

    passed = not (
        expected_duplicates
        or actual_duplicates
        or missing
        or unexpected
        or mismatches
        or nc_connected
    )
    report = {
        "schema": "stm32h747-native-netlist-verification-v2",
        "status": "match" if passed else "mismatch",
        "candidate": {
            **capabilities,
            "limitations": [
                item
                for item in (
                    "explicit no-connect pins are absent from this format"
                    if not capabilities["includes_no_connect"]
                    else None,
                    "sheet/page identity is absent from this format"
                    if not capabilities["includes_page"]
                    else None,
                )
                if item is not None
            ],
        },
        "comparison": {
            "identity": ["ref", "number"],
            "fields": ["net", "no_connect"] + ([] if effective_ignore_page else ["page"]),
            "ignore_page": effective_ignore_page,
            "ignore_page_requested": args.ignore_page,
            "nc_policy": (
                "compare explicit NC records"
                if capabilities["includes_no_connect"]
                else "require every connected reference pin, reject any exported NC reference pin, and account for omitted NC pins"
            ),
        },
        "counts": {
            "expected_pins": len(expected),
            "expected_connected_pins": len(expected) - len(expected_nc_keys),
            "expected_no_connect_pins": len(expected_nc_keys),
            "candidate_pins": len(actual),
            "matched_pins": len(expected_keys & actual_keys) - len(mismatches),
            "missing_pins": len(missing),
            "unexpected_pins": len(unexpected),
            "mismatched_pins": len(mismatches),
            "nc_pins_in_candidate": len(nc_connected),
            "expected_nc_pins_omitted_by_format": len(omitted_expected_nc),
            "expected_duplicate_identities": len(expected_duplicates),
            "candidate_duplicate_identities": len(actual_duplicates),
        },
        "expected_duplicates": [{"ref": ref, "number": number} for ref, number in expected_duplicates],
        "candidate_duplicates": [{"ref": ref, "number": number} for ref, number in actual_duplicates],
        "missing": [summarize_record(expected_by_key[item]) for item in missing],
        "unexpected": [summarize_record(actual_by_key[item]) for item in unexpected],
        "mismatches": mismatches,
        "nc_pins_in_candidate": nc_connected,
        "expected_nc_pins_omitted_by_format": [
            summarize_record(expected_by_key[item]) for item in omitted_expected_nc
        ],
    }
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"status={report['status']}")
    print(json.dumps(report["counts"], ensure_ascii=False, indent=2))
    limit = max(args.max_display, 0)
    for category in (
        "expected_duplicates",
        "candidate_duplicates",
        "missing",
        "unexpected",
        "mismatches",
        "nc_pins_in_candidate",
    ):
        values = report[category]
        if values and limit:
            print(f"{category} (showing {min(limit, len(values))}/{len(values)}):")
            print(json.dumps(values[:limit], ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
