"""Offline-only seven-channel expansion using verified existing ADC1 devices.

Reads the 2026-10-17 fresh source; never contacts EasyEDA or changes libraries.
"""
import copy
import hashlib
import json
import math
import runpy
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / "output/validation/native-adc10-sch-before-20261017.epru"
BASE_SHA = "885b9eaa95591d23a652d521fa0c785f63d5eb836f148ad16f58402825c9cd45"
CHECKPOINT = ROOT / "output/checkpoints/STM32H747_before_adc10_20261017.epro2"
OLD = ROOT / "output/candidates/adc-inline-wiring"


def uid(key):
    return hashlib.sha256(("stm32h747-adc10-dc-20261017/" + key).encode()).hexdigest()[:16]


def parse(path):
    rows = []
    for raw in path.read_text(encoding="utf8").splitlines():
        if raw.strip():
            h, b = raw.split("||", 1)
            rows.append({"h": json.loads(h), "b": json.loads(b.rstrip("|"))})
    return rows


def read_checkpoint(path):
    """Materialize latest log records, including native empty-body tombstones."""
    with zipfile.ZipFile(path) as archive:
        source=archive.read(next(n for n in archive.namelist() if n.endswith(".epru"))).decode("utf8")
    docs={}
    current=None
    for raw in source.splitlines():
        if not raw.strip(): continue
        h,b=raw.split("||",1)
        h=json.loads(h)
        value=b.rstrip("|")
        b=json.loads(value) if value else None
        if h["type"]=="DOCHEAD":
            current=(b["docType"],b["uuid"])
            docs.setdefault(current,{})
        key=h["type"],str(h.get("id",""))
        previous=docs[current].get(key)
        if previous is None or h.get("ticket",0)>=previous[0].get("ticket",0):
            docs[current][key]=(h,b)
    return {k:{i:v for i,v in values.items() if isinstance(v[1],dict)} for k,values in docs.items()}


def on(p, a, b):
    return abs((p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])) < 1e-4 and min(a[0],b[0])-1e-5 <= p[0] <= max(a[0],b[0])+1e-5 and min(a[1],b[1])-1e-5 <= p[1] <= max(a[1],b[1])+1e-5


def translate(b, dx, dy):
    for k in ("x", "startX", "endX", "dotX1", "dotX2"):
        if b.get(k) is not None:
            b[k] += dx
    for k in ("y", "startY", "endY", "dotY1", "dotY2"):
        if b.get(k) is not None:
            b[k] += dy
    for p in b.get("points", []):
        p["x"] += dx
        p["y"] += dy


