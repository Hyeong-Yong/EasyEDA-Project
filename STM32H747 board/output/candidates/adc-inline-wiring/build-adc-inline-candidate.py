"""Offline existing-topology inline ADC1 redraw; no EasyEDA/API calls."""
from __future__ import annotations
import copy
import hashlib
import json
import runpy
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = HERE.parent / "adc-dc-buffer"
BASE = ROOT / "output/validation/native-adc-inline-before-20261016.epru"
UTIL = runpy.run_path(str(ROOT / "scripts/build-adc-dc-schematic-patch.py"))
UID = lambda key: hashlib.sha256(("stm32h747-adc-inline-20261016/" + key).encode()).hexdigest()[:16]


def main():
    original = UTIL["parse"](BASE.read_text(encoding="utf8"))
    rows = copy.deepcopy(original)
    lookup = {(r["h"]["type"], r["h"].get("id")): r for r in rows}
    ids = {k[1]: r for k, r in lookup.items() if k[1]}
    attrs = defaultdict(dict)
    refs = {}
    for r in rows:
        if r["h"]["type"] == "ATTR":
            attrs[r["b"]["parentId"]][r["b"]["key"]] = r
            if r["b"]["key"] == "Designator":
                refs[r["b"]["value"]] = r["b"]["parentId"]
    ticket = max(r["h"].get("ticket", 0) for r in rows)
    removed = set()
    dnp = json.loads((HERE / "independent-dnp-deletion-audit.json").read_text(encoding="utf8"))
    dnp_before = {(r["h"]["type"], r["h"].get("id")): r["b"] for r in UTIL["parse"](Path(dnp["sourcePath"]).read_text(encoding="utf8"))}
    for ch in dnp["channels"]:
        for key in ch["deleteRecordKeys"]:
            key = tuple(key)
            assert lookup[key]["b"] == dnp_before[key], ("DNP fresh baseline mismatch", key)
            removed.add(key)
    assert len(removed) == 84

    def add(kind, body, name):
        nonlocal ticket
        rid = UID(name)
        assert rid not in ids
        ticket += 1
        r = {"h": {"type": kind, "id": rid, "ticket": ticket}, "b": body}
        rows.append(r)
        lookup[kind, rid] = r
        ids[rid] = r
        return rid

    def remove_record(r):
        removed.add((r["h"]["type"], r["h"].get("id")))

    def remove_wire(wid):
        assert ("WIRE", wid) in lookup
        for r in rows:
            if r["h"].get("id") == wid or r["b"].get("parentId") == wid or r["b"].get("lineGroup") == wid:
                remove_record(r)

    def set_wire(wid, segments, label_position):
        # Reuse native WIRE/NET IDs, but replace all its geometric segments.
        assert ("WIRE", wid) in lookup
        for r in rows:
            if r["h"]["type"] == "LINE" and r["b"].get("lineGroup") == wid:
                remove_record(r)
        for n, (a, b) in enumerate(segments):
            assert a != b
            add("LINE", {"startX": a[0], "startY": a[1], "endX": b[0], "endY": b[1], "lineGroup": wid,
                "strokeColor": "#009600", "strokeStyle": "SOLID", "strokeWidth": 0.6, "fillColor": None, "fillStyle": None}, f"{wid}/inline/line/{n}")
        netattr = attrs[wid]["NET"]["b"]
        netattr.update(x=label_position[0], y=label_position[1], fontSize=0.001, valueVisible=True)

    def segments(points):
        return list(zip(points, points[1:]))

    def translate(r, dx, dy):
        b = r["b"]
        for f in ("x", "startX", "endX"):
            if b.get(f) is not None:
                b[f] += dx
        for f in ("y", "startY", "endY"):
            if b.get(f) is not None:
                b[f] += dy
        for p in b.get("points", []):
            p["x"] += dx
            p["y"] += dy

    def move_component(ref, x, y, labels=None):
        cid = refs[ref]
        r = ids[cid]
        dx, dy = x - r["b"]["x"], y - r["b"]["y"]
        translate(r, dx, dy)
        for child in attrs[cid].values():
            translate(child, dx, dy)
        if labels:
            for key, (lx, ly) in labels.items():
                attrs[cid][key]["b"].update(x=lx, y=ly)
        return cid

    def text_move(value, old_near, x, y):
        found = [r for r in rows if r["h"]["type"] == "TEXT" and r["b"].get("value") == value and abs(r["b"]["x"]-old_near[0]) < .01 and abs(r["b"]["y"]-old_near[1]) < .01]
        assert len(found) == 1, (value, old_near, len(found))
        found[0]["b"].update(x=x, y=y)

    def generated_text_move(value, name, x, y):
        r = ids[UTIL["uid"](name)]
        assert r["h"]["type"] == "TEXT" and r["b"]["value"] == value
        r["b"].update(x=x, y=y)

    # Remove only the two visible PRE/DRV text labels per old/top and lower buffer.
    for r in rows:
        if r["h"]["type"] == "TEXT" and r["b"].get("value", "").startswith(("ADC1_PRE", "ADC1_DRV")):
            remove_record(r)
    original_plan = json.loads((PREVIOUS / "adc-dc-schematic-plan.json").read_text(encoding="utf8"))
    old_uid = UTIL["uid"]
    layout = []
    for i, offset in enumerate((0, 335, 665)):
        ch = i + 1
        old_mix, old_cap = 345+offset, 425+offset
        x = lambda local: local + offset
        move_component(f"R{137+i}", x(280), 150, {"Designator": (x(288),145), "Value": (x(288),152)})
        move_component(f"R{140+2*i}", x(255), 190, {"Designator": (x(243),177), "Value": (x(243),184)})
        move_component(f"R{141+2*i}", x(420), 200, {"Designator": (x(412),180), "Value": (x(412),187)})
        move_component(f"C{80+i}", x(455), 230, {"Designator": (x(470),227), "Value": (x(470),234)})
        move_component(f"U{10+i}", x(345), 200, {"Designator": (x(350),141), "Value": (x(350),148)})
        move_component(f"C{97+i}", x(280), 235, {"Designator": (x(244),233), "Value": (x(244),240)})
        move_component(f"C{100+i}", x(440), 145, {"Designator": (x(452),142), "Value": (x(452),149)})
        tp = ids[refs[f"TP{ch}"]]["b"]
        move_component(f"TP{ch}", tp["x"]+30, tp["y"]+10)
        move_component(f"#PWR{102+3*i:04d}", x(455), 255)

        mix = ["9cbcdfde5f635eb8", "6310f649efc85c6b", "30b085aeb466535e"][i]
        bias = ["7ddd73c0b38755f1", "d6843d6273b35f38", "f6a06b7190d45f7e"][i]
        adc = ["5c4de7a10ad053ca", "89307564115e53e3", "44186a4f52345d92"][i]
        raw = ["d19f603d9ea658ba", "3d77b22a0e9152df", "4fa527c83b015f01"][i]
        capgnd = ["9d2cb9ba25d5556d", "25ea92c5700855aa", "0b4c2f7a5834580b"][i]
        drv = old_uid(f"buffer-out/{ch}")
        set_wire(raw, [((x(235),190),(x(240),190))], (x(235),190))
        set_wire(mix, [((x(270),190),(x(280),190)), ((x(280),190),(x(305),190)), ((x(280),165),(x(280),190)), ((x(280),190),(x(280),225))], (x(280),190))
        set_wire(bias, [((x(280),135),(x(280),115))], (x(280),115))
        set_wire(drv, segments([(x(390),200),(x(400),200),(x(405),200)]) + segments([(x(400),200),(x(400),265),(x(295),265),(x(295),210),(x(305),210)]), (x(390),200))
        set_wire(adc, [((x(435),200),(x(455),200)), ((x(455),200),(x(500),200)), ((x(455),185),(x(455),200)), ((x(455),200),(x(455),220))], (x(500),200))
        set_wire(capgnd, [((x(455),240),(x(455),250))], (x(455),245))
        set_wire(old_uid(f"buffer-input-gnd/{ch}"), [((x(280),245),(x(280),255))], (x(280),255))
        set_wire(old_uid(f"buffer-power/{ch}"), segments([(x(345),165),(x(345),130),(x(440),130),(x(440),135)]), (x(345),130))
        set_wire(old_uid(f"buffer-gnd/{ch}"), [((x(345),235),(x(345),240))], (x(345),240))
        set_wire(old_uid(f"buffer-decouple-gnd/{ch}"), [((x(440),155),(x(440),165))], (x(440),165))
        for obsolete in ("driver-to-series", "buffer-input", "buffer-feedback"):
            remove_wire(old_uid(f"{obsolete}/{ch}"))

        generated_text_move("ADC_BIAS_2V5", f"bias-label/{ch}", x(252),105)
        generated_text_move("C0G", f"c0g-label/{ch}", x(470),245)
        yold = (880,970,1060)[i]
        generated_text_move("GND", f"buffer-input-gnd/{ch}/label", x(267),268)
        generated_text_move("+3V3", f"buffer-power/{ch}/label", x(335),120)
        generated_text_move("GND", f"buffer-gnd/{ch}/label", x(332),253)
        generated_text_move("GND", f"buffer-decouple-gnd/{ch}/label", x(422),168)

        # The port arrows, MCU-pin annotations, and original junction dots are
        # real root POLYs from the source PDF; translate their exact vectors.
        old_port = (480,810,1140)[i]
        for r in rows:
            if r["h"]["type"] != "POLY" or not r["b"].get("points"):
                continue
            b, pts = r["b"], r["b"]["points"]
            if all(old_port-0.01 <= p["x"] <= old_port+44 and 185 <= p["y"] <= 194 for p in pts) and b.get("fillColor") in (None,"#840000"):
                translate(r, x(500)-old_port, 10)
            elif b.get("fillColor") == "#0000FF" and all(old_cap+5 <= p["x"] <= old_cap+45 and 181 <= p["y"] <= 192 for p in pts):
                translate(r, 30, 10)
            elif b.get("fillColor") == "#009600" and all(abs(p["x"]-old_mix)<2 and abs(p["y"]-190)<2 for p in pts):
                translate(r, x(280)-old_mix, 0)
            elif b.get("fillColor") == "#009600" and all(abs(p["x"]-old_cap)<2 and abs(p["y"]-190)<2 for p in pts):
                translate(r, 30, 10)
        dot = copy.deepcopy(lookup["POLY", "430d4377cb89570b"]["b"])
        # The template has already moved to channel 1's ADC node (455,200).
        dot["points"] = [{"x": p["x"]+x(400)-455, "y":p["y"]} for p in dot["points"]]
        add("POLY", dot, f"feedback-dot/{ch}")
        layout.append({"channel": ch, "columnOffset": offset, "smaSignal": [x(235),190], "inputResistor": [x(255),190], "biasResistor": [x(280),150], "mixNode": [x(280),190], "preFilter": [x(280),235], "buffer": [x(345),200], "seriesResistor": [x(420),200], "adcFilter": [x(455),230], "adcPort": [x(500),200], "feedbackLoop": [[x(400),200],[x(400),265],[x(295),265],[x(295),210],[x(305),210]]})

    generated_text_move("VADC = 0.25 V ... 2.25 V", "adc-range", 455,155)
    rows = [r for r in rows if (r["h"]["type"],r["h"].get("id")) not in removed]
    final = {(r["h"]["type"],r["h"].get("id")): r for r in rows}
    old = {(r["h"]["type"],r["h"].get("id")): r for r in original}
    assert len(final) == len(rows)
    changes = [{"type":k[0],"id":k[1],"before":old[k]["b"],"after":final[k]["b"]} for k in old.keys() & final.keys() if old[k]["b"] != final[k]["b"]]
    deleted = [old[k] for k in old.keys()-final.keys()]
    added = [final[k] for k in final.keys()-old.keys()]
    serialized = "".join(json.dumps(r["h"],separators=(",",":"))+"||"+json.dumps(r["b"],separators=(",",":"))+"|\n" for r in rows)
    candidate = HERE / "06_ADC_TIMER_DAC_inline_candidate.epru"
    candidate.write_text(serialized,encoding="utf8",newline="\n")
    plan = {"schema":"adc1-existing-topology-inline-wiring-20261016-v1","pageUuid":"a07bf8e4331877a8","baselinePath":str(BASE),"baselineSha256":hashlib.sha256(BASE.read_bytes()).hexdigest(),"candidatePath":str(candidate),"candidateSha256":hashlib.sha256(candidate.read_bytes()).hexdigest(),"changes":changes,"deleted":deleted,"added":added,"layout":layout,"deletedDnpRefs":["R146","R147","R148"],"dnpOwnershipManifest":str(HERE/"independent-dnp-deletion-audit.json"),"allExistingLibrariesUnchanged":True,"electricalContract":{"preserveAllRemainingComponentPinNets":True,"preserveAllPartValuesAndUuids":True,"gain":0.5,"offsetV":1.25,"dcCoupled":True,"floatingInputBehaviorUnchanged":True,"floatingZeroRedesignPendingUserChoice":True,"firmwareUnchanged":True,"pcbUnchanged":True},"notes":["No new pulldown, negative rail, or front-end topology change.","PRE/DRV NET names retained as hidden metadata; all three paths use real continuous wires rather than detached same-name labels.","R146-R148 symbol-internal PDF glyphs/NC crosses disappear with component deletion; shared library bodies preserved.","REF3325 and its full source block remain byte-identical."]}
    (HERE/"adc-inline-schematic-plan.json").write_text(json.dumps(plan,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"candidatePath":str(candidate),"sha256":plan["candidateSha256"],"changed":len(changes),"deleted":len(deleted),"added":len(added),"changedTypes":dict(Counter(x["type"] for x in changes)),"deletedTypes":dict(Counter(x["h"]["type"] for x in deleted))},indent=2))


if __name__ == "__main__":
    main()
