"""Read-only C95 TOP exterior alternative, retaining original MCU escapes."""
import inspect
import json
import math
import runpy
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "output/candidates/adc10-pcb-finish-20261018/bottom-buckets"
HERE = ROOT / "output/candidates/adc10-pcb-finish-20261018/strip/c95-layer18"
I = runpy.run_path(str(CHILD / "plan-inner3-branches.py"))
T, M = I["T"], I["M"]


def main():
    board = M["Board"]()
    six = T["AllLayers"](board)
    board.route_power_fill_exceptions = T["POWER_FILL_EXCEPTION"]
    board.obstacles = []
    for obj in six.obs:
        if 1 not in obj["layers"]:
            continue
        o = dict(obj)
        o["via"] = o["kind"] == "VIA"
        o["clear"] = M["offset"](o["paths"], M["CLR"] + M["MARGIN"])
        o["viaClear"] = M["offset"](o["paths"], .06 + M["MARGIN"]) if o["via"] else None
        board.obstacles.append(o)
    board.fills = [o for o in six.ground if 1 in o["layers"]]
    board.ground_union = M["union"]([p for o in board.fills for p in o["paths"]])
    board.ground_mask = M["raster"](board.ground_union).astype(bool)
    board.legacy_bottom_envelopes = []
    docs, _ = M["READ"](M["CHECKPOINT"])
    for (kind, cid), comp in board.rows.items():
        if kind != "COMPONENT" or comp["layerId"] != 1:
            continue
        points = []
        a = math.radians(comp["angle"])
        def world(x, y):
            x, y = x*M["MM"], y*M["MM"]
            return (comp["x"]*M["MM"] + x*math.cos(a) - y*math.sin(a), comp["y"]*M["MM"] + x*math.sin(a) + y*math.cos(a))
        for (pk, pid), (header, p) in docs["FOOTPRINT", board.attrs[cid]["Footprint"]].items():
            if pk not in ("LINE", "ARC") or p.get("layerId") not in (3, 9, 48):
                continue
            q, z = world(p["startX"], p["startY"]), world(p["endX"], p["endY"])
            pts = M["OLD"]["arc"](q, z, p["angle"]) if pk == "ARC" else [q, z]
            r = (p.get("width") or p.get("lineWidth") or 0)*M["MM"]/2
            for x, y in pts:
                points.extend([(x-r,y-r),(x+r,y+r)])
        if points and M["overlap"](M["bbox"](points), M["BOUNDS"], 1):
            board.legacy_bottom_envelopes.append({"ref": board.attrs[cid].get("Designator"), "bboxMm": M["bbox"](points), "basis": "Actual TOP silk/assembly/courtyard footprint outline; MCU package is prohibited"})
    # Power FILL is permitted to receive bounded pad/route clearance cutouts;
    # no narrow signal trace, signal FILL, via or component pad is exempted.
    code = textwrap.dedent(inspect.getsource(M["Board"].copper_obstacles))
    code = code.replace('if not pad and o["kind"]=="FILL"', 'if o["kind"]=="FILL"')
    scope = dict(M["Board"].copper_obstacles.__globals__)
    exec(compile(code, str(__file__) + ":pad-plane-cut-exception", "exec"), scope)
    board.copper_obstacles = scope["copper_obstacles"].__get__(board, type(board))
    code = textwrap.dedent(inspect.getsource(M["Board"].pad_hits))
    code = code.replace('for o in self.obstacles+self.new:', 'for o in self.obstacles+self.new:\n        if o["kind"]=="FILL" and o["net"] in self.route_power_fill_exceptions:continue')
    scope = dict(M["Board"].pad_hits.__globals__)
    exec(compile(code, str(__file__) + ":pad-plane-cut-exception", "exec"), scope)
    board.pad_hits = scope["pad_hits"].__get__(board, type(board))
    code = textwrap.dedent(inspect.getsource(M["Board"].search))
    code = code.replace('if not self.ground_mask[gy,gx]:continue', 'if False:continue')
    code = code.replace('if not all(0<=tx<W and 0<=ty<H and self.ground_mask[ty,tx] for tx,ty in corners):continue', 'if False:continue')
    code = code.replace('if not all(point_in_solid(q,self.ground_union) for q in fp(rectangle(p2,axis))):continue', 'if False:continue')
    scope = dict(M["Board"].search.__globals__)
    exec(compile(code, str(__file__) + ":ground-return-required", "exec"), scope)
    board.search = scope["search"].__get__(board, type(board))
    channel = next(c for c in board.inv if c["net"] == "ADC3_INP7")
    alternatives = json.loads((HERE / "branch-alternatives-layer18-ADC3_INP7.json").read_text())
    probes = []
    for center in [(52.8,77.3),(54,77.3),(55.2,77.3),(53.4,78.1),(54.6,78.1),(57.8,78.5)]:
        for axis in [(1,0),(-1,0),(0,1),(0,-1)]:
            p1 = [center[0]+.48*axis[0],center[1]+.48*axis[1]]
            p2 = [center[0]-.48*axis[0],center[1]-.48*axis[1]]
            hx,hy=(.95,.5) if axis[0] else (.5,.95)
            probes.append({"center":center,"axis":axis,"signalPadHits":board.pad_hits(p1,axis,channel["net"]),"groundPadHits":board.pad_hits(p2,axis,"GND"),"bodyClear":board.body_clear([center[0]-hx,center[1]-hy,center[0]+hx,center[1]+hy]),"directRouteHitsFromSouthTap":board.route_hits([[52.8,78.32],p1],channel["net"])})
    (HERE / "c95-top-probes.json").write_text(json.dumps(probes,indent=2)+"\n",encoding="utf8")
    # TOP-only search uses the exact same checked route/pad geometry, changing
    # only its physical layer and corresponding obstacle/envelope inventory.
    selected = next(a for a in alternatives if math.dist(a["xyMm"], [52.8,78.32]) < 1e-7)
    axis = (-1,0)
    center = [54.0,77.3]
    p1,p2 = [53.52,77.3],[54.48,77.3]
    route = [selected["xyMm"],p1]
    assert six.viable(selected["xyMm"], channel["net"])
    assert not board.pad_hits(p1,axis,channel["net"])
    assert not board.pad_hits(p2,axis,"GND")
    assert not board.route_hits(route,channel["net"])
    box = [center[0]-.95,center[1]-.5,center[0]+.95,center[1]+.5]
    assert board.body_clear(box)
    land = [M["rectangle"](p2,axis)]
    ground_contact = M["inter"](land,board.ground_union)
    contact_area = sum(M["pc"].Area(p) for p in ground_contact)/M["SCALE"]**2
    assert contact_area > .08
    ground_nodes = M["diff"](board.ground_union,[],True).Childs
    def contains(node,p):
        q=(round(p[0]*M["SCALE"]),round(p[1]*M["SCALE"]))
        return M["pc"].PointInPolygon(q,node.Contour)!=0 and not any(M["pc"].PointInPolygon(q,c.Contour)!=0 for c in node.Childs if c.IsHole)
    gnd_nodes = [n for n in ground_nodes if contains(n,p2)]
    anchored = sorted({vid for vid,net,p,rad in board.vias if net=="GND" and any(contains(n,p) for n in gnd_nodes)})
    ground_route = None
    if not anchored:
        signal_copper = M["capsule"](route,M["WIDTH"]/2) + [M["rectangle"](p1,axis)] + [M["circle"](selected["xyMm"],selected["diameterMm"]/2)]
        for vid,net,p,rad in sorted(board.vias,key=lambda v:math.dist(p2,v[2])):
            if net != "GND" or math.dist(p2,p)>4:
                continue
            copper = M["capsule"]([p2,p],.15)
            if M["inter"](copper,M["offset"](signal_copper,M["CLR"]+M["MARGIN"])):
                continue
            bad = False
            for o in board.obstacles:
                if o["net"] == "GND" or o["kind"]=="FILL" and o["net"] in board.route_power_fill_exceptions:
                    continue
                if M["inter"](copper,o["clear"]):
                    bad=True
                    break
            if not bad:
                ground_route={"layerId":1,"net":"GND","widthMm":.30,"pointsMm":[p2,p],"lengthMm":math.dist(p2,p),"existingGroundViaId":vid}
                anchored=[vid]
                break
    assert anchored, "No literal source-plane or short GND-via return"
    own_ground_clearance = M["offset"](land,M["CLR"]+M["WIDTH"]/2+M["MARGIN"])
    assert not M["inter"](M["capsule"](route,M["WIDTH"]/2),own_ground_clearance)
    result = {"ref":"C95","net":channel["net"],"componentId":board.refs["C95"],"escapeViaId":channel["nearestAdcEscapeVia"]["id"],"escapeXYmm":channel["nearestAdcEscapeVia"]["xyMm"],"selectedRoutingSource":selected,"requiredWorldPads":{"1":{"net":channel["net"],"xyMm":p1},"2":{"net":"GND","xyMm":p2}},"centerXYmm":center,"axisOfPositiveLocalX":axis,"targetLayer":"TOP","signalRoute":{"layerId":1,"widthMm":M["WIDTH"],"pointsMm":route,"lengthMm":math.dist(*route)},"assemblyBoundingBoxMm":box,"nativeRotationDegrees":180,"offlineExactProof":{"allSixLayerViaClearOfUnmodifiedSignalCopperAndOriginalDrills":True,"powerAndGndPlaneLocalAntipadsStillRequired":True,"bothCapPadsClearOfOtherNetCopper":True,"straightSignalRouteClearOfOtherNetCopper":True,"signalRouteClearOfOwnGroundLand":True,"actualTopEnvelopeScreenPassed":True,"groundPadSourceGroundContactAreaMm2":contact_area,"literalSameTopGroundIslandViaIds":anchored,"sourceGroundRegionLocallyOutsideAllPriorStripEdits":True}}
    if ground_route:
        result["groundRoute"]=ground_route
    if "signalRoute" in result:
        result["targetLayer"] = "TOP"
        result["signalRoute"]["layerId"] = 1
        selected = result["selectedRoutingSource"]
        result["additionalSignalRoutes"] = [selected["innerBranchRoute"]]
        result["newSignalVias"] = [selected]
        result["electricalEscapeToCapPathMm"] = selected["electricalDistanceFromEscapeMm"] + result["signalRoute"]["lengthMm"]
        result["needsFinalCutAndGroundProof"] = True
    output = {"schema": "adc10-c95-top-exterior-independent-20261018-v1", "sourceSha256": M["EXPECTED_SHA"], "topEnvelopeInventory": board.legacy_bottom_envelopes, "result": result, "nativeCalls": 0, "manufacturingReady": False}
    (HERE / "c95-top-exterior-result.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf8")
    M["render"](board, [result], HERE / "c95-top-exterior-result.png")
    print(json.dumps({"file": str(HERE / "c95-top-exterior-result.json"), "placed": "signalRoute" in result, "center": result.get("centerXYmm"), "electricalLengthMm": result.get("electricalEscapeToCapPathMm")}), flush=True)


if __name__ == "__main__":
    main()
