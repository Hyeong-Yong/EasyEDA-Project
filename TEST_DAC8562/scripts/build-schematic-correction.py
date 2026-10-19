"""Incremental page-1 repair and connected page-2 receiver; never emit PCB edits."""
import copy
import csv
import importlib.util
import json
import math
import uuid
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/schematic-correction'
spec = importlib.util.spec_from_file_location('correction_io', ROOT / 'scripts/correction-io.py')
io = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io)
before = io.read_export(ROOT / 'backups/DAC8562_live_before_schematic_correction_2026-10-12.epro2')
loaded = io.read_export(OUT / 'library-loaded-complete.epro2')
templates = {}

def uid():
    return uuid.uuid4().hex[:16]

for page, prefix in [(before['e58bcc16379b10f4'], 'OLD_'), (loaded['e3a1c5f417017755'], '')]:
    props = io.attrs(page)
    for (kind, ident), (_, item) in page['records'].items():
        if kind != 'COMPONENT' or not props.get(ident, {}).get('Designator'):
            continue
        a = copy.deepcopy(props[ident])
        dev = loaded[a['Device']]
        inherited = copy.deepcopy(dev['records'][('META', 'META')][1]['attributes'])
        inherited.update({k:v for k,v in a.items() if k not in ['Footprint','Symbol'] or v})
        if inherited.get('Name') == '={Value}':
            inherited['Name'] = inherited['Value']
        if inherited.get('Name') == '={Manufacturer Part}':
            inherited['Name'] = inherited['Manufacturer Part']
        key = prefix + a['Designator'].removeprefix('SEED_')
        templates.setdefault(key, (copy.deepcopy(item), inherited))

def pins(item, props):
    symbol = loaded[props['Symbol']]
    sa = io.attrs(symbol)
    angle = -math.radians(item['rotation'])
    result = {}
    for (kind, ident), (_, p) in symbol['records'].items():
        if kind != 'PIN' or p.get('partId') != item['partId']:
            continue
        x = p['x']*math.cos(angle) - p['y']*math.sin(angle)
        y = p['x']*math.sin(angle) + p['y']*math.cos(angle)
        if item.get('isMirror'):
            x = -x
        result[str(sa[ident]['Pin Number'])] = (round(item['x']+x,6), round(item['y']+y,6))
    return result

