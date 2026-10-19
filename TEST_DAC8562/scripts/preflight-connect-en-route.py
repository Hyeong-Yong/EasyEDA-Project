"""Direct IN/EN wiring with a non-junction NR crossing, never overlapping wires."""
import copy,importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
c=json.loads((out/'native-validation.json').read_text(encoding='utf8'));doc=next(iter(io.documents(c['pages'][0]['source']).values()));aa=io.attrs(doc)
clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100
def update(key,p):
 global clock
 clock+=1;h=dict(doc['records'][key][0]);h['ticket']=clock;doc['records'][key]=(h,p)
drop={i for (t,i),(_,p) in doc['records'].items() if t=='COMPONENT' and p.get('x')==995 and p.get('y')==-2600 and aa.get(i,{}).get('Global Net Name')=='VPOS12'}
doc['records']={k:v for k,v in doc['records'].items() if k[1] not in drop and v[1].get('parentId') not in drop}
for key,(h,p) in list(doc['records'].items()):
 if key[0]=='LINE' and aa.get(p.get('lineGroup'),{}).get('NET')=='VPOS12' and p.get('startY')==p.get('endY')==-2600:
  q=copy.deepcopy(p);q['endX']=930;update(key,q)
  clock+=1;doc['records'][('LINE','caba6de762ef4e61')]=({'type':'LINE','id':'caba6de762ef4e61','ticket':clock},{**q,'startX':930,'endX':930,'startY':-2600,'endY':-2630})
(out/'DAC8562.final-source.txt').write_text(io.source_of(doc),encoding='utf8')
