"""Offline-only bounded legacy PRE copper isolation plan; no PCB candidate.

Generate an explicit primitive-ID manifest and small new PRE-to-bias-pad link
proposals. New OPA input/output paths await reviewed component placement.
"""
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import runpy

from shapely import affinity
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "output/validation/native-adc10-pcb-oriented-20261017.epru"
SOURCE_SHA = "a1981a3fd491e3f61daee520ebc2e768ddb3d2210e6ca0ce03474cec4a60213a"
LIB = runpy.run_path(str(HERE / "independent-adc10-pcb-footprint-pad-audit.py"))
SPECS = [
    ("J2", "R137", "R140", "R141", "C80", "U10", "ADC1_PRE1", "ADC1_DRV1", "ADC1_INP0"),
    ("J3", "R138", "R142", "R143", "C81", "U11", "ADC1_PRE2", "ADC1_DRV2", "ADC1_INP1"),
    ("J4", "R139", "R144", "R145", "C82", "U12", "ADC1_PRE3", "ADC1_DRV3", "ADC1_INP16"),
    ("J5", "R149", "R152", "R153", "C86", "U13", "ADC2_PRE1", "ADC2_DRV1", "ADC2_INP3"),
    ("J6", "R150", "R154", "R155", "C87", "U14", "ADC2_PRE2", "ADC2_DRV2", "ADC2_INP12"),
    ("J7", "R151", "R156", "R157", "C88", "U15", "ADC2_PRE3", "ADC2_DRV3", "ADC2_INP13"),
    ("J8", "R161", "R165", "R166", "C93", "U16", "ADC3_PRE1", "ADC3_DRV1", "ADC3_INP2"),
    ("J9", "R162", "R167", "R168", "C94", "U17", "ADC3_PRE2", "ADC3_DRV2", "ADC3_INP6"),
    ("J10", "R163", "R169", "R170", "C95", "U18", "ADC3_PRE3", "ADC3_DRV3", "ADC3_INP7"),
    ("J11", "R164", "R171", "R172", "C96", "U19", "ADC3_PRE4", "ADC3_DRV4", "ADC3_INP8"),
]
MM = .0254
MIN_GAP = .1524


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def line_shape(body):
    return LineString([(body["startX"]*MM, body["startY"]*MM),
                       (body["endX"]*MM, body["endY"]*MM)]).buffer(body["width"]*MM/2, resolution=32)


