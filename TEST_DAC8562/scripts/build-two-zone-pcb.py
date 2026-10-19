"""Generate an unrouted two-zone PCB from the verified schematic, retaining rules."""
import copy, hashlib, importlib.util, json, math
from pathlib import Path
spec=importlib.util.spec_from_file_location('model',Path(__file__).with_name('pcb-physical-model.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
MM=1/.0254
POS={
 'J1':(14,95,0),'J4':(55,95,0),'J2':(95.85,90,180),'J3':(95.85,75,180),
 'U1':(23,82,0),'Q1':(13,90,180),'L1':(16,85,0),'L2':(31,81,0),'D1':(26,90,270),'D2':(27,76,270),
 'C6':(16,92,0),'C7':(19,79,90),'C8':(22,78,90),'C9':(30,93,0),'C10':(35,93,0),'C11':(30,71,0),'C12':(35,71,0),
 'R1':(22,86,90),'R2':(24,86,90),'C1':(22,88.5,0),'C5':(26,85,90),'C4':(28,84,0),'C2':(30,85.5,0),'C3':(31,87,0),
 'R3':(29,83,0),'R4':(32,83,0),'R5':(19,76,0),
 'U2':(43,87,0),'C13':(41.8,91,0),'C14':(46,90,0),'C15':(40.5,83,180),'C27':(44.2,82,0),'R22':(44.2,83.5,0),'R23':(47.2,83.5,0),
 'U3':(60,86,0),'C16':(58,90,0),'C17':(63,90,0),'C24':(56,88,180),'R6':(62,79,0),'R7':(65,79,0),'R8':(59,81,90),'R9':(61,81,90),'R10':(57,81,90),
 'U4':(74,81,180),'K1':(86,83,180),'R12':(72,89,0),'R13':(76,89,180),'R14':(69,86,0),'R15':(69,83,90),'R16':(80,84,0),
 'R17':(71,72,0),'R18':(75,72,180),'R19':(68,75,0),'R20':(68,78,90),'R21':(80,79,0),
 'C18':(77.5,77.5,0),'C19':(70.5,82,180),'C20':(77,82,90),'C21':(71,79.5,90),'C22':(92,90,0),'C23':(92,75,0),'C25':(75.5,85.5,0),'C26':(74,76.5,0),
 'U5':(49.5,87,0),'U6':(51,77,0),'C28':(46.5,90,90),'C29':(48,80,90),'Q2':(45,76,0),'R24':(47,77,90),'R25':(44,73,0),
 'U7':(20,65,0),'R26':(24,63.5,0),'R27':(27,63.5,0),'R28':(24,66.5,0),'R29':(27,66.5,0),'C30':(19,68,90),
 'U8':(34,65,0),'R30':(38,63.5,0),'R31':(41,63.5,0),'R32':(38,66.5,0),'R33':(41,66.5,0),'C31':(33,68,90),
 'U9':(19,56,0),'R34':(23,54.5,0),'R35':(26,54.5,0),'R36':(23,57.5,0),'R37':(26,57.5,0),'C32':(18,59,90),
 'Q3':(30,56,0),'R38':(31,59,0),'R39':(35,59,0),'U10':(39,57,90),
 'U11':(47,61,0),'U12':(55,61,0),'U13':(63,61,0),'C33':(44,59,90),'C34':(52,59,90),'C35':(60,59,90),
 'R40':(47,64,0),'R41':(54,64,0),'R42':(66,61,90),'R43':(63,64,0),'Q4':(87,67,180),'D3':(91,83,270),
 'LED1':(9,65,0),'R11':(9,68,90),
 'J101':(4.15,35,0),'J102':(4.15,15,0),'J103':(95.85,35,180),'J104':(95.85,15,180),'J105':(50,7,0),
 'K101':(20,27,180),'K102':(86,27,180),'U101':(31,27,180),'U102':(50,22,180),'U103':(74,27,180),
 'R101':(12,35,0),'R111':(12,15,0),'R102':(27,32,0),'R112':(28,22,0),
 'R103':(69,32,0),'R104':(72,35,0),'R105':(76,35,180),'R106':(67,29,90),
 'R113':(68,22,0),'R114':(71,19,0),'R115':(75,19,180),'R116':(67,25,90),'R107':(80,31,0),'R117':(80,23,0),
 'C101':(75.5,31.5,0),'C111':(74,22.5,0),'C102':(92,35,0),'C112':(92,15,0),
 'R121':(49,28,0),'R122':(52,28,0),'C121':(35,23.5,0),'C122':(27.5,29,180),'C123':(54,18.5,0),'C124':(46.5,24,180),'C125':(78,23.5,0),'C126':(70.5,29,180),
 'U104':(21,42,0),'U105':(83,42,0),'Q101':(18,37,180),'Q102':(88,40,180),'D101':(25,26,270),'D102':(91,27,270),
 'R123':(18,40,0),'R124':(24,42,90),'R125':(88,43,0),'R126':(86,45,0),'C127':(18,44,0),'C128':(80,40,90),
}
assert set(POS)==set(m.PARTS),(sorted(set(m.PARTS)-set(POS)),sorted(set(POS)-set(m.PARTS)))
(m.OUT/'initial-placement.json').write_text(json.dumps({n:{'xMm':x,'yMm':y,'angle':angle,'zone':'DAC8562' if m.PARTS[n]['page']=='e58bcc16379b10f4' else 'DAC_MCU'} for n,(x,y,angle) in POS.items()},indent=2),encoding='utf8')
if (m.OUT/'refined-placement.json').exists():
    refined=json.loads((m.OUT/'refined-placement.json').read_text(encoding='utf8'))
    POS={n:(p['xMm'],p['yMm'],p['angle']) for n,p in refined.items()}
before=json.loads((m.ROOT/'output/schematic-correction/pcb-before-inventory.json').read_text(encoding='utf8'))
base=next(iter(m.io.documents(before['source']).values()))
new={'head':copy.deepcopy(base['head']),'records':{}}
def ident(key):return hashlib.sha256(('two-zone-v1:'+key).encode()).hexdigest()[:16]
def add(typ,pid,payload):new['records'][(typ,pid)]=({'type':typ,'id':pid,'ticket':1},payload)
for (typ,pid),(h,p) in base['records'].items():
    if typ in {'CANVAS','LAYER','LAYER_PHYS','ACTIVE_LAYER','SILK_OPTS','PRIMITIVE','RULE_TEMPLATE','RULE','PREFERENCE','PANELIZE'}:
        new['records'][(typ,pid)]=(copy.deepcopy(h),copy.deepcopy(p))
new['records'][('CANVAS','CANVAS')][1].update(unit='mm')
def attr(cid,key,value,x=None,y=None,visible=False,footprint=None):
    child=next((pid for (typ,pid),(_,p) in m.LIB[footprint]['records'].items() if typ=='ATTR' and p['key']==key),None) if footprint else None
    child=child or ('e0' if key=='Device' else 'e9000')
    add('ATTR',cid+child,{'partitionId':'','groupID':0,'parentId':cid,'layerId':3,'x':x,'y':y,'key':key,'value':value,'keyVisible':False,'valueVisible':visible,'fontFamily':'default','fontSize':30,'strokeWidth':5,'bold':0,'italic':0,'origin':'LEFT_BOTTOM','angle':0,'reverse':False,'expansion':0,'mirror':False,'locked':False,'zIndex':-1,'specialColor':None})
placements={};expected_pads=[]
for name,(xm,ym,angle) in POS.items():
    part=m.PARTS[name];a=part['attributes'];cid=ident(name);x,y=xm*MM,ym*MM
    override={k:v for k,v in a.items() if k not in {'Symbol','Device','Footprint','Designator','Group ID','Channel ID','Reuse Block','Multi-Part Group'} and v is not None}
    if override.get('Name')=='={Value}':override['Name']=a.get('Value')
    override['Name']=override.get('Name') or a.get('Manufacturer Part')
    add('COMPONENT',cid,{'partitionId':'','groupId':0,'layerId':1,'x':x,'y':y,'angle':angle,'attrs':override,'locked':False,'zIndex':-1})
    attr(cid,'Device',a['Device'],footprint=part['footprint']);attr(cid,'Footprint',part['footprint'],footprint=part['footprint']);attr(cid,'Designator',name,(xm-1.0)*MM,(ym+3.8)*MM,True,part['footprint'])
    pads=[]
    for pad in part['pads']:
        pid=json.dumps(['PAD_NET',cid,pad['num'],pad['id']],separators=(',',':'))
        add('PAD_NET',pid,{'partitionId':'','padNet':pad['net'],'padLen':None,'attrsMap':{}})
        p=m.world_pad(part,pad,x,y,angle);p.update(component=cid,designator=name);pads.append(p);expected_pads.append(p)
    placements[name]={'id':cid,'xMm':xm,'yMm':ym,'angle':angle,'zone':'DAC8562' if part['page']=='e58bcc16379b10f4' else 'DAC_MCU'}
for net in sorted({p['net'] for p in expected_pads if p['net']}):
    nid=json.dumps(['NET',net],separators=(',',':'))
    add('NET',nid,{'netType':None,'specialColor':None,'retLine':True,'differentialName':None,'isPositiveNet':False,'equalLengthGroupName':None})
    pid=json.dumps(['RULE_SELECTOR',['NET',net]],separators=(',',':'))
    add('RULE_SELECTOR',pid,{'ruleOrder':4,'ruleKeyValue':{},'copperValue':{},'innerPlaneValue':{}})
def poly_path(x1,y1,x2,y2):return [x1,y1,'L',x1,y2,x2,y2,x2,y1,x1,y1]
add('POLY',ident('outline'),{'partitionId':'','groupId':0,'netName':'','layerId':11,'width':10,'path':poly_path(0,0,100*MM,100*MM),'locked':True,'zIndex':-1,'polyType':'NORMAL'})
holes=[p for (t,_),(_,p) in base['records'].items() if t=='PAD' and p['num'].startswith('MH')]
for i,(x,y) in enumerate([(5,5),(95,5),(5,95),(95,95)]):
    hole=copy.deepcopy(holes[i]);hole.update(centerX=x*MM,centerY=y*MM,num='MH'+str(i+1));add('PAD',ident('MH'+str(i+1)),hole)
    for layer in [1,2]:
        r=3.5*MM;cx,cy=x*MM,y*MM
        path=[cx+r,cy,'L']
        for j in range(1,65):path.extend([cx+r*math.cos(j*2*math.pi/64),cy+r*math.sin(j*2*math.pi/64)])
        add('REGION',ident('MHkeep'+str(i)+str(layer)),{'partitionId':'','groupId':0,'layerId':layer,'width':.2,'prohibitType':['TRACK','COMPONENT','VIA','COPPER','FILL'],'path':[path],'locked':True,'name':'M3 mounting clearance','regionType':'PROHIBIT'})
strings=[('DAC8562 - PRECISION DAC',38,98),('DAC_MCU - STM32H747 SMA',35,46),('COMMON GND / SHARED +/-12V',35,50),('DAC OUT A',87,92),('DAC OUT B',88,69),('MCU IN A',1,41),('MCU IN B',1,9),('MCU OUT A',87,41),('MCU OUT B',87,9),('5V / SPI',9,98),('MCU 3V3 / VREF+',42,3)]
for i,(text,x,y) in enumerate(strings):
    add('STRING',ident('label'+str(i)),{'partitionId':'','groupId':0,'layerId':3,'x':x*MM,'y':y*MM,'text':text,'fontFamily':'default','fontSize':45,'strokeWidth':6,'bold':0,'italic':0,'origin':'LEFT_BOTTOM','angle':0,'reverse':False,'expansion':0,'mirror':False,'locked':False,'zIndex':-1,'specialColor':None})
add('LINE',ident('separator'),{'partitionId':'','groupId':0,'netName':'','layerId':3,'startX':5*MM,'startY':48.5*MM,'endX':95*MM,'endY':48.5*MM,'width':6,'locked':False,'zIndex':-1})
assert len(placements)==154
assert all(p['yMm']>=52 for p in placements.values() if p['zone']=='DAC8562')
assert all(p['yMm']<=46 for p in placements.values() if p['zone']=='DAC_MCU')
(m.OUT/'placement.json').write_text(json.dumps(placements,indent=2),encoding='utf8')
(m.OUT/'expected-pads.json').write_text(json.dumps(expected_pads,ensure_ascii=False,indent=2),encoding='utf8')
(m.OUT/'unrouted-source.txt').write_text(m.io.source_of(new),encoding='utf8',newline='\n')
print(json.dumps({'components':len(placements),'pads':len(expected_pads),'nets':len({p['net'] for p in expected_pads if p['net']}),'zones':{z:sum(p['zone']==z for p in placements.values()) for z in ['DAC8562','DAC_MCU']},'sizeMm':[100,100]}))
