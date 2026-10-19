"""Schematic/footprint model for the authorized single-board redesign."""
import importlib.util, json, math, re
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pcb-two-zone'
OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('cio',Path(__file__).with_name('correction-io.py'));io=importlib.util.module_from_spec(spec);spec.loader.exec_module(io)
LIB=io.read_export(ROOT/'output/schematic-correction/DAC8562 module_schematic_ERC_clean.epro2')
validation=json.loads((ROOT/'output/schematic-correction/erc-final-validation.json').read_text(encoding='utf8'))
pin_nets={};net=None
for line in validation['pages'][-1]['netlist'].splitlines():
    s=line.strip()
    if s=='(':net='';continue
    if s==')':net=None;continue
    if net is None:continue
    if not net:net=s
    elif s:pin_nets[re.sub(r'^([^-]+)-([^ ]+).*',r'\1.\2',s)]=net
PARTS={}
for pg in validation['pages']:
    doc=next(iter(io.documents(pg['source']).values()));attrs=io.attrs(doc)
    for (typ,pid),(_,p) in doc['records'].items():
        a=attrs.get(pid,{})
        name=a.get('Designator')
        if typ!='COMPONENT' or not name or name in PARTS: continue
        dev=next(v['attributes'] for _,v in LIB[a['Device']]['records'].values() if 'attributes' in v)
        fp=a.get('Footprint') or dev['Footprint'];footprint=LIB[fp]
        pads=[]
        for (t,padid),(_,pad) in footprint['records'].items():
            if t!='PAD':continue
            pads.append({'id':padid,**pad,'net':pin_nets.get(name+'.'+pad['num'],'')})
        PARTS[name]={'page':pg['page'],'schematicId':pid,'attributes':a,'footprint':fp,'pads':pads}
def transform(x,y,angle):
    r=math.radians(angle)
    return x*math.cos(r)-y*math.sin(r),x*math.sin(r)+y*math.cos(r)
def world_pad(part,pad,x,y,angle):
    dx,dy=transform(pad['centerX'],pad['centerY'],angle)
    return {**pad,'centerX':x+dx,'centerY':y+dy,'padAngle':(pad['padAngle']+angle)%360}
if __name__=='__main__':
    (OUT/'physical-model.json').write_text(json.dumps(PARTS,ensure_ascii=False,indent=2),encoding='utf8')
    seen=set();seed=[]
    for name,part in PARTS.items():
        if part['footprint'] in seen: continue
        seen.add(part['footprint'])
        dev=LIB[part['attributes']['Device']]
        source=next(v['source'] for h,v in dev['records'].values() if 'source' in v)
        uuid,libraryUuid=source.split('|')
        seed.append({'name':name,'footprint':part['footprint'],'uuid':uuid,'libraryUuid':libraryUuid})
    (OUT/'seed-references.json').write_text(json.dumps(seed,indent=2),encoding='utf8')
    for name,p in PARTS.items():
        if name.startswith(('U','K','J')) or name in ['Q1','C6','C7','C9','C10','C11','C12','L1','L2','D1','D2','R1','R2','R3','R4','R5']:
            print(name,p['attributes'].get('Manufacturer Part'),[(d['num'],d['net'],round(d['centerX']*.0254,2),round(d['centerY']*.0254,2)) for d in p['pads']])
