"""Read-only PCB/API inventory; emits an analysis report, never EDA source."""
import hashlib
import json
import math
import runpy
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/validation/native-adc10-pcb-before-20261017.epru"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_adc10_20261017.epro2"
OUT = ROOT / "output/analysis/adc10-pcb-eco-api-feasibility-20261017.json"
PARSE = runpy.run_path(str(ROOT/"output/candidates/adc-dc-buffer/independent-static-adc-plan-review.py"))["parse"]
READ = runpy.run_path(str(ROOT/"output/candidates/adc-inline-wiring/audit-inline-final-project.py"))["read_snapshot"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(SOURCE) == "9d0dd97d4c93bf04ed9a00692c5997371d989175dfb94a8dcbb57831319c30f5"
    rows = PARSE(SOURCE)
    docs,_ = READ(CHECKPOINT)
    attrs = defaultdict(dict)
    for (kind,rid),body in rows.items():
        if kind == "ATTR":
            attrs[body["parentId"]][body["key"]] = body.get("value")
    refs = {v["Designator"]:cid for cid,v in attrs.items() if "Designator" in v}
    comps = {rid:body for (kind,rid),body in rows.items() if kind == "COMPONENT"}
    pad_nets = {}
    for (kind,rid),body in rows.items():
        if kind == "PAD_NET":
            key = json.loads(rid)
            pad_nets[key[1],str(key[2])] = body["padNet"]

    def pads(ref):
        cid = refs[ref]
        c = comps[cid]
        theta = math.radians(c["angle"])
        result = []
        for (kind,rid),(head,body) in docs["FOOTPRINT",attrs[cid]["Footprint"]].items():
            if kind != "PAD":
                continue
            x,y = body["centerX"],body["centerY"]
            gx = c["x"]+x*math.cos(theta)-y*math.sin(theta)
            gy = c["y"]+x*math.sin(theta)+y*math.cos(theta)
            result.append({"number":str(body["num"]),"localId":rid,"net":pad_nets.get((cid,str(body["num"])),""),"localMil":[x,y],"worldMm":[round(gx*.0254,7),round(gy*.0254,7)],"localPad":body["defaultPad"]})
        return result

    board_ids = {v["attrs"]["Unique ID"]: {"ref":attrs[cid].get("Designator"),"componentId":cid,"footprint":attrs[cid].get("Footprint")} for cid,v in comps.items()}
    sch_ids = {}
    for doc,records in docs.items():
        if doc[0] != "SCH_PAGE":
            continue
        a = defaultdict(dict)
        for (kind,rid),(head,body) in records.items():
            if kind == "ATTR":a[body["parentId"]][body["key"]] = body.get("value")
        for cid,v in a.items():
            if v.get("Convert to PCB") == "yes" and v.get("Unique ID") and ("COMPONENT",cid) in records:
                if v["Unique ID"] in sch_ids:
                    # U1's multiple schematic units intentionally share one
                    # physical identity; they must agree on ref/footprint.
                    assert sch_ids[v["Unique ID"]]["ref"] == v.get("Designator")
                    assert sch_ids[v["Unique ID"]]["footprint"] == v.get("Footprint")
                    continue
                sch_ids[v["Unique ID"]] = {"ref":v.get("Designator"),"componentId":cid,"footprint":v.get("Footprint")}
    uid_audit = {"schematicComponents":len(sch_ids),"pcbComponents":len(board_ids),"matchingUids":len(sch_ids.keys()&board_ids.keys()),"pcbOnly":[board_ids[k] for k in board_ids.keys()-sch_ids.keys()],"schematicOnly":[sch_ids[k] for k in sch_ids.keys()-board_ids.keys()],"mismatchedReferences":[[sch_ids[k],board_ids[k]] for k in sch_ids.keys()&board_ids.keys() if sch_ids[k]["ref"]!=board_ids[k]["ref"]],"changedFootprintBindings":[{"ref":sch_ids[k]["ref"],"schematic":sch_ids[k]["footprint"],"pcb":board_ids[k]["footprint"]} for k in sch_ids.keys()&board_ids.keys() if sch_ids[k]["footprint"]!=board_ids[k]["footprint"]]}
    channel_specs = [
        (2,"ADC1_INP0","T1",137,140,141,80,146),(3,"ADC1_INP1","T2",138,142,143,81,147),(4,"ADC1_INP16","N5",139,144,145,82,148),
        (5,"ADC2_INP3","R3",149,152,153,86,158),(6,"ADC2_INP12","M3",150,154,155,87,159),(7,"ADC2_INP13","M4",151,156,157,88,160),
        (8,"ADC3_INP2","L4",161,165,166,93,173),(9,"ADC3_INP6","L3",162,167,168,94,174),(10,"ADC3_INP7","K4",163,169,170,95,175),(11,"ADC3_INP8","K2",164,171,172,96,176)]
    mcu_pads = {p["number"]:p for p in pads("U1")}
    all_vias = [(rid,b) for (kind,rid),b in rows.items() if kind=="VIA"]
    gnd_vias = [(rid,b) for rid,b in all_vias if b.get("netName")=="GND"]
    channels = []
    for j,net,ball,bias,rin,rout,cap,dnp in channel_specs:
        bp = mcu_pads[ball]
        assert bp["net"] == net
        bx,by = bp["worldMm"]
        vias = [{"id":rid,"xyMm":[round(v["centerX"]*.0254,7),round(v["centerY"]*.0254,7)],"distanceToBallMm":math.hypot(v["centerX"]*.0254-bx,v["centerY"]*.0254-by),"diameterMm":v["viaDiameter"]*.0254,"holeMm":v["holeDiameter"]*.0254} for rid,v in all_vias if v.get("netName")==net]
        vias.sort(key=lambda v:v["distanceToBallMm"])
        esc = vias[0]
        near_gnd = [{"id":rid,"xyMm":[round(v["centerX"]*.0254,7),round(v["centerY"]*.0254,7)],"distanceToEscapeMm":math.hypot(v["centerX"]*.0254-esc["xyMm"][0],v["centerY"]*.0254-esc["xyMm"][1]),"diameterMm":v["viaDiameter"]*.0254} for rid,v in gnd_vias]
        near_gnd.sort(key=lambda v:v["distanceToEscapeMm"])
        related = []
        for ref in [f"J{j}",f"R{bias}",f"R{rin}",f"R{rout}",f"C{cap}",f"R{dnp}",f"TP{j-1}"]:
            cid = refs[ref]
            c = comps[cid]
            related.append({"ref":ref,"componentId":cid,"xyMil":[c["x"],c["y"]],"xyMm":[round(c["x"]*.0254,7),round(c["y"]*.0254,7)],"angleDegrees":c["angle"],"layer":c["layerId"],"footprintUuid":attrs[cid].get("Footprint"),"pads":pads(ref)})
        lines = [{"id":rid,"layer":b["layerId"],"startMm":[b["startX"]*.0254,b["startY"]*.0254],"endMm":[b["endX"]*.0254,b["endY"]*.0254],"widthMm":b["width"]*.0254} for (kind,rid),b in rows.items() if kind=="LINE" and b.get("netName")==net]
        channels.append({"smaRef":f"J{j}","net":net,"mcuBall":bp,"nearestAdcEscapeVia":esc,"otherAdcVias":vias[1:],"closestGroundVias":near_gnd[:6],"originalAnalogParts":related,"existingAdcLines":lines,"existingAdcRoutingLayerCounts":dict(Counter(x["layer"] for x in lines)),"bucketMoveRequired":True,"proposedBucketLayer":"BOTTOM","placementWarning":"No coordinates are declared collision-free yet: check all bottom traces/vias/FILL, mask and assembly clearances; no via-in-pad without process approval."})
    lib = json.loads((ROOT/"output/candidates/adc-dc-buffer/adc-dc-runtime-library-map.json").read_text(encoding="utf8"))
    doc_dir = ROOT/".tools/easyeda-api/references"
    api = [
        {"method":"pcb_Document.importChanges","signature":"importChanges(uuid?: string): Promise<boolean>","documentation":str(doc_dir/"classes/PCB_Document.md"),"note":"Schematic UUID, not sheet UUID. Installed adapter launches normal Board-linked Unique-ID ECO comparison workflow; true is not proof of applied delta. Do not use undocumented force argument."},
        {"method":"pcb_PrimitiveComponent.create","signature":"create(component, layer, xMil, yMil, rotationDegrees?, primitiveLock?): Promise<IPCB_PrimitiveComponent | undefined>","documentation":str(doc_dir/"classes/PCB_PrimitiveComponent.md"),"projectDeviceDescriptors":{"OPA320":{"libraryUuid":"project","uuid":lib["devices"]["OPA320"]["uuid"]},"REF3325":{"libraryUuid":"project","uuid":lib["devices"]["REF3325"]["uuid"]}},"note":"Prefer native ECO for matching schematic Unique ID and pin nets. Manual create must bind real footprint plus exact schematic Unique ID/designator and set all pad nets; attributes alone do not generate electrical pads."},
        {"method":"pcb_PrimitiveComponent.modify","signature":"modify(primitiveId, {x?, y?, rotation?, designator?, uniqueId?, name?, ...}): Promise<IPCB_PrimitiveComponent | undefined>","documentation":str(doc_dir/"classes/PCB_PrimitiveComponent.md"),"note":"Placement only of explicitly allowlisted ADC components; inspect full source and actual pad coordinates afterward."},
        {"method":"pcb_Document.autoRouting","signature":"autoRouting({RoutingNets?: string[]|'selected'|'selectedComponents', existingPrimitiveMode?: KEEP, layers?: copperLayerIds[], ...}): Promise<IPCB_AutoRoutingResult>","documentation":str(doc_dir/"interfaces/IPCB_AutoRoutingProps.md"),"note":"Installed implementation reads case-sensitive RoutingNets; examples using nets are wrong. KEEP='keep', REMOVE='remove'. Never clear all routing. Restrict to affected nets/layers; not a preservation guarantee. No global autoLayout because its API has no subset parameter."}]
    report = {"schema":"adc10-pcb-eco-readonly-20261017-v1","readOnly":True,"nativeCallsPerformed":False,"source":{"path":str(SOURCE),"sha256":sha(SOURCE)},"checkpoint":{"path":str(CHECKPOINT),"sha256":sha(CHECKPOINT)},"pcbCounts":dict(Counter(k[0] for k in rows)),"uidAudit":uid_audit,"expectedAllTenFinalPhysicalComponents":354,"expectedECOArithmetic":"330 original - 10 removed DNP + 34 new (10 OPA + 20 input/local C + REF + 3 REF C)","api":api,"channels":channels,"newProjectFootprints":lib["footprints"],"passiveOrientationWarning":{"biasResistors":"Old vertical baked-angle0 pad1 is power and pad2 is mixer. New horizontal generic R pad1 is PRE, pad2 is BIAS: proposed angle90 degrees preserves old physical locations with deliberately exchanged old pad numbering.","inputAndSeriesResistors":"Generic R angle0 normally preserves existing horizontal pad locations; verify per-part after ECO.","adcCapacitors":"Old vertical baked-angle0 pad1 ADC is bottom, pad2 GND top. Generic C pad1 is right, pad2 left; proposed angle270 degrees preserves old site, but these ten buckets should instead move to bottom near MCU escape and verify actual bottom pad reflection."},"safeSequence":["Freeze all-ten schematic/ERC/native netlist and full PCB checkpoint.","Import normal Board-linked ECO; review deletion/new-part/40 passive replacement counts and Unique IDs before applying.","Capture actual post-ECO source; verify remaining320 original component identities, all unrelated copper/rules/stack/outline/drill geometry.","Resolve regenerated passive rotations against actual footprint/pad coordinates.","Keep original local47R positions if possible; place10 new OPAs with short1-to4 feedback and local100nF near mixers; move only ten2.2nF buckets to bottom MCU escape sites.","Remove only obsolete local+3V3 bias branches, DNP copper stubs and pre-to-series bypasses; preserve long ADC routes/MCU escape vias.","Use manual/explicit-net routing with KEEP; no whole-board autoLayout, clearRouting(all), or source replacement.","Native ERC/DRC/netlist comparison, saved/reopened geometry audit and CAM/assembly review before any manufacturing claim."],"openZeroDetectorExcluded":True,"placementAndRoutingProven":False,"manufacturingReady":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(OUT),"pcbComponents":len(comps),"matchingExistingUids":uid_audit["matchingUids"],"channelCount":len(channels),"mcuBallInventoryComplete":True,"apiCallsPerformed":False},indent=2))


if __name__ == "__main__":
    main()
