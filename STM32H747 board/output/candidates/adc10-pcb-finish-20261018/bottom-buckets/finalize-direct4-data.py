"""Freeze direct-four native data, rule proof, and physical GND-anchor proof."""
import copy
import hashlib
import json
import math
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/"plan-bottom-buckets.py"))
F=runpy.run_path(str(HERE/"build-local-fill-operations.py"))
ROOT=M["ROOT"];MM=M["MM"];pc=M["pc"];SCALE=M["SCALE"]
SOURCE=ROOT/"output/validation/native-adc10-pcb-ref_courtyard-20261018.epru"
INPUT=HERE/"bottom-bucket-routing-manifest-local-api-operations.json"


def main():
    data=json.loads(INPUT.read_text());assert data["passedOfflineFillAndGroundAudit"] and data["solvedCapCount"]==4
    M["Board"].__init__.__globals__["SOURCE"]=SOURCE;b=M["Board"]();rows=b.rows
    # Literal original Inner1 GND copper, including physically present VIA
    # annuli. No net-name-only teleport edges are used to establish this tie.
    ground=[]
    for (k,i),v in rows.items():
        if v.get("netName")!="GND":continue
        if k=="FILL" and v["layerId"]==15:ground.extend(M["offset"](M["filled_rings"](v["path"]),v["width"]*MM/2))
        elif k in ("LINE","ARC") and v["layerId"]==15:
            a=(v["startX"]*MM,v["startY"]*MM);z=(v["endX"]*MM,v["endY"]*MM)
            pts=M["OLD"]["arc"](a,z,v["angle"]) if k=="ARC" else [a,z]
            ground.extend(M["capsule"](pts,v["width"]*MM/2))
        elif k=="VIA" and 15 not in v.get("unusedInnerLayers",[]):ground.append(M["circle"]((v["centerX"]*MM,v["centerY"]*MM),v["viaDiameter"]*MM/2))
    tree=M["diff"](M["union"](ground),[],True);nodes=F["solid_nodes"](tree)
    wanted=sorted({i for r in data["finalGroundContinuityAudit"] for i in r["sameIslandExistingGroundViaIds"]})
    positions={i:(v["centerX"]*MM,v["centerY"]*MM) for (k,i),v in rows.items() if k=="VIA" and v["netName"]=="GND"}
    common=[n for n in nodes if all(F["node_solid"](positions[i],n) for i in wanted)]
    docs,_=M["READ"](M["CHECKPOINT"])
    uid=b.refs["U1"];u=rows["COMPONENT",uid];theta=math.radians(u["angle"])
    pn={}
    for (k,i),v in rows.items():
        if k=="PAD_NET":
            key=json.loads(i)
            if key[1]==uid:pn[str(key[2])]=v["padNet"]
    gnd_pads=[]
    for (k,i),(h,v) in docs["FOOTPRINT",b.attrs[uid]["Footprint"]].items():
        if k!="PAD" or pn.get(str(v["num"]))!="GND":continue
        x,y=v["centerX"]*MM,v["centerY"]*MM
        gnd_pads.append((str(v["num"]),(u["x"]*MM+x*math.cos(theta)-y*math.sin(theta),u["y"]*MM+x*math.sin(theta)+y*math.cos(theta))))
    anchors=[]
    for (k,i),v in rows.items():
        if k!="LINE" or v["netName"]!="GND" or v["layerId"]!=1:continue
        a=(v["startX"]*MM,v["startY"]*MM);z=(v["endX"]*MM,v["endY"]*MM)
        for first,last in [(a,z),(z,a)]:
            pads=[(num,p) for num,p in gnd_pads if math.dist(first,p)<.00001]
            vias=[vid for vid,p in positions.items() if math.dist(last,p)<.00001 and 15 not in rows["VIA",vid].get("unusedInnerLayers",[])]
            for num,p in pads:
                for vid in vias:
                    if common and F["node_solid"](positions[vid],common[0]):anchors.append({"mcuRef":"U1","mcuGroundPad":num,"groundPadXYmm":p,"topGroundLineId":i,"lineEndpointsMm":[a,z],"groundViaId":vid,"groundViaXYmm":positions[vid],"joinsSameUnchangedInner1SolidAsAllBottomReturnVias":True})
    graph={"passed":bool(common and anchors),"method":"Each final Bottom GND pad lies in an explicit surviving Bottom GND solid with listed original GND via(s). All listed return vias and this MCU VSS ground fanout via lie in one unchanged literal Inner1 GND copper connected component, including native via annuli. Edges are geometric copper contacts, not NET labels.","bottomReturnViaIds":wanted,"commonInner1GroundComponents":len(common),"commonInner1ComponentOuterAreaMm2":abs(pc.Area(common[0].Contour))/(SCALE*SCALE) if common else None,"mcuVssAnchorExamples":anchors[:5]}
    radius=next((v for (k,i),v in rows.items() if k=="RULE" and json.loads(i)[1:]==["RADIUS","viaSize"]))
    other=next((v for (k,i),v in rows.items() if k=="RULE" and json.loads(i)[1:]==["OTHER","otherClearance"]))
    track=next((v for (k,i),v in rows.items() if k=="RULE" and json.loads(i)[1:]==["TRACK","copperThickness1oz"]))
    engine=Path("C:/Program Files/easyeda-pro/resources/app/assets/pro-pcb/3.2.193.682ed44e/js/pcb.js")
    es=engine.read_text(encoding="utf8");snippets=[]
    for needle in ["let r=t,i=r.minRadius/10", "o.model.radius*2,2),i=we(o.model.holeRadius*2,2)"]:
        i=es.index(needle);snippets.append({"needle":needle,"offset":i,"snippet":es[max(0,i-80):i+430]})
    rc=radius["ruleContext"]
    rules={"selectedRuleTemplate":next(v for (k,i),v in rows.items() if k=="RULE_TEMPLATE"),"ruleCount":sum(k=="RULE" for k,i in rows),"actualRadiusRule":radius,"actualOtherClearanceRule":other,"actualTopBottomTrackRule":track,"installedEnginePath":str(engine),"installedEngineSha256":hashlib.sha256(engine.read_bytes()).hexdigest(),"installedEngineRadiusDecodeAndDiameterValidatorEvidence":snippets,"derivedUnits":{"nativeSourceRuleLengths":"mil; radius fields encode radii; public VIA API holeDiameter/diameter encode diameters","minimumViaDiameterMm":2*rc["minRadius"]*MM,"minimumViaDrillDiameterMm":2*rc["minInner"]*MM,"proposedViaDiameterMm":.31,"proposedViaHoleMm":.20,"outerDiameterMarginMm":.31-2*rc["minRadius"]*MM,"drillDiameterMarginMm":.20-2*rc["minInner"]*MM,"radialAnnulusMm":(.31-.20)/2,"annulusCaveat":"No separate radial-annulus minimum field exists in selected 18 RULE bodies. 0.055 mm is geometric arithmetic, not a native-rule encoded 0.05 mm guarantee. Native DRC/CAM/manufacturer checks remain mandatory.","minimumHoleEdgeClearanceMm":other["ruleContext"]["holeClearance"]*MM,"routeWidthMm":.12,"minimumTopBottomWidthMm":track["ruleContext"]["track"]["content"][0]["stroMin"]*MM}}
    out=copy.deepcopy(data);out["schema"]="adc-direct4-native-operations-20261018-v2"
    out["inputLocalManifestSha256"]=hashlib.sha256(INPUT.read_bytes()).hexdigest();out["physicalGroundAnchorProof"]=graph;out["selected18RuleEvidence"]=rules
    out["componentMoves"]=[];out["lineCreates"]=[]
    for r in out["channels"]:
        ax=r["axisOfPositiveLocalX"];center=r["centerXYmm"];axis_angle=math.degrees(math.atan2(ax[1],ax[0]))%360
        out["componentMoves"].append({"operation":"pcb_PrimitiveComponent.modify","primitiveId":r["componentId"],"ref":r["ref"],"beforeComponentBody":rows["COMPONENT",r["componentId"]],"targetLayerId":2,"targetXYmil":[v/MM for v in center],"axisAngleWorldDegrees":axis_angle,"requiredWorldPadsMm":r["requiredWorldPads"],"bottomRotationCalibrationRequired":True,"nativeRotationIfBottomReflectsLocalX":(axis_angle+180)%360,"nativeRotationIfBottomReflectsLocalY":axis_angle,"courtyardBoundingBoxMm":[center[0]-(.95 if ax[0] else .5),center[1]-(.5 if ax[0] else .95),center[0]+(.95 if ax[0] else .5),center[1]+(.5 if ax[0] else .95)],"minimumCourtyardGapMm":.10})
        for a,z in zip(r["signalRoute"]["pointsMm"],r["signalRoute"]["pointsMm"][1:]):out["lineCreates"].append({"operation":"pcb_PrimitiveLine.create","ref":r["ref"],"net":r["net"],"layerId":2,"startXYmil":[v/MM for v in a],"endXYmil":[v/MM for v in z],"widthMil":r["signalRoute"]["widthMm"]/MM,"primitiveLock":False})
    out["legacyBottomAssemblyEnvelopes"]=b.legacy_bottom_envelopes
    out["passedOfflineFillGroundAndRuleEvidence"]=data["passedOfflineFillAndGroundAudit"] and graph["passed"]
    target=HERE/"direct4-native-operations-ready-for-calibration.json"
    target.write_text(json.dumps(out,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(target),"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"groundProofPassed":graph["passed"],"moves":len(out["componentMoves"]),"lines":len(out["lineCreates"]),"fillModifies":len(out["fillModifyOperations"]),"fillCreates":len(out["fillCreateOperations"]),"orphansRemoved":len(out["localNewOrphanFragmentCleanup"])}),flush=True)


if __name__=="__main__":main()
