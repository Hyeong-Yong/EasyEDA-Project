"""Read-only reference-cap correction proof; invalid nested holes are NOT repaired."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
M = runpy.run_path(str(HERE / 'audit-adc10-strip-dc-graph-ground-20261018.py'))
PARSE, BM = M['M']['parse'], M['BM']
PLAN = HERE / 'strip/adc10-reference-courtyard-correction-20261018.json'
PLAN_SHA = '526d89e8e62a11fa5d389bb5434828ed068b75eda322830c82d8c29ff1836261'
BEFORE = ROOT / 'output/validation/native-adc10-pcb-strip_routes_lines_5-20261018.epru'
OLD = ROOT / 'output/validation/native-adc10-pcb-strip_routes_fill-20261018.epru'
ACTUAL = ROOT / 'output/validation/native-adc10-pcb-ref_courtyard-20261018.epru'
MM = .0254


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert sha(PLAN) == PLAN_SHA
    plan = json.loads(PLAN.read_text())
    before, _ = PARSE(BEFORE)
    old, _ = PARSE(OLD)
    actual, _ = PARSE(ACTUAL)
    assert sha(BEFORE) == plan['sourceSha256']
    checks, errors = [], []

    def check(ok, test, detail=None):
        item = {'test': test, 'passed': bool(ok)}
        if detail is not None: item['detail'] = detail
        checks.append(item)
        if not ok: errors.append(item)

    expected = copy.deepcopy(before)
    allowed = set()
    moves = []
    for move in plan['componentMoves']:
        cid = move['componentId']
        k = 'COMPONENT', cid
        check(before[k] == move['beforeBody'], 'Exact before component ' + move['ref'])
        target = dict(move['afterBody'])
        target.update(x=round(target['x'], 4), y=round(target['y'], 4))
        expected[k] = target
        allowed.add(k)
        check(actual[k] == target, 'Only approved component XY plus exact4decimal-mil serialization ' + move['ref'])
        dx = move['afterBody']['x'] - before[k]['x']
        dy = move['afterBody']['y'] - before[k]['y']
        owned = []
        for ak, body in before.items():
            if ak[0] != 'ATTR' or body.get('parentId') != cid: continue
            e = dict(body)
            if e.get('x') is not None and e.get('y') is not None:
                e.update(x=round(e['x']+dx, 4), y=round(e['y']+dy, 4))
            expected[ak] = e
            allowed.add(ak)
            check(actual.get(ak) == e, 'Owned ATTR rigid XY only ' + move['ref']+'.'+body['key'])
            owned.append(ak[1])
        moves.append({'ref': move['ref'], 'componentId': cid, 'actualXYmm': [target['x']*MM, target['y']*MM], 'ownedATTRIds': owned})
    expected_line = {k: b for k, b in before.items() if k[0] == 'LINE'}
    requested_delete = {('LINE', d['id']) for d in plan['deleteOnlyNewPhase2Lines']}
    for d in plan['deleteOnlyNewPhase2Lines']:
        k = 'LINE', d['id']
        check(before[k] == d['beforeBody'], 'Exact deleted phase2 leaf guard '+d['id'])
        check(k not in old, 'Requested leaf deletion never targets original pre-phase2 LINE '+d['id'])
        expected_line.pop(k)
    for i, create in enumerate(plan['newLineCreates']):
        expected_line['LINE', 'planned-'+str(i)] = {
            'layerId': create['layerId'], 'netName': create['net'],
            'startX': round(create['startXMil'], 4), 'startY': round(create['startYMil'], 4),
            'endX': round(create['endXMil'], 4), 'endY': round(create['endYMil'], 4),
            'width': round(create['widthMil'], 4)}
    old_lines = {k: b for k, b in old.items() if k[0] == 'LINE'}
    check(all(actual.get(k) == b for k, b in old_lines.items()), 'Every original pre-phase2 LINE ID and body exact', {'count': len(old_lines)})
    missing_lines = {k for k in before.keys()-actual.keys() if k[0] == 'LINE'}
    extra_deleted = sorted(k[1] for k in missing_lines-requested_delete)
    check(all(('LINE', rid) not in old for rid in extra_deleted), 'All additionally normalized deleted LINE IDs are phase2-only', extra_deleted)
    nets = {c['net'] for c in plan['newLineCreates']}
    check(all(actual[k] == before[k] for k in before.keys() & actual.keys() if k[0] == 'LINE'),
          'Every surviving existing LINE full body exact; merges only replace IDs')
    new_line_keys = [k for k in actual.keys()-before.keys() if k[0] == 'LINE']
    allowed_widths = {round(c['widthMil'], 4) for c in plan['newLineCreates']}
    allowed_widths |= {before[k]['width'] for k in missing_lines}
    required_line_keys = {'partitionId', 'groupId', 'netName', 'layerId', 'startX', 'startY', 'endX', 'endY', 'width', 'locked', 'zIndex'}
    check(all(set(actual[k]) == required_line_keys and actual[k]['netName'] in nets and actual[k]['layerId'] == 1
              and actual[k]['width'] in allowed_widths and actual[k]['partitionId'] == '' and actual[k]['groupId'] == 0
              and actual[k]['locked'] is False and actual[k]['zIndex'] == -1 for k in new_line_keys),
          'All created/normalized LINE records stay in requested nets/layer/width/default fields',
          {'newLINECount': len(new_line_keys), 'allowedWidthsMil': sorted(allowed_widths)})
    geometry = []
    for net in sorted(nets):
        e = unary_union([BM['trackshape']('LINE', b) for b in expected_line.values() if b.get('layerId') == 1 and b.get('netName') == net])
        a = unary_union([BM['trackshape']('LINE', b) for (kind, rid), b in actual.items() if kind == 'LINE' and b.get('layerId') == 1 and b.get('netName') == net])
        xor, hd = e.symmetric_difference(a).area*MM*MM, e.hausdorff_distance(a)*MM
        check(xor == 0 and hd == 0, 'Exact aggregate copper, all widths, after requested leaf replacement '+net, {'XORmm2': xor, 'HausdorffMm': hd})
        geometry.append({'net': net, 'XORmm2': xor, 'HausdorffMm': hd})
    for k, body in before.items():
        if k[0] == 'LINE' and body.get('layerId') == 1 and body.get('netName') in nets: continue
        if k in allowed or k == ('FILL', 'e680230ef8d2c5dd') or k[0] == 'DOCHEAD': continue
        check(actual.get(k) == body, 'Protected body exact '+k[0]+':'+k[1])
    unplanned_membership = [k for k in (before.keys() ^ actual.keys()) if k[0] != 'LINE']
    check(not unplanned_membership, 'No non-LINE primitive membership changes', unplanned_membership)
    fillplan = plan['fillPathUpdates'][0]
    fk = 'FILL', fillplan['id']
    check({k: b for k, b in before[fk].items() if k != 'path'} == {k: b for k, b in actual[fk].items() if k != 'path'}, 'All TOP GND non-path body fields exact')
    def q(value):
        if isinstance(value, list): return [q(v) for v in value]
        return round(value, 4) if isinstance(value, (int, float)) and not isinstance(value, bool) else value
    check(actual[fk]['path'] == q(fillplan['afterPath']), 'Actual FILL path equals exact4decimal-mil approved path, no hidden repair')
    rings = [BM['polyline'](p) for p in actual[fk]['path']]
    poly = Polygon(rings[0], rings[1:])
    holes = [Polygon(r) for r in rings[1:]]
    nested = []
    for i, a in enumerate(holes, 1):
        for j, b in enumerate(holes, 1):
            if i != j and a.contains(b):
                nested.append({'containingPathIndex': i, 'containedPathIndex': j, 'containedAreaMm2': b.area*MM*MM,
                    'containedBoundsMm': [v*MM for v in b.bounds], 'sameWinding': a.exterior.is_ccw == b.exterior.is_ccw})
    check(poly.is_valid, 'Actual outer-with-holes polygon topology valid; never silently repaired', {'reason': explain_validity(poly), 'nestedPairs': nested})
    planned_rings = [BM['polyline'](p) for p in fillplan['afterPath']]
    planned_poly = Polygon(planned_rings[0], planned_rings[1:])
    check(planned_poly.is_valid, 'Approved correction outer-with-holes topology valid', explain_validity(planned_poly))
    report = {'schema': 'stm32h747-reference-courtyard-readback-independent-20261018-v1', 'passed': not errors,
        'sourcePath': str(ACTUAL), 'sourceSha256': sha(ACTUAL), 'beforePath': str(BEFORE), 'beforeSha256': sha(BEFORE),
        'planPath': str(PLAN), 'planSha256': PLAN_SHA, 'componentMoves': moves, 'additionalNormalizedDeletedLINEIds': extra_deleted,
        'prePhase2ProtectedLINECount': len(old_lines), 'copperGeometryProof': geometry,
        'groundContourCount': len(rings), 'groundOuterMinusHolesTopologyValid': poly.is_valid,
        'groundValidity': explain_validity(poly), 'groundNestedPairs': nested,
        'errors': errors, 'checks': checks, 'liveAPICalls': 0, 'nativeFilesWritten': 0,
        'limitations': ['This report intentionally FAILS for nested holes in both approved and native path. No buffer(0) or automatic native repair is accepted.',
            'Nested contour may have fill-rule-specific semantics. Require bounded reviewed correction plus actual native/DRC/CAM validation before ground approval.',
            'Same-net all-width copper unions exactly match; additional removed IDs belong only to new phase2 routes and all old original LINE bodies remain exact.',
            'No fabrication approval or final DRC claim.']}
    out = HERE / 'adc10-reference-courtyard-native-readback-independent-audit-20261018.json'
    out.write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'passed': not errors, 'path': str(out), 'sha256': sha(out), 'failedTests': [e['test'] for e in errors],
        'additionalNormalizedDeletedLINEIds': extra_deleted, 'groundNestedPairs': nested}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == '__main__': main()