class Page:
    def __init__(self, page_id):
        self.doc = copy.deepcopy(before[page_id])
        self.ticket = max(h.get('ticket',0) for h,_ in self.doc['records'].values()) + 100
        self.components = {}
        a = io.attrs(self.doc)
        for (kind, ident), (_, p) in self.doc['records'].items():
            if kind == 'COMPONENT' and a.get(ident,{}).get('Designator'):
                name = a[ident]['Designator']
                self.components.setdefault(name, []).append({'id':ident,'name':name,'item':p,'props':a[ident], 'pins':pins(p,a[ident])})

    def rec(self, kind, data, ident=None):
        ident = ident or uid()
        self.ticket += 1
        self.doc['records'][(kind,ident)] = ({'type':kind,'id':ident,'ticket':self.ticket}, data)
        return ident

    def attr(self, parent, key, value, x=None, y=None, visible=False, size=6):
        return self.rec('ATTR', {'parentId':parent,'key':key,'value':value,'x':x,'y':y,'rotation':0,
             'fontFamily':'Arial','fontSize':size,'align':'LEFT_BOTTOM','keyVisible':False,'valueVisible':visible,'zIndex':self.ticket})

    def text(self,x,y,value,size=9):
        self.rec('TEXT', {'x':x,'y':y,'value':value,'rotation':0,'fontFamily':'Arial','fontSize':size,
                         'align':'LEFT_BOTTOM','color':'#243746','fontWeight':size>=13,'zIndex':self.ticket})

    def delete(self, ident):
        targets = {ident}
        for (kind,pid), (_,p) in self.doc['records'].items():
            if kind == 'ATTR' and p.get('parentId') == ident:
                targets.add(pid)
        self.doc['records'] = {k:v for k,v in self.doc['records'].items() if k[1] not in targets}

    def set_attrs(self, ident, updates):
        existing = {p['key']:pid for (kind,pid), (_,p) in self.doc['records'].items() if kind=='ATTR' and p.get('parentId')==ident}
        for key,value in updates.items():
            if key in existing:
                h,p = self.doc['records'][('ATTR', existing[key])]
                p=copy.deepcopy(p);p['value']=value
                self.rec('ATTR',p,existing[key])
            else:
                self.attr(ident,key,value)

    def replace(self, name, key, *, dy=0, mirror=None):
        obj = self.components[name][0]
        template, a = copy.deepcopy(templates[key])
        item = copy.deepcopy(obj['item'])
        item['partId'] = template['partId']
        item['y'] += dy
        if mirror is not None:
            item['isMirror'] = mirror
        self.rec('COMPONENT', item, obj['id'])
        a.update({'Designator':name, 'Unique ID':obj['props']['Unique ID']})
        self.set_attrs(obj['id'], a)
        obj.update(item=item,props=a,pins=pins(item,a))
        return obj

    def add(self, key, name, x, y, rotation=0, part=0, mirror=False, overrides=None):
        item,a = copy.deepcopy(templates[key])
        parts=[ident for (kind,ident) in loaded[a['Symbol']]['records'] if kind=='PART']
        item.update(x=x,y=y,rotation=rotation,isMirror=mirror,partId=parts[part],zIndex=self.ticket)
        a.update({'Designator':name,'Unique ID':'schematic-correction-'+name,'Multi-Part Group':'schematic-correction-'+name,
                  'Add into BOM':'yes','Convert to PCB':'yes'})
        if overrides:
            a.update(overrides)
        ident=self.rec('COMPONENT', item)
        is_passive=name.startswith(('R','C','L'))
        for key,value in a.items():
            visible=key in ['Designator','Name']
            if is_passive and rotation in [90,270]:
                tx,ty=x+12,y+(-6 if key=='Designator' else 10)
            else:
                tx,ty=x-20,y+(-12 if key=='Designator' else 16) if is_passive else y+(-50 if key=='Designator' else 55)
            self.attr(ident,key,value,tx if visible else None,ty if visible else None,visible)
        obj={'id':ident,'name':name,'item':item,'props':a,'pins':pins(item,a)}
        self.components.setdefault(name,[]).append(obj)
        return obj

    def wire(self, net, points, label=False):
        points=[tuple(round(v,6) for v in pt) for pt in points]
        wid=self.rec('WIRE',{'zIndex':self.ticket})
        for a,b in zip(points,points[1:]):
            if a==b:continue
            self.rec('LINE',{'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],'lineGroup':wid,
                     'strokeColor':None,'strokeStyle':None,'strokeWidth':None,'fillColor':None,'fillStyle':None,'zIndex':self.ticket})
        self.attr(wid,'NET',net,points[-1][0],points[-1][1]-3,label,5)
        return wid

    def stem(self,obj,num,net,length=25):
        pt=obj['pins'][str(num)]
        dx=pt[0]-obj['item']['x'];dy=pt[1]-obj['item']['y']
        direction=(-1 if dx<0 else 1,0) if abs(dx)>=abs(dy) or dx else (0,-1 if dy<0 else 1)
        self.wire(net,[pt,(pt[0]+length*direction[0],pt[1]+length*direction[1])],True)

    def cap(self,name,x,y,rail,ground='GND',key='OLD_C18'):
        o=self.add(key,name,x,y,270)
        top,bottom=sorted(o['pins'],key=lambda n:o['pins'][n][1])
        self.stem(o,top,rail)
        self.stem(o,bottom,ground)
        return o

    def resistor(self,name,x,y,value,top,bottom,rotation=270,precision=False):
        key = {'100k':'R100K','10k':'R10K','24.3k':'R24K3','14k':'R14K','34k':'R34K','10M':'R10M'}.get(value,'OLD_R10')
        numeric=value.removesuffix('k')
        code=numeric.replace('.','K' if value.endswith('k') else 'R') + ('K' if value.endswith('k') and '.' not in numeric else '')
        mpn = 'RT0603BRD07'+code.upper()+'L'
        overrides={'Name':value,'Value':value}
        if precision:
            code={'100k':'1003','10k':'1002','24.3k':'2432','14k':'1402'}[value]
            overrides.update({'Manufacturer':'Susumu','Manufacturer Part':'RG1608N-'+code+'-W-T5',
                'Tolerance':'±0.05%','Temperature Coefficient':'±10ppm/C','Supplier':'Manual procurement','Supplier Part':'',
                'LCSC Part Name':'','JLCPCB Part Class':'','Datasheet':'https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf'})
        elif value not in ['100k','10k','24.3k','14k','34k','10M']:
            overrides.update({'Manufacturer':'YAGEO','Manufacturer Part':mpn,'Tolerance':'±0.1%',
                'Temperature Coefficient':'±25ppm/C','Supplier':'Manual procurement','Supplier Part':'', 'LCSC Part Name':'','JLCPCB Part Class':'',
                'Datasheet':'https://www.yageo.com/upload/media/product/productsearch/datasheet/rchip/pyu-rt_51_rohs_l.pdf'})
        o=self.add(key,name,x,y,rotation,overrides=overrides)
        p,q=sorted(o['pins'],key=lambda n:o['pins'][n][1] if rotation in [90,270] else o['pins'][n][0])
        self.stem(o,p,top);self.stem(o,q,bottom)
        return o

    def save(self,name):
        # The editor source interface accepts primitives, not export-log metadata.
        data=copy.deepcopy(self.doc)
        native_name='native-page1-source.json' if self.doc['head']['uuid']=='e58bcc16379b10f4' else 'native-seed-source.json'
        native=json.loads((OUT/native_name).read_text(encoding='utf8'))['source']
        data['head']=next(iter(io.documents(native).values()))['head']
        data['records']={k:v for k,v in data['records'].items() if k[0] not in ['META','ELE_PLACEHOLDER']}
        for ticket,(header,payload) in enumerate(data['records'].values(),1):
            header.clear();header.update(type=next(k[0] for k,v in data['records'].items() if v[0] is header),ticket=ticket)
        for (kind,ident),(header,payload) in data['records'].items():header['id']=ident
        (OUT/name).write_text(io.source_of(data),encoding='utf8')


