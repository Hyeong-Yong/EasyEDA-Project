"""Read current native symbols and pin coordinates without changing documents."""
import importlib.util
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/readability'
spec=importlib.util.spec_from_file_location('cio',ROOT/'scripts/correction-io.py')
io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
LIB=io.read_export(ROOT/'backups/DAC8562_live_before_readability_2026-10-12.epro2')
final_export=ROOT/'output/final-review/DAC8562 module_final_review_ERC_DRC_clean.epro2'
if final_export.exists():LIB.update(io.read_export(final_export))
elif (OUT/'Q3_library_loaded.epro2').exists():LIB.update(io.read_export(OUT/'Q3_library_loaded.epro2'))
BEFORE=json.loads((OUT/'before-pages.json').read_text(encoding='utf8'))

def pins(item,props):
    sym=LIB[props['Symbol']];a=io.attrs(sym);r=-math.radians(item.get('rotation',0))
    result={}
    for (typ,pid),(_,p) in sym['records'].items():
        if typ!='PIN' or p.get('partId','')!=item.get('partId',''):continue
        x=p['x']*math.cos(r)-p['y']*math.sin(r)
        y=p['x']*math.sin(r)+p['y']*math.cos(r)
        if item.get('isMirror'):x=-x
        result[str(a[pid].get('Pin Number',''))]=(round(item['x']+x,6),round(item['y']+y,6))
    return result

def components(doc):
    a=io.attrs(doc);result={}
    for (typ,pid),(_,p) in doc['records'].items():
        if typ!='COMPONENT' or not a.get(pid,{}).get('Designator'):continue
        props=a[pid];name=props['Designator'];pp=pins(p,props)
        if name in ('U101','U102','U103'):
            name += 'A' if '1' in pp else 'B'
        result[name]={'id':pid,'item':p,'props':props,'pins':pp}
    return result

if __name__=='__main__':
    for page in BEFORE['pages']:
        doc=next(iter(io.documents(page['source']).values()));a=io.attrs(doc)
        print('PAGE',page['page'])
        for name,c in components(doc).items():
            if page['page']=='e58bcc16379b10f4' and c['item']['y'] < -1500:continue
            print(name,{k:c['item'].get(k) for k in ['x','y','rotation','isMirror','partId']},c['pins'])
        flags=[(pid,p,a[pid]) for (t,pid),(_,p) in doc['records'].items() if t=='COMPONENT' and a.get(pid,{}).get('Global Net Name')]
        print('FLAGS',[(x[2].get('Global Net Name'),x[2].get('Symbol'),x[1]) for x in flags[:4]])
