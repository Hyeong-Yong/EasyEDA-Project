#!/usr/bin/env python3
"""Offline, new-only native libraries for the DC/60 Hz ADC labtool revision.

Writes only output/candidates/adc10-labtool-20261018/libraries.  This does not
connect to EasyEDA, import libraries, or mutate the native project.  The older
generator is imported only for its proven v3 primitive serializers, never run.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import re
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/candidates/adc10-labtool-20261018/libraries"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_labtool_afe_20261018.epro2"
PROJECT = "STM32H747_MCU_BOARD_v19"
PREFIX = "STM_H747_ADC_LABTOOL_20261018_"
TAG = "ADC_LABTOOL_20261018"
STAMP = 1792281600000
PARTS = {
    "OPA189": {"mpn": "OPA189IDBVR", "pdf": "opa189", "revision": "SBOS830I October 2021", "pinPage": 5, "landPage": 44, "package": "DBV5", "role": "preferred bipolar input follower"},
    "OPA192": {"mpn": "OPA192IDBVR", "pdf": "opa192", "revision": "SBOS620E November 2015", "pinPage": 4, "landPage": 56, "package": "DBV5", "role": "unused alternative only; no circuit-selection claim"},
    "REF5025": {"mpn": "REF5025AID", "pdf": "ref50", "revision": "SBOS410O October 2025", "pinPage": 4, "landPage": 47, "package": "SOIC8", "role": "2.5 V AI-generation reference, not EI"},
    "TPS60403": {"mpn": "TPS60403DBVR", "pdf": "tps60403", "revision": "SLVS324C October 2020", "pinPage": 3, "landPage": 31, "package": "DBV5", "role": "inverting switched-capacitor supply"},
    "TPS72301": {"mpn": "TPS72301DBVR", "pdf": "tps723", "revision": "SLVS346E March 2026", "pinPage": 3, "landPage": 42, "package": "DBV5", "role": "adjustable negative LDO; pin4 FB, not NR"},
    "TPS7A2033": {"mpn": "TPS7A2033PDBVR", "pdf": "tps7a20", "revision": "SBVS338H July 2024", "pinPage": 4, "landPage": 57, "package": "DBV5", "role": "3.3 V quiet LDO candidate; use not decided by this library"},
}
SOURCE_FOOT = "6bb29ef4f7785623"
R_SYMBOL, R_FOOT = "ae94444fd364ffa4", "c177c8c7ab4f7483"
C_SYMBOL, C_FOOT = "4aa7dcf070817259", "33204de9fd4fd5be"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def uid(kind, label):
    return hashlib.sha256(f"stm32h747-adc-labtool-libraries-20261018\0{kind}\0{label}".encode()).hexdigest()[:16]


def read_snapshot(path):
    with zipfile.ZipFile(path) as archive:
        source = archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode("utf8")
    documents, current = {}, None
    for line in source.splitlines():
        if not line.strip():
            continue
        h, raw = line.split("||", 1)
        h, raw = json.loads(h), raw.rstrip("|")
        body = json.loads(raw) if raw else None
        if h["type"] == "DOCHEAD":
            current = body["docType"], body["uuid"]
            documents.setdefault(current, {})
        key = h["type"], str(h.get("id", ""))
        old = documents[current].get(key)
        if old is None or h.get("ticket", 0) >= old[0].get("ticket", 0):
            documents[current][key] = h, body
    return {doc: {key: row for key, row in rows.items() if row[1] is not None} for doc, rows in documents.items()}


def serializer():
    spec = importlib.util.spec_from_file_location("adc_prior_library_serializer", ROOT / "scripts/build-adc-dc-libraries.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PREFIX, module.STAMP, module.uid = PREFIX, STAMP, uid
    return module


M = serializer()


def symbol(key):
    part = PARTS[key]
    doc = M.Doc("SYMBOL", key, PREFIX + part["mpn"])
    doc.add("CANVAS", {"originX": 0, "originY": 0}, "CANVAS")
    doc.add("PART", {"title": "A"}, "A")
    doc.add("META", {"title": doc.title, "description": part["role"], "docType": 2,
        "tags": ["PROJECT_LOCAL", TAG], "source": doc.uuid + "|project"}, "META")
    if key in {"OPA189", "OPA192"}:
        M.poly(doc, [(-20, -25), (-20, 25), (25, 0)], True, "#FFFFC2")
        specs = [("1", "OUT", 45, 0, 20, 180, "OUT"), ("2", "V-", 0, 35, 20, 270, "Power"),
                 ("3", "+IN", -40, -10, 20, 0, "IN"), ("4", "-IN", -40, 10, 20, 0, "IN"),
                 ("5", "V+", 0, -35, 20, 90, "Power")]
        design_xy, value_xy = (-22, -49), (-22, -42)
    elif key == "REF5025":
        M.poly(doc, [(-35, -45), (35, -45), (35, 45), (-35, 45)], True, "#FFFFC2")
        specs = [("1", "DNC", -60, -30, 25, 0, "Passive"), ("2", "VIN", -60, -10, 25, 0, "Power"),
                 ("3", "TEMP", -60, 10, 25, 0, "OUT"), ("4", "GND", -60, 30, 25, 0, "Ground"),
                 ("5", "TRIM/NR", 60, 30, 25, 180, "Passive"), ("6", "VOUT", 60, 10, 25, 180, "OUT"),
                 ("7", "NC", 60, -10, 25, 180, "Passive"), ("8", "DNC", 60, -30, 25, 180, "Passive")]
        design_xy, value_xy = (-35, -64), (-35, -56)
    else:
        M.poly(doc, [(-30, -35), (30, -35), (30, 35), (-30, 35)], True, "#FFFFC2")
        if key == "TPS60403":
            specs = [("1", "OUT", 50, -15, 20, 180, "Power"), ("2", "IN", -50, -15, 20, 0, "Power"),
                     ("3", "CFLY-", -50, 20, 20, 0, "Passive"), ("4", "GND", 0, 55, 20, 270, "Ground"),
                     ("5", "CFLY+", 50, 20, 20, 180, "Passive")]
        elif key == "TPS72301":
            specs = [("1", "GND", 0, 55, 20, 270, "Ground"), ("2", "IN", -50, -15, 20, 0, "Power"),
                     ("3", "EN", -50, 15, 20, 0, "IN"), ("4", "FB", 50, 15, 20, 180, "IN"),
                     ("5", "OUT", 50, -15, 20, 180, "Power")]
        elif key == "TPS7A2033":
            specs = [("1", "IN", -50, -15, 20, 0, "Power"), ("2", "GND", 0, 55, 20, 270, "Ground"),
                     ("3", "EN", -50, 15, 20, 0, "IN"), ("4", "NC", 50, 15, 20, 180, "Passive"),
                     ("5", "OUT", 50, -15, 20, 180, "Power")]
        else:
            raise ValueError(key)
        design_xy, value_xy = (-30, -54), (-30, -46)
    pins = []
    for number, name, x, y, length, rotation, electric in specs:
        p = M.pin(doc, number, name, x, y, length, rotation, electric,
                  show_name=not (key in {"OPA189", "OPA192"} and number == "1"))
        if key == "REF5025" and number in {"1", "8"}:
            p["mustRemainUnconnected"] = True
            p["connectionContract"] = "DNC: do not connect, including GND"
        elif name == "NC":
            p["unusedPhysicalPin"] = True
        pins.append(p)
    M.attr(doc, "", "Designator", "U?", *design_xy, True)
    M.attr(doc, "", "Value", part["mpn"], *value_xy, True)
    return doc, {"uuid": doc.uuid, "title": doc.title, "pins": pins, "partId": "A",
        "coordinateUnit": "0.01 inch, positive Y down in symbol-local source",
        "datasheetPinPage": part["pinPage"], "visibleValue": part["mpn"]}


def clone_dbv(documents):
    label = "DBV5"
    rows = documents["FOOTPRINT", SOURCE_FOOT]
    doc = M.Doc("FOOTPRINT", label, PREFIX + "TI_DBV0005A_SOT23_5")
    ids = {h["id"]: uid(label, h["type"] + "/clone/" + str(h["id"]))
           for h, body in rows.values() if re.fullmatch("[0-9a-f]{16}", str(h.get("id", "")))}
    def remap(v):
        if isinstance(v, str):
            return ids.get(v, v)
        if isinstance(v, list):
            return [remap(x) for x in v]
        if isinstance(v, dict):
            return {k: remap(x) for k, x in v.items()}
        return v
    for h, body in rows.values():
        if h["type"] in {"DOCHEAD", "DELETE_DOC"}:
            continue
        body = remap(copy.deepcopy(body))
        if h["type"] == "META":
            body.update(title=doc.title, source=doc.uuid + "|project", tags=[TAG],
                        description="New-identity exact geometry clone of verified DBV0005A land pattern")
        doc.add(h["type"], body, ids.get(h.get("id"), h.get("id")))
    pads = []
    for h, body in doc.records:
        if h["type"] == "PAD":
            pads.append({"number": str(body["num"]), "centerMm": [body["centerX"] * .0254, body["centerY"] * .0254],
                         "copperSizeMm": [body["defaultPad"]["width"] * .0254, body["defaultPad"]["height"] * .0254],
                         "nativeBody": copy.deepcopy(body)})
    expected = {"1": (-1.3, .95), "2": (-1.3, 0), "3": (-1.3, -.95), "4": (1.3, -.95), "5": (1.3, .95)}
    assert set(p["number"] for p in pads) == set(expected)
    for pad in pads:
        assert max(abs(a-b) for a,b in zip(pad["centerMm"], expected[pad["number"]])) < 2e-8
        assert max(abs(a-b) for a,b in zip(pad["copperSizeMm"], (1.1,.6))) < 2e-8
    return doc, {"uuid": doc.uuid, "title": doc.title, "pads": pads, "cloneSourceUuid": SOURCE_FOOT,
        "drawing": "TI DBV0005A 4214839/K 08/2024", "geometryOrigin": "Exact existing copper/body/assembly geometry; new META and primitive identities only",
        "coordinateUnit": "mil, positive Y up, top view", "manufacturingApproval": False,
        "bodySizeMm": [1.6,2.9], "courtyardMm": [4.2,3.6]}


def soic8(dbv_doc):
    label = "SOIC8"
    doc = M.Doc("FOOTPRINT", label, PREFIX + "TI_D0008A_SOIC8_1P27")
    doc.add("META", {"title": doc.title, "source": doc.uuid + "|project", "tags": [TAG],
        "description": "TI D0008A 4214825/C 02/2019 example land pattern; assembly approval pending"}, "META")
    for h, body in dbv_doc.records:
        if h["type"] in {"CANVAS", "ACTIVE_LAYER", "LAYER"}:
            doc.add(h["type"], copy.deepcopy(body), h["id"])
    cv = lambda x: round(x/.0254, 6)
    coords = {"1": (-2.7,1.905), "2": (-2.7,.635), "3": (-2.7,-.635), "4": (-2.7,-1.905),
              "5": (2.7,-1.905), "6": (2.7,-.635), "7": (2.7,.635), "8": (2.7,1.905)}
    template = next(copy.deepcopy(b) for h,b in dbv_doc.records if h["type"] == "PAD")
    pads = []
    for n, (x,y) in coords.items():
        body = copy.deepcopy(template)
        body.update(num=n, centerX=cv(x), centerY=cv(y), zIndex=int(n),
                    defaultPad={"padType":"RECT", "width":cv(1.55), "height":cv(.6), "radius":cv(.05)})
        doc.add("PAD", body, uid(label,"pad/"+n))
        pads.append({"number":n,"centerMm":[x,y],"copperSizeMm":[1.55,.6],"cornerRadiusMm":.05,
                     "solderMaskExpansionMm":.07,"pasteExpansionMm":0,"nativeBody":body})
    # Package body is 3.9 mm across X and 4.9 mm across Y.  Courtyard is a
    # conservative project-specific outline, not a TI factory recommendation.
    for layer,hx,hy,width in [(9,1.95,2.45,.1),(48,3.75,2.7,.05)]:
        vertices=[(-hx,-hy),(hx,-hy),(hx,hy),(-hx,hy)]
        for a,b in zip(vertices,vertices[1:]+vertices[:1]):
            doc.add("LINE", {"groupId":0,"netName":"","layerId":layer,"startX":cv(a[0]),"startY":cv(a[1]),
                "endX":cv(b[0]),"endY":cv(b[1]),"lineWidth":cv(width),"locked":False,"zIndex":len(doc.records)})
    doc.add("LINE", {"groupId":0,"netName":"","layerId":3,"startX":cv(-3.65),"startY":cv(2.5),
        "endX":cv(-3.45),"endY":cv(2.5),"lineWidth":cv(.2),"locked":False,"zIndex":len(doc.records)})
    return doc,{"uuid":doc.uuid,"title":doc.title,"pads":pads,"drawing":"TI D0008A 4214825/C 02/2019",
        "coordinateUnit":"mil, positive Y up, top view", "geometryOrigin":"Official TI example land pattern, REF50 PDF physical page47",
        "bodySizeMm":[3.9,4.9],"courtyardMm":[7.5,5.4],"manufacturingApproval":False,
        "notes":["Pad row centre separation5.4mm, pitch1.27mm, pad1.55x0.60mm.","Courtyard/assembly outlines are project-local; assembler approval required."]}


def passive_references(documents):
    old=json.loads((ROOT/"output/candidates/adc-dc-buffer/adc-dc-runtime-library-map.json").read_text(encoding="utf8"))
    values={"R1M":"1M","R3K32":"3.32k","R3K":"3k","R4K":"4k","R16K5":"16.5k","R10K":"10k"}
    refs={"resistor":{"symbolUuid":R_SYMBOL,"footprintUuid":R_FOOT,"templateDeviceUuid":old["devices"]["R6K8"]["uuid"],
        "pins":[{"number":"1","x":-15,"y":0},{"number":"2","x":15,"y":0}],
        "nativePadCoordinatesMil":[b for h,b in documents["FOOTPRINT",R_FOOT].values() if h["type"]=="PAD"],
        "newValues":values,"negativeFeedbackResistors":"same generic resistor symbol and0402 footprint, value chosen by circuit owner",
        "instanceOverrideWarning":"Template device carries6.8k metadata. Override Value, Part Number/Description as appropriate; do not represent template procurement identity as the new resistor MPN."},
        "capacitor":{"symbolUuid":C_SYMBOL,"footprintUuid":C_FOOT,"pins":[{"number":"1","x":0,"y":-10},{"number":"2","x":0,"y":10}],
        "existingDevices":{k:old["devices"][k] for k in ["C2N2","C10N","C100N","C1U","C4U7"]},
        "nativePadCoordinatesMil":[b for h,b in documents["FOOTPRINT",C_FOOT].values() if h["type"]=="PAD"],
        "requestedC10nFC0GDeviceUuid":old["devices"]["C10N"]["uuid"]}}
    for kind,u in [("SYMBOL",R_SYMBOL),("SYMBOL",C_SYMBOL),("FOOTPRINT",R_FOOT),("FOOTPRINT",C_FOOT)]:
        assert (kind,u) in documents
    return refs


def preview(symbol_docs, footprint_docs):
    from PIL import Image,ImageDraw,ImageFont
    canvas=Image.new("RGB",(2100,1600),"white")
    draw=ImageDraw.Draw(canvas)
    def font(size):
        return ImageFont.truetype("C:/Windows/Fonts/arial.ttf",max(9,int(size)))
    for i,doc in enumerate(symbol_docs):
        cx,cy=350+(i%3)*700,240+(i//3)*470
        draw.text((cx-315,cy-210),doc.title.removeprefix(PREFIX),font=font(23),fill="#10243a")
        transform=lambda x,y:(cx+x*3.4,cy+y*3.4)
        for h,b in doc.records:
            if h["type"]=="POLY":
                pts=[transform(p["x"],p["y"]) for p in b["points"]]
                if b["closed"]:
                    draw.polygon(pts,fill="#fffed0",outline="#840000",width=2)
                else:
                    draw.line(pts,fill="#840000",width=2)
            elif h["type"]=="PIN":
                r=math.radians(b["rotation"])
                a=transform(b["x"],b["y"])
                z=transform(b["x"]+math.cos(r)*b["length"],b["y"]+math.sin(r)*b["length"])
                draw.line((a,z),fill="#840000",width=2)
                draw.ellipse((a[0]-2,a[1]-2,a[0]+2,a[1]+2),outline="#840000")
            elif h["type"]=="ATTR" and b["valueVisible"]:
                x,y=transform(b["x"],b["y"])
                anchors={"LEFT_MIDDLE":"lm","RIGHT_MIDDLE":"rm","CENTER_TOP":"mt","CENTER_BOTTOM":"mb","LEFT_MIDDLE":"lm"}
                draw.text((x,y),str(b["value"]),font=font(b["fontSize"]*3.4),fill=b["color"],anchor=anchors.get(b["align"],"lm"))
    for i,doc in enumerate(footprint_docs):
        cx,cy=550+i*1000,1300
        draw.text((cx-370,1040),doc.title.removeprefix(PREFIX)+" (top view)",font=font(22),fill="#10243a")
        transform=lambda x,y:(cx+x*.0254*70,cy-y*.0254*70)
        for h,b in doc.records:
            if h["type"]=="PAD":
                x,y=transform(b["centerX"],b["centerY"])
                w,z=b["defaultPad"]["width"]*.0254*70,b["defaultPad"]["height"]*.0254*70
                draw.rectangle((x-w/2,y-z/2,x+w/2,y+z/2),fill="#cf3030")
                draw.text((x,y),str(b["num"]),font=font(19),fill="white",anchor="mm")
            elif h["type"]=="LINE":
                col={9:"#009080",48:"#96bdb4",3:"#cc9a00"}.get(b["layerId"],"#444444")
                draw.line((transform(b["startX"],b["startY"]),transform(b["endX"],b["endY"])),fill=col,width=2)
    path=OUT/"adc10-labtool-new-library-preview.png"
    canvas.save(path)
    return str(path)


def runtime_map(after_path):
    """Resolve native-import UUID remapping from a saved checkpoint, read-only."""
    manifest=json.loads((OUT/"adc10-labtool-library-manifest.json").read_text(encoding="utf8"))
    before=read_snapshot(CHECKPOINT)
    after=read_snapshot(after_path)
    new=set(after)-set(before)
    mapped={"schema":"adc10-labtool-runtime-library-map-20261018-v1",
            "checkpoint":str(Path(after_path).resolve()),"checkpointSha256":sha(after_path),
            "symbols":{},"footprints":{},"devices":{},"passiveReferences":manifest["passiveReferences"]}
    uuid_map={}
    matched=set()
    for group,kind in [("symbols","SYMBOL"),("footprints","FOOTPRINT"),("devices","DEVICE")]:
        for key,info in manifest[group].items():
            candidates=[]
            for identity in new:
                if identity[0]!=kind:
                    continue
                meta=next((b for h,b in after[identity].values() if h["type"]=="META"),{})
                if str(meta.get("source","")).split("|")[0]==info["uuid"] or meta.get("title")==info["title"]:
                    candidates.append((identity,meta))
            if len(candidates)!=1:
                raise ValueError(f"Expected exactly1 native import match for {group}/{key}: {[v[0] for v in candidates]}")
            identity,meta=candidates[0]
            item=copy.deepcopy(info)
            item.update(uuid=identity[1],oldUuid=info["uuid"],source=meta.get("source",""),runtimeMeta=meta)
            mapped[group][key]=item
            uuid_map[info["uuid"]]=identity[1]
            matched.add(identity)
    for dev in mapped["devices"].values():
        for field,attr in [("symbolUuid","Symbol"),("footprintUuid","Footprint")]:
            dev[field]=uuid_map[dev[field]]
            dev["attributes"][attr]=dev[field]
            if dev["runtimeMeta"]["attributes"].get(attr)!=dev[field]:
                raise ValueError(f"Native imported device {dev['uuid']} has a mismatched {attr} dependency")
    ignored={"DOCHEAD","CANVAS","ACTIVE_LAYER"}
    changes=[]
    for identity,rows in before.items():
        other=after.get(identity,{})
        for key in rows.keys()|other.keys():
            if key[0] in ignored:
                continue
            a=rows.get(key,(None,None))[1]
            b=other.get(key,(None,None))[1]
            if a!=b:
                changes.append({"document":identity,"record":key,
                    "beforeBodySha256":hashlib.sha256(compact(a).encode()).hexdigest(),
                    "afterBodySha256":hashlib.sha256(compact(b).encode()).hexdigest()})
    audit={"schema":"adc10-labtool-library-import-preservation-20261018-v1",
        "beforeCheckpoint":str(CHECKPOINT),"beforeSha256":sha(CHECKPOINT),
        "afterCheckpoint":str(Path(after_path).resolve()),"afterSha256":sha(after_path),
        "beforeDocumentCount":len(before),"afterDocumentCount":len(after),
        "newCounts":dict(Counter(k[0] for k in new)),"newDocuments":sorted(new),
        "allNewDocumentsMapped":new==matched,"protectedExistingNonViewRecordChangeCount":len(changes),
        "protectedExistingNonViewRecordChanges":changes[:50],"excludedViewRecordTypes":sorted(ignored),
        "passed":not changes and new==matched and len(new)==14}
    mapped.update(uuidMap=uuid_map,newDocumentCount=len(new),importPreservationPassed=audit["passed"])
    (OUT/"independent-runtime-map.json").write_text(json.dumps(mapped,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    (OUT/"independent-native-import-preservation-audit.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"passed":audit["passed"],"newCounts":audit["newCounts"],"protectedChanges":len(changes),
        "map":str(OUT/"independent-runtime-map.json")},indent=2))
    if not audit["passed"]:
        raise ValueError("New-only library native-import preservation audit failed")


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    docs=read_snapshot(CHECKPOINT)
    checkpoint_sha=sha(CHECKPOINT)
    generated=[]
    symbols,footprints,devices={},{},{}
    for key in PARTS:
        doc,info=symbol(key)
        generated.append(doc)
        symbols[key]=info
    dbv,dbv_info=clone_dbv(docs)
    soic,soic_info=soic8(dbv)
    generated.extend([dbv,soic])
    footprints.update(DBV5=dbv_info,SOIC8=soic_info)
    for key,part in PARTS.items():
        attrs={"Manufacturer":"Texas Instruments","Part Number":part["mpn"],
               "Datasheet":"https://www.ti.com/lit/ds/symlink/"+part["pdf"]+".pdf",
               "Description":part["role"],"Datasheet Revision":part["revision"]}
        if key=="REF5025":
            attrs.update({"Output Voltage":"2.5 V","Connection Constraint":"Pins1 and8 DNC; pin7 NC; not REF5025EI pinmap"})
        doc,info=M.device(key,part["mpn"],symbols[key],footprints[part["package"]],part["mpn"],"U?",attrs)
        next(b for h,b in doc.records if h["type"]=="META")["tags"]=[PROJECT,TAG]
        generated.append(doc)
        devices[key]=info
    new_uuids=[d.uuid for d in generated]
    existing_uuids={k[1] for k in docs}
    old_primitives={str(h.get("id","")) for rows in docs.values() for h,b in rows.values() if re.fullmatch("[0-9a-f]{16}",str(h.get("id","")))}
    new_primitives=[str(h.get("id","")) for d in generated for h,b in d.records if re.fullmatch("[0-9a-f]{16}",str(h.get("id","")))]
    assert len(new_uuids)==len(set(new_uuids)) and not set(new_uuids)&existing_uuids
    assert not set(new_primitives)&old_primitives
    for key,dev in devices.items():
        pins={p["number"] for p in symbols[key]["pins"]}
        pads={p["number"] for p in footprints[PARTS[key]["package"]]["pads"]}
        assert pins==pads==set(dev["pinToPad"])
        assert all(dev["pinToPad"][p]==p for p in pins)
    assert all(p["electric"]=="Power" for key in ["OPA189","OPA192"] for p in symbols[key]["pins"] if p["number"]=="2")
    assert sum(p["electric"]=="Ground" for s in symbols.values() for p in s["pins"])==4
    order={"SYMBOL":0,"FOOTPRINT":1,"DEVICE":2}
    generated.sort(key=lambda d:(order[d.kind],d.label))
    source="".join(d.source() for d in generated)
    source_path=OUT/"adc10-labtool-new-libraries-20261018.epru"
    source_path.write_text(source,encoding="utf8",newline="\n")
    for doc in generated:
        ext={"SYMBOL":"esym","FOOTPRINT":"efoo","DEVICE":"edevice"}[doc.kind]
        (OUT/f"{doc.label}_{doc.uuid}.{ext}").write_text(doc.source(),encoding="utf8",newline="\n")
    package=OUT/"STM32H747_adc10_labtool_new_libraries_20261018.epro2"
    with zipfile.ZipFile(package,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        payloads={"project2.json":json.dumps({"title":PROJECT,"cbb_project":False,"editorVersion":"3.2.206",
            "description":"New ADC labtool libraries only; no PCB/schematic mutation","tags":"[]"},ensure_ascii=False),PROJECT+".epru":source}
        for name,data in payloads.items():
            info=zipfile.ZipInfo(name,date_time=(2026,10,18,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    sources={key:{"url":"https://www.ti.com/lit/ds/symlink/"+p["pdf"]+".pdf","revision":p["revision"],
        "downloadedPath":str(OUT/"references"/(p["pdf"]+".pdf")),"sha256":sha(OUT/"references"/(p["pdf"]+".pdf")),
        "physicalPinPage":p["pinPage"],"physicalLandPage":p["landPage"],"pinPageVisuallyInspected":True,
        "landPageVisuallyInspected":True} for key,p in PARTS.items()}
    image=preview([d for d in generated if d.kind=="SYMBOL"],[dbv,soic])
    manifest={"schema":"adc10-labtool-new-libraries-20261018-v1","project":PROJECT,"prefix":PREFIX,
        "sourceCheckpoint":str(CHECKPOINT),"sourceCheckpointSha256":checkpoint_sha,"sourceCheckpointDocumentCount":len(docs),
        "newOnly":True,"mutatesExistingLibraries":False,"containsSchematicOrPcb":False,"nativeApiCalled":False,
        "counts":dict(Counter(d.kind for d in generated)),"symbols":symbols,"footprints":footprints,"devices":devices,
        "passiveReferences":passive_references(docs),"officialSources":sources,"sourcePath":str(source_path),
        "sourceSha256":sha(source_path),"packagePath":str(package),"packageSha256":sha(package),"previewPath":image,
        "validation":{"uniqueNewUuidNoCollision":True,"allNewHexPrimitiveIdsNoExistingCollision":True,
            "allSymbolPinsMatchFootprintPads":True,"allNumberToPadMappingsIdentity":True,"negativeSupplyIsPowerNotGround":True,
            "oldDbvCopperGeometryPreserved":True,"newDocumentCount":len(generated),"nativeLibraryImportPending":True,
            "manufacturingApproved":False,"circuitStartupNoiseAndStabilityValidated":False},
        "notes":["Pin Name/Pin Number/Pin Type ATTR keys are used, matching installed native3.2.206, not legacy NAME/NUMBER keys.",
            "All symbol pins are real electrical primitives; Designator and Value are editable visible ATTR records.",
            "REF5025AID is the AI/I pinmap. Pins1 and8 are DNC, not EN or ordinary reusable NC pins. Pin7 is NC.",
            "TPS72301DBVR pin4 is feedback input FB; do not treat it as the fixed-output NR pin.",
            "DBV5 included once as a new-identity exact-geometry clone so IC package import is self-contained.",
            "OPA192 and TPS7A2033 inclusion is not authorization to instantiate them or a final circuit choice.",
            "Passive references point to already existing project-local documents; no old libraries were modified.",
            "New UUIDs will remap on native mini-project import. Resolve by exact prefixed title or META.source oldUuid before schematic rebind.",
            "No live API, ERC, DRC, bench test, simulation, assembly or fabrication approval is implied."]}
    (OUT/"adc10-labtool-library-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    assert sha(CHECKPOINT)==checkpoint_sha
    print(json.dumps({"package":str(package),"sha256":manifest["packageSha256"],"counts":manifest["counts"],
        "manifest":str(OUT/"adc10-labtool-library-manifest.json"),"nativeApiCalled":False},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--runtime-checkpoint",type=Path)
    args=parser.parse_args()
    runtime_map(args.runtime_checkpoint) if args.runtime_checkpoint else main()
