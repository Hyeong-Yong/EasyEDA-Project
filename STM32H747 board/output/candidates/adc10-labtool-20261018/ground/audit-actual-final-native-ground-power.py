"""Direct actual-source graph, using actual pads/copper/barrels and saved libraries."""
import argparse
import json
import runpy
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def region(paths):
    rings = [P['ip'](P['ring_points'](r)) for r in paths]
    return P['difference']([P['positive'](rings[0])], P['union']([P['positive'](r) for r in rings[1:]]))


def xor(a, b):
    return P['area'](P['difference'](a, b)) + P['area'](P['difference'](b, a))


def q(value):
    return float(Decimal(str(value)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP))


def linear_points(ring):
    if any(isinstance(v, str) and v != 'L' for v in ring):
        return None
    numbers = [v for v in ring if not isinstance(v, str)]
    assert len(numbers) >= 6 and len(numbers) % 2 == 0
    return list(zip(numbers[::2], numbers[1::2]))


def canonical_ring(ring, native_grid=False):
    points = linear_points(ring)
    if points is None:
        return ('exact-curve', json.dumps(ring, separators=(',', ':')))
    pts = []
    for x, y in points:
        item = ((int(Decimal(str(x)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP) * 10000),
                 int(Decimal(str(y)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP) * 10000)) if native_grid else
                (Fraction(str(x)), Fraction(str(y))))
        if not pts or item != pts[-1]:
            pts.append(item)
    if pts[-1] == pts[0]:
        pts.pop()
    changed = True
    while changed and len(pts) > 3:
        changed = False
        out = []
        for index, b in enumerate(pts):
            a, c = pts[index - 1], pts[(index + 1) % len(pts)]
            collinear = (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0])
            forward = (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) >= 0
            if collinear and forward:
                changed = True
            else:
                out.append(b)
        pts = out
    assert len(set(pts)) >= 3
    alternatives = []
    for sequence in (pts, list(reversed(pts))):
        smallest = min(sequence)
        alternatives.extend(tuple(sequence[i:] + sequence[:i]) for i, v in enumerate(sequence) if v == smallest)
    return ('linear', min(alternatives))


def canonical_complex(paths, native_grid=False):
    return canonical_ring(paths[0], native_grid), Counter(canonical_ring(r, native_grid) for r in paths[1:])


def native_grid_paths(paths):
    return [[q(v) if isinstance(v, (int, float)) else v for v in r] if linear_points(r) is not None else r for r in paths]


