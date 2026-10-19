"""Offline variant: omit only the 58 explicitly approved, isolated new lobes.

The frozen all-lobe preservation manifest and its ground audit remain intact.
No native FILL, project, UI, or API is modified.
"""
import copy
import hashlib
import json
import runpy
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
BASE = HERE / 'local-static-fill-clearance-short-negative-row290-v2.json'
GRAPH = HERE / 'local-ground-lobe-connectivity-short-negative-row290-v2.json'
BASE_SHA = '0a6abe494b41779b4a8b2f789c2e663f3e48e5029b316528783423f5508f427b'
GRAPH_SHA = 'd25acd2e8fc97dbf639ecdfe12496369775eb4ad7f6f746fc8b8c3e79bf8c475'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def integer_region(paths):
    return P['signed_original']([P['ip'](P['ring_points'](r)) for r in paths])


def twice_ring_area(ring):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])))


def twice_solid_area(paths):
    points = [P['ip'](P['ring_points'](r)) for r in paths]
    return twice_ring_area(points[0]) - sum(twice_ring_area(r) for r in points[1:])


def main():
    assert sha(BASE) == BASE_SHA
    assert sha(GRAPH) == GRAPH_SHA
    plan = json.loads(BASE.read_text(encoding='utf8'))
    graph = json.loads(GRAPH.read_text(encoding='utf8'))
    assert graph['manifestSha256'] == BASE_SHA
    approved = [r for r in graph['lobesSortedByArea'] if r['noSameLayerCopperContactDetected'] and not r['reachesActualMCUVssA17']]
    assert len(approved) == 58
    keys = {r['key'] for r in approved}
    assert all(not r['containsGroundPadContact'] and not r['containsGroundViaContact'] and
               r['separatedOnlyByReviewedLocalCuts'] and not r['allSameLayerPhysicalCopperContacts'] for r in approved)
    original_lobes = {l['key']: l for l in plan['fillCreateOperations']}
    assert len(original_lobes) == 71 and keys <= original_lobes.keys()
    removed = [original_lobes[r['key']] for r in approved]
    retained = [l for l in plan['fillCreateOperations'] if l['key'] not in keys]
    assert len(retained) == 13
    native_after = [o['afterPathsExplicitlyClosedForApi'] for o in plan['fillModifyOperations']]
    original_region = [p for o in plan['fillModifyOperations'] for p in integer_region(o['beforeBody']['path'])]
    full = P['signed_region']([p for s in native_after + [l['afterPathsExplicitlyClosedForApi'] for l in original_lobes.values()] for p in integer_region(s)])
    final = P['signed_region']([p for s in native_after + [l['afterPathsExplicitlyClosedForApi'] for l in retained] for p in integer_region(s)])
    mask = P['signed_region']([p for l in removed for p in integer_region(l['afterPathsExplicitlyClosedForApi'])])
    expected = P['difference'](full, mask)
    extra = P['difference'](full, final)
    symmetric_difference = P['area'](P['difference'](expected, final)) + P['area'](P['difference'](final, expected))
    added = P['area'](P['difference'](final, full))
    added_vs_original = P['area'](P['difference'](final, original_region))
    extra_outside_mask = P['area'](P['difference'](extra, mask))
    missing_removal = P['area'](P['difference'](mask, extra))
    assert symmetric_difference == added == added_vs_original == extra_outside_mask == missing_removal == 0
    twice_area = sum(twice_solid_area(l['afterPathsExplicitlyClosedForApi']) for l in removed)
    exact_area = Decimal(twice_area) / Decimal(2 * P['SCALE'] ** 2)
    physical_area = sum(P['geom'](l['afterPathsExplicitlyClosedForApi']).buffer(l['widthMil'] * P['MM'] / 2).area for l in removed)
    before_ops_sha = [P['digest'](o['beforeBody']) for o in plan['fillModifyOperations']]
    variant = copy.deepcopy(plan)
    variant['schema'] = 'adc10-labtool-explicitly-approved58-local-removal-static-fill-variant-v1'
    variant['preservationVariantPath'] = str(BASE)
    variant['preservationVariantSha256'] = BASE_SHA
    variant['frozenPhysicalGroundGraphPath'] = str(GRAPH)
    variant['frozenPhysicalGroundGraphSha256'] = GRAPH_SHA
    variant['fillCreateOperations'] = retained
    variant['preservedLobeCount'] = 13
    for op in variant['fillModifyOperations']:
        op['preservedCopperLobes'] = [l for l in op['preservedCopperLobes'] if l['key'] not in keys]
        op['newCopperRemovalAreaMm2'] += float(exact_area)
        op['localCutSymmetricDifferenceAreaMm2'] = symmetric_difference
        op['explicitAdditionalRemovalLobeKeys'] = sorted(keys)
    assert before_ops_sha == [P['digest'](o['beforeBody']) for o in variant['fillModifyOperations']]
    variant['approvedAdditionalLocalRemoval'] = {
        'authorizationScope': 'Parent explicitly approved omitting only the 58 frozen d25acd report lobes with zero same-layer copper/pad/via contact and no MCU-VSS anchor. Any later route variant requires a fresh list and separate review; no broad or automatic island deletion.',
        'implementation': 'Do not create these 58 new FILL lobes; original FILL modifications are identical to the preservation variant. No existing FILL primitive is deleted.',
        'removedNewLobeCount': 58, 'retainedNewLobeCount': 13,
        'nominalExtraRemovalAreaMm2ExactDecimal': str(exact_area),
        'nominalExtraRemovalIntegerTwiceAreaNm2': twice_area,
        'nominalExtraRemovalAreaMm2': float(exact_area),
        'physicalPenEnvelopeExtraRemovalAreaMm2': physical_area,
        'physicalPenQualification': 'Nominal contour area is the exact requested 17.3328926 mm2 rounded value. Native 0.2 mil pen adds the separately reported physical envelope; the frozen DC graph established zero contact for every full physical envelope.',
        'copperAdditionAreaVsPreservationVariantMm2': added,
        'copperAdditionAreaVsOriginalMm2': added_vs_original,
        'symmetricDifferenceFromPreservationMinusApprovedMasksMm2': symmetric_difference,
        'extraRemovalOutsideApprovedMasksMm2': extra_outside_mask,
        'approvedMaskNotRemovedAreaMm2': missing_removal,
        'allExistingTargetFILLBeforeBodiesAndPathsUnchangedVsPreservationVariant': True,
        'fourInvalidTopInputFillsRemainExactAndUnmodified': variant['unmodifiedInvalidInputFills'],
        'removedLobesSortedByArea': [{**r, 'exactRemovalPathsExplicitlyClosedForApi': original_lobes[r['key']]['afterPathsExplicitlyClosedForApi'],
                                     'exactNominalAreaMm2Decimal': str(Decimal(twice_solid_area(original_lobes[r['key']]['afterPathsExplicitlyClosedForApi'])) / Decimal(2 * P['SCALE'] ** 2))} for r in approved],
        'otherUnanchoredLoadLobesNotRemoved': [r for r in graph['lobesSortedByArea'] if r['key'] not in keys and not r['reachesActualMCUVssA17']],
        'nativeImplemented': False}
    variant['lobeDirectContactCounts'] = dict(__import__('collections').Counter('NO_DIRECT_CONTACT' if l['noDirectPadOrViaContactDetected'] else 'DIRECT_PAD_OR_VIA_CONTACT' for l in retained))
    variant['pendingMandatoryGates'] = ['New GND ports/stitches and physical MCU-VSS graph for every retained load lobe and all target ground pads.', 'Exact native readback and unchanged-rule strict DRC; common power/ref routing is still incomplete.', 'Any new final route/via/common placement requires rebase and independently reviewed removal list, not replay of this frozen list blindly.']
    target = HERE / 'local-static-fill-clearance-short-negative-row290-v2-approved58-removal.json'
    target.write_text(json.dumps(variant, indent=2) + '\n', encoding='utf8')
    audit = {k: v for k, v in variant['approvedAdditionalLocalRemoval'].items() if k not in {'removedLobesSortedByArea'}}
    audit.update({'schema': variant['schema'], 'passedOfflineGeometry': True, 'manifest': str(target), 'manifestSha256': sha(target),
                  'sourceSha256': variant['sourceSha256'], 'placementSha256': variant['placementSha256'],
                  'routes': variant['routes'], 'preservationVariantSha256': BASE_SHA, 'frozenGroundAuditSha256': GRAPH_SHA,
                  'removed58SummarySortedByArea': [{k: v for k, v in r.items() if k != 'allSameLayerPhysicalCopperContacts'} for r in approved],
                  'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False})
    audit_path = HERE / 'local-static-fill-clearance-short-negative-row290-v2-approved58-removal-audit.json'
    audit_path.write_text(json.dumps(audit, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'manifest': str(target), 'sha256': sha(target), 'nominalExtraRemovalMm2Exact': str(exact_area),
                      'removed': 58, 'retained': 13, 'copperAddition': added, 'xor': symmetric_difference}))


if __name__ == '__main__':
    main()
