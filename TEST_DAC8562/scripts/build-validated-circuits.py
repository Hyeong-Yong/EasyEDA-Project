"""Build separate, fully specified schematic projects; preserve original PCB.

Native exports are imported into isolated copies and checked in EasyEDA itself.
This generator does not imply physical startup or PCB-layout validation.
"""
from pathlib import Path
from collections import defaultdict
import copy, csv, html, json, math, sys, uuid, zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/validated-revision'
LIB = OUT/'library'
OUT.mkdir(exist_ok=True, parents=True)
def uid(): return uuid.uuid4().hex[:16]
def parse(source):
    docs = {}
    current = None
    for line in source.splitlines():
        if '||' not in line: continue
        a,b = line.split('||',1)
        h = json.loads(a)
        try: p = json.loads(b.rstrip('|'))
        except json.JSONDecodeError: p = None
        if h['type']=='DOCHEAD':
            current=docs.setdefault(p['uuid'],{'head':p,'records':{}})
            continue
        if not current: continue
        key=(h['type'],h.get('id',''))
        prior=current['records'].get(key)
        if prior is None or h.get('ticket',0)>=prior[0].get('ticket',0): current['records'][key]=(h,p)
    return {k:[({'type':'DOCHEAD'},d['head'])]+[v for v in d['records'].values() if isinstance(v[1],dict)] for k,d in docs.items()}
def loadzip(path, suffix):
    with zipfile.ZipFile(path) as z:
        return parse(z.read(next(n for n in z.namelist() if n.endswith(suffix))).decode('utf8'))
original=loadzip(ROOT/'output/highz/DAC8562_highz_revision.epro2','.epru')
libraries={k:copy.deepcopy(d) for k,d in original.items() if d[0][1]['docType'] in ['SYMBOL','DEVICE','FOOTPRINT']}
page=next(d for d in original.values() if d[0][1]['docType']=='SCH_PAGE')
props=defaultdict(dict)
for h,p in page:
    if h['type']=='ATTR': props[p.get('parentId')][p['key']]=p['value']
old={}
for h,p in page:
    if h['type']=='COMPONENT' and props[h['id']].get('Designator'):
        old.setdefault(props[h['id']]['Designator'],[]).append((p,props[h['id']]))
selected=json.loads((LIB/'selected.json').read_text(encoding='utf8'))
templates={}
for key,v in selected.items():
    ds=loadzip(LIB/(key+'.elibz2'),'.elibu')
    libraries.update(ds)
    with zipfile.ZipFile(LIB/(key+'.elibz2')) as z:
        item=json.loads(z.read('device2.json'))['devices'][v['uuid']]
    attrs=copy.deepcopy(item['attributes'])
    device=[({'type':'DOCHEAD'},{'docType':'DEVICE','uuid':v['uuid'],'client':'revision-20261012','editVersion':'3.2.149.88089769'}),
            ({'type':'META','ticket':1,'id':'META'},{'title':item['display_title'],'description':item.get('description',''),'source':'','attributes':attrs})]
    libraries[v['uuid']]=device
    templates[key]=copy.deepcopy(attrs)
    templates[key]['Device']=device[0][1]['uuid']
    for field,token in [('Name','Value'),('Name','Manufacturer Part')]:
        if templates[key].get(field)=='={'+token+'}': templates[key][field]=templates[key].get(token,'')
for key, units in old.items():
    instance=copy.deepcopy(units[0][1])
    device=libraries[instance['Device']]
    inherited=copy.deepcopy(next(p for h,p in device if h['type']=='META')['attributes'])
    inherited.update({k:v for k,v in instance.items() if k not in ['Footprint','Symbol'] or v})
    templates['OLD_'+key]=inherited

def derived(key, value, mpn, manufacturer, tolerance, tcr, datasheet, supplier='Manual procurement'):
    attrs=copy.deepcopy(templates[key]); did=uid()
    device=copy.deepcopy(libraries[attrs['Device']]);device[0][1]['uuid']=did
    meta=next(p for h,p in device if h['type']=='META')
    meta['title']=mpn;meta['source']=''
    attrs.update({'Device':did,'Name':value,'Value':value,'Manufacturer':manufacturer,'Manufacturer Part':mpn,
                  'Tolerance':tolerance,'Temperature Coefficient':tcr,'Datasheet':datasheet,
                  'Supplier':supplier,'Supplier Part':'','LCSC Part Name':'','JLCPCB Part Class':''})
    meta['attributes']=copy.deepcopy(attrs)
    libraries[did]=device
    templates[mpn]=attrs
    return mpn
