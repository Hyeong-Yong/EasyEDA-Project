"""OCP/OCCT label-only STEP extraction with geometry round-trip and real meshing.

Original reference and PCB are never modified or exported. Each output is a new
STEP derivative of one named child product, in its unchanged local coordinate
frame. No scaling, geometry construction, booleans, or explicit healing is done.
Native EasyEDA/API/UI is not used.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / ".tools" / "ocp-7.9.3.1.1"
sys.path.insert(0, str(DEPS))
sys.stdout.reconfigure(encoding="utf-8")
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorGen, XCAFDoc_ColorSurf
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE, TopAbs_REVERSED
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRep import BRep_Tool
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from PIL import Image, ImageDraw
import numpy as np

SOURCE = ROOT / "보드 자료" / "MCU_BOARD.step"
DEST = ROOT / "output" / "3d-models-20261018" / "source-models" / "historical-reference-extracted"
AUDIT = json.loads((ROOT / "output" / "3d-models-20261018" / "reference-step-audit.json").read_text(encoding="utf-8"))
SELECTED = [
    "PJ-051BH", "USB_C_USB4105-GF-A", "FTSH-107-01-L-DV-K-A",
    "LQM2MPN2R2NG0L", "SMA_RighAngle_1", "PinSocket_2x05_P2.54mm_Vertical",
    "SOIC-8_3.9x4.9mm_P1.27mm", "SOIC-16_3.9x9.9mm_P1.27mm", "SOT-23", "SOT-223", "TSOT-23-6",
    "QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm", "DFN-6-1EP_3x3mm_P0.95mm_EP1.7x2.6mm",
    "TFBGA-265_14x14mm_Layout17x17_P0.8mm", "TFBGA-90_8X13_ISI", "LAN8742A-CZ-TR",
]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def name_of(label):
    attribute = TDataStd_Name()
    return attribute.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attribute) else ""

def read_document(path):
    doc = TDocStd_Document(TCollection_ExtendedString("Isolated-STEP-model"))
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetLayerMode(True)
    assert reader.ReadFile(str(path)) == IFSelect_RetDone, path
    assert reader.Transfer(doc), path
    return doc, XCAFDoc_DocumentTool.ShapeTool_s(doc.Main()), XCAFDoc_DocumentTool.ColorTool_s(doc.Main())

def sequence_to_list(seq):
    return [seq.Value(i) for i in range(1, seq.Length()+1)]

def topology_count(shape, typ):
    explorer = TopExp_Explorer(shape, typ)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count

def geometry(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    values = list(box.Get())
    volume, area = GProp_GProps(), GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume, True, False, False)
    BRepGProp.SurfaceProperties_s(shape, area, False, False)
    return dict(brep_valid=bool(BRepCheck_Analyzer(shape).IsValid()),
                solids=topology_count(shape, TopAbs_SOLID), faces=topology_count(shape, TopAbs_FACE),
                edge_occurrences=topology_count(shape, TopAbs_EDGE),
                analytic_bounds_mm=dict(min=values[:3], max=values[3:], span=[values[i+3]-values[i] for i in range(3)]),
                closed_volume_mm3=volume.Mass(), surface_area_mm2=area.Mass())

def label_color(colors, label, fallback=None):
    value = Quantity_Color()
    for typ in [XCAFDoc_ColorSurf, XCAFDoc_ColorGen]:
        if colors.GetColor_s(label, typ, value):
            return tuple(value.Values(Quantity_TOC_RGB))
    return fallback

def shape_color(colors, shape, fallback):
    value = Quantity_Color()
    for typ in [XCAFDoc_ColorSurf, XCAFDoc_ColorGen]:
        if colors.GetColor(shape, typ, value):
            return tuple(value.Values(Quantity_TOC_RGB)), True
        if colors.GetColor(shape.Located(TopLoc_Location()), typ, value):
            return tuple(value.Values(Quantity_TOC_RGB)), True
    return fallback, False

def leaves(tool, label, parent_location=TopLoc_Location(), inherited=None):
    color = label_color(active_colors, label, inherited)
    if tool.IsReference_s(label):
        from OCP.TDF import TDF_Label
        target = TDF_Label()
        assert tool.GetReferredShape_s(label, target)
        yield from leaves(tool, target, parent_location.Multiplied(tool.GetLocation_s(label)), color)
    elif tool.IsAssembly_s(label):
        child_seq = TDF_LabelSequence()
        tool.GetComponents_s(label, child_seq, False)
        for child in sequence_to_list(child_seq):
            yield from leaves(tool, child, parent_location, color)
    else:
        yield tool.GetShape_s(label), parent_location, color

def mesh_model(tool, colors, label, output_dir):
    global active_colors
    active_colors = colors
    vertices, triangles, tri_colors = [], [], []
    faces_total = faces_meshed = direct_color_faces = inherited_color_faces = default_color_faces = 0
    for shape, product_location, inherited in leaves(tool, label):
        mesh = BRepMesh_IncrementalMesh(shape, 0.025, False, 0.25, True)
        assert mesh.IsDone(), "OpenCASCADE meshing failed"
        explorer = TopExp_Explorer(shape, TopAbs_FACE)
        while explorer.More():
            faces_total += 1
            face = TopoDS.Face_s(explorer.Current())
            local_location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation_s(face, local_location)
            if triangulation is not None:
                faces_meshed += 1
                fallback = inherited if inherited is not None else (0.65, 0.65, 0.65)
                color, has_face_color = shape_color(colors, face, fallback)
                direct_color_faces += int(has_face_color)
                inherited_color_faces += int(not has_face_color and inherited is not None)
                default_color_faces += int(not has_face_color and inherited is None)
                transform = product_location.Multiplied(local_location).Transformation()
                offset = len(vertices)
                for i in range(1, triangulation.NbNodes()+1):
                    point = triangulation.Node(i).Transformed(transform)
                    vertices.append((point.X(), point.Y(), point.Z()))
                for i in range(1, triangulation.NbTriangles()+1):
                    a, b, c = triangulation.Triangle(i).Get()
                    if face.Orientation() == TopAbs_REVERSED:
                        b, c = c, b
                    triangles.append((offset+a-1, offset+b-1, offset+c-1))
                    tri_colors.append(color)
            explorer.Next()
    assert faces_total == faces_meshed and triangles
    materials = sorted(set(tri_colors))
    lookup = {rgb: i for i, rgb in enumerate(materials)}
    with (output_dir / "triangulated.obj").open("w", encoding="ascii") as stream:
        stream.write("# OpenCASCADE actual surface triangulation; model-local mm coordinates\nmtllib triangulated.mtl\n")
        for point in vertices:
            stream.write("v %.10g %.10g %.10g\n" % point)
        current = None
        for indices, rgb in zip(triangles, tri_colors):
            material = lookup[rgb]
            if material != current:
                stream.write(f"usemtl m{material}\n")
                current = material
            stream.write("f %d %d %d\n" % tuple(i+1 for i in indices))
    with (output_dir / "triangulated.mtl").open("w", encoding="ascii") as stream:
        for i, rgb in enumerate(materials):
            stream.write(f"newmtl m{i}\nKd {rgb[0]:.7g} {rgb[1]:.7g} {rgb[2]:.7g}\nKa 0.1 0.1 0.1\n\n")
    # Software-only orthographic preview from the actual OCCT triangles. No UI.
    right, up, eye = [1/math.sqrt(2), 1/math.sqrt(2), 0], [-1/math.sqrt(6), 1/math.sqrt(6), 2/math.sqrt(6)], [1/math.sqrt(3), -1/math.sqrt(3), 1/math.sqrt(3)]
    projected = [tuple(sum(point[i]*basis[i] for i in range(3)) for basis in [right, up, eye]) for point in vertices]
    lo = [min(v[i] for v in projected) for i in range(2)]
    hi = [max(v[i] for v in projected) for i in range(2)]
    scale = 580 / max(hi[0]-lo[0], hi[1]-lo[1])
    image = Image.new("RGB", (720, 720), "#f2f5f8")
    draw = ImageDraw.Draw(image)
    pixels = np.array(image)
    depth_buffer = np.full((720, 720), -np.inf)
    for i in range(len(triangles)):
        ids = triangles[i]
        a, b, c = [vertices[n] for n in ids]
        ab, ac = [b[k]-a[k] for k in range(3)], [c[k]-a[k] for k in range(3)]
        normal = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
        length = math.sqrt(sum(v*v for v in normal))
        shade = 0.55 + 0.45*abs(sum(normal[k]*eye[k] for k in range(3))/length) if length else 0.75
        rgb = tuple(round(255*max(0, min(1, v))*shade) for v in tri_colors[i])
        polygon = [(360+(projected[n][0]-(lo[0]+hi[0])/2)*scale, 360-(projected[n][1]-(lo[1]+hi[1])/2)*scale) for n in ids]
        x0, y0 = polygon[0]
        x1, y1 = polygon[1]
        x2, y2 = polygon[2]
        xmin, xmax = max(0, math.floor(min(x0, x1, x2))), min(719, math.ceil(max(x0, x1, x2)))
        ymin, ymax = max(0, math.floor(min(y0, y1, y2))), min(719, math.ceil(max(y0, y1, y2)))
        denominator = (y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
        if abs(denominator) < 1e-10 or xmin > xmax or ymin > ymax:
            continue
        yy, xx = np.mgrid[ymin:ymax+1, xmin:xmax+1]
        first = ((y1-y2)*(xx-x2)+(x2-x1)*(yy-y2))/denominator
        second = ((y2-y0)*(xx-x2)+(x0-x2)*(yy-y2))/denominator
        third = 1-first-second
        depth = first*projected[ids[0]][2]+second*projected[ids[1]][2]+third*projected[ids[2]][2]
        region = depth_buffer[ymin:ymax+1, xmin:xmax+1]
        visible = (first >= -1e-8) & (second >= -1e-8) & (third >= -1e-8) & (depth > region)
        region[visible] = depth[visible]
        pixels[ymin:ymax+1, xmin:xmax+1][visible] = rgb
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    draw.text((18, 15), name_of(label), fill="#243448")
    draw.text((18, 690), "OCCT triangulation; local mm frame; not present-board placement", fill="#33475a")
    image.save(output_dir / "preview.png")
    return dict(vertices=len(vertices), triangles=len(triangles), faces=faces_total, faces_meshed=faces_meshed,
                meshing_linear_deflection_mm=0.025, meshing_angular_deflection_rad=0.25,
                direct_color_faces=direct_color_faces, inherited_color_faces=inherited_color_faces,
                default_preview_gray_faces=default_color_faces, material_colors_rgb=[list(v) for v in materials],
                preview_note="Software orthographic render with per-pixel depth buffer from OCCT triangles; STEP retains source style metadata independently. No guessed geometry.")

Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
Interface_Static.SetCVal_s("write.step.unit", "MM")
Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
if "--preview-canonical" in sys.argv:
    for family in ["canonical-reference-models", "canonical-pinregistered-models"]:
        manifest_path = DEST.parent / family / "canonical-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest["models"]:
            path = ROOT / item["path"]
            checked_doc, checked_tool, checked_colors = read_document(path)
            free = TDF_LabelSequence()
            checked_tool.GetFreeShapes(free)
            assert free.Length() == 1
            item["mesh"] = mesh_model(checked_tool, checked_colors, free.Value(1), path.parent)
            item["generated_files"] = [dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size, sha256=sha(p))
                                       for p in [path.parent / "triangulated.obj", path.parent / "triangulated.mtl", path.parent / "preview.png"]]
            print("Canonical preview", family, item["ref"], flush=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.exit(0)
if "--manufacturer-only" in sys.argv:
    manufacturer = ROOT / "output" / "3d-models-20261018" / "source-models" / "manufacturer" / "LINK-PP-LPJE101-0AHNL"
    original = manufacturer / "extracted" / "LPJE101-0AHNL.STEP"
    original_hash = sha(original)
    official_doc, official_tool, official_colors = read_document(original)
    free = TDF_LabelSequence()
    official_tool.GetFreeShapes(free)
    analysis = dict(source_path=str(original.relative_to(ROOT)), source_sha256=original_hash,
                    policy="Original official STEP parsed only; no reserialization or modification. OBJ/MTL/PNG are explicitly derived meshes.", roots=[])
    for i, label in enumerate(sequence_to_list(free), 1):
        folder = manufacturer / "derived-analysis" / f"root{i}"
        folder.mkdir(parents=True, exist_ok=True)
        item = dict(name=name_of(label), geometry=geometry(official_tool.GetShape_s(label)),
                    mesh=mesh_model(official_tool, official_colors, label, folder))
        item["generated_files"] = [dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=sha(path))
                                   for path in [folder / "triangulated.obj", folder / "triangulated.mtl", folder / "preview.png"]]
        analysis["roots"].append(item)
    assert sha(original) == original_hash
    (manufacturer / "kernel-analysis.json").write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False), flush=True)
    sys.exit(0)
if "--preview-only" in sys.argv:
    manifest_path = DEST / "source-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["models"]:
        output = ROOT / item["path"]
        round_doc, round_tool, round_colors = read_document(output)
        free = TDF_LabelSequence()
        round_tool.GetFreeShapes(free)
        assert free.Length() == 1
        item["mesh"] = mesh_model(round_tool, round_colors, free.Value(1), output.parent)
        item["generated_files"] = [dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=sha(path))
                                  for path in [output.parent / "triangulated.obj", output.parent / "triangulated.mtl", output.parent / "preview.png"]]
        print("Depth-buffer preview", item["product"], flush=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    sys.exit(0)
doc, shapes, colors = read_document(SOURCE)
labels_seq = TDF_LabelSequence()
shapes.GetShapes(labels_seq)
by_name = {name_of(label): label for label in sequence_to_list(labels_seq)}
DEST.mkdir(parents=True, exist_ok=True)
manifest = dict(source=str(SOURCE), source_sha256=sha(SOURCE), source_bytes=SOURCE.stat().st_size,
                serializer="cadquery-ocp7.9.3.1.1 / OpenCASCADE7.9.3 / STEPCAFControl reader+writer selected label",
                dependency_install_report="output/3d-models-20261018/ocp-dependency-install-report.json",
                source_provenance="User-supplied historical KiCad electronic assembly, exported2026-10-02. Per-model upstream licences were not embedded/verified; no public redistribution right assumed.",
                geometry_policy="Preserve imported child BRep and nested transforms in original local millimetre frame. No scaling, rotations, dimension edits, simplification, booleans, or explicit healing. STEP file bytes/entities are reserialized, not byte-identical originals.",
                interpretation="Historical model labels are evidence only. They do not certify current BOM equivalence. Current-board binding must use separately validated footprint/placement transforms.",
                validation_policy="Round-trip analytic bbox maxdelta<=1e-5mm, same solid/face counts, relative volume/area<=1e-7, and BRep validity status. Complete OCCT face triangulation required. Any failed condition stays explicit.",
                excluded="Historical PCB, TR1H1102NL, SW1TS1150S, and C41Kemet1.2mm are not exported by this script.", models=[])
for name in SELECTED:
    label = by_name[name]
    shape = shapes.GetShape_s(label)
    before = geometry(shape)
    folder = DEST / name
    folder.mkdir(parents=True, exist_ok=True)
    output = folder / f"{name}.step"
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    writer.SetLayerMode(True)
    writer.SetPropsMode(True)
    assert writer.Transfer(label), name
    assert writer.Write(str(output)) == IFSelect_RetDone, name
    round_doc, round_tool, round_colors = read_document(output)
    free = TDF_LabelSequence()
    round_tool.GetFreeShapes(free)
    assert free.Length() == 1, name
    round_label = free.Value(1)
    after = geometry(round_tool.GetShape_s(round_label))
    flat_before = before["analytic_bounds_mm"]["min"] + before["analytic_bounds_mm"]["max"]
    flat_after = after["analytic_bounds_mm"]["min"] + after["analytic_bounds_mm"]["max"]
    bbox_delta = max(abs(a-b) for a, b in zip(flat_before, flat_after))
    relative = lambda key: abs(after[key]-before[key])/max(abs(before[key]), 1e-12)
    output_text = output.read_text(encoding="utf-8", errors="replace")
    assert "MCU_BOARD_v19_260616_PCB" not in output_text and "MCU_BOARD 1" not in output_text
    checks = dict(single_product_root=True, no_historical_PCB=True, bbox_max_delta_mm=bbox_delta,
                  same_solids=before["solids"] == after["solids"], same_faces=before["faces"] == after["faces"],
                  volume_relative_delta=relative("closed_volume_mm3"), area_relative_delta=relative("surface_area_mm2"))
    checks["pass"] = bool(checks["same_solids"] and checks["same_faces"] and bbox_delta <= 1e-5 and checks["volume_relative_delta"] <= 1e-7 and checks["area_relative_delta"] <= 1e-7 and after["brep_valid"])
    audit_product = next(item for item in AUDIT["product_catalog"] if item["product"] == name)
    historical_occurrences = [item for item in AUDIT["top_level_occurrences"] if item["product"] == name]
    mesh = mesh_model(round_tool, round_colors, round_label, folder)
    item = dict(product=name, source_product_definition_entity=audit_product["product_definition_entity"],
                historical_ref_placements=historical_occurrences,
                path=str(output.relative_to(ROOT)), bytes=output.stat().st_size, sha256=sha(output),
                input_geometry=before, roundtrip_geometry=after, checks=checks,
                output_colour_rgb_entities=len(re.findall(r"COLOUR_RGB\(", output_text)),
                explicit_output_mm_unit="SI_UNIT(.MILLI.,.METRE.)" in re.sub(r"\s+", "", output_text),
                mesh=mesh,
                generated_files=[dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=sha(path))
                                 for path in [folder / "triangulated.obj", folder / "triangulated.mtl", folder / "preview.png"]])
    manifest["models"].append(item)
    print(json.dumps(dict(product=name, valid=after["brep_valid"], roundtrip_pass=checks["pass"],
                          span_mm=after["analytic_bounds_mm"]["span"], triangles=mesh["triangles"], colors=item["output_colour_rgb_entities"])), flush=True)
    (DEST / "source-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
assert sha(SOURCE) == manifest["source_sha256"], "Original reference changed"
print(json.dumps(dict(models=len(manifest["models"]), all_pass=all(item["checks"]["pass"] for item in manifest["models"]), original_unchanged=True)), flush=True)
