"""Independent, fail-closed audit of a completed bounded copper stage.

This reads frozen plans, receipts and native captures only. It never connects to
EasyEDA, edits project documents, or relies on the executor's containment verdict.
Run with .tools/geometry-venv/Scripts/python.exe -X utf8 -B.
"""
import argparse
import hashlib
import json
import math
import runpy
import sys
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
VALIDATION = ROOT / 'output/validation'
PCB = '0ac2a19168000d8e'
MM = .0254
GRID = 10000                 # observed native serialization: 0.0001 mil
SCALE = 1000000              # ground planner's 1 nm integer clipping lattice
VIEW = {'CANVAS', 'ACTIVE_LAYER', 'ELE_PLACEHOLDER'}
JUNCTION_REVIEW_SHA = '90aab429165937b7b16143fc041defbb12ffe92b176bdb65ffd184dd806d6918'
PAIR_JUNCTION_REVIEW_SHA = 'f3425d761d6434e76fa992c5dd500e7e3b79f97759bcb2c87d0868d81bc90f00'
sys.path.insert(0, str(ROOT / '.tools/adc-geometry-deps'))
import pyclipper as pc


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def value_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def scoped(path, folder):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p if str(p).replace('\\', '/').startswith('output/') else folder / p
    p = p.resolve()
    assert p.is_relative_to(folder.resolve()), ('OUTSIDE_APPROVED_SCOPE', str(p))
    return p


def source(path):
    rows = {}
    for no, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if '||' not in line:
            continue
        head, body = line.split('||', 1)
        head = json.loads(head)
        key = head['type'], head.get('id')
        assert key not in rows, ('DUPLICATE_NATIVE_KEY', no, key)
        body = json.loads(body.removesuffix('|'))
        assert isinstance(body, dict), ('TOMBSTONE_OR_NONMATERIALIZED_BODY', no, key)
        rows[key] = body
    heads = [v for (t, _), v in rows.items() if t == 'DOCHEAD']
    assert len(heads) == 1 and heads[0].get('uuid') == PCB and heads[0].get('docType') == 'PCB'
    return rows


def fields(a, b):
    if b is None:
        return ['MISSING']
    return sorted(k for k in set(a) | set(b) if a.get(k, object()) != b.get(k, object()))


def q(v):
    """Explicit decimal half-away-from-zero 4dp native serialization."""
    return float(Decimal(str(v)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP))


def scalar_serialization(actual, expected):
    return (isinstance(actual, (int, float)) and math.isfinite(actual)
            and actual in (expected, q(expected)))


def fraction(v):
    assert isinstance(v, (int, float)) and math.isfinite(v), ('NONFINITE_COORDINATE', v)
    return Fraction(str(v))


def approved_inner15_pair(start, end):
    """Float-expression identity only; generated native coordinates stay exact.

    This permits 12.200000000000001 versus 12.2 mm, not a different segment:
    every raw coordinate must also be within 1e-12 mm and the compiler's full
    ordered 4dp-mil endpoint pair must equal one explicitly approved pair.
    """
    approved = (((40.3, 31.7), (13.8, 35.5)), ((13.8, 35.5), (12.2, 36.9)),
                ((12.2, 36.9), (8.9, 37.5)))
    raw = (start, end)
    if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in raw):
        return False
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for p in raw for v in p):
        return False
    native = tuple(tuple(round(v / MM, 4) for v in p) for p in raw)
    return any(all(abs(raw[i][j] - pair[i][j]) <= 1e-12 for i in range(2) for j in range(2))
               and native == tuple(tuple(round(v / MM, 4) for v in p) for p in pair)
               for pair in approved)


def exact_q4_fraction(value):
    scaled = value * 10000
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    return Fraction(whole + (2 * remainder >= scaled.denominator), 10000)


def focused_junction_proof(op, horizontal, vertical, actual, review, approved_bodies):
    """One hash-pinned native intersection split; no geometric tolerance."""
    assert op['key'] == review['plannedKey'] == 'LABTOOL_LOCAL_0412'
    assert op['net'] == review['net'] == 'ADC_OFFSET_0V97'
    assert op['layerId'] == review['layerId'] == 1 and op['widthMil'] == review['widthMil'] == 8
    ac = op['startXYMil'] + op['endXYMil']
    assert ac == review['originalACmil'] == [1157.4803, 3289.37, 1011.811, 3478.3465]
    assert value_sha(horizontal) == review['oldWideHorizontalBodySha256']
    assert value_sha(vertical) == review['oldWideVerticalBodySha256']
    assert horizontal['netName'] == vertical['netName'] == review['net']
    assert horizontal['layerId'] == vertical['layerId'] == 1
    assert horizontal['width'] == vertical['width'] == 23.622
    assert horizontal['startY'] == horizontal['endY']
    a, c = tuple(map(fraction, ac[:2])), tuple(map(fraction, ac[2:]))
    y = fraction(horizontal['startY'])
    assert c[1] != a[1]
    x = a[0] + (y - a[1]) * (c[0] - a[0]) / (c[1] - a[1])
    exact_b = x, y
    assert [str(v) for v in exact_b] == review['exactIntersectionMil']
    b = tuple(exact_q4_fraction(v) for v in exact_b)
    assert [float(v) for v in b] == review['onlyApprovedSerializedJunctionMil'] == [1028.5023, 3456.6929]
    assert min(fraction(horizontal['startX']), fraction(horizontal['endX'])) <= x <= max(fraction(horizontal['startX']), fraction(horizontal['endX']))
    bound = fraction(review['knownNativePerAxisSerializationBoundMil'])
    assert bound == Fraction(1, 20000) and all(abs(v - z) <= bound for v, z in zip(b, exact_b))
    assert review['actualSplitIds'] == ['06e4e9cdd77323ba', 'e037cb9f75a626cf']
    expected_segments = [(*a, *b), (*b, *c)]
    for rid, segment in zip(review['actualSplitIds'], expected_segments):
        body = actual.get(('LINE', rid))
        assert body is not None and value_sha(body) == value_sha(approved_bodies[rid]), ('APPROVED_SPLIT_BODY_CHANGED', rid)
        coordinates = tuple(fraction(body[k]) for k in ('startX', 'startY', 'endX', 'endY'))
        assert coordinates == segment, ('NONAPPROVED_JUNCTION_VERTEX', rid)
        assert body['netName'] == op['net'] and body['layerId'] == 1 and body['width'] == 8
    return dict(plannedKey=op['key'], net=op['net'], layerId=1, widthMil=8,
                originalACmil=ac, exactIntersectionMil=[str(v) for v in exact_b],
                serializedJunctionMil=[float(v) for v in b],
                perAxisSerializationDeltaMil=[float(v - z) for v, z in zip(b, exact_b)],
                perAxisKnownGridBoundMil=float(bound), actualSplitIds=review['actualSplitIds'],
                normalizedSegmentsMil=[[float(v) for v in s] for s in expected_segments],
                normalizedNativeGeometryExact=True,
                originalVsActualCenterlineUnionExact=False,
                physicalCopperUnionEqualVsUnserializedPlan=False)


