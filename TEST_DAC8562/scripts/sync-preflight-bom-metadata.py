"""Synchronize assembly metadata only; never changes PCB pad nets or geometry."""
import copy,importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
sc=json.loads((out/'native-validation.json').read_text(encoding='utf8'));pcb=json.loads((out/'pcb-native-review.json').read_text(encoding='utf8'))
parts={}
for pg in sc['pages']:
 for props in io.attrs(next(iter(io.documents(pg['source']).values()))).values():
  if props.get('Designator'):parts[props['Designator']]=props
doc=next(iter(io.documents(pcb['source']).values()));aa=io.attrs(doc);before=copy.deepcopy(doc)
clock=max(h.get('ticket',0) for h,p in doc['records'].values())+100;edits=[]
for key,(h,p) in doc['records'].items():
 if key[0]!='COMPONENT':continue
 ref=aa[key[1]]['Designator'];props=parts[ref]
 if ref!='J1' and not (ref in ('R30','R34') or str(props.get('Manufacturer Part','')).startswith(('RG1608N-104-','RG1608N-103-'))):continue
 changed={}
 for k in ('Manufacturer','Manufacturer Part','Supplier','Supplier Part','Name','Value'):
  if k in props and p['attrs'].get(k)!=props[k]:changed[k]=[p['attrs'].get(k),props[k]];p['attrs'][k]=props[k]
 if changed:clock+=1;h['ticket']=clock;edits.append({'ref':ref,'fields':changed})
for key in doc['records']:
 a=copy.deepcopy(before['records'][key][1]);b=copy.deepcopy(doc['records'][key][1])
 if key[0]=='COMPONENT':a.pop('attrs',None);b.pop('attrs',None)
 assert a==b,('Unexpected physical edit',key)
(out/'PCB.bom-metadata-source.txt').write_text(io.source_of(doc),encoding='utf8')
(out/'bom-metadata-change-plan.json').write_text(json.dumps({'layoutRoutingPadNetsUnchanged':True,'edits':edits},indent=2),encoding='utf8')
print(json.dumps({'componentMetadataUpdates':len(edits),'physicalGeometryUnchanged':True}))
