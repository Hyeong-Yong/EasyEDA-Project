"""Build the immutable schematic truth netlist from extracted PDF semantics.

Only physical component pins are emitted.  Power-symbol pseudo components are
connectivity labels, not PCB component pads, and therefore do not belong in
the physical pin-to-net comparison used before PCB creation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
SEMANTIC_PATH = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
OUTPUT_PATH = ROOT / "output" / "semantic" / "reference-netlist.json"
NO_CONNECT_STATES = {"no_connect_marker", "intrinsic_nc", "dnp_disconnected"}


def natural_key(value: str) -> tuple[Any, ...]:
    """Return a deterministic human/numeric sort key for refs and pin names."""
    return tuple(int(part) if part.isdigit() else part.casefold()
                 for part in re.split(r"(\d+)", value))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    semantic = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    strict = semantic.get("strict_pin_validation", {})
    if strict.get("status") != "complete":
        raise ValueError("semantic strict_pin_validation is not complete")

    physical_validation = strict.get("physical_components", {})
    groups = physical_validation.get("groups", [])
    incomplete_groups = [group for group in groups if group.get("status") != "complete"]
    if incomplete_groups:
        refs = ", ".join(str(group.get("base_reference")) for group in incomplete_groups[:12])
        raise ValueError(f"semantic physical pin validation is incomplete: {refs}")

    pins: list[dict[str, Any]] = []
    page_map: list[dict[str, Any]] = []
    component_refs: set[str] = set()
    state_counts: Counter[str] = Counter()

    for page in semantic["pages"]:
        rebuilt_page = int(page["new_sheet_index"])
        source_pdf_page = int(page["pdf_page"])
        page_map.append({
            "page": rebuilt_page,
            "source_pdf_page": source_pdf_page,
            "sheet_name": page["sheet_name"],
        })
        for component in page["components"]:
            if component.get("is_power_symbol"):
                continue
            reference = str(component.get("base_reference") or component.get("reference") or "").strip()
            if not reference:
                raise ValueError(f"physical component without reference on PDF page {source_pdf_page}")
            component_refs.add(reference)
            for pin in component.get("pins", []):
                number = str(pin.get("number") or "").strip()
                if not number:
                    raise ValueError(f"{reference} has a physical pin without a number")
                state = str(pin.get("electrical_state") or "").strip()
                state_counts[state] += 1
                no_connect = state in NO_CONNECT_STATES
                net_value = pin.get("net")
                net = str(net_value).strip() if net_value is not None else None
                if net == "":
                    net = None
                if no_connect and net is not None:
                    raise ValueError(f"{reference}.{number} is NC but also has net {net!r}")
                if not no_connect and net is None:
                    raise ValueError(f"{reference}.{number} is neither connected nor explicitly NC")
                pins.append({
                    "ref": reference,
                    "number": number,
                    "net": net,
                    "page": rebuilt_page,
                    "no_connect": no_connect,
                })

    pins.sort(key=lambda pin: (natural_key(pin["ref"]), natural_key(pin["number"]), pin["page"]))
    keys = [(pin["ref"], pin["number"]) for pin in pins]
    duplicate_keys = sorted((key for key, count in Counter(keys).items() if count > 1),
                            key=lambda key: (natural_key(key[0]), natural_key(key[1])))
    if duplicate_keys:
        raise ValueError(f"duplicate physical ref/pin identities: {duplicate_keys[:12]}")

    expected_by_ref = {
        str(group["base_reference"]): set(map(str, group["expected_pad_numbers"]))
        for group in groups
    }
    actual_by_ref: dict[str, set[str]] = {}
    for pin in pins:
        actual_by_ref.setdefault(pin["ref"], set()).add(pin["number"])
    if expected_by_ref != actual_by_ref:
        missing_refs = sorted(set(expected_by_ref) - set(actual_by_ref), key=natural_key)
        extra_refs = sorted(set(actual_by_ref) - set(expected_by_ref), key=natural_key)
        pin_mismatches = sorted(
            ref for ref in set(expected_by_ref) & set(actual_by_ref)
            if expected_by_ref[ref] != actual_by_ref[ref]
        )
        raise ValueError(
            "physical pin truth differs from strict validation: "
            f"missing refs={missing_refs[:8]}, extra refs={extra_refs[:8]}, "
            f"pin mismatches={pin_mismatches[:8]}"
        )

    connected_pins = sum(pin["net"] is not None for pin in pins)
    no_connect_pins = sum(pin["no_connect"] for pin in pins)
    per_page = []
    for mapping in sorted(page_map, key=lambda item: item["page"]):
        page_pins = [pin for pin in pins if pin["page"] == mapping["page"]]
        per_page.append({
            **mapping,
            "physical_pin_count": len(page_pins),
            "connected_pin_count": sum(pin["net"] is not None for pin in page_pins),
            "no_connect_pin_count": sum(pin["no_connect"] for pin in page_pins),
        })

    document = {
        "schema": "stm32h747-reference-netlist-v1",
        "source": {
            "path": "output/semantic/schematic-pages-2-6.json",
            "sha256": sha256(SEMANTIC_PATH),
            "semantic_schema": semantic.get("schema"),
            "authority": "latest schematic PDF pages 2-6 plus strict physical-pad validation",
        },
        "conventions": {
            "identity": ["ref", "number"],
            "record_fields": ["ref", "number", "net", "page", "no_connect"],
            "ref": "base physical reference; multipart units are consolidated",
            "number": "physical footprint pad/pin number serialized as a string",
            "net": "exact latest-PDF net name; null only for explicitly unconnected pins",
            "page": "rebuilt schematic page 1-5 after removing PDF cover page 1",
            "no_connect": "true for blue-X, intrinsic-NC, or deliberate DNP-disconnected pin",
            "power_symbols_excluded": True,
        },
        "page_map": sorted(page_map, key=lambda item: item["page"]),
        "counts": {
            "physical_component_count": len(component_refs),
            "physical_pin_count": len(pins),
            "connected_pin_count": connected_pins,
            "no_connect_pin_count": no_connect_pins,
            "unique_net_count": len({pin["net"] for pin in pins if pin["net"] is not None}),
            "electrical_state_counts": dict(sorted(state_counts.items())),
            "per_page": per_page,
        },
        "pins": pins,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(json.dumps(document["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
