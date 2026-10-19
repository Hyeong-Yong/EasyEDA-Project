"""Consolidate repeated regulator supply identity; space adjacent control names."""
import copy,importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
capture=json.loads((out/'native-validation.json').read_text(encoding='utf8'))
for pg in capture['pages']:
 doc=next(iter(io.documents(pg['source']).values()));aa=io.attrs(doc)
 clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100
 def replace(key,p):
  global clock
  clock+=1;h=copy.deepcopy(doc['records'][key][0]);h['ticket']=clock;doc['records'][key]=(h,p)
 if pg['page']=='e58bcc16379b10f4':
  groups={p['lineGroup'] for (t,i),(_,p) in doc['records'].items() if t=='LINE' and aa.get(p.get('lineGroup'),{}).get('NET')=='VPOS12' and p.get('startX')==1015 and p.get('startY') in (-2630,-2600)}
  assert len(groups)==2
  keep='3a50b23fb2f84746';assert keep in groups
  for key,(_,p) in list(doc['records'].items()):
   if key[0]=='LINE' and p.get('lineGroup') in groups-{keep}:q=copy.deepcopy(p);q['lineGroup']=keep;replace(key,q)
  removed=groups-{keep}
  doc['records']={k:v for k,v in doc['records'].items() if k[1] not in removed and v[1].get('parentId') not in removed}
  # Visible supply name at EN; the existing IN power flag remains unchanged.
  for key,(_,p) in list(doc['records'].items()):
   if key[0]=='ATTR' and p.get('parentId')==keep and p.get('key')=='NET':q=copy.deepcopy(p);q.update(valueVisible=True,x=980,y=-2592);replace(key,q)
 else:
  # These attributes identify two separate nearby ports, not an added wire.
  for key,(_,p) in list(doc['records'].items()):
   if key[0]=='ATTR' and p.get('key')=='Name' and p.get('parentId')=='dfa65fe16e29451b':q=copy.deepcopy(p);q.update(y=-581);replace(key,q)
  # Hide a redundant name on the physically wired relay B input, keep port.
  for key,(_,p) in list(doc['records'].items()):
   if key[0]=='ATTR' and p.get('key')=='NET' and p.get('value')=='MCU_RCV_EXTERNAL_B' and -790<p.get('y',0)<-235:q=copy.deepcopy(p);q['valueVisible']=False;replace(key,q)
 (out/('DAC8562.final-source.txt' if pg['page']=='e58bcc16379b10f4' else 'DAC_MCU.final-source.txt')).write_text(io.source_of(doc),encoding='utf8')
