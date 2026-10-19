"""Repair accepted-run metadata from existing logs; no simulations or numeric edits."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
SIM=HERE.parent.parent
RUNTIME=SIM/"runtime"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def numeric_state(summary):
    return json.dumps({r["case"]:r.get("voltages_currents") for r in summary["results"]},sort_keys=True)

original_summary=RUNTIME/"dcpoint-summary.json"
original_hash=sha(original_summary)
changes=[]
checks=[]
for filename in ["dcpoint-attempt2-summary.json","dcpoint-accepted-summary.json"]:
    path=RUNTIME/filename
    summary=json.loads(path.read_text())
    numeric_before=numeric_state(summary)
    for row in summary["results"]:
        name=row["case"]
        log_path=SIM/"runs"/(name+".log")
        raw_path=SIM/"runs"/(name+".raw")
        log=log_path.read_text(errors="replace")
        actual="transient op" in log.lower()
        previous=row.get("transient_op_fallback_used")
        row["transient_op_fallback_used"]=actual
        if previous is not actual:
            changes.append({"summary":filename,"case":name,"previous":previous,"current":actual,"log_sha256":sha(log_path)})
        if row["validated_true_dc"]:
            assert not actual,name
            assert row["run"]["run_ok"] and not row["run"]["warnings"],name
            assert not row["run"]["optran_used"],name
        checks.append({"summary":filename,"case":name,"log_sha256":sha(log_path),"raw_sha256":sha(raw_path),"accepted_fallback":actual})
    assert numeric_before==numeric_state(summary),"Numeric results must not change"
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    temporary.replace(path)
assert sha(original_summary)==original_hash,"Initial failed-run summary must remain unchanged"
audit={"action":"Recomputed transient_op_fallback_used from each current accepted run's existing log. Original failures remain in dcpoint-summary.json; no simulations or numeric result changes.","original_attempt1_summary_sha256":original_hash,"original_attempt1_summary_unchanged":True,"changes":changes,"accepted_log_checks":checks}
(RUNTIME/"dcpoint-metadata-normalization.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"metadata_changes":len(changes),"log_checks":len(checks),"initial_summary_unchanged":True,"numeric_results_unchanged":True,"all_accepted_runs_report_no_transient_fallback":all(not c["accepted_fallback"] for c in checks)}))
