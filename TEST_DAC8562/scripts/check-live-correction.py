import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/schematic-correction'
s=importlib.util.spec_from_file_location('audit',ROOT/'scripts/audit-schematic-correction.py');a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
v=json.loads((OUT/(sys.argv[1] if len(sys.argv)>1 else 'live-validation.json')).read_text(encoding='utf8'))
netlist={};net=None
for line in v['pages'][-1]['netlist'].splitlines():
    t=line.strip()
    if t=='(':net='';continue
    if t==')':net=None;continue
    if net is None:continue
    if not net:net=t;netlist.setdefault(net,[])
    elif t:netlist[net].append(re.sub(r'^([^-]+)-([^ ]+).*',r'\1.\2',t))
netlist_pins=defaultdict(list)
for net,pins in netlist.items():
    for pin in pins:netlist_pins[pin].append(net)
allpins={};pages=[]
for page in v['pages']:
    doc=next(iter(a.io.documents(page['source']).values()))
    pn,shorts,floating=a.graph(doc);allpins.update(pn)
    attrs=a.io.attrs(doc)
    segments=[p for (kind,_),(_,p) in doc['records'].items() if kind=='LINE' and p.get('lineGroup')]
    floating_flags=[]
    for (kind,pid),(_,comp) in doc['records'].items():
        if kind!='COMPONENT' or not attrs.get(pid,{}).get('Global Net Name'): continue
        for pin,pt in a.component_pins(comp,attrs[pid]):
            if not any(a.on(pt,(p['startX'],p['startY']),(p['endX'],p['endY'])) for p in segments):
                floating_flags.append({'id':pid,'net':attrs[pid]['Global Net Name'],'point':pt})
    pages.append({'page':page['page'],'shorts':shorts,'floating':floating,'floatingNetFlags':floating_flags})
constraints=[{'pin':pin,'expected':nets,'geometry':allpins.get(pin),'nativeNetlist':sorted(netlist_pins.get(pin,[]))} for pin,nets in a.constraints.items() if allpins.get(pin)!=nets or sorted(netlist_pins.get(pin,[]))!=nets]
mismatches=[{'pin':pin,'geometry':nets,'native':sorted(netlist_pins.get(pin,[]))} for pin,nets in allpins.items() if nets and sorted(netlist_pins.get(pin,[]))!=nets]
export=a.io.read_export(OUT/(sys.argv[2] if len(sys.argv)>2 else 'DAC8562 module_schematic_corrected.epro2'))
before=a.io.read_export(ROOT/'backups/DAC8562_live_before_schematic_correction_2026-10-12.epro2')
result={'pages':pages,'constraintFailures':constraints,'geometryNativeMismatches':mismatches,'nets':len(netlist),
        'pcbUnchanged':a.io.data_hash(export['4e08f91f9a2c4fe4'])==a.io.data_hash(before['4e08f91f9a2c4fe4']),
        'panelUnchanged':a.io.data_hash(export['458da9240aa63aad'])==a.io.data_hash(before['458da9240aa63aad'])}
(OUT/(sys.argv[3] if len(sys.argv)>3 else 'live-connectivity-audit.json')).write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps(result,indent=2))
