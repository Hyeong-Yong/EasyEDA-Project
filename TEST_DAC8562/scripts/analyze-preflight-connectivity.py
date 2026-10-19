"""Read-only fresh native topology analysis and user screenshot questions."""
import importlib.util,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('audit',root/'scripts/audit-readable-schematics.py')
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
capture=json.loads((root/'output/preflight-before-pages.json').read_text(encoding='utf8'))
old=json.loads((root/'output/readability/native-validation.json').read_text(encoding='utf8'))
for pg in capture['pages']:
 doc=next(iter(a.io.documents(pg['source']).values()));props=a.io.attrs(doc)
 pn,shorts=a.graph(doc);prior=next(p for p in old['pages'] if p['page']==pg['page']);pd=next(iter(a.io.documents(prior['source']).values()));op,os=a.graph(pd)
 print('PAGE',pg['page'],'GEOMETRIC PIN DIFF',json.dumps({k:[op.get(k),pn.get(k)] for k in set(op)|set(pn) if op.get(k)!=pn.get(k)}),'shorts',shorts)
 requested=['MCU_RECEIVE_A','MCU_VBIAS','$1N2213','$1N2214','$1N2215','$1N2216','$2N434','$2N439']
 for block in re.findall(r'\(\s*\n(.*?)\n\)',pg['netlist'],re.S):
  rows=block.splitlines()
  if rows[0].strip() in requested:print('NETLIST',rows)
 for (t,i),(_,p) in doc['records'].items():
  if t=='WIRE' and props.get(i,{}).get('NET') in requested:print('WIRE',i,props.get(i),p)
 if pg['page']=='e58bcc16379b10f4':
  for ref in ['U2','R22','R23','C14','C27','C15','J1']:
   c=a.m.components(doc)[ref];print('PART',ref,c['id'],c['item'],c['pins'],c['props'])
