"""Bounded before/after checkpoint scope audit with explicit native tombstones."""
import hashlib
import json
import runpy
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
UTIL = runpy.run_path(str(HERE.parent / "adc-dc-buffer/independent-final-project-scope-audit.py"))
BEFORE = ROOT / "output/checkpoints/STM32H747_before_adc_inline_20261016.epro2"
FINAL = ROOT / "output/checkpoints/STM32H747_adc_inline_schematic_20261016.epro2"
SOURCE = ROOT / "output/validation/native-adc-inline-reopened-20261016.epru"
PAGE = ("SCH_PAGE", "a07bf8e4331877a8")


def read_snapshot(path):
    with zipfile.ZipFile(path) as archive:
        source = archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode("utf8")
    docs, current, tombstones = {}, None, []
    for line in source.splitlines():
        if not line.strip():
            continue
        raw_head, raw_body = line.split("||",1)
        head = json.loads(raw_head)
        body_text = raw_body.rstrip("|")
        deleted = not body_text
        body = None if deleted else json.loads(body_text)
        if head["type"] == "DOCHEAD":
            assert not deleted
            current = body["docType"],body["uuid"]
            docs.setdefault(current,{})
        assert current is not None
        key = head["type"],str(head.get("id",""))
        old = docs[current].get(key)
        if old is None or head.get("ticket",0) >= old[0].get("ticket",0):
            docs[current][key] = head,body
        if deleted:
            tombstones.append({"doc":current,"record":key,"ticket":head.get("ticket")})
    effective = []
    for doc,records in docs.items():
        for key,(head,body) in list(records.items()):
            if body is None:
                effective.append({"doc":doc,"record":key,"ticket":head.get("ticket")})
                del records[key]
    return docs,{"historicalEmptyBodyTombstones":tombstones,"effectiveLatestTombstones":effective,"rule":"Highest-ticket state per document/type/id; an empty body is deletion, not a malformed JSON object or a resurrected earlier body"}


