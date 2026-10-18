"""Read-only bounded audit of the twenty approved passive rotations."""
import hashlib
import json
import argparse
from collections import Counter
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[1]
parse=runpy.run_path(str(ROOT/'scripts/audit-adc10-readback.py'))['parse']
before_path=ROOT/'output/validation/native-adc10-pcb-eco_reopened-20261017.epru'
ap=argparse.ArgumentParser()
ap.add_argument('--source', type=Path, default=ROOT/'output/validation/native-adc10-pcb-oriented-20261017.epru')
ap.add_argument('--tag', default='orientation')
args=ap.parse_args()
after_path=args.source.resolve()
assert after_path.is_relative_to(ROOT.resolve())
assert args.tag.replace('-','').replace('_','').isalnum()
plan_path=ROOT/'output/analysis/adc10-passive-orientation-plan-20261017.json'
plan=json.loads(plan_path.read_text(encoding='utf8'))
a,b=parse(before_path),parse(after_path)
edits={e['componentId']:e for e in plan['edits']}
errors=[]
changes=[]
if a.keys()!=b.keys():
    errors.append('Record membership changed')
for key in a.keys() & b.keys():
    x,y=a[key],b[key]
    if x==y:
        continue
    fields={f for f in x.keys()|y.keys() if x.get(f,'__ABSENT__')!=y.get(f,'__ABSENT__')}
    if key[0]=='DOCHEAD' and fields<={'client','updateTime','version'}:
        continue
    if key[0]=='COMPONENT' and key[1] in edits:
        e=edits[key[1]]
        good=fields=={'angle'} and y['angle']%360==e['set']['rotation']%360 and x['x']==y['x']==e['set']['x'] and x['y']==y['y']==e['set']['y'] and x['attrs']==y['attrs']
    elif key[0]=='ATTR' and x.get('parentId') in edits:
        good=fields<={'x','y','angle'} and x.get('key')==y.get('key') and x.get('value')==y.get('value')
    else:
        good=False
    changes.append({'record':key,'fields':sorted(fields),'allowed':good})
    if not good:
        errors.append({'record':key,'fields':sorted(fields)})
counts=dict(Counter(c['record'][0] for c in changes))
if counts!={'COMPONENT':20,'ATTR':60}:
    errors.append({'unexpectedChangeCounts':counts})
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'passed':not errors,'sourceBeforeSha256':sha(before_path),'sourceAfterSha256':sha(after_path),'planSha256':sha(plan_path),'recordCount':len(b),'changeCounts':counts,'protectedRecordsExactExcludingSessionDochead':len(b)-len(changes)-1,'allComponentCentersAndIdentitiesExact':not errors,'noCopperHoleLayerRuleNetChanges':not errors,'angleNormalization':'Modulo 360; native reopen stores 270 degrees as -90 degrees with identical geometry','changes':changes,'manufacturingReady':False,'errors':errors}
path=ROOT/('output/analysis/adc10-passive-'+args.tag+'-audit-20261017.json')
path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='changes'}|{'report':str(path)},indent=2))
if errors:
    raise SystemExit(1)
