"""Focused local drill/mechanical/silk export check, never fabrication approval."""
import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/"output/validation/STM32H747_adc10_routed_20261018_DIAGNOSTIC_NOT_FOR_FAB.zip"
OLD=ROOT/"output/validation/STM32H747_corners_j18_direction_v2_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip"
PLAN=ROOT/"output/candidates/adc10-pcb-finish-20261018/bottom-buckets/remaining6-native-operations-c95-farvia-20261018.json"
OUT=ROOT/"output/candidates/adc10-pcb-finish-20261018/adc10-focused-diagnostic-gerber-audit-20261018.json"


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def key(x):return (x.category,tuple(round(v,5) for v in x.center_mm),round(x.diameter_mm,5),tuple(round(v,5) for v in x.start_mm) if x.start_mm else None,tuple(round(v,5) for v in x.end_mm) if x.end_mm else None)


def main():
    assert sha(NEW)=="af168c61f367eaa980b4e9140824e6c2cf6ee3e718466cae9c51a08004ce9405"
    drill=load("adc10_focused_drill",ROOT/"scripts/audit-diagnostic-gerber-drill-zip.py")
    geom=load("adc10_focused_outline",ROOT/"scripts/audit-cn1-cutout-gerber-20261016.py")
    before,bmeta,bentries=drill.read_candidate_zip(OLD)
    after,ameta,aentries=drill.read_candidate_zip(NEW)
    a,b=Counter(map(key,before)),Counter(map(key,after));lost=a-b;added=b-a
    added_items=[x for x in after if key(x) in added]
    expected=json.loads(PLAN.read_text())["viaCreates"]
    matches=[]
    for via in expected:
        p=[v*.0254 for v in via["xyMil"]]
        hits=[x for x in added_items if x.kind=="round" and x.plated_class=="pth" and math.dist(p,x.center_mm)<.00002 and abs(x.diameter_mm-.20)<.00002]
        matches.append({"net":via["net"],"expectedXYmm":p,"matchedExportXYmm":list(hits[0].center_mm) if len(hits)==1 else None,"diameterMm":hits[0].diameter_mm if len(hits)==1 else None,"passed":len(hits)==1})
    parser=geom.load_parser()
    with zipfile.ZipFile(OLD) as old,zipfile.ZipFile(NEW) as new:
        outline,bo,ao=geom.gerber_identity(geom.OUTLINE_MEMBER,old.read(geom.OUTLINE_MEMBER),new.read(geom.OUTLINE_MEMBER),parser)
        lines=[x for x in ao["objects"] if x["kind"]=="line"]
        pts=[p for x in lines for p in [x["startMm"],x["endMm"]]]
        bounds=[min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts)]
        inner=[x for x in lines if all(.001<p[0]<99.999 and .001<p[1]<153.999 for p in [x["startMm"],x["endMm"]])]
        ip=[p for x in inner for p in [x["startMm"],x["endMm"]]]
        cn=[max(p[0] for p in ip)-min(p[0] for p in ip),max(p[1] for p in ip)-min(p[1] for p in ip)]
        gbo="Gerber_BottomSilkscreenLayer.GBO"
        ob=geom.parsed(old.read(gbo),gbo,parser);nb=geom.parsed(new.read(gbo),gbo,parser)
        oc,nc=Counter(geom.object_hashes(ob)),Counter(geom.object_hashes(nb))
        silk={"priorAuditedBottomSilkObjects":len(ob["objects"]),"currentBottomSilkObjects":len(nb["objects"]),"priorObjectSequenceMultisetFullyRetained":not bool(oc-nc),"scope":"Exact resolved-aperture stroke identity against previously actual-backside-readability-verified v2 GBO; no new mirror inference or fresh visual readability claim."}
    checks={"frozenZipHash":True,"exportedPhysicalDrills799":len(after)==799,"all793PriorDrillsSlotsNPTHPreserved":len(before)==793 and not lost,"exactly6NewPTHRoundDrills":sum(added.values())==6 and len(added_items)==6,"all6NewDrills0_20mmAtNativeCenters":len(matches)==6 and all(m["passed"] for m in matches),"all8OutlineObjectsExactAgainstPriorApprovedCN1Corners":outline["status"]=="pass" and len(ao["objects"])==8,"outer100x154mm":abs(bounds[2]-bounds[0]-100)<.00001 and abs(bounds[3]-bounds[1]-154)<.00001,"CN1Square1_92mm":len(inner)==4 and all(abs(v-1.92)<.00001 for v in cn)}
    report={"schema":"adc10-focused-diagnostic-gerber-20261018-v1","status":"PASS_FOCUSED_DIAGNOSTIC_ONLY" if all(checks.values()) else "FAIL","zipPath":str(NEW),"zipSha256":sha(NEW),"baselineZipPath":str(OLD),"baselineZipSha256":sha(OLD),"checks":checks,"drills":{"before793":len(before),"after799":len(after),"beforeCounts":dict(Counter(x.category for x in before)),"afterCounts":dict(Counter(x.category for x in after)),"lostPrior":list(lost.items()),"newDrillMatches":matches,"viaOnlySupplementDuplicateFileHandledByExistingParser":True},"outline":{"resolvedObjectsExact":outline["resolved_geometry_object_sequence_exact"],"outerBoundsMm":bounds,"CN1SizeMm":cn},"bottomSilk":silk,"nativeCalls":0,"nativeWrites":0,"manufacturingApproved":False,"limitations":["Focused Excellon inventory and protected mechanical outline only; not a complete copper CAM/DRC/impedance/manufacturing audit.","Prior unresolved inner-layer Gerber corner/export comparison caveats remain in force; this report does not clear them.","J18 direction can only inherit the prior verified backside result if the exact prior bottom-silk stroke multiset is retained; no new rendered visual review was performed."]}
    OUT.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"path":str(OUT),"sha256":sha(OUT),"status":report["status"],"checks":checks,"silk":silk}))
    if not all(checks.values()):raise SystemExit(1)


if __name__=="__main__":main()
