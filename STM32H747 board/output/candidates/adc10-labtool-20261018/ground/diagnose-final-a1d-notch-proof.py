"""Capture a failed offline proof's geometry; does not bypass the failing gate."""
import json
import runpy
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
MAN = HERE / 'local-static-fill-clearance-v5b-final513-50vias-preserving.json'


def main():
    plan = json.loads(MAN.read_text(encoding='utf8'))
    source = Path(plan['source'])
    placement = json.loads(Path(plan['placement']).read_text(encoding='utf8'))
    routes = [json.loads(Path(r['path']).read_text(encoding='utf8')) for r in plan['routes']]
    actors = P['actor_paths'](placement, routes, [], plan['layers'])
    body = P['G']['PARSE'](source)['FILL', 'a1d7888349e74585']
    scopes = json.loads((HERE / 'approved-bottom-four-actor-notch-scope-v5b.json').read_text(encoding='utf8'))
    captured = {}
    old_proof = P['cut_one'].__globals__['reviewed_notch_proof']

    def capture(paths, after, lobes, mask, rings):
        proof = old_proof(paths, after, lobes, mask, rings)
        captured.update(paths=paths, after=after, lobes=lobes, mask=mask, rings=rings, proof=proof)
        return proof

    P['cut_one'].__globals__['reviewed_notch_proof'] = capture
    op, status = P['cut_one']('a1d7888349e74585', body, actors, plan['clearanceMm'], scopes['a1d7888349e74585'])
    assert op is None and status['status'] == 'BLOCKED_APPROVED_NOTCH_PRESERVATION_PROOF'
    original = [P['positive'](captured['rings'][0])]
    new_outers = P['union']([P['positive'](P['ip'](P['ring_points'](s[0])))
                            for s in [captured['after']] + [l['afterPath'] for l in captured['lobes']]])
    mask = captured['mask']
    mask_parts = mask.geoms if mask.geom_type == 'MultiPolygon' else [mask]
    mask_paths = [P['ip'](list(p.exterior.coords)[:-1]) for p in mask_parts]
    removed = P['difference'](original, new_outers)
    extra = P['difference'](removed, mask_paths)
    extra_shapes = [Polygon(P['fp'](p)) for p in extra]
    union_extra = unary_union(extra_shapes)
    actor_intersections = []
    radius = plan['clearanceMm'] + (body.get('width', 0) or 0) * P['MM'] / 2 + P['ROUNDING_GUARD_MM']
    for actor in actors:
        if actor['layerId'] != 2 or actor['net'] == 'GND':
            continue
        expanded = [Polygon(P['fp'](p)) for s in actor['copperPaths'] for p in P['expanded'](s, radius)]
        s = unary_union(expanded)
        overlap = union_extra.intersection(s).area
        if overlap > 1e-12:
            actor_intersections.append({'key': actor['key'], 'kind': actor['kind'], 'net': actor['net'],
                                        'overlapAreaMm2': overlap, 'maskBoundsMm': list(s.bounds),
                                        'copperPathsSha256': P['digest'](actor['copperPaths'])})
    report = {'schema': 'failed-local-outer-notch-gate-diagnostic-v1', 'status': status,
              'sourceSha256': P['sha'](source), 'routing': plan['routes'],
              'nativeCalls': 0, 'gateBypassed': False, 'containsExecutableOperations': False,
              'extraIntegerPathsNm': extra,
              'extraComponents': [{'areaMm2': s.area, 'boundsMm': list(s.bounds)} for s in extra_shapes],
              'contributingActorMasks': actor_intersections,
              'notchProof': captured['proof']}
    target = HERE / 'final-a1d-notch-proof-diagnostic.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target),
                      'extraComponents': report['extraComponents'], 'actors': actor_intersections}))


if __name__ == '__main__':
    main()