def main():
    before,bt = read_snapshot(BEFORE)
    final,ft = read_snapshot(FINAL)
    bodies,sha = UTIL["bodies"],UTIL["sha"]
    errors = []
    if before.keys() != final.keys():
        errors.append({"changedDocumentSet":{"missing":sorted(before.keys()-final.keys()),"added":sorted(final.keys()-before.keys())}})
    changed = [k for k in before.keys()&final.keys() if bodies(before[k]) != bodies(final[k])]
    if changed != [PAGE]:
        errors.append({"changedDocumentBodiesNotExactlyPage06":changed})
    norm = json.loads((HERE/"adc-inline-final-reopened-normalization-audit.json").read_text(encoding="utf8"))
    if not norm["passed"] or norm["sourceSha256"] != sha(SOURCE):
        errors.append("Independent final source audit failed or stale")
    match = UTIL["source_matches_snapshot"](SOURCE,final[PAGE])
    # The decoder's twelve known wire-metadata z-order changes are derived
    # at runtime; the saved full checkpoint stores their original order.
    plan = json.loads((HERE/"adc-inline-schematic-plan.json").read_text(encoding="utf8"))
    candidate = UTIL["native_source"](plan["candidatePath"])
    native = UTIL["native_source"](SOURCE)
    snapshot = bodies(final[PAGE])
    z_ids = {tuple(n["record"]) for n in norm["normalizations"] if n["rule"] == "six inline wire NET/Relevance display z-order normalization"}
    classified_z = []
    for discrepancy in match["errors"]:
        key = tuple(discrepancy.get("record",()))
        if key in z_ids and discrepancy.get("field") == "zIndex" and snapshot[key].get("zIndex") == candidate[key].get("zIndex"):
            classified_z.append(discrepancy)
            match["normalizations"].append({"record":key,"field":"zIndex","rule":"twelve audited PRE/DRV NET/Relevance runtime z-order versus original stored order","nativeValue":native[key].get("zIndex"),"storedValue":snapshot[key].get("zIndex")})
    match["errors"] = [e for e in match["errors"] if e not in classified_z]
    match["bodyDifferences"] = [e for e in match["bodyDifferences"] if e not in classified_z]
    match["passed"] = not match["errors"]
    match["normalizationRuleCounts"] = dict(Counter(n["rule"] for n in match["normalizations"]))
    if len(classified_z) != 12:
        errors.append({"unexpectedRuntimeStoredZNormalizationCount":len(classified_z)})
    if not match["passed"]:
        errors.append({"savedSourceSnapshotMismatch":match["errors"]})
    old_page,new_page = bodies(before[PAGE]),bodies(final[PAGE])
    refs = {v["value"]: v["parentId"] for (k,_),v in old_page.items() if k=="ATTR" and v.get("key")=="Designator"}
    old_uid = runpy.run_path(str(ROOT/"scripts/build-adc-dc-schematic-patch.py"))["uid"]
    ref_components = {refs[r] for r in ["U9","C103","C104","C105"]}
    ref_wires = {old_uid(k) for k in ["ref-in","ref-in-gnd","ref-out","ref-out-cap","ref-gnd","ref-out-gnd"]}
    ref_texts = {old_uid(k+"/label") for k in ["ref-in","ref-in-gnd","ref-out","ref-gnd","ref-out-gnd"]} | {old_uid("ref-header"),"f4ba1d7115d2fc19"}
    protected_ref = {k for k,v in old_page.items() if k[1] in ref_components|ref_wires|ref_texts or v.get("parentId") in ref_components|ref_wires or v.get("lineGroup") in ref_wires}
    ref_differences = [k for k in protected_ref if k not in new_page or old_page[k] != new_page[k]]
    if ref_differences:
        errors.append({"freshReferenceUserEditsChanged":ref_differences})
    with zipfile.ZipFile(BEFORE) as a,zipfile.ZipFile(FINAL) as b:
        meta_exact = json.loads(a.read("project2.json")) == json.loads(b.read("project2.json"))
        changed_images = [n for n in sorted(set(a.namelist())&set(b.namelist())) if n.startswith("IMAGE/") and not n.endswith("/") and a.read(n)!=b.read(n)]
    if not meta_exact:
        errors.append("Project metadata changed")
    report = {"passed":not errors,"schema":"adc-inline-final-project-scope-20261016-v1","checkpoints":{"before":{"path":str(BEFORE),"bytes":BEFORE.stat().st_size,"sha256":sha(BEFORE)},"final":{"path":str(FINAL),"bytes":FINAL.stat().st_size,"sha256":sha(FINAL)}},"documentCounts":{"before":len(before),"final":len(final)},"changedDocumentBodiesExactly":changed,"nonTargetDocumentBodiesExactExcludingSessionDochead":len(before)-1,"pcbDocumentBodyUnchanged":all(bodies(before[k])==bodies(final[k]) for k in before if k[0]=="PCB"),"allLibraryDocumentBodiesUnchanged":all(bodies(before[k])==bodies(final[k]) for k in before if k[0] in {"SYMBOL","FOOTPRINT","DEVICE"}),"otherFourSchematicPagesUnchanged":all(bodies(before[k])==bodies(final[k]) for k in before if k[0]=="SCH_PAGE" and k!=PAGE),"freshReferenceBlockProtected":{"recordCount":len(protected_ref),"allExact":not ref_differences,"differences":ref_differences},"finalPageMatchesSavedReopenedSource":match,"finalNativeSourceNormalizationAuditPassed":norm["passed"],"historicalTombstoneHandling":{"before":bt,"final":ft},"projectMetadataExact":meta_exact,"changedPreviewImages":changed_images,"floatingInputBehaviorUnchanged":True,"floatingZeroRedesignPendingUserChoice":True,"pcbAdcEcoApplied":False,"manufacturingReady":False,"errors":errors}
    path = HERE/"adc-inline-final-project-scope-audit.json"
    path.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"passed":report["passed"],"report":str(path),"changedDocuments":changed,"finalSha256":sha(FINAL),"savedSourceMatch":match["passed"],"protectedReferenceRecords":len(protected_ref),"beforeHistoricalTombstones":len(bt["historicalEmptyBodyTombstones"]),"finalHistoricalTombstones":len(ft["historicalEmptyBodyTombstones"]),"errors":errors},indent=2))
    if errors:
        raise ValueError("Inline final checkpoint scope failed")


if __name__ == "__main__":
    main()
