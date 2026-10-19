"""Independent full-source C103-only move and all107 actual pose checks."""
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
G = runpy.run_path(str(ROOT / 'output/candidates/adc10-dc-buffer-20261017/independent-adc10-candidate-graph-audit.py'))
BEFORE = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru'
AFTER = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v6_saved-20261018.epru'
PLAN = HERE.parent / 'independent-pcb-placement-v6-c103-local-bypass-proposal.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(AFTER) == 'a5d126649aa3e03dd0b74baa5e412d03c2a6ae93466b0fc4e04010f37232e9f9'
    assert sha(PLAN) == '2cbb87c1ace266d67fdbc90a15807a8d8316773e719cd31108b2cd33fa6ddd43'
    before, after = G['parse'](BEFORE), G['parse'](AFTER)
    ba, br = G['attrs_for'](before)
    aa, ar = G['attrs_for'](after)
    cid = br['C103']
    assert cid == ar['C103']
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    errors, changes, poses = [], [], []
    for key in before.keys() | after.keys():
        if key[0] in {'DOCHEAD', 'CANVAS'} or before.get(key) == after.get(key):
            continue
        old, new = before.get(key), after.get(key)
        fields = sorted(f for f in (old or {}).keys() | (new or {}).keys() if (old or {}).get(f) != (new or {}).get(f))
        ok = old is not None and new is not None and ((key == ('COMPONENT', cid) and set(fields) <= {'x', 'y', 'angle'}) or
                (key[0] == 'ATTR' and old.get('parentId') == cid and new.get('parentId') == cid and set(fields) <= {'x', 'y', 'angle'}))
        changes.append({'record': key, 'fields': fields, 'allowed': ok})
        if not ok:
            errors.append(changes[-1])
    for edit in plan['edits']:
        c = after['COMPONENT', edit['componentId']]
        ok = (c['x'] == round(edit['set']['x'], 4) and c['y'] == round(edit['set']['y'], 4) and
              (c['angle'] - edit['angle']) % 360 == 0 and c['layerId'] == edit['layerId'] and
              c['attrs']['Unique ID'] == edit['uniqueId'] and aa[edit['componentId']]['Footprint'] == edit['footprintUuid'])
        poses.append({'ref': edit['ref'], 'passed': ok, 'angle': c['angle'], 'xMil': c['x'], 'yMil': c['y']})
        if not ok:
            errors.append({'pose': poses[-1]})
    counts = Counter(k[0] for k in after)
    design_keys_before = {k for k in before if k[0] not in {'DOCHEAD', 'CANVAS'}}
    design_keys_after = {k for k in after if k[0] not in {'DOCHEAD', 'CANVAS'}}
    if counts['COMPONENT'] != 437 or counts['PAD_NET'] != 1523 or counts['FILL'] != 722 or len(poses) != 107 or design_keys_before != design_keys_after:
        errors.append({'membershipOrCounts': dict(counts)})
    if Counter(c['record'][0] for c in changes) != {'COMPONENT': 1, 'ATTR': 3}:
        errors.append({'notExactlyC103AndThreeDisplayAttrs': changes})
    c103 = after['COMPONENT', cid]
    if c103['x'] != round(22.4 / .0254, 4) or c103['y'] != round(72 / .0254, 4) or c103['angle'] != 180:
        errors.append({'wrongC103Pose': c103})
    report = {'schema': 'adc10-labtool-native107-v6-c103-only-pose-independent-audit-v1', 'passed': not errors,
              'before': str(BEFORE), 'beforeSha256': sha(BEFORE), 'after': str(AFTER), 'afterSha256': sha(AFTER),
              'placementSha256': sha(PLAN), 'components': counts['COMPONENT'], 'all107ProposedPoses': poses,
              'exactAllowedBodyChanges': changes, 'C103UniqueIdAndFootprintAndValueExact': not errors,
              'all1523PadNetBodiesExact': all(before[k] == after[k] for k in before if k[0] == 'PAD_NET'),
              'all722FillBodiesExact': all(before[k] == after[k] for k in before if k[0] == 'FILL'),
              'allOtherCopperRulesDrillsOutlineJ18AndComponentMetadataExact': not errors,
              'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False, 'errors': errors}
    target = HERE / 'actual107-v6-c103-native-delta-audit.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': not errors, 'report': str(target), 'sha256': sha(target), 'changesByType': dict(Counter(c['record'][0] for c in changes)), 'errors': errors}))


if __name__ == '__main__':
    main()
