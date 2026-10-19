"""Local regulator presentation and missing explicit net-label restoration.
Never changes the protected R102.1 / MCU_RECEIVE_A junction.
"""
import copy,importlib.util,json
from collections import defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('draw',root/'scripts/redraw-readable-schematics.py');d=importlib.util.module_from_spec(s);s.loader.exec_module(d)
before=json.loads((root/'output/preflight-before-pages.json').read_text(encoding='utf8'))
plan=json.loads((out/'net-restoration-plan.json').read_text(encoding='utf8'))
for pg in before['pages']:
 page=d.Page(pg);aa=d.io.attrs(page.doc)
 for edit in next(p['edits'] for p in plan if p['page']==pg['page']):
  wid=edit['id'];segments=[p for (t,i),(_,p) in page.doc['records'].items() if t=='LINE' and p.get('lineGroup')==wid]
  first=segments[0];x,y=first['endX'],first['endY']
  # A visible native NET label is intentional here, not a hidden alias or
  # non-electrical TEXT which can vanish on a fresh project reload.
  page.attr(wid,'NET',edit['net'],x,y-8,True,7)
 if pg['page']=='e58bcc16379b10f4':
  names=['U2','R22','R23','C14','C27','C15'];allowed={page.comp[n]['id'] for n in names}
  removed=set()
  for (t,i),(_,p) in page.doc['records'].items():
   if t=='LINE' and p.get('lineGroup') and 970<=min(p['startX'],p['endX']) and max(p['startX'],p['endX'])<=1510 and -2730<=min(p['startY'],p['endY']) and max(p['startY'],p['endY'])<=-2520:removed.add(p['lineGroup'])
   if t=='COMPONENT' and i not in allowed and not aa.get(i,{}).get('Designator') and 970<=p.get('x',0)<=1510 and -2730<=p.get('y',0)<=-2520:removed.add(i)
  page.doc['records']={k:v for k,v in page.doc['records'].items() if k[1] not in removed and v[1].get('parentId') not in removed and v[1].get('lineGroup') not in removed}
  original_wire_ids={i for t,i in page.doc['records'] if t=='WIRE'}
  # Keep U2 pin ordering, and keep original C27 pin-to-PCB mapping.
  page.move('U2',1060,-2620)
  page.move('R22',1250,-2630,0)
  page.move('R23',1380,-2560,270)
  page.move('C27',1250,-2680,0)
  page.move('C15',1480,-2550,270)
  page.move('C14',970,-2550,270)
  for key,net in [('1','VDD5'),('2','DAC_AVDD_FB'),('4','GND')]:
   p=page.pin('U2',key)
   if key=='1':page.wire(net,[p,(1170,p[1]),page.pin('R22',1)],(1160,p[1]-8))
   if key=='2':page.wire(net,[p,(1380,p[1]),page.pin('R23',1)],(1190,p[1]-8))
   if key=='4':page.wire(net,[p,(1160,p[1]),(1160,-2510),(1480,-2510)],(1160,-2502))
  page.wire('VDD5',[page.pin('C27',1),(1170,-2680),(1170,-2630)])
  page.wire('DAC_AVDD_FB',[page.pin('R22',2),(1380,-2630),(1380,-2620)])
  page.wire('DAC_AVDD_FB',[page.pin('C27',2),(1380,-2680),(1380,-2620)])
  page.wire('VDD5',[(1170,-2630),(1170,-2720),(1480,-2720),page.pin('C15',1)])
  page.port('VDD5',(1480,-2720),'out')
  page.wire('GND',[page.pin('R23',2),(1380,-2510)])
  page.wire('GND',[page.pin('C15',2),(1480,-2510)])
  page.port('GND',(1480,-2510),'ground')
  page.wire('LDO_BYP',[page.pin('U2',6),(1000,-2610),(1000,-2600),(970,-2600),page.pin('C14',1)],(970,-2608))
  page.wire('GND',[page.pin('C14',2),(970,-2510),(1160,-2510)])
  page.wire('GND',[page.pin('U2',9),(910,-2640),(910,-2510),(1160,-2510)])
  page.wire('VPOS12',[page.pin('U2',8),(930,-2630),(930,-2600),page.pin('U2',5)],(910,-2640))
  page.port('VPOS12',(930,-2630),'power')
  for pin in (3,7):page.comp['U2']['pins'][str(pin)] # Existing native NC markers are preserved.
  # Use one actual WIRE parent for each locally connected circuit, so a T
  # connection does not depend on duplicate hidden aliases / label presence.
  attrs=d.io.attrs(page.doc);by_net=defaultdict(list)
  for t,i in page.doc['records']:
   if t=='WIRE' and i not in original_wire_ids:by_net[attrs[i]['NET']].append(i)
  for net,ids in by_net.items():
   keeper=ids[0];discard=set(ids[1:]);label=None
   for (t,i),(_,p) in page.doc['records'].items():
    if t=='ATTR' and p.get('parentId') in ids and p.get('key')=='NET' and p.get('valueVisible'):label=(p['x'],p['y'])
   page.doc['records']={k:v for k,v in page.doc['records'].items() if k[1] not in discard and v[1].get('parentId') not in discard}
   for (t,i),(h,p) in page.doc['records'].items():
    if t=='LINE' and p.get('lineGroup') in discard:p['lineGroup']=keeper
    if t=='ATTR' and p.get('parentId')==keeper and p.get('key')=='NET' and label:p.update(x=label[0],y=label[1],valueVisible=True)
 # Assembly choices verified against current land patterns; no pin identity,
 # footprint, gain resistor value, placement, or protected R102 wire changes.
 for ref,c in page.comp.items():
  mpn=c['props'].get('Manufacturer Part','');changes={}
  if mpn=='RG1608N-1003-W-T5':changes['Manufacturer Part']='RG1608N-104-W-T5'
  if mpn=='RG1608N-1002-W-T5':changes['Manufacturer Part']='RG1608N-103-W-T5'
  if ref=='J1':changes.update({'Manufacturer':'Samtec','Manufacturer Part':'SSW-105-02-G-D','Supplier':'Manual procurement','Supplier Part':'','Name':'={Manufacturer Part}','Datasheet':'https://suddendocs.samtec.com/prints/ssw-d.pdf'})
  if ref=='R30':changes.update({'Manufacturer Part':'RT0603BRD07115KL','Value':'115kΩ','Name':'={Value}','Supplier':'Manual procurement','Supplier Part':''})
  if ref=='R34':changes.update({'Manufacturer Part':'RT0603BRD07261KL','Value':'261kΩ','Name':'={Value}','Supplier':'Manual procurement','Supplier Part':''})
  for (t,i),(_,p) in list(page.doc['records'].items()):
   if t=='ATTR' and p.get('parentId')==c['id'] and p.get('key') in changes:
    p=copy.deepcopy(p);p['value']=changes[p['key']];page.rec('ATTR',p,i)
 target=out/('DAC8562.preflight-source.txt' if pg['page']=='e58bcc16379b10f4' else 'DAC_MCU.preflight-source.txt')
 target.write_text(d.io.source_of(page.doc),encoding='utf8');print(target)
