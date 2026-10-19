"""Canonical board-Z-up variants using historical rigid assembly transforms.

No original/reference files or native CAD documents are modified. Translation
registration uses measured historical PCB minimum XY and current frozen component
origins; original child geometry/style data are cloned into new XCAF documents.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".tools" / "ocp-7.9.3.1.1"))
sys.stdout.reconfigure(encoding="utf-8")
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_LabelSequence
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Editor
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopAbs import TopAbs_SOLID, TopAbs_FACE, TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Trsf, gp_Pln, gp_Pnt, gp_Dir
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder

SOURCE = ROOT / "보드 자료" / "MCU_BOARD.step"
OUT = ROOT / "output" / "3d-models-20261018" / "source-models" / "canonical-reference-models"
AUDIT = json.loads((ROOT / "output" / "3d-models-20261018" / "reference-step-audit.json").read_text(encoding="utf-8"))
COMPONENTS = {item["ref"]: item for item in json.loads((ROOT / "output" / "3d-models-20261018" / "inventory" / "components-437.json").read_text(encoding="utf-8"))}
REFS = ["CN1", "CN3", "CN4", "J1", "L1", "J13"]
PIN_REGISTERED = "--pin-registered" in sys.argv
if PIN_REGISTERED:
    OUT = OUT.parent / "canonical-pinregistered-models"
    REFS = ["CN1", "J1", "J13"]

def name_of(label):
    attr = TDataStd_Name()
    return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""

def sequence(seq):
    return [seq.Value(i) for i in range(1, seq.Length()+1)]

def new_doc():
    return TDocStd_Document(TCollection_ExtendedString("Canonical-component"))

def read_document(path):
    doc = new_doc()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    assert reader.ReadFile(str(path)) == IFSelect_RetDone
    assert reader.Transfer(doc)
    return doc, XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())

def shape_bounds(shape):
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    v = list(box.Get())
    return dict(min_mm=v[:3], max_mm=v[3:], span_mm=[v[i+3]-v[i] for i in range(3)])

def count(shape, typ):
    ex, result = TopExp_Explorer(shape, typ), 0
    while ex.More():
        result += 1
        ex.Next()
    return result

def shape_stats(shape):
    volume = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, volume, True, False, False)
    return dict(bounds=shape_bounds(shape), solids=count(shape, TopAbs_SOLID), faces=count(shape, TopAbs_FACE),
                brep_valid=bool(BRepCheck_Analyzer(shape).IsValid()), volume_mm3=volume.Mass())

def section_groups(shape, z):
    section = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)), False)
    section.Build()
    assert section.IsDone()
    edges = []
    ex = TopExp_Explorer(section.Shape(), TopAbs_EDGE)
    while ex.More():
        edge = TopoDS.Edge_s(ex.Current())
        ends = []
        for vertex in [TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge)]:
            if not vertex.IsNull():
                p = BRep_Tool.Pnt_s(vertex)
                ends.append(tuple(round(v, 6) for v in [p.X(), p.Y(), p.Z()]))
        edges.append((edge, set(ends)))
        ex.Next()
    groups = []
    while edges:
        seed, endpoints = edges.pop()
        group = [seed]
        changed = True
        while changed:
            changed = False
            for i in range(len(edges)-1, -1, -1):
                edge, other_ends = edges[i]
                if endpoints.intersection(other_ends):
                    group.append(edge)
                    endpoints.update(other_ends)
                    edges.pop(i)
                    changed = True
        box = Bnd_Box()
        for edge in group:
            BRepBndLib.AddOptimal_s(edge, box, False, False)
        values = list(box.Get())
        groups.append(dict(edges=len(group), bbox_mm=values, xy_bbox_center_mm=[(values[i]+values[i+3])/2 for i in range(2)]))
    return sorted(groups, key=lambda item: tuple(item["xy_bbox_center_mm"]))

def feature_planes_and_cylinders(shape):
    planes, vertical_planes, cylinders = [], [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        face = TopoDS.Face_s(ex.Current())
        surface = BRepAdaptor_Surface(face)
        area = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, area)
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            normal = plane.Axis().Direction()
            origin = plane.Location()
            if abs(normal.Z()) > 0.999999 and area.Mass() > 0.02:
                planes.append(dict(z_mm=origin.Z(), area_mm2=area.Mass(), bbox=shape_bounds(face)))
            elif (abs(normal.X()) > 0.999999 or abs(normal.Y()) > 0.999999) and area.Mass() > 1:
                vertical_planes.append(dict(origin_mm=[origin.X(), origin.Y(), origin.Z()], normal=[normal.X(), normal.Y(), normal.Z()], area_mm2=area.Mass(), bbox=shape_bounds(face)))
        elif surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            axis = cylinder.Axis()
            direction, origin = axis.Direction(), axis.Location()
            if abs(direction.Z()) > 0.999999:
                cylinders.append(dict(radius_mm=cylinder.Radius(), axis_xy_mm=[origin.X(), origin.Y()], bbox=shape_bounds(face)))
        ex.Next()
    return dict(horizontal_planar_faces=sorted(planes, key=lambda x:(round(x["z_mm"],5), -x["area_mm2"])),
                vertical_planar_faces=vertical_planes, vertical_cylinders=cylinders)

Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
Interface_Static.SetCVal_s("write.step.unit", "MM")
Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
if "--canonicalize-manufacturer" in sys.argv:
    parent = ROOT / "output" / "3d-models-20261018" / "source-models"
    original = parent / "manufacturer" / "LINK-PP-LPJE101-0AHNL" / "extracted" / "LPJE101-0AHNL.STEP"
    folder = parent / "canonical-manufacturer-models" / "CN2"
    output = folder / "CN2_LPJE101-0AHNL_board-Zup-approx-registered.step"
    if output.exists():
        raise RuntimeError("Unique canonical manufacturer output already exists; refusing overwrite")
    source_hash = hashlib.sha256(original.read_bytes()).hexdigest()
    official_doc, official_tool = read_document(original)
    free = TDF_LabelSequence()
    official_tool.GetFreeShapes(free)
    assert free.Length() == 1
    original_label = free.Value(1)
    matrix = [[0,0,1,-5.2281420008],[1,0,0,0],[0,1,0,6.55],[0,0,0,1]]
    transform = gp_Trsf()
    transform.SetValues(*[v for row in matrix[:3] for v in row])
    expected = official_tool.GetShape_s(original_label).Moved(TopLoc_Location(transform))
    newdoc = new_doc()
    assert XCAFDoc_Editor.Extract_s(original_label, newdoc.Main())
    newtool = XCAFDoc_DocumentTool.ShapeTool_s(newdoc.Main())
    copied = TDF_LabelSequence()
    newtool.GetFreeShapes(copied)
    assert copied.Length() == 1
    wrapper = newtool.NewShape()
    TDataStd_Name.Set_s(wrapper, TCollection_ExtendedString("CN2_LPJE101-0AHNL_APPROX_board_Zup_registered"))
    newtool.AddComponent(wrapper, copied.Value(1), TopLoc_Location(transform))
    newtool.UpdateAssemblies()
    folder.mkdir(parents=True, exist_ok=True)
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    assert writer.Transfer(wrapper)
    assert writer.Write(str(output)) == IFSelect_RetDone
    checkdoc, checktool = read_document(output)
    checked = TDF_LabelSequence()
    checktool.GetFreeShapes(checked)
    assert checked.Length() == 1
    before, after = shape_stats(expected), shape_stats(checktool.GetShape_s(checked.Value(1)))
    bboxdelta = max(abs(a-b) for key in ["min_mm", "max_mm"] for a,b in zip(before["bounds"][key],after["bounds"][key]))
    volumedelta = abs(before["volume_mm3"]-after["volume_mm3"])/max(abs(before["volume_mm3"]),1e-12)
    result = dict(ref="CN2", product="LPJE101-0AHNL", source=str(original.relative_to(ROOT)), source_sha256=source_hash,
                  source_product_page="https://www.l-p.com/products/457326.htm", source_zip_url="https://www.l-p.com/upload/file/2023/03-15/020654246.zip",
                  rigid_transform_local_to_canonical_mm=matrix, canonical_stats=after,
                  relation="Manufacturer-linked exact-MPN CAD with APPROXIMATE footprint registration and inferred seating datum; not certified mechanical fit.",
                  registration_evidence="Retaining-post centerplane localZ10.29→current footprint locatorX5.0618579992; localX+/-6.35→currentY+/-6.35. SourceY=-6.55 seating candidate reproduces drawing13.1mm body height. This datum is geometry/drawing-supported inference, not an explicit vendor Mpoint.",
                  limitations=["Signal pitch1.02mm vs footprint1.016mm: up to0.014mmY residual.","Shield-leg centers+/-8.225mm vs current+/-8.128mm:0.097mm residual.","CAD sidewall span16.55mm vs official drawing16.26mm.","Metric rounding leaves up to0.005mmX pin-row/LED registration residual.","Full bounds include extended EMI springs; do not shrink to nominal enclosure dimensions."],
                  path=str(output.relative_to(ROOT)), bytes=output.stat().st_size, sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  checks=dict(brep_valid=after["brep_valid"], same_solids=before["solids"]==after["solids"], same_faces=before["faces"]==after["faces"], bbox_maxdelta_mm=bboxdelta, volume_relative_delta=volumedelta))
    result["checks"]["pass"] = bool(after["brep_valid"] and result["checks"]["same_solids"] and result["checks"]["same_faces"] and bboxdelta<=1e-5 and volumedelta<=1e-7)
    assert result["checks"]["pass"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == source_hash
    (folder / "canonical-manifest.json").write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False),flush=True)
    sys.exit(0)
if "--manufacturer-features" in sys.argv:
    folder = ROOT / "output" / "3d-models-20261018" / "source-models" / "manufacturer" / "LINK-PP-LPJE101-0AHNL"
    path = folder / "extracted" / "LPJE101-0AHNL.STEP"
    official_doc, official_tool = read_document(path)
    free = TDF_LabelSequence()
    official_tool.GetFreeShapes(free)
    assert free.Length() == 1
    official_shape = official_tool.GetShape_s(free.Value(1))
    orientation = gp_Trsf()
    orientation.SetValues(0,0,1,0, 1,0,0,0, 0,1,0,0)
    proposed_zup = official_shape.Moved(TopLoc_Location(orientation))
    result = dict(source=str(path.relative_to(ROOT)), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  geometry=shape_stats(official_shape), features=feature_planes_and_cylinders(official_shape),
                  sections={str(z):section_groups(official_shape,z) for z in [0.1, 2.0, 2.7, 2.9]},
                  proposed_Zup=dict(rotation=[[0,0,1],[1,0,0],[0,1,0]], geometry=shape_stats(proposed_zup),
                    features=feature_planes_and_cylinders(proposed_zup),
                    sections={str(z):section_groups(proposed_zup,z) for z in [-8.9,-7.0,-6.7,-6.55,-6.35]}))
    (folder / "datum-analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(dict(geometry=result["geometry"], proposed_Zup=result["proposed_Zup"]["geometry"], sections=result["proposed_Zup"]["sections"]), ensure_ascii=False), flush=True)
    sys.exit(0)
doc, shapes = read_document(SOURCE)
all_labels = TDF_LabelSequence()
shapes.GetShapes(all_labels)
labels = {name_of(label): label for label in sequence(all_labels)}
pcb_shape = shapes.GetShape_s(labels["MCU_BOARD_v19_260616_PCB"])
pcb_bounds = shape_bounds(pcb_shape)
board_xmin, board_ymin = pcb_bounds["min_mm"][:2]
mount_datum = 1.555
OUT.mkdir(parents=True, exist_ok=True)
manifest = dict(source=str(SOURCE), source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                historical_PCB_bounds_mm=pcb_bounds,
                board_coordinate_registration=dict(x_shift_mm=-board_xmin, y_shift_mm=-board_ymin,
                    evidence="Historical PCB minimum XY→current board-relative zero. Independently cross-checked by unchanged J1 and L1 origins; current per-reference footprints contain baked offsets."),
                up_axis_evidence="Historical PCB spans Z0..1.47; top-side source component placement origin/body datum is Z1.555 for CN1/CN3/J1/L1. PCB underside is Z0. This source datum is0.085mm above substrate top, not identical to physical contact seating for every model: J1 SMTcontact bottoms are1.1486 and require+0.4064Z correction in the separate contactregistered variant.",
                mount_datum_source_Z_mm=mount_datum,
                policy="Rigid assembly transform only, no scale/mirror/dimension edits. Full source rotation is applied. New Z0 means historical component seating datum1.555. XY is registered to each current frozen component origin; models are therefore per-reference canonical variants, not a universal unrotated footprint model.",
                serializer="OpenCASCADE7.9.3 XCAFDoc_Editor.Extract + assembly TopLoc_Location + STEPCAFControl_Writer",
                models=[])
if PIN_REGISTERED:
    manifest["additional_registration"] = dict(
        policy="Separate variants retain original child dimensions, but apply a measured rigid XY registration correction from source cross-section pins to frozen current pad-pattern centers.",
        CN1=dict(correction_mm=[-0.05, 0, 0], evidence="All five metal pins and the plastic locator at source Z=-0.5 have uniform +0.050mmX residual versus current numbered pads/locator. Correcting X does not change relative pin pitch."),
        J1=dict(correction_mm=[0, 0, 0.4064], evidence="Fourteen SMTfootbottom faces areZ-0.4064 in the historical bodyfloor-datum variant. Raising0.4064 places contactsZ0; bodyfloor+.4064, locatorends-.8636, top6.1214. Independent current nativeOBJ measured same contact datum."),
        J13=dict(correction_mm=[-0.016, 0, 0], evidence="Source section Z=-0.5 has signalcenterX+0.0160005 and four grounds atX-2.5239995/+2.5560005,Y+/-2.54. Current pad-patterncenter is0 with5.08mm square pitch. Correcting X gives uniform <2um residual."),
        qualification="SMA_RighAngle_1 remains a historical generic model, not independently manufacturer-certified SMA-KWE901 geometry.")
for ref in REFS:
    occurrence = next(item for item in AUDIT["top_level_occurrences"] if item["ref"] == ref)
    current = COMPONENTS[ref]
    matrix = [row[:] for row in occurrence["transform"]]
    matrix[0][3] -= board_xmin + current["x_mm"]
    matrix[1][3] -= board_ymin + current["y_mm"]
    matrix[2][3] -= mount_datum
    if PIN_REGISTERED:
        correction = {"CN1": [-0.05, 0, 0], "J1": [0, 0, 0.4064], "J13": [-0.016, 0, 0]}[ref]
        for axis in range(3):
            matrix[axis][3] += correction[axis]
    transform = gp_Trsf()
    transform.SetValues(*[value for row in matrix[:3] for value in row])
    assert abs(transform.ScaleFactor()-1) < 1e-12
    newdoc = new_doc()
    assert XCAFDoc_Editor.Extract_s(labels[occurrence["product"]], newdoc.Main())
    newtool = XCAFDoc_DocumentTool.ShapeTool_s(newdoc.Main())
    free = TDF_LabelSequence()
    newtool.GetFreeShapes(free)
    assert free.Length() == 1
    model_label = free.Value(1)
    wrapper = newtool.NewShape()
    TDataStd_Name.Set_s(wrapper, TCollection_ExtendedString(f"{ref}_canonical_board_Zup"))
    newtool.AddComponent(wrapper, model_label, TopLoc_Location(transform))
    newtool.UpdateAssemblies()
    expected = shapes.GetShape_s(labels[occurrence["product"]]).Moved(TopLoc_Location(transform))
    before = shape_stats(expected)
    folder = OUT / ref
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "board-Zup-pinregistered" if PIN_REGISTERED else "board-Zup"
    path = folder / f"{ref}_{occurrence['product']}_{suffix}.step"
    writer = STEPCAFControl_Writer()
    writer.SetColorMode(True)
    writer.SetNameMode(True)
    assert writer.Transfer(wrapper)
    assert writer.Write(str(path)) == IFSelect_RetDone
    checked_doc, checked_tool = read_document(path)
    free2 = TDF_LabelSequence()
    checked_tool.GetFreeShapes(free2)
    assert free2.Length() == 1
    checked_shape = checked_tool.GetShape_s(free2.Value(1))
    after = shape_stats(checked_shape)
    delta = max(abs(a-b) for key in ["min_mm", "max_mm"] for a, b in zip(before["bounds"][key], after["bounds"][key]))
    relative_volume = abs(before["volume_mm3"]-after["volume_mm3"])/max(abs(before["volume_mm3"]), 1e-12)
    item = dict(ref=ref, product=occurrence["product"], historical_transform=occurrence["transform"],
                current_component=dict(x_mm=current["x_mm"], y_mm=current["y_mm"], rotation_deg=current["rotation_deg"], footprint_uuid=current["footprint_uuid"]),
                rigid_transform_local_to_canonical_mm=matrix, canonical_stats=after,
                registration_note="Computed from common board-coordinate shift and exact current component origin; validate terminal cross-sections against current pad centers before native binding.",
                current_pin_centers_mm=current["orientation_hints"]["pin_centers_mm"],
                sections_below_mount_plane={str(z): section_groups(checked_shape, z) for z in [-0.5, -0.1]},
                path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                checks=dict(brep_valid=after["brep_valid"], same_solids=before["solids"]==after["solids"], same_faces=before["faces"]==after["faces"], bbox_maxdelta_mm=delta, volume_relative_delta=relative_volume))
    item["checks"]["pass"] = bool(after["brep_valid"] and item["checks"]["same_solids"] and item["checks"]["same_faces"] and delta <= 1e-5 and relative_volume <= 1e-7)
    if PIN_REGISTERED:
        item["registration_note"] = "Additional measured pin-pattern translation correction applied; see manifest additional_registration. No source or existing historical variant changed."
    if ref in ["CN1", "CN3", "J1", "L1", "J13"]:
        item["datum_features"] = feature_planes_and_cylinders(checked_shape)
    manifest["models"].append(item)
    print(json.dumps(dict(ref=ref, transform=matrix, geometry=after, checks=item["checks"])), flush=True)
    (OUT / "canonical-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
# Share SMA outward vectors for every historical/current instance without claiming
# a new placement for refs that moved in the current board.
manifest["historical_SMA_outward_vectors"] = [dict(ref=item["ref"], outward_board_XY=[item["transform"][0][2], item["transform"][1][2]],
    historical_origin=item["transform"], current_origin_mm=[COMPONENTS[item["ref"]]["x_mm"], COMPONENTS[item["ref"]]["y_mm"]])
    for item in AUDIT["top_level_occurrences"] if item["product"] == "SMA_RighAngle_1" and item["ref"] in COMPONENTS]
(OUT / "canonical-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == manifest["source_sha256"]
print("Canonical variants complete; original source unchanged", flush=True)
