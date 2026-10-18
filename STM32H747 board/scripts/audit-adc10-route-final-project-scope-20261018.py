"""Read-only final routing checkpoint scope, materializing native tombstones."""
import hashlib
import json
import runpy
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
H=runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))
U=H["UTIL"]
BEFORE=ROOT/"output/checkpoints/STM32H747_before_pcb_route_20261018.epro2"
PCB=("PCB","0ac2a19168000d8e")
OUT=ROOT/"output/candidates/adc10-pcb-finish-20261018/adc10-final-route-project-scope-independent-audit-20261018.json"


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    final=Path(sys.argv[1]);source=Path(sys.argv[2])
    before,bt=H["read_snapshot"](BEFORE)
    after,at=H["read_snapshot"](final)
    body=U["bodies"]
    errors=[]
    if set(before)!=set(after):errors.append({"documentSetChanged":{"missing":sorted(set(before)-set(after)),"added":sorted(set(after)-set(before))}})
    changed=[k for k in before.keys()&after.keys() if body(before[k])!=body(after[k])]
    if changed!=[PCB]:errors.append({"changedDesignDocumentBodiesNotExactlyPCB":changed})
    header_errors=[];session_only=[]
    for doc in before.keys()&after.keys():
        a=next(b for (kind,i),(h,b) in before[doc].items() if kind=="DOCHEAD")
        b=next(b for (kind,i),(h,b) in after[doc].items() if kind=="DOCHEAD")
        fields=[f for f in a.keys()|b.keys() if a.get(f)!=b.get(f)]
        if fields:
            if set(fields)<={"client","version","updateTime"}:session_only.append({"doc":doc,"fields":fields})
            else:header_errors.append({"doc":doc,"fields":fields})
    if header_errors:errors.append({"unexpectedDocumentHeaderChanges":header_errors})
    match=U["source_matches_snapshot"](source,after[PCB])
    # Runtime creates empty per-NET inheritance selectors for the 21 ADC nets;
    # the stored checkpoint omits those no-op defaults. Never normalize an
    # assigned rule, copper value, plane value or any unrelated selector.
    native=U["native_source"](source)
    snap=body(after[PCB])
    expected_nets={"ADC_BIAS_2V5"}|{f"ADC{adc}_{role}{i}" for adc,n in [(1,3),(2,3),(3,4)] for role in ["PRE","DRV"] for i in range(1,n+1)}
    empty={"ruleOrder":4,"ruleKeyValue":{},"copperValue":{},"innerPlaneValue":{}}
    derived=[];kept=[]
    for error in match["errors"]:
        key=tuple(error.get("sourceOnly",[]))
        valid=False
        if len(key)==2 and key[0]=="RULE_SELECTOR" and native.get(key)==empty:
            selector=json.loads(key[1])
            if selector[0]=="RULE_SELECTOR" and selector[1][0]=="NET" and selector[1][1] in expected_nets:
                net=selector[1][1]
                valid=any(k[0]=="NET" and json.loads(k[1])==["NET",net] for k,v in snap.items())
                if valid:derived.append({"record":key,"net":net,"exactRuntimeBody":empty,"rule":"Runtime-only empty per-net selector: no rule/copper/plane override; unchanged selected global rules apply"})
        if not valid:kept.append(error)
    if {d["net"] for d in derived}!=expected_nets:
        errors.append({"unexpectedEmptyRuntimeADCSelectorSet":{"classified":[d["net"] for d in derived],"expected":sorted(expected_nets)}})
    match["errors"]=kept
    match["normalizations"].extend(derived)
    match["passed"]=not kept
    match["runtimeOnlyEmptyADCNetSelectors"]=derived
    before_pcb=body(before[PCB])
    rules_before={k:v for k,v in before_pcb.items() if k[0]=="RULE"}
    rules_final={k:v for k,v in snap.items() if k[0]=="RULE"}
    if rules_before!=rules_final or len(rules_final)!=18:
        errors.append("Selected18 native RULE bodies changed")
    if not match["passed"]:errors.append({"savedReopenedNativePCBVsCheckpoint":match["errors"]})
    with zipfile.ZipFile(BEFORE) as a,zipfile.ZipFile(final) as b:
        meta_exact=json.loads(a.read("project2.json"))==json.loads(b.read("project2.json"))
        changed_images=[n for n in sorted(set(a.namelist())&set(b.namelist())) if n.startswith("IMAGE/") and not n.endswith("/") and a.read(n)!=b.read(n)]
    if not meta_exact:errors.append("project2.json metadata changed; inspect before classifying")
    report={"schema":"adc10-final-route-project-scope-independent-20261018-v1","status":"PASS" if not errors else "FAIL","beforeCheckpoint":{"path":str(BEFORE),"sha256":sha(BEFORE)},"finalCheckpoint":{"path":str(final),"sha256":sha(final)},"actualNativePCB":{"path":str(source),"sha256":sha(source)},"documentCounts":{"before":len(before),"after":len(after),"byType":dict(Counter(d[0] for d in after))},"changedDesignDocumentBodiesExactly":changed,"allOtherNonHeaderDocumentBodiesExact":len(before)-1,"allFiveSchematicPagesExact":all(body(before[d])==body(after[d]) for d in before if d[0]=="SCH_PAGE"),"allSymbolFootprintDeviceBodiesExact":all(body(before[d])==body(after[d]) for d in before if d[0] in {"SYMBOL","FOOTPRINT","DEVICE"}),"projectMetadataExact":meta_exact,"sessionOnlyHeaderChanges":session_only,"unexpectedHeaderChanges":header_errors,"savedReopenedPCBMatchesCheckpoint":match,"historicalTombstoneHandling":{"beforeHistoricalCount":len(bt["historicalEmptyBodyTombstones"]),"beforeEffectiveCount":len(bt["effectiveLatestTombstones"]),"afterHistoricalCount":len(at["historicalEmptyBodyTombstones"]),"afterEffectiveCount":len(at["effectiveLatestTombstones"]),"rule":at["rule"]},"changedPreviewImageNames":changed_images,"liveCalls":0,"nativeWrites":0,"manufacturingReady":False,"errors":errors}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"sha256":sha(OUT),"status":report["status"],"docs":len(after),"changed":changed,"errors":errors}))
    if errors:raise SystemExit(1)


if __name__=="__main__":main()
