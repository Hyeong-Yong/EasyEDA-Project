"""Inspect the native autoGenerateModels=false passive OBJ export read-only.

The OBJ has no per-reference o/g labels. This audit checks its 337 physical
three-material instances against the independent native metadata/placement plan.
It writes descriptive JSON only under the 3D evidence directory.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
ROOT = HERE.parents[2]


def bounds(points):
    return [min(p[i] for p in points) for i in range(3)] + [max(p[i] for p in points) for i in range(3)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--export", type=Path, required=True)
    ap.add_argument("--stage", required=True)
    args = ap.parse_args()
    assert re.fullmatch(r"[a-zA-Z0-9_-]{1,70}", args.stage)
    path = args.export.resolve()
    assert path.is_relative_to(ROOT.resolve())
    plan = json.loads((OUT / "passive-3d-apply-plan.json").read_text(encoding="utf-8"))
    inventory = {p["ref"]: p for p in json.loads((HERE / "components-437.json").read_text(encoding="utf-8"))}
    assert len(plan["entries"]) == 337
    expected = {}
    for e in plan["entries"]:
        p = inventory[e["ref"]]
        assert not p["dnp"] and not p["ref"].startswith("TP")
        tr = [float(v) for v in e["transform"].split(",")]
        ox, oy = tr[6] * .0254, tr[7] * .0254
        if p["side"] == "bottom":
            oy = -oy
        a = math.radians(p["rotation_deg"])
        center = [p["x_mm"] + ox * math.cos(a) - oy * math.sin(a), p["y_mm"] + ox * math.sin(a) + oy * math.cos(a)]
        # Passive shapes are symmetric under 180deg; bottom reflection changes
        # sign of the local angle but leaves their cardinal-axis extent intact.
        az = math.radians(p["rotation_deg"] + (-tr[3] if p["side"] == "bottom" else tr[3]))
        size = [v * .0254 for v in tr[:3]]
        worldsize = [abs(math.cos(az)) * size[0] + abs(math.sin(az)) * size[1],
                     abs(math.sin(az)) * size[0] + abs(math.cos(az)) * size[1], size[2]]
        expected[e["ref"]] = {"center": center, "size": worldsize, "side": p["side"], "family": e["family"],
                              "quarter_turn": round(math.degrees(az) / 90) % 2}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        objname = next(n for n in names if n.endswith(".obj"))
        mtlname = next(n for n in names if n.endswith(".mtl"))
        obj, mtl = z.read(objname).decode(), z.read(mtlname).decode()
    materials = {}
    current = None
    for line in mtl.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        if tokens[0] == "newmtl":
            current = tokens[1]
            materials[current] = {}
        elif current is not None and tokens[0] in ("Ka", "Kd", "Ks", "d"):
            materials[current][tokens[0]] = [float(v) for v in tokens[1:]]
    vertices = [None]
    blocks = []
    counts = Counter()
    for line in obj.splitlines():
        tokens = line.split()
        if not tokens:
            continue
        kind = tokens[0]
        counts[kind] += 1
        if kind == "v":
            vertices.append(tuple(float(v) for v in tokens[1:4]))
        elif kind == "usemtl":
            blocks.append({"material": tokens[1], "vertex_ids": set(), "faces": 0})
        elif kind == "f":
            assert blocks
            blocks[-1]["faces"] += 1
            for token in tokens[1:]:
                vi = int(token.split("/", 1)[0])
                blocks[-1]["vertex_ids"].add(vi if vi > 0 else len(vertices) + vi)
    for b in blocks:
        b["bbox_mm"] = bounds([vertices[i] for i in b["vertex_ids"]])
        b["vertices"] = len(b.pop("vertex_ids"))
    board = [b for b in blocks if b["bbox_mm"][3] - b["bbox_mm"][0] > 50 and b["bbox_mm"][4] - b["bbox_mm"][1] > 50]
    assert len(board) == 1
    bb = board[0]["bbox_mm"]
    modelblocks = [b for b in blocks if b is not board[0]]
    assert len(modelblocks) == 337 * 3
    matched, models, errors = set(), [], []
    for i in range(0, len(modelblocks), 3):
        group = modelblocks[i:i+3]
        bbox = [min(b["bbox_mm"][j] for b in group) for j in range(3)] + [max(b["bbox_mm"][j] for b in group) for j in range(3, 6)]
        center = [(bbox[j] + bbox[j + 3]) / 2 for j in range(3)]
        size = [bbox[j + 3] - bbox[j] for j in range(3)]
        candidates = sorted((math.dist(center[:2], e["center"]), ref) for ref, e in expected.items())
        dist = candidates[0][0]
        same_position_refs = sorted(ref for dd, ref in candidates if abs(dd - dist) < 1e-10)
        available = [ref for ref in same_position_refs if ref not in matched]
        if not available:
            errors.append({"too_many_instances_at_expected_location": same_position_refs, "group": i // 3})
        ref = available[0] if available else same_position_refs[0]
        matched.add(ref)
        e = expected[ref]
        size_error = [size[j] - e["size"][j] for j in range(3)]
        # The catalog transform uses a nominal model envelope, which need not
        # be the exact triangulated bounding box (e.g. R0402 H0.4 -> mesh H0.36).
        # Preserve and report those differences rather than silently rescaling.
        if dist > .005:
            errors.append({"mesh_does_not_match_expected_instance_center": ref, "center_error_mm": dist})
        if e["side"] == "top":
            correct_side = bbox[2] >= bb[5] - .005
        else:
            correct_side = bbox[5] <= bb[2] + .005
        if not correct_side:
            errors.append({"mesh_wrong_board_side": ref, "bbox": bbox, "board_bbox": bb})
        canonical_size = [size[1], size[0], size[2]] if e["quarter_turn"] else size
        models.append({"ref": ref, "ref_identity_candidates": same_position_refs,
                       "identity_note": "One-to-one deterministic allocation only; OBJ cannot distinguish coincident refs." if len(same_position_refs) > 1 else "Unique expected instance location.",
                       "family": e["family"], "side": e["side"], "bbox_mm": bbox, "size_mm": size,
                       "canonical_family_mesh_size_mm": canonical_size,
                       "center_mm": center, "center_error_xy_mm": dist, "size_error_mm": size_error,
                       "material_names": [b["material"] for b in group], "faces": sum(b["faces"] for b in group),
                       "placed_on_expected_board_side": correct_side})
    if matched != set(expected):
        errors.append({"ref_coverage_diff": {"missing": sorted(set(expected) - matched), "extra": sorted(matched - set(expected))}})
    positions = defaultdict(list)
    for ref, e in expected.items():
        positions[tuple(e["center"])].append(ref)
    coincident = [sorted(rr) for rr in positions.values() if len(rr) > 1]
    profiles = {}
    for family in {m["family"] for m in models}:
        mm = [m["canonical_family_mesh_size_mm"] for m in models if m["family"] == family]
        profiles[family] = {"count": len(mm), "minimum_xyz_mm": [min(v[i] for v in mm) for i in range(3)],
                            "maximum_xyz_mm": [max(v[i] for v in mm) for i in range(3)]}
    report = {"schema": "stm32-native-passive-obj-coverage-audit-v1", "passed": not errors,
              "export": {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "members": names},
              "native_export_option": {"autoGenerateModels": False, "evidence": "Root's recorded native export invocation; OBJ itself does not encode this option."},
              "obj": {"tokens": dict(counts), "object_group_labels_present": bool(counts["o"] or counts["g"]), "materials": materials,
                      "material_block_counts": dict(Counter(b["material"] for b in blocks)), "board_bbox_mm": bb},
              "model_instance_count": len(models), "ref_coverage_count": len(matched), "top_count": sum(m["side"] == "top" for m in models),
              "bottom_count": sum(m["side"] == "bottom" for m in models),
              "unique_expected_xy_positions": len(positions), "coincident_ref_groups_in_frozen_baseline": coincident,
              "individual_ref_identity_from_obj_alone_proved": not coincident,
              "catalog_nominal_size_is_not_exact_triangle_bbox": True,
              "actual_mesh_family_profiles": profiles,
              "max_center_error_xy_mm": max(m["center_error_xy_mm"] for m in models),
              "max_size_error_mm": max(abs(v) for m in models for v in m["size_error_mm"]),
              "families": dict(Counter(m["family"] for m in models)), "instances": sorted(models, key=lambda m: m["ref"]),
              "errors": errors, "limits": ["OBJ has no o/g ref labels or source-model UUIDs; matching combines spatial mesh instances with the independently audited native 337-model plan.",
                                            "337 consecutive three-material mesh instances plus one board block were verified, not inferred from the 437 footprint count.",
                                            "The .005mm numeric center matching gate detects wrong spatial assignment; it is unrelated to exact CAD copper preservation or manufacturing clearance. Actual triangle bboxes are reported separately from catalog nominal extents.",
                                            "Five coincident resistor pairs already exist in the frozen baseline. OBJ can prove two mesh instances at each shared location, not the individual ref identity of two identical overlapping meshes. The native metadata plan proves the intended ref bindings separately.",
                                            "No MPN body-height/lead/polarity/fit guarantee; native system models are package-equivalent visualizations."]}
    target = OUT / "audits" / ("obj-" + args.stage + ".json")
    assert not target.exists()
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "report": str(target.relative_to(ROOT)), "instances": len(models), "coverage": len(matched),
                      "top": report["top_count"], "bottom": report["bottom_count"], "max_center_error_mm": report["max_center_error_xy_mm"],
                      "max_size_error_mm": report["max_size_error_mm"], "board_bbox_mm": bb, "materials": len(materials), "errors": errors[:6]}))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
