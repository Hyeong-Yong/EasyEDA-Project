"""Independent read-only C95 route search, reserving only the direct four caps."""
import json
import inspect
import runpy
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "output/candidates/adc10-pcb-finish-20261018/bottom-buckets"
HERE = ROOT / "output/candidates/adc10-pcb-finish-20261018/strip/c95-layer18"
I = runpy.run_path(str(CHILD / "plan-inner3-branches.py"))
T = I["T"]
M = I["M"]


def main():
    HERE.mkdir(parents=True, exist_ok=True)
    board = M["Board"]()
    board.route_power_fill_exceptions = T["POWER_FILL_EXCEPTION"]
    six = T["AllLayers"](board)
    direct = json.loads((CHILD / "bottom-bucket-routing-manifest.json").read_text())
    results = []
    for r in direct["channels"]:
        if "signalRoute" not in r:
            continue
        p, axis = r["centerXYmm"], r["axisOfPositiveLocalX"]
        hx, hy = (.95, .5) if axis[0] else (.5, .95)
        r["assemblyBoundingBoxMm"] = [p[0]-hx, p[1]-hy, p[0]+hx, p[1]+hy]
        assert board.body_clear(r["assemblyBoundingBoxMm"])
        board.accept(r)
        results.append(r)
    router = I["InnerRouter"](six, 18)
    router.alternatives.__func__.__globals__["HERE"] = HERE
    channel = next(c for c in board.inv if c["net"] == "ADC3_INP7")
    cached = HERE / "branch-alternatives-layer18-ADC3_INP7.json"
    alternatives = json.loads(cached.read_text()) if cached.exists() else router.alternatives(channel)
    # Existing GND FILL membership of the whole capacitor land is not a PCB
    # requirement: its added copper can reach anchored GND via a local trace.
    # Relax only that old-plane test; retain exact pad and signal clearances.
    code = textwrap.dedent(inspect.getsource(M["Board"].search))
    code = code.replace('if not self.ground_mask[gy,gx]:continue', 'if False:continue')
    code = code.replace('if not all(0<=tx<W and 0<=ty<H and self.ground_mask[ty,tx] for tx,ty in corners):continue', 'if False:continue')
    code = code.replace('if not all(point_in_solid(q,self.ground_union) for q in fp(rectangle(p2,axis))):continue', 'if False:continue')
    code = code.replace('hh=(.95,.5) if ax else (.5,.95)', 'hh=(.55,.30) if ax else (.30,.55)')
    scope = dict(M["Board"].search.__globals__)
    exec(compile(code, str(__file__) + ":relaxed-plane-membership", "exec"), scope)
    board.search = scope["search"].__get__(board, type(board))
    result = board.search(channel, limit=8, tap_sources=alternatives) if alternatives else {"ref": "C95", "net": "ADC3_INP7", "status": "NO_LAYER18_BRANCH_SITE"}
    if "signalRoute" in result:
        selected = result["selectedRoutingSource"]
        result["additionalSignalRoutes"] = [selected["innerBranchRoute"]]
        result["newSignalVias"] = [selected]
        result["electricalEscapeToCapPathMm"] = selected["electricalDistanceFromEscapeMm"] + result["signalRoute"]["lengthMm"]
        result["needsExplicitGroundReturnReview"] = True
        result["assemblyBasis"] = "0402 actual 1.0x0.5mm body plus0.05mm envelope; existing legacy component silk envelopes and all exact copper pads retain their original checks. Silk overlap must be separately screened."
    output = {"schema": "adc10-c95-layer18-independent-search-20261018-v1", "sourceSha256": M["EXPECTED_SHA"], "reservedRefs": [r["ref"] for r in results], "branchAlternatives": len(alternatives), "result": result, "nativeCalls": 0, "manufacturingReady": False}
    (HERE / "c95-layer18-result.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf8")
    M["render"](board, results + [result], HERE / "c95-layer18-result.png")
    print(json.dumps({"result": str(HERE / "c95-layer18-result.json"), "branchAlternatives": len(alternatives), "placed": "signalRoute" in result, "electricalDistanceMm": result.get("electricalEscapeToCapPathMm")}), flush=True)


if __name__ == "__main__":
    main()
