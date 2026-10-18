"""Independent strict polygon validity audit; never repairs invalid geometry."""
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path
from shapely.geometry import Polygon
from shapely.validation import explain_validity
from shapely.strtree import STRtree

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"output/candidates/adc10-pcb-finish-20261018"
OLD=runpy.run_path(str(ROOT/"scripts/draft-adc10-bucket-placement-readonly-20261017.py"))
OLD["ring_path"].__globals__["SAG"]=.0001
MM=.0254


def ring(p):
    if p[0]=="CIRCLE":
        return [((p[1]+p[3]*math.cos(i*math.tau/256))*MM,(p[2]+p[3]*math.sin(i*math.tau/256))*MM) for i in range(256)]
    if p[0]=="R":
        _,x,y,w,h,a,*_=p
        a=math.radians(a)
        return [((x+dx*math.cos(a)-dy*math.sin(a))*MM,(y+dx*math.sin(a)+dy*math.cos(a))*MM) for dx,dy in [(0,0),(w,0),(w,h),(0,h)]]
    return OLD["ring_path"](p)


def inspect_paths(paths):
    rings=[ring(p) for p in paths]
    poly=Polygon(rings[0],rings[1:])
    closed=all(isinstance(p[0],str) or p[:2]==p[-2:] for p in paths)
    quantized=[[round(v,4) if isinstance(v,(int,float)) else v for v in p] for p in paths]
    qrings=[ring(p) for p in quantized]
    qpoly=Polygon(qrings[0],qrings[1:])
    return {"valid":poly.is_valid,"explanation":explain_validity(poly),"quantizedNativeRound4Valid":qpoly.is_valid,"quantizedNativeRound4Explanation":explain_validity(qpoly),"contours":len(paths),"allAPIRingsExplicitlyClosed":closed,"areaMm2":poly.area,"boundsMm":list(poly.bounds)},poly


def main():
    source=Path(sys.argv[1]) if len(sys.argv)>1 else HERE/"bottom-buckets/remaining6-rebased-layout-local-api-operations.json"
    data=json.loads(source.read_text())
    rows=[]
    for op in data["fillModifyOperations"]:
        after=op["afterPathsExplicitlyClosedForApi"]
        row,_=inspect_paths(after)
        before,_=inspect_paths(op["beforeBody"]["path"])
        row["beforeValid"]=before["valid"]
        row["beforeValidityExplanation"]=before["explanation"]
        if not row["valid"]:
            holes=[Polygon(ring(p)) for p in after[1:]]
            tree=STRtree(holes)
            nested=[]
            for i,h in enumerate(holes):
                for j in tree.query(h):
                    j=int(j)
                    if i!=j and holes[j].contains(h):
                        nested.append({"innerIndex":i+1,"outerIndex":j+1,"innerAreaMm2":h.area,"innerBoundsMm":list(h.bounds),"outerAreaMm2":holes[j].area})
            row["nestedPairs"]=nested
        row.update({"id":op["primitiveId"],"layerId":op["layerId"],"net":op["net"],"operation":"modify"})
        rows.append(row)
    for op in data["fillCreateOperations"]:
        row,_=inspect_paths(op["afterPathsExplicitlyClosedForApi"])
        row.update({"id":op["semanticId"],"layerId":op["layerId"],"net":op["net"],"operation":"create"})
        rows.append(row)
    errors=[r for r in rows if not r["valid"] or not r["quantizedNativeRound4Valid"] or not r["allAPIRingsExplicitlyClosed"]]
    report={"schema":"adc10-remaining6-strict-independent-fill-validity-20261018-v1","status":"PASS" if not errors else "FAIL","inputPath":str(source),"inputSha256":hashlib.sha256(source.read_bytes()).hexdigest(),"nativeSourceSha256":data["sourceSha256"],"testedFillPaths":len(rows),"fills":rows,"errors":errors,"geometryRepaired":False,"liveCalls":0,"scope":"Strict native outer+hole topology and explicit public API closure only; not a full clearance/GND/netlist proof."}
    out=HERE/"strip/adc10-remaining6-independent-fill-validity-20261018.json"
    out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"report":str(out),"sha256":hashlib.sha256(out.read_bytes()).hexdigest(),"status":report["status"],"fills":len(rows),"errors":errors}))


if __name__=="__main__":main()
