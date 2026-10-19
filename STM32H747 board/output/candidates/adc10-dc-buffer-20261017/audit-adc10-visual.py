"""Record completed human/model visual review plus source-level dot checks."""
import hashlib
import json
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def main():
    plan=json.loads((HERE/"adc10-schematic-plan.json").read_text(encoding="utf8"))
    renderer=json.loads((HERE/"adc10-proposed-source-visual-qa.json").read_text(encoding="utf8"))
    source=Path(plan["candidatePath"])
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha==plan["candidateSha256"]==renderer["sourceSha256"]
    assert not renderer["missingSymbols"] and not renderer["unsupportedPrimitives"]
    rows=runpy.run_path(str(HERE/"build-adc10-dc-candidate.py"))["parse"](source)
    circles=[]
    lines=[]
    for r in rows:
        b=r["b"]
        if r["h"]["type"]=="LINE":
            lines.append(((b["startX"],b["startY"]),(b["endX"],b["endY"])))
        if r["h"]["type"]=="POLY" and b.get("fillColor")=="#009600" and b.get("closed") and b.get("points"):
            pts=b["points"]
            xs,ys=[p["x"] for p in pts],[p["y"] for p in pts]
            if 3.5<=max(xs)-min(xs)<=3.7 and 3.5<=max(ys)-min(ys)<=3.7:
                circles.append({"id":r["h"]["id"],"center":[(max(xs)+min(xs))/2,(max(ys)+min(ys))/2]})
    expected=[]
    for off,dy in [(0,0),(335,0),(665,0),(0,170),(335,170),(665,170),(0,340),(335,340),(665,340),(1005,340)]:
        for name,x,y in (("mixer",280,190),("feedback",400,200),("adc",455,200)):
            p=[x+off,y+dy]
            found=[c["id"] for c in circles if abs(c["center"][0]-p[0])<1e-5 and abs(c["center"][1]-p[1])<1e-5]
            assert len(found)==1,(name,p,found)
            expected.append({"role":name,"point":p,"dotId":found[0]})
    on=runpy.run_path(str(HERE/"build-adc10-dc-candidate.py"))["on"]
    orphan=[c for c in circles if not any(on(c["center"],a,b) for a,b in lines)]
    assert not orphan,orphan
    reviewed=["adc10-proposed-source-visual-qa.png","adc10-proposed-adc1-bank.png","adc10-proposed-adc2-bank.png",
        "adc10-proposed-adc3-bank.png","adc10-proposed-reference-context.png","adc10-proposed-timer-dac-context.png","adc10-proposed-notes-j18-context.png"]
    assert all((HERE/f).exists() for f in reviewed)
    report={"schema":"adc10-offline-source-visual-review-20261017-v1","passed":True,
        "sourcePath":str(source),"sourceSha256":sha,"renderer":"Exact saved project SYMBOL vectors plus candidate source, independent offline SVG/PNG; not native EasyEDA SVG export",
        "reviewedFiles":reviewed,"manualFindings":{"all10InputPathsContinuousAndReadable":True,"all10MixersHaveSingleVisibleJunctionDot":True,
            "all10FeedbackLoopsClearBelowOpamp":True,"all7DnpGrayGlyphsAndNcOverlaysGone":True,"noFloatingLegacyJunctionDots":True,
            "allReferencesValuesAndAdcPortMcuLabelsLegible":True,"threeBankGrouping3_3_4FitsA3Frame":True,"rightmostAdc3PortFitsFrame":True,
            "timerPlus95yAndDacMcoPlus100yReadable":True,"noNewJ18OrReferenceOverlap":True,"referenceTwoTextCaptionChangesLegible":True,
            "lowerLeftNotesStateNoFloatingDetector":True},"exact30ChannelJunctionDotChecks":expected,
        "allPageJunctionCircleCount":len(circles),"orphanJunctionCircles":orphan,
        "nativeErcAndNetlistRequiredAfterApplication":True,"rawZeroDetectorAdded":False,"pcbApplied":False,"manufacturingApproval":False}
    out=HERE/"adc10-proposed-visual-review.json"
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"passed":True,"report":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"channelDots":len(expected),"orphanDots":len(orphan)},indent=2))


if __name__=="__main__":main()