def fill_shape(body):
    assert len(body["path"]) == 1
    path = body["path"][0]
    assert path[2] == "L" and all(isinstance(v, (int, float)) for v in path if v != "L"), path
    values = [v for v in path if v != "L"]
    ring = [(values[i]*MM, values[i+1]*MM) for i in range(0, len(values), 2)]
    result = Polygon(ring)
    assert result.is_valid and result.area > 0
    # FILL's optional outline width is conservatively included in its region.
    return result.buffer(body.get("width", 0)*MM/2, resolution=32)


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA
    rows, headers, attrs = {}, {}, defaultdict(dict)
    for raw in SOURCE.read_text(encoding="utf8").splitlines():
        if not raw.strip(): continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], h.get("id")
        assert key not in rows
        rows[key], headers[key] = b, h
        if h["type"] == "ATTR": attrs[b["parentId"]][b["key"]] = b["value"]
    refs = {a["Designator"]: cid for cid, a in attrs.items() if "Designator" in a}
    docs = LIB["read_libs"]()
    errors, operations, channels, proposed = [], [], [], []

    def pad(ref, number):
        cid = refs[ref]
        component = rows["COMPONENT", cid]
        master = docs["FOOTPRINT", attrs[cid]["Footprint"]]
        matches = [(pid, p) for (kind, pid), p in master.items() if kind == "PAD" and str(p["num"]) == str(number)]
        assert len(matches) == 1
        pid, p = matches[0]
        shape = p["defaultPad"]
        assert shape["padType"] == "RECT" and not p["specialPad"] and p["hole"] is None
        x, y = p["centerX"]*MM, p["centerY"]*MM
        w, h, r = shape["width"]*MM, shape["height"]*MM, shape.get("radius", 0)*MM
        if r:
            local = box(x-w/2+r, y-h/2+r, x+w/2-r, y+h/2-r).buffer(r, resolution=64)
        else:
            local = box(x-w/2, y-h/2, x+w/2, y+h/2)
        angle = component["angle"]
        world = affinity.translate(affinity.rotate(local, angle, origin=(0, 0)), component["x"]*MM, component["y"]*MM)
        a = math.radians(angle)
        point = ((component["x"] + p["centerX"]*math.cos(a) - p["centerY"]*math.sin(a))*MM,
                 (component["y"] + p["centerX"]*math.sin(a) + p["centerY"]*math.cos(a))*MM)
        return point, world, pid

    for sma, rb, rin, series, cap, opa, pre, drv, adc in SPECS:
        old_net = f"NET-({rb}-PAD2)"
        old = {key: body for key, body in rows.items() if body.get("netName") == old_net}
        if Counter(k[0] for k in old) != Counter({"LINE": 2, "FILL": 1}):
            raise ValueError((old_net, Counter(k[0] for k in old)))
        assert all(b["layerId"] == 1 for b in old.values())
        old_lines = {k: b for k, b in old.items() if k[0] == "LINE"}
        fill_key = next(k for k in old if k[0] == "FILL")
        fill = fill_shape(old[fill_key])
        line_copper = unary_union([line_shape(b) for b in old_lines.values()])
        legacy_copper = unary_union([fill, line_copper])
        pin_positions = {}
        pin_shapes = {}
        for ref, pin in [(rin, "2"), (rb, "1"), (rb, "2"), (series, "1"), (series, "2")]:
            point, shape, pid = pad(ref, pin)
            key = ref + "." + pin
            pin_positions[key] = {"xyMmYUp": list(point), "masterPadPrimitiveId": pid}
            pin_shapes[key] = shape
        required_before = [rin+".2", rb+".1", series+".1"]
        if not all(legacy_copper.intersects(pin_shapes[p]) for p in required_before):
            raise ValueError((sma, "Old mixer copper does not join all expected three pins"))
        # Preserve the two original upstream LINE geometries. The rightmost
        # existing endpoint is inside the old mixer FILL and forms a stable
        # local PRE anchor for the new branch to Rb.pad1.
        endpoints = [(b["startX"]*MM, b["startY"]*MM) for b in old_lines.values()]
        endpoints += [(b["endX"]*MM, b["endY"]*MM) for b in old_lines.values()]
        anchor = max(endpoints)
        dest = tuple(pin_positions[rb+".1"]["xyMmYUp"])
        dx, dy = dest[0]-anchor[0], dest[1]-anchor[1]
        assert dx > 0 and dy > dx
        elbow = (dest[0], anchor[1]+dx)
        points = [anchor, elbow, dest]
        width = min(b["width"]*MM for b in old_lines.values())
        link_shape = LineString(points).buffer(width/2, resolution=32)
        new_copper = unary_union([line_copper, link_shape])
        # Proof is deliberately bounded: no newly proposed PRE copper extends
        # beyond the legacy mixer copper that is being removed/reused.
        outside_area = link_shape.difference(legacy_copper.buffer(1e-7)).area
        gap_to_series = new_copper.distance(pin_shapes[series+".1"])
        gap_to_bias = new_copper.distance(pin_shapes[rb+".2"])
        if outside_area > 1e-10 or gap_to_series < MIN_GAP or gap_to_bias < MIN_GAP:
            errors.append({"sma": sma, "outsideOldCopperAreaMm2": outside_area,
                           "gapToSeriesInputMm": gap_to_series, "gapToQuietBiasPadMm": gap_to_bias})
        assert new_copper.intersects(pin_shapes[rin+".2"]) and new_copper.intersects(pin_shapes[rb+".1"])
        assert not new_copper.intersects(pin_shapes[series+".1"])
        channel_ops = []
        for key, body in sorted(old_lines.items()):
            after_body = dict(body, netName=pre)
            op = {"action": "modify", "type": key[0], "id": key[1],
                  "allowedChangedFields": ["netName"], "beforeHeader": headers[key],
                  "beforeBodySha256": digest(body), "beforeBody": body, "afterBody": after_body,
                  "reason": "Retain exact Rin-to-local-mixer routing geometry, assign it to new PRE net"}
            operations.append(op); channel_ops.append({"type": key[0], "id": key[1], "action": "modify-net-only"})
        operations.append({"action": "delete", "type": "FILL", "id": fill_key[1],
                           "beforeHeader": headers[fill_key], "beforeBodySha256": digest(old[fill_key]),
                           "beforeBody": old[fill_key],
                           "reason": "Exclusive legacy local mixer copper shorts PRE to Rseries input; remove only this island for OPA insertion"})
        channel_ops.append({"type": "FILL", "id": fill_key[1], "action": "delete"})
        segment_proposals = []
        for index, (p, q) in enumerate(zip(points, points[1:])):
            segment_proposals.append({"proposalId": f"{sma}-pre-rb-link-{index+1}", "type": "LINE",
                "netName": pre, "layerId": 1, "widthMil": width/MM,
                "startX": p[0]/MM, "startY": p[1]/MM, "endX": q[0]/MM, "endY": q[1]/MM,
                "xyMmYUp": [list(p), list(q)],
                "state": "Geometry-reviewed local link proposal only; root must recheck current target pad positions before public API creation"})
        proposed.extend(segment_proposals)
        channels.append({"sma": sma, "biasResistor": rb, "inputResistor": rin, "seriesResistor": series,
            "adcCapacitor": cap, "buffer": opa, "oldMixerNet": old_net, "newPRE": pre, "newDRV": drv, "ADCpost": adc,
            "operations": channel_ops, "legacyMixerFillBoundsMmYUp": list(fill.bounds),
            "oldMixerCopperAreaMm2": legacy_copper.area, "pinPositions": pin_positions,
            "oldCuTouchesRin2Rb1Series1": True,
            "afterProposedLinkTouchesRin2Rb1": True, "afterProposedLinkTouchesSeries1": False,
            "newLinkOutsideLegacyCopperAreaMm2": outside_area,
            "newPREGapToSeriesInputCopperMm": gap_to_series,
            "newPREGapToQuietBiasPadCopperMm": gap_to_bias,
            "proposedLocalPRELinks": segment_proposals,
            "pendingConnections": [f"{pre} to {opa}.3 and prefilter-cap.1 after reviewed new placement",
                                   f"{opa}.1 and .4 on {drv} to {series}.1, without PRE/DRV copper bridge",
                                   f"{rb}.2 ADC_BIAS_2V5 after deleting its dedicated old main3V3 feed LINE"]})

    modified_keys = {(op["type"], op["id"]) for op in operations}
    protected = {key: body for key, body in rows.items() if key not in modified_keys and key[0] != "DOCHEAD"}
    adc_nets = {s[-1] for s in SPECS}
    post_copper = {key: body for key, body in rows.items() if body.get("netName") in adc_nets}
    report = {
        "schema": "stm32h747-adc10-bounded-pre-copper-isolation-plan-20261017-v1",
        "passedBoundedGeometryChecks": not errors, "errors": errors,
        "sourcePath": str(SOURCE), "sourceSha256": SOURCE_SHA,
        "units": "Native coordinates mil; explicitly named xyMmYUp and geometry metrics in millimeters",
        "state": "OFFLINE reviewed PARTIAL copper plan, not applied, not a full PCB candidate or completed routing",
        "summary": {"channels": 10, "deleteExclusiveMixerFILL": 10,
                    "netOnlyModifyRinLINE": 20, "proposedNewLocalPRELINE": len(proposed),
                    "ARCChanges": 0, "VIAChanges": 0, "PADChanges": 0,
                    "global3V3GeometryChanges": 0, "ADCpostCopperChanges": 0,
                    "MCUFanoutChanges": 0, "boardOutlineOrNPTHChanges": 0},
        "operationGuards": "Before any native edit root must match each primitive type/ID and exact beforeBodySha256 against latest source, because placement exports may have a newer DOCHEAD. Only netName may change in the twenty specified LINEs. Delete only the ten specified FILL islands, never global FILL/planes.",
        "operations": operations, "channels": channels,
        "post47ADCProtectedCopper": [{"type": key[0], "id": key[1], "bodySha256": digest(body)} for key, body in sorted(post_copper.items())],
        "post47ADCProtectedCopperCounts": dict(sorted(Counter(k[0] for k in post_copper).items())),
        "allOtherProtectedRecordCount": len(protected),
        "allOtherProtectedBodiesSha256": digest([[list(k), v] for k, v in sorted(protected.items())]),
        "geometryProof": "Each replacement short PRE branch is contained in the original exclusive mixer copper region (outside area <=1e-10mm²). It joins current Rin.2 and Rb.1, stays separated from Rseries.1 and quiet Rb.2 by more than0.1524mm. This is NOT a full other-net clearance audit, which still requires latest placed board native DRC.",
        "limitations": ["The plan deliberately breaks the old passive PRE-to-series bypass. OPA input/output and quiet-bias routing MUST be completed before powered use.",
                        "No new OPA coordinates assumed. Existing OPA parts are parked pending placement. Do not connect guessed OPA pads.",
                        "Child bias-feed manifest governs ten old +3V3 LINE deletions and the R164 via clearance issue separately.",
                        "Existing post47 long routes and MCU fanout are fully protected here. Old left-side capacitor stubs stay untouched; relocated ADC buckets need separately reviewed short final routes.",
                        "No source/native/API writes, no global plane repour, no fabrication approval."],
        "liveAPICalls": 0, "nativeFilesWritten": 0,
    }
    out = HERE / "adc10-pre-copper-isolation-plan-20261017.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n", encoding="utf8")
    print(json.dumps({"path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "passedBoundedGeometryChecks": not errors, "operations": len(operations),
        "minimumNewPREToSeriesCopperGapMm": min(c["newPREGapToSeriesInputCopperMm"] for c in channels),
        "minimumNewPREToQuietBiasCopperGapMm": min(c["newPREGapToQuietBiasPadCopperMm"] for c in channels),
        "errors": errors}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