def focused_paired_junction_proof(ops, prior_crossing, actual, review):
    """Only the second, separately hash-approved pair of diagonal splits."""
    assert review['net'] == '+5V_AFE' and review['layerId'] == 1
    assert value_sha(prior_crossing) == review['priorCrossingBodySha256']
    assert [s['plannedKey'] for s in review['segments']] == ['LABTOOL_PWR_0029', 'LABTOOL_LOCAL_0333']
    assert [o['key'] for o in ops] == [s['plannedKey'] for s in review['segments']]
    ac = []
    for op, approved in zip(ops, review['segments']):
        assert value_sha(op) == approved['plannedOperationSha256']
        assert op['net'] == review['net'] and op['layerId'] == 1
        assert op['widthMil'] == approved['widthMilRequested']
        assert q(op['widthMil']) == approved['widthMilSerialized']
        values = op['startXYMil'] + op['endXYMil']
        assert values == approved['originalACmil']
        ac.append(tuple(map(fraction, values)))
    assert tuple(fraction(prior_crossing[k]) for k in ('startX', 'startY', 'endX', 'endY')) == ac[1]
    assert prior_crossing['netName'] == '+5V_AFE' and prior_crossing['layerId'] == 1 and prior_crossing['width'] == 8
    a, c, d, e = ac[0][:2], ac[0][2:], ac[1][:2], ac[1][2:]
    v, w, delta = (c[0]-a[0], c[1]-a[1]), (e[0]-d[0], e[1]-d[1]), (d[0]-a[0], d[1]-a[1])
    def cross(p, z): return p[0]*z[1] - p[1]*z[0]
    denominator = cross(v, w)
    assert denominator
    t, u = cross(delta, w)/denominator, cross(delta, v)/denominator
    assert 0 < t < 1 and 0 < u < 1
    exact_b = a[0]+t*v[0], a[1]+t*v[1]
    assert [str(x) for x in exact_b] == review['exactIntersectionMil']
    b = tuple(exact_q4_fraction(x) for x in exact_b)
    assert [float(x) for x in b] == review['onlyApprovedSerializedJunctionMil'] == [1189.5335, 914.9902]
    bound = fraction(review['knownNativePerAxisSerializationBoundMil'])
    assert bound == Fraction(1, 20000) and all(abs(x-z) <= bound for x,z in zip(b,exact_b))
    results = []
    for op, approved, segment in zip(ops, review['segments'], ac):
        pieces = [(*segment[:2], *b), (*b, *segment[2:])]
        for rid, required, body_sha in zip(approved['actualSplitIds'], pieces, approved['actualSplitBodySha256']):
            body = actual.get(('LINE', rid))
            assert body is not None and value_sha(body) == body_sha, ('APPROVED_PAIR_SPLIT_BODY_CHANGED', rid)
            assert tuple(fraction(body[k]) for k in ('startX', 'startY', 'endX', 'endY')) == required
            assert body['netName'] == '+5V_AFE' and body['layerId'] == 1 and body['width'] == approved['widthMilSerialized']
        results.append(dict(plannedKey=op['key'], net=op['net'], layerId=1,
                            widthMil=approved['widthMilSerialized'], originalACmil=approved['originalACmil'],
                            actualSplitIds=approved['actualSplitIds'], normalizedSegmentsMil=[[float(x) for x in p] for p in pieces]))
    return dict(net='+5V_AFE', layerId=1, exactIntersectionMil=[str(x) for x in exact_b],
                serializedJunctionMil=[float(x) for x in b], perAxisSerializationDeltaMil=[float(x-z) for x,z in zip(b,exact_b)],
                perAxisKnownGridBoundMil=float(bound), segments=results, normalizedNativeGeometryExact=True,
                originalVsActualCenterlineUnionExact=False, physicalCopperUnionEqualVsUnserializedPlan=False)


def linear_points(ring):
    if not ring or not isinstance(ring[0], (int, float)):
        return None
    nums = []
    for token in ring:
        if isinstance(token, str):
            if token != 'L':
                return None
        else:
            fraction(token)
            nums.append(token)
    assert len(nums) >= 6 and len(nums) % 2 == 0, 'MALFORMED_L_ONLY_RING'
    return list(zip(nums[::2], nums[1::2]))


def simple_cycle(points):
    """Only exact duplicates/collinear intermediate vertices can disappear."""
    pts = []
    for point in points:
        if not pts or point != pts[-1]:
            pts.append(point)
    if len(pts) > 1 and pts[-1] == pts[0]:
        pts.pop()
    changed = True
    while changed and len(pts) > 3:
        changed = False
        kept = []
        for i, b in enumerate(pts):
            a, c = pts[i - 1], pts[(i + 1) % len(pts)]
            if ((b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0])
                    and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) >= 0):
                changed = True
            else:
                kept.append(b)
        pts = kept
    assert len(set(pts)) >= 3, 'COLLAPSED_RING'
    # Choose an orientation-independent cyclic representative. This changes
    # neither the first-contour outer role nor the subsequent hole roles.
    def orientation(p):
        smallest = min(p)
        return min(tuple(p[i:] + p[:i]) for i, v in enumerate(p) if v == smallest)
    return min(orientation(pts), orientation(list(reversed(pts))))