p1=Page('e58bcc16379b10f4')
p2=Page('e3a1c5f417017755')
q=p1.replace('Q1','QPM',dy=-10)
assert q['pins']==pins(templates['OLD_Q1'][0],templates['OLD_Q1'][1]), 'Replacement PMOS must preserve all original pin locations'
p1.replace('C4','OLD_C5')
p1.components['C4'][0]['props']['Symbol']=templates['OLD_C4'][1]['Symbol']
p1.components['C4'][0]['item']['partId']=templates['OLD_C4'][0]['partId']
p1.set_attrs(p1.components['C4'][0]['id'],{'Symbol':templates['OLD_C4'][1]['Symbol']})
p1.rec('COMPONENT',p1.components['C4'][0]['item'],p1.components['C4'][0]['id'])
p1.components['C4'][0]['pins']=pins(p1.components['C4'][0]['item'],p1.components['C4'][0]['props'])
p1.replace('C5','OLD_C4')
for name in ['R12','R14','R17','R19','R13','R15','R18','R20']:
    value='24.3k' if name in ['R12','R14','R17','R19'] else '100k'
    o=p1.replace(name,'R24K3' if value=='24.3k' else 'R100K')
    code='2432' if value=='24.3k' else '1003'
    update={'Name':value,'Value':value,'Manufacturer':'Susumu','Manufacturer Part':'RG1608N-'+code+'-W-T5',
        'Tolerance':'±0.05%','Temperature Coefficient':'±10ppm/C','Supplier':'Manual procurement','Supplier Part':'',
        'JLCPCB Part Class':'','LCSC Part Name':'','Datasheet':'https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf'}
    p1.set_attrs(o['id'],update);o['props'].update(update)

# Rewire only the existing LDO block. All original amplifier/SPI/power placements remain.
remove_wires=set()
for (kind,ident), (_,p) in list(p1.doc['records'].items()):
    if kind=='LINE' and p.get('lineGroup') and 850<=p['startX']<=1330 and 850<=p['endX']<=1330 and -1130<=p['startY']<=-930 and -1130<=p['endY']<=-930:
        remove_wires.add(p['lineGroup'])
for wid in remove_wires:
    for (kind,ident), (_,p) in list(p1.doc['records'].items()):
        if kind=='LINE' and p.get('lineGroup')==wid:p1.delete(ident)
    p1.delete(wid)
for (kind,ident), (_,p) in list(p1.doc['records'].items()):
    if kind=='COMPONENT' and ident not in {o['id'] for v in p1.components.values() for o in v} and 850<=p.get('x',0)<=1330 and -1130<=p.get('y',0)<=-930:
        p1.delete(ident)
ldo=p1.replace('U2','LDO',mirror=True)
p1.replace('C13','CO10');p1.replace('C15','CO10')
for n,net in [('1','VDD5'),('2','DAC_AVDD_FB'),('4','GND'),('5','VPOS12'),('6','LDO_BYP'),('8','VPOS12'),('9','GND')]:
    p1.stem(ldo,n,net,15 if n=='4' else 25)
for name,rail in [('C13','VPOS12'),('C14','LDO_BYP'),('C15','VDD5')]:
    o=p1.components[name][0]
    top,bottom=sorted(o['pins'],key=lambda n:o['pins'][n][1])
    p1.stem(o,top,rail);p1.stem(o,bottom,'GND')
p1.resistor('R22',1160,-1100,'34k','VDD5','DAC_AVDD_FB',rotation=0)
p1.resistor('R23',1310,-1040,'10k','DAC_AVDD_FB','GND')
cff=p1.add('OLD_C14','C27',1160,-1050)
p1.stem(cff,'1','VDD5');p1.stem(cff,'2','DAC_AVDD_FB')
# Correct pre-existing text, not its position.
for (kind,ident), (_,p) in list(p1.doc['records'].items()):
    if kind=='TEXT' and p.get('value')=='02  +5 V LOW-NOISE REGULATOR':p['value']='02  +5.214 V LOW-NOISE REGULATOR';p1.rec(kind,p,ident)
    if kind=='TEXT' and p.get('value')=='LP2985-50':p['value']='TPS7A4901 / NR soft start';p1.rec(kind,p,ident)

# Use independent power-off-protected TTL SPI buffers, leaving the existing J1 pinout.
a=io.attrs(p1.doc)
for name in ['R8','R9','R10']:
    o=p1.components[name][0]
    # Find the original VIN_RAW wire on the resistor, not every VIN_RAW net.
    points=set(o['pins'].values())
    wids={line['lineGroup'] for (kind,ident),(_,line) in p1.doc['records'].items() if kind=='LINE' and line.get('lineGroup') and a.get(line['lineGroup'],{}).get('NET')=='VIN_RAW' and ((line['startX'],line['startY']) in points or (line['endX'],line['endY']) in points)}
    for wid in wids:
        p1.set_attrs(wid,{'NET':'VDD5'})
        lines=[p for (kind,ident),(_,p) in p1.doc['records'].items() if kind=='LINE' and p.get('lineGroup')==wid]
        for (kind,ident),(_,cp) in list(p1.doc['records'].items()):
            if kind=='COMPONENT' and a.get(ident,{}).get('Global Net Name')=='VIN_RAW' and any((cp['x'],cp['y']) in [(q['startX'],q['startY']),(q['endX'],q['endY'])] for q in lines):
                p1.set_attrs(ident,{'Global Net Name':'VDD5','Name':'VDD5'})
for (kind,ident),(_,cp) in list(p1.doc['records'].items()):
    if kind=='COMPONENT' and a.get(ident,{}).get('Global Net Name')=='VIN_RAW' and any(abs(cp.get('x',0)-x)<5 and abs(cp.get('y',0)-y)<20 for x,y in [(700,-375),(860,-375),(450,-520)]):
        p1.set_attrs(ident,{'Global Net Name':'VDD5','Name':'VDD5'})

