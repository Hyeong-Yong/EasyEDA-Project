import importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/pcb-two-zone'
spec=importlib.util.spec_from_file_location('io_c',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
v=json.loads((out/'native-save-reopen-first.json').read_text(encoding='utf8'));doc=next(iter(io.documents(v['source']).values()));attrs=io.attrs(doc)
model=json.loads((out/'physical-model.json').read_text(encoding='utf8'))
before=json.loads((out.parent/'schematic-correction/pcb-before-inventory.json').read_text(encoding='utf8'))
old=next(iter(io.documents(before['source']).values()))
old_attrs=io.attrs(old)
legacy=next(p['attrs']['Channel ID'] for (typ,pid),(_,p) in old['records'].items() if typ=='COMPONENT' and old_attrs.get(pid,{}).get('Designator')=='U1')
for (typ,pid),(_,p) in doc['records'].items():
    if typ!='COMPONENT':continue
    name=attrs[pid]['Designator'];p['attrs']['Channel ID']=legacy if model[name]['page']=='e58bcc16379b10f4' else model[name]['page']
(out/'linked-channel-source.txt').write_text(io.source_of(doc),encoding='utf8',newline='\n')
