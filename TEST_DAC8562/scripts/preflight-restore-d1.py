"""Preserve the original boost rectifier line outside the LDO drawing region."""
import copy,importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('m',root/'scripts/readability-model.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
c=json.loads((out/'native-validation.json').read_text(encoding='utf8'));doc=next(iter(m.io.documents(c['pages'][0]['source']).values()))
old=next(iter(m.io.documents((out/'DAC8562.tidied-source.txt').read_text(encoding='utf8')).values()));a=m.io.attrs(old)
point=m.components(old)['D1']['pins']['1'];groups={p['lineGroup'] for (t,i),(_,p) in old['records'].items() if t=='LINE' and ((p['startX'],p['startY'])==point or (p['endX'],p['endY'])==point)}
assert len(groups)==1
clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100
for key,(h,p) in old['records'].items():
 if key[1] in groups or p.get('parentId') in groups or p.get('lineGroup') in groups:
  clock+=1;header=dict(h);header['ticket']=clock;doc['records'][key]=(header,copy.deepcopy(p))
(out/'DAC8562.final-source.txt').write_text(m.io.source_of(doc),encoding='utf8')
print('Restored original D1.1 VPOS12 branch',point,groups)
