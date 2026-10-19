"""Remove ambiguous overlapping NR/EN drawing; preserve electrical pin nets."""
import importlib.util,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('d',root/'scripts/redraw-readable-schematics.py');d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
capture=json.loads((out/'native-validation.json').read_text(encoding='utf8'))
page=d.Page(capture['pages'][0]);aa=d.io.attrs(page.doc)
for key,(h,p) in list(page.doc['records'].items()):
 if key[0]=='LINE' and aa.get(p.get('lineGroup'),{}).get('NET')=='LDO_BYP' and 900<=p['startX']<=1020:
  page.doc['records'].pop(key)
 if key[0]=='LINE' and aa.get(p.get('lineGroup'),{}).get('NET')=='VPOS12' and p.get('startY')==p.get('endY')==-2600 and min(p['startX'],p['endX'])>=900:
  page.doc['records'].pop(key)
 if key[0]=='LINE' and aa.get(p.get('lineGroup'),{}).get('NET')=='VPOS12' and p.get('startX')==p.get('endX')==930:
  page.doc['records'].pop(key)
page.wire('LDO_BYP',[page.pin('U2',6),(970,-2610),page.pin('C14',1)],(970,-2618))
# This repeated supply stub is explicitly named rather than overlapping NR.
page.wire('VPOS12',[page.pin('U2',5),(995,-2600)],(980,-2592))
(out/'DAC8562.visual-finished-source.txt').write_text(d.io.source_of(page.doc),encoding='utf8')