# Renaming the host side requires splitting each existing signal by endpoint.
# The exact source wire graph is edited by cutting the J1 connection and placing
# its new input labels; all DAC-side wires, termination resistors and DAC stay put.
host=p1.components['J1'][0]
hostsignals={'6':'DAC_HOST_CLR','7':'DAC_HOST_LDAC','8':'DAC_HOST_SYNC','9':'DAC_HOST_SCLK','10':'DAC_HOST_DIN'}
hostcut=[]
for num,net in hostsignals.items():
    px,py=host['pins'][num]
    for (kind,ident), (_,line) in list(p1.doc['records'].items()):
        if kind!='LINE' or not line.get('lineGroup'):continue
        endpoints=[(line['startX'],line['startY']),(line['endX'],line['endY'])]
        if (px,py) not in endpoints:continue
        h=copy.deepcopy(line)
        end=0 if endpoints[0]==(px,py) else 1
        other=endpoints[1-end]
        dx=other[0]-px;dy=other[1]-py
        if abs(dx)+abs(dy)<10:raise ValueError('Host cut has no clearance')
        if end==0:h['startX']=px+(10 if dx>0 else -10 if dx<0 else 0);h['startY']=py+(10 if dy>0 else -10 if dy<0 else 0)
        else:h['endX']=px+(10 if dx>0 else -10 if dx<0 else 0);h['endY']=py+(10 if dy>0 else -10 if dy<0 else 0)
        p1.rec('LINE',h,ident)
        hostcut.append({'pin':num,'wire':line['lineGroup'],'point':(px,py),'net':net})
    # Short stubs go outward in the opposite direction to the retained wire.
    direction=-1 if px<host['item']['x'] else 1
    p1.wire(net,[(px,py),(px+direction*5,py)],True)

# Power/control additions live below the retained original circuit; no grid rebuild.
p1.text(80,50,'06  POWER-GOOD / DEFAULT-MUTED OUTPUT / SPI ISOLATION',17)
bufmaps=[{1:'DAC_SPI_OE_N',2:'DAC_HOST_SCLK',3:'SCLK',4:'DAC_SPI_OE_N',5:'DAC_HOST_DIN',6:'DIN',7:'GND',8:'SYNC_N',9:'DAC_HOST_SYNC',10:'DAC_SPI_OE_N',11:'LDAC_N',12:'DAC_HOST_LDAC',13:'DAC_SPI_OE_N',14:'VDD5'},
         {1:'DAC_SPI_OE_N',2:'DAC_HOST_CLR',3:'CLR_N',4:'VDD5',5:'GND',7:'GND',9:'GND',10:'VDD5',12:'GND',13:'VDD5',14:'VDD5'}]
for i,m in enumerate(bufmaps,5):
    b=p1.add('BUF','U'+str(i),230+(i-5)*320,170)
    for n,net in m.items():p1.stem(b,n,net,45)
    p1.cap('C'+str(28+i-5),370+(i-5)*320,230,'VDD5')
p1.resistor('R24',690,100,'47k','VDD5','DAC_SPI_OE_N')
spi=p1.add('NFET','Q2',740,190)
for n,net in {1:'DAC_SPI_ENABLE',2:'GND',3:'DAC_SPI_OE_N'}.items():p1.stem(spi,n,net)
p1.resistor('R25',640,250,'47k','DAC_SPI_ENABLE','GND')

# Supervisors compare +12 V, DAC AVDD and -12 V magnitude; negative domain is optical.
def monitor(pg, name, x, y, rail, ground, uv, ov, good, rn, cn, supply=None):
    m=pg.add('MON',name,x,y)
    n={1:good,2:ground,3:name+'_UV',4:name+'_OV',5:supply or rail,6:good}
    for num,net in n.items():pg.stem(m,num,net,35)
    dividers=[]
    for dx,v,hi,lo in [(-130,uv,rail,name+'_UV'),(-130,'10k',name+'_UV',ground),(130,ov,rail,name+'_OV'),(130,'10k',name+'_OV',ground)]:
        lower=lo==ground
        dividers.append(pg.resistor('R'+str(rn),x+dx,y+(70 if lower else -60),v,hi,lo));rn+=1
    for first,second,net in [(dividers[0],dividers[1],name+'_UV'),(dividers[2],dividers[3],name+'_OV')]:
        p=max(first['pins'].values(),key=lambda p:p[1]);q=min(second['pins'].values(),key=lambda p:p[1])
        pg.wire(net,[p,q])
    pg.cap('C'+str(cn),x+200,y-70,supply or rail,ground)

monitor(p1,'U7',260,430,'VPOS12','GND','274k','312k','DAC_POS_GOOD',26,30,supply='VIN_RAW')
monitor(p1,'U8',780,430,'VDD5','GND','116k','127k','DAC_POS_GOOD',30,31,supply='VIN_RAW')
monitor(p1,'U9',1300,430,'GND','VNEG12','260k','320k','DAC_NEG_LOCAL',34,32,supply='GND')
p1.resistor('R38',1110,580,'47k','GND','DAC_NEG_LOCAL')
neg=p1.add('NFET','Q3',1210,600)
for n,net in {1:'DAC_NEG_LOCAL',2:'VNEG12',3:'DAC_NEG_LED_K'}.items():p1.stem(neg,n,net)
p1.resistor('R39',1110,660,'1.8k','GND','DAC_NEG_LED_A',rotation=0)
opto=p1.add('OPTO','U10',1360,650)
for n,net in {1:'DAC_NEG_LED_A',2:'DAC_NEG_LED_K',3:'GND',4:'DAC_NEG_VALID_N'}.items():p1.stem(opto,n,net)
p1.resistor('R40',1480,590,'47k','MCU_3V3','DAC_NEG_VALID_N')
p1.resistor('R41',700,620,'47k','MCU_3V3','DAC_POS_GOOD')
inv=p1.add('INV','U11',230,700)
for n,net in {2:'DAC_NEG_VALID_N',3:'GND',4:'DAC_NEG_GOOD',5:'MCU_3V3'}.items():p1.stem(inv,n,net)
for name,x,m in [('U12',450,{1:'DAC_POS_GOOD',2:'DAC_NEG_GOOD',3:'GND',4:'DAC_HW_PGOOD',5:'MCU_3V3'}),
                  ('U13',770,{1:'DAC_HW_PGOOD',2:'DAC_OUTPUT_ENABLE',3:'GND',4:'DAC_RELAY_ENABLE',5:'MCU_3V3'})]:
    o=p1.add('AND',name,x,790)
    for n,net in m.items():p1.stem(o,n,net)
