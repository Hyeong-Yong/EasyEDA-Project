"""Offline wrapper for two independently screened, same-centre passive flips."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
p = HERE / 'routing/reference-two-rotation-exact-operations-v5b.json'
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(p) == '00e117ead6bb4f93d8a6ef3cfeb0a07e57d3f8b91125e2e4062c6f89a75c201a'
r = json.loads(p.read_text())
assert r['allOther105EntriesExact'] and r['originalDrillChanges'] == r['viaChanges'] == 0
assert {o['ref'] for o in r['operations']} == {'R202', 'C158'}
ops = []
for o in r['operations']:
    assert o['physicalPadsUnionAndCourtUnchanged']
    before, after = o['beforeBody'], o['afterBody']
    assert {k: v for k, v in before.items() if k != 'angle'} == {k: v for k, v in after.items() if k != 'angle'}
    assert (after['angle'] - before['angle']) % 360 == 180
    ops.append(dict(type='COMPONENT', id=o['componentId'], action='place',
                    ref=o['ref'], uniqueId=o['uniqueId'], beforeBody=before,
                    afterBody=after, expectedWorldPads=o['expectedPads']))
result = dict(schema='labtool-reference-two-same-centre-rotations-v5b',
              PCBRequired='0ac2a19168000d8e', sourcePath=r['sourcePath'],
              sourceSha256=r['sourceSha256'], reviewedProposalPath=str(p),
              reviewedProposalSha256=digest(p),
              batches=[dict(stage='adjust_ref0', operations=ops)],
              nativeCalls=0, manufacturingReady=False)
out = HERE / 'pcb-reference-rotations-v5b-execution.json'
out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
print(json.dumps(dict(path=str(out), sha256=digest(out))))
