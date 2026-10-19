"""Explicit frozen-list-only offline removal variant; no automatic cleanup."""
import argparse
import copy
import hashlib
import json
import runpy
from collections import Counter
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
A = runpy.run_path(str(HERE / 'make-approved58-local-removal-variant.py'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--manifest-sha', required=True)
    ap.add_argument('--graph', type=Path, required=True)
    ap.add_argument('--approved-graph-sha', required=True)
    ap.add_argument('--approved-count', type=int, required=True)
    ap.add_argument('--approval-review', type=Path)
    ap.add_argument('--approval-review-sha')
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    assert sha(args.manifest) == args.manifest_sha
    assert sha(args.graph) == args.approved_graph_sha
    base = json.loads(args.manifest.read_text(encoding='utf8'))
    graph = json.loads(args.graph.read_text(encoding='utf8'))
    assert graph['manifestSha256'] == args.manifest_sha
    approved = [r for r in graph['lobesSortedByArea'] if not r['reachesActualMCUVssA17'] and r['noSameLayerCopperContactDetected']]
    assert len(approved) == args.approved_count
    assert all(not r['allSameLayerPhysicalCopperContacts'] and not r['containsGroundPadContact'] and not r['containsGroundViaContact'] and r['separatedOnlyByReviewedLocalCuts'] for r in approved)
    keys = {r['key'] for r in approved}
    review = None
    if args.approval_review:
        assert sha(args.approval_review) == args.approval_review_sha
        review = json.loads(args.approval_review.read_text(encoding='utf8'))
        assert review['manifestSha256'] == args.manifest_sha and review['groundGraphSha256'] == args.approved_graph_sha
        assert review['exactKeysSorted'] == sorted(keys) and review['candidateCount'] == args.approved_count
        assert review['allCandidateCopperPadViaContactsZero'] and review['allCandidateInvalidSourceBoundsOverlapZero']
        assert base['passed'] and graph['loadConnectivityPassed']
    lobes = {l['key']: l for l in base['fillCreateOperations']}
    assert keys <= lobes.keys()
    removed = [lobes[r['key']] for r in approved]
    retained = [l for l in base['fillCreateOperations'] if l['key'] not in keys]
    region = A['integer_region']
    group_proofs = []
    for layer, net in sorted({(l['layerId'], l['net']) for l in removed}):
        after = [o['afterPathsExplicitlyClosedForApi'] for o in base['fillModifyOperations'] if (o['layerId'], o['net']) == (layer, net)]
        old_group = [l for l in lobes.values() if (l['layerId'], l['net']) == (layer, net)]
        kept_group = [l for l in retained if (l['layerId'], l['net']) == (layer, net)]
        removed_group = [l for l in removed if (l['layerId'], l['net']) == (layer, net)]
        full = P['signed_region']([p for s in after + [l['afterPathsExplicitlyClosedForApi'] for l in old_group] for p in region(s)])
        final = P['signed_region']([p for s in after + [l['afterPathsExplicitlyClosedForApi'] for l in kept_group] for p in region(s)])
        mask = P['signed_region']([p for l in removed_group for p in region(l['afterPathsExplicitlyClosedForApi'])])
        wanted = P['difference'](full, mask)
        extra = P['difference'](full, final)
        group_proofs.append({'layerId': layer, 'net': net,
                             'xor': P['area'](P['difference'](wanted, final)) + P['area'](P['difference'](final, wanted)),
                             'added': P['area'](P['difference'](final, full)),
                             'outside': P['area'](P['difference'](extra, mask)),
                             'missing': P['area'](P['difference'](mask, extra)),
                             'physicalPenEnvelopeRemovalUnionAreaMm2': P['unary_union']([P['geom'](l['afterPathsExplicitlyClosedForApi']).buffer(l['widthMil'] * P['MM'] / 2, resolution=64) for l in removed_group]).area})
    xor, added, outside, missing = (sum(p[k] for p in group_proofs) for k in ('xor', 'added', 'outside', 'missing'))
    assert xor == added == outside == missing == 0
    exact_area = Decimal(sum(A['twice_solid_area'](l['afterPathsExplicitlyClosedForApi']) for l in removed)) / Decimal(2 * P['SCALE'] ** 2)
    variant = copy.deepcopy(base)
    variant['schema'] = 'adc10-labtool-explicit-frozen-isolated-lobe-removal-variant-v1'
    variant['preservationVariantPath'] = str(args.manifest.resolve())
    variant['preservationVariantSha256'] = args.manifest_sha
    variant['fillCreateOperations'] = retained
    variant['preservedLobeCount'] = len(retained)
    for op in variant['fillModifyOperations']:
        parent_removed = [l for l in removed if l['sourceParentPrimitiveId'] == op['primitiveId']]
        parent_area = Decimal(sum(A['twice_solid_area'](l['afterPathsExplicitlyClosedForApi']) for l in parent_removed)) / Decimal(2 * P['SCALE'] ** 2)
        op['preservedCopperLobes'] = [l for l in op['preservedCopperLobes'] if l['key'] not in keys]
        op['newCopperRemovalAreaMm2'] += float(parent_area)
        op['explicitAdditionalRemovalLobeKeys'] = [l['key'] for l in parent_removed]
        op['explicitAdditionalRemovalAreaMm2ExactDecimal'] = str(parent_area)
    for audit in variant['fillAudits']:
        if audit['status'] == 'PLANNED_BOUNDED_LOCAL_CUT':
            audit['preservedLocalLobes'] = sum(l['sourceParentPrimitiveId'] == audit['id'] for l in retained)
    variant['lobeDirectContactCounts'] = dict(Counter('NO_DIRECT_CONTACT' if l['noDirectPadOrViaContactDetected'] else 'DIRECT_PAD_OR_VIA_CONTACT' for l in retained))
    retained_graph = [r for r in graph['lobesSortedByArea'] if r['key'] not in keys]
    proof = {'explicitAuthorizationScope': 'Parent explicitly approved only this graph SHA and exact isolated-lobe count. This is not an automatic cleanup policy and cannot be reused for a later route/placement/antipad variant without fresh review.',
             'graphPath': str(args.graph.resolve()), 'graphSha256': args.approved_graph_sha,
             'removedNewLobeCount': len(removed), 'retainedNewLobeCount': len(retained),
             'nominalAdditionalRemovalAreaMm2ExactDecimal': str(exact_area), 'nominalAdditionalRemovalAreaMm2': float(exact_area),
             'physicalPenEnvelopeAdditionalRemovalAreaMm2': sum(P['geom'](l['afterPathsExplicitlyClosedForApi']).buffer(l['widthMil'] * P['MM'] / 2, resolution=64).area for l in removed),
             'physicalPenEnvelopeAdditionalRemovalUnionAreaMm2': sum(p['physicalPenEnvelopeRemovalUnionAreaMm2'] for p in group_proofs),
             'additionalCopperAreaMm2': added, 'extraRemovalOutsideApprovedMasksMm2': outside,
             'perLayerAndNetDifferenceProofs': group_proofs,
             'approvedMaskNotRemovedAreaMm2': missing, 'symmetricDifferenceFromPreservationMinusApprovedMasksMm2': xor,
             'allBeforeBodyAndParentApiPathsUnchanged': all(a['beforeBody'] == b['beforeBody'] and a['afterPathsExplicitlyClosedForApi'] == b['afterPathsExplicitlyClosedForApi'] for a, b in zip(base['fillModifyOperations'], variant['fillModifyOperations'])),
             'allRetainedGroundLobesMcuAnchoredInFrozenGraph': all(r['reachesActualMCUVssA17'] for r in retained_graph),
             'allTargetGroundPadsMcuAnchoredInFrozenGraph': not graph.get('unanchoredTargetGroundPhysicalPads'),
             'removedLobesSortedByArea': [{**r, 'exactRemovalPathsExplicitlyClosedForApi': lobes[r['key']]['afterPathsExplicitlyClosedForApi']} for r in approved],
             'retainedGroundLobeGraphEvidence': retained_graph, 'existingNativeFillPrimitivesDeleted': 0,
             'implementation': 'Omit only these proposed new FILL creations. Keep parent FILL path changes identical to the reviewed all-lobe preservation variant.',
             'nativeCalls': 0, 'nativeImplemented': False, 'manufacturingApproved': False}
    if review:
        assert float(exact_area) == review['nominalIntegerUnionAreaMm2']
        proof['explicitReviewPath'] = str(args.approval_review.resolve())
        proof['explicitReviewSha256'] = args.approval_review_sha
        proof['approvedExactKeysSha256'] = review['exactKeysSortedSha256']
        proof['invalidSourceExclusionSha256'] = review['invalidExclusionSha256']
        proof['maximumNominalRemovalLobeAreaMm2'] = review['maximumNominalAreaMm2']
        proof['mandatoryLargeLobesPreserved'] = review['mandatoryPreservedLargeLobes']
    variant['explicitlyApprovedAdditionalLocalRemoval'] = proof
    variant['pendingMandatoryGates'] = ['Final integrated routing and these exact omission keys are frozen; any subsequent geometry/input change requires fresh review, not automatic cleanup reuse.', 'Native geometry readback, all physical nets, full unchanged-rule DRC, save/reopen and CAM remain mandatory.']
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(variant, indent=2) + '\n', encoding='utf8')
    audit = {k: v for k, v in proof.items() if k != 'removedLobesSortedByArea'}
    audit.update({'schema': variant['schema'], 'passedOfflineDifferenceProof': True, 'manifest': str(target), 'manifestSha256': sha(target),
                  'preservationVariantSha256': args.manifest_sha, 'sourceSha256': base['sourceSha256'],
                  'removedSummarySortedByArea': approved})
    audit_path = HERE / (args.output_prefix + '-audit.json')
    audit_path.write_text(json.dumps(audit, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'manifest': str(target), 'sha256': sha(target), 'removed': len(removed), 'retained': len(retained),
                      'nominalAdditionalRemovalAreaMm2Exact': str(exact_area), 'xor': xor, 'added': added, 'outside': outside}))


if __name__ == '__main__':
    main()