for name,x in [('C33',350),('C34',650),('C35',950)]:p1.cap(name,x,710,'MCU_3V3')
relay=p1.add('RELAY','K1',1160,900)
for n,net in {1:'VIN_RAW',8:'DAC_OUT_COIL_N',2:'GND',3:'DAC_SMA_A',4:'OUT_A',5:'OUT_B',6:'DAC_SMA_B',7:'GND'}.items():p1.stem(relay,n,net,60)
driver=p1.add('DRIVER','Q4',900,980)
for n,net in {1:'DAC_RELAY_ENABLE',2:'GND',3:'DAC_OUT_COIL_N'}.items():p1.stem(driver,n,net)
p1.resistor('R42',780,960,'47k','DAC_RELAY_ENABLE','GND')
p1.resistor('R43',780,1060,'47k','DAC_OUTPUT_ENABLE','GND')
diode=p1.add('DIO','D3',1040,1000,270)
for n,net in {1:'VIN_RAW',2:'DAC_OUT_COIL_N'}.items():p1.stem(diode,n,net)
header=p1.add('HEADER','J4',260,1000)
for n,net in {1:'MCU_3V3',2:'GND',3:'DAC_SPI_ENABLE',4:'DAC_OUTPUT_ENABLE',5:'DAC_HW_PGOOD',6:'GND',7:'GND',8:'GND',9:'GND',10:'GND'}.items():p1.stem(header,n,net,35)
# Original SMA feedback must remain on OUT_A/B before the mute relay.
for name,net in [('J2','DAC_SMA_A'),('J3','DAC_SMA_B')]:
    o=p1.components[name][0]
    px,py=o['pins']['5']
    for (kind,ident), (_,line) in list(p1.doc['records'].items()):
        if kind=='LINE' and line.get('lineGroup') and (line['startX'],line['startY'])==(px,py):
            line=copy.deepcopy(line);line['startX']=px-10;p1.rec(kind,line,ident)
        elif kind=='LINE' and line.get('lineGroup') and (line['endX'],line['endY'])==(px,py):
            line=copy.deepcopy(line);line['endX']=px-10;p1.rec(kind,line,ident)
    p1.wire(net,[(px,py),(px-5,py)],True)
p1.text(80,1160,'START: mute -> PGOOD stable -> SPI on -> reset 0x280001 -> both 0x8000 -> ref 0x380001 -> gain x2 0x020000 -> settle -> output enable',8)
p1.text(80,1190,'CLR = negative full scale, NOT 0 V. All enable inputs default LOW. Shutdown: mute first, wait relay release, then power off.',8)
p1.text(80,1220,'Relay fault release is not instantaneous. Qualify rail transients / maximum output swing / AVDD overshoot before fabrication.',8)
p1.text(80,1250,'TPS7A49: OUT1 FB2 NC3 GND4 EN5 NR6 DNC7 IN8 EP9. AVDD = 1.185*(1+34k/10k) = 5.214 V nominal.',8)

# Page 2: two clearly wired left-to-right analog channels, sharing the real MCU VREF+.
p2.text(70,-1120,'DAC_MCU — STM32H747 SMA RECEIVER / BIPOLAR CONVERTER',18)
p2.text(70,-1080,'External MCU board: VDDA / VREF+ nominal 3.3 V; DAC1_OUT1 PA4 and DAC1_OUT2 PA5. No MCU is placed on this receiver.',9)
p2.text(70,-1050,'High-impedance outputs, NOT 50-ohm terminated. VOUT = (100k/14k)*(VIN - VREF+/2); 0.25..3.05 V -> -10..+10 V.',9)

