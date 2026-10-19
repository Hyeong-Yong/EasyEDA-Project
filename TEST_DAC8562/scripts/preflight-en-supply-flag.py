import importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('d',root/'scripts/redraw-readable-schematics.py');d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
capture=json.loads((out/'native-validation.json').read_text(encoding='utf8'));page=d.Page(capture['pages'][0])
page.port('VPOS12',(995,-2600),'power',180,(45,28))
for key,(h,p) in list(page.doc['records'].items()):
 if key[0]=='ATTR' and p.get('parentId')=='3a50b23fb2f84746' and p.get('key')=='NET':p=dict(p);p['valueVisible']=False;page.rec('ATTR',p,key[1])
(out/'DAC8562.final-source.txt').write_text(d.io.source_of(page.doc),encoding='utf8')