def ring_key(ring, quantized=False):
    points = linear_points(ring)
    if points is None:
        # Curves are NOT approximated to authorize an edit. Their native arrays
        # must be byte-value identical, even if a tessellation looks similar.
        return ('CURVE_EXACT', json.dumps(ring, separators=(',', ':')))
    if quantized:
        points = [(int(Decimal(str(x)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP) * GRID),
                   int(Decimal(str(y)).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP) * GRID))
                  for x, y in points]
    else:
        points = [(fraction(x), fraction(y)) for x, y in points]
    return 'L', simple_cycle(points)


def complex_key(path, quantized=False):
    assert isinstance(path, list) and path, 'EMPTY_COMPLEX_POLYGON'
    return ring_key(path[0], quantized), Counter(ring_key(r, quantized) for r in path[1:])


def quantized_path(path):
    return [[q(v) if isinstance(v, (int, float)) else v for v in r]
            if linear_points(r) is not None else r for r in path]


def clip(paths, other=None, operation=None):
    if not paths and not other:
        return []
    c = pc.Pyclipper()
    c.PreserveCollinear = True
    if paths:
        c.AddPaths(paths, pc.PT_SUBJECT, True)
    if other:
        c.AddPaths(other, pc.PT_CLIP, True)
    return c.Execute(operation or pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)


def integer_area(paths):
    return sum(abs(pc.Area(p)) for p in paths) / SCALE ** 2


