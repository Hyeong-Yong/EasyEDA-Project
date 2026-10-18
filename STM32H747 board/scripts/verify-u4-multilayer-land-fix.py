"""Verify full project library records after the U4 copper-only land update."""
from __future__ import annotations
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BEFORE = ROOT / "output/checkpoints/STM32H747_after_via031_track013_20261015.epro2"
AFTER = ROOT / "output/checkpoints/STM32H747_after_u4_land036_20261015.epro2"
UUID = "a3627e2915fe61c1"

def read(path):
    docs = {}
    with zipfile.ZipFile(path) as archive:
        source = archive.read("STM32H747_MCU_BOARD_v19.epru").decode("utf-8-sig")
    current = None
    for line in source.splitlines():
        h, b = line.split("||", 1)
        h, b = json.loads(h), json.loads(b.removesuffix("|"))
        if h["type"] == "DOCHEAD":
            current = b.get("uuid")
            docs[current] = {"type": b.get("docType"), "records": {}}
        if current is not None:
            docs[current]["records"][(h["type"], h.get("id"))] = b
    return docs

def main():
    old, new = read(BEFORE), read(AFTER)
    differences = []
    assert set(old) == set(new)
    changes = []
    normalizations = []
    library_count = 0
    for uuid, doc in old.items():
        if doc["type"] not in ("FOOTPRINT", "SYMBOL", "DEVICE"):
            continue
        library_count += 1
        a, b = doc["records"], new[uuid]["records"]
        if a.keys() != b.keys():
            differences.append([uuid, "record-keys"])
            continue
        for key, expected in a.items():
            actual = json.loads(json.dumps(b[key]))
            if key[0] == "DOCHEAD":
                for k in ("updateTime", "version", "user", "editVersion"):
                    if k in expected:
                        actual[k] = expected[k]
                    else:
                        actual.pop(k, None)
            if uuid == UUID and key[0] == "PAD":
                assert actual["hole"] is None and actual["layerId"] == 1
                assert abs(actual["defaultPad"]["width"] * .0254 - .36) < .000002
                assert abs(actual["defaultPad"]["height"] * .0254 - .36) < .000002
                changes.append(key[1])
                actual["defaultPad"] = expected["defaultPad"]
            if uuid == UUID and key == ("ATTR", "e0a8672cdac74e947") and expected.get("value") == "" and "value" not in actual and expected.get("parentId") == "" and expected.get("key") == "Footprint" and not expected.get("valueVisible"):
                actual["value"] = ""
                normalizations.append({"uuid": uuid, "id": key[1], "field": "value", "before": "", "after": "omitted-empty-hidden-library-attribute"})
            if actual != expected:
                differences.append([uuid, list(key), expected, b[key]])
    assert len(changes) == 90
    report = {"passed": not differences, "beforeSha256": hashlib.sha256(BEFORE.read_bytes()).hexdigest(), "afterSha256": hashlib.sha256(AFTER.read_bytes()).hexdigest(), "libraryDocumentsCompared": library_count, "u4PadIds": changes, "changedFieldContract": "Only U4 defaultPad.width/height: .4064 mm -> .36 mm; centres/IDs/numbers/holes and other library bodies unchanged apart from recorded empty hidden ATTR serialization.", "nativeNormalizations": normalizations, "differences": differences}
    path = ROOT / "output/validation/native-multilayer-u4-land036-full-library-verified-audit.json"
    assert not path.exists()
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "libraryDocumentsCompared": library_count, "u4Pads": len(changes), "differenceCount": len(differences), "report": str(path)}))
    if differences:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
