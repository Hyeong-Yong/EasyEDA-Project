import importlib.util,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('m',root/'scripts/readability-model.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
before=json.loads((root/'output/preflight-before-pages.json').read_text(encoding='utf8'))
prior=json.loads((root/'output/readability/native-validation.json').read_text(encoding='utf8'))
def pinmap(text):
 p={}
 for b in re.findall(r'\(\s*\n(.*?)\n\)',text,re.S):
  rows=b.splitlines();net=rows[0].strip()
  for row in rows[1:]:
   match=re.match(r'([^\s-]+)-([^\s]+)',row.strip())
   if match:p[match[1]+'.'+match[2].split('-')[0]]=net
 return p
old=pinmap(prior['pages'][0]['netlist']);now=pinmap(before['pages'][0]['netlist'])
diff={k:{'before':old.get(k),'now':now.get(k)} for k in set(old)|set(now) if old.get(k)!=now.get(k)}
print(json.dumps(diff,indent=2))
for pg in before['pages']:
 d=next(iter(m.io.documents(pg['source']).values()));pp=m.io.attrs(d)
 for ref,c in m.components(d).items():
  if not any(k.startswith(ref.split('A')[0]+'.') for k in diff) and ref not in ('R102','U101A'):continue
  print('PART',pg['page'],ref,c['pins'])
  for num,pt in c['pins'].items():
   k=c['props']['Designator']+'.'+num
   if k not in diff:continue
   candidates=[]
   for (t,i),(_,p) in d['records'].items():
    if t=='LINE' and p.get('lineGroup'):
     if min(abs(p[x]-pt[0])+abs(p[y]-pt[1]) for x,y in [('startX','startY'),('endX','endY')])<50:
      candidates.append((i,p,pp.get(p['lineGroup'])))
   print('NEAR',k,json.dumps(candidates))
(root/'output/preflight-netlist-differences.json').write_text(json.dumps(diff,indent=2),encoding='utf8')
