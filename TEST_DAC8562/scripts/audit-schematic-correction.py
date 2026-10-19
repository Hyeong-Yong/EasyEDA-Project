"""Independent geometry/topology audit of the two editable schematic sources."""
import importlib.util
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/schematic-correction'
s=importlib.util.spec_from_file_location('io_c',ROOT/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
libraries=io.read_export(OUT/'library-loaded-complete.epro2')
def on(p,a,b):
    return min(a[0],b[0])-1e-5<=p[0]<=max(a[0],b[0])+1e-5 and min(a[1],b[1])-1e-5<=p[1]<=max(a[1],b[1])+1e-5 and abs((p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0]))<1e-4

def component_pins(item,props):
    sym=libraries[props['Symbol']];a=io.attrs(sym);r=-math.radians(item['rotation'])
    for (kind,ident),(_,p) in sym['records'].items():
        if kind!='PIN' or p.get('partId')!=item['partId']:continue
        x=p['x']*math.cos(r)-p['y']*math.sin(r);y=p['x']*math.sin(r)+p['y']*math.cos(r)
        if item.get('isMirror'):x=-x
        yield str(a[ident].get('Pin Number','')), (round(item['x']+x,5),round(item['y']+y,5))

def graph(doc):
    attrs=io.attrs(doc)
    seg=[];names=defaultdict(set)
    for (kind,ident),(_,p) in doc['records'].items():
        if kind=='LINE' and p.get('lineGroup'):
            wid=p['lineGroup'];seg.append((wid,(p['startX'],p['startY']),(p['endX'],p['endY'])))
            if attrs.get(wid,{}).get('NET'):names[wid].add(attrs[wid]['NET'])
    roots={wid:wid for wid,_,_ in seg}
    def root(x):
        while roots[x]!=x:roots[x]=roots[roots[x]];x=roots[x]
        return x
    def join(a,b):
        a,b=root(a),root(b)
        if a!=b:roots[b]=a
    for (w,a,b),(v,c,d) in itertools.combinations(seg,2):
        if w!=v and any(on(p,a,b) and on(p,c,d) for p in [a,b,c,d]):join(w,v)
    components=[]
    for (kind,ident),(_,p) in doc['records'].items():
        if kind!='COMPONENT':continue
        pr=attrs.get(ident,{})
        if not pr.get('Symbol'):continue
        for num,pt in component_pins(p,pr):
            hits={w for w,a,b in seg if on(pt,a,b)}
            if pr.get('Global Net Name'):
                for w in hits:names[w].add(pr['Global Net Name'])
            if pr.get('Designator'):components.append((pr['Designator']+'.'+num,pt,hits))
    net_names=defaultdict(set)
    for wid,ns in names.items():net_names[root(wid)].update(ns)
    shorts=[{'wire':wid,'nets':sorted(ns)} for wid,ns in net_names.items() if len(ns)>1]
    pin_nets={};floating=[]
    for pin,pt,hits in components:
        ns=set().union(*(net_names[root(w)] for w in hits)) if hits else set()
        if not ns:floating.append({'pin':pin,'point':pt})
        pin_nets[pin]=sorted(set(pin_nets.get(pin,[]))|ns)
    return pin_nets,shorts,floating

allpins={};reports=[]
for filename in ['DAC8562.corrected-source.txt','DAC_MCU.corrected-source.txt']:
    doc=next(iter(io.documents((OUT/filename).read_text(encoding='utf8')).values()))
    p,shorts,floating=graph(doc);allpins.update(p)
    reports.append({'file':filename,'shorts':shorts,'floating':floating})
constraints={
 'U2.1':['VDD5'],'U2.2':['DAC_AVDD_FB'],'U2.4':['GND'],'U2.5':['VPOS12'],'U2.6':['LDO_BYP'],'U2.8':['VPOS12'],'U2.9':['GND'],
 'Q1.1':['BSW_GATE'],'Q1.2':['VIN_RAW'],'Q1.3':['VIN_SW'],
 'U3.1':['DACA'],'U3.2':['DACB'],'U3.3':['GND'],'U3.4':['LDAC_N'],'U3.5':['CLR_N'],'U3.6':['SYNC_N'],'U3.7':['SCLK_DAC'],'U3.8':['DIN_DAC'],'U3.9':['VDD5'],'U3.10':['VREF2V5'],
 'J1.6':['DAC_HOST_CLR'],'J1.7':['DAC_HOST_LDAC'],'J1.8':['DAC_HOST_SYNC'],'J1.9':['DAC_HOST_SCLK'],'J1.10':['DAC_HOST_DIN'],
 'J2.5':['DAC_SMA_A'],'J3.5':['DAC_SMA_B'],
 'K1.1':['VIN_RAW'],'K1.8':['DAC_OUT_COIL_N'],'K1.2':['GND'],'K1.3':['DAC_SMA_A'],'K1.4':['OUT_A'],'K1.5':['OUT_B'],'K1.6':['DAC_SMA_B'],'K1.7':['GND'],
 'U101.1':['MCU_BUFFER_A'],'U101.2':['MCU_BUFFER_A'],'U101.3':['MCU_RECEIVE_A'],'U101.4':['VNEG12'],'U101.5':['MCU_RECEIVE_B'],'U101.6':['MCU_BUFFER_B'],'U101.7':['MCU_BUFFER_B'],'U101.8':['VPOS12'],
 'U102.1':['MCU_VBIAS'],'U102.2':['MCU_VBIAS'],'U102.3':['MCU_VHALF'],'U102.4':['VNEG12'],'U102.5':['GND'],'U102.6':['MCU_SPARE'],'U102.7':['MCU_SPARE'],'U102.8':['VPOS12'],
 'U103.1':['MCU_RAW_A'],'U103.2':['MCU_MINUS_A'],'U103.3':['MCU_PLUS_A'],'U103.4':['VNEG12'],'U103.5':['MCU_PLUS_B'],'U103.6':['MCU_MINUS_B'],'U103.7':['MCU_RAW_B'],'U103.8':['VPOS12'],
 'K101.1':['VIN_RAW'],'K101.8':['MCU_IN_COIL_N'],'K101.2':['MCU_VBIAS'],'K101.3':['MCU_RECEIVE_A'],'K101.4':['MCU_RCV_EXTERNAL_A'],'K101.5':['MCU_RCV_EXTERNAL_B'],'K101.6':['MCU_RECEIVE_B'],'K101.7':['MCU_VBIAS'],
 'K102.1':['VIN_RAW'],'K102.8':['MCU_OUT_COIL_N'],'K102.2':['GND'],'K102.3':['MCU_OUT_A'],'K102.4':['MCU_SENSE_A'],'K102.5':['MCU_SENSE_B'],'K102.6':['MCU_OUT_B'],'K102.7':['GND'],
 'J101.5':['MCU_IN_A'],'J102.5':['MCU_IN_B'],'J103.5':['MCU_OUT_A'],'J104.5':['MCU_OUT_B'],
}
issues=[{'pin':pin,'expected':nets,'actual':allpins.get(pin)} for pin,nets in constraints.items() if allpins.get(pin)!=nets]
report={'pages':reports,'pinConstraintFailures':issues,'pinNets':allpins}
(OUT/'source-audit.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps({'pages':reports,'pinConstraintFailures':issues},indent=2))
