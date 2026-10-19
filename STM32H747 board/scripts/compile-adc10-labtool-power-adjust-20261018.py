"""Offline wrapper of the two reviewed V4 placement corrections only."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'output/candidates/adc10-labtool-20261018'
p=HERE/'routing/commonpower-v4-two-component-actual-operations.json'
assert hashlib.sha256(p.read_bytes()).hexdigest()=='3e6a17917f4bc09fd677bd4457fab3ce5f7fe250f3654c0b800d0211574b8258'
r=json.loads(p.read_text());assert {o['ref'] for o in r['operations']}=={'C152','D20'}
ops=[]
for o in r['operations']:
    ops.append({'type':'COMPONENT','id':o['id'],'action':'place','ref':o['ref'],
                'uniqueId':o['beforeBody']['attrs']['Unique ID'],
                'beforeBody':o['beforeBody'],'afterBody':o['expectedAfterRound4Mil']})
out={'schema':'labtool-commonpower-v4-bounded-api-batch','PCBRequired':'0ac2a19168000d8e',
     'sourcePath':r['sourcePath'],'sourceSha256':r['sourceSha256'],
     'reviewedProposalPath':str(p),'reviewedProposalSha256':hashlib.sha256(p.read_bytes()).hexdigest(),
     'batches':[{'stage':'adjust_power0','operations':ops}],
     'nativeCalls':0,'manufacturingReady':False}
target=HERE/'pcb-commonpower-adjust-v4-execution.json'
target.write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
