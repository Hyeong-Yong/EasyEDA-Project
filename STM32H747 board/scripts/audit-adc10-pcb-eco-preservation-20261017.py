"""Read-only source audit of DNP removal and the subsequently reviewed PCB ECO."""
import hashlib
import json
import runpy
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSE = runpy.run_path(str(ROOT / "output/candidates/adc-dc-buffer/independent-static-adc-plan-review.py"))["parse"]
FILES = {
    "before": ROOT / "output/validation/native-adc10-pcb-before-20261017.epru",
    "dnpRemoved": ROOT / "output/validation/native-adc10-pcb-dnp_removed-20261017.epru",
    "ecoApplied": ROOT / "output/validation/native-adc10-pcb-eco_applied-20261017.epru",
}
OUT = ROOT / "output/analysis/adc10-pcb-eco-preservation-20261017.json"
DNP = {f"R{x}" for x in (146,147,148,158,159,160,173,174,175,176)}
PASSIVES = {f"R{x}" for x in (137,138,139,140,141,142,143,144,145,149,150,151,152,153,154,155,156,157,161,162,163,164,165,166,167,168,169,170,171,172)} | {f"C{x}" for x in (80,81,82,86,87,88,93,94,95,96)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index(rows):
    attrs = defaultdict(dict)
    for (kind,rid),body in rows.items():
        if kind == "ATTR":
            attrs[body["parentId"]][body["key"]] = body.get("value")
    components = {rid:body for (kind,rid),body in rows.items() if kind == "COMPONENT"}
    uids = {}
    for cid,body in components.items():
        uid = body["attrs"]["Unique ID"]
        assert uid not in uids
        uids[uid] = {"componentId":cid,"ref":attrs[cid]["Designator"],"attributes":attrs[cid],"body":body}
    return attrs,components,uids


def owned(key,body,ids):
    kind,rid = key
    if kind == "COMPONENT":
        return rid in ids
    if kind == "ATTR":
        return body.get("parentId") in ids
    if kind == "PAD_NET":
        return json.loads(rid)[1] in ids
    return False


def diff(a,b):
    return set(a)-set(b),set(b)-set(a),{k for k in a.keys()&b.keys() if a[k] != b[k]}


def tally(keys):
    return dict(Counter(k[0] for k in keys))


def main():
    rows = {k:PARSE(v) for k,v in FILES.items()}
    a,b,c = (rows[k] for k in ("before","dnpRemoved","ecoApplied"))
    aa,ac,au = index(a)
    ba,bc,bu = index(b)
    ca,cc,cu = index(c)
    dnp_ids = {cid for cid,v in aa.items() if v.get("Designator") in DNP}
    assert len(dnp_ids) == 10
    deleted,added,changed = diff(a,b)
    allowed = {k for k,v in a.items() if owned(k,v,dnp_ids)}
    assert deleted == allowed and len(deleted) == 60 and not added
    assert changed == {("DOCHEAD",None)}
    assert {k for k in a["DOCHEAD",None] if a["DOCHEAD",None][k] != b["DOCHEAD",None][k]} == {"client","version","updateTime"}
    assert len(ac) == 330 and len(bc) == 320 and len(cc) == 354
    assert not (bu.keys()-cu.keys())
    replaced = {uid for uid in bu if bu[uid]["componentId"] != cu[uid]["componentId"]}
    assert {bu[uid]["ref"] for uid in replaced} == PASSIVES and len(replaced) == 40
    new = cu.keys()-bu.keys()
    assert len(new) == 34
    assert {cu[uid]["ref"] for uid in new} == {f"U{x}" for x in range(9,20)} | {f"C{x}" for x in range(97,120)}
    for uid in bu:
        assert bu[uid]["ref"] == cu[uid]["ref"]
    old_ids = {bu[uid]["componentId"] for uid in replaced}
    new_ids = {cu[uid]["componentId"] for uid in replaced | new}
    deleted,added,changed = diff(b,c)
    assert all(owned(k,b[k],old_ids) for k in deleted)
    assert len(deleted) == 240 and tally(deleted) == {"COMPONENT":40,"ATTR":120,"PAD_NET":80}
    unowned_add = {k for k in added if not owned(k,c[k],new_ids)}
    assert tally(unowned_add) == {"NET":21,"RULE_SELECTOR":21}
    expected_nets = {f"ADC{bank}_{name}{i}" for bank,n in ((1,3),(2,3),(3,4)) for name in ("PRE","DRV") for i in range(1,n+1)} | {"ADC_BIAS_2V5"}
    assert {json.loads(rid)[1] for kind,rid in unowned_add if kind == "NET"} == expected_nets
    assert changed == {("DOCHEAD",None)}
    assert {k for k in b["DOCHEAD",None] if b["DOCHEAD",None][k] != c["DOCHEAD",None][k]} == {"client","version","updateTime"}
    pinsets = defaultdict(set)
    for (kind,rid),body in c.items():
        if kind == "PAD_NET":
            _,cid,num,local_id = json.loads(rid)
            pinsets[ca[cid]["Designator"],str(num)].add(body["padNet"])
    assert all(len(v) == 1 for v in pinsets.values())
    actual = {k:next(iter(v)) for k,v in pinsets.items() if next(iter(v))}
    contract_path = ROOT / "output/candidates/adc10-dc-buffer-20261017/independent-adc10-expected-full-pin-contract-20261017.json"
    contract = json.loads(contract_path.read_text(encoding="utf8"))
    expected = {(v["ref"],v["number"]):v["net"] for v in contract["expectedPins"]}
    assert actual == expected and len(actual) == 1136
    protected = {k for k in b if not owned(k,b[k],old_ids) and k != ("DOCHEAD",None)}
    assert all(k in c and b[k] == c[k] for k in protected)
    report = {
        "schema":"adc10-pcb-eco-preservation-20261017-v1",
        "status":"PASS", "readOnly":True, "nativeCallsPerformed":False,
        "sources":{k:{"path":str(v),"sha256":digest(v),"records":len(rows[k])} for k,v in FILES.items()},
        "dnpRemoval":{"refs":sorted(DNP),"deleted":{"COMPONENT":10,"ATTR":30,"PAD_NET":20},"added":0,"onlyChangedExistingRecord":"DOCHEAD client/version/updateTime"},
        "eco":{"originalRemainingUniqueIdsPreserved":320,"replacedRefs":sorted(PASSIVES),"footprintReplacementCount":40,"newRefs":sorted(cu[uid]["ref"] for uid in new),"newParts":34,"totalComponents":354,"deletedRecordCounts":tally(deleted),"addedRecordCounts":tally(added),"unownedAdditions":{"NET":21,"RULE_SELECTOR":21},"newNetNames":sorted(expected_nets),"onlyChangedExistingRecord":"DOCHEAD client/version/updateTime","protectedRecordCountExact":len(protected)},
        "pinContract":{"path":str(contract_path),"sha256":digest(contract_path),"uniquePhysicalPinNumbers":len(pinsets),"connectedPins":1136,"missing":0,"extra":0,"mismatched":0,"conflictingDuplicatePadBindings":0},
        "protectedBodiesExact":["All old non-component-owned records","LINE5422","ARC2184","FILL730","POLY500","VIA634","Free PAD4 mounting holes","STRING21","Existing NET280","All existing RULE_SELECTOR280","RULE18","RULE_TEMPLATE1","LAYER64","LAYER_PHYS17","Outline primitives and approved CN1 cutout"],
        "state":"Unsaved ECO capture; replacement/new placement and routing are still incomplete",
        "physicalRoutingVerified":False,"manufacturingReady":False,"floatingActualZeroDetectorImplemented":False,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"status":"PASS","report":str(OUT),"protectedExact":len(protected),"connectedPins":len(actual),"physicalParts":len(cc)}))


if __name__ == "__main__":
    main()
