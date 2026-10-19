"""Read-only comparison of pre-3D and C1 pilot checkpoints; writes research JSON only."""
import collections
import hashlib
import json
from pathlib import Path
import re
import zipfile

HERE=Path(__file__).resolve().parent
BOARD=HERE.parents[2]
BEFORE=BOARD/"output/checkpoints/STM32H747_before_3d_models_20261018.epro2"
AFTER=BOARD/"output/checkpoints/STM32H747_3d_c1_pilot_20261018.epro2"
MODEL="6034de4795654a0c8c74309dab7cb0b9"
LIBRARY="0819f05c4eef4c71ace90d822a990e87"

def sha(data):
    return hashlib.sha256(data).hexdigest()

def inspect(path):
    with zipfile.ZipFile(path) as archive:
        entries={item.filename:{"bytes":item.file_size,"compressed_bytes":item.compress_size,"sha256":sha(archive.read(item.filename))} for item in archive.infolist()}
        text_name=next(n for n in entries if n.endswith(".epru"))
        text=archive.read(text_name).decode("utf-8-sig")
        metadata=json.loads(archive.read("project2.json"))
        model_lines=[]
        doc_types=collections.Counter()
        current_doc=None
        document_uuid=None
        records=collections.Counter()
        canonical={}
        blob_kinds=collections.Counter()
        total=0
        for lineno,line in enumerate(text.splitlines(),1):
            if "||" not in line:
                continue
            outer,inner=line.split("||",1)
            try:
                head=json.loads(outer)
                body=json.loads(inner.removesuffix("|"))
            except json.JSONDecodeError:
                continue
            total+=1
            if head.get("type")=="DOCHEAD" and isinstance(body,dict):
                current_doc=body.get("docType")
                document_uuid=body.get("uuid")
                doc_types[str(current_doc)]+=1
            records[str(head.get("type"))]+=1
            key=json.dumps([str(current_doc),str(document_uuid),head.get("type"),head.get("id")],ensure_ascii=True)
            prior=canonical.get(key)
            if prior is None or head.get("ticket",0)>=prior["head"].get("ticket",0):
                canonical[key]={"head":head,"body":body}
            if current_doc=="BLOB" and isinstance(body,dict) and "data" in body:
                value=str(body["data"])
                blob_kinds[value.split(",",1)[0][:100]]+=1
            if MODEL in line:
                model_lines.append({"line":lineno,"doc_type":current_doc,"document_uuid":document_uuid,"head":head,"body":body})
        return {"path":str(path),"bytes":path.stat().st_size,"sha256":sha(path.read_bytes()),"entries":entries,"project_metadata":metadata,"text_entry":text_name,"doc_types":dict(doc_types),"record_types":dict(records),"total_records":total,"model_uuid_occurrences":text.count(MODEL),"model_reference_records":model_lines,"step_header_present":b"ISO-10303-21" in archive.read(text_name),"blob_media_kinds":dict(blob_kinds)},canonical

before,before_records=inspect(BEFORE)
after,after_records=inspect(AFTER)
assert set(before["entries"])==set(after["entries"])
changed=[name for name in before["entries"] if before["entries"][name]["sha256"]!=after["entries"][name]["sha256"]]
added=sorted(set(after_records)-set(before_records))
removed=sorted(set(before_records)-set(after_records))
body_changed=[key for key in before_records.keys() & after_records.keys() if before_records[key]["body"]!=after_records[key]["body"]]
changed_records=[{"record_key":json.loads(key),"before":before_records[key],"after":after_records[key]} for key in body_changed[:25]]
result={
    "method":"Read-only ZIP entry hashing and parsed EPRU log inspection. No native API, bridge, UI, source checkpoint edit, or system library access.",
    "model_uuid":MODEL,"source_library_uuid":LIBRARY,
    "before":before,"after":after,"file_byte_increase":after["bytes"]-before["bytes"],
    "entry_names_unchanged":True,"changed_entries":changed,"canonical_added_records":added,"canonical_added_record_details_first25":[{"record_key":json.loads(key),"record":after_records[key]} for key in added[:25]],"canonical_removed_records":removed,"canonical_body_changed_count":len(body_changed),"canonical_body_changes_first25":changed_records,
    "conclusion":"The pilot checkpoint stores a qualified external system-library reference and its title/transform. No standalone 3D model entry, model document type, or new geometry payload was found in the archive. This verifies saved binding metadata, not embedded model portability. Rendering or STEP export may resolve/cache the referenced model separately; that is not proven by this checkpoint.",
    "limits":"The comparison proves what is present in these two ZIP snapshots. It does not inspect unrelated app caches or network fetching, nor claim the native renderer cannot cache external models elsewhere."
}
OUT=HERE/"c1-checkpoint-payload-audit.json"
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
assert sha(BEFORE.read_bytes())==before["sha256"] and sha(AFTER.read_bytes())==after["sha256"]
print(json.dumps({"report":str(OUT),"before_bytes":before["bytes"],"after_bytes":after["bytes"],"byte_increase":result["file_byte_increase"],"entry_count":len(after["entries"]),"changed_entries":changed,"doc_types":after["doc_types"],"model_reference_records":after["model_reference_records"],"canonical_body_changed_count":len(body_changed),"canonical_added_records":len(added),"canonical_removed_records":len(removed),"blob_media_kinds":after["blob_media_kinds"]}))
