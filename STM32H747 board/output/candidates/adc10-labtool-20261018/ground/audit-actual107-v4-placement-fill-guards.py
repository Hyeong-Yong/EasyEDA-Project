"""Read-only actual107 V4 pose, identity, pad-net and FILL guard audit."""
import hashlib
import json
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
G = runpy.run_path(str(ROOT / 'output/candidates/adc10-dc-buffer-20261017/independent-adc10-candidate-graph-audit.py'))
BASE = ROOT / 'output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru'
SOURCE = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v4_saved-20261018.epru'
PLAN = HERE.parent / 'independent-pcb-placement-short-negative-commonpower-v4-proposal.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    a, b = G['parse'](BASE), G['parse'](SOURCE)
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    errors = []
    poses = []
    for edit in plan['edits']:
        cid = edit['componentId']
        c, old = b['COMPONENT', cid], a['COMPONENT', cid]
        diffs = {f: [c[f], round(edit['set'][f], 4)] for f in ('x', 'y') if c[f] != round(edit['set'][f], 4)}
        ok = not diffs and (c['angle'] - edit['angle']) % 360 == 0 and c['layerId'] == edit['layerId'] and c['attrs'] == old['attrs']
        poses.append({'ref': edit['ref'], 'componentId': cid, 'uniqueId': c['attrs']['Unique ID'], 'passed': ok,
                      'xMil': c['x'], 'yMil': c['y'], 'angle': c['angle'], 'layerId': c['layerId'], 'coordinateDifferences': diffs})
        if not ok:
            errors.append({'poseOrAttrs': poses[-1]})
    fill_diffs = [k for k in a.keys() | b.keys() if k[0] == 'FILL' and a.get(k) != b.get(k)]
    pad_diffs = [k for k in a.keys() | b.keys() if k[0] == 'PAD_NET' and a.get(k) != b.get(k)]
    components = {k: body for k, body in b.items() if k[0] == 'COMPONENT'}
    a_components = {k: body for k, body in a.items() if k[0] == 'COMPONENT'}
    attrs_diffs = [k for k in components if components[k]['attrs'] != a_components[k]['attrs']]
    if fill_diffs or pad_diffs or attrs_diffs or components.keys() != a_components.keys() or len(poses) != 107 or len(components) != 437:
        errors.append({'scope': {'fillChanges': fill_diffs, 'padNetChanges': pad_diffs, 'componentAttrsChanges': attrs_diffs,
                                 'componentCount': len(components), 'targetPoses': len(poses)}})
    report = {'schema': 'adc10-labtool-actual107-v4-placement-and-fill-guards-readonly-audit-v1', 'passed': not errors,
              'source': str(SOURCE), 'sourceSha256': sha(SOURCE), 'baselineSha256': sha(BASE), 'placementSha256': sha(PLAN),
              'components': len(components), 'targetPoses': poses, 'all107AtNative4DecimalMilProposedPose': all(p['passed'] for p in poses),
              'allComponentAttrsUnchangedVsVerifiedEco': not attrs_diffs, 'allPadNetBodiesExactVsVerifiedEco': not pad_diffs,
              'allExistingFillBodiesExactVsVerifiedEco': not fill_diffs, 'fillCount': sum(k[0] == 'FILL' for k in b),
              'nativeApiCalls': 0, 'nativeModified': False, 'manufacturingApproved': False, 'errors': errors}
    target = HERE / 'actual107-v4-placement-and-fill-guards-audit.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': not errors, 'report': str(target), 'sha256': sha(target), 'sourceSha256': sha(SOURCE), 'errors': errors}))


if __name__ == '__main__':
    main()
