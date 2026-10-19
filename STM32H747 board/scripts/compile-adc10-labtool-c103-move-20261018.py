"""Offline bounded wrapper for the reviewed single C103 local-bypass move."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
p = HERE / 'routing/c103-only-placement-exact-operations-v6.json'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(p) == '429eb30d108c1101486ca8d1bea0bcaabf5fab438fba142935152f4d3b066236'
r = json.loads(p.read_text())
assert r['sourceSha256'] == '568ca754e9ff92d9df6cf5f96e3384811f9ad6038404410ce7ca4c843d80296b'
assert r['allOther106EntriesExact'] and r['originalDrillChanges'] == r['viaChanges'] == 0
assert len(r['operations']) == 1
o = r['operations'][0]
assert o['ref'] == 'C103' and o['uniqueId'] == 'd5e2941e244657a1'
before, after = o['beforeBody'], o['afterBody']
assert {k: v for k, v in before.items() if k not in ('x', 'y', 'angle')} == {k: v for k, v in after.items() if k not in ('x', 'y', 'angle')}
assert abs(after['x'] * .0254 - 22.4) < 1e-9 and abs(after['y'] * .0254 - 72) < 1e-9 and after['angle'] == 180
op = dict(type='COMPONENT', id=o['componentId'], action='place', ref=o['ref'],
          uniqueId=o['uniqueId'], beforeBody=before, afterBody=after,
          expectedWorldPads=o['expectedPads'])
result = dict(schema='labtool-C103-single-bypass-placement-v6-bounded-execution',
              PCBRequired='0ac2a19168000d8e', sourcePath=r['sourcePath'],
              sourceSha256=r['sourceSha256'], reviewedProposalPath=str(p),
              reviewedProposalSha256=sha(p), batches=[dict(stage='adjust_c1030', operations=[op])],
              nativeCalls=0, manufacturingReady=False)
out = HERE / 'pcb-c103-local-bypass-v6-execution.json'
out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
print(json.dumps(dict(path=str(out), sha256=sha(out))))