class Audit:
    def __init__(self):
        self.errors = []
        self.normalizations = []
        self.report = {'schema': 'stm32h747-independent-copper-readback-v1',
                       'nativeApiCalls': 0, 'nativeDesignModified': False,
                       'manufacturingReady': False, 'errors': self.errors,
                       'qualifiedNormalizations': self.normalizations}
        self.ground = None
        self.junctions = []
        self.current_manifest = None
        self.current_stage = None

    def need(self, condition, code, **detail):
        if not condition:
            self.errors.append(dict(code=code, **detail))
        return bool(condition)

    def geometry(self):
        if self.ground is None:
            helper = HERE / 'ground/plan-local-static-fill-clearance.py'
            self.ground = runpy.run_path(str(helper))
            self.report['geometryHelper'] = dict(path=str(helper), sha256=sha(helper),
                                                integerScalePerMm=SCALE)
        return self.ground

    def region(self, path):
        g = self.geometry()
        rings = []
        for i, ring in enumerate(path):
            pts = [(round(x * SCALE), round(y * SCALE)) for x, y in g['ring_points'](ring)]
            assert len(set(pts)) >= 3, 'DEGENERATE_INTEGER_RING'
            if (pc.Area(pts) > 0) != (i == 0):
                pts.reverse()
            rings.append(pts)
        return clip(rings)

    def fill_geometry(self, key, intended, actual):
        """Require exact contour identity, or the documented 4dp grid only."""
        exact = complex_key(intended) == complex_key(actual)
        effective = intended
        if not exact:
            if not self.need(complex_key(intended, True) == complex_key(actual, True),
                             'FILL_CONTOUR_NOT_EQUIVALENT', key=key):
                return False
            # Reject unqualified sub-grid drift. Actual vertices must be either
            # a requested native point or exactly a native 4dp serialized point.
            requested = {tuple(p) for r in intended for p in (linear_points(r) or [])}
            unqualified = [list(p) for r in actual for p in (linear_points(r) or [])
                           if p not in requested and (p[0] != q(p[0]) or p[1] != q(p[1]))]
            if not self.need(not unqualified, 'FILL_NON_GRID_COORDINATE_DRIFT', key=key,
                             sample=unqualified[:5]):
                return False
            effective = quantized_path(intended)
            # Use the same quantized domain only after the exact per-coordinate
            # condition above. This is not an area/hausdorff tolerance waiver.
            actual = quantized_path(actual)
            self.normalizations.append(dict(key=key, kind='native-4dp-mil-path-serialization',
                                            maxPerAxisBoundMil=.00005,
                                            maxPerAxisBoundMm=.00005 * MM))
        # Canonical exact rings already prove curved commands unchanged. Now
        # require both independent integer and double polygon region checks.
        a, b = self.region(effective), self.region(actual)
        xor = clip(a, b, pc.CT_XOR)
        integer_ok = not xor
        g = self.geometry()
        sa, sb = g['geom'](effective), g['geom'](actual)
        valid = sa.is_valid and sb.is_valid
        symmetric = sa.symmetric_difference(sb).area if valid else None
        # Polygon simplification with identical rational edges is authoritative;
        # GEOS double arithmetic may emit a zero-width edge with area zero, but
        # no positive area allowance is used.
        ok = self.need(integer_ok and valid and symmetric == 0,
                       'FILL_REGION_PROOF_FAILED', key=key, integerXorAreaMm2=integer_area(xor),
                       shapelyValidExpected=sa.is_valid, shapelyValidActual=sb.is_valid,
                       shapelySymmetricDifferenceAreaMm2=symmetric)
        return ok

    def receipts(self, manifest_path, manifest, stage):
        stages = [b['stage'] for b in manifest['batches']]
        assert len(stages) == len(set(stages)) and stage in stages, 'UNKNOWN_OR_DUPLICATE_STAGE'
        prefix = manifest['batches'][:stages.index(stage) + 1]
        baseline_path = scoped(manifest['sourcePath'], VALIDATION)
        assert sha(baseline_path) == manifest['sourceSha256'], 'BASELINE_HASH_CHANGED'
        previous_path, previous_sha = baseline_path, sha(baseline_path)
        created, operations, evidence = {}, [], []
        mh = sha(manifest_path)
        for batch in prefix:
            rp = HERE / ('native-pcb-' + batch['stage'] + '-receipt.json')
            rec = load(rp)
            assert rec['stage'] == batch['stage'], 'RECEIPT_STAGE_MISMATCH'
            assert rec['manifestHash'] == mh, 'RECEIPT_MANIFEST_HASH_MISMATCH'
            assert scoped(rec['manifestRelative'], HERE) == manifest_path, 'RECEIPT_MANIFEST_PATH_MISMATCH'
            assert scoped(rec['priorRelative'], VALIDATION) == previous_path, 'BROKEN_CAPTURE_CHAIN_PATH'
            assert rec['priorHash'] == previous_sha, 'BROKEN_CAPTURE_CHAIN_HASH'
            assert not rec.get('failure'), ('EXECUTOR_REPORTED_FAILURE', rec.get('failure'))
            # Not a proof of containment: completion/receipt coverage only.
            expected_touched = Counter((o['action'], o['type'], o.get('id'), o.get('key'))
                                       for o in batch['operations'])
            observed_touched = Counter((o['action'], o['type'], o.get('id'), o.get('key'))
                                       for o in rec['touched'])
            assert expected_touched == observed_touched, 'INCOMPLETE_OR_DUPLICATE_OPERATION_RECEIPT'
            expected_created = Counter((o['type'], o['key']) for o in batch['operations']
                                       if o['action'] in ('via', 'line', 'fill_create'))
            actual_created = Counter((o['type'], o['key']) for o in rec['created'])
            assert expected_created == actual_created, 'CREATED_KEY_RECEIPT_MISMATCH'
            for item in rec['created']:
                k = item['type'], item['key']
                assert k not in created and isinstance(item.get('id'), str) and item['id'], 'DUPLICATE_OR_EMPTY_CREATED_KEY'
                created[k] = item['id']
            cp = scoped(rec['path'], VALIDATION)
            assert sha(cp) == rec['sourceSha256'], 'READBACK_CAPTURE_HASH_CHANGED'
            evidence.append(dict(stage=batch['stage'], receiptPath=str(rp), receiptSha256=sha(rp),
                                 capturePath=str(cp), captureSha256=sha(cp),
                                 executorContainmentPassed=rec.get('containmentPassed'),
                                 executorIssues=rec.get('issues', [])))
            operations.extend(batch['operations'])
            previous_path, previous_sha = cp, sha(cp)
        self.report.update(manifestPath=str(manifest_path), manifestSha256=mh, stage=stage,
                           baselinePath=str(baseline_path), baselineSha256=sha(baseline_path),
                           actualPath=str(previous_path), actualSha256=previous_sha,
                           receiptEvidence=evidence, completedOperationCounts=dict(Counter(o['action'] for o in operations)))
        return source(baseline_path), source(previous_path), operations, created

    def new_via(self, op, body, rid):
        key = 'VIA:' + rid
        if not self.need(body is not None, 'CREATED_VIA_MISSING', key=key):
            return
        for f, value in [('centerX', op['xyMil'][0]), ('centerY', op['xyMil'][1]),
                         ('holeDiameter', op['drillMil']), ('viaDiameter', op['diameterMil'])]:
            self.need(scalar_serialization(body.get(f), value), 'CREATED_VIA_GEOMETRY',
                      key=key, field=f, expected=value, actual=body.get(f))
        required = dict(netName=op['net'], viaType='NORMAL', locked=False,
                        partitionId='', groupId=0, ruleName='', topSolderExpansion=None,
                        bottomSolderExpansion=None, unusedInnerLayers=[])
        for f, v in required.items():
            self.need(f in body and body[f] == v, 'CREATED_VIA_FIELD', key=key, field=f,
                      expected=v, actual=body.get(f))
        self.need(not (set(body) - set(required) - {'centerX', 'centerY', 'holeDiameter', 'viaDiameter'}),
                  'UNEXPECTED_CREATED_VIA_FIELD', key=key, fields=sorted(set(body) - set(required)
                  - {'centerX', 'centerY', 'holeDiameter', 'viaDiameter'}))

    def records(self, baseline, actual, ops, created):
        modify = {o['id']: o for o in ops if o['action'] == 'fill'}
        assert len(modify) == sum(o['action'] == 'fill' for o in ops), 'DUPLICATE_FILL_MODIFICATION'
        line_ops = [o for o in ops if o['action'] == 'line']
        buckets = {(o['net'], o['layerId']) for o in line_ops}
        old_line_metadata = defaultdict(list)
        coordinate_fields = {'startX', 'startY', 'endX', 'endY'}
        for (kind, _), old in baseline.items():
            if kind == 'LINE':
                old_line_metadata[old.get('netName'), old.get('layerId')].append(
                    {k: v for k, v in old.items() if k not in coordinate_fields})
        protected, changed = Counter(), []
        for key, old in baseline.items():
            kind, rid = key
            body = actual.get(key)
            if kind in VIEW:
                continue
            if kind == 'DOCHEAD':
                self.need(body is not None and body.get('uuid') == PCB and body.get('docType') == 'PCB',
                          'DOCUMENT_IDENTITY_CHANGED')
                continue
            if kind == 'FILL' and rid in modify:
                op = modify[rid]
                self.need(op['beforeBody'] == old, 'FROZEN_FILL_BEFORE_BODY_MISMATCH', id=rid)
                if not self.need(body is not None, 'MODIFIED_FILL_MISSING', id=rid):
                    continue
                diffs = fields(old, body)
                allowed = {'path'}
                if old.get('refs') is None and body.get('refs') == [None]:
                    allowed.add('refs')
                    self.normalizations.append(dict(key='FILL:' + rid, kind='refs-null-to-single-null-array'))
                self.need(set(diffs) <= allowed, 'MODIFIED_FILL_NON_PATH_FIELD', id=rid, fields=diffs)
                self.fill_geometry('FILL:' + rid, op['afterPath'], body['path'])
                changed.append('FILL:' + rid)
            elif kind == 'LINE' and (old.get('netName'), old.get('layerId')) in buckets:
                # Native may split/merge only the geometry in these buckets.
                if body is not None:
                    diffs = fields(old, body)
                    self.need(set(diffs) <= {'startX', 'startY', 'endX', 'endY'},
                              'OLD_LINE_NON_GEOMETRY_CHANGED', id=rid, fields=diffs)
                changed.append('LINE:' + rid)
            else:
                if self.need(body == old, 'PROTECTED_BODY_CHANGED', key=str(key), fields=fields(old, body)):
                    protected[kind] += 1
        known_created = {(t, rid) for (t, _), rid in created.items()}
        for key, body in actual.items():
            if key in baseline or key[0] in VIEW:
                continue
            if key[0] == 'LINE' and (body.get('netName'), body.get('layerId')) in buckets:
                # IDs returned by an earlier create can disappear after merge;
                # only per-bucket exact geometry can admit the replacement ID.
                allowed = {'partitionId', 'groupId', 'netName', 'layerId', 'startX', 'startY',
                           'endX', 'endY', 'width', 'locked', 'zIndex', 'refs'}
                self.need(not set(body) - allowed, 'NEW_LINE_UNKNOWN_FIELD', id=key[1],
                          fields=sorted(set(body) - allowed))
                metadata = {k: v for k, v in body.items() if k not in coordinate_fields}
                inherited = metadata in old_line_metadata[body.get('netName'), body.get('layerId')]
                default_new = (body.get('partitionId') == '' and body.get('groupId') == 0
                               and body.get('locked') is False and body.get('zIndex', -1) == -1
                               and body.get('refs') in (None, [None]))
                self.need(default_new or inherited,
                          'NEW_LINE_NONDEFAULT_METADATA', id=key[1], bodyWithoutCoordinates={k: v for k, v in body.items()
                          if k not in {'startX', 'startY', 'endX', 'endY'}})
                if inherited and not default_new:
                    self.normalizations.append(dict(key='LINE:' + key[1],
                        kind='new-native-merge-id-retains-exact-baseline-line-metadata'))
            else:
                self.need(key in known_created, 'UNRECEIPTED_NEW_RECORD', key=str(key))
        for op in ops:
            if op['action'] == 'via':
                rid = created['VIA', op['key']]
                self.need(('VIA', rid) not in baseline, 'CREATED_VIA_REUSED_OLD_ID', id=rid)
                self.new_via(op, actual.get(('VIA', rid)), rid)
            elif op['action'] == 'fill_create':
                rid = created['FILL', op['key']]
                self.need(('FILL', rid) not in baseline, 'CREATED_FILL_REUSED_OLD_ID', id=rid)
                b = actual.get(('FILL', rid))
                if not self.need(b is not None, 'CREATED_FILL_MISSING', id=rid):
                    continue
                identity = dict(netName=op['net'], layerId=op['layerId'], fillStyle='SOLID', locked=False,
                                partitionId='', groupId=0)
                for f, v in identity.items():
                    self.need(f in b and b[f] == v, 'CREATED_FILL_FIELD', id=rid, field=f, expected=v, actual=b.get(f))
                self.need(scalar_serialization(b.get('width'), op['widthMil']), 'CREATED_FILL_WIDTH', id=rid)
                self.need(not set(b) - set(identity) - {'width', 'path', 'zIndex', 'isBridgingCopper', 'networkList', 'refs'},
                          'CREATED_FILL_UNKNOWN_FIELD', id=rid)
                self.need(b.get('isBridgingCopper', False) is False and b.get('networkList', []) == []
                          and b.get('refs') in (None, [None]) and b.get('zIndex', -1) == -1,
                          'CREATED_FILL_NONDEFAULT_METADATA', id=rid)
                self.fill_geometry('FILL:' + rid, op['afterPath'], b['path'])
        counts = Counter(k[0] for k in baseline)
        after_counts = Counter(k[0] for k in actual)
        self.need(counts['VIA'] == 640 and counts['COMPONENT'] == 437 and counts['RULE'] == 18,
                  'UNEXPECTED_BASELINE_COUNTS', counts=dict(counts))
        expected_vias = sum(o['action'] == 'via' for o in ops)
        self.need(after_counts['VIA'] == 640 + expected_vias, 'CREATED_VIA_COUNT', expected=640 + expected_vias,
                  actual=after_counts['VIA'])
        self.need(len({created['VIA', o['key']] for o in ops if o['action'] == 'via'}) == expected_vias,
                  'DUPLICATE_CREATED_VIA_ID')
        expected_fills = sum(o['action'] == 'fill_create' for o in ops)
        self.need(after_counts['FILL'] == counts['FILL'] + expected_fills, 'CREATED_FILL_COUNT',
                  expected=counts['FILL'] + expected_fills, actual=after_counts['FILL'])
        self.need(len({created['FILL', o['key']] for o in ops if o['action'] == 'fill_create'}) == expected_fills,
                  'DUPLICATE_CREATED_FILL_ID')
        self.report.update(protectedExactBodyCounts=dict(protected), baselineCounts=dict(counts),
                           actualCounts=dict(after_counts), geometryEligibleOldRecordCount=len(changed),
                           originalPhysicalDrillPreservationQualification='All original 640 VIA, 437 COMPONENT, all ATTR, PAD_NET, free PAD and library-binding bodies exact; library documents are outside this PCB capture and require checkpoint audit.')

    def fills_no_added_copper(self, manifest, baseline, actual, ops, created):
        """Compare each changed parent's complete retained parent+lobe union.

        During a multi-stage fill sequence missing future lobes are expected;
        they are not reported as removed copper. Created pieces alone must never
        add copper beyond the original parent's region.
        """
        fill_plan = load(scoped(manifest['fillsPath'], HERE))
        lobe_parent = {o['key']: o['sourceParentPrimitiveId'] for o in fill_plan['fillCreateOperations']}
        applied_mods = {o['id']: o for o in ops if o['action'] == 'fill'}
        groups = {rid: [] for rid in applied_mods}
        for o in ops:
            if o['action'] == 'fill_create':
                parent = lobe_parent[o['key']]
                assert parent in groups, 'LOBE_CREATED_BEFORE_ITS_PARENT_CLEARANCE'
                b = actual.get(('FILL', created['FILL', o['key']]))
                if b:
                    groups[parent].append(b['path'])
        proofs = []
        for rid, lobes in groups.items():
            b = actual.get(('FILL', rid))
            if b is None:
                continue
            before = self.region(baseline['FILL', rid]['path'])
            after = clip([r for path in [b['path']] + lobes for r in self.region(path)])
            # Native 4dp path quantization can move a boundary by <=1.27 nm
            # per axis. Do NOT waive a positive copper sliver. Any such effect
            # is explicit FAIL for a separately reviewed typed qualification.
            added = clip(after, before, pc.CT_DIFFERENCE)
            self.need(not added, 'LOCAL_FILL_COPPER_ADDITION', parent=rid,
                      integerAddedCopperAreaMm2=integer_area(added))
            all_lobes = {k for k, p in lobe_parent.items() if p == rid}
            done = {o['key'] for o in ops if o['action'] == 'fill_create' and lobe_parent[o['key']] == rid}
            proofs.append(dict(parent=rid, createdLobes=len(lobes), finalLobeCount=len(all_lobes),
                               allParentLobesPresent=all_lobes == done,
                               addedCopperIntegerAreaMm2=integer_area(added)))
        self.report['parentAndLobeCopperAdditionProofs'] = proofs

    def lines(self, baseline, actual, ops):
        line_ops = [o for o in ops if o['action'] == 'line']
        route_buckets = {(o['net'], o['layerId']) for o in line_ops}
        expected, observed = defaultdict(list), defaultdict(list)
        widths = defaultdict(set)
        resolved_widths = {}
        for o in line_ops:
            logical = o['net'], o['layerId'], fraction(o['widthMil'])
            if logical in resolved_widths:
                continue
            variants = {fraction(b['width']) for key, b in actual.items()
                        if key[0] == 'LINE' and key not in baseline
                        and b.get('netName') == o['net'] and b.get('layerId') == o['layerId']
                        and b.get('width') in (o['widthMil'], q(o['widthMil']))}
            self.need(len(variants) <= 1, 'MIXED_NEW_LINE_WIDTH_SERIALIZATION',
                      net=o['net'], layer=o['layerId'], requestedMil=o['widthMil'],
                      actualVariantsMil=[float(v) for v in sorted(variants)])
            resolved = next(iter(variants)) if len(variants) == 1 else fraction(q(o['widthMil']))
            resolved_widths[logical] = resolved
            if resolved != fraction(o['widthMil']):
                self.normalizations.append(dict(kind='native-4dp-mil-line-width-serialization',
                    net=o['net'], layerId=o['layerId'], requestedWidthMil=o['widthMil'],
                    serializedWidthMil=float(resolved), maxBoundMil=.00005))
        for (kind, _), b in baseline.items():
            if kind == 'LINE' and (b.get('netName'), b.get('layerId')) in route_buckets:
                w = fraction(b['width'])
                widths[b['netName'], b['layerId']].add(w)
                expected[b['netName'], b['layerId'], w].append((b['startX'], b['startY'], b['endX'], b['endY']))
        for o in line_ops:
            w = resolved_widths[o['net'], o['layerId'], fraction(o['widthMil'])]
            widths[o['net'], o['layerId']].add(w)
            expected[o['net'], o['layerId'], w].append((*o['startXYMil'], *o['endXYMil']))
        for (kind, rid), b in actual.items():
            if kind != 'LINE' or (b.get('netName'), b.get('layerId')) not in route_buckets:
                continue
            w = fraction(b['width'])
            if w not in widths[b['netName'], b['layerId']]:
                self.need(False, 'UNPLANNED_LINE_WIDTH', id=rid, width=b['width'])
            observed[b['netName'], b['layerId'], w].append((b['startX'], b['startY'], b['endX'], b['endY']))
        raw_expected = {bucket: list(segments) for bucket, segments in expected.items()}
        normalized_buckets = set()
        stage_order = [b['stage'] for b in self.current_manifest['batches']] if self.current_manifest else []
        for junction in self.junctions:
            review, diagnostic = junction['review'], junction['diagnostic']
            if stage_order.index(self.current_stage) < stage_order.index(review['stageFirstObserved']):
                continue
            if junction['kind'] == 'single':
                selected = [o for o in line_ops if o['key'] == review['plannedKey']]
                assert len(selected) == 1, 'MISSING_APPROVED_JUNCTION_ORIGINAL_OPERATION'
                op = selected[0]
                proof = focused_junction_proof(op, diagnostic['oldWideHorizontalBody'],
                                              diagnostic['oldWideVerticalBody'], actual, review, diagnostic['actualNewBodies'])
                replacements = [proof]
            else:
                selected = [next(o for o in line_ops if o['key'] == s['plannedKey']) for s in review['segments']]
                proof = focused_paired_junction_proof(selected, diagnostic['oldPriorCrossingBody'], actual, review)
                replacements = proof['segments']
            for selected_op, replacement in zip(selected, replacements):
                bucket = selected_op['net'], selected_op['layerId'], fraction(replacement['widthMil'])
                normalized_buckets.add(bucket)
                original_segment = tuple(selected_op['startXYMil'] + selected_op['endXYMil'])
                assert expected[bucket].count(original_segment) == 1, 'AMBIGUOUS_EXPECTED_JUNCTION_SEGMENT'
                expected[bucket].remove(original_segment)
                expected[bucket].extend(tuple(s) for s in replacement['normalizedSegmentsMil'])
            proof.update(kind='root-approved-hash-pinned-native-intersection-q4mil-serialization',
                         reviewPath=str(junction['path']), reviewSha256=junction['sha256'], diagnosticSha256=review['diagnosticSha256'])
            self.normalizations.append(proof)
        proofs = []
        for bucket in sorted(set(expected) | set(observed), key=str):
            a = canonical_segments(expected[bucket])
            b = canonical_segments(observed[bucket])
            raw_a = canonical_segments(raw_expected.get(bucket, []))
            raw_same = raw_a == b
            same = a == b
            self.need(same, 'LINE_UNION_NOT_EXACT', net=bucket[0], layer=bucket[1], widthMil=float(bucket[2]),
                      expectedSupportCount=len(a), actualSupportCount=len(b),
                      expectedGeometrySha256=value_sha(repr(a)), actualGeometrySha256=value_sha(repr(b)))
            proofs.append(dict(net=bucket[0], layerId=bucket[1], widthMil=float(bucket[2]),
                               expectedSegments=len(expected[bucket]), actualSegments=len(observed[bucket]),
                               exactRationalCenterlineUnionEqual=raw_same,
                               physicalCopperUnionEqual=raw_same,
                               physicalCopperUnionEqualVsUnserializedPlan=raw_same,
                               normalizedNativeGeometryExact=same,
                               rootSpecificJunctionNormalizationApplied=bucket in normalized_buckets,
                               physicalUnionProof=('Original unserialized AC and actual ABC are NOT equal. Only this fixed root-approved q4mil intersection split is compared to the exact normalized expected ABC; area is not an acceptance criterion.'
                                   if bucket in normalized_buckets else
                                   'Equal exact rational centerline sets at the same serialized width imply identical Minkowski sums with the same round-cap disk; no buffer tessellation tolerance is used.')))
        self.report['lineGeometryProofs'] = proofs

    def run(self, manifest_path, stage, junction_review_path=None, junction_review_sha=None):
        manifest = load(manifest_path)
        assert manifest['schema'] == 'stm32h747-labtool-reviewed-copper-bounded-execution-v1'
        assert manifest['PCBRequired'] == PCB
        for path_key, hash_key in [('routesPath', 'routesSha256'), ('fillsPath', 'fillsSha256'),
                                   ('rootReviewPath', 'rootReviewSha256')]:
            assert sha(scoped(manifest[path_key], HERE)) == manifest[hash_key], ('REVIEWED_INPUT_HASH_CHANGED', path_key)
        review = load(scoped(manifest['rootReviewPath'], HERE))
        assert review['approvedForBoundedNativeApplication'] is True and review['wholePcbFillRegenerationAuthorized'] is False
        assert review['sourceSha256'] == manifest['sourceSha256']
        assert review['routesSha256'] == manifest['routesSha256'] and review['fillsSha256'] == manifest['fillsSha256']
        assert not review['unresolvedPhysicalConflicts']
        self.verify_compilation(manifest)
        self.current_manifest, self.current_stage = manifest, stage
        assert bool(junction_review_path) == bool(junction_review_sha), 'JUNCTION_REVIEW_PATH_AND_HASH_BOTH_REQUIRED'
        if junction_review_path:
            paths = [junction_review_path] if isinstance(junction_review_path, (str, Path)) else junction_review_path
            hashes = [junction_review_sha] if isinstance(junction_review_sha, str) else junction_review_sha
            assert len(paths) == len(hashes) <= 2 and len(set(hashes)) == len(hashes), 'ONLY_TWO_DISTINCT_APPROVED_JUNCTION_CASES'
            for path, expected_sha in zip(paths, hashes):
                self.load_junction_review(path, expected_sha, manifest_path, manifest)
        baseline, actual, ops, created = self.receipts(manifest_path, manifest, stage)
        assert all(o['action'] in {'fill', 'fill_create', 'via', 'line'} for o in ops), 'UNEXPECTED_EXECUTION_SCOPE'
        self.records(baseline, actual, ops, created)
        self.lines(baseline, actual, ops)
        self.fills_no_added_copper(manifest, baseline, actual, ops, created)
        self.report['scopeQualification'] = ('This independently proves cumulative completed native PCB records and copper geometry only. '
            'It does not establish strict DRC, netlist/MCU-VSS graph reachability, CAM output, analog stability, or manufacturing approval.')

    def load_junction_review(self, path, expected_sha, manifest_path, manifest):
        path = scoped(path, HERE)
        assert expected_sha in {JUNCTION_REVIEW_SHA, PAIR_JUNCTION_REVIEW_SHA} and sha(path) == expected_sha, 'UNAPPROVED_JUNCTION_REVIEW_HASH'
        review = load(path)
        kind = 'single' if expected_sha == JUNCTION_REVIEW_SHA else 'pair'
        assert review['schema'] == ('root-specific-native-junction-serialization-qualification-v1' if kind == 'single'
                                    else 'root-specific-native-junction-serialization-pair-qualification-v1')
        assert review['approvedForAuditorNormalization'] is True
        assert review['globalGeometricToleranceAuthorized'] is False and review['nativePcbChangesAuthorizedByThisReview'] is False
        assert review['manifestSha256'] == sha(manifest_path)
        assert review['originalVsActualCenterlineUnionExact'] is False and review['originalVsActualPhysicalCopperUnionExact'] is False
        dp = scoped(review['diagnosticPath'], HERE)
        assert sha(dp) == review['diagnosticSha256']
        diagnostic = load(dp)
        assert diagnostic['manifestSha256'] == sha(manifest_path)
        assert diagnostic['actualSourceSha256'] == review['firstObservedActualSourceSha256']
        assert sha(scoped(diagnostic['actualSourcePath'], VALIDATION)) == review['firstObservedActualSourceSha256']
        prior_path = scoped(diagnostic['priorSourcePath'], VALIDATION)
        assert sha(prior_path) == diagnostic['priorSourceSha256']
        prior = source(prior_path)
        if kind == 'single':
            assert prior['LINE', review['oldWideHorizontalId']] == diagnostic['oldWideHorizontalBody']
            assert prior['LINE', review['oldWideVerticalId']] == diagnostic['oldWideVerticalBody']
            assert value_sha(diagnostic['oldWideHorizontalBody']) == review['oldWideHorizontalBodySha256']
            assert value_sha(diagnostic['oldWideVerticalBody']) == review['oldWideVerticalBodySha256']
        else:
            assert prior['LINE', review['priorCrossingId']] == diagnostic['oldPriorCrossingBody']
            assert value_sha(diagnostic['oldPriorCrossingBody']) == review['priorCrossingBodySha256']
        failed_path = scoped(review['failedOriginalAuditMustRemain'], HERE)
        failed_sha = ('4388b17cd27fcbcc47132b7d06e623f0e54dbc9ad7ede34c1b8349d3b36d0022' if kind == 'single'
                      else 'ef36357a29e40d91f84790c0710657d350d52d6ba7827b34c7ca93349db98072')
        assert sha(failed_path) == failed_sha
        failed = load(failed_path)
        assert failed['passed'] is False and failed['actualSha256'] == review['firstObservedActualSourceSha256']
        self.junctions.append(dict(kind=kind, path=path, sha256=sha(path), review=review, diagnostic=diagnostic))
        evidence = dict(path=str(path), sha256=sha(path),
            diagnosticPath=str(dp), diagnosticSha256=sha(dp), failedOriginalAuditPath=str(failed_path),
            failedOriginalAuditSha256=sha(failed_path), nativeGeometryChangeAuthorized=False,
            globalToleranceAuthorized=False, originalPhysicalExactEqualityClaimed=False)
        self.report.setdefault('specificJunctionReviews', []).append(evidence)
        if kind == 'single':
            self.report['specificJunctionReview'] = evidence

    def verify_compilation(self, manifest):
        """Independently bind every executable op to the root-reviewed inputs."""
        fills = load(scoped(manifest['fillsPath'], HERE))
        routes = load(scoped(manifest['routesPath'], HERE))
        assert fills['passed'] is True and not fills['blocked']
        assert fills['sourceSha256'] == manifest['sourceSha256']
        assert not routes.get('unroutedConnections', []) and not routes.get('exactLiteralCopperConflicts', [])
        expected = []
        for o in fills['fillModifyOperations']:
            assert o['layerId'] in {1, 2, 15, 16, 17, 18}
            assert o['copperAdditionAreaMm2'] < 1e-8
            expected.append(dict(action='fill', type='FILL', id=o['primitiveId'],
                                 beforeBody=o['beforeBody'], afterPath=o['afterPath'], localClearanceOnly=True))
        for o in fills['fillCreateOperations']:
            assert o['valid'] and o['nativeOuterClockwise'] and o['nativeHolesCounterclockwise']
            expected.append(dict(action='fill_create', type='FILL', key=o['key'], net=o['net'],
                                 layerId=o['layerId'], widthMil=o['widthMil'], afterPath=o['afterPath'],
                                 localClearanceOnly=True))
        for o in routes['newViaCreates']:
            assert abs(o['viaDiameterMm'] - .45) < 1e-9 and abs(o['holeDiameterMm'] - .2) < 1e-9
            assert set(o.get('allLayers', [1, 2, 15, 16, 17, 18])) == {1, 2, 15, 16, 17, 18}
            expected.append(dict(action='via', type='VIA', key=o['key'], net=o['net'],
                                 xyMil=[round(v / MM, 4) for v in o['xyMm']],
                                 diameterMil=o['viaDiameterMm'] / MM, drillMil=o['holeDiameterMm'] / MM))
        for o in routes['newLineCreates']:
            assert o['widthMm'] >= .1524 and math.isfinite(o['widthMm'])
            if o['layerId'] not in (1, 2):
                assert o['layerId'] == 15 and o['net'] == '-3V_AFE' and abs(o['widthMm'] - .25) < 1e-9
                assert approved_inner15_pair(o['startXYmm'], o['endXYmm']), 'UNAPPROVED_INNER15_SEGMENT'
            expected.append(dict(action='line', type='LINE', key=o['key'], net=o['net'],
                                 layerId=o['layerId'], startXYMil=[round(v / MM, 4) for v in o['startXYmm']],
                                 endXYMil=[round(v / MM, 4) for v in o['endXYmm']],
                                 widthMil=round(o['widthMm'] / MM, 8)))
        flattened = [o for b in manifest['batches'] for o in b['operations']]
        assert expected == flattened, 'EXECUTION_OPERATIONS_DIFFER_FROM_FROZEN_REVIEWED_INPUTS'
        for kind in ('VIA', 'LINE', 'FILL'):
            keys = [o['key'] for o in expected if o['type'] == kind and 'key' in o]
            assert len(keys) == len(set(keys)), ('DUPLICATE_PLANNED_KEY', kind)
        sites = [tuple(o['xyMil']) for o in expected if o['action'] == 'via']
        assert len(sites) == len(set(sites)), 'DUPLICATE_PLANNED_VIA_SITE'
        self.report['reviewedInputsIndependentlyRecompiledExact'] = True