for ch,y,unit,inputj,outputj,base in [('A',-850,0,'J101','J103',101),('B',-430,1,'J102','J104',111)]:
    sx=180
    inp=p2.add('OLD_J2',inputj,sx,y,mirror=True)
    out=p2.add('OLD_J2',outputj,1480,y+10)
    for o,signal in [(inp,'MCU_IN_'+ch),(out,'MCU_OUT_'+ch)]:
        for num in ['1','2','3','4']:p2.stem(o,num,'GND',15)
    # Input protection limits current; high-Z bias does not load the MCU DAC with a 50-ohm termination.
    r=p2.add('OLD_R11','R'+str(base),290,y-20)
    p,q=sorted(r['pins'],key=lambda n:r['pins'][n][0])
    p2.wire('MCU_IN_'+ch,[inp['pins']['5'],(230,inp['pins']['5'][1]),(230,y-20),r['pins'][p]])
    buffer=p2.add('OLD_U4','U101',490,y-30,part=unit)
    plus,minus,output=('3','2','1') if unit==0 else ('5','6','7')
    p2.wire('MCU_RECEIVE_'+ch,[r['pins'][q],(400,y-20),buffer['pins'][plus]])
    p2.resistor('R'+str(base+1),370,y+80,'10M','MCU_RECEIVE_'+ch,'MCU_VBIAS')
    p2.wire('MCU_BUFFER_'+ch,[buffer['pins'][output],(570,y-30),(570,y-120),(425,y-120),(425,y-40),buffer['pins'][minus]])
    if unit==0:
        p2.stem(buffer,'8','VPOS12');p2.stem(buffer,'4','VNEG12')
    # The matched-ratio difference stage keeps DC feedback before the output relay.
    gain=p2.add('OLD_U4','U103',1030,y-30,part=unit)
    rg=p2.add('R14K','R'+str(base+2),790,y-20,overrides={'Name':'14k','Value':'14k'})
    rb=p2.add('R14K','R'+str(base+3),790,y-110,overrides={'Name':'14k','Value':'14k'})
    rf=p2.add('R100K','R'+str(base+4),1070,y-160,overrides={'Name':'100k','Value':'100k'})
    rground=p2.add('R100K','R'+str(base+5),930,y+60,270,overrides={'Name':'100k','Value':'100k'})
    for obj,val,code in [(rg,'14k','1402'),(rb,'14k','1402'),(rf,'100k','1003'),(rground,'100k','1003')]:
        changes={'Manufacturer':'Susumu','Manufacturer Part':'RG1608N-'+code+'-W-T5','Tolerance':'±0.05%',
            'Temperature Coefficient':'±10ppm/C','Supplier':'Manual procurement','Supplier Part':'','LCSC Part Name':'',
            'JLCPCB Part Class':'','Datasheet':'https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf'}
        p2.set_attrs(obj['id'],changes);obj['props'].update(changes)
    l,rn=sorted(rg['pins'],key=lambda n:rg['pins'][n][0])
    p2.wire('MCU_BUFFER_'+ch,[rg['pins'][l],(620,y-20),(620,y-30),buffer['pins'][output]])
    p2.wire('MCU_PLUS_'+ch,[rg['pins'][rn],(930,y-20),gain['pins'][plus]])
    top,bottom=sorted(rground['pins'],key=lambda n:rground['pins'][n][1])
    p2.wire('MCU_PLUS_'+ch,[(930,y-20),rground['pins'][top]])
    p2.stem(rground,bottom,'GND')
    l,rn=sorted(rb['pins'],key=lambda n:rb['pins'][n][0])
    p2.stem(rb,l,'MCU_VBIAS',35)
    p2.wire('MCU_MINUS_'+ch,[rb['pins'][rn],(945,y-110),(945,y-40),gain['pins'][minus]])
    l,rn=sorted(rf['pins'],key=lambda n:rf['pins'][n][0])
    p2.wire('MCU_MINUS_'+ch,[rf['pins'][l],(945,y-160),(945,y-110)])
    p2.wire('MCU_SENSE_'+ch,[rf['pins'][rn],(1280,y-160),(1280,y-30)])
    comp=p2.add('OLD_C25','C'+str(base),1070,y-100)
    l,rn=sorted(comp['pins'],key=lambda n:comp['pins'][n][0])
    p2.wire('MCU_MINUS_'+ch,[comp['pins'][l],(945,y-100),(945,y-160)])
    p2.wire('MCU_RAW_'+ch,[comp['pins'][rn],(1150,y-100),(1150,y-30),gain['pins'][output]])
    iso=p2.add('OLD_R16','R'+str(base+6),1210,y-30)
    l,rn=sorted(iso['pins'],key=lambda n:iso['pins'][n][0])
    p2.wire('MCU_RAW_'+ch,[gain['pins'][output],iso['pins'][l]])
    p2.wire('MCU_SENSE_'+ch,[iso['pins'][rn],(1280,y-30),(1290,y-30)],True)
    cout=p2.add('OLD_C22','C'+str(base+1),1310,y+50,270)
    top,bottom=sorted(cout['pins'],key=lambda n:cout['pins'][n][1])
    p2.wire('MCU_OUT_'+ch,[out['pins']['5'],(1380,out['pins']['5'][1]),(1380,y-30),(1310,y-30),cout['pins'][top]])
    p2.stem(cout,bottom,'GND')
    if unit==0:
        p2.stem(gain,'8','VPOS12');p2.stem(gain,'4','VNEG12')
    p2.text(170,y+155,'CHANNEL '+ch+' — INPUT DEFAULTS TO VBIAS; OUTPUT DEFAULTS TO GND',10)

# Reference tracking and input/output selection are separate from the amplifier feedback.
ref=p2.add('HEADER','J105',180,-110)
for n,net in {1:'MCU_3V3',2:'GND',3:'MCU_VREF_PLUS',4:'MCU_INPUT_ENABLE',5:'MCU_OUTPUT_ENABLE',6:'DAC_HW_PGOOD',7:'GND',8:'GND',9:'GND',10:'GND'}.items():p2.stem(ref,n,net,40)
p2.resistor('R121',380,-170,'10k','MCU_VREF_PLUS','MCU_VHALF',precision=True)
p2.resistor('R122',380,-40,'10k','MCU_VHALF','GND',precision=True)
bias=p2.add('OLD_U4','U102',600,-130,part=0)
for n,net in {3:'MCU_VHALF',8:'VPOS12',4:'VNEG12'}.items():p2.stem(bias,n,net)
p2.wire('MCU_VBIAS',[bias['pins']['1'],(690,-130),(690,-220),(550,-220),(550,-140),bias['pins']['2']],True)
spare=p2.add('OLD_U4','U102',870,-130,part=1)
p2.stem(spare,'5','GND')
p2.wire('MCU_SPARE',[spare['pins']['7'],(950,-130),(950,-220),(820,-220),(820,-140),spare['pins']['6']])
for n,x,rail in [('C121',1050,'VPOS12'),('C122',1140,'VNEG12'),('C123',1230,'VPOS12'),('C124',1320,'VNEG12'),('C125',1410,'VPOS12'),('C126',1500,'VNEG12')]:p2.cap(n,x,-120,rail)

