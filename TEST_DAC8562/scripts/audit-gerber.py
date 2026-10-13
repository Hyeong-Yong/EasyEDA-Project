"""Render this project's native Gerbers and audit outline/drill/export coverage.

This deliberately supports only the primitives emitted by the inspected EasyEDA
export. Unknown records or aperture shapes are errors, not silently skipped.
"""
import json
import math
import re
import sys
import zipfile
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFilter

root = Path(__file__).resolve().parents[1]
out = root / "output/pcb-two-zone"
scale = 24
size = (102 * scale, 102 * scale)


def pixel(p):
    return ((p[0] + 1) * scale, (101 - p[1]) * scale)


def render(text, vector=False):
    geometry = []
    if vector:
        sys.path.insert(0, str(root / ".tools/pcb-python"))
        from shapely.geometry import LineString, Point, Polygon, box
        from shapely.ops import unary_union
    apertures, unknown, coords = {}, [], []
    image = Image.new("1", size)
    drawer = ImageDraw.Draw(image)
    selected, last, region, contours, operation, interpolation = None, (0, 0), False, [], 2, 1
    stats = {"regions": 0, "flashes": 0, "draws": 0}
    for record in re.findall(r"%[^%]*%|[^%*]+\*", text):
        record = record.strip()
        if not record:
            continue
        if record.startswith("%AMRoundRect*"):
            continue
        m = re.fullmatch(r"%ADD(\d+)([A-Za-z]+),([^*]+)\*%", record)
        if m:
            shape = m[2]
            values = [float(x) for x in m[3].split("X")]
            if shape not in ("C", "R", "O", "RoundRect"):
                unknown.append(record)
            apertures[int(m[1])] = (shape, values)
            continue
        if record.startswith(("G04", "%FSLAX26Y26", "%MOMM")) or record in ("G75*", "M02*"):
            continue
        m = re.fullmatch(r"(?:G54)?D(\d+)\*", record)
        if m and int(m[1]) >= 10:
            selected = int(m[1])
            continue
        if record == "G36*":
            region, contours = True, []
            continue
        if record == "G37*":
            region = False
            fill = Image.new("1", size)
            for contour in contours:
                if len(contour) < 3:
                    continue
                layer = Image.new("1", size)
                ImageDraw.Draw(layer).polygon([pixel(p) for p in contour], fill=1)
                fill = ImageChops.logical_xor(fill, layer)
            if vector:
                polygon = Polygon()
                for contour in contours:
                    if len(contour) >= 3:
                        polygon = polygon.symmetric_difference(Polygon(contour).buffer(0))
                geometry.append(polygon)
            image = ImageChops.logical_or(image, fill)
            drawer = ImageDraw.Draw(image)
            stats["regions"] += 1
            continue
        m = re.fullmatch(r"(?:G0([123]))?(?:X(-?\d+))?(?:Y(-?\d+))?(?:I(-?\d+))?(?:J(-?\d+))?(?:D0([123]))?\*", record)
        if not m or not any(m.groups()):
            unknown.append(record)
            continue
        if m[1]:
            interpolation = int(m[1])
        point = (int(m[2]) / 1e6 if m[2] else last[0], int(m[3]) / 1e6 if m[3] else last[1])
        if m[6]:
            operation = int(m[6])
        coords.append(point)
        if operation == 2:
            if region:
                contours.append([point])
            last = point
            continue
        shape, values = ("C", [0]) if region else apertures[selected]
        if operation == 3:
            x, y = pixel(point)
            if shape == "RoundRect":
                radius, x1, y1, x2, y2 = values
                width, height = 2 * max(abs(x1), abs(x2)) + radius, 2 * max(abs(y1), abs(y2)) + radius
                drawer.rounded_rectangle((x-width*scale/2,y-height*scale/2,x+width*scale/2,y+height*scale/2), radius=radius*scale/2, fill=1)
                if vector:
                    px, py = point
                    geometry.append(box(px-width/2+radius/2,py-height/2+radius/2,px+width/2-radius/2,py+height/2-radius/2).buffer(radius/2,quad_segs=32))
            else:
                width = values[0]
                height = values[1] if len(values) > 1 else width
                flash_box = (x-width*scale/2,y-height*scale/2,x+width*scale/2,y+height*scale/2)
                if shape == "C":
                    drawer.ellipse(flash_box, fill=1)
                    if vector:
                        geometry.append(Point(point).buffer(width/2,quad_segs=64))
                elif shape == "R":
                    drawer.rectangle(flash_box, fill=1)
                    if vector:
                        from shapely.geometry import box as shape_box
                        geometry.append(shape_box(point[0]-width/2,point[1]-height/2,point[0]+width/2,point[1]+height/2))
                elif shape == "O":
                    drawer.rounded_rectangle(flash_box, radius=min(width,height)*scale/2, fill=1)
                    if vector:
                        radius = min(width,height)/2
                        dx,dy = max(0,width/2-radius),max(0,height/2-radius)
                        geometry.append(LineString([(point[0]-dx,point[1]-dy),(point[0]+dx,point[1]+dy)]).buffer(radius,quad_segs=64))
            stats["flashes"] += 1
        elif operation == 1:
            path = [last, point]
            if interpolation != 1:
                center = (last[0] + (int(m[4]) / 1e6 if m[4] else 0), last[1] + (int(m[5]) / 1e6 if m[5] else 0))
                radius = math.dist(last, center)
                begin = math.atan2(last[1]-center[1],last[0]-center[0])
                end = math.atan2(point[1]-center[1],point[0]-center[0])
                delta = (end-begin) % (2*math.pi) if interpolation == 3 else -((begin-end) % (2*math.pi))
                if abs(delta) < 1e-10:
                    delta = 2*math.pi if interpolation == 3 else -2*math.pi
                steps = max(4, math.ceil(abs(delta)*radius*scale))
                path = [(center[0]+radius*math.cos(begin+delta*i/steps),center[1]+radius*math.sin(begin+delta*i/steps)) for i in range(steps+1)]
                path[0], path[-1] = last, point
            if region:
                contours[-1].extend(path[1:])
            else:
                if shape != "C":
                    unknown.append("Noncircular stroked aperture: " + record)
                width = max(1, round(values[0]*scale))
                pixels = [pixel(p) for p in path]
                drawer.line(pixels, fill=1, width=width)
                for x,y in [pixels[0],pixels[-1]]:
                    drawer.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=1)
                if vector:
                    geometry.append(LineString(path).buffer(values[0]/2,quad_segs=16))
            stats["draws"] += 1
        last = point
    if unknown:
        raise ValueError(unknown[:10])
    stats["coordinateBoundsMm"] = [min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]
    return image, stats, unary_union(geometry) if vector else None


