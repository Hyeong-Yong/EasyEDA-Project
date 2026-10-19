"""Offline identity rebase after proven exact native collinear consolidation."""
import copy
import hashlib
import json
import runpy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'output/candidates/adc10-labtool-20261018'
QA=runpy.run_path(str(ROOT/'scripts/audit-adc10-labtool-isolation-20261018.py'))
source=ROOT/'output/validation/native-adc10-pcb-labtool_isolate_2-20261018.epru'
original=HERE/'pcb-isolation-placement-execution-v1.json'
audit=json.loads((HERE/'independent-isolation-isolate_2-audit.json').read_text())
assert audit['passed'] and audit['exactIntegerGridLineUnionWithMetadataPreserved']
assert audit['sourceSha256']==QA['sha'](source)
plan=json.loads(original.read_text());rows=QA['read'](source)
oldops=[o for b in plan['batches'] for o in b['operations'] if o['action']=='rename']
assert len(oldops)==41
other=[o for o in oldops if o['beforeBody']['netName']!='ADC_BIAS_2V5']
bias=[o for o in oldops if o['beforeBody']['netName']=='ADC_BIAS_2V5']
assert len(other)==30 and len(bias)==11
ops=[]
for o in other:
    assert rows['LINE',o['id']]==o['beforeBody']
    ops.append(copy.deepcopy(o))
actualbias={k:b for k,b in rows.items() if k[0]=='LINE' and b.get('netName')=='ADC_BIAS_2V5'}
expectedbias={('LINE',o['id']):o['beforeBody'] for o in bias}
assert QA['exact_line_union'](actualbias)==QA['exact_line_union'](expectedbias)
assert len(actualbias)==5
for (_,rid),b in actualbias.items():
    after=copy.deepcopy(b);after['netName']='ADC_OFFSET_0V97'
    ops.append({'type':'LINE','id':rid,'action':'rename','beforeBody':b,'afterBody':after,
                'reason':'Same exact offset trunk centerline union, native collinear identity consolidation only'})
out={'schema':'stm32h747-labtool-rebased-net-rename-execution-20261018-v2',
     'PCBRequired':'0ac2a19168000d8e','sourcePath':str(source),'sourceSha256':QA['sha'](source),
     'originalPlanPath':str(original),'originalPlanSha256':QA['sha'](original),
     'batches':[{'stage':f'rename_r{i//20}','operations':ops[i:i+20]} for i in range(0,len(ops),20)],
     'oldPlannedRenameCount':41,'rebasedNativeRenameCount':35,
     'exactRetainedBiasCopperUnion':True,'nativeApiCalls':0,'manufacturingReady':False}
path=HERE/'pcb-rename-rebased-v2.json'
path.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
print(json.dumps({'path':str(path),'sha256':QA['sha'](path),'stages':[b['stage'] for b in out['batches']]}))
