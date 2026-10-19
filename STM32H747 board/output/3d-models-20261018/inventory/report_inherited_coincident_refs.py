"""Record pre-existing coincident resistor refs; no layout/DRC changes."""
from collections import defaultdict
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
M = runpy.run_path(str(HERE / "audit_model_metadata.py"))
rows, _ = M["parse"](M["BASELINE"])
refids, attrs = M["refs"](rows)
inventory = {p["ref"]: p for p in json.loads((HERE / "components-437.json").read_text(encoding="utf-8"))}
pairs = [("R78", "R93"), ("R79", "R92"), ("R80", "R87"), ("R81", "R84"), ("R82", "R83")]
pin_nets = defaultdict(dict)
rev = {refids[r]: r for pair in pairs for r in pair}
for (kind, rid), b in rows.items():
    if kind == "PAD_NET":
        _, cid, number, pad_id = json.loads(rid)
        if cid in rev:
            pin_nets[rev[cid]][number] = b.get("padNet")
groups = []
for pair in pairs:
    pp = [inventory[r] for r in pair]
    assert pp[0]["side"] == pp[1]["side"] == "top"
    assert pp[0]["x_mm"] == pp[1]["x_mm"] and pp[0]["y_mm"] == pp[1]["y_mm"]
    assert not any(p["dnp"] for p in pp)
    groups.append({"refs": pair, "identical_component_origin_xy_mm": [pp[0]["x_mm"], pp[0]["y_mm"]],
                   "side": "top", "both_dnp_false": True,
                   "parts": [{"ref": p["ref"], "component_id": p["component_id"], "value": p["value"],
                              "footprint_uuid": p["footprint_uuid"], "component_rotation_deg": p["rotation_deg"],
                              "local_pin_centers_mm": p["orientation_hints"]["pin_centers_mm"], "pad_nets": pin_nets[p["ref"]]} for p in pp]})
report = {"schema": "stm32-frozen-baseline-coincident-resistor-refs-v1",
          "baseline": {"path": str(M["BASELINE"].relative_to(M["ROOT"])), "sha256": M["sha"](M["BASELINE"])},
          "coincident_group_count": len(groups), "groups": groups,
          "introduced_by_3d_assignment": False,
          "interpretation": "Five pairs of different fitted resistor refs have the same frozen PCB component origin and opposite terminal numbering. Their terminal nets differ. Their 3D meshes therefore coincide; source-level electrical/assembly intent needs a separate review before fabrication.",
          "limits": ["This diagnostic records frozen source facts; it does not change any placement, net, DNP or 3D model binding.",
                     "No new native DRC was run and the historical strict DRC0 result is not reclassified or invalidated by this read-only report.",
                     "The unlabelled OBJ contains two instances at each shared location; individual identical mesh refs cannot be distinguished from OBJ alone."]}
target = OUT / "audits/inherited-coincident-resistors.json"
assert not target.exists()
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"path": str(target), "groups": len(groups), "baseline_sha256": report["baseline"]["sha256"]}))
