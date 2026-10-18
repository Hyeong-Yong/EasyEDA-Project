"""Frozen remaining-six public-operation manifest on actual direct4 native PCB."""
import copy
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
T=runpy.run_path(str(HERE/"plan-tap-vias.py"));M=T["M"]
F=runpy.run_path(str(HERE/"build-local-fill-operations.py"))
ROOT=M["ROOT"];MM=M["MM"];pc=M["pc"];SCALE=M["SCALE"]
SOURCE=ROOT/"output/validation/native-adc10-pcb-direct4_copper-20261018.epru"
EXPECTED="f4c4fd15b00355d60b78391249c64aff1dd99903597fdbf937ed5dbb48c9fc4a"
DIRECT4={"C88","C81","C86","C96"}


class UF:
    def __init__(self):self.p={}
    def find(self,a):
        self.p.setdefault(a,a)
        if self.p[a]!=a:self.p[a]=self.find(self.p[a])
        return self.p[a]
    def join(self,a,b):self.p[self.find(a)]=self.find(b)


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest()==EXPECTED
    candidates=json.loads((HERE/"bottom-bucket-layer15-manifest.json").read_text())
    parent_path=HERE.parent/"strip/c95-layer18/c95-top-exterior-result.json"
    c95=json.loads(parent_path.read_text())["result"]
    alternate_path=HERE.parent/"strip/c95-layer18/branch-alternatives-layer18-ADC3_INP7.json"
    alternate=next(r for r in json.loads(alternate_path.read_text()) if r["xyMm"]==[55.36,78.44])
    c95["selectedRoutingSource"]=copy.deepcopy(alternate)
    c95["newSignalVias"]=[copy.deepcopy(alternate)]
    c95["additionalSignalRoutes"]=[copy.deepcopy(alternate["innerBranchRoute"])]
    c95["axisOfPositiveLocalX"]=[1,0]
    c95["nativeRotationDegrees"]=0
    c95["requiredWorldPads"]["1"]["xyMm"]=[54.48,77.3]
    c95["requiredWorldPads"]["2"]["xyMm"]=[53.52,77.3]
    c95["signalRoute"]["pointsMm"]=[alternate["xyMm"][:],[54.48,77.3]]
    c95["signalRoute"]["lengthMm"]=math.dist(*c95["signalRoute"]["pointsMm"])
    c95["electricalEscapeToCapPathMm"]=alternate["branchLengthMm"]+c95["signalRoute"]["lengthMm"]
    c95["groundRoute"]["pointsMm"][0]=[53.52,77.3]
    c95["groundRoute"]["lengthMm"]=math.dist(*c95["groundRoute"]["pointsMm"])
    c95["c95Layer17GroundNeckRepair"]={"previousUnappliedViaXYmm":[52.8,78.32],"newViaXYmm":alternate["xyMm"],"componentCenterUnchanged":True,"componentRotationRequiredDegrees":0,"groundRouteToSameOriginalVia":True,"reason":"Move new signal via outside narrow old layer17 GND neck; verify full-layer same-net via anchors after all cuts"}
    channels=[copy.deepcopy(r) for r in candidates["channels"] if r["ref"] not in DIRECT4 and "signalRoute" in r]+[copy.deepcopy(c95)]
    assert len(channels)==6 and {r["ref"] for r in channels}=={"C80","C82","C87","C93","C94","C95"}
    layout={"schema":"adc-remaining6-rebased-layout-20261018-v1","sourcePath":str(SOURCE),"sourceSha256":EXPECTED,"alreadyAppliedDirect4":sorted(DIRECT4),"channels":channels}
    input_path=HERE/"remaining6-rebased-layout-c95-farvia.json";input_path.write_text(json.dumps(layout,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"stage":"remaining6_layout_rebased","channels":6,"sourceSha256":EXPECTED,"direct4OperationsDuplicated":False}),flush=True)
    # Local cut builder reads the actual current source including direct4 lobe
    # 23f25be226b43a88 and updated 647; it does not reuse frozen direct4 paths.
    old_argv=sys.argv;sys.argv=[str(HERE/"build-local-fill-operations.py"),input_path.name,SOURCE.name]
    try:F["main"]()
    finally:sys.argv=old_argv
    cut_path=HERE/"remaining6-rebased-layout-c95-farvia-local-api-operations.json"
    cuts=json.loads(cut_path.read_text());assert cuts["passedOfflineFillAndGroundAudit"],cuts["errors"]
    print(json.dumps({"stage":"remaining6_cut_union_pass","fillModifies":len(cuts["fillModifyOperations"]),"fillCreates":len(cuts["fillCreateOperations"])}),flush=True)
    M["Board"].__init__.__globals__["SOURCE"]=SOURCE
    b=M["Board"]();b.route_power_fill_exceptions=T["POWER_FILL_EXCEPTION"];b.use_actual_passive_bodies=True
    six=T["AllLayers"](b)
    objects=list(six.obs);errors=[];added=[]
    def check(obj):
        bb=M["paths_bbox"](obj["paths"])
        for other in objects+added:
            if obj["net"]==other["net"] or not set(obj["layers"])&set(other["layers"]):continue
            if other["kind"]=="FILL" and other["net"] in T["POWER_FILL_EXCEPTION"]:continue
            if not M["overlap"](bb,other["bbox"],M["CLR"]+.0005):continue
            if M["inter"](obj["paths"],M["offset"](other["paths"],M["CLR"]+.0005)):errors.append({"new":obj["id"],"oldOrNew":other["id"],"error":"DIFFERENT_NET_COPPER_CLEARANCE"})
    for r in channels:
        layer=r["signalRoute"]["layerId"]
        if layer==2 and not b.body_clear(r["assemblyBoundingBoxMm"]):errors.append({"ref":r["ref"],"error":"ACTUAL_BOTTOM_BODY_COLLISION"})
        for via in r["newSignalVias"]:
            if not six.viable(via["xyMm"],r["net"]):errors.append({"ref":r["ref"],"error":"ALL_SIX_LAYER_VIA_OR_DRILL_CHECK_FAILED"})
            o={"id":r["ref"]+":VIA","kind":"NEW_VIA","net":r["net"],"layers":[1,2,15,16,17,18],"paths":[M["circle"](via["xyMm"],via["diameterMm"]/2)]};check(o);o["bbox"]=M["paths_bbox"](o["paths"]);added.append(o)
        for pn,p in r["requiredWorldPads"].items():
            o={"id":r["ref"]+":PAD"+pn,"kind":"NEW_CAP_PAD","net":p["net"],"layers":[layer],"paths":[M["rectangle"](p["xyMm"],r["axisOfPositiveLocalX"])]};check(o);o["bbox"]=M["paths_bbox"](o["paths"]);added.append(o)
        for ri,route in enumerate([r["signalRoute"]]+r.get("additionalSignalRoutes",[])+([r["groundRoute"]] if "groundRoute" in r else [])):
            net="GND" if route is r.get("groundRoute") else r["net"]
            o={"id":r["ref"]+":TRACE"+str(ri),"kind":"NEW_LINE","net":net,"layers":[route["layerId"]],"paths":M["capsule"](route["pointsMm"],route["widthMm"]/2)};check(o);o["bbox"]=M["paths_bbox"](o["paths"]);added.append(o)
        if layer==2:b.placed.append(r["assemblyBoundingBoxMm"])
    print(json.dumps({"stage":"remaining6_mutual_copper_check","errors":errors}),flush=True)
    if not errors:
        current=M["ROOT"]/"output/validation/native-adc10-pcb-remaining6_move-20261018.epru"
        assert hashlib.sha256(current.read_bytes()).hexdigest()=="af83b97cf7b775d834fc8339eb627beade225247ff077c2a234b3a50a4f808d4"
        current_rows=M["OLD"]["PARSE"](current)
        rotation={"schema":"adc-c95-rotation-only-guarded-20261018-v1","sourcePath":str(current),"sourceSha256":hashlib.sha256(current.read_bytes()).hexdigest(),"componentMoves":[{"operation":"pcb_PrimitiveComponent.modify","ref":"C95","primitiveId":c95["componentId"],"beforeComponentBody":current_rows["COMPONENT",c95["componentId"]],"targetLayerId":1,"targetXYmil":[v/MM for v in c95["centerXYmm"]],"axisAngleWorldDegrees":0,"nativeRotationDegrees":0,"requiredWorldPadsMm":c95["requiredWorldPads"],"allowedChangedFields":["angle"],"reason":"New far ADC tap avoids old layer17 GND neck; rotate same-body C95 to keep TOP signal and GND traces from crossing"}],"allSixLayerViaAndOldNewMutualCopperPassed":True,"nativeWorldPadVerificationRequiredBeforeCopper":True,"readOnlyBuilder":True,"nativeCallsPerformed":False}
        rotation_path=HERE/"c95-rotation-only-guarded-20261018.json";rotation_path.write_text(json.dumps(rotation,indent=2)+"\n",encoding="utf8")
        print(json.dumps({"stage":"c95_rotation_only_guard_ready","path":str(rotation_path),"sha256":hashlib.sha256(rotation_path.read_bytes()).hexdigest()}),flush=True)
    frozen4=json.loads((HERE/"direct4-native-operations-ready-for-calibration.json").read_text())
    all_buckets=channels+[r for r in frozen4["channels"] if r["ref"] in DIRECT4]
    assert len(all_buckets)==10
    afe=json.loads((HERE.parent/"strip/adc10-strip-phase1-explicit-closed-API-polygon-20261018.json").read_text())
    ref_correction=json.loads((HERE.parent/"strip/adc10-reference-courtyard-correction-20261018.json").read_text())["newPadWorldGeometry"]
    afe_ground=[]
    for component in afe["componentPlacements"]:
        ref=component["ref"]
        pads=[{"number":pn,**p,"rectangleXYmm":p["rectangle"]} for pn,p in ref_correction[ref].items()] if ref in ref_correction else component["expectedWorldPads"]
        for p in pads:
            if p["net"]=="GND":afe_ground.append({"ref":ref,"pin":p["number"],"layerId":1,"xyMm":p["xyMm"],"paths":[M["positive"](M["ip"](p["rectangleXYmm"]))]})
    # Final literal GND graph, after every cut and with the added GND lands and
    # explicit GND traces. Original plated GND via barrels link layer nodes.
    modified={o["primitiveId"]:o["afterNativeBody"] for o in cuts["fillModifyOperations"]}
    ground={l:[] for l in [1,2,15,16,17,18]}
    for (k,i),v in b.rows.items():
        if v.get("netName")!="GND":continue
        if k=="FILL" and v["layerId"] in ground:
            q=modified.get(i,v);ground[v["layerId"]].extend(M["offset"](M["filled_rings"](q["path"]),q["width"]*MM/2))
        elif k in ("LINE","ARC") and v["layerId"] in ground:
            a=(v["startX"]*MM,v["startY"]*MM);z=(v["endX"]*MM,v["endY"]*MM);pts=M["OLD"]["arc"](a,z,v["angle"]) if k=="ARC" else [a,z]
            ground[v["layerId"]].extend(M["capsule"](pts,v["width"]*MM/2))
        elif k=="VIA":
            for l in ground:
                if l in v.get("unusedInnerLayers",[]):continue
                ground[l].append(M["circle"]((v["centerX"]*MM,v["centerY"]*MM),v["viaDiameter"]*MM/2))
    for cr in cuts["fillCreateOperations"]:
        if cr["net"]=="GND":ground[cr["layerId"]].extend(M["offset"](M["filled_rings"](cr["afterNativePaths"]),cr["lineWidthMil"]*MM/2))
    for o in six.obs+added:
        if o["net"]!="GND" or o["kind"]=="FILL":continue
        for l in o["layers"]:ground[l].extend(o["paths"])
    for p in afe_ground:ground[p["layerId"]].extend(p["paths"])
    nodes={l:F["solid_nodes"](M["diff"](M["union"](paths),[],True)) for l,paths in ground.items()}
    uf=UF();via_nodes={}
    for (k,i),v in b.rows.items():
        if k!="VIA" or v["netName"]!="GND":continue
        p=(v["centerX"]*MM,v["centerY"]*MM);members=[]
        for l,ns in nodes.items():
            if l in v.get("unusedInnerLayers",[]):continue
            for ni,n in enumerate(ns):
                if F["node_solid"](p,n):uf.join(("VIA",i),(l,ni));members.append([l,ni])
        via_nodes[i]=members
    anchor=frozen4["physicalGroundAnchorProof"]["mcuVssAnchorExamples"][0]
    anchor_key=("VIA",anchor["groundViaId"]);ground_audit=[]
    ground_targets=[{"ref":r["ref"],"pin":"2","scope":"all10 bucket capacitors including direct4 after remaining6 cuts","layerId":r["signalRoute"]["layerId"],"xyMm":r["requiredWorldPads"]["2"]["xyMm"]} for r in all_buckets]+[{**p,"scope":"all34 AFE components; every actual GND pad, corrected C103/104/105"} for p in afe_ground]
    for target in ground_targets:
        l=target["layerId"];p=target["xyMm"]
        ns=[(l,ni) for ni,n in enumerate(nodes[l]) if F["node_solid"](p,n)]
        passed=any(uf.find(n)==uf.find(anchor_key) for n in ns)
        same_vias=[i for i,members in via_nodes.items() if any(uf.find(tuple(m))==uf.find(n) for m in members for n in ns)]
        ground_audit.append({"ref":target["ref"],"pin":target["pin"],"scope":target["scope"],"layerId":l,"groundPadXYmm":p,"physicalGroundGraphPassed":passed,"samePhysicalGroundViaIds":same_vias,"mcuVssAnchor":anchor})
        if not passed:errors.append({"ref":target["ref"],"pin":target["pin"],"error":"GND_DOES_NOT_REACH_MCU_VSS_BY_LITERAL_COPPER_AND_VIA_BARREL_GRAPH"})
    out=copy.deepcopy(cuts);out["schema"]="adc-remaining6-native-operations-20261018-v1";out["componentMoves"]=[];out["lineCreates"]=[];out["viaCreates"]=[]
    for r in channels:
        layer=r["signalRoute"]["layerId"];a=r["axisOfPositiveLocalX"];angle=math.degrees(math.atan2(a[1],a[0]))%360
        out["componentMoves"].append({"operation":"pcb_PrimitiveComponent.modify","ref":r["ref"],"primitiveId":r["componentId"],"beforeComponentBody":b.rows["COMPONENT",r["componentId"]],"targetLayerId":layer,"targetXYmil":[v/MM for v in r["centerXYmm"]],"axisAngleWorldDegrees":angle,"nativeRotationDegrees":angle,"requiredWorldPadsMm":r["requiredWorldPads"],"nativeBottomNormalRotationCalibration":"C88 native Bottom angle180 verified by root all8direct4pads; no local-X mirror adjustment","physicalBodyBoundingBoxMm":r["assemblyBoundingBoxMm"]})
        for via in r["newSignalVias"]:out["viaCreates"].append({"operation":"pcb_PrimitiveVia.create","ref":r["ref"],"net":r["net"],"xyMil":[v/MM for v in via["xyMm"]],"holeDiameterMil":via["holeMm"]/MM,"diameterMil":via["diameterMm"]/MM,"viaTypeMember":"EPCB_PrimitiveViaType.VIA","viaTypeValue":0,"designRuleBlindViaName":None,"primitiveLock":False})
        for route in [r["signalRoute"]]+r.get("additionalSignalRoutes",[])+([r["groundRoute"]] if "groundRoute" in r else []):
            net="GND" if route is r.get("groundRoute") else r["net"]
            for a,z in zip(route["pointsMm"],route["pointsMm"][1:]):out["lineCreates"].append({"operation":"pcb_PrimitiveLine.create","ref":r["ref"],"net":net,"layerId":route["layerId"],"startXYmil":[v/MM for v in a],"endXYmil":[v/MM for v in z],"widthMil":route["widthMm"]/MM,"primitiveLock":False})
    out["alreadyAppliedDirect4References"]=sorted(DIRECT4);out["noDuplicateDirect4Operations"]=not any(m["ref"] in DIRECT4 for m in out["componentMoves"]+out["lineCreates"])
    out["physicalGroundGraphAudit"]=ground_audit;out["selected18RuleEvidence"]=frozen4["selected18RuleEvidence"];out["sameNetOld634ViasAnd793DrillsMustRemainExact"]=True
    out["prospectiveGroundGraphScope"]={"all10Buckets":10,"afeComponentPlacements":len(afe["componentPlacements"]),"afeGroundPadCount":len(afe_ground),"correctedReferenceCapPadsUsed":sorted(ref_correction),"allGroundTargetsPassed":all(a["physicalGroundGraphPassed"] for a in ground_audit)}
    out["additionalDrills"]=len(out["viaCreates"]);out["nativeDrcRequired"]=True;out["allNewViaPadTraceMutualGeometryErrors"]=errors
    c80=next(r for r in channels if r["ref"]=="C80");c82=next(r for r in channels if r["ref"]=="C82")
    out["c80C82PhysicalBodyProof"]={"bothActualBodiesMm":[.5,1.0],"centerDeltaMm":[c80["centerXYmm"][0]-c82["centerXYmm"][0],c80["centerXYmm"][1]-c82["centerXYmm"][1]],"horizontalBodyEdgeGapMm":c80["assemblyBoundingBoxMm"][0]-c82["assemblyBoundingBoxMm"][2],"minimumLandEdgeGapMm":.30,"requiredBodyGapMm":.10,"requiredCopperClearanceMm":M["CLR"],"silkEnvelopeOverlapMustBeCleanedBeforeFabrication":True}
    out["passedOfflineCompositeAudit"]=not errors and cuts["passedOfflineFillAndGroundAudit"]
    out["errors"]=errors;out["applicationApproved"]=False;out["status"]="READY_FOR_PARENT_STAGED_NATIVE_APPLICATION" if out["passedOfflineCompositeAudit"] else "GEOMETRY_ERRORS_DO_NOT_APPLY"
    target=HERE/"remaining6-native-operations-c95-farvia-20261018.json";target.write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"passed":out["passedOfflineCompositeAudit"],"moves":len(out["componentMoves"]),"vias":len(out["viaCreates"]),"lines":len(out["lineCreates"]),"fillModifies":len(out["fillModifyOperations"]),"fillCreates":len(out["fillCreateOperations"]),"errors":errors}),flush=True)


if __name__=="__main__":main()