def canonical_segments(segments):
    """Exact rational collinear interval union; permits splits and merges only."""
    lines = defaultdict(list)
    for segment in segments:
        x1, y1, x2, y2 = map(fraction, segment)
        dx, dy = x2 - x1, y2 - y1
        assert dx or dy, 'ZERO_LENGTH_LINE'
        denominator = math.lcm(dx.denominator, dy.denominator)
        ux, uy = int(dx * denominator), int(dy * denominator)
        divisor = math.gcd(abs(ux), abs(uy))
        ux, uy = ux // divisor, uy // divisor
        if ux < 0 or (ux == 0 and uy < 0):
            ux, uy = -ux, -uy
        support = ux * y1 - uy * x1
        a, b = ux * x1 + uy * y1, ux * x2 + uy * y2
        lines[ux, uy, support].append((min(a, b), max(a, b)))
    result = []
    for support, intervals in sorted(lines.items()):
        merged = []
        for a, b in sorted(intervals):
            if merged and a <= merged[-1][1]:
                merged[-1] = merged[-1][0], max(b, merged[-1][1])
            else:
                merged.append((a, b))
        result.append((support, tuple(merged)))
    return tuple(result)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', required=True, help='Reviewed execution JSON, project-relative or candidate-relative')
    ap.add_argument('--stage', required=True)
    ap.add_argument('--junction-review', action='append', help='Repeat only for the two separately approved, hash-pinned serialization cases')
    ap.add_argument('--junction-review-sha', action='append')
    args = ap.parse_args()
    audit = Audit()
    try:
        path = scoped(args.manifest, HERE)
        assert path.suffix == '.json'
        audit.run(path, args.stage, args.junction_review, args.junction_review_sha)
    except Exception as exc:
        audit.errors.append(dict(code='FAIL_CLOSED_EXCEPTION', message=str(exc),
                                 traceback=traceback.format_exc()))
    audit.report.update(passed=not audit.errors, auditedUtc=datetime.now(timezone.utc).isoformat(),
                        auditorPath=str(Path(__file__).resolve()), auditorSha256=sha(Path(__file__)))
    folder = HERE / 'audits'
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    safe_stage = ''.join(c for c in args.stage if c.isalnum() or c == '_')[:60]
    report = folder / f'copper-readback-{safe_stage}-{stamp}-{uuid.uuid4().hex[:8]}.json'
    with report.open('x', encoding='utf-8') as handle:
        json.dump(audit.report, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    print(json.dumps(dict(passed=not audit.errors, report=str(report), sha256=sha(report),
                          errors=len(audit.errors), qualifiedNormalizations=len(audit.normalizations)), ensure_ascii=False))
    return 0 if not audit.errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
