import importlib.util,json
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
c=json.loads((root/'output/manufacturing-preflight/native-validation.json').read_text(encoding='utf8'))
for pg in c['pages']:
 d=next(iter(io.documents(pg['source']).values()));aa=io.attrs(d);groups=defaultdict(list)
 for (t,i),(h,p) in d['records'].items():
  if t=='ATTR' and p.get('key')=='NET':groups[p['parentId']].append((i,p))
 print(pg['page'],'Duplicate NET parents',[(k,len(v)) for k,v in groups.items() if len(v)>1])
 for (t,i),(_,p) in d['records'].items():
  if t=='TEXT' and (p.get('value','').startswith('TPS7') or p.get('value','').startswith('02 ')):print('TEXT',i,p)
  if t=='ATTR' and aa.get(p.get('parentId'),{}).get('Designator') in ('R15','C25','R12','R14','U2') and p.get('valueVisible'):print('LABEL',i,p)
