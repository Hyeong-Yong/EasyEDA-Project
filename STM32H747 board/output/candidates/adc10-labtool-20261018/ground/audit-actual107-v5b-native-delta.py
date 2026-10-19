"""Read-only V4->V5b native two-passive rotation and 107-pose audit."""
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
G = runpy.run_path(str(ROOT / 'output/candidates/adc10-dc-buffer-20261017/independent-adc10-candidate-graph-audit.py'))
BEFORE = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v4_saved-20261018.epru'
AFTER = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru'
PLAN = HERE.parent / 'independent-pcb-placement-short-negative-commonpower-v5b-ref-flipped-proposal.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    assert sha(AFTER) == '568ca754e9ff92d9df6cf5f96e3384811f9ad6038404410ce7ca4c843d80296b'
    assert sha(PLAN) == '7121af6778ac0a04d674d8ac355122fb613cd4028201dd7ad18e6dae606387fe'
    before, after = G['parse'](BEFORE), G['parse'](AFTER)
    ba, br = G['attrs_for'](before)
    aa, ar = G['attrs_for'](after)
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    allowed = {br['R202'], br['C158']}
    errors, changes, poses = [], [], []
    for key in before.keys() | after.keys():
        if key[0] == 'DOCHEAD' or before.get(key) == after.get(key):
            continue
        old, new = before.get(key), after.get(key)
        fields = sorted(f for f in (old or {}).keys() | (new or {}).keys() if (old or {}).get(f) != (new or {}).get(f))
        ok = old is not None and new is not None and ((key[0] == 'COMPONENT' and key[1] in allowed and set(fields) <= {'angle'}) or
                   (key[0] == 'ATTR' and old.get('parentId') in allowed and set(fields) <= {'x', 'y', 'angle'}))
        change = {'record': key, 'fields': fields, 'allowed': ok}
        changes.append(change)
        if not ok:
            errors.append(change)
    for edit in plan['edits']:
        c = after['COMPONENT', edit['componentId']]
        ok = (c['x'] == round(edit['set']['x'], 4) and c['y'] == round(edit['set']['y'], 4) and
              (c['angle'] - edit['angle']) % 360 == 0 and c['layerId'] == edit['layerId'] and
              c['attrs']['Unique ID'] == edit['uniqueId'] and aa[edit['componentId']]['Footprint'] == edit['footprintUuid'])
        poses.append({'ref': edit['ref'], 'passed': ok, 'angle': c['angle'], 'xMil': c['x'], 'yMil': c['y']})
        if not ok:
            errors.append({'pose': poses[-1]})
    count = Counter(k[0] for k in after)
    if count['COMPONENT'] != 437 or count['PAD_NET'] != 1523 or count['FILL'] != 722 or len(poses) != 107 or before.keys() != after.keys():
        errors.append({'membershipOrCounts': dict(count)})
    if len([c for c in changes if c['record'][0] == 'COMPONENT']) != 2:
        errors.append({'notExactlyTwoComponentRotations': changes})
    report = {'schema': 'adc10-labtool-native107-v5b-two-passive-rotation-independent-audit-v1', 'passed': not errors,
              'before': str(BEFORE), 'beforeSha256': sha(BEFORE), 'after': str(AFTER), 'afterSha256': sha(AFTER),
              'placementSha256': sha(PLAN), 'components': count['COMPONENT'], 'all107ProposedPoses': poses,
              'exactAllowedBodyChanges': changes, 'R202Rotation': [before['COMPONENT', br['R202']]['angle'], after['COMPONENT', ar['R202']]['angle']],
              'C158Rotation': [before['COMPONENT', br['C158']]['angle'], after['COMPONENT', ar['C158']]['angle']],
              'all1523PadNetBodiesExact': all(before[k] == after[k] for k in before if k[0] == 'PAD_NET'),
              'all722FillBodiesExact': all(before[k] == after[k] for k in before if k[0] == 'FILL'),
              'allOtherCopperRulesDrillsOutlineJ18AndComponentMetadataExact': not errors,
              'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False, 'errors': errors}
    target = HERE / 'actual107-v5b-native-delta-audit.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': not errors, 'report': str(target), 'sha256': sha(target), 'changesByType': dict(Counter(c['record'][0] for c in changes)), 'errors': errors}))


if __name__ == '__main__':
    main()
