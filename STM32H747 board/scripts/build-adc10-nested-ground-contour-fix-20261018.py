"""Remove one independently identified nested clearance contour, offline only."""
import copy
import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = runpy.run_path(str(ROOT / "scripts/build-adc10-strip-operations-20261018.py"))
G = M["G"]
SOURCE = ROOT / "output/validation/native-adc10-pcb-ref_courtyard-20261018.epru"
OUTPUT = M["HERE"] / "adc10-nested-ground-contour-fix-20261018.json"


def main():
    assert M["sha"](SOURCE) == "5a7aa8d85268aac8c31347c53b1f236ea521b1d94dc2899157037839bf832668"
    rows = G["PARSE"](SOURCE)
    body = rows["FILL", "e680230ef8d2c5dd"]
    paths = body["path"]
    assert len(paths) == 222
    outer_hole = M["positive"](M["ip"](G["ring_path"](paths[220])))
    inner_hole = M["positive"](M["ip"](G["ring_path"](paths[221])))
    inside = M["intersection"]([outer_hole], [inner_hole])
    area = M["area"]([inner_hole])
    assert abs(M["area"](inside) - area) < 1e-7
    after = copy.deepcopy(paths[:221])
    assert all(p[:2] == p[-2:] for p in after)
    assert after == paths[:-1]
    update = {
        "id": "e680230ef8d2c5dd", "type": "FILL",
        "sourceBodyBefore": body, "beforeBodySha256": M["digest"](body),
        "beforePathSha256": M["digest"](paths), "afterPath": after,
        "afterPathSha256": M["digest"](after), "allowedChangedFields": ["path"],
        "outerPathExact": True, "retainedContourArraysExact": 221,
        "removedContourIndex": 221, "containingContourIndex": 220,
    }
    report = {
        "schema": "adc10-bounded-nested-ground-contour-fix-20261018-v1",
        "status": "READY_FOR_SINGLE_FILL_PUBLIC_API_REVIEW",
        "sourcePath": str(SOURCE), "sourceSha256": M["sha"](SOURCE),
        "liveCalls": 0, "wholePCBSetSource": False,
        "fillPathUpdates": [update],
        "proof": {
            "nestedContourFullyContained": True,
            "removedContourAreaMm2": area,
            "removedContourBoundsMm": list(M["bounds"]([inner_hole])),
            "allOtherContourArraysExact": True,
            "allAPIContoursExplicitlyClosed": True,
            "outerMinusUnionHoleSemanticsCopperDifferenceMm2": 0,
            "evenOddSemanticsMaximumCopperRemovedMm2": area,
            "noCopperAddedUnderEitherUnionHolesOrEvenOddSemantics": True,
            "nativeSemanticsNotAssumed": True,
            "reason": "Drop only one nested same-orientation contour. Under outer-minus-hole-union it is redundant; under even-odd it removes a tiny island. No copper is added under either interpretation.",
        },
        "protectedContract": {
            "allOtherRecordBodiesExact": True, "rulesUnchanged": 18,
            "componentsUnchanged": 354, "originalViaBodiesUnchanged": 634,
            "mountingPadsUnchanged": 4, "allNonTargetFillsExact": True,
            "allLinesArcsPolysStringsNetsPinMapsExact": True,
        },
        "nativeAfterApplyRequired": ["full strict unchanged-rule DRC", "literal GND copper-to-existing-via connectivity proof", "focused exported copper/CAM review"],
        "manufacturingReady": False,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"manifest": str(OUTPUT), "sha256": M["sha"](OUTPUT), "removedIndex": 221, "retainedContoursExact": 221, "removedAreaMm2": area, "removedBoundsMm": report["proof"]["removedContourBoundsMm"]}))


if __name__ == "__main__":
    main()
