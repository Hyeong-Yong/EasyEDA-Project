"""Build reviewed DC-coupled LabTool-principle candidates offline.

No EasyEDA API, native project, or existing library mutation. New power/reference
circuits occupy unused space on page 03; all ten input chains remain on page 06.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/candidates/adc10-labtool-20261018'
BASE = ROOT / 'output/validation/native-adc10-sch-labtool_before-20261018.epru'
CHECK = ROOT / 'output/checkpoints/STM32H747_before_labtool_afe_20261018.epro2'
G = runpy.run_path(str(ROOT / 'output/candidates/adc10-dc-buffer-20261017/build-adc10-dc-candidate.py'))
READ = G['read_checkpoint']
OLDLIB = json.loads((ROOT / 'output/candidates/adc-dc-buffer/adc-dc-runtime-library-map.json').read_text())


def uid(s):
    return hashlib.sha256(('stm-h747-labtool-20261018/' + s).encode()).hexdigest()[:16]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def serialize(rows):
    return ''.join(json.dumps(r['h'], separators=(',', ':')) + '||' + json.dumps(r['b'], ensure_ascii=False, separators=(',', ':')) + '|\n' for r in rows)


def on(p, a, b):
    return abs((p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])) < 1e-5 and min(a[0],b[0])-1e-6 <= p[0] <= max(a[0],b[0])+1e-6 and min(a[1],b[1])-1e-6 <= p[1] <= max(a[1],b[1])+1e-6


class Sheet:
    def __init__(self, rows, docs, libraries, name):
        self.original = copy.deepcopy(rows)
        self.rows = copy.deepcopy(rows)
        self.docs, self.libraries, self.name = docs, libraries, name
        self.removed = set()
        self.ticket = max(r['h'].get('ticket', 0) for r in rows)
        self.refresh()
        self.templates = {ref: self.block(ref) for ref in self.refs}
        self.contract = {}

    def refresh(self):
        self.lookup = {(r['h']['type'], r['h'].get('id')): r for r in self.rows}
        self.attrs = defaultdict(dict)
        for r in self.rows:
            if r['h']['type'] == 'ATTR':
                self.attrs[r['b']['parentId']][r['b']['key']] = r
        self.refs = {a['Designator']['b']['value']: cid for cid, a in self.attrs.items() if 'Designator' in a}

    def add(self, kind, body, key):
        rid = uid(self.name + '/' + key)
        if (kind, rid) in self.lookup:
            raise RuntimeError(('duplicate primitive', kind, rid, key))
        self.ticket += 1
        row = {'h': {'type': kind, 'id': rid, 'ticket': self.ticket}, 'b': body}
        self.rows.append(row)
        self.lookup[kind, rid] = row
        if kind == 'ATTR':
            self.attrs[body['parentId']][body['key']] = row
        return rid

    def attr(self, cid, key, value, x=None, y=None, visible=False):
        body = {'parentId': cid, 'key': key, 'value': value, 'x': x, 'y': y,
                'rotation': 0, 'color': '#000080', 'fontFamily': 'Arial',
                'fontSize': .001 if key == 'NET' else 5 if visible else None,
                'fontWeight': False, 'italic': False, 'underline': False, 'strikeout': False,
                'align': 'LEFT_BOTTOM', 'keyVisible': False, 'valueVisible': visible,
                'fillColor': None, 'locked': False, 'zIndex': 9000}
        return self.add('ATTR', body, 'attr/' + cid + '/' + key)

    def text(self, value, x, y, key, size=5):
        self.add('TEXT', {'x': x, 'y': y, 'value': value, 'rotation': 0, 'color': '#006666',
                         'fillColor': None, 'fontFamily': 'Arial', 'fontSize': size,
                         'fontWeight': False, 'italic': False, 'underline': False,
                         'align': 'LEFT_BOTTOM', 'zIndex': 10000, 'locked': False}, key)

    def block(self, ref):
        cid = self.refs[ref]
        return [copy.deepcopy(self.lookup['COMPONENT', cid])] + [copy.deepcopy(r) for r in self.attrs[cid].values()]

    def remove_component(self, ref):
        cid = self.refs[ref]
        self.removed.add(('COMPONENT', cid))
        self.removed.update(('ATTR', r['h']['id']) for r in self.attrs[cid].values())

    def remove_wire(self, wid):
        self.removed.add(('WIRE', wid))
        for (kind, rid), r in self.lookup.items():
            if r['b'].get('lineGroup') == wid or r['b'].get('parentId') == wid:
                self.removed.add((kind, rid))

    def pins(self, ref):
        cid = self.refs[ref]
        b = self.lookup['COMPONENT', cid]['b']
        sym = self.attrs[cid]['Symbol']['b']['value']
        pa = defaultdict(dict)
        doc = self.docs['SYMBOL', sym]
        for h, body in doc.values():
            if h['type'] == 'ATTR':
                pa[body.get('parentId')][body['key']] = body.get('value')
        a = math.radians(b['rotation'])
        result = {}
        for h, p in doc.values():
            if h['type'] != 'PIN' or p.get('partId', b['partId']) != b['partId']:
                continue
            xx = p['x']*math.cos(a) + p['y']*math.sin(a)
            yy = -p['x']*math.sin(a) + p['y']*math.cos(a)
            if b.get('isMirror'):
                xx = -xx
            result[str(pa[h['id']]['Pin Number'])] = (round(b['x']+xx,6), round(b['y']+yy,6))
        return result

    def component(self, ref, template, x, y, rotation=0, device=None, value=None, extra=None, block=None):
        # Existing components retain both primitive identity and physical Unique ID.
        existed = ref in self.refs and ('COMPONENT', self.refs[ref]) not in self.removed
        source = copy.deepcopy(block if block is not None else self.templates[template])
        cb = source[0]['b']
        old_attrs = {r['b']['key']: r['b'] for r in source[1:]}
        cid = self.refs[ref] if existed else uid(self.name + '/component/' + ref)
        unique = self.attrs[cid]['Unique ID']['b']['value'] if existed else old_attrs.get('Unique ID', {}).get('value') if block is not None else uid('physical/' + ref)
        if not unique:
            unique = uid('physical/' + ref)
        cb.update(x=x, y=y, rotation=rotation, isMirror=False)
        if not existed:
            self.ticket += 1
            row = {'h': {'type':'COMPONENT','id':cid,'ticket':self.ticket}, 'b':cb}
            self.rows.append(row)
            self.lookup['COMPONENT',cid] = row
            self.refs[ref] = cid
        else:
            self.lookup['COMPONENT',cid]['b'] = cb
        props = {k: v.get('value') for k,v in old_attrs.items()}
        props.update({'Designator':ref, 'Unique ID':unique})
        if device:
            lib = self.libraries[device]
            props.update(lib['attributes'])
            props.update({'Designator':ref, 'Unique ID':unique, 'Device':lib['uuid'],
                          'Symbol':lib['symbolUuid'], 'Footprint':lib['footprintUuid'],
                          'Value':value or lib['attributes']['Value']})
            # Match known working native COMPONENT metadata, not guessed UUID strings.
            sym_info = next(i for i in self.libmanifest['symbols'].values() if i['uuid']==lib['symbolUuid']) if device in self.newkeys else OLDLIB['symbols']['R' if device=='R6K8' else 'C'] if device.startswith(('R','C')) else OLDLIB['symbols'].get(device)
            footprint_info = next((i for i in self.allfootprints if i['uuid']==lib['footprintUuid']), None)
            cb.setdefault('attrs', {}).update({
                'DeviceName':json.dumps({'uuid':lib['uuid'],'name':lib['title'],'source':lib.get('source',lib['uuid']+'|project')},separators=(',',':')),
                'SymbolName':json.dumps({'uuid':lib['symbolUuid'],'name':sym_info['title'],'source':sym_info.get('source',lib['symbolUuid']+'|project')},separators=(',',':')),
                'FootprintName':json.dumps({'uuid':lib['footprintUuid'],'name':footprint_info['title'],'source':footprint_info.get('source',lib['footprintUuid']+'|project')},separators=(',',':')),
                'Devices':'[]','Symbols':'[]','Footprints':'[]'})
        if value is not None:
            props['Value'] = value
        props.update(extra or {})
        for key, val in props.items():
            ab = copy.deepcopy(old_attrs.get(key, {'x':None,'y':None,'rotation':0,'keyVisible':False,'valueVisible':False,'fontSize':None,'align':'LEFT_BOTTOM','color':None,'fontFamily':None,'locked':False,'zIndex':100}))
            ab.update(parentId=cid, key=key, value=val)
            if key in ('Designator','Value'):
                ab.update(x=x+8,y=y-12 if key=='Designator' else y-5,rotation=0,fontSize=4.8,valueVisible=True,align='LEFT_BOTTOM')
                if device and (device in self.newkeys or device=='OPA320'):
                    ab.update(x=x-55,y=y-35 if key=='Designator' else y-28)
                if device in ('TPS60403','TPS72301','TPS7A2033','REF5025'):
                    ab.update(x=x-30,y=y-65 if key=='Designator' else y-58)
                if ref.startswith('J'):
                    ab.update(x=x-10,y=y-16,valueVisible=key=='Designator')
                if ref.startswith('TP'):
                    # Existing per-TP symbols retain their original vector caption.
                    ab.update(x=x-8,y=y-16,valueVisible=False)
            elif ab.get('x') is not None:
                ab.update(x=None,y=None,valueVisible=False)
            if key in self.attrs[cid]:
                self.attrs[cid][key]['b'] = ab
            else:
                self.add('ATTR', ab, 'component/'+ref+'/'+key)
        return self.pins(ref)

    def wire(self, net, points, key, show=False):
        # Each key represents one connected island; extra branches use segments().
        return self.segments(net, list(zip(points,points[1:])), key, show=show)

    def segments(self, net, segments, key, show=False):
        wid = self.add('WIRE', {'zIndex':9000,'locked':False}, 'wire/'+key)
        self.attr(wid,'NET',net,*segments[0][0],True)
        self.attr(wid,'Relevance','[]')
        for i,(a,b) in enumerate(segments):
            if a==b:
                continue
            self.add('LINE', {'startX':a[0],'startY':a[1],'endX':b[0],'endY':b[1],
                             'lineGroup':wid,'strokeColor':'#009600','strokeStyle':'SOLID','strokeWidth':.6,
                             'fillColor':None,'fillStyle':None}, 'wire/'+key+'/'+str(i))
        if show:
            x,y=segments[0][0]
            self.text(net,x,y-4,'netlabel/'+key,4.7)
        return wid

    def pin_stub(self, ref, number, net, dx=0, dy=10, key=None):
        p = self.pins(ref)[str(number)]
        end = (p[0]+dx,p[1]+dy)
        self.wire(net,[p,end],key or ref+'/'+str(number),True)

    def expected(self, ref, nets):
        self.contract[ref] = {str(k):v for k,v in nets.items()}

    def finished(self):
        return [r for r in self.rows if (r['h']['type'],r['h'].get('id')) not in self.removed]


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    runtime_path = OUT / 'libraries/runtime-library-map.json'
    if not runtime_path.is_file():
        raise RuntimeError('Import and independently map new native libraries before building candidates')
    newlib = json.loads(runtime_path.read_text())
    protection_path=OUT/'libraries/reverse-protection/runtime-library-map.json'
    if not protection_path.is_file():
        raise RuntimeError('Reverse-current protection library runtime map required')
    protection=json.loads(protection_path.read_text())
    for group in ('devices','symbols','footprints'):
        newlib[group].update(protection[group])
    docs = READ(ROOT / 'output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2')
    adc_rows = G['parse'](BASE)
    power_id = ('SCH_PAGE','360993a3108b5759')
    before_docs = READ(CHECK)
    power_rows = [{'h':h,'b':b} for h,b in before_docs[power_id].values()]
    lib_devices = {**OLDLIB['devices'],**newlib['devices']}
    adc = Sheet(adc_rows,docs,lib_devices,'adc')
    power = Sheet(power_rows,docs,lib_devices,'power')
    for sheet in (adc,power):
        sheet.newkeys=set(newlib['devices'])
        sheet.libmanifest=newlib
        sheet.allfootprints=list(OLDLIB['footprints'].values())+list(newlib['footprints'].values())
    # Reuse proven native passive component attributes even on power page.
    power.templates.update(adc.templates)
    target=[]
    specs=[(2,'ADC1_INP0',137,140,141,80,97,100,0,0),(3,'ADC1_INP1',138,142,143,81,98,101,1,0),(4,'ADC1_INP16',139,144,145,82,99,102,2,0),
           (5,'ADC2_INP3',149,152,153,86,106,113,0,1),(6,'ADC2_INP12',150,154,155,87,107,114,1,1),(7,'ADC2_INP13',151,156,157,88,108,115,2,1),
           (8,'ADC3_INP2',161,165,166,93,109,116,0,2),(9,'ADC3_INP6',162,167,168,94,110,117,1,2),(10,'ADC3_INP7',163,169,170,95,111,118,2,2),(11,'ADC3_INP8',164,171,172,96,112,119,3,2)]
    for i,(j,net,rb,ri,rs,c,pre,dec,col,row) in enumerate(specs):
        target.extend([f'J{j}',f'R{rb}',f'R{ri}',f'R{rs}',f'C{c}',f'C{pre}',f'C{dec}',f'U{10+i}',f'TP{j-1}'])
    target += ['U9','C103','C104','C105']
    old_target_pins=[p for ref in target for p in adc.pins(ref).values()]
    affected_wires={r['b']['lineGroup'] for r in adc.original if r['h']['type']=='LINE' and any(on(p,(r['b']['startX'],r['b']['startY']),(r['b']['endX'],r['b']['endY'])) for p in old_target_pins)}
    # Only nonphysical flags directly attached to old target islands are removed.
    affected_lines=[r['b'] for r in adc.original if r['h']['type']=='LINE' and r['b'].get('lineGroup') in affected_wires]
    flags=[]
    for ref,cid in list(adc.refs.items()):
        if ref in target or adc.attrs[cid].get('Convert to PCB',{}).get('b',{}).get('value')=='yes':
            continue
        if any(on(p,(b['startX'],b['startY']),(b['endX'],b['endY'])) for p in adc.pins(ref).values() for b in affected_lines):
            flags.append(ref)
    for wid in affected_wires:
        adc.remove_wire(wid)
    for ref in flags:
        adc.remove_component(ref)
    # Delete old ADC port-vector/text annotations; keep the original border and aux circuits.
    for r in adc.rows:
        typ,b=r['h']['type'],r['b']
        pts=[(b['x'],b['y'])] if b.get('x') is not None and b.get('y') is not None else []
        if typ=='POLY':
            pts=[(p['x'],p['y']) for p in b.get('points',[])]
        if typ in ('POLY','TEXT') and pts and all(180<=x<=1590 and 85<=y<=610 for x,y in pts):
            adc.removed.add((typ,r['h']['id']))
        if typ=='TEXT' and any(v in str(b.get('value','')) for v in ('ADC_BIAS_2V5','Shared 2.5 V','bias - 2026','VADC = 0.25','VIN = 2 x','Floating ADC','Floating input','Source impedance affects')):
            adc.removed.add((typ,r['h']['id']))
        if typ=='TEXT' and b.get('x')==130 and 1020<=b.get('y',0)<=1075:
            adc.removed.add((typ,r['h']['id']))
        if typ=='TEXT' and b.get('value') in ('GND','+3V3') and 980<=b.get('x',0)<=1450 and 710<=b.get('y',0)<=865:
            adc.removed.add((typ,r['h']['id']))
    # Relocate complete auxiliary drawings, preserving all wire nets and identities.
    for r in adc.rows:
        typ,b=r['h']['type'],r['b']
        if (typ,r['h'].get('id')) in adc.removed:
            continue
        pts=[(b['x'],b['y'])] if b.get('x') is not None and b.get('y') is not None else []
        if typ=='LINE':pts=[(b['startX'],b['startY']),(b['endX'],b['endY'])]
        if typ=='POLY':pts=[(p['x'],p['y']) for p in b.get('points',[])]
        if pts and all(180<=x<=1200 and 610<=y<=725 for x,y in pts):G['translate'](b,0,100)
        elif pts and all(600<=x<=1030 and 780<=y<=1000 for x,y in pts):G['translate'](b,300,50)
        elif pts and all(180<=x<=700 and 730<=y<=835 for x,y in pts):G['translate'](b,0,130)
    # Move the four old REF components to page03 with their physical UIDs intact.
    ref_blocks={ref:adc.block(ref) for ref in ('U9','C103','C104','C105')}
    for ref in ref_blocks:adc.remove_component(ref)

    for i,(j,net,rb,ri,rs,c,pre,dec,col,row) in enumerate(specs):
        ox,oy=145+350*col,80+200*row
        at=lambda x,y:(ox+x,oy+y)
        raw=f'ADC_J{j}_RAW'; pre_net=f'ADC_J{j}_FILTER'; buf=f'ADC_J{j}_BUF'; summ=f'ADC_J{j}_SUM'; drv=f'ADC_J{j}_DRV'
        # Move SMA by its real pin1 rather than guessing the legacy symbol origin.
        old=adc.pins(f'J{j}')['1']; cb=adc.lookup['COMPONENT',adc.refs[f'J{j}']]['b']
        jx,jy=cb['x']+ox+10-old[0],cb['y']+oy+60-old[1]
        adc.component(f'J{j}',f'J{j}',jx,jy,cb['rotation'])
        adc.component(f'R{ri}','R140',*at(45,60),device='R6K8',value='3.32k',extra={'Tolerance':'0.1%','Temperature Coefficient':'25 ppm/K or better'})
        adc.component(f'C{pre}','C97',*at(70,100),device='C10N',value='10nF')
        adc.component(f'R{177+i}','R140',*at(10,110),rotation=90,device='R6K8',value='100k',extra={'Tolerance':'0.1%'})
        adc.component(f'U{20+i}','U10',*at(120,70),device='OPA189')
        adc.component(f'C{120+i*3}','C100',*at(150,10),device='C100N',value='100nF')
        adc.component(f'C{121+i*3}','C100',*at(150,100),device='C100N',value='100nF')
        adc.component(f'R{rb}','R140',*at(190,60),device='R6K8',value='4.00k',extra={'Tolerance':'0.1%'})
        adc.component(f'U{10+i}','U10',*at(235,100),device='OPA320')
        adc.component(f'C{dec}','C100',*at(295,60),device='C100N',value='100nF')
        adc.component(f'R{187+i}','R140',*at(235,155),device='R6K8',value='2.80k',extra={'Tolerance':'0.1%'})
        adc.component(f'C{122+i*3}','C97',*at(235,180),rotation=90,device='C10N',value='10nF')
        adc.component(f'R{rs}','R141',*at(305,100),device='R47',value='47')
        adc.component(f'C{c}','C80',*at(330,135),device='C10N',value='10nF')
        old=adc.pins(f'TP{j-1}')['1']; cb=adc.lookup['COMPONENT',adc.refs[f'TP{j-1}']]['b']
        adc.component(f'TP{j-1}',f'TP{j-1}',cb['x']+ox+330-old[0],cb['y']+oy+80-old[1],cb['rotation'])
        # Real contiguous signal wires from SMA to MCU, separated only by devices.
        rp=adc.pins(f'R{177+i}')
        adc.segments(raw,[(at(10,60),at(30,60)),(at(10,60),(rp['2'][0],rp['2'][1]))],f'J{j}/raw')
        adc.wire('GND',[rp['1'],at(10,140)],f'J{j}/pulldown-ground',True)
        adc.segments(pre_net,[(at(60,60),at(80,60)),(at(70,60),at(70,90))],f'J{j}/input-filter')
        adc.pin_stub(f'C{pre}',2,'GND',dy=10)
        adc.segments(buf,[(at(165,70),at(175,70)),(at(175,70),at(175,60)),
                         (at(165,70),at(172,70)),(at(172,70),at(172,120)),(at(172,120),at(75,120)),(at(75,120),at(75,80)),(at(75,80),at(80,80))],f'J{j}/buffer-feedback')
        adc.wire('+5V_AFE',[at(120,35),at(120,-5),at(150,-5),at(150,0)],f'J{j}/buffer-positive',True)
        adc.pin_stub(f'C{120+i*3}',2,'GND',dx=10,dy=0)
        adc.wire('-3V_AFE',[at(120,105),at(140,105),at(140,90),at(150,90)],f'J{j}/buffer-negative',True)
        adc.pin_stub(f'C{121+i*3}',2,'GND',dy=5)
        adc.segments(summ,[(at(205,60),at(205,110)),(at(205,110),at(195,110)),(at(195,110),at(180,110)),(at(180,110),at(180,155)),(at(180,155),at(220,155)),(at(180,155),at(180,180)),(at(180,180),at(225,180))],f'J{j}/sum')
        adc.wire('ADC_OFFSET_0V97',[at(195,90),at(185,90),at(185,85)],f'J{j}/offset',True)
        adc.segments(drv,[(at(280,100),at(290,100)),(at(280,100),at(285,100)),(at(285,100),at(285,155)),(at(285,155),at(250,155)),(at(285,155),at(285,180)),(at(285,180),at(245,180))],f'J{j}/driver-feedback')
        adc.wire('+3V3',[at(235,65),at(235,50),at(295,50)],f'J{j}/driver-power',True)
        adc.pin_stub(f'U{10+i}',2,'GND',dy=10)
        adc.pin_stub(f'C{dec}',2,'GND',dy=10)
        adc.segments(net,[(at(320,100),at(340,100)),(at(330,80),at(330,100)),(at(330,100),at(330,125))],f'J{j}/adc',True)
        adc.pin_stub(f'C{c}',2,'GND',dy=10)
        adc.pin_stub(f'J{j}',2,'GND',dy=10)
        adc.text(f'J{j}: -2V .. +2V; DC / 60Hz',*at(0,-20),f'J{j}/caption',5.5)
        for ref,nets in {
            f'J{j}':{1:raw,2:'GND'},f'R{177+i}':{1:'GND',2:raw},f'R{ri}':{1:raw,2:pre_net},f'C{pre}':{1:pre_net,2:'GND'},
            f'U{20+i}':{1:buf,2:'-3V_AFE',3:pre_net,4:buf,5:'+5V_AFE'},f'C{120+i*3}':{1:'+5V_AFE',2:'GND'},f'C{121+i*3}':{1:'-3V_AFE',2:'GND'},
            f'R{rb}':{1:buf,2:summ},f'U{10+i}':{1:drv,2:'GND',3:'ADC_OFFSET_0V97',4:summ,5:'+3V3'},f'C{dec}':{1:'+3V3',2:'GND'},
            f'R{187+i}':{1:summ,2:drv},f'C{122+i*3}':{1:summ,2:drv},f'R{rs}':{1:drv,2:net},f'C{c}':{1:net,2:'GND'},f'TP{j-1}':{1:net}}.items():adc.expected(ref,nets)

    # Page03 upper/right empty region: filtered +5, inverter and quiet -3V LDO.
    power.component('U30','U10',1140,250,device='TPS60403')
    power.component('R197','R140',1030,235,device='R6K8',value='4.7',extra={'Tolerance':'1%','Power Rating':'0.1 W minimum'})
    power.wire('+5V',[(1000,235),(1015,235)],'pump-5v',True)
    power.component('C150','C104',1060,275,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.segments('AFE_PUMP_IN',[((1045,235),(1090,235)),((1060,235),(1060,265))],'pump-input')
    power.pin_stub('C150',2,'GND')
    power.component('C151','C104',1140,320,rotation=90,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.wire('AFE_FLY_N',[(1090,270),(1080,270),(1080,320),(1130,320)],'fly-n')
    power.wire('AFE_FLY_P',[(1190,270),(1200,270),(1200,320),(1150,320)],'fly-p')
    power.pin_stub('U30',4,'GND',dy=10)
    power.component('C152','C104',1220,275,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.component('U31','U10',1310,250,device='TPS72301')
    power.segments('AFE_VNEG_RAW',[((1190,235),(1260,235)),((1220,235),(1220,265)),((1260,235),(1245,235)),((1245,235),(1245,265)),((1245,265),(1260,265))],'negative-raw',True)
    power.pin_stub('C152',2,'GND')
    power.component('C153','C104',1440,275,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.component('C154','C104',1480,275,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.segments('-3V_AFE',[((1360,235),(1480,235)),((1440,235),(1440,265)),((1480,235),(1480,265))],'negative-regulated',True)
    power.pin_stub('C153',2,'GND');power.pin_stub('C154',2,'GND');power.pin_stub('U31',1,'GND')
    power.component('R198','R140',1390,330,rotation=90,device='R6K8',value='15.4k',extra={'Tolerance':'0.1%'})
    power.component('R199','R140',1430,330,rotation=90,device='R6K8',value='10.0k',extra={'Tolerance':'0.1%'})
    power.wire('-3V_AFE',[(1390,345),(1390,360),(1505,360),(1505,235),(1480,235)],'negative-feedback-lower')
    power.wire('GND',[(1430,345),(1450,345),(1450,350)],'negative-feedback-ground',True)
    power.wire('AFE_NEG_FB',[(1360,265),(1390,265),(1390,315),(1430,315)],'negative-feedback')
    power.component('C155','C97',1460,330,device='C10N',value='10nF')
    power.wire('AFE_NEG_FB',[(1430,315),(1460,315),(1460,320)],'negative-feedback-cff-top')
    power.wire('-3V_AFE',[(1460,340),(1460,360),(1505,360)],'negative-feedback-cff-bottom')
    power.component('D20','R140',1280,185,rotation=180,device='BAT54WS')
    power.wire('-3V_AFE',[(1305,185),(1360,185),(1360,235)],'negative-protection-cathode')
    power.wire('AFE_VNEG_RAW',[(1255,185),(1215,185),(1215,235)],'negative-protection-anode')
    power.expected('D20',{1:'-3V_AFE',2:'AFE_VNEG_RAW'})
    # REF5025 classic AI uses ESR-controlled output capacitor; DNC/NC left open.
    power.component('R200','R140',1030,450,device='R6K8',value='4.7',extra={'Tolerance':'1%','Power Rating':'0.1 W minimum'})
    power.wire('+5V',[(1000,450),(1015,450)],'afe-positive-feed',True)
    power.component('C156','C104',1070,490,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.component('C157','C104',1100,490,device='C4U7',value='4.7uF',extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.component('U9','U10',1180,460,device='REF5025',block=ref_blocks['U9'])
    power.segments('+5V_AFE',[((1045,450),(1120,450)),((1070,450),(1070,480)),((1100,450),(1100,480))],'afe-positive',True)
    power.pin_stub('C156',2,'GND');power.pin_stub('C157',2,'GND');power.pin_stub('U9',4,'GND')
    power.component('C103','C103',1060,545,device='C1U',value='1uF',block=ref_blocks['C103'])
    power.wire('+5V_AFE',[(1060,535),(1045,535),(1045,450),(1070,450)],'reference-input-cap')
    power.pin_stub('C103',2,'GND')
    power.component('R201','R140',1270,520,rotation=90,device='R6K8',value='1.0',extra={'Tolerance':'1%'})
    power.component('C104','C104',1270,565,device='C4U7',value='4.7uF',block=ref_blocks['C104'],extra={'Voltage Rating':'10 V','Dielectric':'X7R'})
    power.wire('AFE_REF_2V5',[(1240,470),(1270,470),(1270,505)],'ref-out',True)
    power.wire('AFE_REF_ESR',[(1270,535),(1270,555)],'ref-output-esr')
    power.pin_stub('C104',2,'GND')
    power.component('C105','C105',1220,550,device='C1U',value='1uF',block=ref_blocks['C105'])
    power.wire('AFE_REF_NR',[(1240,490),(1250,490),(1250,530),(1220,530),(1220,540)],'ref-nr')
    power.pin_stub('C105',2,'GND')
    power.component('R202','R140',1330,470,device='R6K8',value='15.8k',extra={'Tolerance':'0.1%','Temperature Coefficient':'10 ppm/K or better'})
    power.wire('AFE_REF_2V5',[(1270,470),(1315,470)],'ref-divider-top')
    power.component('R203','R140',1380,520,rotation=90,device='R6K8',value='10.0k',extra={'Tolerance':'0.1%','Temperature Coefficient':'10 ppm/K or better'})
    power.component('C158','C104',1420,520,device='C4U7',value='4.7uF')
    power.segments('AFE_OFFSET_FILTER',[((1345,470),(1420,470)),((1380,470),(1380,505)),((1420,470),(1420,510))],'offset-divider',True)
    power.pin_stub('R203',1,'GND');power.pin_stub('C158',2,'GND')
    power.component('U32','U10',1360,670,device='OPA189')
    power.wire('AFE_OFFSET_FILTER',[(1420,470),(1460,470),(1460,605),(1310,605),(1310,660),(1320,660)],'offset-buffer-input')
    power.wire('AFE_OFFSET_BUFFER',[(1405,670),(1420,670),(1420,735),(1310,735),(1310,680),(1320,680)],'offset-buffer-feedback')
    power.component('R204','R140',1460,670,device='R6K8',value='1.00k',extra={'Tolerance':'1%'})
    power.wire('AFE_OFFSET_BUFFER',[(1420,670),(1445,670)],'offset-isolator-input')
    power.component('C159','C104',1510,710,device='C4U7',value='4.7uF')
    power.wire('ADC_OFFSET_0V97',[(1475,670),(1510,670),(1510,700)],'offset-bus',True)
    power.pin_stub('C159',2,'GND');power.pin_stub('U32',2,'GND')
    power.pin_stub('U32',5,'+5V_AFE',dy=-15)
    power.component('C160','C100',1440,610,device='C100N',value='100nF')
    power.pin_stub('C160',1,'+5V_AFE',dy=-10);power.pin_stub('C160',2,'GND')
    power.text('ADC analog supply: +5V input only; do not feed from 12V',1010,105,'power-caption',6)
    power.text('Ground-referenced bipolar buffers; fixed DC coupling; no input ground switch',1010,120,'power-caption2',5)
    power.text('Offset is NOT MCU VREF+: VREF+/VDDA and final OPA320 keep original +3V3 domain.',1010,785,'reference-separation',5)
    power.text('OPA189 +5V_AFE / -3V_AFE. TPS723 nominal -3.013V (1.186V ref, 15.4k/10k).',1010,800,'negative-value',5)
    for ref,nets in {'U30':{1:'AFE_VNEG_RAW',2:'AFE_PUMP_IN',3:'AFE_FLY_N',4:'GND',5:'AFE_FLY_P'},'R197':{1:'+5V',2:'AFE_PUMP_IN'},'C150':{1:'AFE_PUMP_IN',2:'GND'},'C151':{1:'AFE_FLY_N',2:'AFE_FLY_P'},'C152':{1:'AFE_VNEG_RAW',2:'GND'},'U31':{1:'GND',2:'AFE_VNEG_RAW',3:'AFE_VNEG_RAW',4:'AFE_NEG_FB',5:'-3V_AFE'},'C153':{1:'-3V_AFE',2:'GND'},'C154':{1:'-3V_AFE',2:'GND'},'R198':{1:'-3V_AFE',2:'AFE_NEG_FB'},'R199':{1:'GND',2:'AFE_NEG_FB'},'C155':{1:'AFE_NEG_FB',2:'-3V_AFE'},'R200':{1:'+5V',2:'+5V_AFE'},'C156':{1:'+5V_AFE',2:'GND'},'C157':{1:'+5V_AFE',2:'GND'},'U9':{1:None,2:'+5V_AFE',3:None,4:'GND',5:'AFE_REF_NR',6:'AFE_REF_2V5',7:None,8:None},'C103':{1:'+5V_AFE',2:'GND'},'R201':{1:'AFE_REF_ESR',2:'AFE_REF_2V5'},'C104':{1:'AFE_REF_ESR',2:'GND'},'C105':{1:'AFE_REF_NR',2:'GND'},'R202':{1:'AFE_REF_2V5',2:'AFE_OFFSET_FILTER'},'R203':{1:'GND',2:'AFE_OFFSET_FILTER'},'C158':{1:'AFE_OFFSET_FILTER',2:'GND'},'U32':{1:'AFE_OFFSET_BUFFER',2:'GND',3:'AFE_OFFSET_FILTER',4:'AFE_OFFSET_BUFFER',5:'+5V_AFE'},'R204':{1:'AFE_OFFSET_BUFFER',2:'ADC_OFFSET_0V97'},'C159':{1:'ADC_OFFSET_0V97',2:'GND'},'C160':{1:'+5V_AFE',2:'GND'}}.items():power.expected(ref,nets)
    original_power_keys={(r['h']['type'],r['h'].get('id')) for r in power.original}
    for r in power.rows:
        if (r['h']['type'],r['h'].get('id')) not in original_power_keys:
            G['translate'](r['b'],60,0)
    adc.text('10 inputs: SMA ground referenced; DC preserved; open input returns near GND, ADC near 1.647V.',130,1025,'contract-note1',5.5)
    adc.text('Nominal VADC = 1.6472868 - 0.7 x VIN (50-ohm loading ~0.05%); calibrate gain/offset and sign.',130,1037,'contract-note2',5.5)
    adc.text('Signal LPF poles ~4.72kHz and 5.68kHz; ADC reservoir 47ohm / 10nF. No 1MHz passband.',130,1049,'contract-note3',5)
    adc.text('Start with ADC acquisition >=8us; verify actual sample time / settling. Firmware is not changed here.',130,1061,'contract-note4',5)
    adc.text('Common offset, negative supply and reference on 03_MCU_POWER. Powered-off/overvoltage inputs not qualified.',130,1073,'contract-note5',5)
    plans=[]
    for sheet,filename in ((power,'03_MCU_POWER_labtool_candidate.epru'),(adc,'06_ADC_TIMER_DAC_labtool_candidate.epru')):
        baseline_path=OUT/(sheet.name+'-baseline.epru')
        baseline_path.write_text(serialize(sheet.original),encoding='utf8',newline='\n')
        final=sheet.finished(); path=OUT/filename; path.write_text(serialize(final),encoding='utf8',newline='\n')
        old={(r['h']['type'],r['h'].get('id')):r['b'] for r in sheet.original}; new={(r['h']['type'],r['h'].get('id')):r['b'] for r in final}
        plans.append({'pageUuid':final[0]['b']['uuid'],'candidatePath':str(path),'candidateSha256':sha(path),'baselinePath':str(baseline_path),'baselineSha256':sha(baseline_path),'baselineRows':len(old),'candidateRows':len(new),
                      'changed':[[*k] for k in old.keys()&new.keys() if old[k]!=new[k]],'deleted':[[*k] for k in old.keys()-new.keys()],'added':[[*k] for k in new.keys()-old.keys()],
                      'pinContract':sheet.contract})
    manifest={'schema':'adc10-labtool-schematic-candidates-20261018-v1','status':'OFFLINE_CANDIDATE_NOT_APPLIED','checkpoint':str(CHECK),'checkpointSha256':sha(CHECK),'pages':plans,
              'nativeProjectModifiedByThisScript':False,'firmwareModified':False,'manufacturingApproved':False,'filterChoice':'DC/60Hz low noise; several-kHz signal bandwidth',
              'gainNominal':-.7,'offsetNominalV':1.7*2.5*10/25.8,'inputRangeV':[-2,2],'openSmaIdealV':0,'openAdcIdealV':1.7*2.5*10/25.8,
              'preservedAdcPins':True,'independentVddaRegulatorFitted':False,'newLibraryRuntimeMap':str(runtime_path),'allPinContracts':{**adc.contract,**power.contract}}
    (OUT/'schematic-plan.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    print(json.dumps({'pages':[{k:p[k] for k in ('pageUuid','candidatePath','candidateRows')} for p in plans],'contractParts':len(manifest['allPinContracts']),'status':manifest['status']},ensure_ascii=False))


if __name__=='__main__':main()
