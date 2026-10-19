"""Offline same-site180degree swaps for referenceLPFpinordering only."""
import copy,hashlib,json,runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-labtool-20261018"
OLD=HERE/"independent-pcb-placement-short-negative-commonpower-v4-proposal.json"
LIVE=ROOT/"output/validation/native-adc10-pcb-labtool_107_placed_v4_saved-20261018.epru"
M=runpy.run_path(str(HERE/"independent-pcb-placement-proposal.py"))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
def main():
    before=json.loads(OLD.read_text(encoding="utf8"));after=copy.deepcopy(before)
    rows=M["parse"](LIVE);attrs=M["attrs_of"](rows);refs={a["Designator"]:cid for cid,a in attrs.items() if "Designator" in a}
    edits=[]
    for p in after["edits"]:
        if p["ref"] not in ("R202","C158"):continue
        old=next(q for q in before["edits"] if q["ref"]==p["ref"])
        x,y=p["xyMm"]
        p["angle"]=(p["angle"]+180)%360
        p["set"]["rotation"]=p["angle"]
        for pad in p["pads"]:
            px,py=pad["centerMm"];a,b,c,d=pad["boundsMm"]
            pad["centerMm"]=[2*x-px,2*y-py];pad["boundsMm"]=[2*x-c,2*y-d,2*x-a,2*y-b]
        for pad in p["pads"]:
            peer=next(q for q in old["pads"] if q["number"]!=pad["number"])
            assert max(abs(a-b) for a,b in zip(pad["centerMm"],peer["centerMm"]))<1e-7
            assert max(abs(a-b) for a,b in zip(pad["boundsMm"],peer["boundsMm"]))<1e-7
        cid=refs[p["ref"]];body=rows["COMPONENT",cid]
        assert abs(body["x"]*.0254-x)<1e-5 and abs(body["y"]*.0254-y)<1e-5
        assert body["angle"]==old["angle"]
        expected=copy.deepcopy(body);expected["angle"]=p["angle"]
        assert body["attrs"]["Unique ID"]==p["uniqueId"]
        edits.append({"ref":p["ref"],"componentId":cid,"uniqueId":p["uniqueId"],"beforeBody":body,"beforeBodySha256":digest(body),"afterBody":expected,"allowedChangedFields":["angle"],"value":attrs[cid].get("Value"),"footprint":attrs[cid]["Footprint"],"physicalPadsUnionAndCourtUnchanged":True,"expectedPads":p["pads"]})
    oldby={p["ref"]:p for p in before["edits"]};newby={p["ref"]:p for p in after["edits"]}
    assert [r for r in oldby if oldby[r]!=newby[r]]==["R202","C158"]
    after.update({"schema":"adc10-labtool-placement-v5-two-reference-rotation-variant-20261018","parentPlacementSha256":sha(OLD),"sourcePath":str(LIVE),"sourceSha256":sha(LIVE),"variantReason":"180degreerotationsofsamereferenceR202/C158padsitespermitshortTOPLPFnetwork;nohighZsignalVIAsrequiredifroutegraphpasses","changedRefsOnly":["R202","C158"],"nativeCalls":0,"nativeWriteApproved":False})
    out=HERE/"independent-pcb-placement-short-negative-commonpower-v5b-ref-flipped-proposal.json"
    assert not out.exists();out.write_text(json.dumps(after,indent=2)+"\n",encoding="utf8")
    operation={"schema":"adc10-labtool-reference-two-rotation-exact-operations-20261018","sourcePath":str(LIVE),"sourceSha256":sha(LIVE),"placementPath":str(out),"placementSha256":sha(out),"operations":edits,"allOther105EntriesExact":True,"originalDrillChanges":0,"viaChanges":0,"liveCalls":0,"rootMustVerifyNativeSourceBeforeApplying":True}
    opout=HERE/"routing/reference-two-rotation-exact-operations-v5b.json";assert not opout.exists();opout.write_text(json.dumps(operation,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"placement":str(out),"placementSha256":sha(out),"operations":str(opout),"operationsSha256":sha(opout)}))
if __name__=="__main__":main()
