"""Prove the final name ECO changes neither PCB geometry nor pad nets."""
import importlib.util,json,sys
from collections import Counter
from pathlib import Path
root=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py')
io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
capture=json.loads((root/'output/readability/q3-name-sync.json').read_text(encoding='utf8'))
before=next(iter(io.documents(capture['beforeSource']).values()))
after=next(iter(io.documents(capture['source']).values()))
changes=[]
for key in sorted(set(before['records'])|set(after['records'])):
    a=before['records'].get(key,(None,None))[1];b=after['records'].get(key,(None,None))[1]
    if a!=b:changes.append({'type':key[0],'id':key[1],'before':a,'after':b})
sys.path.insert(0,str(root/'.tools/pcb-python'))
from shapely.geometry import LineString
from shapely.ops import unary_union
segments=[c for c in changes if c['type']=='LINE']
nonsegments=[c for c in changes if c['type']!='LINE']
assert len(nonsegments)==1,[(c['type'],c['id']) for c in nonsegments]
change=nonsegments[0]
assert change['type']=='COMPONENT' and change['id']=='1e58e2330359a121'
a=json.loads(json.dumps(change['before']));b=json.loads(json.dumps(change['after']))
assert a['attrs'].pop('Name')=='2N7002LT1G'
assert b['attrs'].pop('Name',None) in (None,'={Manufacturer Part}')
assert capture['afterName']=='={Manufacturer Part}'
assert a==b
assert len(segments)==3
old=[c['before'] for c in segments if c['before'] is not None]
new=[c['after'] for c in segments if c['after'] is not None]
assert len(old)==1 and len(new)==2
metadata=lambda p:{k:v for k,v in p.items() if k not in ('startX','startY','endX','endY')}
assert all(metadata(p)==metadata(old[0]) for p in new)
geometry=lambda ps:unary_union([LineString([(p['startX'],p['startY']),(p['endX'],p['endY'])]) for p in ps])
assert geometry(old).equals(geometry(new))
assert capture['passed'] is True and capture['details']==[]
result={'passed':True,'changesByType':dict(Counter(c['type'] for c in changes)),
        'q3NameOnly':True,'layoutRoutingCopperPadNetsUnchanged':True,
        'nameStorage':'Fixed Name override removed; native getter resolves device default ={Manufacturer Part}.',
        'nativeNormalization':'One existing collinear VNEG12 track split into two; exact centerline, width, layer and net unchanged.',
        'changes':changes}
(root/'output/final-review/q3-name-change-audit.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='changes'}))
