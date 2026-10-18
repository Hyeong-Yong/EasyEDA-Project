"""Offline, placement-only orientation plan against the native ECO capture."""
import hashlib
import json
import math
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSE = runpy.run_path(str(ROOT / "output/candidates/adc-dc-buffer/independent-static-adc-plan-review.py"))["parse"]
SOURCE = ROOT / "output/validation/native-adc10-pcb-eco_applied-20261017.epru"
BEFORE = ROOT / "output/validation/native-adc10-pcb-before-20261017.epru"
INVENTORY = ROOT / "output/analysis/adc10-pcb-eco-api-feasibility-20261017.json"
OUT = ROOT / "output/analysis/adc10-passive-orientation-plan-20261017.json"


def main():
    rows = PARSE(SOURCE)
    old = PARSE(BEFORE)
    attrs = {}
    for (kind,rid),body in rows.items():
        if kind == "ATTR":
            attrs.setdefault(body["parentId"],{})[body["key"]] = body.get("value")
    refs = {v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    inv = json.loads(INVENTORY.read_text(encoding="utf8"))
    old_parts = {p["ref"]:p for ch in inv["channels"] for p in ch["originalAnalogParts"]}
    bias = {f"R{x}" for x in (137,138,139,149,150,151,161,162,163,164)}
    bucket = {f"C{x}" for x in (80,81,82,86,87,88,93,94,95,96)}
    plan = []
    for ref in sorted(bias|bucket):
        cid = refs[ref]
        b = rows["COMPONENT",cid]
        prev = old_parts[ref]
        assert b["layerId"] == 1 and b["angle"] == 0
        assert b["x"] == prev["xyMil"][0] and b["y"] == prev["xyMil"][1]
        ang = 90 if ref in bias else 270
        # Generic 0402 pad geometry was independently extracted from the saved
        # project footprint docs; report world pads as the transformation oracle.
        offset = 20.078701 if ref in bias else 18.897638
        locals_ = {"1":(-offset,0),"2":(offset,0)} if ref in bias else {"1":(offset,0),"2":(-offset,0)}
        theta = math.radians(ang)
        pads = {}
        for num,(px,py) in locals_.items():
            x = b["x"]+px*math.cos(theta)-py*math.sin(theta)
            y = b["y"]+px*math.sin(theta)+py*math.cos(theta)
            nets = {body["padNet"] for (kind,rid),body in rows.items() if kind == "PAD_NET" and json.loads(rid)[1:3] == [cid,num]}
            assert len(nets) == 1
            pads[num] = {"xyMil":[x,y],"xyMm":[x*.0254,y*.0254],"net":next(iter(nets))}
        if ref in bias:
            # Deliberate pin-number exchange: new pin1 PRE occupies old pin2
            # mixer location, new pin2 BIAS occupies old pin1 supply location.
            mappings = {"1":"2","2":"1"}
        else:
            mappings = {"1":"1","2":"2"}
        errors = []
        for num,old_num in mappings.items():
            op = next(p for p in prev["pads"] if p["number"] == old_num)
            errors.append(math.dist(pads[num]["xyMm"],op["worldMm"]))
        assert max(errors) < .00001
        plan.append({"ref":ref,"componentId":cid,"uniqueId":b["attrs"]["Unique ID"],"footprintUuid":attrs[cid]["Footprint"],"sourceBodyBefore":b,"set":{"x":b["x"],"y":b["y"],"rotation":ang,"layer":b["layerId"]},"expectedPadWorld":pads,"oldPadNumberAtNewSite":mappings,"maxPadCenterDifferenceMm":max(errors),"temporaryAtOldSite":ref in bucket})
    unchanged = []
    for ch in inv["channels"]:
        for p in ch["originalAnalogParts"]:
            ref = p["ref"]
            if ref.startswith("R") and ref not in bias and ref in refs:
                b = rows["COMPONENT",refs[ref]]
                assert b["angle"] == 0 and [b["x"],b["y"]] == p["xyMil"]
                unchanged.append({"ref":ref,"componentId":refs[ref],"rotation":0,"xyMil":[b["x"],b["y"]]})
    assert len(plan) == 20 and len(unchanged) == 20
    report = {"schema":"adc10-passive-orientation-plan-20261017-v1","readOnly":True,"sourcePath":str(SOURCE),"sourceSha256":hashlib.sha256(SOURCE.read_bytes()).hexdigest(),"componentCountToRotate":20,"placementOnly":True,"preserveFullPrecisionCenters":True,"noNetOrCopperChanges":True,"edits":plan,"alreadyCorrectHorizontalResistors":unchanged,"warnings":["This only restores pad contact orientation; it does not repair old bias +3V3 branches or mixer-to-series bypass copper.","Ten capacitors remain temporarily at old strip sites. Final 2.2nF buckets must still move to bottom MCU ADC escape locations.","After async component done, re-read source and require only the 20 allowed component angle changes plus any separately reviewed owned display transformations; reject unrelated rounding/default changes.","All temporary sites are TOP; bottom-side mirroring must be checked afresh when buckets move."],"manufacturingReady":False}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"rotate":len(plan),"alreadyCorrect":len(unchanged),"maxPadDeltaMm":max(x["maxPadCenterDifferenceMm"] for x in plan)}))


if __name__ == "__main__":
    main()
