"""Read-only independent, geometric verification of ADC inline candidate.

NET attribute strings annotate physical islands but NEVER join them here.
Connections are built only where actual line endpoints touch other lines.
"""
import hashlib
import argparse
import json
import math
import runpy
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TOL = 1e-5


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    result = {}
    for raw in path.read_text(encoding="utf8").splitlines():
        if not raw.strip():
            continue
        h, b = raw.split("||", 1)
        h, b = json.loads(h), json.loads(b.rstrip("|"))
        key = h["type"], h.get("id")
        assert key not in result
        result[key] = b
    return result


def on_segment(p, a, b):
    cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
    return (abs(cross) <= TOL * max(1, math.dist(a, b))
            and min(a[0], b[0]) - TOL <= p[0] <= max(a[0], b[0]) + TOL
            and min(a[1], b[1]) - TOL <= p[1] <= max(a[1], b[1]) + TOL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actual-reopened", action="store_true")
    args = parser.parse_args()
    plan = json.loads((HERE / "adc-inline-schematic-plan.json").read_text(encoding="utf8"))
    candidate, base = Path(plan["candidatePath"]), Path(plan["baselinePath"])
    source = ROOT / "output/validation/native-adc-inline-reopened-20261016.epru" if args.actual_reopened else candidate
    assert sha(candidate) == plan["candidateSha256"] and sha(base) == plan["baselineSha256"]
    before, manifest_rows, rows = parse(base), parse(candidate), parse(source)
    errors, tests = [], []

    def check(condition, name, detail=None):
        tests.append({"test": name, "passed": bool(condition), "detail": detail})
        if not condition:
            errors.append(tests[-1])

    normalization_counts = Counter()
    normalization_changes = []
    check(rows.keys() == manifest_rows.keys(), "actual saved/reopened record membership exactly candidate")
    for key in rows.keys() & manifest_rows.keys():
        a, b = manifest_rows[key], rows[key]
        for field in a.keys() | b.keys():
            old, new = a.get(field), b.get(field)
            if old == new:
                continue
            rule = None
            if key[0] == "DOCHEAD" and field in {"client", "updateTime", "version"}:
                rule = "session header bookkeeping"
            elif key[0] == "ATTR" and field == "zIndex" and isinstance(old, (int, float)) and isinstance(new, (int, float)) and 0 <= old <= 60 and 0 <= new <= 60:
                rule = "native display-order renumber only"
            elif key[0] == "LINE" and field == "strokeWidth" and old == 0.6 and new is None and key not in before:
                rule = "new wire default stroke representation0.6 to null"
            elif key[0] == "POLY" and field == "points" and isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
                if [{f: v for f, v in p.items() if f != "hashed"} for p in old] == [{f: v for f, v in p.items() if f != "hashed"} for p in new]:
                    rule = "cached point hash recomputed; every coordinate exact"
            normalization_changes.append({"record": key, "field": field, "rule": rule})
            check(rule is not None, "native normalization only " + str(key) + "." + field,
                  {"allowedRule": rule})
            if rule:
                normalization_counts[rule] += 1

    added = {(d["h"]["type"], d["h"].get("id")) for d in plan["added"]}
    deleted = {(d["h"]["type"], d["h"].get("id")) for d in plan["deleted"]}
    changed = {(d["type"], d["id"]) for d in plan["changes"]}
    check(manifest_rows.keys() - before.keys() == added, "added record keys exactly manifest")
    check(before.keys() - manifest_rows.keys() == deleted, "deleted record keys exactly manifest")
    check({k for k in manifest_rows.keys() & before.keys() if manifest_rows[k] != before[k]} == changed,
          "changed record keys exactly manifest")
    for d in plan["changes"]:
        key = d["type"], d["id"]
        check(before[key] == d["before"] and manifest_rows[key] == d["after"], "manifest exact body " + str(key))
    for d in plan["added"]:
        check(manifest_rows[(d["h"]["type"], d["h"].get("id"))] == d["b"], "added body " + d["h"].get("id", ""))
    for d in plan["deleted"]:
        check(before[(d["h"]["type"], d["h"].get("id"))] == d["b"], "deleted body " + d["h"].get("id", ""))
    dnp = json.loads((HERE / "independent-dnp-deletion-audit.json").read_text(encoding="utf8"))
    dnp_keys = {tuple(k) for c in dnp["channels"] for k in c["deleteRecordKeys"]}
    check(dnp_keys <= deleted, "all84 DNP ownership records deleted")
    check(not (dnp_keys & rows.keys()), "all84 DNP ownership records absent from actual source")
    deleted_ids = {rid for kind, rid in dnp_keys}
    check(not [rid for (kind, rid), b in rows.items() if kind == "ATTR" and b.get("parentId") in deleted_ids],
          "no DNP/ground/stub-owned orphan attributes remain")
    check(all(("WIRE", b["lineGroup"]) in rows for (kind, rid), b in rows.items() if kind == "LINE"),
          "every actual LINE belongs to an existing WIRE")

    attrs, old_attrs = defaultdict(dict), defaultdict(dict)
    for dataset, target in ((rows, attrs), (before, old_attrs)):
        for (kind, rid), body in dataset.items():
            if kind == "ATTR":
                target[body.get("parentId")][body.get("key")] = body.get("value")
    refs = {a["Designator"]: rid for rid, a in attrs.items() if a.get("Designator")}
    check(all(ref not in refs for ref in ("R146", "R147", "R148")), "three DNP references absent")
    for (kind, rid), body in rows.items():
        if kind == "COMPONENT":
            check((kind, rid) in before, "no new component " + rid)
            check(attrs[rid] == old_attrs[rid], "all remaining component semantic attrs unchanged " + rid)
            check({k: v for k, v in body.items() if k not in {"x", "y", "rotation"}}
                  == {k: v for k, v in before[(kind, rid)].items() if k not in {"x", "y", "rotation"}},
                  "component instance binding/body invariant " + rid)
    # Protect the CURRENT reference block, including the user's pre-existing
    # U9/C98 layout edits captured in the fresh baseline rather than older save.
    reference_keys = set()
    reference_wire_ids = set()
    for (kind, rid), b in before.items():
        xy = []
        if b.get("x") is not None and b.get("y") is not None:
            xy.append((b["x"], b["y"]))
        if kind == "LINE":
            xy.extend(((b["startX"], b["startY"]), (b["endX"], b["endY"])))
        if kind == "POLY":
            xy.extend((p["x"], p["y"]) for p in b.get("points", []))
        if xy and all(980 <= x <= 1450 and 710 <= y <= 865 for x, y in xy):
            reference_keys.add((kind, rid))
            if kind == "LINE":
                reference_wire_ids.add(b["lineGroup"])
        if kind == "COMPONENT" and old_attrs[rid].get("Designator") in {"U9", "C103", "C104", "C105"}:
            reference_keys.add((kind, rid))
    reference_parent_ids = {rid for kind, rid in reference_keys if kind == "COMPONENT"} | reference_wire_ids
    reference_keys.update(("WIRE", rid) for rid in reference_wire_ids)
    reference_keys.update(k for k, b in before.items() if k[0] == "ATTR" and b.get("parentId") in reference_parent_ids)
    check(all(k in rows and rows[k] == before[k] for k in reference_keys),
          "fresh-baseline moved REF3325/current reference block bodies exactly protected",
          {"recordCount": len(reference_keys), "componentRefs": ["U9", "C103", "C104", "C105"],
           "sourceU9Position": [before[("COMPONENT", refs["U9"])]["x"], before[("COMPONENT", refs["U9"])]["y"]]})
    check(not [b for (k, rid), b in rows.items() if k == "TEXT" and str(b.get("value", "")).startswith(("ADC1_PRE", "ADC1_DRV"))],
          "no visible detached PRE/DRV text")

    # Actual physical wire islands. Endpoint-on-segment joins ordinary straight
    # and T-junction paths even if different WIRE IDs, but equal names never join.
    segments = []
    for (kind, rid), body in rows.items():
        if kind == "LINE":
            net = attrs[body.get("lineGroup")].get("NET")
            if net is not None:
                segments.append({"id": rid, "wire": body["lineGroup"], "net": net,
                                 "a": (body["startX"], body["startY"]),
                                 "b": (body["endX"], body["endY"])})
    parent = list(range(len(segments)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(j)] = find(i)

    for i, a in enumerate(segments):
        for j in range(i):
            b = segments[j]
            if any(on_segment(p, b["a"], b["b"]) for p in (a["a"], a["b"])) or any(on_segment(p, a["a"], a["b"]) for p in (b["a"], b["b"])):
                union(i, j)
    islands = defaultdict(list)
    for i, s in enumerate(segments):
        islands[find(i)].append(s)
    island_nets = {i: set(s["net"] for s in segs) for i, segs in islands.items()}
    check(all(len(nets) == 1 for nets in island_nets.values()), "no endpoint-connected mixed-net wire island",
          [{"island": i, "nets": sorted(n)} for i, n in island_nets.items() if len(n) != 1])

    checkpoint = ROOT / "output/checkpoints/STM32H747_adc_dc_corners_j18_direction_v2_20261016.epro2"
    libraries = runpy.run_path(str(ROOT / "scripts/build-adc-dc-libraries.py"))["read_checkpoint"](checkpoint)
    expected = {(p["ref"], p["number"]): p["net"] for p in dnp["expectedNetlistContract"]["expectedPins"]}
    pin_data = {}
    page_pin_contract = []
    for (kind, rid), body in rows.items():
        if kind != "COMPONENT" or attrs[rid].get("Designator") not in {r for r, n in expected}:
            continue
        ref = attrs[rid]["Designator"]
        symbol = libraries[("SYMBOL", attrs[rid]["Symbol"])]
        symbol_attrs = defaultdict(dict)
        for h, b in symbol.values():
            if h["type"] == "ATTR":
                symbol_attrs[b.get("parentId")][b.get("key")] = b.get("value")
        t = math.radians(body["rotation"])
        for h, b in symbol.values():
            if h["type"] != "PIN" or b.get("partId", body["partId"]) != body["partId"]:
                continue
            number = symbol_attrs[h["id"]].get("Pin Number")
            key = ref, number
            if key not in expected:
                continue
            x, y = (-b["x"] if body.get("isMirror") else b["x"]), b["y"]
            point = (round(body["x"] + x * math.cos(t) + y * math.sin(t), 6),
                     round(body["y"] - x * math.sin(t) + y * math.cos(t), 6))
            touching = sorted({find(i) for i, s in enumerate(segments) if on_segment(point, s["a"], s["b"])})
            actual = sorted({n for i in touching for n in island_nets[i]})
            check(len(touching) == 1 and actual == [expected[key]], "physical pin net " + ref + "." + number,
                  {"point": point, "expected": expected[key], "actual": actual, "islands": touching})
            pin_data[key] = {"point": point, "islands": touching, "net": actual, "pinName": symbol_attrs[h["id"]].get("Pin Name")}
            page_pin_contract.append({"ref": ref, "number": number, **pin_data[key]})

    channel_reports = []
    for i, net in enumerate(("ADC1_INP0", "ADC1_INP1", "ADC1_INP16")):
        n = i + 1
        j, rb, ri, rs, u, pre_c, adc_c, dec_c = f"J{2+i}", f"R{137+i}", f"R{140+2*i}", f"R{141+2*i}", f"U{10+i}", f"C{97+i}", f"C{80+i}", f"C{100+i}"
        groups = {
            "raw": [(j, "1"), (ri, "1")],
            "pre": [(ri, "2"), (rb, "1"), (u, "3"), (pre_c, "1")],
            "driver": [(u, "1"), (u, "4"), (rs, "1")],
            "adc": [(rs, "2"), (adc_c, "1"), (f"TP{1+i}", "1")],
            "vplus": [(u, "5"), (dec_c, "1")],
        }
        group_islands = {}
        for name, pins_in_group in groups.items():
            roots = {root for p in pins_in_group for root in pin_data[p]["islands"]}
            check(len(roots) == 1, f"channel{n} {name} pins one REAL wire island", {"pins": pins_in_group, "islands": sorted(roots)})
            group_islands[name] = sorted(roots)
        signal_roots = [group_islands[g][0] for g in ("raw", "pre", "driver", "adc")]
        check(len(set(signal_roots)) == 4, f"channel{n} raw/pre/driver/ADC isolated by intended components")
        check("GND" not in island_nets[group_islands["driver"][0]], f"channel{n} OUT and IN- not grounded")
        for p in ((u, "2"), (pre_c, "2"), (adc_c, "2"), (dec_c, "2"), (j, "2")):
            check(pin_data[p]["net"] == ["GND"], f"channel{n} expected ground pin {p}")
        for internal in (f"ADC1_PRE{n}", f"ADC1_DRV{n}"):
            ids = [root for root, names in island_nets.items() if internal in names]
            check(len(ids) == 1, internal + " has exactly ONE physical island, no label bridge", ids)
        port_point = plan["layout"][i]["adcPort"]
        at_port = {find(jj) for jj, s in enumerate(segments) if on_segment(port_point, s["a"], s["b"])}
        check(at_port == set(group_islands["adc"]), f"channel{n} real wire reaches ADC port anchor", port_point)
        port_outlines = [rid for (kind, rid), b in rows.items() if kind == "POLY" and b.get("strokeColor") == "#840000"
                         and len(b.get("points", [])) == 7 and any(math.dist(port_point, (p["x"], p["y"])) < TOL for p in b["points"])]
        check(len(port_outlines) == 1, f"channel{n} ADC port visual anchor touches real wire", port_outlines)
        channel_reports.append({"channel": n, "nets": {g: sorted(island_nets[v[0]]) for g, v in group_islands.items()},
                                "realWireIslands": {g: [s["id"] for s in islands[v[0]]] for g, v in group_islands.items()},
                                "portAnchor": port_point, "portOutlineId": port_outlines})
    physical_refs = {attrs[rid]["Designator"] for (kind, rid), body in rows.items()
                     if kind == "COMPONENT" and attrs[rid].get("Convert to PCB") == "yes"}
    old_physical_refs = {old_attrs[rid]["Designator"] for (kind, rid), body in before.items()
                         if kind == "COMPONENT" and old_attrs[rid].get("Convert to PCB") == "yes"}
    check(old_physical_refs - physical_refs == {"R146", "R147", "R148"} and not physical_refs - old_physical_refs,
          "physical page component membership only deletes3 DNP resistors")
    native_netlist_audit = None
    if args.actual_reopened:
        net_parse = runpy.run_path(str(ROOT / "scripts/verify-native-netlist.py"))["parse_protel2"]
        before_net = ROOT / "output/validation/native-adc-inline-before-Protel2-20261016.net"
        after_net = ROOT / "output/validation/native-adc-inline-after-Protel2-20261016.net"
        nodes, blocks = [], []
        import re
        for net_path in (before_net, after_net):
            raw = net_path.read_text(encoding="utf8").replace("\r\n", "\n")
            pp = net_parse(raw)
            nn = {(p["ref"], p["number"]): p["net"] for p in pp}
            check(len(pp) == len(nn), "unique native netlist pins " + net_path.name)
            nodes.append(nn)
            blocks.append({b.splitlines()[1]: b for b in re.findall(r"(?ms)^\[\n(.*?)^\]", raw)})
        n_before, n_after = nodes
        b_before, b_after = blocks
        removed = sorted(n_before.keys() - n_after.keys())
        added_pins = sorted(n_after.keys() - n_before.keys())
        changed_pins = [{"pin": k, "before": n_before[k], "after": n_after[k]}
                        for k in sorted(n_before.keys() & n_after.keys()) if n_before[k] != n_after[k]]
        expected_removed = sorted((ref, number) for ref in ("R146", "R147", "R148") for number in ("1", "2"))
        check(len(n_before) == 1093 and len(n_after) == 1087, "native full-project pins1093 to1087")
        check(removed == expected_removed and not added_pins and not changed_pins,
              "exactly6 DNP pins removed; all1087 remaining native pin-net identities unchanged",
              {"removed": removed, "added": added_pins, "changed": changed_pins})
        check(len(b_before) == 343 and len(b_after) == 340, "native physical component blocks343 to340")
        check(b_before.keys() - b_after.keys() == {"R146", "R147", "R148"} and not b_after.keys() - b_before.keys(),
              "native component membership only three DNP removals")
        changed_blocks = sorted(ref for ref in b_before.keys() & b_after.keys() if b_before[ref] != b_after[ref])
        check(not changed_blocks, "all340 remaining component blocks byte-identical", changed_blocks)
        erc_path = ROOT / "output/validation/native-adc-inline-after-erc-20261016.json"
        erc_passed = json.loads(erc_path.read_text(encoding="utf8")).get("passed") is True
        check(erc_passed, "actual after native ERC passed=true")
        native_netlist_audit = {"beforePath": str(before_net), "beforeSha256": sha(before_net),
                               "afterPath": str(after_net), "afterSha256": sha(after_net),
                               "beforePins": len(n_before), "afterPins": len(n_after),
                               "removedPinsExactly6Dnp": removed, "newPins": added_pins, "changedRemainingPins": changed_pins,
                               "beforeComponentBlocks": len(b_before), "afterComponentBlocks": len(b_after),
                               "changedRemainingComponentBlocks": changed_blocks,
                               "nativeErcPath": str(erc_path), "nativeErcPassed": erc_passed}
    report = {"schema": "adc-inline-independent-physical-wire-audit-20261016-v1", "passed": not errors,
              "sourcePath": str(source), "sourceSha256": sha(source), "baselinePath": str(base), "baselineSha256": sha(base),
              "nativeReopenedSource": args.actual_reopened,
              "candidateSha256": sha(candidate), "nativeNormalizationCounts": dict(normalization_counts),
              "nativeNormalizationChanges": normalization_changes,
              "recordCounts": {"before": len(before), "after": len(rows), "changed": len(changed), "deleted": len(deleted), "added": len(added)},
              "nonTargetRecordsExactInCandidate": len(before) - len(changed) - len(deleted),
              "nonTargetRecordsLiteralExactInActualSource": sum(k in rows and rows[k] == b for k, b in before.items() if k not in changed | deleted),
              "physicalWireMethod": "Literal LINE endpoint-on-segment connectivity only; equal NET strings DO NOT join separate geometry. Interior-only crossings without endpoints not electrically joined.",
              "physicalWireIslandCount": len(islands), "pageConnectedPinsIndependentlyChecked": len(page_pin_contract),
              "remainingPagePinContract": page_pin_contract, "channels": channel_reports,
              "deletionOnlyExpectedFullNetlistPins": 1087, "deletionOnlyExpectedPhysicalParts": 340,
              "allRemainingComponentSemanticsUnchanged": not [t for t in tests if t["test"].startswith("all remaining component semantic") and not t["passed"]],
              "protectedCurrentReferenceBlockRecordsExact": len(reference_keys),
              "gain": 0.5, "offsetV": 1.25, "dcBlockingCapsAdded": 0,
              "floatingInputRedesignApplied": False, "floatingInputExpectedBehaviorUnchanged": True,
              "nativeNetlistAudit": native_netlist_audit,
              "nativeErcAndFreshNetlistStillRequired": not args.actual_reopened, "pcbMutated": False,
              "checks": tests, "errors": errors}
    out = HERE / ("independent-inline-native-final-audit-20261016.json" if args.actual_reopened else "independent-inline-wire-graph-audit.json")
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"passed": report["passed"], "path": str(out), "sha256": sha(out),
                      "sourceSha256": sha(source), "recordCounts": report["recordCounts"],
                      "pagePinsChecked": len(page_pin_contract), "channels": channel_reports, "errors": errors}, indent=2))
    if errors:
        raise ValueError("Independent inline geometry review failed")


if __name__ == "__main__":
    main()
