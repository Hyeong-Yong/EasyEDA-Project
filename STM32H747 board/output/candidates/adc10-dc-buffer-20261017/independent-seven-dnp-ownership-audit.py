"""Read-only exact ownership manifest for seven approved DNP removals."""

import hashlib
import json
import re
import runpy
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT / "output/validation/native-adc10-sch-before-20261017.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_adc10_20261017.epro2"
PREVIOUS = ROOT / "output/validation/native-adc-inline-reopened-20261016.epru"
EXPECTED_SHA = "885b9eaa95591d23a652d521fa0c785f63d5eb836f148ad16f58402825c9cd45"
REFS = ["R158", "R159", "R160", "R173", "R174", "R175", "R176"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def parse(path):
    result = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        header, body = line.split("||", 1)
        header, body = json.loads(header), json.loads(body.rstrip("|"))
        key = header["type"], header.get("id")
        assert key not in result, key
        result[key] = (header, body)
    return result


def bbox(points):
    return [min(x for x, y in points), min(y for x, y in points), max(x for x, y in points), max(y for x, y in points)] if points else None


def full_record(key, rows):
    h, b = rows[key]
    return {"key": list(key), "header": h, "body": b, "bodySha256": canonical_sha(b)}


def main():
    assert sha(SOURCE) == EXPECTED_SHA
    rows = parse(SOURCE)
    assert rows[("DOCHEAD", None)][1]["uuid"] == "a07bf8e4331877a8"
    attrs, children = defaultdict(dict), defaultdict(list)
    for key, (h, b) in rows.items():
        if key[0] == "ATTR":
            attrs[b.get("parentId")][b.get("key")] = b.get("value")
            children[b.get("parentId")].append(key)
    refs = {a["Designator"]: cid for cid, a in attrs.items() if "Designator" in a}
    wanted = {attrs[refs[ref]]["Symbol"] for ref in REFS}
    libraries = {}
    current = None
    with zipfile.ZipFile(CHECKPOINT) as archive:
        member = next(n for n in archive.namelist() if n.endswith(".epru"))
        for raw in archive.read(member).decode("utf-8-sig").splitlines():
            if not raw.strip():
                continue
            hh, bb = raw.split("||", 1)
            hh = json.loads(hh)
            payload = bb.removesuffix("|")
            if hh["type"] == "DOCHEAD":
                head = json.loads(payload)
                current = ("SYMBOL", head.get("uuid")) if head.get("docType") == "SYMBOL" and head.get("uuid") in wanted else None
                if current:
                    libraries[current] = {}
            if current:
                k = (hh["type"], hh.get("id"))
                if not payload or payload == '""':
                    libraries[current].pop(k, None)
                else:
                    libraries[current][k] = (hh, json.loads(payload))
    assert len(libraries) == 7
    delete, channels = set(), []
    for ref in REFS:
        cid = refs[ref]
        component = rows[("COMPONENT", cid)][1]
        properties = attrs[cid]
        assert properties["Value"] == "30k_NC" and properties["DNP"] == "yes"
        assert properties["Add into BOM"] == "no" and properties["Convert to PCB"] == "yes"
        assert component["rotation"] == 0 and component["isMirror"] is False
        symbol = libraries[("SYMBOL", properties["Symbol"])]
        sa = defaultdict(dict)
        for h, b in symbol.values():
            if h["type"] == "ATTR":
                sa[b.get("parentId")][b.get("key")] = b.get("value")
        pins, polys = {}, []
        for h, b in symbol.values():
            if h["type"] == "PIN":
                num = sa[h["id"]].get("Pin Number", sa[h["id"]].get("NUMBER"))
                pins[num] = [round(component["x"] + b["x"], 7), round(component["y"] + b["y"], 7)]
            elif h["type"] == "POLY":
                pts = [(p["x"], p["y"]) for p in b.get("points", [])]
                polys.append({"id": h["id"], "boundsLocal": bbox(pts), "strokeColor": b.get("strokeColor"),
                              "fillColor": b.get("fillColor"), "strokeWidth": b.get("strokeWidth"), "pointCount": len(pts)})
        assert set(pins) == {"1", "2"}
        x, top_y = pins["1"]
        bx, bottom_y = pins["2"]
        assert abs(x - bx) < 1e-6 and abs(bottom_y - top_y - 30) < 1e-6
        def line_at(target):
            matches = [(k, b) for k, (_, b) in rows.items() if k[0] == "LINE" and
                       all(abs(v - w) < 1e-6 for v, w in zip([b["startX"], b["startY"], b["endX"], b["endY"]], target))]
            assert len(matches) == 1, (ref, target, matches)
            return matches[0]
        tk, tb = line_at([x, top_y - 5, x, top_y])
        bk, bb = line_at([x, bottom_y, x, bottom_y + 5])
        tw, bw = tb["lineGroup"], bb["lineGroup"]
        bline_keys = [k for k, (_, b) in rows.items() if b.get("lineGroup") == bw]
        assert bline_keys == [bk]
        top_sibling_keys = [k for k, (_, b) in rows.items() if b.get("lineGroup") == tw and k != tk]
        assert top_sibling_keys
        assert attrs[bw]["NET"] == "GND"
        grounds = [(k, b) for k, (_, b) in rows.items() if k[0] == "COMPONENT" and attrs[k[1]].get("Global Net Name") == "GND"
                   and abs(b["x"] - x) < 1e-6 and abs(b["y"] - bottom_y - 10) < 1e-6]
        assert len(grounds) == 1, (ref, grounds)
        gk, gb = grounds[0]
        keys = {("COMPONENT", cid), tk, bk, ("WIRE", bw), gk, *children[cid], *children[bw], *children[gk[1]]}
        assert not delete.intersection(keys), "Overlapping deletion ownership"
        delete.update(keys)
        assert ("WIRE", tw) not in keys
        assert all(k not in keys for k in top_sibling_keys)
        all_symbol_pts = [(component["x"] + p["x"], component["y"] + p["y"]) for h, b in symbol.values() if h["type"] == "POLY" for p in b["points"]]
        page_bbox = bbox(all_symbol_pts)
        nearby = []
        for key, (_, b) in rows.items():
            if key[0] != "POLY" or not b.get("points"):
                continue
            pb = bbox([(p["x"], p["y"]) for p in b["points"]])
            if pb[0] >= x - 10 and pb[2] <= x + 60 and pb[1] >= top_y - 10 and pb[3] <= bottom_y + 15:
                nearby.append({"key": list(key), "bounds": pb, "strokeColor": b.get("strokeColor"), "fillColor": b.get("fillColor")})
        assert all(p["strokeColor"] == "#009600" for p in nearby), (ref, nearby)
        channels.append({"ref": ref, "componentId": cid, "properties": properties, "pins": pins,
                         "symbolIdToPreserve": properties["Symbol"], "symbolRecordCounts": dict(Counter(h["type"] for h, b in symbol.values())),
                         "symbolVisualBoundsOnPage": page_bbox, "symbolOwnedPolys": polys,
                         "symbolOwnedColorHistogram": dict(Counter(str(p["strokeColor"]) + "/" + str(p["fillColor"]) for p in polys)),
                         "visualOwnership": "Resistor body, static reference/value glyphs, gray glyphs and NC overlays within this SYMBOL disappear with the instance. Preserve the shared SYMBOL document; do not delete symbol internals separately.",
                         "rootNearbyPolysToPreserve": nearby,
                         "topStubToDelete": full_record(tk, rows),
                         "sharedPreWireGroupToPreserve": full_record(("WIRE", tw), rows),
                         "sharedPreWireAttrsToPreserve": [full_record(k, rows) for k in children[tw]],
                         "sharedPreOtherLinesToPreserve": [full_record(k, rows) for k in top_sibling_keys],
                         "bottomStubToDelete": full_record(bk, rows),
                         "dedicatedGroundToDelete": full_record(gk, rows),
                         "deleteRecordKeys": [list(k) for k in sorted(keys)],
                         "deleteRecordsWithExactBodyChecks": [full_record(k, rows) for k in sorted(keys)]})
    previous = parse(PREVIOUS)
    differences = []
    for key in sorted(previous.keys() & rows.keys(), key=lambda k: (k[0], str(k[1]))):
        a, b = previous[key][1], rows[key][1]
        if a != b:
            fields = sorted(f for f in a.keys() | b.keys() if a.get(f) != b.get(f))
            classification = "ui-metadata" if key[0] in ("DOCHEAD", "CANVAS", "META") else "layout-only" if set(fields) <= {"x", "y", "rotation", "align", "zIndex", "locked"} else "reviewed-body-fields"
            differences.append({"key": list(key), "classification": classification, "fields": fields,
                                "changes": {f: {"before": a.get(f), "fresh": b.get(f)} for f in fields}})
    report = {"schema": "adc10-independent-seven-dnp-ownership-20261017-v1", "passed": True,
              "source": {"path": str(SOURCE.resolve()), "sha256": sha(SOURCE)},
              "checkpoint": {"path": str(CHECKPOINT.resolve()), "sha256": sha(CHECKPOINT)},
              "channels": channels, "deleteRecordKeys": [list(k) for k in sorted(delete)],
              "deleteRecordCounts": dict(Counter(k[0] for k in delete)), "totalDeleteRecords": len(delete),
              "allDeleteBodiesFrozenInReport": True, "allSevenSharedPreWireGroupsPreserved": True,
              "rootGlyphPolysDeleted": 0, "symbolLibraryDocumentsDeleted": 0,
              "maxReferencesOnFreshPage": {prefix: max(int(ref[len(prefix):]) for ref in refs if re.fullmatch(prefix + r"\d+", ref)) for prefix in ("U", "C", "R")},
              "freshVsLastInline": {"previousPath": str(PREVIOUS.resolve()), "previousSha256": sha(PREVIOUS),
                  "addedKeys": [list(k) for k in rows.keys() - previous.keys()], "removedKeys": [list(k) for k in previous.keys() - rows.keys()],
                  "bodyDifferenceCount": len(differences), "classificationCounts": dict(Counter(d["classification"] for d in differences)), "differences": differences},
              "warnings": ["This is deletion-ownership review only; it is not the complete approved seven-channel electrical redesign.",
                           "Delete top DNP stub LINE only, not its shared PRE WIRE group or siblings. Dedicated bottom stub WIRE and GND instance are wholly DNP-owned.",
                           "Do not reuse old source as candidate baseline; preserve fresh-source user edits.",
                           "No native/API/UI/PCB/library mutation or candidate source produced; native ERC and saved/reopened netlist/visual audits remain required after implementation."]}
    target = HERE / "independent-seven-dnp-ownership-audit.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "path": str(target.resolve()), "sha256": sha(target), "deleteRecordCounts": report["deleteRecordCounts"],
                      "totalDeleteRecords": len(delete), "maxReferencesOnFreshPage": report["maxReferencesOnFreshPage"],
                      "freshDiffCount": len(differences), "freshDiffClassifications": report["freshVsLastInline"]["classificationCounts"]}, indent=2))


if __name__ == "__main__":
    main()