RG_DS='https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf'
rg={}
for value,code in [('24.3k','2432'),('14k','1402'),('100k','1003'),('10k','1002')]:
    rg[value]=derived('R100K',value,'RG1608N-'+code+'-W-T5','Susumu','±0.05%','±10ppm/C',RG_DS)
txamp=derived('OLD_U4','OPA2320AIDR','OPA2320AIDR','Texas Instruments','','','https://www.ti.com/lit/ds/symlink/opa2320.pdf')
rt={'312k':'R312K','320k':'R320K'}
for value,code in [('274k','274K'),('260k','260K'),('116k','116K'),('127k','127K'),('68k','68K'),('77.5k','77K5'),('1.8k','1K8'),('47k','47K'),('100','100R')]:
    rt[value]=derived('R100K',value,'RT0603BRD07'+code+'L','YAGEO','±0.1%','±25ppm/C','https://www.yageo.com/upload/media/product/productsearch/datasheet/rchip/pyu-rt_51_rohs_l.pdf')

# Audit library electrical pin roles against manufacturer functions, rather than
# accepting stock symbols that mark an open-drain output as an input/passive pin.
role_maps={
    'MON':{'1':'Open Collector','2':'Ground','3':'IN','4':'IN','5':'Power','6':'Open Collector'},
    'AND':{'1':'IN','2':'IN','3':'Ground','4':'OUT','5':'Power'},
    'INV':{'1':'Passive','2':'IN','3':'Ground','4':'OUT','5':'Power'},
    'BUF':{str(n):('Power' if n==14 else 'Ground' if n==7 else 'HIZ' if n in [3,6,8,11] else 'IN') for n in range(1,15)},
    'LDO':{'1':'Power','2':'Passive','3':'Passive','4':'IN','5':'Passive','6':'Ground','7':'IN','8':'Power','9':'Ground'},
    'OPTO':{str(n):'Passive' for n in [1,2,3,4]},
    'OLD_U4':{'1':'OUT','2':'IN','3':'IN','4':'Power','5':'IN','6':'IN','7':'OUT','8':'Power'},
    txamp:{'1':'OUT','2':'IN','3':'IN','4':'Ground','5':'IN','6':'IN','7':'OUT','8':'Power'},
}
patched_symbols={}
for key,a in templates.items():
    if key in role_maps: roles=role_maps[key]
    elif key.startswith('OLD_') and key[4:5] in ['R','C','L','D','Q','J'] or key in ['QPM','NFET','DRIVER','RELAY','HEADER','DIO','CO10','R10M','R34K','R312K','R320K','R200K','R10K','R100K','R24K3','R14K'] or key.startswith(('RG1608','RT0603')):
        roles=None
    else: continue
    old_sid=a['Symbol']; cachekey=(old_sid,json.dumps(roles,sort_keys=True))
    if cachekey not in patched_symbols:
        sym=copy.deepcopy(libraries[old_sid]); sid=uid();sym[0][1]['uuid']=sid
        next(p for h,p in sym if h['type']=='META')['title'] += '__verified_'+sid[:6]
        nums={p['parentId']:str(p['value']) for h,p in sym if h['type']=='ATTR' and p.get('key')=='Pin Number'}
        for h,q in sym:
            if h['type']=='ATTR' and q.get('key')=='Pin Type':
                num=nums.get(q.get('parentId'))
                q['value']='Passive' if roles is None else roles.get(num,'Passive')
        libraries[sid]=sym;patched_symbols[cachekey]=sid
    a['Symbol']=patched_symbols[cachekey]
    # Clone device metadata too so project-level changes cannot affect the
    # manufacturer's/system library or the preserved original project.
    dev=copy.deepcopy(libraries[a['Device']]);did=uid();dev[0][1]['uuid']=did
    devmeta=next(p for h,p in dev if h['type']=='META')
    devmeta['title']+='__verified_'+did[:6]
    devmeta['attributes']['Symbol']=a['Symbol']
    libraries[did]=dev;a['Device']=did

