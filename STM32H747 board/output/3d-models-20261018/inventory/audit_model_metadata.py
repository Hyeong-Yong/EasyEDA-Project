"""Audit 3D-only PCB changes against the frozen routed source, without native calls.

Default strict mode fails if LINE records are reserialized. An explicit
--allow-exact-line-reserialization option accepts only an EXACT rational
centerline union proof grouped by all non-coordinate line metadata. It does
not add a distance, area, rounding, clearance, or manufacturing tolerance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
ROOT = HERE.parents[2]
BASELINE = ROOT / "output/validation/native-adc10-pcb-labtool_adc10_routed_final_saved-20261018.epru"
BASE_SHA = "b7c6b99df160aaed2bb1f91717c2bde25e379bfdba88ec23dea5b4fdb7548d0f"
MODEL_KEYS = {"3D Model", "3D Model Title", "3D Model Transform"}
EMPTY_NET_BODY = {"netType": None, "specialColor": None, "retLine": True, "differentialName": None,
                  "isPositiveNet": False, "equalLengthGroupName": None}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    rows, headers = {}, {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        h, b = line.split("||", 1)
        h = json.loads(h)
        b = b.rstrip("|")
        k = h["type"], str(h.get("id", ""))
        if k not in headers or h.get("ticket", 0) >= headers[k].get("ticket", 0):
            rows[k] = json.loads(b) if b else None
            headers[k] = h
    return {k: b for k, b in rows.items() if b is not None}, headers


def refs(rows):
    attrs = defaultdict(dict)
    for (kind, rid), b in rows.items():
        if kind == "ATTR":
            attrs[b["parentId"]][b["key"]] = b.get("value")
    comp = {rid: b for (kind, rid), b in rows.items() if kind == "COMPONENT"}
    return {attrs[cid]["Designator"]: cid for cid in comp}, attrs


def canonical_line(b, ignored_metadata=()):
    metadata = {k: v for k, v in b.items() if k not in ("startX", "startY", "endX", "endY") and k not in ignored_metadata}
    # str(JSON float) preserves its exact finite decimal value; no rounding.
    x1, y1, x2, y2 = [Fraction(str(b[k])) for k in ("startX", "startY", "endX", "endY")]
    dx, dy = x2 - x1, y2 - y1
    if not dx and not dy:
        support = ("POINT", str(x1), str(y1))
        return json.dumps(metadata, sort_keys=True, separators=(",", ":")), support, (Fraction(0), Fraction(0))
    aa, bb = dy, -dx
    cc = -(aa * x1 + bb * y1)
    denominator = math.lcm(aa.denominator, bb.denominator, cc.denominator)
    integers = [int(v * denominator) for v in (aa, bb, cc)]
    divisor = math.gcd(*[abs(v) for v in integers])
    integers = [v // divisor for v in integers]
    if next(v for v in integers if v) < 0:
        integers = [-v for v in integers]
    values = (x1, x2) if dx else (y1, y2)
    support = ("X" if dx else "Y", *integers)
    return json.dumps(metadata, sort_keys=True, separators=(",", ":")), support, (min(values), max(values))


def line_unions(rows, ignored_metadata=()):
    groups = defaultdict(list)
    for (kind, rid), body in rows.items():
        if kind == "LINE":
            metadata, support, interval = canonical_line(body, ignored_metadata)
            groups[metadata, support].append(interval)
    unions = {}
    for key, spans in groups.items():
        merged = []
        for lo, hi in sorted(spans):
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
            else:
                merged.append((lo, hi))
        unions[key] = tuple(merged)
    return unions


def without_models(body):
    result = dict(body)
    result["attrs"] = {k: v for k, v in body.get("attrs", {}).items() if k not in MODEL_KEYS}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--plan", type=Path, action="append", default=[])
    ap.add_argument("--stage", required=True)
    ap.add_argument("--allow-exact-line-reserialization", action="store_true")
    ap.add_argument("--reviewed-line-change", type=Path)
    ap.add_argument("--allow-missing-transform-preview", action="store_true", help="Temporary mesh-default measurement only; never final readiness")
    ap.add_argument("--require-final-412", action="store_true", help="Require exactly all437 minus6DNP minus19bareTP, with complete explicit transforms and final plans")
    args = ap.parse_args()
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,70}", args.stage)
    source = args.source.resolve()
    assert source.is_relative_to(ROOT.resolve()), "Source outside STM32H747 board scope"
    assert sha(BASELINE) == BASE_SHA, "Frozen baseline has changed"
    before, bh = parse(BASELINE)
    after, ah = parse(source)
    br, ba = refs(before)
    ar, aa = refs(after)
    inventory = json.loads((HERE / "components-437.json").read_text(encoding="utf-8"))
    excluded = {p["ref"] for p in inventory if p["dnp"] or p["ref"].startswith("TP")}
    errors, display_changes, component_changes, allowed_empty_net_additions = [], [], [], []
    if br != ar or len(ar) != 437:
        errors.append({"code": "component_membership_or_ids_changed", "before": len(br), "after": len(ar)})
    changed = [k for k in before.keys() & after.keys() if before[k] != after[k]]
    added = after.keys() - before.keys()
    deleted = before.keys() - after.keys()
    cid_ref = {cid: ref for ref, cid in br.items()}
    for key in changed:
        kind, rid = key
        old, new = before[key], after[key]
        if kind == "COMPONENT":
            ref = cid_ref.get(rid)
            if without_models(old) != without_models(new):
                errors.append({"code": "component_non3d_body_changed", "ref": ref, "id": rid})
            delta = [k for k in old.get("attrs", {}).keys() | new.get("attrs", {}).keys() if old.get("attrs", {}).get(k) != new.get("attrs", {}).get(k)]
            if not set(delta) <= MODEL_KEYS:
                errors.append({"code": "component_non3d_attrs_changed", "ref": ref, "keys": delta})
            component_changes.append({"ref": ref, "id": rid, "changed_keys": sorted(delta),
                                      "before": {k: old.get("attrs", {}).get(k) for k in MODEL_KEYS},
                                      "after": {k: new.get("attrs", {}).get(k) for k in MODEL_KEYS}})
        elif kind == "DOCHEAD":
            fields = {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}
            if fields <= {"client", "updateTime", "version"} and old.get("uuid") == "0ac2a19168000d8e" and new.get("uuid") == old.get("uuid") and old.get("docType") == new.get("docType") == "PCB":
                display_changes.append({"record": key, "fields": sorted(fields), "before": old, "after": new})
            else:
                errors.append({"code": "dochead_identity_or_other_fields_changed", "record": key, "before": old, "after": new})
        elif kind == "ACTIVE_LAYER" and set(old) == set(new) == {"layerId"}:
            layer_id = str(["LAYER", new["layerId"]]).replace("'", '"').replace(" ", "")
            if ("LAYER", layer_id) not in after:
                errors.append({"code": "active_layer_selects_missing_layer", "after": new})
            display_changes.append({"record": key, "before": old, "after": new, "classification": "editor selection only; LAYER bodies separately checked"})
        elif kind != "LINE":
            errors.append({"code": "non_model_record_body_changed", "record": key, "before": old, "after": new})
    for key in sorted(added):
        if key[0] == "NET" and key[1] == '["NET",""]' and after[key] == EMPTY_NET_BODY:
            allowed_empty_net_additions.append({"record": key, "body": after[key]})
        elif key[0] != "LINE":
            errors.append({"code": "unexpected_record_addition", "record": key, "body": after[key]})
    for key in sorted(deleted):
        if key[0] != "LINE":
            errors.append({"code": "unexpected_record_deletion", "record": key, "body": before[key]})
    lines_changed = any(k[0] == "LINE" for k in added | deleted | set(changed))
    old_union, new_union = line_unions(before), line_unions(after)
    union_differences = []
    for key in old_union.keys() | new_union.keys():
        if old_union.get(key) != new_union.get(key):
            union_differences.append({"metadata": json.loads(key[0]), "exact_infinite_line_support": key[1],
                                      "before_intervals": [[str(a), str(b)] for a, b in old_union.get(key, [])],
                                      "after_intervals": [[str(a), str(b)] for a, b in new_union.get(key, [])]})
    physical_old, physical_new = line_unions(before, {"zIndex"}), line_unions(after, {"zIndex"})
    physical_union_exact = physical_old == physical_new
    line_delta = {
        "added_lines": [{"record": list(k), "body": after[k]} for k in sorted(added) if k[0] == "LINE"],
        "deleted_lines": [{"record": list(k), "body": before[k]} for k in sorted(deleted) if k[0] == "LINE"],
        "changed_line_bodies": [{"record": list(k), "before": before[k], "after": after[k]} for k in sorted(changed) if k[0] == "LINE"],
    }
    reviewed = {"verified": False}
    if args.reviewed_line_change:
        review_path = args.reviewed_line_change.resolve()
        assert review_path.is_relative_to(OUT.resolve()), "Reviewed case must be in this 3D evidence folder"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review_ok = (review.get("baseline_sha256") == BASE_SHA and review.get("allowed_omitted_metadata_fields") == ["zIndex"]
                     and review.get("exact_geometry_and_non_display_metadata_union_preserved") is True
                     and review.get("line_delta") == line_delta and physical_union_exact
                     and all(r["body"].get("zIndex") == -1 for r in line_delta["added_lines"]))
        reviewed = {"verified": review_ok, "path": str(review_path.relative_to(ROOT)), "sha256": sha(review_path),
                    "scope": "Only the exact frozen old/new LINE IDs and bodies; only zIndex may differ in the exact union grouping. No tolerance."}
        if not review_ok:
            errors.append({"code": "reviewed_exact_line_case_does_not_match_current_delta"})
    if not physical_union_exact:
        errors.append({"code": "exact_line_geometry_or_non_display_metadata_union_changed", "all_metadata_differences": union_differences})
    elif union_differences and not reviewed["verified"]:
        errors.append({"code": "line_zindex_union_changed_requires_exact_frozen_review", "differences": union_differences})
    if lines_changed and not (args.allow_exact_line_reserialization or reviewed["verified"]):
        errors.append({"code": "strict_record_preservation_failed_line_reserialization_requires_explicit_review",
                       "message": "Even if the exact union matches, old LINE IDs/bodies were not preserved. Original diff is retained."})
    applied = {ref: after["COMPONENT", cid].get("attrs", {}) for ref, cid in ar.items() if after["COMPONENT", cid].get("attrs", {}).get("3D Model")}
    missing_transform_preview_refs = []
    for ref, a in applied.items():
        if ref in excluded:
            errors.append({"code": "dnp_or_bare_test_point_has_3d_body", "ref": ref})
        required = MODEL_KEYS - {"3D Model Transform"} if args.allow_missing_transform_preview else MODEL_KEYS
        if not all(isinstance(a.get(k), str) and a.get(k) for k in required):
            errors.append({"code": "incomplete_3d_model_metadata", "ref": ref})
        if args.allow_missing_transform_preview and not a.get("3D Model Transform"):
            missing_transform_preview_refs.append(ref)
            continue
        try:
            values = [float(v) for v in a["3D Model Transform"].split(",")]
            if len(values) != 9 or not all(math.isfinite(v) for v in values) or not all(v > 0 for v in values[:3]):
                raise ValueError()
        except (KeyError, ValueError):
            errors.append({"code": "invalid_model_transform", "ref": ref})
    expected = {}
    plans = []
    for path in args.plan:
        path = path.resolve()
        assert path.is_relative_to(ROOT.resolve()), "Plan outside STM32 scope"
        plan = json.loads(path.read_text(encoding="utf-8-sig"))
        entries = plan["entries"] if isinstance(plan, dict) else plan
        plans.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path), "entries": len(entries)})
        for e in entries:
            if e["ref"] in expected and any(expected[e["ref"]].get(k) != e.get(k) for k in ["model", "title", "transform", "id", "footprintUuid"]):
                errors.append({"code": "conflicting_duplicate_plan_entry", "ref": e["ref"]})
            expected[e["ref"]] = e
    if args.require_final_412:
        fitted = {p["ref"] for p in inventory} - excluded
        if args.allow_missing_transform_preview:
            errors.append({"code": "final412_cannot_use_missing_transform_preview"})
        if len(fitted) != 412 or set(applied) != fitted:
            errors.append({"code": "final412_fitted_body_refset_mismatch", "target_count": len(fitted), "actual_count": len(applied),
                           "missing": sorted(fitted-set(applied)), "extra": sorted(set(applied)-fitted)})
        if not plans or set(expected) != fitted:
            errors.append({"code": "final412_plan_refset_mismatch", "target_count": len(fitted), "plan_count": len(expected),
                           "missing": sorted(fitted-set(expected)), "extra": sorted(set(expected)-fitted)})
        if any(e.get("executable") is False for e in expected.values()):
            errors.append({"code": "final412_plan_has_explicit_nonexecutable_candidate"})
    if plans:
        if set(applied) != set(expected):
            errors.append({"code": "applied_model_ref_set_differs_from_plans", "missing": sorted(set(expected) - set(applied)), "extra": sorted(set(applied) - set(expected))})
        for ref, e in expected.items():
            if ref in excluded:
                errors.append({"code": "plan_contains_dnp_or_test_point", "ref": ref})
            if ar.get(ref) != e.get("id", ar.get(ref)):
                errors.append({"code": "plan_component_id_mismatch", "ref": ref})
            if ref in applied:
                got = applied[ref]
                for pk, ak in [("model", "3D Model"), ("title", "3D Model Title"), ("transform", "3D Model Transform")]:
                    if e.get(pk) != got.get(ak):
                        errors.append({"code": "model_binding_differs_from_plan", "ref": ref, "field": ak, "expected": e.get(pk), "actual": got.get(ak)})
                if e.get("footprintUuid", ba[ar[ref]].get("Footprint")) != aa[ar[ref]].get("Footprint"):
                    errors.append({"code": "plan_footprint_uuid_mismatch", "ref": ref})
    header_changed = [k for k in bh.keys() & ah.keys() if bh[k] != ah[k]]
    protected = {}
    for typ in sorted({k[0] for k in before} | {k[0] for k in after}):
        a, b = {k: v for k, v in before.items() if k[0] == typ}, {k: v for k, v in after.items() if k[0] == typ}
        protected[typ] = {"before_records": len(a), "after_records": len(b), "exact_body_and_id_match": a == b}
    report = {"schema": "stm32-pcb-3d-metadata-preservation-audit-v1", "passed": not errors,
              "baseline": {"path": str(BASELINE.relative_to(ROOT)), "sha256": sha(BASELINE)},
              "source": {"path": str(source.relative_to(ROOT)), "sha256": sha(source)}, "plans": plans,
              "native_calls": 0, "strict_model_plus_display_metadata_only": not lines_changed and not errors,
              "final_all412_required": args.require_final_412,
              "temporary_default_mesh_measurement_preview": args.allow_missing_transform_preview,
              "missing_transform_preview_refs": sorted(missing_transform_preview_refs),
              "eligible_for_final_audit": not args.allow_missing_transform_preview and not missing_transform_preview_refs,
              "line_records_reserialized": lines_changed, "exact_line_reserialization_explicitly_accepted": args.allow_exact_line_reserialization,
              "exact_all_line_geometry_and_metadata_union_preserved": not union_differences,
              "exact_line_geometry_and_non_display_metadata_union_preserved": physical_union_exact,
              "reviewed_line_zindex_reserialization": reviewed,
              "line_proof_method": "Fraction(str(native decimal)) rational arithmetic; normalized exact infinite-line support and closed-interval union grouped by ALL non-coordinate LINE body fields. No tolerance or coordinate rounding.",
              "changed_component_count": len(component_changes), "applied_model_count": len(applied), "excluded_refs": sorted(excluded),
              "applied_refs": sorted(applied), "display_only_changes": display_changes,
              "allowed_exact_empty_default_NET_additions": allowed_empty_net_additions,
              "changed_components": sorted(component_changes, key=lambda x: x["ref"] or ""), "record_type_comparison": protected,
              **line_delta,
              "header_identity_ticket_changes": {"count": len(header_changed), "by_record_type": dict(Counter(k[0] for k in header_changed)),
                                                 "note": "Headers are native serialization/ticket metadata; geometric and electrical bodies audited separately."},
              "errors": errors, "limitations": ["Geometry preservation is not a new DRC/CAM or model-fit approval.", "3D mesh correctness, body height, polarity and final visual fit remain separate checks.", "If LINE records are reserialized, strict old record equality is FALSE even when exact physical centerline union preservation is proved."]}
    audit_dir = OUT / "audits"
    audit_dir.mkdir(exist_ok=True)
    target = audit_dir / ("model-metadata-" + args.stage + ".json")
    assert not target.exists(), "Use a new stage rather than overwrite an audit"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(target.relative_to(ROOT)), "sha256": sha(target),
                      "models": len(applied), "changed_components": len(component_changes), "line_reserialization": lines_changed,
                      "all_metadata_line_union_preserved": not union_differences, "physical_line_union_exact": physical_union_exact,
                      "frozen_line_zindex_review_verified": reviewed["verified"], "added_lines": len(report["added_lines"]),
                      "deleted_lines": len(report["deleted_lines"]), "display_changes": len(display_changes),
                      "errors": errors[:3]}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
