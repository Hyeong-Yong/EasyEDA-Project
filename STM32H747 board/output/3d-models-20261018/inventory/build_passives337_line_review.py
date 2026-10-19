"""Freeze the one inspected native 10->20 line split and zIndex reset case.

This creates evidence only. It does not amend CAD or normalize any source.
The generic audit may reuse this case only while all exact old/new LINE IDs
and bodies remain identical; future unrelated line differences are not waived.
"""
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / "audit_model_metadata.py"))
ROOT, OUT = M["ROOT"], M["OUT"]
baseline = M["BASELINE"]
source = ROOT / "output/validation/pcb-3d-passives-337-20261018.epru"
a, _ = M["parse"](baseline)
b, _ = M["parse"](source)
assert M["sha"](baseline) == M["BASE_SHA"]
added, deleted = b.keys() - a.keys(), a.keys() - b.keys()
changed = [k for k in a.keys() & b.keys() if a[k] != b[k]]
delta = {
    "added_lines": [{"record": list(k), "body": b[k]} for k in sorted(added) if k[0] == "LINE"],
    "deleted_lines": [{"record": list(k), "body": a[k]} for k in sorted(deleted) if k[0] == "LINE"],
    "changed_line_bodies": [{"record": list(k), "before": a[k], "after": b[k]} for k in sorted(changed) if k[0] == "LINE"],
}
assert len(delta["added_lines"]) == 20 and len(delta["deleted_lines"]) == 10 and not delta["changed_line_bodies"]
assert {r["body"]["zIndex"] for r in delta["deleted_lines"]} == {400, 524, 564, 570, 3498, 3551, 6157, 6160, 6179, 6189}
assert {r["body"]["zIndex"] for r in delta["added_lines"]} == {-1}
assert M["line_unions"](a, {"zIndex"}) == M["line_unions"](b, {"zIndex"})
assert M["line_unions"](a) != M["line_unions"](b)
review = {
    "schema": "stm32-native-passives337-frozen-line-serialization-review-v1",
    "baseline_sha256": M["sha"](baseline), "reviewed_source_sha256": M["sha"](source),
    "strict_line_id_and_body_preservation": False,
    "all_metadata_line_union_preservation": False,
    "exact_geometry_and_non_display_metadata_union_preserved": True,
    "allowed_omitted_metadata_fields": ["zIndex"],
    "method": "Exact rational collinear interval unions. All LINE body fields other than coordinates are grouping keys; only zIndex is separately waived for the exact frozen old10/new20 body set.",
    "interpretation": "Native serialization split straight tracks at component-pad positions and reset drawing order to -1. Net, layer, width, locked/group/partition and exact occupied centerline union remain identical. No coordinate/area/distance tolerance.",
    "line_delta": delta,
    "reusable_only_if_exact_delta_matches": True,
    "cad_modified_by_review": False,
}
target = OUT / "audits/line-reserialization-passives337-review.json"
assert not target.exists(), "Do not replace reviewed evidence"
target.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"path": str(target.relative_to(ROOT)), "sha256": M["sha"](target), "old_lines": 10, "new_lines": 20, "physical_geometry_exact": True, "strict_record_metadata_exact": False}))
