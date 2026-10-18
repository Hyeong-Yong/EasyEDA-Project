"""Audit the August-revision value changes and ten removed-capacitor PCB bridges.

This is a static, read-only checker.  It does not call EasyEDA or modify a
project.  The JSON report is intended to make the June-Gerber to August-PDF
reconstruction decisions durable and independently reviewable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
PROJECT_MEMBER = "STM32H747_MCU_BOARD_v19.epru"
DEFAULT_PCB = ROOT / "output/validation/native-final-pcb-after_inner_pad_shapes-reopened.epru"
DEFAULT_CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_inner_pad_shapes_20261014.epro2"
DEFAULT_ROUTES = ROOT / "output/semantic/gerber-copper-routes.json"
DEFAULT_ROUTE_MANIFEST = ROOT / "output/native-pcb/gerber-routing-reference-manifest.json"
DEFAULT_OUTPUT = ROOT / "output/validation/native-final-pcb-latest-revision-gap-audit.json"
MM_TO_MIL = 1000.0 / 25.4
EPS_MM = 0.000003
EPS_MIL = 0.0002


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def input_record(path: Path) -> dict[str, Any]:
    return {"path": rel(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def parse_line(raw: str) -> tuple[dict[str, Any], dict[str, Any]]:
    header_text, body_text = raw.split("||", 1)
    if body_text.endswith("|"):
        body_text = body_text[:-1]
    return json.loads(header_text), json.loads(body_text)


def read_native(path: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [parse_line(raw) for raw in path.read_text(encoding="utf-8-sig").splitlines()]


def native_net_name(header: dict[str, Any]) -> str | None:
    if header.get("type") != "NET":
        return None
    try:
        key = json.loads(str(header.get("id")))
    except json.JSONDecodeError:
        return None
    return str(key[1]) if isinstance(key, list) and len(key) >= 2 else None


def pad_net_identity(header: dict[str, Any]) -> tuple[str, str, str] | None:
    if header.get("type") != "PAD_NET":
        return None
    try:
        key = json.loads(str(header.get("id")))
    except json.JSONDecodeError:
        return None
    if not isinstance(key, list) or len(key) < 4:
        return None
    return str(key[1]), str(key[2]), str(key[3])


def close(left: float, right: float, tolerance: float) -> bool:
    return math.isclose(float(left), float(right), rel_tol=0, abs_tol=tolerance)


def point_in_polygon(point: list[float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    for index, current in enumerate(polygon):
        previous = polygon[index - 1]
        x1, y1 = previous
        x2, y2 = current
        if ((y1 > y) != (y2 > y)) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def region_polygon(region: dict[str, Any]) -> list[list[float]]:
    contours = region.get("contours") or []
    if len(contours) != 1:
        raise AssertionError("expected one contour for removed-capacitor continuation region")
    segments = contours[0]
    if not segments or any(segment.get("kind") != "line" for segment in segments):
        raise AssertionError("removed-capacitor continuation region is not a line-only polygon")
    points = [segment["startMm"] for segment in segments]
    if segments[-1]["endMm"] != points[0]:
        points.append(segments[-1]["endMm"])
    return points


def checkpoint_schematic_attributes(path: Path) -> dict[str, dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        lines = archive.read(PROJECT_MEMBER).decode("utf-8-sig").splitlines()
    result: dict[str, dict[str, Any]] = {}
    current_type: str | None = None
    attrs: list[dict[str, Any]] = []

    def flush() -> None:
        if current_type != "SCH_PAGE":
            return
        parents = {
            str(body.get("value")): str(body.get("parentId"))
            for body in attrs
            if body.get("key") == "Designator"
        }
        for reference, parent_id in parents.items():
            result[reference] = {
                str(body.get("key")): body.get("value")
                for body in attrs
                if str(body.get("parentId")) == parent_id
            }

    for raw in lines:
        header, body = parse_line(raw)
        if header.get("type") == "DOCHEAD":
            flush()
            current_type = str(body.get("docType"))
            attrs = []
        elif current_type == "SCH_PAGE" and header.get("type") == "ATTR":
            attrs.append(body)
    flush()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pcb-source", type=Path, default=DEFAULT_PCB)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--routes", type=Path, default=DEFAULT_ROUTES)
    parser.add_argument("--route-manifest", type=Path, default=DEFAULT_ROUTE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    records = read_native(args.pcb_source)
    routes = json.loads(args.routes.read_text(encoding="utf-8"))
    manifest = json.loads(args.route_manifest.read_text(encoding="utf-8"))
    schematic = checkpoint_schematic_attributes(args.checkpoint)

    designators = {
        str(body.get("value")): str(body.get("parentId"))
        for header, body in records
        if header.get("type") == "ATTR" and body.get("key") == "Designator"
    }
    component_count = sum(header.get("type") == "COMPONENT" for header, _ in records)
    if component_count != 330 or len(designators) != 330:
        raise AssertionError(f"expected 330 native components/designators, got {component_count}/{len(designators)}")

    line_by_id = {
        str(header.get("id")): body for header, body in records if header.get("type") == "LINE"
    }
    net_records = {
        name for header, _ in records if (name := native_net_name(header)) is not None
    }
    pad_nets: dict[tuple[str, str], dict[str, Any]] = {}
    for header, body in records:
        identity = pad_net_identity(header)
        if identity is not None:
            component_id, number, library_pad_id = identity
            pad_nets[(component_id, number)] = {
                "library_pad_id": library_pad_id,
                "net": str(body.get("padNet")),
            }

    bridge_rows = manifest["net_patch"]["bridges"]
    bridge_by_ref = {str(row["removed_component"]): row for row in bridge_rows}
    channels = routes["latestPatches"]["page6BiasChannels"]
    if len(channels) != 10 or len(bridge_by_ref) != 10:
        raise AssertionError("expected ten removed-capacitor channels and ten bridge records")

    min_x, min_y, _, _ = routes["coordinateTransform"]["boardBoundsSourceMm"]
    layer = routes["copper"]["layers"]["F.Cu"]
    channel_reports: list[dict[str, Any]] = []
    all_old_nets: set[str] = set()
    for channel in channels:
        reference = str(channel["removedComponent"])
        latest = str(channel["latestNet"])
        old_nets = [str(value) for value in channel["oldNets"]]
        all_old_nets.update(old_nets)
        bridge_meta = bridge_by_ref[reference]
        primitive_id = str(bridge_meta["primitive_id"])
        native = line_by_id.get(primitive_id)
        if native is None:
            raise AssertionError(f"{reference}: bridge LINE {primitive_id} missing")
        hint = channel["replacementCopperHint"]
        start_mm = [float(value) for value in hint["startMm"]]
        end_mm = [float(value) for value in hint["endMm"]]
        expected_start = [(start_mm[0] - min_x) * MM_TO_MIL, (start_mm[1] - min_y) * MM_TO_MIL]
        expected_end = [(end_mm[0] - min_x) * MM_TO_MIL, (end_mm[1] - min_y) * MM_TO_MIL]
        actual_start = [float(native["startX"]), float(native["startY"])]
        actual_end = [float(native["endX"]), float(native["endY"])]
        if any(not close(a, e, EPS_MIL) for a, e in zip(actual_start + actual_end, expected_start + expected_end)):
            raise AssertionError(f"{reference}: native bridge coordinates differ from the frozen hint")
        if native.get("layerId") != 1 or not close(native.get("width"), 0.25 * MM_TO_MIL, EPS_MIL):
            raise AssertionError(f"{reference}: bridge layer or width changed")
        if str(native.get("netName")).upper() != latest.upper():
            raise AssertionError(f"{reference}: bridge net differs from the August schematic")

        old_tracks = [item for item in layer["tracks"] if item.get("netOld") in old_nets]
        old_regions = [item for item in layer["regions"] if item.get("netOld") in old_nets]
        if len(old_tracks) != 1 or len(old_regions) != 1:
            raise AssertionError(f"{reference}: expected one old track and one old region")
        track = old_tracks[0]
        track_points = [track["startMm"], track["endMm"]]
        track_touches_start = any(
            math.hypot(point[0] - start_mm[0], point[1] - start_mm[1]) <= EPS_MM
            for point in track_points
        )
        region_contains_end = point_in_polygon(end_mm, region_polygon(old_regions[0]))
        if not track_touches_start or not region_contains_end:
            raise AssertionError(f"{reference}: bridge does not close both sides of the former capacitor gap")

        upper_ref = str(channel["upperBiasResistor"])
        upper_component = designators.get(upper_ref)
        upper_pad2 = pad_nets.get((str(upper_component), "2"))
        if upper_pad2 is None or str(upper_pad2["net"]).upper() != latest.upper():
            raise AssertionError(f"{reference}: {upper_ref}.2 is not bound to the latest net")
        if reference in designators:
            raise AssertionError(f"{reference}: removed component still exists in native PCB")

        channel_reports.append({
            "removed_component": reference,
            "upper_bias_resistor": upper_ref,
            "adc_net": channel["adcNet"],
            "old_nets": old_nets,
            "latest_net": latest,
            "bridge": {
                "primitive_id": primitive_id,
                "layer_id": native["layerId"],
                "width_mm": 0.25,
                "start_mm": start_mm,
                "end_mm": end_mm,
                "native_start_mil": actual_start,
                "native_end_mil": actual_end,
            },
            "physical_continuity": {
                "left_old_track_exact_endpoint": track_touches_start,
                "right_old_region_contains_endpoint": region_contains_end,
            },
            "native_latest_pad_net": upper_pad2,
        })

    old_native_names = {name.upper() for name in net_records} & {name.upper() for name in all_old_nets}
    if old_native_names:
        raise AssertionError(f"obsolete NET records remain: {sorted(old_native_names)}")
    if any(reference in designators for reference in bridge_by_ref):
        raise AssertionError("one or more removed capacitors remain in the native PCB")
    if not manifest["validation"]["route_net_set_equals_latest_reference_netlist"]:
        raise AssertionError("route net set no longer equals the latest reference netlist")
    if manifest["validation"]["latest_unique_net_count"] != 279:
        raise AssertionError("latest reference net count changed")

    expected_values = {
        "C69": {"Value": "470p", "Name": "470p", "DNP": "no", "Add into BOM": "yes"},
        "R129": {"Value": "100k", "Name": "100k", "DNP": "no", "Add into BOM": "yes"},
    }
    upper_refs = [str(channel["upperBiasResistor"]) for channel in channels]
    for reference in upper_refs:
        expected_values[reference] = {
            "Value": "7.5k", "Name": "7.5k", "DNP": "no", "Add into BOM": "yes"
        }
    lower_refs = ["R146", "R147", "R148", "R158", "R159", "R160", "R173", "R174", "R175", "R176"]
    for reference in lower_refs:
        expected_values[reference] = {
            "Value": "30k_NC", "Name": "30k_NC", "DNP": "yes", "Add into BOM": "no"
        }
    value_reports: dict[str, Any] = {}
    for reference, expected in expected_values.items():
        actual = schematic.get(reference)
        if actual is None:
            raise AssertionError(f"{reference}: absent from native schematic checkpoint")
        mismatches = {key: [expected_value, actual.get(key)] for key, expected_value in expected.items() if actual.get(key) != expected_value}
        if mismatches:
            raise AssertionError(f"{reference}: native schematic attributes differ: {mismatches}")
        value_reports[reference] = {key: actual[key] for key in expected}

    report = {
        "schema": "stm32h747-latest-revision-bias-gap-audit-v1",
        "status": "pass-static-reconstruction-not-manufacturing-approval",
        "inputs": {
            "native_pcb_source": input_record(args.pcb_source),
            "native_project_checkpoint": input_record(args.checkpoint),
            "gerber_route_semantics": input_record(args.routes),
            "native_route_manifest": input_record(args.route_manifest),
        },
        "native_pcb": {
            "component_records": component_count,
            "unique_designators": len(designators),
            "native_net_records_including_empty": len(net_records),
            "latest_route_net_count": manifest["validation"]["latest_unique_net_count"],
            "removed_components_absent": sorted(bridge_by_ref),
            "obsolete_old_nets_absent": sorted(all_old_nets),
        },
        "removed_capacitor_channels": channel_reports,
        "latest_native_schematic_attributes": value_reports,
        "checks": {
            "physical_component_count_330": True,
            "removed_capacitors_absent_from_native_pcb": True,
            "obsolete_twenty_old_net_records_absent": True,
            "ten_latest_net_records_and_upper_resistor_pad2_bindings_present": True,
            "ten_bridge_lines_present_with_frozen_ids_net_width_layer_and_endpoints": True,
            "each_bridge_touches_old_left_track_and_overlaps_old_right_region": True,
            "route_net_set_equals_latest_reference_netlist_279": True,
            "native_schematic_c69_470p_r129_100k": True,
            "native_schematic_upper_ten_7p5k_fitted": True,
            "native_schematic_lower_ten_30k_nc_dnp": True,
        },
        "release_note": (
            "The ten bridge lines are explicit Gerber-to-August reconstruction patches. "
            "This static proof does not replace final native DRC and diagnostic manufacturing-file review."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": rel(args.output), "sha256": sha256(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
