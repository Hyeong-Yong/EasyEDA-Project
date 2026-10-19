"""Prepare a non-executable 3D candidate mapping from the frozen inventory.

Writes JSON/TXT only under output/3d-models-20261018. No native calls.
Model axes, offset origin and pin-1 mark must be calibrated against the selected
mesh; the source determines 2D registration, not arbitrary meshes' coordinates.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
MM_TO_MIL = 1 / .0254


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def angle(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360


def mean(points):
    return [sum(p[i] for p in points) / len(points) for i in range(2)]


def center_of_bounds(bounds):
    return [(bounds["xmin_mm"] + bounds["xmax_mm"]) / 2, (bounds["ymin_mm"] + bounds["ymax_mm"]) / 2]


def row_registration(centers, pin_count, first_row_count):
    left = [centers[str(i)] for i in range(1, first_row_count + 1)]
    right = [centers[str(i)] for i in range(first_row_count + 1, pin_count + 1)]
    return (angle(left[0], left[-1]) + 90) % 360, mean([mean(left), mean(right)])


def body_spec(x, y, z, basis, height_basis="Unverified representative package height; selected mesh/default or manufacturer drawing must supersede this value."):
    return {"x_mm": x, "y_mm": y, "z_mm": z, "xy_basis": basis, "height_basis": height_basis,
            "mpn_dimensions_verified": False, "purpose": "visual package-equivalent candidate, not mechanical-fit certification"}


def family_spec(part):
    g, ref = part["package_group"], part["ref"]
    passive = {
        "R_0402": ("0402R", 1, .5, .35), "R_0603": ("0603R", 1.6, .8, .45),
        "C_0402": ("0402C", 1, .5, .5), "C_0603": ("0603C", 1.6, .8, .8),
        "C_0805": ("0805C", 2, 1.25, 1.25), "C_1206": ("1206C", 3.2, 1.6, 1.6),
        "C_1411": ("TANTALUM_B_3528", 3.5, 2.8, 1.9), "FB_0603": ("0603_FERRITE", 1.6, .8, .8),
        "L_0806": ("0806_INDUCTOR", 2, 1.6, 1), "LED_0805_2012M_HandSolder": ("0805_LED", 2, 1.25, .8),
        "D_SOD-523": ("SOD523", 1.2, .8, .6), "D_SMB [DO-214AA]": ("SMB_DO214AA", 4.3, 3.6, 2.3),
        "CLK_SMD_NX3215SA-L": ("CRYSTAL_3215_2PIN", 3.2, 1.5, .9),
    }
    if g in passive:
        family, x, y, z = passive[g]
        basis = "Nominal package-code XY; actual MPN height not validated."
        height = "Unverified representative package height."
        if g == "C_0402":
            height = "0.5mm is the 0402C system-model size confirmed by the C1 UI pilot; actual capacitor MPN height remains unverified."
        return family, body_spec(x, y, z, basis, height), "two_terminal"
    if "SOD323" in g:
        return "SOD323", body_spec(1.95, 1.5, 1.1, "Footprint layer9 body outline XY; Z is a generic candidate."), "two_terminal"
    if "SOT23_5" in g:
        return "SOT23_5_DBV", body_spec(1.6, 2.9, 1.2, "Footprint layer9 exact XY outline; canonical X crosses lead rows, Y follows each row."), "row5"
    if g.startswith("SOT-23-6"):
        return "SOT23_6", body_spec(1.7, 3, 1.2, "XY explicitly named by footprint; canonical X crosses lead rows."), "row6"
    if g == "SOT-23":
        return "SOT23_3", body_spec(1.3, 2.9, 1.1, "Representative SOT23 package; canonical X crosses lead rows."), "row3"
    if g.startswith("DFN-6"):
        return "DFN6_3X3_EP", body_spec(3, 3, 1, "3x3mm explicitly named by footprint; pin7 is exposed pad."), "row6ep"
    if "SOIC8" in g or g.startswith("SOIC-8"):
        return "SOIC8_150MIL", body_spec(3.9, 4.9, 1.75, "Footprint name/layer9 XY; X crosses rows, Y follows rows."), "row8"
    if g.startswith("SOIC-16"):
        return "SOIC16_150MIL", body_spec(3.9, 9.9, 1.75, "Actual SOIC16 footprint; stale U8 Package=SOIC-8 is intentionally ignored."), "row16"
    if g.startswith("SOT-223"):
        return "SOT223", body_spec(3.5, 6.5, 1.8, "Representative body XY; source silk orientation shows body center offset -1.575mm X."), "sot223"
    if g == "IC_LAN8742A-CZ-TR":
        return "QFN24_4X4_EP", body_spec(4, 4, 1, "Representative package family/body footprint silk."), "qfn24"
    if g == "USB3320C-EZK":
        return "QFN32_5X5_EP", body_spec(5, 5, 1, "Representative QFN32 family/body footprint silk."), "qfn32"
    if g == "TFBGA-265_14x14mm":
        return "TFBGA265_14X14", body_spec(14, 14, 1.2, "14x14mm explicitly named by footprint."), "bga265"
    if g == "TFBGA-90_8X13mm_ISI":
        return "TFBGA90_13X8_SOURCE_AXES", body_spec(13, 8, 1.2, "Footprint name 8x13mm; local pad rectangle/lines establish long dimension along local X."), "bga90"
    if g.startswith("CLK_OSC"):
        return "OSCILLATOR_3225_4PIN", body_spec(3.2, 2.5, 1.2, "3.2x2.5mm explicitly named by footprint."), "osc4"
    if g == "SW_PUSH_SMD_6mm":
        return "TACT_SWITCH_6X6", body_spec(6, 6, 7.5, "6mm footprint label; 7.5mm is a value-name hypothesis H075, not a verified drawing."), "switch"
    if g == "TR_KMS_1102NL":
        return "ETHERNET_TRANSFORMER_16PIN_KMS1102", body_spec(None, None, None, "Actual MPN model/drawing required; pad row spacing is not body size."), "transformer"
    if g == "CON_SMA_RA":
        return "SMA_RA_KWE901", body_spec(None, None, None, "Actual right-angle connector mesh required; square 8.3mm silk does not give barrel/depth/height."), "sma"
    if g == "PJ-051BH":
        return "DC_JACK_PJ051BH", body_spec(None, None, None, "MPN-specific connector mesh/drawing required; footprint body-edge registration retained separately."), "dcjack"
    if g == "RJ45_LPJE101-0AHNL":
        return "RJ45_RA_LPJE101", body_spec(None, None, None, "MPN-specific shielded right-angle connector mesh/drawing required."), "rj45"
    if g == "USB_C_GCT_USB4105-GF-A_Custum":
        return "USB_C_USB4105_GF_A", body_spec(None, None, None, "MPN-specific USB4105 mesh required; silk region does not include a verified complete shell model."), "usb"
    if g.startswith("CON_SAMTEC"):
        return "SAMTEC_FTSH107_14_SMD", body_spec(None, None, None, "MPN-specific FTSH107 mesh required; SMD-tail row separation is 4.07mm, not a 1.27mm through-hole header."), "header14"
    if g.startswith("CON_HeaderSocket"):
        return "SOCKET_2X5_P254", body_spec(None, None, None, "PPTC052LFBN-RC drawing/mesh preferred; pitch/row spacing established from pins."), "socket10"
    raise ValueError((ref, g))


def main():
    parts, fps = read("components-437.json"), read("footprints-288.json")
    excluded, targets = [], []
    for p in parts:
        if p["dnp"] or p["ref"].startswith("TP"):
            excluded.append({"ref": p["ref"], "reason": "DNP" if p["dnp"] else "bare test-point pad; no fitted body"})
            continue
        fp = fps[p["footprint_uuid"]]
        c = fp["orientation_hints"]["pin_centers_mm"]
        family, body, strategy = family_spec(p)
        theta, xy, basis, ambiguities = None, [0, 0], "", []
        if strategy == "two_terminal":
            theta = fp["orientation_hints"]["two_terminal_pin1_to_pin2_axis_deg"]
            xy = fp["orientation_hints"]["two_terminal_midpoint_mm"]
            basis = "Canonical terminal1 at -X, terminal2 at +X; rotation/center computed from actual pad centroids."
        elif strategy.startswith("row"):
            count = {"row3": 3, "row5": 5, "row6": 6, "row6ep": 6, "row8": 8, "row16": 16}[strategy]
            first = 2 if count == 3 else 3 if count == 5 else count // 2
            theta, xy = row_registration(c, count, first)
            basis = "Canonical first pin on left row at +Y, numbering progresses toward -Y; body center is midpoint of lead-row centers."
        elif strategy == "sot223":
            theta = (angle(c["1"], c["3"]) + 90) % 360
            xy = mean([mean([c["1"], c["2"], c["3"]]), c["4"]])
            basis = "Canonical three pins on left row, tab on right; midpoint between lead row and tab."
            ambiguities.append("Selected SOT223 mesh origin must be registered; geometry gives center -1.575mm X rather than footprint origin.")
        elif strategy in ("qfn24", "qfn32"):
            n = 6 if strategy == "qfn24" else 8
            theta = (angle(c["1"], c[str(n)]) + 90) % 360
            xy = mean([c[str(i)] for i in range(1, n * 4 + 1)])
            basis = "Canonical first side is left with pin1 at +Y, subsequent pins toward -Y; exposed-pad drill holes ignored."
        elif strategy in ("bga265", "bga90"):
            xy = center_of_bounds(fp["pad_envelope_mm"])
            theta = 0
            basis = "Source canonical A1 at minX/minY; letter rows increase +X, numeric columns +Y. Source body axes are used, not assumed model axes."
            ambiguities.append("Chosen BGA mesh A1 corner/axis convention requires verification; a generic 8x13 model may require swapping XY/90deg relative to the source 13x8 body axes.")
        elif strategy == "osc4":
            xy = mean([c[str(i)] for i in range(1, 5)])
            theta = 180 if c["1"][0] > xy[0] else 0
            basis = "Body long axis X from pad spans; canonical pin1 marker at -X/-Y, source pin1 at +X/+Y."
            ambiguities.append("Four-pin oscillator selected mesh pin1 marking and numbered terminal convention need visual verification; supplied rotation matches body axes/corner only.")
        elif strategy == "switch":
            theta = 0
            xy = mean([c["1"], c["2"]])
            basis = "Symmetric 6x6 actuator body; actual two logical contacts each have two physical pads."
            ambiguities.append("Actuator/body height must be taken from an actual GT-TC089B-H075-L1 mesh/drawing; candidate 7.5mm is unverified.")
        elif strategy == "transformer":
            theta, xy = row_registration(c, 16, 8)
            basis = "16-pad numbering establishes lead-row registration; actual asymmetric transformer body dimensions not recoverable from pads."
            ambiguities.append("Actual KMS1102 model body extent/origin/height needed; do not resize using pad envelope.")
        elif strategy == "sma":
            nearest = min([(p["x_mm"], 180), (100 - p["x_mm"], 0), (p["y_mm"], 270), (154 - p["y_mm"], 90)])
            theta = nearest[1]
            basis = "Port-axis +X canonical; outward direction is INFERRED from nearest 100x154mm board edge, not determined by the symmetric footprint."
            ambiguities.append("Four shell legs plus central signal pad and square silk are rotationally symmetric. Confirm barrel outward direction and model's signal-pin origin before native assignment.")
        elif strategy in ("usb", "dcjack", "rj45"):
            bb = fp["drawn_envelopes_by_layer_mm"]["3"]
            xy = center_of_bounds(bb)
            theta = 90 if strategy == "usb" and p["ref"] == "CN4" else 0
            basis = "Source silk-region centroid and opening toward local +X (CN3/CN1/CN2) or +Y (CN4); model shell datum is not established by this bound."
            ambiguities.append("The silk-region center includes stroke/marking and is only an initial shell offset. Exact chosen mesh must be registered against the asymmetric named pads/mechanical holes.")
        elif strategy == "header14":
            xy = mean([c[str(i)] for i in range(1, 15)])
            theta = angle(c["1"], c["13"])
            basis = "Long header axis from pin1 to pin13; pin1 at -X/-Y; numbered SMD pads only, NPTH locator holes excluded."
            ambiguities.append("Require FTSH107 SMD-tail mesh or equivalent with correct tails/polarization; generic through-hole 2x7 is unsuitable.")
        elif strategy == "socket10":
            xy = mean([c[str(i)] for i in range(1, 11)])
            theta = angle(c["1"], c["9"])
            basis = "Canonical long axis from pin1 to pin9; pin1 at -X/-Y in canonical socket definition; row2 on +Y."
            # With theta=180 the source pin1 remains +X/-Y, so matching a pin1
            # corner would additionally depend on model Y convention.
            ambiguities.append("Source pin1 at +X/-Y; chosen socket model pin1 corner/handedness and height require checking. Long-axis registration alone leaves 180deg/row ambiguity.")
        else:
            raise AssertionError(strategy)
        theta = theta % 360
        if min(abs(theta - round(theta / 90) * 90), abs(theta - 360)) < 1e-4:
            theta = (round(theta / 90) * 90) % 360
        if strategy != "two_terminal" or p["ref"].startswith("D") or p["ref"] == "C41":
            ambiguities.append("Native model rotZ sign/pin1 orientation must be calibrated against the selected model; numeric source-Y convention alone is insufficient.")
        dims = [body[k] for k in ("x_mm", "y_mm", "z_mm")]
        # Native size is the COMPLETE selected mesh extent, including leads and
        # balls. Body XY cannot be used to shrink a SOIC/SOT mesh with leads.
        # Only the 0402C complete mesh size has been confirmed by the root pilot.
        native_size = [v * MM_TO_MIL for v in dims] if family == "0402C" else [None, None, None]
        candidate = [*native_size, theta, 0, 0, xy[0] * MM_TO_MIL, xy[1] * MM_TO_MIL, 0]
        ar = math.radians(p["rotation_deg"])
        ox, oy = xy
        if p["side"] == "bottom":
            oy = -oy
        worldcenter = [p["x_mm"] + ox * math.cos(ar) - oy * math.sin(ar), p["y_mm"] + ox * math.sin(ar) + oy * math.cos(ar)]
        model = {"family": family, "relation": "package-equivalent candidate; no exact-MPN mesh verified", "uuid": None, "library_uuid": None}
        if family == "0402C":
            model.update({"uuid": "6034de4795654a0c8c74309dab7cb0b9", "library_uuid": "0819f05c4eef4c71ace90d822a990e87", "title": "0402C",
                          "evidence": "C1 native UI pilot confirmed by root; 1x0.5x0.5mm size. This is a package model, not an exact capacitor MPN."})
        targets.append({"ref": p["ref"], "component_id": p["component_id"], "footprint_uuid": p["footprint_uuid"],
                        "part_number": p["part_number"], "value": p["value"], "source_package_group": p["package_group"],
                        "model_candidate": model, "nominal_body": body,
                        "registration": {"local_rotation_z_deg": theta, "local_offset_mm": [*xy, 0], "basis": basis,
                                         "native_transform_mil_candidate": candidate,
                                         "native_sizing_confirmed": family == "0402C",
                                         "native_sizing_policy": "Keep selected mesh full XYZ extents until its geometry is inspected. Body dimensions do not include leads/balls and must not be copied into full-mesh size fields. Null size fields are intentionally non-executable.",
                                         "native_candidate_note": "Size XYZ mil, rotZXY deg, offset XYZ mil. Rotation is relative to the explicitly documented canonical package, not yet to an arbitrary selected mesh: add its verified axis/pin1 correction. Native PCB side mirroring must handle bottom, not a second manual flip.",
                                         "side": p["side"], "component_rotation_deg": p["rotation_deg"], "world_body_center_mm": worldcenter,
                                         "world_primary_axis_deg": (p["rotation_deg"] + (-theta if p["side"] == "bottom" else theta)) % 360},
                        "ambiguities": ambiguities,
                        "source_local_pin_centers_mm": c,
                        "scope": "Candidate plan only; no board/model/library writes or native calls."})
    assert len(targets) == 412 and len(excluded) == 25
    assert Counter(x["reason"] for x in excluded) == {"DNP": 6, "bare test-point pad; no fitted body": 19}
    groups = defaultdict(list)
    for t in targets:
        groups[t["model_candidate"]["family"]].append(t["ref"])
    result = {"schema": "stm32-per-component-3d-transform-candidates-v1", "status": "CANDIDATE_NOT_APPLIED", "native_calls": 0,
              "source_inventory_sha256": hashlib.sha256((HERE / "components-437.json").read_bytes()).hexdigest(),
              "target_count": len(targets), "excluded_count": len(excluded), "excluded": excluded,
              "family_counts": {k: len(v) for k, v in sorted(groups.items())},
              "family_refs": dict(sorted(groups.items())),
              "native_transform_order": ["sizeX_mil", "sizeY_mil", "sizeZ_mil", "rotZ_deg", "rotX_deg", "rotY_deg", "offsetX_mil", "offsetY_mil", "offsetZ_mil"],
              "registration_convention": "2D footprint-local numeric axes. Component mount-side and rotation are separate. Canonical axes are explicitly documented per entry; model-relative origin/handedness must be calibrated.",
              "limits": ["No model UUID except root-confirmed 0402C is asserted available; other families are search/matching targets.",
                         "Nominal XY from named packages/source body outline are separated from representative unverified Z heights; generic heights must not be presented as manufacturer dimensions.",
                         "Exact MPN mesh match is not claimed for any target, including the system 0402C model.",
                         "Only 0402C native complete-mesh XYZ size is confirmed. Other native arrays deliberately have null size fields: preserve selected model's full extents, never shrink a leaded mesh to body dimensions.",
                         "SMA outward directions are nearest-edge inferences because the footprints are rotationally symmetric.",
                         "U8 actual SOIC16 footprint takes precedence over its stale SOIC8 Package attribute.",
                         "DNP6 and bare TP19 have no model bodies in an as-fitted rendering."],
              "targets": targets}
    (OUT / "component-3d-transform-candidates.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    no_size = [t["ref"] for t in targets if any(t["nominal_body"][k] is None for k in ("x_mm", "y_mm", "z_mm"))]
    size_confirmed = [t["ref"] for t in targets if t["registration"]["native_sizing_confirmed"]]
    bottom = [t["ref"] for t in targets if t["registration"]["side"] == "bottom"]
    report = ["STM32H747 component 3D candidate plan — not applied", "", f"Targets: {len(targets)} fitted bodies; excluded: DNP6 + bare test points19.",
              "Known system mesh: 0402C, model6034de4795654a0c8c74309dab7cb0b9, library0819f05c4eef4c71ace90d822a990e87, root-confirmed C1 pilot.",
              "Other model family entries are package-equivalent search targets; no unverified UUIDs or exact-MPN claims.",
              "Native sizeXYZ is COMPLETE mesh extent including leads/balls. Only 0402C size is confirmed; other arrays intentionally contain null XYZ. Retain selected model extents and calibrate its axes/mark before applying rotation/offset candidates.",
              "", "Unresolved nominal body dimensions (actual model/drawing required): " + ", ".join(no_size),
              "Bottom bodies, native mount-side mirroring required: " + ", ".join(bottom),
              "", "Critical baked rotation/offset examples:"]
    for ref in ["C1", "C5", "C41", "U2", "U6", "U8", "U9", "U10", "U5", "U7", "CN3", "CN4", "J2", "J12", "J16"]:
        t = next(t for t in targets if t["ref"] == ref)
        r = t["registration"]
        report.append(f"{ref}: family={t['model_candidate']['family']}, local rotZ={r['local_rotation_z_deg']:.6g}deg, offset={r['local_offset_mm']}; {r['basis']}")
    report += ["", "All Z heights except the demonstrated generic 0402C 0.5mm are explicitly unverified representative package candidates.",
               "SMA16 have only a symmetric land pattern: outward direction is an inference, not a source-proven model orientation.",
               "U8 is SOIC16 despite the stale SOIC8 package attribute. FTSH J1 is SMD-tail 14-pin, not generic through-hole.",
               "No CAD, DB, original export, model library, native application, bridge or unrelated project was modified."]
    (OUT / "component-3d-transform-candidates.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"targets": len(targets), "excluded": len(excluded), "families": len(groups), "native_full_mesh_size_confirmed_count": len(size_confirmed), "body_nominal_dimensions_unresolved": no_size, "bottom": bottom}))


if __name__ == "__main__":
    main()
