"""Materialize parent's exact additional via2 review; no native design edits."""
import json
import runpy
from pathlib import Path
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    old = json.loads((HERE / 'approved-bottom-four-actor-notch-scope-v5b.json').read_text(encoding='utf8'))
    scope = old['a1d7888349e74585']
    route_path = HERE.parent / 'routing/frozen-combined-routing-v2.json'
    assert P['sha'](route_path) == 'fef1c7280edc8412c5f154f9663580f4ef49695746fb35250433ad02e4f59ed3'
    route = json.loads(route_path.read_text(encoding='utf8'))
    actors = P['actor_paths']({'edits': []}, [route], [], {2})
    actor = next(a for a in actors if a['key'] == 'RAW5_BILAYER_EXTRA_VIA_2')
    assert actor['kind'] == 'VIA' and actor['net'] == '+5V' and actor['xyMm'] == [29.4, 33.8] and actor['diameterMm'] == .45
    radius = scope['clearanceMm'] + scope['fillPenRadiusMm'] + scope['roundingReserveMm']
    mask = unary_union([Polygon(P['fp'](p)) for s in actor['copperPaths'] for p in P['expanded'](s, radius)])
    parts = mask.geoms if mask.geom_type == 'MultiPolygon' else [mask]
    paths = [P['ip'](list(p.exterior.coords)[:-1]) for p in parts]
    scope['allowedConnectedInteriorActorKeys'] = [actor['key']]
    scope['expectedActors'][actor['key']] = {'kind': actor['kind'], 'net': actor['net'],
            'copperPathsSha256': P['digest'](actor['copperPaths']), 'maskSha256': P['digest'](paths)}
    scope['portCentersMm'][actor['key']] = actor['xyMm']
    scope['authorization'] += ' Parent separately approved the exact frozenV2 RAW5_BILAYER_EXTRA_VIA_2(29.4,33.8),diameter.45/hole.20,clearance.17 mask joining these four masks. Additional ear removal0.0227637806385mm2 was specifically reviewed in2f9d7abe3cf5197c6a8599450e80d6c6e934b4e0a1e3f93cfefe41f43a92982e. No unapproved actor or generic numerical-sliver waiver.'
    scope['approvedAdditionalVia2EarAreaMm2'] = .0227637806385
    scope['requiresExactIntegerUnionMaskProof'] = True
    target = HERE / 'approved-bottom-five-actor-notch-scope-v5b.json'
    target.write_text(json.dumps(old, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'scope': str(target), 'sha256': P['sha'](target), 'via2': scope['expectedActors'][actor['key']]}))


if __name__ == '__main__':
    main()
