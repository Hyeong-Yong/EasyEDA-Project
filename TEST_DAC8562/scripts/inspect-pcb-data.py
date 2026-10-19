import importlib.util, json
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cio',Path(__file__).with_name('correction-io.py'));cio=importlib.util.module_from_spec(spec);spec.loader.exec_module(cio)
out=root/'output/schematic-correction'
doc=next(iter(cio.documents(json.loads((out/'pcb-before-inventory.json').read_text(encoding='utf8'))['source']).values()))
print('PCB TYPES',Counter(k[0] for k in doc['records']))
for (typ,pid),(h,p) in doc['records'].items():
    if typ in {'CANVAS','RULE','RULE_SELECTOR','POUR','REGION','COMPONENT','PAD','PAD_NET'}:
        if typ not in {'COMPONENT','PAD_NET'} or pid==next((x for (t,x) in doc['records'] if t==typ),None):
            print(typ,pid,json.dumps(p,ensure_ascii=False)[:1500])
lib=cio.read_export(out/'DAC8562 module_schematic_ERC_clean.epro2')
footprints=Counter();missing=[];parts=[]
for page in ['e58bcc16379b10f4','e3a1c5f417017755']:
    attrs=cio.attrs(lib[page]);seen=set()
    for (typ,pid),(h,p) in lib[page]['records'].items():
        a=attrs.get(pid,{})
        if typ!='COMPONENT' or not a.get('Designator') or a['Designator'] in seen: continue
        seen.add(a['Designator'])
        device=next((v['attributes'] for h,v in lib[a['Device']]['records'].values() if 'attributes' in v),{})
        footprint=a.get('Footprint') or device.get('Footprint');footprints[footprint]+=1
        if footprint not in lib:missing.append((a['Designator'],footprint))
        parts.append({'page':page,'id':pid,'designator':a['Designator'],'footprint':footprint,'mpn':a.get('Manufacturer Part')})
print('FOOTPRINTS',dict(footprints));print('MISSING',missing)
for fp,n in footprints.items():
    fd=lib.get(fp)
    if not fd: continue
    pads=[p for (t,_),(_,p) in fd['records'].items() if t=='PAD']
    print('FOOTPRINT',fp,n,fd['head'],json.dumps(pads[:2],ensure_ascii=False))
(out/'pcb-parts-plan.json').write_text(json.dumps(parts,ensure_ascii=False,indent=2),encoding='utf8')