def audit(archive, prefix="gerber", expected_vias=133):
  with zipfile.ZipFile(archive) as z:
    layers = {}
    stats = {}
    for suffix in ["GTL", "GBL", "GTO", "GTS", "GKO"]:
        name = next(n for n in z.namelist() if n.endswith("." + suffix))
        layers[suffix], stats[suffix], _ = render(z.read(name).decode())
    drill = z.read("Drill_NPTH_Through.DRL").decode()
    holes = [(float(x),float(y)) for x,y in re.findall(r"X(-?[\d.]+)Y(-?[\d.]+)",drill)]
    plated = z.read("Drill_PTH_Through.DRL").decode()
    via = z.read("Drill_PTH_Through_Via.DRL").decode()
    pth_positions = re.findall(r"X(-?[\d.]+)Y(-?[\d.]+)",plated)
    via_positions = re.findall(r"X(-?[\d.]+)Y(-?[\d.]+)",via)
    assert stats["GKO"]["coordinateBoundsMm"] == [0,0,100.000001,100.000001]
    assert len(holes) == 4
    assert all(min(math.dist(h,q) for q in [(5,5),(95,5),(5,95),(95,95)]) < 1e-4 for h in holes)
    assert len(via_positions) == expected_vias and len(set(via_positions)) == expected_vias
    assert all(p in pth_positions for p in via_positions)
    assert stats["GTL"]["regions"] == stats["GBL"]["regions"] == 3
    copper = layers["GTL"].convert("L")
    bottom = layers["GBL"].convert("L")
    silk = layers["GTO"].convert("L")
    mask = layers["GTS"].convert("L")
    guard = mask.filter(ImageFilter.MaxFilter(7))
    collision = ImageChops.multiply(silk, guard)
    board = Image.new("L", size)
    ImageDraw.Draw(board).rectangle((scale,scale,101*scale,101*scale),fill=255)
    collision = ImageChops.multiply(collision,board)
    overlap_px = sum(collision.histogram()[1:])
    preview = Image.new("RGB",size,"#102c26")
    preview.paste("#264939",mask=bottom)
    preview.paste("#3c8061",mask=copper)
    preview.paste("#d4bb73",mask=mask)
    preview.paste("#f4f5df",mask=silk)
    draw = ImageDraw.Draw(preview)
    for x,y in pth_positions:
        px,py = pixel((float(x),float(y)))
        draw.ellipse((px-3,py-3,px+3,py+3),fill="#0b1511")
    for x,y in holes:
        px,py = pixel((x,y)); r=3.200001/2*scale
        draw.ellipse((px-r,py-r,px+r,py+r),fill="#0b1511")
    preview.paste("#b4d4c3",mask=layers["GKO"].convert("L"))
    preview.save(out / (prefix + "-top-preview.png"))
    highlighted = preview.copy()
    highlighted.paste("#ff2860",mask=collision)
    highlighted.save(out / (prefix + "-silkscreen-mask-audit.png"))
    result = {"status":"Native Gerber export parsed; visual review required","layers":stats,"npthHolesMm":holes,"viaDrillCount":len(via_positions),"platedDrillCount":len(pth_positions),"viaDrillsIncludedInCombinedPthFile":True,"silkscreenWithinApprox015mmOfMaskPixels":overlap_px,"pixelSizeMm":1/scale,"unsupportedRecords":0,"files":[{"name":n,"bytes":len(z.read(n))} for n in z.namelist()]}
    (out / (prefix + "-audit.json")).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({k:v for k,v in result.items() if k != "files"},indent=2))
    return result


if __name__ == "__main__":
    audit(out / "DAC8562_DAC_MCU_100x100_Gerber.zip")
