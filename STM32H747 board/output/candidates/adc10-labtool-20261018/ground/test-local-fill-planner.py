"""Synthetic polygon unit cases; no native design data or API is modified."""
import hashlib
import json
import runpy
import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def ring(points, outer=False):
    return P['native_ring'](P['ip'](points), outer=outer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=HERE / 'local-fill-planner-unit-tests.json')
    args = parser.parse_args()
    tests = []
    outer = ring([(0, 0), (10, 0), (10, 10), (0, 10)], True)
    hole = ring([(4, 4), (6, 4), (6, 6), (4, 6)])
    paths = [outer, hole]
    body = {'netName': 'GND', 'layerId': 1, 'path': paths, 'width': .2, 'fillStyle': 'SOLID'}
    rings = [P['ip'](P['ring_points'](r)) for r in paths]
    # Requested ring void encloses a real copper island with an old inner hole.
    current = [P['positive'](P['ip']([(2, 2), (8, 2), (8, 8), (2, 8)])),
               list(reversed(P['positive'](P['ip']([(3, 3), (7, 3), (7, 7), (3, 7)]))))]
    after, lobes, retained, _, added, lost, xor = P['split_local_lobes']('synthetic', body, paths, rings, current)
    tests.append({'name': 'Enclosed copper island retained as separate FILL with exact original inner hole',
                  'passed': len(lobes) == 1 and hole in lobes[0]['afterPath'] and retained == [0, 1] and added == lost == xor == 0 and lobes[0]['nativeOuterClockwise']})
    # A second nested void/island exercises multiple PolyTree depths.
    nested = current + [P['positive'](P['ip']([(3.5, 3.5), (6.5, 3.5), (6.5, 6.5), (3.5, 6.5)])),
                        list(reversed(P['positive'](P['ip']([(4, 4), (6, 4), (6, 6), (4, 6)]))))]
    body2 = {**body, 'path': [outer]}
    after, lobes, _, _, added, lost, xor = P['split_local_lobes']('nested', body2, [outer], [rings[0]], nested)
    tests.append({'name': 'Multiple PolyTree depths preserve both nested copper islands',
                  'passed': len(lobes) == 2 and added == lost == xor == 0 and all(P['geom'](l['afterPath']).is_valid for l in lobes)})
    native_outer = ring([(0, 0), (5, 0), (10, 0), (10, 10), (5, 10), (0, 10), (0, 5)], True)
    notch_body = {**body, 'path': [native_outer]}
    actor = {'kind': 'VIA', 'key': 'APPROVED_TEST_VIA', 'layerId': 1, 'net': '+5V',
             'copperPaths': P['capsule']((.1, 5), (.1, 5), .3)}
    op, diagnostic = P['cut_one']('notch', notch_body, [actor], .17)
    tests.append({'name': 'Unapproved outer contact is blocked without a candidate mutation',
                  'passed': op is None and diagnostic['status'] == 'BLOCKED_CUT_TOUCHES_OUTER_BOUNDARY'})
    approval = {'beforeBodySha256': P['digest'](notch_body), 'allowedOuterActorKeys': ['APPROVED_TEST_VIA']}
    op, diagnostic = P['cut_one']('notch', notch_body, [actor], .17, approval)
    tests.append({'name': 'Approved notch restores native vertices and outside-mask edges exactly',
                  'passed': op is not None and op['reviewedLocalOuterNotch']['proof']['passed'] and
                            op['copperAdditionAreaMm2'] == op['oldVoidLostAreaMm2'] == 0})
    scoped_actor = {**actor, 'xyMm': [.1, 5], 'diameterMm': .6}
    scoped_approval = {**approval, 'portCentersMm': {'APPROVED_TEST_VIA': [.1, 5]},
                       'viaCopperDiameterMm': .6, 'clearanceMm': .17,
                       'fillPenRadiusMm': .2 * P['MM'] / 2, 'roundingReserveMm': P['ROUNDING_GUARD_MM']}
    op, diagnostic = P['cut_one']('notch', notch_body, [scoped_actor], .17, scoped_approval)
    tests.append({'name': 'Exact reviewed port center/diameter/clearance passes', 'passed': op is not None})
    for name, change in [('center', {'xyMm': [.10001, 5]}), ('diameter', {'diameterMm': .60001}),
                         ('kind', {'kind': 'LINE'})]:
        op, diagnostic = P['cut_one']('notch', notch_body, [{**scoped_actor, **change}], .17, scoped_approval)
        tests.append({'name': 'Changed approved actor ' + name + ' is blocked',
                      'passed': op is None and bool(diagnostic.get('authorizationErrors'))})
    op, diagnostic = P['cut_one']('notch', notch_body, [scoped_actor], .171, scoped_approval)
    tests.append({'name': 'Changed reviewed clearance is blocked',
                  'passed': op is None and bool(diagnostic.get('authorizationErrors'))})
    invalid_hole = ring([(2, 2), (7, 7), (2, 7), (7, 2)])
    invalid = {**body, 'path': [outer, invalid_hole]}
    op, diagnostic = P['cut_one']('invalid', invalid, [{'kind': 'PAD', 'key': 'P', 'layerId': 1, 'net': '+5V',
                 'copperPaths': [P['ip']([(8, 8), (9, 8), (9, 9), (8, 9)])]}], .17)
    tests.append({'name': 'Invalid original input is blocked rather than buffer-zero repaired',
                  'passed': op is None and diagnostic['status'] == 'BLOCKED_INVALID_INPUT_REQUIRES_REVIEW'})
    result = {'schema': 'local-static-fill-planner-synthetic-tests-v1', 'passed': all(t['passed'] for t in tests), 'tests': tests,
              'generatorSha256': hashlib.sha256((HERE / 'plan-local-static-fill-clearance.py').read_bytes()).hexdigest(),
              'nativeCalls': 0, 'nativeModified': False}
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
