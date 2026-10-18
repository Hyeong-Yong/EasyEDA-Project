"""Materialized checkpoint scope audit for the ADC10 in-progress PCB handoff."""
from pathlib import Path
import hashlib
import json
import runpy

ROOT=Path(__file__).resolve().parents[1]
read=runpy.run_path(str(ROOT/'output/candidates/adc-inline-wiring/audit-inline-final-project.py'))['read_snapshot']
base=ROOT/'output/checkpoints/STM32H747_before_adc10_20261017.epro2'
eco=ROOT/'output/checkpoints/STM32H747_adc10_pcb_eco_wip_20261017.epro2'
final=ROOT/'output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2'
a,_=read(base)
e,_=read(eco)
b,_=read(final)
page=('SCH_PAGE','a07bf8e4331877a8')
pcb=('PCB','0ac2a19168000d8e')
errors=[]
if a.keys()!=b.keys() or e.keys()!=b.keys():
    errors.append('Document membership changed')
changed=[k for k in a.keys() & b.keys() if a[k]!=b[k]]
eco_changed=[k for k in e.keys() & b.keys() if e[k]!=b[k]]
if set(changed)!={page,pcb}:
    errors.append({'unexpectedOverallChanges':changed})
if eco_changed!=[pcb]:
    errors.append({'unexpectedOrientationCheckpointChanges':eco_changed})
plan=json.loads((ROOT/'output/analysis/adc10-passive-orientation-plan-20261017.json').read_text(encoding='utf8'))
ids={p['componentId']:p for p in plan['edits']}
body=lambda records:{k:r[1] for k,r in records.items() if k[0]!='DOCHEAD'}
old,new=body(e[pcb]),body(b[pcb])
if old.keys()!=new.keys():
    errors.append('PCB record membership changed during orientation')
diffs=[]
for k in old.keys() & new.keys():
    x,y=old[k],new[k]
    if x==y:
        continue
    fields={f for f in x.keys()|y.keys() if x.get(f,'__ABSENT__')!=y.get(f,'__ABSENT__')}
    good=False
    if k[0]=='COMPONENT' and k[1] in ids:
        good=fields=={'angle'} and y['angle']%360==ids[k[1]]['set']['rotation']%360
    elif k[0]=='ATTR' and x.get('parentId') in ids:
        good=fields<={'x','y','angle'}
    diffs.append({'record':k,'fields':sorted(fields),'allowed':good})
    if not good:
        errors.append(diffs[-1])
if len(diffs)!=80:
    errors.append({'unexpectedOrientationRecordDelta':len(diffs)})
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
report={'passed':not errors,'finalCheckpoint':str(final),'finalCheckpointSha256':sha(final),'beforeCheckpointSha256':sha(base),'ecoCheckpointSha256':sha(eco),'documentCount':len(b),'overallChangedDocuments':changed,'nonTargetDocumentsExactIncludingHeaders':len(b)-2,'orientationChangedDocuments':eco_changed,'orientationOnly80RecordsChanged':len(diffs)==80,'newSchematicAndAllLibrariesUnchangedDuringPcbOrientation':all(e[k]==b[k] for k in e if k!=pcb),'manufacturingReady':False,'openInputRawZeroImplemented':False,'changes':diffs,'errors':errors}
path=ROOT/'output/analysis/adc10-final-wip-checkpoint-scope-20261017.json'
path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='changes'}|{'report':str(path)},indent=2))
if errors:
    raise SystemExit(1)
