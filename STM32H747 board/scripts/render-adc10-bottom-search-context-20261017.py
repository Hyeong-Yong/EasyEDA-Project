"""Offline literal PCB-bottom copper view around the ADC BGA escape region."""
import json
import runpy
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[1]
M=runpy.run_path(str(ROOT/"scripts/draft-adc10-bucket-placement-readonly-20261017.py"))
rows=M["PARSE"](M["SOURCE"])
bounds=(47,76.5,59,87)
scale=190
canvas=Image.new("RGB",(round((bounds[2]-bounds[0])*scale),round((bounds[3]-bounds[1])*scale)),"#10151d")
draw=ImageDraw.Draw(canvas)
font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf",18)
def xy(p):return ((p[0]-bounds[0])*scale,(bounds[3]-p[1])*scale)
def local(poly):return [xy(p) for p in poly]
for (kind,rid),b in rows.items():
    if kind!="FILL" or b["layerId"]!=2:continue
    rings=[M["ring_path"](p) for p in b["path"]]
    if not M["bb_overlap"](M["bbox"](rings[0]),bounds):continue
    layer=Image.new("RGB",canvas.size,"#183b2b" if b["netName"]=="GND" else "#60234c")
    mask=Image.new("L",canvas.size,0);md=ImageDraw.Draw(mask)
    md.polygon(local(rings[0]),fill=255)
    for ring in rings[1:]:md.polygon(local(ring),fill=0)
    canvas.paste(layer,mask=mask)
draw=ImageDraw.Draw(canvas)
for (kind,rid),b in rows.items():
    if kind in ("LINE","ARC") and b["layerId"]==2:
        a=(b["startX"]*.0254,b["startY"]*.0254);z=(b["endX"]*.0254,b["endY"]*.0254)
        pts=M["arc"](a,z,b["angle"]) if kind=="ARC" else [a,z]
        if M["bb_overlap"](M["bbox"](pts),bounds,1):draw.line(local(pts),fill="#5de290" if b["netName"]=="GND" else "#ef6cda",width=max(1,round(b["width"]*.0254*scale)))
for (kind,rid),b in rows.items():
    if kind!="VIA":continue
    p=(b["centerX"]*.0254,b["centerY"]*.0254)
    if not M["bb_overlap"]((p[0],p[1],p[0],p[1]),bounds,.5):continue
    x,y=xy(p);r=b["viaDiameter"]*.0254*scale/2;h=b["holeDiameter"]*.0254*scale/2
    n=b["netName"];c="#f1d051" if n.startswith("ADC") else "#69e695" if n=="GND" else "#a35fe3"
    draw.ellipse((x-r,y-r,x+r,y+r),fill=c);draw.ellipse((x-h,y-h,x+h,y+h),fill="#10151d")
    if n.startswith("ADC") or n=="GND":draw.text((x+r+3,y-8),n.replace("ADC", "A"),fill=c,font=font)
report_path=ROOT/"output/analysis/adc10-bottom-bucket-feasibility-20261017.json"
if report_path.exists():
    report=json.loads(report_path.read_text())
    for ch in report["channels"]:
        if "requiredWorldPads" not in ch:continue
        p1=ch["requiredWorldPads"]["1"]["xyMm"];p2=ch["requiredWorldPads"]["2"]["xyMm"]
        axis=ch["axisOfPositiveLocalX"]
        for point in (p1,p2):draw.polygon(local(M["rectangle"](point,axis)),outline="#57c9ff",width=4)
        draw.text(xy(ch["centerXYmm"]),ch["ref"],fill="white",font=font)
        draw.line(local([ch["signalConnection"]["startXYmm"],p1]),fill="#57c9ff",width=3)
draw.text((15,15),"BOTTOM copper, top-view projection / mm; yellow=ADC via, green=GND, magenta=other nets",fill="white",font=font)
out=ROOT/"output/analysis/adc10-bottom-copper-search-context-20261017.png"
canvas.save(out)
print(out)
