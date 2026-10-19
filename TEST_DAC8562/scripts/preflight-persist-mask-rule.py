"""Persist top pad mask expansion as a native rule; virtual pad API didn't serialize."""
import copy,importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
capture=json.loads((out/'pcb-mask-reviewed.json').read_text(encoding='utf8'));doc=next(iter(io.documents(capture['source']).values()))
key=('RULE','["RULE","SOLDER","solderMaskExpansion"]');h,p=doc['records'][key];p=copy.deepcopy(p)
assert p['ruleContext']['padTopExpan']==2
p['ruleContext']['padTopExpan']=1
h=dict(h);h['ticket']=max(hh.get('ticket',0) for hh,pp in doc['records'].values())+100
doc['records'][key]=(h,p)
(out/'PCB.mask-rule-source.txt').write_text(io.source_of(doc),encoding='utf8')