# Input/output DPDT relay blocks: NO external signal, NC bias/ground, COM downstream.
for key,name,x,y,m in [
    ('RELAY','K101',400,130,{1:'VIN_RAW',8:'MCU_IN_COIL_N',2:'MCU_VBIAS',3:'MCU_RECEIVE_A',4:'MCU_RCV_EXTERNAL_A',5:'MCU_RCV_EXTERNAL_B',6:'MCU_RECEIVE_B',7:'MCU_VBIAS'}),
    ('RELAY','K102',1040,130,{1:'VIN_RAW',8:'MCU_OUT_COIL_N',2:'GND',3:'MCU_OUT_A',4:'MCU_SENSE_A',5:'MCU_SENSE_B',6:'MCU_OUT_B',7:'GND'})]:
    o=p2.add(key,name,x,y)
    for n,net in m.items():p2.stem(o,n,net,60)
# Relays are inserted by renaming the series-resistor downstream wires, leaving the buffer-side nets.
for ch,base in [('A',101),('B',111)]:
    series=p2.components['R'+str(base)][0]
    endpoint=max(series['pins'].values())
    for (kind,ident), (_,line) in list(p2.doc['records'].items()):
        if kind=='LINE' and (line.get('startX'),line.get('startY'))==endpoint:
            line=copy.deepcopy(line);line['startX']+=10;p2.rec(kind,line,ident)
    p2.wire('MCU_RCV_EXTERNAL_'+ch,[endpoint,(endpoint[0]+5,endpoint[1])],True)

for name,x,m in [('U104',260,{1:'DAC_HW_PGOOD',2:'MCU_INPUT_ENABLE',3:'GND',4:'MCU_INPUT_SAFE',5:'MCU_3V3'}),
                 ('U105',900,{1:'DAC_HW_PGOOD',2:'MCU_OUTPUT_ENABLE',3:'GND',4:'MCU_OUTPUT_SAFE',5:'MCU_3V3'})]:
    o=p2.add('AND',name,x,350)
    for n,net in m.items():p2.stem(o,n,net)
for ch,x,qname,dname,rname,enable in [('IN',500,'Q101','D101','R123','MCU_INPUT_SAFE'),('OUT',1140,'Q102','D102','R125','MCU_OUTPUT_SAFE')]:
    o=p2.add('DRIVER',qname,x,430)
    for n,net in {1:enable,2:'GND',3:'MCU_'+ch+'_COIL_N'}.items():p2.stem(o,n,net)
    d=p2.add('DIO',dname,x+120,360,270)
    for n,net in {1:'VIN_RAW',2:'MCU_'+ch+'_COIL_N'}.items():p2.stem(d,n,net)
    p2.resistor(rname,x-110,430,'47k',enable,'GND')
p2.resistor('R124',260,520,'47k','MCU_INPUT_ENABLE','GND')
p2.resistor('R126',900,520,'47k','MCU_OUTPUT_ENABLE','GND')
p2.cap('C127',700,400,'MCU_3V3');p2.cap('C128',1350,400,'MCU_3V3')
p2.text(70,600,'MCU sequence: calibrate DAC buffers -> write midscale -> enable input relay -> wait signal/relay settling -> enable output relay.',9)
p2.text(70,630,'Receiver buffer does NOT remove coax capacitance from MCU pin. Keep source CL <=50 pF or use a source-side cable-driver buffer.',9)
p2.text(70,660,'12-bit MCU DAC: ~5.75 mV/output LSB; INL up to 4 LSB ~23 mV. Two-point calibration cannot remove INL.',9)
p2.text(70,690,'Do not substitute a local 3.3 V source for the MCU VREF+ tracking input. Both enable controls must default low.',9)

for pg,bottom,height in [(p1,1320,2490),(p2,780,1960)]:
    pa=io.attrs(pg.doc)
    for (kind,ident),(_,cp) in list(pg.doc['records'].items()):
        if kind=='COMPONENT' and 'Title Block' in pa.get(ident,{}):
            cp=copy.deepcopy(cp);cp['y']=bottom;pg.rec('COMPONENT',cp,ident)
            pg.set_attrs(ident,{'Width':'1654','Height':str(height),'Page Size':'Custom','@Page Count':'2',
                               '@Page Name':'DAC8562' if pg is p1 else 'DAC_MCU','@Page No':'1' if pg is p1 else '2',
                               'Version':'V1.3','@Update Date':'2026-10-12'})
# Old unattached power-label stems outside the original drawing area are removed.
for (kind,ident),(_,line) in list(p1.doc['records'].items()):
    if kind=='ATTR' and line.get('key')=='NET' and line.get('x') in [1450,1530] and line.get('y') in [560,890]:
        wid=line['parentId']
        for (lk,lid),(_,lp) in list(p1.doc['records'].items()):
            if lk=='LINE' and lp.get('lineGroup')==wid:p1.delete(lid)
        p1.delete(wid)
