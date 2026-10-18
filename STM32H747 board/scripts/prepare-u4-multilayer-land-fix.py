"""Prepare a full, checkpoint-backed U4 footprint with 90 smaller copper lands."""

from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_after_via031_track013_20261015.epro2"
OUTPUT = ROOT / "output/candidates/multilayer-route-clearance"
UUID = "a3627e2915fe61c1"


def main() -> None:
    with zipfile.ZipFile(CHECKPOINT) as archive:
        source = archive.read("STM32H747_MCU_BOARD_v19.epru").decode("utf-8-sig")
    selected = False
    records = []
    for line in source.splitlines():
        head, body = line.split("||", 1)
        head, body = json.loads(head), json.loads(body.removesuffix("|"))
        if head["type"] == "DOCHEAD":
            selected = body.get("uuid") == UUID and body.get("docType") == "FOOTPRINT"
        if selected:
            records.append((head, body))
    assert len(records) == 121
    before = copy.deepcopy(records)
    pads = [record for record in records if record[0]["type"] == "PAD"]
    assert len(pads) == 90
    assert len({body["num"] for _, body in pads}) == 90
    changes = []
    for head, body in pads:
        assert body["layerId"] == 1 and body["hole"] is None
        assert body["defaultPad"] == {"padType": "ELLIPSE", "width": 16, "height": 16}
        assert not body["specialPad"] and not body["unusedInnerLayers"]
        original = copy.deepcopy(body)
        body["defaultPad"]["width"] = round(.36 / .0254, 6)
        body["defaultPad"]["height"] = round(.36 / .0254, 6)
        changes.append({"id": head["id"], "before": original, "after": copy.deepcopy(body)})
    for (head, body), (old_head, old_body) in zip(records, before):
        assert head == old_head
        normalized = copy.deepcopy(body)
        if head["type"] == "PAD":
            normalized["defaultPad"] = old_body["defaultPad"]
        assert normalized == old_body
    OUTPUT.mkdir(parents=True, exist_ok=True)
    def save_records(name, rows):
        data = "\n".join(json.dumps(h, separators=(",", ":"), ensure_ascii=False) + "||" + json.dumps(b, separators=(",", ":"), ensure_ascii=False) + "|" for h, b in rows) + "\n"
        path = OUTPUT / name
        assert not path.exists()
        path.write_text(data, encoding="utf-8", newline="\n")
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {
        "schema": "stm32h747-u4-multilayer-land-fix-v1", "status": "reviewed-candidate-not-applied",
        "checkpoint": {"path": str(CHECKPOINT), "sha256": hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest()},
        "footprintUuid": UUID, "componentId": "3de4fa6d5f5df65c", "padCount": 90,
        "before": save_records("u4-land036-before.epru", before),
        "candidate": save_records("u4-land036-candidate.epru", records),
        "recordCounts": dict(Counter(h["type"] for h, _ in records)),
        "changes": changes,
        "protected": "All record IDs, pad centres, numbers, binding IDs, holes, mask/paste expansions and all non-PAD records unchanged; only defaultPad.width/height 16 mil -> .36 mm.",
        "evidence": {"guide": "https://www.issi.com/WW/pdf/appnotes/dram/AN42S01.AN.pdf", "rule": "BGA land typically about 80% of nominal ball; this .36 mm candidate assumes .45 mm nominal ball. Requires native DRC plus assembly/PI/SI review before fabrication."},
    }
    path = OUTPUT / "u4-land036-plan.json"
    assert not path.exists()
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"manifest": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "candidate": manifest["candidate"], "counts": manifest["recordCounts"]}))


if __name__ == "__main__":
    main()
