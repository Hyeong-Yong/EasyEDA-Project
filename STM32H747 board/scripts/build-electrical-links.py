"""Build an authoritative electrical-link plan for the reconstructed sheets.

The KiCad PDF semantic extraction already assigns every green wire segment and
every component pin an exact net name.  This script turns those independent
segments into the connected WIRE groups expected by EasyEDA Pro and resolves
every pin to one of four native connection mechanisms:

* a geometrically touching WIRE group;
* a global NetFlag at the same coordinate;
* another pin at the same coordinate;
* a deliberate no-connect state.

It does not edit a schematic.  The output is deterministic input for
``build-native-schematic-pages.py`` and for runtime/ERC verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEMANTIC = ROOT / "output" / "semantic" / "schematic-pages-2-6.json"
DEFAULT_LIBRARY = ROOT / "output" / "native-libraries" / "manifest.json"
DEFAULT_DEVICES = ROOT / "output" / "native-libraries" / "devices.json"
DEFAULT_OUTPUT = ROOT / "output" / "semantic" / "electrical-links.json"
TOLERANCE = 0.002  # EasyEDA units; source geometry is normally on a 5-unit grid.
PDF_PT_TO_EASYEDA = 100.0 / 72.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rid(label: str) -> str:
    """Match the deterministic IDs used by build-native-schematic-pages.py."""

    return uuid.uuid5(uuid.NAMESPACE_URL, "stm32h747-native/" + label).hex[:16]


def rounded_point(point: Iterable[float], digits: int = 6) -> tuple[float, float]:
    x, y = point
    return round(float(x), digits), round(float(y), digits)


def points_equal(a: Iterable[float], b: Iterable[float], tol: float = TOLERANCE) -> bool:
    ax, ay = a
    bx, by = b
    return abs(ax - bx) <= tol and abs(ay - by) <= tol


def point_on_segment(
    point: Iterable[float],
    start: Iterable[float],
    end: Iterable[float],
    tol: float = TOLERANCE,
) -> bool:
    """Return True for a point on an arbitrary (not just orthogonal) segment."""

    px, py = map(float, point)
    ax, ay = map(float, start)
    bx, by = map(float, end)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length <= tol:
        return points_equal(point, start, tol)
    cross = abs((px - ax) * dy - (py - ay) * dx)
    if cross > tol * max(1.0, length):
        return False
    return (
        min(ax, bx) - tol <= px <= max(ax, bx) + tol
        and min(ay, by) - tol <= py <= max(ay, by) + tol
    )


def _orientation(a: Iterable[float], b: Iterable[float], c: Iterable[float]) -> float:
    ax, ay = a
    bx, by = b
    cx, cy = c
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def proper_intersection(
    a1: Iterable[float],
    a2: Iterable[float],
    b1: Iterable[float],
    b2: Iterable[float],
    tol: float = TOLERANCE,
) -> bool:
    """Whether two segments cross, including touching and collinear overlap."""

    if any(
        point_on_segment(point, start, end, tol)
        for point, start, end in (
            (a1, b1, b2),
            (a2, b1, b2),
            (b1, a1, a2),
            (b2, a1, a2),
        )
    ):
        return True
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)
    return (o1 > tol and o2 < -tol or o1 < -tol and o2 > tol) and (
        o3 > tol and o4 < -tol or o3 < -tol and o4 > tol
    )


class DisjointSet:
    def __init__(self, values: Iterable[int]):
        self.parent = {value: value for value in values}

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


@dataclass(frozen=True)
class Segment:
    index: int
    net: str
    p1: tuple[float, float]
    p2: tuple[float, float]


def segments_are_connected(
    left: Segment,
    right: Segment,
    junctions: list[tuple[float, float]],
    tol: float = TOLERANCE,
) -> bool:
    """Apply schematic connectivity rules without joining plain crossings.

    Shared endpoints, endpoint-on-line T connections, and collinear overlap are
    connected.  An interior/interior crossing is connected only when the PDF
    contains a junction dot at the crossing.
    """

    if left.net != right.net:
        return False

    endpoint_touch = any(
        point_on_segment(point, start, end, tol)
        for point, start, end in (
            (left.p1, right.p1, right.p2),
            (left.p2, right.p1, right.p2),
            (right.p1, left.p1, left.p2),
            (right.p2, left.p1, left.p2),
        )
    )
    if endpoint_touch:
        return True
    if not proper_intersection(left.p1, left.p2, right.p1, right.p2, tol):
        return False
    return any(
        point_on_segment(junction, left.p1, left.p2, tol)
        and point_on_segment(junction, right.p1, right.p2, tol)
        for junction in junctions
    )


def build_wire_groups(page: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, int]]:
    """Group only geometrically connected segments of the same exact net."""

    segments = [
        Segment(
            index=index,
            net=wire["net"],
            p1=rounded_point(wire["p1_easyeda"]),
            p2=rounded_point(wire["p2_easyeda"]),
        )
        for index, wire in enumerate(page["wire_segments"])
    ]
    if any(not segment.net for segment in segments):
        raise ValueError(f"Page {page['pdf_page']} contains a wire without an exact net")

    junctions = [rounded_point(item["centre_easyeda"]) for item in page["junctions"]]
    by_net: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        by_net[segment.net].append(segment)

    dsu = DisjointSet(segment.index for segment in segments)
    for net_segments in by_net.values():
        for offset, left in enumerate(net_segments):
            for right in net_segments[offset + 1 :]:
                if segments_are_connected(left, right, junctions):
                    dsu.union(left.index, right.index)

    members: dict[int, list[Segment]] = defaultdict(list)
    for segment in segments:
        members[dsu.find(segment.index)].append(segment)

    raw_groups = sorted(members.values(), key=lambda value: min(item.index for item in value))
    groups: list[dict[str, Any]] = []
    segment_to_group: dict[int, int] = {}
    for group_index, group_segments in enumerate(raw_groups):
        group_segments.sort(key=lambda item: item.index)
        nets = {item.net for item in group_segments}
        if len(nets) != 1:
            raise AssertionError(f"Mixed-net WIRE group on page {page['pdf_page']}: {nets}")
        net = next(iter(nets))
        native_wire_id = rid(f"{page['pdf_page']}/electrical-wiregroup/{group_index}")
        group_junctions = [
            list(point)
            for point in junctions
            if sum(point_on_segment(point, item.p1, item.p2) for item in group_segments) >= 2
        ]
        group = {
            "index": group_index,
            "native_wire_id": native_wire_id,
            "native_net_attr_id": rid(
                f"{page['pdf_page']}/electrical-wiregroup/{group_index}/NET"
            ),
            "native_relevance_attr_id": rid(
                f"{page['pdf_page']}/electrical-wiregroup/{group_index}/Relevance"
            ),
            "net": net,
            "segment_indices": [item.index for item in group_segments],
            "line_ids": [
                rid(f"{page['pdf_page']}/wireline/{item.index}")
                for item in group_segments
            ],
            "junctions_easyeda": sorted(group_junctions),
            "attached_pins": [],
        }
        groups.append(group)
        for segment in group_segments:
            segment_to_group[segment.index] = group_index
    return groups, segment_to_group


def component_id(page_number: int, reference: str) -> str:
    return rid(f"{page_number}/component/{reference}")


def pin_primitive_lookup(
    library: dict[str, Any],
    instances: list[dict[str, Any]],
) -> dict[tuple[int, str, str], dict[str, Any]]:
    """Map semantic (page, reference, pin number) to the generated PIN row."""

    result: dict[tuple[int, str, str], dict[str, Any]] = {}
    symbols = library["symbols"]
    for instance in instances:
        symbol = symbols[instance["base_reference"]]
        candidates = [
            pin
            for pin in symbol["pins"]
            if pin["part"] == instance["subpart"]
        ]
        for pin in candidates:
            key = (instance["page"], instance["reference"], str(pin["number"]))
            if key in result:
                raise ValueError(f"Duplicate native PIN mapping: {key}")
            result[key] = pin
    return result


def netflag_identification(value: str) -> str:
    if value == "GND":
        return "Ground"
    if value == "Earth_P":
        return "ProtectGround"
    return "Power"


def supplemental_flag_endpoint(
    point: tuple[float, float], component: dict[str, Any]
) -> tuple[float, float]:
    """Return a non-zero point hidden inside the drawn NetFlag pin stroke.

    EasyEDA does not electrically join a NetFlag and an ordinary component pin
    merely because their terminals are coincident.  The reference drawing has
    fourteen such direct overlaps.  A short native WIRE must therefore lie on
    top of the existing NetFlag pin stroke.  A real source graphic segment is
    selected instead of trusting the heuristic ``side`` field (one rotated GND
    symbol is intentionally a counterexample).
    """

    drawn_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for line in component["graphics"]["lines"]:
        drawn_segments.append(
            (rounded_point(line["p1_easyeda"]), rounded_point(line["p2_easyeda"]))
        )
    for curve in component["graphics"]["curves"]:
        current: tuple[float, float] | None = None
        for command in curve["path_top_left_pt"]:
            if not command.get("points"):
                continue
            raw = command["points"][-1]
            target = rounded_point(
                (raw[0] * PDF_PT_TO_EASYEDA, raw[1] * PDF_PT_TO_EASYEDA)
            )
            if command["op"] == "m":
                current = target
            elif command["op"] == "l" and current is not None:
                drawn_segments.append((current, target))
                current = target

    candidates: list[tuple[float, tuple[float, float]]] = []
    for start, end in drawn_segments:
        if points_equal(point, start) and not points_equal(start, end):
            candidates.append((math.dist(start, end), end))
        elif points_equal(point, end) and not points_equal(start, end):
            candidates.append((math.dist(start, end), start))
    if not candidates:
        raise ValueError(
            f"No drawn NetFlag pin stroke at {point} for {component['reference']}"
        )
    return min(candidates, key=lambda item: item[0])[1]


def page_plan(
    page: dict[str, Any],
    pin_lookup: dict[tuple[int, str, str], dict[str, Any]],
) -> dict[str, Any]:
    page_number = page["pdf_page"]
    groups, _ = build_wire_groups(page)
    segments = [
        Segment(
            index=index,
            net=wire["net"],
            p1=rounded_point(wire["p1_easyeda"]),
            p2=rounded_point(wire["p2_easyeda"]),
        )
        for index, wire in enumerate(page["wire_segments"])
    ]

    net_flags: list[dict[str, Any]] = []
    power_drivers: list[dict[str, Any]] = []
    all_connected_by_location: dict[
        tuple[tuple[float, float], str], list[tuple[dict[str, Any], dict[str, Any]]]
    ] = defaultdict(list)
    for component in page["components"]:
        for pin in component["pins"]:
            if pin["electrical_state"] != "connected":
                continue
            key = (rounded_point(pin["connection"]["easyeda"]), pin["net"])
            all_connected_by_location[key].append((component, pin))

    for component in page["components"]:
        if not component.get("is_power_symbol"):
            continue
        pin = component["pins"][0]
        item = {
            "reference": component["reference"],
            "native_component_id": component_id(page_number, component["reference"]),
            "value": component["value"],
            "net": pin["net"],
            "terminal_easyeda": list(rounded_point(pin["connection"]["easyeda"])),
            "native_pin_number": str(pin["number"]),
        }
        if component["value"] == "PWR_FLAG" or component["reference"].startswith("#FLG"):
            item.update(
                {
                    "native_role": "power_driver_net_flag_translation",
                    "identification": "Power",
                    "required_component_type": "netflag",
                    "required_symbol_doc_type": 18,
                    "required_pin_type": "OUT",
                    "required_attributes": {
                        "Global Net Name": pin["net"],
                        "Name": pin["net"],
                        "Relevance": "[]",
                    },
                    "reason": "KiCad PWR_FLAG is translated to a native type-18 NetFlag whose Name and Global Net Name both equal the actual rail, while its source power-output (OUT) ERC role remains encoded on the library pin",
                }
            )
            power_drivers.append(item)
        else:
            item.update(
                {
                    "native_role": "global_net_flag",
                    "identification": netflag_identification(component["value"]),
                    "required_component_type": "netflag",
                    "required_symbol_doc_type": 18,
                    "required_attributes": {
                        "Global Net Name": pin["net"],
                        "Name": pin["net"],
                        "Relevance": "[]",
                    },
                }
            )
            net_flags.append(item)

    netflag_locations = {
        (tuple(item["terminal_easyeda"]), item["net"]): item for item in net_flags
    }

    pin_links: list[dict[str, Any]] = []
    missing_native_pins: list[dict[str, Any]] = []
    unresolved_connected: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    method_counts: Counter[str] = Counter()
    group_by_index = {item["index"]: item for item in groups}

    for component in page["components"]:
        cid = component_id(page_number, component["reference"])
        for pin in component["pins"]:
            number = str(pin["number"])
            state = pin["electrical_state"]
            connection = pin.get("connection")
            point = (
                rounded_point(connection["easyeda"])
                if connection and connection.get("easyeda") is not None
                else None
            )
            native_pin = pin_lookup.get((page_number, component["reference"], number))
            native_pin_id = f"{cid}-{native_pin['primitive_id']}" if native_pin else None
            if native_pin is None and state != "intrinsic_nc":
                missing_native_pins.append(
                    {"reference": component["reference"], "number": number}
                )

            matching_groups: list[int] = []
            if state == "connected" and point is not None:
                for group in groups:
                    if group["net"] != pin["net"]:
                        continue
                    if any(
                        point_on_segment(point, segments[index].p1, segments[index].p2)
                        for index in group["segment_indices"]
                    ):
                        matching_groups.append(group["index"])

            location_key = (point, pin.get("net")) if point is not None else None
            peers = all_connected_by_location.get(location_key, []) if location_key else []
            flag = netflag_locations.get(location_key) if location_key else None
            if state == "no_connect_marker":
                method = "no_connect_marker"
            elif state == "intrinsic_nc":
                method = "hidden_intrinsic_nc"
            elif matching_groups:
                method = "wire_group"
            elif flag:
                method = (
                    "global_net_flag_anchor"
                    if flag["reference"] == component["reference"]
                    else "global_net_flag"
                )
            elif len(peers) > 1:
                method = "direct_pin_overlap"
            else:
                method = "unresolved"

            link = {
                "reference": component["reference"],
                "base_reference": component["base_reference"],
                "unit": component.get("unit"),
                "number": number,
                "net": pin.get("net"),
                "point_easyeda": list(point) if point is not None else None,
                "electrical_state": state,
                "native_component_id": cid,
                "native_pin_id": native_pin_id,
                "native_pin_primitive_id": native_pin["primitive_id"] if native_pin else None,
                "method": method,
                "wire_group_indices": matching_groups,
                "global_net_flag_reference": flag["reference"] if flag else None,
                "peer_pins": [
                    {"reference": peer_component["reference"], "number": str(peer_pin["number"])}
                    for peer_component, peer_pin in peers
                    if peer_component["reference"] != component["reference"]
                    or str(peer_pin["number"]) != number
                ],
            }
            pin_links.append(link)
            state_counts[state] += 1
            method_counts[method] += 1
            if method == "unresolved":
                unresolved_connected.append(link)
            for group_index in matching_groups:
                group_by_index[group_index]["attached_pins"].append(
                    {
                        "reference": component["reference"],
                        "number": number,
                        "native_pin_id": native_pin_id,
                        "point_easyeda": list(point) if point is not None else None,
                    }
                )

    direct_clusters = []
    for (point, net), peers in sorted(all_connected_by_location.items()):
        if len(peers) < 2:
            continue
        direct_clusters.append(
            {
                "point_easyeda": list(point),
                "net": net,
                "pins": [
                    {"reference": component["reference"], "number": str(pin["number"])}
                    for component, pin in peers
                ],
                "contains_global_net_flag": (point, net) in netflag_locations,
            }
        )

    component_by_reference = {
        component["reference"]: component for component in page["components"]
    }
    supplemental_wire_groups: list[dict[str, Any]] = []
    for cluster in direct_clusters:
        if not cluster["contains_global_net_flag"]:
            continue
        point = tuple(cluster["point_easyeda"])
        flag = netflag_locations[(point, cluster["net"])]
        flag_component = component_by_reference[flag["reference"]]
        flag_pin = flag_component["pins"][0]
        end = supplemental_flag_endpoint(point, flag_component)
        if points_equal(point, end):
            raise AssertionError(
                f"Zero-length supplemental NetFlag WIRE on page {page_number}: {flag['reference']}"
            )
        index = len(supplemental_wire_groups)
        supplemental_wire_groups.append(
            {
                "index": index,
                "native_wire_id": rid(
                    f"{page_number}/supplemental-wiregroup/{index}"
                ),
                "native_net_attr_id": rid(
                    f"{page_number}/supplemental-wiregroup/{index}/NET"
                ),
                "native_relevance_attr_id": rid(
                    f"{page_number}/supplemental-wiregroup/{index}/Relevance"
                ),
                "line_id": rid(f"{page_number}/supplemental-wireline/{index}"),
                "net": cluster["net"],
                "p1_easyeda": list(point),
                "p2_easyeda": list(end),
                "net_flag_reference": flag["reference"],
                "net_flag_terminal_side": flag_pin["side"],
                "attached_pins": cluster["pins"],
                "reason": "Native EasyEDA requires a non-zero WIRE to join a coincident NetFlag and physical pin; this segment overlays the existing flag pin stroke",
            }
        )

    for group in groups:
        group["attached_pins"].sort(key=lambda item: (item["reference"], item["number"]))

    return {
        "pdf_page": page_number,
        "sheet_index": page["new_sheet_index"],
        "sheet_name": page["sheet_name"],
        "wire_groups": groups,
        "supplemental_wire_groups": supplemental_wire_groups,
        "net_flags": sorted(net_flags, key=lambda item: item["reference"]),
        "power_driver_components": sorted(
            power_drivers, key=lambda item: item["reference"]
        ),
        "direct_pin_clusters": direct_clusters,
        "pin_links": sorted(pin_links, key=lambda item: (item["reference"], item["number"])),
        "validation": {
            "wire_segments": len(segments),
            "wire_groups": len(groups),
            "wire_group_reduction": len(segments) - len(groups),
            "supplemental_wire_groups": len(supplemental_wire_groups),
            "wire_groups_with_mixed_nets": sum(
                len({segments[index].net for index in group["segment_indices"]}) != 1
                for group in groups
            ),
            "global_net_flags": len(net_flags),
            "power_driver_components": len(power_drivers),
            "pin_state_counts": dict(sorted(state_counts.items())),
            "pin_connection_methods": dict(sorted(method_counts.items())),
            "missing_native_pin_ids": missing_native_pins,
            "unresolved_connected_pins": unresolved_connected,
        },
    }


def build_plan(
    semantic_path: Path = DEFAULT_SEMANTIC,
    library_path: Path = DEFAULT_LIBRARY,
    devices_path: Path = DEFAULT_DEVICES,
) -> dict[str, Any]:
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    library = json.loads(library_path.read_text(encoding="utf-8"))
    devices = json.loads(devices_path.read_text(encoding="utf-8"))
    instances = devices["instances"]
    pin_lookup = pin_primitive_lookup(library, instances)
    pages = [page_plan(page, pin_lookup) for page in semantic["pages"]]

    totals: Counter[str] = Counter()
    total_state_counts: Counter[str] = Counter()
    total_method_counts: Counter[str] = Counter()
    unresolved: list[dict[str, Any]] = []
    missing_native: list[dict[str, Any]] = []
    for page in pages:
        validation = page["validation"]
        for key in (
            "wire_segments",
            "wire_groups",
            "wire_group_reduction",
            "global_net_flags",
            "power_driver_components",
            "supplemental_wire_groups",
        ):
            totals[key] += validation[key]
        total_state_counts.update(validation["pin_state_counts"])
        total_method_counts.update(validation["pin_connection_methods"])
        unresolved.extend(
            {"page": page["pdf_page"], **item}
            for item in validation["unresolved_connected_pins"]
        )
        missing_native.extend(
            {"page": page["pdf_page"], **item}
            for item in validation["missing_native_pin_ids"]
        )

    return {
        "schema": "stm32h747-electrical-links-v1",
        "purpose": "Connected EasyEDA WIRE groups, native pin IDs, NetFlags, and NC truth for PDF pages 2-6",
        "sources": {
            "semantic": {"path": str(semantic_path), "sha256": sha256(semantic_path)},
            "library_manifest": {"path": str(library_path), "sha256": sha256(library_path)},
            "devices": {"path": str(devices_path), "sha256": sha256(devices_path)},
        },
        "geometry_contract": {
            "coordinate_system": "EasyEDA schematic units (10 mil)",
            "tolerance": TOLERANCE,
            "wire_group_rule": "same exact net plus shared endpoint, endpoint-on-segment, collinear overlap, or explicit-junction crossing",
            "plain_crossing_rule": "interior/interior crossing without a PDF junction stays in separate WIRE groups",
            "supplemental_wire_rule": "direct NetFlag/physical-pin coincidences get a separate non-zero WIRE over the already drawn NetFlag pin stroke; these do not alter source segment/group counts",
        },
        "native_contract": {
            "wire_relevance": "[]",
            "wire_note": "API-created native wire probe retained empty Relevance; electrical association is geometric",
            "supplemental_wire_note": "Create each supplemental_wire_group as its own WIRE with one LINE plus exact-case NET and empty Relevance attributes",
            "component_pin_id": "<component UUID>-<symbol PIN primitive ID>",
            "no_connect_attribute": {
                "parent_id": "<component UUID>-<symbol PIN primitive ID>",
                "key": "NO_CONNECT",
                "value": "yes",
            },
            "net_flag": {
                "component_type": "netflag",
                "symbol_doc_type": 18,
                "attributes": ["Symbol", "Device", "Relevance", "Global Net Name", "Name"],
                "api": "SCH_PrimitiveComponent.createNetFlag(identification, net, x, y, rotation, mirror)",
                "power_probe": {
                    "part_id": "pid8a0e77bacb214e",
                    "symbol_uuid": "eae98f75c81ede90",
                    "device_uuid": "51cd75596c24845f",
                    "warning": "These exact IDs are the probed Power flag only; use createNetFlag for Ground/ProtectGround rather than guessing IDs",
                },
            },
            "pwr_flag_note": "All seven KiCad PWR_FLAG instances are native type-18 NetFlag translations whose Name and Global Net Name both equal the exact rail, while their library PIN keeps type OUT; using the literal component value PWR_FLAG as Name merges the seven rails during native netlist compilation",
        },
        "pages": pages,
        "validation": {
            **dict(sorted(totals.items())),
            "pin_state_counts": dict(sorted(total_state_counts.items())),
            "pin_connection_methods": dict(sorted(total_method_counts.items())),
            "unresolved_connected_pins": unresolved,
            "missing_native_pin_ids": missing_native,
            "status": "pass" if not unresolved and not missing_native else "fail",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic", type=Path, default=DEFAULT_SEMANTIC)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--devices", type=Path, default=DEFAULT_DEVICES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    plan = build_plan(args.semantic, args.library, args.devices)
    if plan["validation"]["status"] != "pass":
        raise SystemExit(json.dumps(plan["validation"], ensure_ascii=False, indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    # Byte write keeps the JSON checksum independent of Windows newline rules.
    args.output.write_bytes(payload.encode("utf-8"))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                "validation": plan["validation"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