for name,rail in [('C18','VPOS12'),('C19','VNEG12'),('C20','VPOS12'),('C21','VNEG12')]:
    o=p1.components[name][0];top=min(o['pins'],key=lambda n:o['pins'][n][1]);p1.stem(o,top,rail,15)

p1.save('DAC8562.corrected-source.txt')
p2.save('DAC_MCU.corrected-source.txt')
report={'backupPcbHash':io.data_hash(before['4e08f91f9a2c4fe4']), 'backupPanelHash':io.data_hash(before['458da9240aa63aad']),
        'originalComponentCoordinatesPreservedExcept':['Q1: -10 source-y to align the replacement symbol pins'],
        'expectedPinNets':{},'pages':{},'noConnect':{p1.doc['head']['uuid']:{'U1':['12','20'],'U2':['3','7'],'U6':['6','8','11'],'U11':['1']}}}
for pg in [p1,p2]:
    report['pages'][pg.doc['head']['uuid']]={'components':sum(len(a) for a in pg.components.values()),'hash':io.data_hash(pg.doc)}
with (OUT/'correction-plan.json').open('w',encoding='utf8') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))

native_plan=[]
for pg,base_file in [(p1,'native-page1-source.json'),(p2,'native-seed-source.json')]:
    base=next(iter(io.documents(json.loads((OUT/base_file).read_text(encoding='utf8'))['source']).values()))
    ba,da=io.attrs(base),io.attrs(pg.doc)
    step={'page':pg.doc['head']['uuid'],'deleteComponents':[],'components':[],'attributes':[],
          'deleteWires':[],'wires':[],'deleteTexts':[],'texts':[]}
    for (kind,ident),(_,bp) in base['records'].items():
        if kind=='COMPONENT' and ((kind,ident) not in pg.doc['records'] or (ba.get(ident,{}).get('Designator') or '').startswith('SEED_')):
            step['deleteComponents'].append(ident)
        if kind=='COMPONENT' and ba.get(ident,{}).get('Global Net Name') and da.get(ident,{}).get('Global Net Name')!=ba[ident]['Global Net Name']:
            if ident not in step['deleteComponents']:step['deleteComponents'].append(ident)
    for (kind,ident),(_,dp) in pg.doc['records'].items():
        if kind!='COMPONENT':continue
        props=da.get(ident,{})
        if props.get('Designator'):
            old_props=ba.get(ident,{})
            changed=(kind,ident) not in base['records'] or old_props.get('Device')!=props.get('Device') or old_props.get('Symbol')!=props.get('Symbol')
            if changed:
                if (kind,ident) in base['records'] and ident not in step['deleteComponents']:step['deleteComponents'].append(ident)
                # For the 4.7-nF replacement retain the old 0603 capacitor geometry.
                device=props['Device'] if props.get('Designator')!='C4' else templates['OLD_C4'][1]['Device']
                src=loaded[device]['records'][('META','META')][1]['source']
                device_uuid,library_uuid=src.split('|')
                style={p['key']:p for (t,i),(_,p) in pg.doc['records'].items() if t=='ATTR' and p.get('parentId')==ident and p.get('key') in ['Name','Designator']}
                step['components'].append({'id':ident,'device':{'uuid':device_uuid,'libraryUuid':library_uuid},'item':dp,'props':props,'style':style})
            else:
                for (t,aid),(_,ap) in pg.doc['records'].items():
                    if t=='ATTR' and ap.get('parentId')==ident and ap.get('value')!=old_props.get(ap['key']):step['attributes'].append({'id':aid,'value':ap['value']})
        elif ident not in step['deleteComponents']:
            for (t,aid),(_,ap) in pg.doc['records'].items():
                if t=='ATTR' and ap.get('parentId')==ident and ap.get('value')!=ba.get(ident,{}).get(ap['key']):step['attributes'].append({'id':aid,'value':ap['value']})
            if (kind,ident) in base['records'] and dp.get('y')!=base['records'][(kind,ident)][1].get('y'):
                step.setdefault('moveComponents',[]).append({'id':ident,'x':dp['x'],'y':dp['y']})
    def wires(doc,props):
        result={}
        for (t,i),(_,p) in doc['records'].items():
            if t=='WIRE':result[i]={'net':props.get(i,{}).get('NET',''),'segments':[],'label':props.get(i,{}).get('NET','')}
        for (t,i),(_,p) in doc['records'].items():
            if t=='LINE' and p.get('lineGroup') in result:
                result[p['lineGroup']]['segments'].append([p['startX'],p['startY'],p['endX'],p['endY']])
        return result
    bw,dw=wires(base,ba),wires(pg.doc,da)
    for wid,w in bw.items():
        if dw.get(wid)!=w:step['deleteWires'].append(wid)
    for wid,w in dw.items():
        if bw.get(wid)!=w and w['segments']:step['wires'].append({'id':wid,**w})
    for (kind,ident),(_,p) in pg.doc['records'].items():
        if kind=='TEXT' and base['records'].get((kind,ident),({},{}))[1].get('value')!=p.get('value'):
            if (kind,ident) in base['records']:step['deleteTexts'].append(ident)
            step['texts'].append(p)
    native_plan.append(step)
(OUT/'native-operations.json').write_text(json.dumps(native_plan,ensure_ascii=False,indent=2),encoding='utf8')