def compare_known_api_paths(expected, actual):
    """Only modified/created API FILLs may use this exact observed serializer."""
    raw_expected, raw_actual = P['geom'](expected), P['geom'](actual)
    if not raw_expected.is_valid or not raw_actual.is_valid:
        return {'passed': False, 'reason': 'Invalid raw native/source polygon is never normalized or repaired'}

    def region_proof(effective_expected, effective_actual, normalized):
        expected_geom, actual_geom = P['geom'](effective_expected), P['geom'](effective_actual)
        integer_xor = xor(region(effective_expected), region(effective_actual))
        passed = expected_geom.is_valid and actual_geom.is_valid and integer_xor == 0 and expected_geom.symmetric_difference(actual_geom).area == 0
        return {'passed': passed, 'qualifiedNative4dpMilSerialization': normalized,
                'curvedCommandsExactNoCurveRoundingAuthorized': True,
                'integerGeometryXorAreaMm2': integer_xor,
                'maxPerAxisSerializationBoundMil': .00005 if normalized else 0,
                'noBufferOrRepairUsedToMatchGeometry': True}

    if expected == actual:
        return region_proof(expected, actual, False)
    requested = {p for r in expected for p in (linear_points(r) or [])}
    coordinates_qualified = all(point in requested or point == (q(point[0]), q(point[1]))
                                for r in actual for point in (linear_points(r) or []))
    # Test the exact integer-grid branch first. This avoids expensive Fraction
    # arithmetic for large API-serialized paths without widening the accepted
    # geometry set. Exact rational-edge equivalence remains the fallback.
    if coordinates_qualified and canonical_complex(expected, True) == canonical_complex(actual, True):
        result = region_proof(native_grid_paths(expected), native_grid_paths(actual), True)
        if result['passed']:
            return result
    if canonical_complex(expected) == canonical_complex(actual):
        return region_proof(expected, actual, False)
    return {'passed': False, 'reason': 'Actual path differs beyond exact requested edges or qualified native4dp serialization'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--actual', type=Path, required=True)
    ap.add_argument('--checkpoint', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    ap.add_argument('--geometry-only', action='store_true')
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    actual_sha, cp_sha = P['sha'](args.actual), P['sha'](args.checkpoint)
    frozen_path = HERE / 'local-static-fill-clearance-v6-routingv5-approved116-omission-final.json'
    assert P['sha'](frozen_path) == '660036f5ebfd445fbe96780349bd661510c0abeb0767f93ac1c44390a8bfa0a2'
    frozen = json.loads(frozen_path.read_text(encoding='utf8'))
    baseline = P['G']['PARSE'](Path(frozen['source']))
    actual = P['G']['PARSE'](args.actual)
    errors, geometry = [], []
    before_vias = {rid for kind, rid in baseline if kind == 'VIA'}
    after_vias = {rid for kind, rid in actual if kind == 'VIA'}
    before_fills = {rid for kind, rid in baseline if kind == 'FILL'}
    after_fills = {rid for kind, rid in actual if kind == 'FILL'}
    assert before_vias <= after_vias and len(before_vias) == 640 and len(after_vias - before_vias) == 64
    assert before_fills <= after_fills and len(after_fills - before_fills) == 28
    for key, b in baseline.items():
        if key[0] in {'COMPONENT', 'PAD_NET', 'RULE', 'LAYER', 'PAD'} or key[0] == 'VIA':
            if actual.get(key) != b:
                errors.append({'protectedActualRecordChanged': key})
    for op in frozen['fillModifyOperations']:
        b = actual['FILL', op['primitiveId']]
        comparison = compare_known_api_paths(op['afterPathsExplicitlyClosedForApi'], b['path'])
        passed = comparison['passed'] and b['netName'] == op['net'] and b['layerId'] == op['layerId'] and b['width'] == op['beforeBody']['width']
        geometry.append({'kind': 'modifiedOriginalFill', 'id': op['primitiveId'], **comparison, 'passed': passed})
        if not passed:
            errors.append(geometry[-1])
    unmatched = after_fills - before_fills
    existing_audit_lobes = []
    mappings = []
    for lobe in frozen['fillCreateOperations']:
        matches = [rid for rid in unmatched if actual['FILL', rid]['netName'] == lobe['net'] and actual['FILL', rid]['layerId'] == lobe['layerId'] and
                   actual['FILL', rid]['width'] == lobe['widthMil'] and compare_known_api_paths(lobe['afterPathsExplicitlyClosedForApi'], actual['FILL', rid]['path'])['passed']]
        assert len(matches) == 1, 'Native retained-lobe geometry did not match exactly: ' + lobe['key']
        rid = matches[0]
        unmatched.remove(rid)
        b = actual['FILL', rid]
        mappings.append({'plannedKey': lobe['key'], 'actualNativeFillId': rid,
                         **compare_known_api_paths(lobe['afterPathsExplicitlyClosedForApi'], b['path']),
                         'areaMm2': lobe['areaMm2'], 'layerId': lobe['layerId']})
        existing_audit_lobes.append({'key': lobe['key'], 'existingNativePrimitiveId': rid, 'net': b['netName'],
                                    'layerId': b['layerId'], 'widthMil': b['width'], 'afterPathsExplicitlyClosedForApi': b['path']})
    assert not unmatched
    assert not errors, json.dumps(errors)
    if args.geometry_only:
        report = {'schema': 'actual-native-api-fill-known-serialization-focused-audit-v1', 'passed': True,
                  'actualSource': str(args.actual.resolve()), 'actualSourceSha256': actual_sha,
                  'checkpointSha256': cp_sha, 'frozenPlanSha256': P['sha'](frozen_path),
                  'modifiedOriginalFillGeometry': geometry, 'actualRetainedFillMappings': mappings,
                  'allOriginal640ViasAnd437ComponentsAndPadNetsRulesLayersExact': True,
                  'connectivityGraphNotRunInThisFocusedPartialStage': True,
                  'noBufferOrCopperRepair': True, 'nativeCalls': 0, 'nativeModified': False}
        target = HERE / (args.output_prefix + '-geometry-only-audit.json')
        target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
        print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'passed': True}))
        return
    placement_path = HERE / (args.output_prefix + '-actual-library-context.json')
    placement_path.write_text(json.dumps({'checkpointPath': str(args.checkpoint.resolve()), 'checkpointSha256': cp_sha,
                                         'edits': [], 'usesOnlyActualNativeComponentPoses': True}, indent=2) + '\n', encoding='utf8')
    context = {'schema': 'actual-native-physical-graph-input-no-proposed-copper-v1', 'passed': True,
               'source': str(args.actual.resolve()), 'sourceSha256': actual_sha,
               'placement': str(placement_path), 'placementSha256': P['sha'](placement_path),
               'routes': [], 'fillModifyOperations': [], 'fillCreateOperations': [],
               'auditExistingFillPrimitives': existing_audit_lobes,
               'scope': 'Only actual source geometry is graphed; auditExistingFillPrimitives selects already-present native FILLs for anchor queries and adds no copper.'}
    context_path = HERE / (args.output_prefix + '-actual-graph-input.json')
    context_path.write_text(json.dumps(context, indent=2) + '\n', encoding='utf8')
    auditor = HERE / 'audit-local-ground-lobe-connectivity.py'

    def run(net):
        suffix = '-gnd' if net == 'GND' else '-3v3'
        cmd = [sys.executable, str(auditor), '--manifest', str(context_path), '--output-prefix', args.output_prefix + suffix, '--net', net]
        if net != 'GND':
            cmd += ['--anchor-pad', 'U3:4']
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        path = HERE / (args.output_prefix + suffix + '.json')
        return path, json.loads(path.read_text(encoding='utf8'))

    with ThreadPoolExecutor(max_workers=2) as pool:
        g_future, p_future = pool.submit(run, 'GND'), pool.submit(run, '+3V3')
        (g_path, ground), (p_path, power) = g_future.result(), p_future.result()
    old_ground = {rid for rid in before_vias if baseline['VIA', rid].get('netName') == 'GND'}
    new_ground = {rid for rid in after_vias - before_vias if actual['VIA', rid].get('netName') == 'GND'}
    ground_roots = {r['id']: r['reachesSelectedSourcePad'] for r in ground['originalViaAnchorAudit']}
    assert len(old_ground) == 199 and len(new_ground) == 29
    assert len(ground['allPhysicalGroundPads']) == 345 and len(power['allPhysicalNetPads']) == 138
    assert len(power['originalViaAnchorAudit']) == 77
    assert ground['loadConnectivityPassed'] and power['loadConnectivityPassed']
    assert all(ground_roots[v] for v in old_ground | new_ground)
    assert ground['lobeCount'] == ground['mcuAnchoredLobeCount'] == 28 and ground['unanchoredLobeCount'] == 0
    assert P['sha'](args.actual) == actual_sha and P['sha'](args.checkpoint) == cp_sha
    report = {'schema': 'direct-actual-native-final-ground-power-lobe-audit-v1', 'passed': True,
              'actualSource': str(args.actual.resolve()), 'actualSourceSha256': actual_sha,
              'checkpoint': str(args.checkpoint.resolve()), 'checkpointSha256': cp_sha,
              'frozenPlanSha256': P['sha'](frozen_path), 'allCoordinatesFromActualSourceNoProposedPoseOverlay': True,
              'groundLoadConnectivityPassed': True, 'powerLoadConnectivityPassed': True,
              'groundPads': 345, 'originalGroundViaIds': sorted(old_ground), 'newGroundViaIds': sorted(new_ground),
              'allOriginal199AndNew29GroundViasActuallyAnchoredToMcuVss': True,
              'powerPads': 138, 'originalPowerVias': 77, 'retainedActualNativeFillAnchorCount': 28,
              'protectedOriginal640ViasAnd437ComponentsAndPadNetsRulesLayersExact': True,
              'modifiedOriginalFillGeometry': geometry, 'actualRetainedFillMappings': mappings,
              'groundReport': str(g_path), 'groundReportSha256': P['sha'](g_path),
              'powerReport': str(p_path), 'powerReportSha256': P['sha'](p_path),
              'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False,
              'qualification': 'This directly establishes physical DC copper connectivity from actual native shapes/pads/barrels and saved footprint libraries, not merely evidence transfer from proposed geometry. Native DRC, full-netlist and manufacturing/CAM checks remain separate.'}
    target = HERE / (args.output_prefix + '-audit.json')
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'passed': True}))


if __name__ == '__main__':
    main()
