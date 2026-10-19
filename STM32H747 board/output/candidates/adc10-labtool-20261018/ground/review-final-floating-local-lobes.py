"""Explicit final no-contact list for parent review; authorizes no removal."""
import argparse
import json
import runpy
from collections import defaultdict
from pathlib import Path
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--ground-graph', type=Path, required=True)
    ap.add_argument('--power-graph', type=Path, required=True)
    ap.add_argument('--invalid-exclusion', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    plan = json.loads(args.manifest.read_text(encoding='utf8'))
    ground = json.loads(args.ground_graph.read_text(encoding='utf8'))
    power = json.loads(args.power_graph.read_text(encoding='utf8'))
    invalid = json.loads(args.invalid_exclusion.read_text(encoding='utf8'))
    frozen = P['sha'](args.manifest)
    assert plan['passed'] and ground['loadConnectivityPassed'] and power['loadConnectivityPassed']
    assert ground['manifestSha256'] == power['manifestSha256'] == invalid['manifestSha256'] == frozen
    assert invalid['graphSha256'] == P['sha'](args.ground_graph) and invalid['passed']
    assert not power['lobesSortedByArea'], 'Any selected power-net lobe requires separate review before combining cleanup'
    lobe_map = {l['key']: l for l in plan['fillCreateOperations']}
    physical_groups, integer_groups = defaultdict(list), defaultdict(list)
    review = []
    for item in ground['lobesSortedByArea']:
        if item['reachesActualMCUVssA17']:
            continue
        assert item['noSameLayerCopperContactDetected'] and not item['allSameLayerPhysicalCopperContacts']
        assert not item['sameGraphOriginalGroundViaIds'] and not item['sameGraphPlannedGroundViaIds']
        lobe = lobe_map[item['key']]
        shape = P['geom'](lobe['afterPathsExplicitlyClosedForApi'])
        assert shape.is_valid
        paths = [P['ip'](P['ring_points'](r)) for r in lobe['afterPathsExplicitlyClosedForApi']]
        integer_copper = P['difference']([P['positive'](paths[0])], P['union']([P['positive'](p) for p in paths[1:]]))
        physical = shape.buffer(lobe['widthMil'] * P['MM'] / 2, resolution=64)
        assert physical.is_valid
        group = (lobe['layerId'], lobe['net'])
        physical_groups[group].append(physical)
        integer_groups[group].extend(integer_copper)
        review.append({'key': item['key'], 'net': lobe['net'], 'layerId': lobe['layerId'],
                       'nominalIntegerAreaMm2': P['area'](integer_copper),
                       'nominalGraphAreaMm2': item['nominalAreaMm2'], 'physicalPenEnvelopeAreaMm2': physical.area,
                       'boundsMm': item['boundsMm'], 'widthMil': lobe['widthMil'],
                       'sourceParentPrimitiveId': lobe['sourceParentPrimitiveId'],
                       'sourceParentBeforeBodySha256': lobe['sourceParentBeforeBodySha256'],
                       'afterApiPathSha256': P['digest'](lobe['afterPathsExplicitlyClosedForApi']),
                       'sameLayerAllCopperContactCount': 0, 'groundPadContactCount': 0,
                       'originalOrNewGroundViaContactCount': 0, 'mcuAnchored': False,
                       'excludedInvalidOriginalCopperBoundingBoxOverlapCount': 0,
                       'separatedOnlyByReviewedLocalCuts': item['separatedOnlyByReviewedLocalCuts'],
                       'deletionAuthorized': False})
    review.sort(key=lambda r: (-r['nominalIntegerAreaMm2'], r['key']))
    per_group = [{'layerId': layer, 'net': net,
                  'nominalIntegerUnionAreaMm2': P['area'](P['signed_region'](paths)),
                  'physicalPenEnvelopeUnionAreaMm2': unary_union(physical_groups[layer, net]).area}
                 for (layer, net), paths in sorted(integer_groups.items())]
    mandatory = []
    for layer, area in [(1, 20.077817639411037), (2, 7.58451118903618), (2, 70.30000384023006)]:
        matches = [l for l in ground['lobesSortedByArea'] if l['layerId'] == layer and abs(l['nominalAreaMm2'] - area) < 1e-8]
        assert len(matches) == 1 and matches[0]['reachesActualMCUVssA17']
        mandatory.append({'key': matches[0]['key'], 'layerId': layer, 'nominalAreaMm2': area,
                          'mcuAnchored': True, 'mustPreserve': True,
                          'sameGraphPlannedGroundViaIds': matches[0]['sameGraphPlannedGroundViaIds']})
    report = {'schema': 'final-isolated-local-ground-lobes-explicit-parent-review-v1',
              'status': 'PENDING_PARENT_EXACT_LIST_APPROVAL_NO_NATIVE_APPLY',
              'manifest': str(args.manifest.resolve()), 'manifestSha256': frozen,
              'sourceSha256': plan['sourceSha256'], 'placementSha256': plan['placementSha256'], 'routes': plan['routes'],
              'groundGraphSha256': P['sha'](args.ground_graph), 'powerGraphSha256': P['sha'](args.power_graph),
              'invalidExclusionSha256': P['sha'](args.invalid_exclusion),
              'groundLoadConnectivityPassed': ground['loadConnectivityPassed'], 'powerLoadConnectivityPassed': power['loadConnectivityPassed'],
              'groundPhysicalPads': len(ground['allPhysicalGroundPads']), 'originalGroundVias': len(ground['originalViaAnchorAudit']),
              'newGroundVias': len(ground['plannedViaAnchorAudit']),
              'powerPhysicalPads': len(power['allPhysicalNetPads']), 'originalPowerVias': len(power['originalViaAnchorAudit']),
              'candidateCount': len(review), 'exactKeysSorted': sorted(r['key'] for r in review),
              'exactKeysSortedSha256': P['digest'](sorted(r['key'] for r in review)),
              'nominalIntegerSumAreaMm2': sum(r['nominalIntegerAreaMm2'] for r in review),
              'nominalIntegerUnionAreaMm2': sum(r['nominalIntegerUnionAreaMm2'] for r in per_group),
              'maximumNominalAreaMm2': max((r['nominalIntegerAreaMm2'] for r in review), default=0),
              'physicalPenEnvelopeSumAreaMm2': sum(r['physicalPenEnvelopeAreaMm2'] for r in review),
              'physicalPenEnvelopeUnionAreaMm2': sum(r['physicalPenEnvelopeUnionAreaMm2'] for r in per_group),
              'allCandidateCopperPadViaContactsZero': True, 'allCandidateInvalidSourceBoundsOverlapZero': True,
              'mandatoryPreservedLargeLobes': mandatory, 'retainedMcuAnchoredLobeCount': ground['mcuAnchoredLobeCount'],
              'perLayerNetAreaProof': per_group, 'candidatesSortedByArea': review,
              'nativeCalls': 0, 'nativeModified': False, 'deletionAuthorized': False,
              'qualification': 'Nominal contour area uses1nm integer Boolean geometry. Physical pen envelope includes each static FILL half-width with64-segment-per-quadrant round joins; it is an offline geometric envelope, not a manufacturing signoff. No existing primitive deletion or source write is performed.'}
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'count': len(review),
                      'nominalIntegerUnionAreaMm2': report['nominalIntegerUnionAreaMm2'],
                      'maximumNominalAreaMm2': report['maximumNominalAreaMm2'],
                      'physicalPenEnvelopeUnionAreaMm2': report['physicalPenEnvelopeUnionAreaMm2']}))


if __name__ == '__main__':
    main()