class Project:
    def __init__(self,name):
        self.name=name;self.board=uid();self.sch=uid();self.pages=[];self.objects=[];self.expected=defaultdict(set);self.nc=[]
    def newpage(self,title,notes):
        d=[({'type':'DOCHEAD'},{'docType':'SCH_PAGE','uuid':uid(),'client':'revision-20261012','editVersion':'3.2.149.88089769'})]
        self.pages.append(d);self.page=d;self.slot=0;self.wires=[]
        self.rec('META',{'title':title,'schematic':self.sch,'source':'','zIndex':len(self.pages)},'META')
        self.rec('CANVAS',{'originX':0,'originY':0},'CANVAS')
        self.text(80,0,title,18)
        for i,t in enumerate(notes): self.text(80,30+i*18,t,9)
    def rec(self,kind,p,id=None):
        self.page.append(({'type':kind,'ticket':len(self.page),'id':id or uid()},p))
    def text(self,x,y,value,size=7):
        self.rec('TEXT',{'x':x,'y':y,'value':value,'rotation':0,'fontFamily':'Arial','fontSize':size,'align':'LEFT_BOTTOM','zIndex':len(self.page)})
    def attr(self,parent,key,value,x=None,y=None,visible=False):
        self.rec('ATTR',{'parentId':parent,'key':key,'value':value,'x':x,'y':y,'rotation':0,'fontFamily':'Arial','fontSize':7,'align':'LEFT_BOTTOM','keyVisible':False,'valueVisible':visible,'zIndex':len(self.page)})
    def add(self,key,name,nets,part=None,x=None,y=None):
        a=copy.deepcopy(templates[key])
        symbol=libraries[a['Symbol']]
        parts=[h['id'] for h,p in symbol if h['type']=='PART']
        if part is None and len(parts)>1:
            result=[]
            for i,pid in enumerate(parts):
                pinids={h['id'] for h,q in symbol if h['type']=='PIN' and q.get('partId')==pid}
                nums={str(q['value']) for h,q in symbol if h['type']=='ATTR' and q.get('parentId') in pinids and q.get('key')=='Pin Number'}
                result.append(self.add(key,name,{str(k):v for k,v in nets.items() if str(k) in nums},part=i))
            return result
        if part is None: part=0
        pid=parts[part]
        if x is None:
            x=190+(self.slot%6)*250;y=290+(self.slot//6)*260;self.slot+=1
        cid=uid();a.update({'Designator':name,'Unique ID':self.name+'-'+name,'Multi-Part Group':self.name+'-'+name,'Add into BOM':'yes','Convert to PCB':'yes'})
        for k in ['Reuse Block','Group ID','Channel ID','Relevance']: a.pop(k,None)
        self.rec('COMPONENT',{'partId':pid,'x':x,'y':y,'rotation':0,'isMirror':False,'attrs':{},'zIndex':len(self.page)},cid)
        for k,v in a.items():
            self.attr(cid,k,v,x-20 if k in ['Designator','Name'] else None,y-115 if k=='Designator' else y+110,k in ['Designator','Name'])
        pinattrs=defaultdict(dict)
        for h,p in symbol:
            if h['type']=='ATTR': pinattrs[p.get('parentId')][p['key']]=p['value']
        obj={'id':cid,'name':name,'key':key,'props':a,'x':x,'y':y,'partId':pid,'page':len(self.pages),'pins':{},'nets':{str(k):v for k,v in nets.items()}}
        for h,p in symbol:
            if h['type']!='PIN' or p.get('partId')!=pid: continue
            num=str(pinattrs[h['id']]['Pin Number']);px=x+p['x'];py=y+p['y']
            obj['pins'][num]=[px,py]
            if num not in obj['nets']:
                self.nc.append({'component':cid,'designator':name,'pin':num,'pageUuid':self.page[0][1]['uuid']})
                continue
            net=obj['nets'][num]
            dx=px-x;dy=py-y
            if abs(dx)>=abs(dy) or dx:
                end=[px+(-25 if dx<=0 else 25),py]
            else: end=[px,py+(-25 if dy<0 else 25)]
            wid=uid();self.rec('WIRE',{'zIndex':len(self.page)},wid)
            self.rec('LINE',{'startX':px,'startY':py,'endX':end[0],'endY':end[1],'lineGroup':wid,'strokeColor':None,'strokeStyle':None,'strokeWidth':None,'fillColor':None,'fillStyle':None})
            self.attr(wid,'NET',net,end[0],end[1]-2,False)
            self.text(end[0],end[1]-3,net,6)
            self.wires.append((net,[px,py],end))
            self.expected[net].add(name+'.'+num)
        self.objects.append(obj)
        return obj
    def pair(self,key,name,top,bottom): return self.add(key,name,{1:top,2:bottom})
    def finish(self):
        def meta(kind,id,p):return [({'type':'DOCHEAD'},{'docType':kind,'uuid':id,'client':'revision-20261012','editVersion':'3.2.149.88089769'}),({'type':'META','id':'META','ticket':1},p)]
        used=set()
        for obj in self.objects:used.update(obj['props'].get(k,'') for k in ['Device','Symbol','Footprint'])
        ld=[copy.deepcopy(libraries[k]) for k in used if k in libraries]
        # Device symbols/footprints and drawing-sheet libraries are all self-contained.
        docs=ld+[meta('BOARD',self.board,{'title':self.name,'zIndex':1}),meta('SCH',self.sch,{'title':self.name,'board':self.board,'source':'','zIndex':1})]+self.pages
        config=next(d for d in original.values() if d[0][1]['docType']=='CONFIG')
        docs.append(copy.deepcopy(config))
        source='\n'.join(json.dumps(h,ensure_ascii=False,separators=(',',':'))+'||'+json.dumps(p,ensure_ascii=False,separators=(',',':'))+'|' for d in docs for h,p in d)+'\n'
        folder=OUT/self.name;folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(folder/(self.name+'.epro2'),'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('project2.json',json.dumps({'title':self.name,'cbb_project':0,'editorVersion':'3.2.149.88089769','description':'Schematic revision; PCB routing and physical qualification required.'}))
            z.writestr(self.name+'.epru',source)
        (folder/'expected-connectivity.json').write_text(json.dumps({'name':self.name,'schematicUuid':self.sch,'pages':[d[0][1]['uuid'] for d in self.pages],'nets':{k:sorted(v) for k,v in self.expected.items()},'noConnectPins':self.nc,'components':self.objects},ensure_ascii=False,indent=2),encoding='utf8')
        with (folder/'BOM.tsv').open('w',encoding='utf8',newline='') as f:
            w=csv.writer(f,delimiter='\t');w.writerow(['Designator','Value','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Footprint','Tolerance','TCR','Datasheet']);seen=set()
            for o in self.objects:
                if o['name'] in seen:continue
                seen.add(o['name']);p=o['props']
                w.writerow([o['name']]+[p.get(k,'') for k in ['Value','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Footprint','Tolerance','Temperature Coefficient','Datasheet']])
        return {'name':self.name,'file':str(folder/(self.name+'.epro2')),'board':self.board,'sch':self.sch,'pages':[d[0][1]['uuid'] for d in self.pages],'physicalParts':len({o['name'] for o in self.objects}), 'pins':sum(len(v) for v in self.expected.values())}

def add_safety(p, prefix, reference, lower_uv, upper_ov):
    p.newpage('Power-good supervision / relay drivers',[
        'Negative monitor is floated on VNEG12; optocoupler crosses to MCU 3V3. No negative voltage is applied to logic inputs.',
        'Positive rail window: 11.36..12.88V; negative magnitude window: 10.8..13.2V (nominal thresholds).',
        'Relay disconnect is not an instantaneous brownout clamp. Normal shutdown: OUT_ENABLE=0, wait >=10ms + measured release margin.',
        'All enable inputs default LOW. MCU 3V3 supply is separate from VREF+.'])
    monpos=prefix+'U1'; monref=prefix+'U2'; monneg=prefix+'U3'
    p.add('MON',monpos,{1:'POS_REF_GOOD',2:'GND',3:'POS_UV',4:'POS_OV',5:'VIN_RAW',6:'POS_REF_GOOD'})
    for name,val,a,b in [('R1','274k','VPOS12','POS_UV'),('R2','10k','POS_UV','GND'),('R3','312k','VPOS12','POS_OV'),('R4','10k','POS_OV','GND')]:p.pair(rt.get(val, 'R10K'),prefix+name,a,b)
    p.add('MON',monref,{1:'POS_REF_GOOD',2:'GND',3:'REF_UV',4:'REF_OV',5:'VIN_RAW',6:'POS_REF_GOOD'})
    for name,val,a,b in [('R5',lower_uv,reference,'REF_UV'),('R6','10k','REF_UV','GND'),('R7',upper_ov,reference,'REF_OV'),('R8','10k','REF_OV','GND')]:p.pair(rt.get(val,'R10K'),prefix+name,a,b)
    p.add('MON',monneg,{1:'NEG_LOCAL_GOOD',2:'VNEG12',3:'NEG_UV',4:'NEG_OV',5:'GND',6:'NEG_LOCAL_GOOD'})
    for name,val,a,b in [('R9','260k','GND','NEG_UV'),('R10','10k','NEG_UV','VNEG12'),('R11','320k','GND','NEG_OV'),('R12','10k','NEG_OV','VNEG12')]:p.pair(rt.get(val,'R10K'),prefix+name,a,b)
    p.pair(rt['47k'],prefix+'R13','GND','NEG_LOCAL_GOOD')
    p.add('NFET',prefix+'Q1',{1:'NEG_LOCAL_GOOD',2:'VNEG12',3:'NEG_LED_K'})
    p.pair(rt['1.8k'],prefix+'R14','GND','NEG_LED_A')
    p.add('OPTO',prefix+'U4',{1:'NEG_LED_A',2:'NEG_LED_K',3:'GND',4:'NEG_VALID_N'})
    p.pair(rt['47k'],prefix+'R15','MCU_3V3','NEG_VALID_N')
    p.pair(rt['47k'],prefix+'R16','MCU_3V3','POS_REF_GOOD')
    p.add('INV',prefix+'U5',{2:'NEG_VALID_N',3:'GND',4:'NEG_GOOD',5:'MCU_3V3'})
    p.add('AND',prefix+'U6',{1:'POS_REF_GOOD',2:'NEG_GOOD',3:'GND',4:'HW_PGOOD',5:'MCU_3V3'})
    p.add('AND',prefix+'U7',{1:'HW_PGOOD',2:'MCU_OUTPUT_ENABLE',3:'GND',4:'RELAY_ENABLE',5:'MCU_3V3'})
    p.add('DRIVER',prefix+'Q2',{1:'RELAY_ENABLE',2:'GND',3:'OUT_COIL_N'})
    p.pair(rt['47k'],prefix+'R17','RELAY_ENABLE','GND')
    p.pair(rt['47k'],prefix+'R18','MCU_OUTPUT_ENABLE','GND')
    p.add('DIO',prefix+'D1',{1:'VIN_RAW',2:'OUT_COIL_N'})
    for i,(rail,gnd) in enumerate([('VIN_RAW','GND'),('VIN_RAW','GND'),('GND','VNEG12'),('MCU_3V3','GND'),('MCU_3V3','GND'),('MCU_3V3','GND')],1):p.pair('OLD_C18',prefix+'C'+str(i),rail,gnd)
    # An explicit load keeps the DAC LDO discharge time bounded, but hardware mute
    # remains asserted on loss of power-good; firmware full-reset is still required.
    p.add('AND',prefix+'U8',{1:'HW_PGOOD',2:'MCU_INPUT_ENABLE',3:'GND',4:'INPUT_ENABLE_SAFE',5:'MCU_3V3'})
    p.pair(rt['47k'],prefix+'R19','MCU_INPUT_ENABLE','GND')
    p.pair('OLD_C18',prefix+'C7','MCU_3V3','GND')

main=Project('DAC8562_power_accuracy_revision')
mapping={pin:net for net,pins in json.loads((ROOT/'simulation/highz/current-schematic.json').read_text(encoding='utf8'))['actual'].items() for pin in pins}
main.newpage('TPS65131 / TPS7A49 / DAC8562T revised circuit',[
    'Original project and routed PCB preserved separately. This project contains revised schematics only; NOT a routed PCB.',
    'C4 CN=4.7nF; C5 CP=10nF. U2 TPS7A4901DGNR: 34k/10k -> AVDD nominal 5.2536V.',
    'J1 host pinout retained; J4 adds 3V3, SPI_ENABLE, OUTPUT_ENABLE and HW_PGOOD. All five DAC digital signals buffered.',
    'Precision gain: 100k/24.3k. Preload both DACs to 0x8000 BEFORE reference enable; CLR is negative full-scale, NOT zero volts.'])
for name,units in sorted(old.items(),key=lambda kv:(kv[0][0],int(''.join(filter(str.isdigit,kv[0])) or 0))):
    if not any(pin.startswith(name+'.') for pin in mapping):continue
    nets={k.split('.')[1]:v for k,v in mapping.items() if k.startswith(name+'.')}
    key='OLD_'+name
    if name=='Q1':key='QPM'
    elif name=='U2':
        key='LDO';nets={'1':'VDD5','4':'AVDD_FB','5':'LDO_BYP','6':'GND','7':'VPOS12','8':'VPOS12','9':'GND'}
    elif name=='C4':key='OLD_C5'
    elif name=='C5':key='OLD_C4'
    elif name in ['C13','C15']:key='CO10'
    elif name in ['R12','R14','R17','R19']:key=rg['24.3k']
    elif name in ['R13','R15','R18','R20']:key=rg['100k']
    elif name=='J1':key='HEADER';nets.update({'6':'CLR_EXT','7':'LDAC_EXT','8':'SYNC_EXT'})
    if name in ['R8','R9','R10']:nets['1']='VDD5'
    if name=='R6':nets['1']='SCLK_BUFFERED'
    if name=='R7':nets['1']='DIN_BUFFERED'
    if name=='J2':nets['5']='SMA_OUT_A'
    if name=='J3':nets['5']='SMA_OUT_B'
    for part,(base,pr) in enumerate(units):
        if name=='U4':
            sym=libraries[pr['Symbol']]
            pinids={h['id'] for h,q in sym if h['type']=='PIN' and q.get('partId')==base['partId']}
            nums={str(q['value']) for h,q in sym if h['type']=='ATTR' and q.get('parentId') in pinids and q.get('key')=='Pin Number'}
            main.add(key,name,{k:v for k,v in nets.items() if k in nums},part=part)
        else: main.add(key,name,nets)
main.pair('R34K','R22','VDD5','AVDD_FB');main.pair('R10K','R23','AVDD_FB','GND')
main.pair('OLD_C14','C27','VDD5','AVDD_FB');main.pair('R10K','R24','VDD5','GND')
main.add('RELAY','K1',{1:'VIN_RAW',8:'OUT_COIL_N',2:'GND',3:'SMA_OUT_A',4:'OUT_A',7:'GND',6:'SMA_OUT_B',5:'OUT_B'})
main.add('HEADER','J4',{1:'MCU_3V3',2:'GND',3:'MCU_INPUT_ENABLE',4:'MCU_OUTPUT_ENABLE',5:'HW_PGOOD',6:'GND',7:'GND',8:'GND',9:'GND',10:'GND'})
main.newpage('DAC digital isolation / partial-power-down protection',[
    'SN74LV125ATPWR powered from DAC AVDD, TTL VIH=2.0V and Ioff. OE pull-up makes default state high impedance.',
    'MCU_INPUT_ENABLE enables SPI only when HW_PGOOD=1. Keep OUTPUT_ENABLE=0 throughout DAC reset/reference startup.',
    'Unused gates: inputs grounded, OE high, outputs intentionally NC. Outputs never connect directly to a 3.3V MCU pin.'])
main.add('BUF','U5',{1:'SPI_OE_N',2:'SCLK',3:'SCLK_BUFFERED',4:'SPI_OE_N',5:'DIN',6:'DIN_BUFFERED',7:'GND',8:'SYNC_N',9:'SYNC_EXT',10:'SPI_OE_N',11:'LDAC_N',12:'LDAC_EXT',13:'SPI_OE_N',14:'VDD5'})
main.add('BUF','U6',{1:'SPI_OE_N',2:'CLR_EXT',3:'CLR_N',4:'VDD5',5:'GND',7:'GND',9:'GND',10:'VDD5',12:'GND',13:'VDD5',14:'VDD5'})
main.add('DRIVER','Q2',{1:'INPUT_ENABLE_SAFE',2:'GND',3:'SPI_OE_N'})
main.pair('R10K','R25','VDD5','SPI_OE_N');main.pair(rt['47k'],'R26','INPUT_ENABLE_SAFE','GND')
for i,net in enumerate(['SCLK','DIN','SYNC_EXT','LDAC_EXT','CLR_EXT'],27):main.pair('R100K','R'+str(i),net,'GND')
main.pair('R10K','R32','SCLK_DAC','GND')
main.pair('R10K','R33','DIN_DAC','GND')
for n in ['C28','C29']:main.pair('OLD_C18',n,'VDD5','GND')
add_safety(main,'S','VDD5','116k','127k')

mcu=Project('STM32H747_DAC_SMA_2CH_revision')
mcu.newpage('STM32H747 DAC SMA receiver / bipolar output',[
    'External MCU, VREF+=3.3V baseline. Two SMA inputs and two SMA outputs, high impedance load; NO 50-ohm termination.',
    'J5: 1 +12V, 2 GND, 3 -12V, 4 GND, 5 VREF+, 6 MCU 3V3, 7 5V, 8 INPUT_ENABLE, 9 OUTPUT_ENABLE, 10 HW_PGOOD.',
    'Input relay K2 disconnects MCU signals when receiver is unpowered. Enable inputs FIRST, settle, then enable outputs.',
    'MCU/source-side buffer remains required for ordinary coax CL>50pF. Nominal output gain 100k/14k = 7.142857.'])
mcu.add('HEADER','J5',{1:'VPOS12',2:'GND',3:'VNEG12',4:'GND',5:'MCU_VREF_PLUS',6:'MCU_3V3',7:'VIN_RAW',8:'MCU_INPUT_ENABLE',9:'MCU_OUTPUT_ENABLE',10:'HW_PGOOD'})
mcu.pair(rg['10k'],'R31','MCU_VREF_PLUS','BIAS_HALF');mcu.pair(rg['10k'],'R32','BIAS_HALF','GND')
mcu.add('OLD_U4','U2',{1:'VBIAS',2:'VBIAS',3:'BIAS_HALF',4:'VNEG12',8:'VPOS12'},part=0)
mcu.add('OLD_U4','U2',{5:'GND',6:'SPARE_OUT',7:'SPARE_OUT'},part=1)
for ch,offset,part in [('A',0,0),('B',10,1)]:
    mcu.add('OLD_J2','J1' if ch=='A' else 'J2',{1:'GND',2:'GND',3:'GND',4:'GND',5:'MCU_'+ch})
    mcu.pair('OLD_R11','R'+str(offset+1),'RECEIVE_'+ch,'IN_'+ch)
    mcu.pair('R10M','R'+str(offset+2),'IN_'+ch,'VBIAS')
    mcu.add('OLD_U4','U1',({1:'BUF_A',2:'BUF_A',3:'IN_A',4:'VNEG12',8:'VPOS12'} if ch=='A' else {5:'IN_B',6:'BUF_B',7:'BUF_B'}),part=part)
    for n,key,a,b in [(3,rg['14k'],'BUF_'+ch,ch+'_PLUS'),(4,rg['100k'],ch+'_PLUS','GND'),(5,rg['14k'],'VBIAS',ch+'_MINUS'),(6,rg['100k'],ch+'_SENSE',ch+'_MINUS'),(7,'OLD_R16',ch+'_RAW',ch+'_SENSE')]:mcu.pair(key,'R'+str(offset+n),a,b)
    mcu.add('OLD_U4','U3',({1:'A_RAW',2:'A_MINUS',3:'A_PLUS',4:'VNEG12',8:'VPOS12'} if ch=='A' else {5:'B_PLUS',6:'B_MINUS',7:'B_RAW'}),part=part)
    mcu.pair('OLD_C25','C1' if ch=='A' else 'C3',ch+'_MINUS',ch+'_RAW')
    mcu.pair('OLD_C22','C2' if ch=='A' else 'C4',ch+'_SENSE','GND')
    mcu.add('OLD_J2','J3' if ch=='A' else 'J4',{1:'GND',2:'GND',3:'GND',4:'GND',5:'SMA_OUT_'+ch})
mcu.add('RELAY','K1',{1:'VIN_RAW',8:'OUT_COIL_N',2:'GND',3:'SMA_OUT_A',4:'A_SENSE',7:'GND',6:'SMA_OUT_B',5:'B_SENSE'})
mcu.add('RELAY','K2',{1:'VIN_RAW',8:'IN_COIL_N',2:'VBIAS',3:'RECEIVE_A',4:'MCU_A',7:'VBIAS',6:'RECEIVE_B',5:'MCU_B'})
mcu.add('DRIVER','Q1',{1:'INPUT_ENABLE_SAFE',2:'GND',3:'IN_COIL_N'})
mcu.add('DIO','D1',{1:'VIN_RAW',2:'IN_COIL_N'})
mcu.pair(rt['47k'],'R33','INPUT_ENABLE_SAFE','GND')
for i in range(3):
    for j,rail in enumerate(['VPOS12','VNEG12']):mcu.pair('OLD_C18','C'+str(11+2*i+j),rail,'GND')
add_safety(mcu,'S','MCU_VREF_PLUS','68k','77.5k')
tx=Project('STM32H747_DAC_SMA_TX_buffer_revision')
tx.newpage('MCU-side SMA cable driver - separate transmitter accessory',[
    'Install at the MCU end, BEFORE the SMA/coax cable. OPA2320AIDR dual SOIC-8, single MCU 3V3 supply.',
    'J1: 1 MCU 3V3, 2 GND, 3 raw DAC1, 4 raw DAC2, 5..10 GND. J2/J3 are buffered SMA cable outputs.',
    'Unity feedback is before 100-ohm cable isolation resistor. Receiver is high impedance, NOT 50-ohm terminated.',
    'Power with the MCU analog supply; use normal DAC buffer mode and calibrate the COMPLETE transmitter/receiver path.'])
tx.add('HEADER','J1',{1:'MCU_3V3',2:'GND',3:'DAC1_RAW',4:'DAC2_RAW',5:'GND',6:'GND',7:'GND',8:'GND',9:'GND',10:'GND'})
tx.add(txamp,'U1',{1:'TX_A',2:'TX_A',3:'DAC1_RAW',4:'GND',8:'MCU_3V3'},part=0)
tx.add(txamp,'U1',{5:'DAC2_RAW',6:'TX_B',7:'TX_B'},part=1)
tx.pair('OLD_R16','R1','TX_A','SMA_A');tx.pair('OLD_R16','R2','TX_B','SMA_B')
tx.pair('OLD_R3','R3','DAC1_RAW','GND');tx.pair('OLD_R3','R4','DAC2_RAW','GND')
tx.pair('OLD_C18','C1','MCU_3V3','GND');tx.pair('OLD_C6','C2','MCU_3V3','GND')
tx.add('OLD_J2','J2',{1:'GND',2:'GND',3:'GND',4:'GND',5:'SMA_A'});tx.add('OLD_J2','J3',{1:'GND',2:'GND',3:'GND',4:'GND',5:'SMA_B'})
if '--main-only' in sys.argv:
    prior=json.loads((OUT/'build-manifest.json').read_text(encoding='utf8'))
    manifest=[main.finish()]+prior[1:]
elif '--tx-only' in sys.argv:
    manifest=json.loads((OUT/'build-manifest.json').read_text(encoding='utf8'))[:2]+[tx.finish()]
else:
    manifest=[main.finish(),mcu.finish(),tx.finish()]
(OUT/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
print(json.dumps(manifest))
