"""Review-only geometry for blocked local outer cuts; never emits executable operations."""
import argparse
import json
import runpy
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    if Path(args.output_prefix).name != args.output_prefix:
        raise ValueError('Output prefix must remain in own ground folder')
    report = json.loads(args.manifest.read_text(encoding='utf8'))
    source = Path(report['source'])
    placement = Path(report['placement'])
    assert P['sha'](source) == report['sourceSha256']
    assert P['sha'](placement) == report['placementSha256']
    routes = []
    for r in report['routes']:
        path = Path(r['path'])
        assert P['sha'](path) == r['sha256']
        routes.append(json.loads(path.read_text(encoding='utf8')))
    rows = P['G']['PARSE'](source)
    actors = P['actor_paths'](json.loads(placement.read_text(encoding='utf8')), routes, [], report['layers'])
    requests = []
    for audit in report['fillAudits']:
        if audit['status'] != 'BLOCKED_CUT_TOUCHES_OUTER_BOUNDARY':
            continue
        body = rows['FILL', audit['id']]
        outer = Polygon(P['ring_points'](body['path'][0]))
        old_fill = P['geom'](body['path'])
        assert outer.is_valid and old_fill.is_valid
        pen = abs(body.get('width', 0) or 0) * P['MM'] / 2
        radius = report['clearanceMm'] + pen + P['ROUNDING_GUARD_MM']
        requested = []
        for actor in actors:
            if actor['layerId'] != body['layerId'] or actor['net'] == body.get('netName'):
                continue
            polys = [Polygon(P['fp'](p)) for s in actor['copperPaths'] for p in P['expanded'](s, radius)]
            mask = unary_union(polys)
            if not outer.boundary.intersects(mask):
                continue
            mask_int = [P['ip'](list(p.exterior.coords)[:-1]) for p in (mask.geoms if mask.geom_type == 'MultiPolygon' else [mask])]
            requested.append({
                'key': actor['key'], 'kind': actor['kind'], 'net': actor['net'],
                'layerId': actor['layerId'], 'xyMm': actor.get('xyMm'),
                'diameterMm': actor.get('diameterMm'),
                'copperPathsSha256': P['digest'](actor['copperPaths']),
                'maskPathsNm': mask_int, 'maskSha256': P['digest'](mask_int),
                'maskBoundsMm': list(mask.bounds),
                'outerOverlapAreaMm2': outer.intersection(mask).area,
                'actualOldFillOverlapAreaMm2': old_fill.intersection(mask).area,
                'alreadyApprovedActorKey': actor['key'] in audit.get('approvedActorKeys', []),
            })
        all_masks = P['union']([p for r in requested for p in r['maskPathsNm']])
        old_masks = P['union']([p for r in requested if r['alreadyApprovedActorKey'] for p in r['maskPathsNm']])
        outer_int = [P['positive'](P['ip'](P['ring_points'](body['path'][0])))]
        all_removed = P['intersection'](outer_int, all_masks)
        old_removed = P['intersection'](outer_int, old_masks)
        requests.append({
            'primitiveId': audit['id'], 'layerId': body['layerId'], 'net': body.get('netName'),
            'beforeBodySha256': P['digest'](body), 'originalOuterPathSha256': P['digest'](body['path'][0]),
            'originalOuterVertexCount': len(P['original_native_points'](body['path'][0])),
            'originalHoleCount': len(body['path']) - 1,
            'requestedActorMasks': requested,
            'totalOuterRemovalWithinAllActorMasksMm2': P['area'](all_removed),
            'additionalOuterRemovalBeyondPriorActorMasksMm2': P['area'](P['difference'](all_removed, old_removed)),
            'allOuterRemovalIntegerPathsSha256': P['digest'](all_removed),
            'reviewQualification': 'Mask intersection only, not an approved or executable afterPath. Final native-edge preservation, retained-lobe and full GND connectivity proofs remain required.',
        })
    result = {'schema': 'pending-local-outer-notch-mask-review-v1',
              'status': 'PENDING_EXPLICIT_PARENT_REVIEW_NOT_FOR_NATIVE_APPLY',
              'inputManifest': str(args.manifest.resolve()), 'inputManifestSha256': P['sha'](args.manifest),
              'source': str(source), 'sourceSha256': report['sourceSha256'],
              'clearanceMm': report['clearanceMm'], 'requests': requests,
              'nativeCalls': 0, 'nativeModified': False,
              'notApproved': True, 'containsExecutableOperations': False}
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target),
                      'requests': [{**{k: r[k] for k in ('primitiveId', 'totalOuterRemovalWithinAllActorMasksMm2', 'additionalOuterRemovalBeyondPriorActorMasksMm2')},
                                    'actors': [a['key'] for a in r['requestedActorMasks']]} for r in requests]}))


if __name__ == '__main__':
    main()
