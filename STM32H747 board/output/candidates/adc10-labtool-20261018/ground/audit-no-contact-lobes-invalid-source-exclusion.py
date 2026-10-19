"""Conservative bounds screen prevents omitted invalid copper hiding a contact."""
import argparse
import json
import runpy
from pathlib import Path
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--graph', type=Path, required=True)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    graph = json.loads(args.graph.read_text(encoding='utf8'))
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    assert P['sha'](args.manifest) == graph['manifestSha256']
    source = Path(manifest['source'])
    assert P['sha'](source) == manifest['sourceSha256']
    rows = P['G']['PARSE'](source)
    excluded = []
    for item in graph['excludedOriginalInvalidGeometryNoRepair']:
        assert item['kind'] == 'FILL', 'New unsupported excluded geometry requires explicit review'
        body = rows['FILL', item['id']]
        points = [xy for path in body['path'] for xy in P['ring_points'](path)]
        radius = abs(body.get('width', 0) or 0) * P['MM'] / 2
        bounds = [min(p[0] for p in points) - radius, min(p[1] for p in points) - radius,
                  max(p[0] for p in points) + radius, max(p[1] for p in points) + radius]
        excluded.append({**item, 'conservativeAllContoursPenExpandedBoundsMm': bounds,
                         'sourceBodySha256': P['digest'](body)})
    candidates = [l for l in graph['lobesSortedByArea'] if not l['reachesActualMCUVssA17'] and l['noSameLayerCopperContactDetected']]
    lobe_map = {l['key']: l for l in manifest['fillCreateOperations']}
    overlaps = []
    for lobe in candidates:
        physical = P['geom'](lobe_map[lobe['key']]['afterPathsExplicitlyClosedForApi']).buffer(lobe_map[lobe['key']]['widthMil'] * P['MM'] / 2)
        for item in excluded:
            if item['layerId'] != lobe['layerId']:
                continue
            bounds_shape = box(*item['conservativeAllContoursPenExpandedBoundsMm'])
            if physical.envelope.intersects(bounds_shape):
                overlaps.append({'lobeKey': lobe['key'], 'excludedInvalidId': item['id'],
                                 'layerId': lobe['layerId'], 'conservativeBoundsOverlap': True})
    report = {'schema': 'no-contact-lobes-invalid-source-conservative-exclusion-audit-v1',
              'passed': not overlaps, 'graph': str(args.graph.resolve()), 'graphSha256': P['sha'](args.graph),
              'manifestSha256': P['sha'](args.manifest), 'sourceSha256': P['sha'](source),
              'noContactUnanchoredCandidateCount': len(candidates),
              'excludedInvalidOriginalFills': excluded, 'potentialHiddenContactsRequiringReview': overlaps,
              'noInvalidSourceGeometryRepaired': True,
              'claim': 'Only if every conservative same-layer bound is disjoint can excluded invalid original copper not hide a contact with a proposed no-contact lobe.',
              'nativeCalls': 0, 'nativeModified': False, 'deletionAuthorized': False}
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'passed': report['passed'],
                      'candidates': len(candidates), 'potentialHiddenContacts': len(overlaps)}))


if __name__ == '__main__':
    main()
