"""Make a separate DFM copy: clip only top silkscreen, never copper or drills."""
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "output/pcb-two-zone"
sys.path.insert(0,str(root / ".tools/pcb-python"))
from shapely.geometry import box
from shapely.ops import unary_union

spec = importlib.util.spec_from_file_location("gerber", root / "scripts/audit-gerber.py")
gerber = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gerber)
original = out / "DAC8562_DAC_MCU_100x100_Gerber.zip"
target = out / "DAC8562_DAC_MCU_100x100_Gerber_DFM.zip"
if target.exists():
    raise FileExistsError(target)
with zipfile.ZipFile(original) as z:
    files = {n:z.read(n) for n in z.namelist()}
    _,_,silk = gerber.render(files["Gerber_TopSilkscreenLayer.GTO"].decode(),vector=True)
    _,_,mask = gerber.render(files["Gerber_TopSolderMaskLayer.GTS"].decode(),vector=True)
    guard = mask.buffer(0.15,quad_segs=64)
    allowed = silk.difference(guard).intersection(box(0.15,0.15,99.85,99.85))
    pieces = list(allowed.geoms) if hasattr(allowed,"geoms") else [allowed]
    pieces = [p for p in pieces if p.geom_type == "Polygon" and p.area > 1e-8]
    lines = ["G04 Native EasyEDA top silkscreen clipped to mask + 0.15mm and board - 0.15mm*", "%FSLAX26Y26*%", "%MOMM*%", "G75*", "%ADD10C,0.01*%", "G54D10*"]
    for p in pieces:
        lines.append("G36*")
        for ring in [p.exterior,*p.interiors]:
            for i,(x,y) in enumerate(ring.coords):
                lines.append(f"G01X{round(x*1e6)}Y{round(y*1e6)}D{'02' if i == 0 else '01'}*")
        lines.append("G37*")
    lines.append("M02*")
    generated = "\n".join(lines) + "\n"
    _,_,actual = gerber.render(generated,vector=True)
    assert actual.is_valid
    assert actual.intersection(mask.buffer(0.149,quad_segs=64)).area < 1e-7
    assert actual.difference(box(0.149,0.149,99.851,99.851)).area < 1e-7
    before_hashes = {n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    files["Gerber_TopSilkscreenLayer.GTO"] = generated.encode()
    with zipfile.ZipFile(target,"x",compression=zipfile.ZIP_DEFLATED) as t:
        for n,b in files.items():
            t.writestr(n,b)
    after_hashes = {n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    changed = [n for n in files if before_hashes[n] != after_hashes[n]]
    assert changed == ["Gerber_TopSilkscreenLayer.GTO"]
    result = {"input":original.name,"output":target.name,"changedFiles":changed,"copperMasksOutlineDrillsByteIdentical":True,"clearanceToMaskMm":0.15,"boardInsetMm":0.15,"polygons":len(pieces),"silkAreaBeforeMm2":silk.area,"silkAreaAfterMm2":actual.area,"quantizedGeometryDifferenceMm2":allowed.symmetric_difference(actual).area,"clearanceToMaskActuallyMeasuredMm":actual.distance(mask),"prototypeDfmNotAssemblyApproval":True}
    (out / "gerber-dfm-processing.json").write_text(json.dumps(result,indent=2),encoding="utf8")
    print(json.dumps(result,indent=2))
gerber.audit(target,"gerber-dfm")
