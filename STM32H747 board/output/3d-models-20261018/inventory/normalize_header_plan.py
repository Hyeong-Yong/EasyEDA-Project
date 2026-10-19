"""Add the native apply helper transformMIL alias without changing numbers."""
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
OUT=HERE.parent
source=OUT/'headers-native-final-apply-plan.json'
plan=json.loads(source.read_text(encoding='utf-8'))
for e in plan['entries']:
    assert isinstance(e['transform'],str) and len(e['transform'].split(','))==9
    e['transformMIL']=e['transform']
    e['transform_values_mil_degrees']=[float(x) for x in e['transform'].split(',')]
plan['normalized_from']={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                          'change':'Add transformMIL alias identical to transform; parsed numeric array is diagnostic only. All existing fields and strings unchanged.'}
target=OUT/'headers-native-final-apply-plan-normalized.json'
assert not target.exists()
target.write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'entries':len(plan['entries'])}))
