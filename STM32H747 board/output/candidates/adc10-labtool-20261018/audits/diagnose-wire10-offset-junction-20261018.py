"""Read-only exact diagnosis, not a waiver or native repair."""
import json
import math
import runpy
from collections import Counter
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parents[2]
M = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-copper-readback-20261018.py'))
MM = F('0.0254')
NET = 'ADC_OFFSET_0V97'
IDS = ['06e4e9cdd77323ba', 'e037cb9f75a626cf']
OLD_HORIZONTAL = '99367c2f509621d1'
OLD_VERTICAL = '2dfae3e0e3f002c3'


def exact_grid(x):
    scaled = x * 10000
    whole, rem = divmod(scaled.numerator, scaled.denominator)
    return F(whole + (2 * rem >= scaled.denominator), 10000)


def points(body):
    return tuple(F(str(body[k])) for k in ('startX', 'startY', 'endX', 'endY'))


def squared_distance(p, a, b):
    x, y = b[0] - a[0], b[1] - a[1]
    projection = (p[0] - a[0]) * x + (p[1] - a[1]) * y
    length = x * x + y * y
    if projection <= 0:
        return (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2
    if projection >= length:
        return (p[0] - b[0]) ** 2 + (p[1] - b[1]) ** 2
    return ((p[0] - a[0]) * y - (p[1] - a[1]) * x) ** 2 / length


def main():
    manifest_path = HERE / 'pcb-final-copper-v5-execution.json'
    manifest = M['load'](manifest_path)
    before_path = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire9-20261018.epru'
    actual_path = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire10-20261018.epru'
    old, prior, actual = M['source'](Path(manifest['sourcePath'])), M['source'](before_path), M['source'](actual_path)
    assert M['sha'](actual_path) == '6786a3df2a3795793219d85858560e421afb8ac9515b52ef4012c9360c24736e'
    ops = []
    for stage in manifest['batches']:
        ops.extend(stage['operations'])
        if stage['stage'] == 'copper_wire10':
            break
    expected = []
    for (kind, rid), b in old.items():
        if kind == 'LINE' and b.get('netName') == NET and b.get('layerId') == 1:
            expected.append(dict(key=rid, segment=points(b), width=F(str(b['width']))))
    for o in ops:
        if o['action'] == 'line' and o['net'] == NET and o['layerId'] == 1:
            expected.append(dict(key=o['key'], segment=tuple(F(str(v)) for v in o['startXYMil'] + o['endXYMil']),
                                 width=F(str(M['q'](o['widthMil'])))))
    observed = [dict(key=rid, segment=points(b), width=F(str(b['width']))) for (kind, rid), b in actual.items()
                if kind == 'LINE' and b.get('netName') == NET and b.get('layerId') == 1]
    original = next(x for x in expected if x['key'] == 'LABTOOL_LOCAL_0412')
    a, c = original['segment'][:2], original['segment'][2:]
    first, second = actual['LINE', IDS[0]], actual['LINE', IDS[1]]
    b = points(first)[2:]
    assert points(first)[:2] == a and points(second)[:2] == b and points(second)[2:] == c
    assert first['netName'] == second['netName'] == NET and first['width'] == second['width'] == 8
    assert first['layerId'] == second['layerId'] == 1
    hor, vert = prior['LINE', OLD_HORIZONTAL], prior['LINE', OLD_VERTICAL]
    assert hor['startY'] == hor['endY'] and F(str(hor['startY'])) == b[1]
    assert hor['width'] == vert['width'] == 23.622
    dx, dy = c[0] - a[0], c[1] - a[1]
    exact_x = a[0] + (b[1] - a[1]) * dx / dy
    exact_b = exact_x, b[1]
    rounded_b = exact_grid(exact_x), exact_grid(b[1])
    assert b == rounded_b and min(F(str(hor['startX'])), F(str(hor['endX']))) <= b[0] <= max(F(str(hor['startX'])), F(str(hor['endX'])))
    grid_ok = all(abs(x - z) <= F(1, 20000) for x, z in zip(b, exact_b))
    normalized = [x for x in expected if x['key'] != original['key']] + [
        dict(key='FOCUSED_NORMALIZED_AB', segment=(*a, *b), width=F(8)),
        dict(key='FOCUSED_NORMALIZED_BC', segment=(*b, *c), width=F(8))]
    bucket_proofs = []
    for width in sorted({x['width'] for x in expected + observed}):
        e = M['canonical_segments']([tuple(float(v) for v in x['segment']) for x in expected if x['width'] == width])
        n = M['canonical_segments']([tuple(float(v) for v in x['segment']) for x in normalized if x['width'] == width])
        v = M['canonical_segments']([tuple(float(v) for v in x['segment']) for x in observed if x['width'] == width])
        bucket_proofs.append(dict(widthMil=float(width), originalExpectedExactEqual=e == v,
                                 normalizedExpectedExactEqual=n == v,
                                 originalSupportCount=len(e), normalizedSupportCount=len(n), actualSupportCount=len(v)))
    assert all(x['normalizedExpectedExactEqual'] for x in bucket_proofs)
    # Other existing types remain byte-value exact across this wire9→10 batch.
    protected = {kind: dict(count=sum(k[0] == kind for k in prior), exact={k: v for k, v in prior.items() if k[0] == kind}
                           == {k: v for k, v in actual.items() if k[0] == kind})
                 for kind in ['COMPONENT', 'ATTR', 'PAD_NET', 'VIA', 'FILL', 'RULE', 'LAYER', 'LAYER_PHYS', 'PAD', 'ARC', 'POLY', 'STRING']}
    assert all(x['exact'] for x in protected.values())
    # All unchanged same-net pads/vias/polygonal copper are added to BOTH
    # physical unions, so this does not mislabel a difference hidden by a pad.
    P = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-proposed-power-graph-20261018.py'))
    H = P['H']; attrs = H['attrs_of'](actual)
    docs, _ = H['READ'](ROOT / 'output/checkpoints/STM32H747_labtool_107_placed_v6_wip_20261018.epro2')
    pn = {}
    for (kind, rid), body in actual.items():
        if kind == 'PAD_NET':
            enc = json.loads(rid);pn[enc[1], str(enc[2])] = body.get('padNet')
    common = []
    for (kind, rid), body in actual.items():
        if kind == 'COMPONENT':
            for (pk, _), (_, pad) in docs['FOOTPRINT', attrs[rid]['Footprint']].items():
                if pk == 'PAD' and pn.get((rid, str(pad['num']))) == NET:
                    assert body['layerId'] == 1
                    common.append(H['world'](P['pad_shape'](pad), (body['x'] * float(MM), body['y'] * float(MM)), body['angle']))
        elif body.get('netName') == NET and kind == 'VIA':
            center = Point(body['centerX'] * float(MM), body['centerY'] * float(MM))
            common.append(center.buffer(body['viaDiameter'] * float(MM) / 2, resolution=1024).difference(
                center.buffer(body['holeDiameter'] * float(MM) / 2, resolution=1024)))
        elif body.get('netName') == NET and body.get('layerId') == 1 and kind in ('FILL', 'ARC', 'CARC', 'POLY'):
            raise AssertionError(('Additional non-LINE net copper requires explicit model', kind, rid))
    measures = []
    for resolution in (64, 256, 1024):
        disks = {}
        def capsule(entry):
            x1, y1, x2, y2 = [float(v * MM) for v in entry['segment']]
            radius = float(entry['width'] * MM / 2)
            length = math.hypot(x2 - x1, y2 - y1)
            nx, ny = -(y2 - y1) / length * radius, (x2 - x1) / length * radius
            rect = Polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
            parts = [rect]
            for xy in ((x1, y1), (x2, y2)):
                key = xy, radius
                disks.setdefault(key, Point(xy).buffer(radius, resolution=resolution))
                parts.append(disks[key])
            return unary_union(parts)
        e = unary_union(common + [capsule(x) for x in expected])
        v = unary_union(common + [capsule(x) for x in observed])
        add, missing = v.difference(e), e.difference(v)
        measures.append(dict(circleQuadrantResolution=resolution, addedCopperAreaMm2=add.area,
                             missingCopperAreaMm2=missing.area, xorAreaMm2=add.area + missing.area,
                             addedBoundsMm=list(add.bounds), missingBoundsMm=list(missing.bounds),
                             numericalNotExactProof=True))
    # Rational witness near the midpoint of AB demonstrates an actual *line*
    # copper sliver outside the original AC capsule (not just a support-label
    # mismatch). It must also miss every other expected LINE capsule exactly.
    with localcontext() as ctx:
        ctx.prec = 80
        def dec(v):return Decimal(v.numerator) / Decimal(v.denominator)
        ux, uy = b[0] - a[0], b[1] - a[1]
        length = dec(ux * ux + uy * uy).sqrt()
        nx, ny = -dec(uy) / length, dec(ux) / length
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        sign = 1 if dx * (middle[1] - a[1]) - dy * (middle[0] - a[0]) > 0 else -1
        deviation = abs(dec(dx * (middle[1] - a[1]) - dy * (middle[0] - a[0]))) / dec(dx * dx + dy * dy).sqrt()
        distance = Decimal(4) - deviation / 4
        witness = tuple(F(str(v.quantize(Decimal('.000000000001')))) for v in
                        (dec(middle[0]) + sign * nx * distance, dec(middle[1]) + sign * ny * distance))
        inside_actual = squared_distance(witness, a, b) < F(16)
        outside_all_expected_lines = all(squared_distance(witness, x['segment'][:2], x['segment'][2:]) > (x['width'] / 2) ** 2 for x in expected)
        normal = abs(dec(dx * (b[1] - a[1]) - dy * (b[0] - a[0]))) / dec(dx * dx + dy * dy).sqrt()
    receipt = M['load'](HERE / 'native-pcb-copper_wire10-receipt.json')
    created = [x for x in receipt['created'] if x['key'] == 'LABTOOL_LOCAL_0412']
    report = dict(schema='focused-wire10-native-offset-junction-diagnostic-v1', nativeCalls=0, nativeModified=False,
                  approvalGranted=False, proposedGlobalToleranceMil=0, primaryAuditStillFailed=True,
                  manifestPath=str(manifest_path), manifestSha256=M['sha'](manifest_path),
                  priorSourcePath=str(before_path), priorSourceSha256=M['sha'](before_path),
                  actualSourcePath=str(actual_path), actualSourceSha256=M['sha'](actual_path),
                  expectedOriginalKey=original['key'], expectedOriginalWidthMil=8,
                  expectedOriginalACmil=[float(v) for v in original['segment']],
                  actualNewBodies={rid: actual['LINE', rid] for rid in IDS}, actualReturnedCreation=created,
                  oldWideHorizontalId=OLD_HORIZONTAL, oldWideHorizontalBody=hor,
                  oldWideHorizontalBodySha256=M['value_sha'](hor), oldWideVerticalId=OLD_VERTICAL,
                  oldWideVerticalBody=vert, oldWideVerticalBodySha256=M['value_sha'](vert),
                  exactIntersectionMil=[str(x) for x in exact_b], actualJunctionMil=[float(x) for x in b],
                  rawPerAxisRoundingDeltaMil=[float(x - z) for x, z in zip(b, exact_b)],
                  actualEqualsExactIntersectionRounded4dpMil=b == rounded_b,
                  maxPerAxis4dpGridBoundMil=.00005, withinPerAxisGridBound=grid_ok,
                  maximumCenterlineNormalDeviationMm=float(normal * Decimal('.0254')),
                  originalVsActualCenterlineUnionExact=False,
                  normalizedExpectedABCvsActualCenterlineExact=all(x['normalizedExpectedExactEqual'] for x in bucket_proofs),
                  perWidthProofs=bucket_proofs, protectedNonLineBodies=protected,
                  physicalCopperMeasurements=measures,
                  physicalExactEqualityClaimed=False,
                  rationalLineCopperWitness=dict(pointMil=[str(x) for x in witness], pointMm=[float(x * MM) for x in witness],
                    strictlyInsideActualABCapsule=inside_actual, strictlyOutsideAllExpectedLineCapsules=outside_all_expected_lines,
                    actualABDistanceSquaredMil2=str(squared_distance(witness, a, b)), radiusSquaredMil2='16',
                    qualification='Exact rational line-capsule inequalities. Full physical union change is measured separately including unchanged same-net pads/vias.'),
                  focusedQualificationCandidate='Only new LABTOOL_LOCAL_0412 AC is deterministically split into exact A-q4(intersection with the identified prior wide horizontal)-C; all other per-width centerline sets exact. This is native junction coordinate serialization, NOT original geometry equality and NOT a blanket geometric tolerance.',
                  requirements=['Root explicit decision before any qualification.', 'Retain failed primary audit and this non-equivalence diagnosis.',
                                'If approved, require these exact input bodies/hashes and this calculated junction; no unrelated vertex change.',
                                'Full subsequent readback, native strict DRC, saved-state bridge, netlist and CAM checks remain mandatory.'])
    out = HERE / 'audits/wire10-offset-junction-diagnostic-v1.json'
    assert not out.exists()
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(report=str(out), sha256=M['sha'](out), gridProof=grid_ok,
                         normalizedABCExact=report['normalizedExpectedABCvsActualCenterlineExact'],
                         normalDeviationMm=report['maximumCenterlineNormalDeviationMm'], copperMeasurements=measures,
                         lineWitness=report['rationalLineCopperWitness'])), flush=True)


if __name__ == '__main__':
    main()