def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest() == BASE_SHA
    original = parse(BASE)
    rows = copy.deepcopy(original)
    old = {(r["h"]["type"], r["h"].get("id")): r for r in original}
    lookup = {(r["h"]["type"], r["h"].get("id")): r for r in rows}
    attrs, refs = defaultdict(dict), {}
    for r in rows:
        if r["h"]["type"] == "ATTR":
            attrs[r["b"]["parentId"]][r["b"]["key"]] = r
            if r["b"]["key"] == "Designator":
                refs[r["b"]["value"]] = r["b"]["parentId"]
    old_attrs = {cid: {k: copy.deepcopy(r["b"]) for k, r in a.items()} for cid, a in attrs.items()}
    lib = read_checkpoint(CHECKPOINT)
    ticket = max(r["h"].get("ticket", 0) for r in rows)
    removed, scopes, specs, layout = set(), defaultdict(set), [], []

    def add(kind, b, key):
        nonlocal ticket
        rid = uid(key)
        assert (kind, rid) not in lookup and all(k[1] != rid for k in lookup)
        ticket += 1
        r = {"h": {"type": kind, "id": rid, "ticket": ticket}, "b": b}
        rows.append(r)
        lookup[kind, rid] = r
        if kind == "ATTR":
            attrs[b["parentId"]][b["key"]] = r
        return rid

    def attr(parent, key, value, keyname, x=None, y=None, visible=False):
        return add("ATTR", {"parentId": parent, "key": key, "value": value, "x": x, "y": y,
            "rotation": 0, "color": None, "fontFamily": None, "fontSize": .001 if key == "NET" else 5.5 if visible else None,
            "fontWeight": False, "italic": False, "underline": False, "strikeout": False,
            "align": "LEFT_BOTTOM", "keyVisible": False, "valueVisible": visible,
            "fillColor": None, "locked": False, "zIndex": 100}, keyname)

    def text(value, x, y, name, size=5.5, color="#006666"):
        return add("TEXT", {"x": x, "y": y, "value": value, "rotation": 0, "color": color,
            "fillColor": None, "fontFamily": "Arial", "fontSize": size, "fontWeight": False,
            "italic": False, "underline": False, "strikeout": False, "align": "LEFT_BOTTOM", "zIndex": 10000, "locked": False}, name)

    def component_pins(ref, use_original=False):
        cid = refs[ref]
        cb = (old if use_original else lookup)["COMPONENT", cid]["b"]
        a = old_attrs[cid] if use_original else {k: r["b"] for k, r in attrs[cid].items()}
        doc = lib["SYMBOL", a["Symbol"]["value"]]
        pa = defaultdict(dict)
        for h, b in doc.values():
            if h["type"] == "ATTR":
                pa[b.get("parentId")][b["key"]] = b.get("value")
        result = {}
        theta = math.radians(cb["rotation"])
        for h, b in doc.values():
            if h["type"] != "PIN" or b.get("partId", cb["partId"]) != cb["partId"]:
                continue
            x, y = b["x"], b["y"]
            xx, yy = x*math.cos(theta)+y*math.sin(theta), -x*math.sin(theta)+y*math.cos(theta)
            if cb.get("isMirror"):
                xx = -xx
            result[pa[h["id"]]["Pin Number"]] = (round(cb["x"]+xx, 6), round(cb["y"]+yy, 6))
        return result

    def old_wire_at(point, net=None):
        found = set()
        for (kind, rid), r in old.items():
            b = r["b"]
            if kind == "LINE" and on(point, (b["startX"],b["startY"]), (b["endX"],b["endY"])):
                wid = b["lineGroup"]
                if net is None or old_attrs[wid]["NET"]["value"] == net:
                    found.add(wid)
        assert len(found) == 1, ("wire at", point, net, found)
        return next(iter(found))

    def old_flag(wid, net):
        lines = [r["b"] for (k, i), r in old.items() if k == "LINE" and r["b"].get("lineGroup") == wid]
        found = []
        for ref, cid in refs.items():
            if cid not in old_attrs or old_attrs[cid].get("Global Net Name", {}).get("value") != net:
                continue
            pins = component_pins(ref, True)
            if any(on(p, (b["startX"],b["startY"]), (b["endX"],b["endY"])) for p in pins.values() for b in lines):
                found.append(ref)
        assert len(found) == 1, ("flag", wid, net, found)
        return found[0]

    def remove_instance(ref, scope):
        cid = refs[ref]
        keys = {("COMPONENT", cid)} | {("ATTR", r["h"]["id"]) for r in attrs[cid].values()}
        removed.update(keys)
        scopes[scope].update(keys)

    def remove_wire(wid, scope):
        keys = {("WIRE", wid)} | {k for k, r in old.items() if r["b"].get("lineGroup") == wid or r["b"].get("parentId") == wid}
        removed.update(keys)
        scopes[scope].update(keys)

    def set_wire(wid, net, segs, labelxy, name):
        assert ("WIRE", wid) in lookup
        for k, r in old.items():
            if k[0] == "LINE" and r["b"].get("lineGroup") == wid:
                removed.add(k)
        for i, (a, b) in enumerate(segs):
            assert a != b
            add("LINE", {"startX": a[0], "startY": a[1], "endX": b[0], "endY": b[1], "lineGroup": wid,
                "strokeColor": "#009600", "strokeStyle": "SOLID", "strokeWidth": .6, "fillColor": None, "fillStyle": None}, name+"/line/"+str(i))
        attrs[wid]["NET"]["b"].update(value=net, x=labelxy[0], y=labelxy[1], fontSize=.001, valueVisible=True)

    def wire(net, segs, name, labelxy):
        wid = add("WIRE", {"zIndex": 9000, "locked": False}, name)
        attr(wid, "NET", net, name+"/net", *labelxy, True)
        attr(wid, "Relevance", "[]", name+"/relevance")
        for i, (a,b) in enumerate(segs):
            add("LINE", {"startX":a[0],"startY":a[1],"endX":b[0],"endY":b[1],"lineGroup":wid,
                "strokeColor":"#009600","strokeStyle":"SOLID","strokeWidth":.6,"fillColor":None,"fillStyle":None}, name+"/line/"+str(i))
        return wid

    def move(ref, x, y):
        cid = refs[ref]
        b = lookup["COMPONENT", cid]["b"]
        dx, dy = x-b["x"], y-b["y"]
        translate(b, dx, dy)
        for r in attrs[cid].values():
            translate(r["b"], dx, dy)

    def bind_from_template(ref, template_ref, x, y, existing=True):
        template_id = refs[template_ref]
        source_body = old["COMPONENT", template_id]["b"]
        b = copy.deepcopy(source_body)
        dx, dy = x-b["x"], y-b["y"]
        translate(b, dx, dy)
        if existing:
            cid = refs[ref]
            unique = old_attrs[cid]["Unique ID"]["value"]
            lookup["COMPONENT", cid]["b"] = b
        else:
            cid = add("COMPONENT", b, "component/"+ref)
            refs[ref] = cid
            unique = uid("physical/"+ref)
        for key, template in old_attrs[template_id].items():
            ab = copy.deepcopy(template)
            translate(ab, dx, dy)
            ab["parentId"] = cid
            if key == "Designator":
                ab["value"] = ref
            if key == "Unique ID":
                ab["value"] = unique
            if existing and key in attrs[cid]:
                attrs[cid][key]["b"] = ab
            else:
                add("ATTR", ab, "component/"+ref+"/"+key)
        specs.append({"ref": ref, "componentId": cid, "template": template_ref, "new": not existing,
            "deviceUuid": attrs[cid]["Device"]["b"]["value"], "symbolUuid": attrs[cid]["Symbol"]["b"]["value"],
            "footprintUuid": attrs[cid]["Footprint"]["b"]["value"], "value": attrs[cid]["Value"]["b"]["value"],
            "xy": [x,y], "rotation": b["rotation"], "pins": component_pins(ref)})
        return cid

    def translate_region(box, dy, scope):
        keys, parents, wire_ids = set(), set(), set()
        for k, r in old.items():
            b = r["b"]
            points = []
            if b.get("x") is not None and b.get("y") is not None:
                points.append((b["x"], b["y"]))
            if k[0] == "LINE":
                points.extend(((b["startX"],b["startY"]),(b["endX"],b["endY"])))
            if k[0] == "POLY":
                points.extend((p["x"],p["y"]) for p in b.get("points", []))
            if points and all(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x,y in points):
                keys.add(k)
                if k[0] == "COMPONENT":
                    parents.add(k[1])
                if k[0] == "LINE":
                    wire_ids.add(b["lineGroup"])
        keys.update(k for k,r in old.items() if k[0] == "ATTR" and r["b"].get("parentId") in parents | wire_ids)
        keys.update(("WIRE",wid) for wid in wire_ids)
        for k in keys:
            translate(lookup[k]["b"], 0, dy)
        scopes[scope].update(keys)
        return keys

    # The only auxiliary layout changes approved by root: complete connected
    # TIMER/DAC/MCO drawing blocks move together, never REF or J18.
    translate_region((180,520,1200,625), 95, "TIMER complete block translation +95y")
    translate_region((180,635,700,730), 100, "DAC/MCO complete block translation +100y")
    note_values = {
        "ADC1: DC coupled; CH1/CH2 = DC + 60 Hz; CH3 = DC; 15.6 kS/s/channel": ("ADC1/ADC2/ADC3: 10 DC-coupled inputs; nominal VIN = -2 V ... +2 V", 1025),
        "VIN = 2 x (VADC - 1.25 V), nominal. No series coupling capacitor.": ("VIN = 2 x (VADC - 1.25 V), nominal. No series coupling capacitor.", 1037),
        "DC passes unchanged except gain/offset. VREF+ remains on existing VDDA supply.": ("Source impedance affects gain/offset. Floating ADC zero detector NOT fitted.", 1049)}
    for r in rows:
        if r["h"]["type"] == "TEXT" and r["b"].get("value") in note_values:
            value, y = note_values[r["b"]["value"]]
            r["b"].update(value=value, x=130, y=y)
            scopes["10-channel scope/limits notes"].add(("TEXT",r["h"]["id"]))
    text("ADC_BIAS_2V5 is shared by all 10 inputs; REF/VDDA remain separate.", 130, 1061, "shared-reference-note", 5)
    caption_values={
        "ADC1 DC revision 2026-10-16":"ADC1/ADC2/ADC3 bias - 2026-10-17",
        "Dedicated ADC1 bias - do not connect to VDDA/VREF+":"Shared 2.5 V bias: 10 inputs, not VDDA/VREF+"}
    caption_keys=set()
    for r in rows:
        if r["h"]["type"]=="TEXT" and r["b"].get("value") in caption_values:
            r["b"]["value"]=caption_values[r["b"]["value"]]
            caption_keys.add(("TEXT",r["h"]["id"]))
    assert len(caption_keys)==2
    scopes["root-approved REF captions value-only update"].update(caption_keys)

    target_specs = [(2,5,149,152,153,158,86,4,0,170), (2,6,150,154,155,159,87,5,335,170),
        (2,7,151,156,157,160,88,6,665,170), (3,8,161,165,166,173,93,7,0,340),
        (3,9,162,167,168,174,94,8,335,340), (3,10,163,169,170,175,95,9,665,340),
        (3,11,164,171,172,176,96,10,1005,340)]
    for index, (bank,j,rb,ri,rs,rdnp,c,tp,off,dy) in enumerate(target_specs):
        channel = j-1
        scope = f"ADC{bank} J{j}"
        x = lambda local: local + off
        y = lambda local: local + dy
        pre, drv = f"ADC{bank}_PRE{tp-3 if bank==2 else tp-6}", f"ADC{bank}_DRV{tp-3 if bank==2 else tp-6}"
        old_raw_p = component_pins(f"J{j}", True)["1"]
        old_mix_p = component_pins(f"R{ri}", True)["2"]
        old_junction_x = component_pins(f"R{rb}", True)["2"][0]
        old_adc_p = component_pins(f"R{rs}", True)["2"]
        old_adc_node = component_pins(f"C{c}", True)["1"]
        rawwid = old_wire_at(old_raw_p)
        mixwid = old_wire_at(old_mix_p)
        biaswid = old_wire_at(component_pins(f"R{rb}", True)["1"], "+3V3")
        adcwid = old_wire_at(old_adc_p)
        capgnd = old_wire_at(component_pins(f"C{c}", True)["2"], "GND")
        smagnd = old_wire_at(component_pins(f"J{j}", True)["2"], "GND")
        dnpgnd = old_wire_at(component_pins(f"R{rdnp}", True)["2"], "GND")
        old_net = old_attrs[adcwid]["NET"]["value"]
        rawnet = old_attrs[rawwid]["NET"]["value"]
        biasflag, capflag, smaflag, dnpflag = old_flag(biaswid,"+3V3"), old_flag(capgnd,"GND"), old_flag(smagnd,"GND"), old_flag(dnpgnd,"GND")
        old_lines = [r["b"] for (k,i),r in old.items() if k=="LINE" and r["b"].get("lineGroup")==adcwid]
        old_port = max([(b["startX"],b["startY"]) for b in old_lines]+[(b["endX"],b["endY"]) for b in old_lines])
        old_main_y = old_raw_p[1]
        # Remove DNP instance, its dedicated ground network/flag, and obsolete
        # +3V3 bias flag. Shared mix WIRE is rebuilt, not deleted.
        remove_instance(f"R{rdnp}", scope+" DNP")
        remove_instance(dnpflag, scope+" DNP")
        remove_wire(dnpgnd, scope+" DNP")
        remove_instance(biasflag, scope+" obsolete main3V3 bias flag")
        jbody = lookup["COMPONENT",refs[f"J{j}"]]["b"]
        move(f"J{j}", jbody["x"]+x(235)-old_raw_p[0], jbody["y"]+y(190)-old_raw_p[1])
        sgbody = lookup["COMPONENT",refs[smaflag]]["b"]
        move(smaflag, sgbody["x"]+x(235)-old_raw_p[0], sgbody["y"]+y(190)-old_raw_p[1])
        for k,r in old.items():
            if k[0]=="LINE" and r["b"].get("lineGroup")==smagnd:
                translate(lookup[k]["b"], x(235)-old_raw_p[0], y(190)-old_raw_p[1])
        for ar in attrs[smagnd].values():
            translate(ar["b"], x(235)-old_raw_p[0], y(190)-old_raw_p[1])
        bind_from_template(f"R{rb}","R137",x(280),y(150))
        bind_from_template(f"R{ri}","R140",x(255),y(190))
        bind_from_template(f"R{rs}","R141",x(420),y(200))
        bind_from_template(f"C{c}","C80",x(455),y(230))
        u, pre_c, dec_c = f"U{13+index}", f"C{106+index}", f"C{113+index}"
        bind_from_template(u,"U10",x(345),y(200),False)
        bind_from_template(pre_c,"C97",x(280),y(235),False)
        bind_from_template(dec_c,"C100",x(440),y(145),False)
        tpbody=lookup["COMPONENT",refs[f"TP{tp}"]]["b"]
        # Target ADC node is the old main horizontal line, not capacitor pinY.
        move(f"TP{tp}",tpbody["x"]+x(455)-old_adc_node[0],tpbody["y"]+y(200)-old_main_y)
        move(capflag,x(455),y(255))
        set_wire(rawwid,rawnet,[((x(235),y(190)),(x(240),y(190)))],(x(235),y(190)),scope+"/raw")
        set_wire(mixwid,pre,[((x(270),y(190)),(x(280),y(190))),((x(280),y(190)),(x(305),y(190))),
            ((x(280),y(165)),(x(280),y(190))),((x(280),y(190)),(x(280),y(225)))],(x(280),y(190)),scope+"/pre")
        set_wire(biaswid,"ADC_BIAS_2V5",[((x(280),y(135)),(x(280),y(115)))],(x(280),y(115)),scope+"/bias")
        set_wire(adcwid,old_net,[((x(435),y(200)),(x(455),y(200))),((x(455),y(200)),(x(500),y(200))),
            ((x(455),y(185)),(x(455),y(200))),((x(455),y(200)),(x(455),y(220)))],(x(500),y(200)),scope+"/adc")
        set_wire(capgnd,"GND",[((x(455),y(240)),(x(455),y(250)))],(x(455),y(245)),scope+"/adc-gnd")
        drvpath=[(x(390),y(200)),(x(400),y(200)),(x(405),y(200))]
        feedback=[(x(400),y(200)),(x(400),y(265)),(x(295),y(265)),(x(295),y(210)),(x(305),y(210))]
        wire(drv,list(zip(drvpath,drvpath[1:]))+list(zip(feedback,feedback[1:])),scope+"/driver",drvpath[0])
        wire("GND",[((x(280),y(245)),(x(280),y(255)))],scope+"/pre-gnd",(x(280),y(255)))
        power=[(x(345),y(165)),(x(345),y(130)),(x(440),y(130)),(x(440),y(135))]
        wire("+3V3",list(zip(power,power[1:])),scope+"/power",power[0])
        wire("GND",[((x(345),y(235)),(x(345),y(240)))],scope+"/opamp-gnd",(x(345),y(240)))
        wire("GND",[((x(440),y(155)),(x(440),y(165)))],scope+"/decap-gnd",(x(440),y(165)))
        for value,xx,yy,name,size in (("ADC_BIAS_2V5",252,105,"bias",5.5),("C0G",470,245,"c0g",4.5),
            ("GND",267,268,"pre-gnd-label",5.5),("+3V3",335,120,"supply-label",5.5),("GND",332,253,"opa-gnd-label",5.5),
            ("GND",422,168,"decap-gnd-label",5.5)):
            text(value,x(xx),y(yy),scope+"/"+name,size)
        # Translate original exact MCU pin glyphs, ADC port vectors and junction
        # dots. Device-owned resistor/capacitor glyphs disappear by rebinding.
        for k,r in old.items():
            b=r["b"]
            if k[0]!="POLY" or not b.get("points"):
                continue
            pts=b["points"]
            if b.get("strokeColor")=="#840000" and all(old_port[0]-.01<=p["x"]<=old_port[0]+45 and old_main_y-5<=p["y"]<=old_main_y+5 for p in pts):
                translate(lookup[k]["b"],x(500)-old_port[0],y(200)-old_main_y)
            elif b.get("fillColor")=="#0000FF" and all(old_adc_node[0]+4<=p["x"]<=old_adc_node[0]+50 and old_main_y-12<=p["y"]<=old_main_y+3 for p in pts):
                translate(lookup[k]["b"],x(455)-old_adc_node[0],y(200)-old_main_y)
            elif b.get("fillColor")=="#009600" and all(abs(p["x"]-old_junction_x)<2 and abs(p["y"]-old_main_y)<2 for p in pts):
                translate(lookup[k]["b"],x(280)-old_junction_x,y(190)-old_main_y)
            elif b.get("fillColor")=="#009600" and all(abs(p["x"]-old_adc_node[0])<2 and abs(p["y"]-old_main_y)<2 for p in pts):
                translate(lookup[k]["b"],x(455)-old_adc_node[0],y(200)-old_main_y)
        dot=copy.deepcopy(old["POLY","430d4377cb89570b"]["b"])
        translate(dot,x(400)-455,dy)
        add("POLY",dot,scope+"/feedback-dot")
        layout.append({"bank":bank,"channelInBank":tp-3 if bank==2 else tp-6,"smaRef":f"J{j}","offset":[off,dy],
            "adcPort":old_net,"adcPortPoint":[x(500),y(200)],"bias":f"R{rb}","input":f"R{ri}","series":f"R{rs}","adcCap":f"C{c}",
            "deletedDnp":f"R{rdnp}","opamp":u,"preCap":pre_c,"decap":dec_c,"preNet":pre,"driverNet":drv,
            "oldMixNet":old_attrs[mixwid]["NET"]["value"],"pins":{ref:component_pins(ref) for ref in (f"J{j}",f"R{rb}",f"R{ri}",f"R{rs}",f"C{c}",u,pre_c,dec_c,f"TP{tp}")}})
    rows=[r for r in rows if (r["h"]["type"],r["h"].get("id")) not in removed]
    final={(r["h"]["type"],r["h"].get("id")):r for r in rows}
    assert len(final)==len(rows)
    changes=[{"type":k[0],"id":k[1],"before":old[k]["b"],"after":final[k]["b"]} for k in sorted(old.keys()&final.keys(),key=str) if old[k]["b"]!=final[k]["b"]]
    deleted=[old[k] for k in sorted(old.keys()-final.keys(),key=str)]
    added=[final[k] for k in sorted(final.keys()-old.keys(),key=str)]
    # REF/J18 record bodies are literal exact, including all locally connected
    # lines and their attrs. Existing ADC1 electrical/body placement is intact.
    protected=[]
    for k,r in old.items():
        b=r["b"]
        points=[]
        if b.get("x") is not None and b.get("y") is not None:
            points=[(b["x"],b["y"])]
        if k[0]=="LINE": points=[(b["startX"],b["startY"]),(b["endX"],b["endY"])]
        if k[0]=="POLY": points=[(p["x"],p["y"]) for p in b.get("points",[])]
        if points and (all(980<=x<=1450 and 710<=y<=865 for x,y in points) or all(600<=x<=1025 and 785<=y<=990 for x,y in points)):
            assert k in final
            if k in caption_keys:
                assert {f:v for f,v in final[k]["b"].items() if f!="value"}=={f:v for f,v in b.items() if f!="value"}
            else:
                assert final[k]["b"]==b,("REF/J18 protected",k)
            protected.append(k)
    candidate=HERE/"06_ADC_TIMER_DAC_adc10_candidate.epru"
    candidate.write_text("".join(json.dumps(r["h"],separators=(",",":"))+"||"+json.dumps(r["b"],separators=(",",":"))+"|\n" for r in rows),encoding="utf8",newline="\n")
    plan={"schema":"adc10-dc-buffer-offline-plan-20261017-v1","baselinePath":str(BASE),"baselineSha256":BASE_SHA,"candidatePath":str(candidate),
        "candidateSha256":hashlib.sha256(candidate.read_bytes()).hexdigest(),"checkpointPath":str(CHECKPOINT),"pageUuid":"a07bf8e4331877a8",
        "changes":changes,"deleted":deleted,"added":added,"components":specs,"layout":layout,
        "approvedAuxiliaryReflowScopes":{s:sorted(keys) for s,keys in scopes.items()},"protectedRefJ18GeometryRecordKeys":protected,
        "physicalPartCountExpected":354,"connectedPinCountExpected":1136,"newRefs":[s["ref"] for s in specs if s["new"]],
        "deletedDnpRefs":["R158","R159","R160","R173","R174","R175","R176"],"allLibrariesReusedUnchanged":True,
        "electricalContract":{"gainNominalLowSourceZ":.5,"offsetV":1.25,"inputRangeV":[-2,2],"adcRangeV":[.25,2.25],
            "dcCoupled":True,"newRawZeroDetector":False,"floatingInputRemains2V5":True,"firmwareUnchanged":True,"pcbNotYetMutated":True},
        "notes":["Fresh source differs onlyDOCHEAD from last reviewed inline source; all user geometry kept.","Seven channels reuse verified ADC1 runtime devices, symbol and footprints; no library creation.",
            "REF/J18 placement/components/wiring remain exact; only two root-approved REF TEXT values updated to allten scope/date with every other text field exact.",
            "TIMER+95y and DAC/MCO+100y complete connected blocks are approved electrical-no-op reflow.","Native ERC/netlist/save/reopen plus visual QA required before live apply."]}
    (HERE/"adc10-schematic-plan.json").write_text(json.dumps(plan,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"candidate":str(candidate),"sha256":plan["candidateSha256"],"records":len(rows),"changed":len(changes),"deleted":len(deleted),"added":len(added),"newRefs":plan["newRefs"],"rebinds":len(specs)-21},indent=2))


if __name__=="__main__":
    main()
