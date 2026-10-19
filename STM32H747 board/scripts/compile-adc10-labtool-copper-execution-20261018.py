"""Compile reviewed offline copper into bounded public-API operations only.

Never writes native PCB source or connects to EasyEDA. Explicit input hashes
are required; this is not permission to regenerate pours or discard islands.
"""
import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
MM = .0254
LAYERS = {1, 2, 15, 16, 17, 18}
APPROVED_INNER15 = {
    ((40.3, 31.7), (13.8, 35.5)),
    ((13.8, 35.5), (12.2, 36.9)),
    ((12.2, 36.9), (8.9, 37.5)),
}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_source(p):
    rows = {}
    for line in p.read_text(encoding='utf-8-sig').splitlines():
        if '||' not in line:
            continue
        h, b = line.split('||', 1)
        h = json.loads(h)
        key = h['type'], h.get('id')
        assert key not in rows, key
        rows[key] = json.loads(b.removesuffix('|'))
    return rows


def frozen(relative, expected):
    p = (HERE / relative).resolve()
    assert p.is_relative_to(HERE.resolve()) and p.suffix == '.json'
    assert sha(p) == expected, f'Reviewed input changed: {p}'
    return p, json.loads(p.read_text(encoding='utf-8-sig'))


def milpoint(xy):
    assert len(xy) == 2 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in xy)
    assert 0 < xy[0] < 100 and 0 < xy[1] < 154, xy
    return [round(v / MM, 4) for v in xy]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, help='Reviewed actual native readback under output/validation')
    ap.add_argument('--source-sha', required=True)
    ap.add_argument('--routes', required=True)
    ap.add_argument('--routes-sha', required=True)
    ap.add_argument('--fills', required=True)
    ap.add_argument('--fills-sha', required=True)
    ap.add_argument('--review', required=True, help='Frozen root review with explicit mask/island approvals')
    ap.add_argument('--review-sha', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source = (ROOT / args.source).resolve()
    assert source.is_relative_to((ROOT / 'output/validation').resolve()) and source.suffix == '.epru'
    assert sha(source) == args.source_sha
    source_sha = sha(source)
    rows = read_source(source)
    assert sum(k[0] == 'COMPONENT' for k in rows) == 437
    assert sum(k[0] == 'VIA' for k in rows) == 640
    assert sum(k[0] == 'RULE' for k in rows) == 18
    rp, routes = frozen(args.routes, args.routes_sha)
    fp, fills = frozen(args.fills, args.fills_sha)
    vp, review = frozen(args.review, args.review_sha)
    assert fills['passed'] and not fills['blocked']
    assert fills['sourceSha256'] == source_sha
    assert review['sourceSha256'] == source_sha
    assert review['routesSha256'] == sha(rp) and review['fillsSha256'] == sha(fp)
    assert review['approvedForBoundedNativeApplication'] is True
    assert review['wholePcbFillRegenerationAuthorized'] is False
    assert not review['unresolvedPhysicalConflicts']
    assert not routes.get('unroutedConnections', [])
    assert not routes.get('exactLiteralCopperConflicts', [])
    ops = []
    for p in fills['fillModifyOperations']:
        assert rows['FILL', p['primitiveId']] == p['beforeBody']
        assert p['layerId'] in LAYERS
        assert p['copperAdditionAreaMm2'] < 1e-8
        ops.append(dict(action='fill', type='FILL', id=p['primitiveId'],
                        beforeBody=p['beforeBody'], afterPath=p['afterPath'],
                        localClearanceOnly=True))
    for p in fills['fillCreateOperations']:
        assert p['valid'] and p['layerId'] in LAYERS
        assert p['nativeOuterClockwise'] and p['nativeHolesCounterclockwise']
        ops.append(dict(action='fill_create', type='FILL', key=p['key'],
                        net=p['net'], layerId=p['layerId'], widthMil=p['widthMil'],
                        afterPath=p['afterPath'], localClearanceOnly=True))
    vias = routes['newViaCreates']
    assert len({p['key'] for p in vias}) == len(vias)
    sites = set()
    for p in vias:
        xy = milpoint(p['xyMm'])
        assert tuple(xy) not in sites, ('Duplicate through-via site', p)
        sites.add(tuple(xy))
        assert abs(p['viaDiameterMm'] - .45) < 1e-9
        assert abs(p['holeDiameterMm'] - .2) < 1e-9
        if 'allLayers' in p:
            assert set(p['allLayers']) == LAYERS
        ops.append(dict(action='via', type='VIA', key=p['key'], net=p['net'],
                        xyMil=xy, diameterMil=p['viaDiameterMm'] / MM,
                        drillMil=p['holeDiameterMm'] / MM))
    lines = routes['newLineCreates']
    assert len({p['key'] for p in lines}) == len(lines)
    linekeys = set()
    for p in lines:
        if p['layerId'] not in (1, 2):
            assert p['layerId'] == 15 and p['net'] == '-3V_AFE' and abs(p['widthMm'] - .25) < 1e-9
            pair = (p['startXYmm'], p['endXYmm'])
            # The frozen planner can emit 12.200000000000001 for 12.2.
            # Accept only IEEE representation noise AND identical native
            # 4dp-mil serialized endpoints, not a PCB geometry tolerance.
            assert any(
                all(abs(v - approved) <= 1e-12
                    for xy, target in zip(pair, exact)
                    for v, approved in zip(xy, target))
                and [milpoint(xy) for xy in pair] == [milpoint(xy) for xy in exact]
                for exact in APPROVED_INNER15
            ), 'Only three specifically reviewed Inner15 feed segments are authorized'
        a, b = milpoint(p['startXYmm']), milpoint(p['endXYmm'])
        assert a != b
        assert math.isfinite(p['widthMm']) and p['widthMm'] >= .1524
        key = p['net'], p['layerId'], p['widthMm'], tuple(sorted((tuple(a), tuple(b))))
        assert key not in linekeys, ('Duplicate line', p)
        linekeys.add(key)
        ops.append(dict(action='line', type='LINE', key=p['key'], net=p['net'],
                        layerId=p['layerId'], startXYMil=a, endXYMil=b,
                        widthMil=round(p['widthMm'] / MM, 8)))
    batches = []
    for phase, selected in [
        ('fill', [o for o in ops if o['action'] in ('fill', 'fill_create')]),
        ('via', [o for o in ops if o['action'] == 'via']),
        ('wire', [o for o in ops if o['action'] == 'line']),
    ]:
        size = 8 if phase == 'fill' else 25 if phase == 'via' else 40
        for i in range(0, len(selected), size):
            batches.append(dict(stage=f'copper_{phase}{i // size}', operations=selected[i:i + size]))
    plan = dict(schema='stm32h747-labtool-reviewed-copper-bounded-execution-v1',
                PCBRequired='0ac2a19168000d8e', sourcePath=str(source),
                sourceSha256=source_sha, routesPath=str(rp), routesSha256=sha(rp),
                fillsPath=str(fp), fillsSha256=sha(fp), rootReviewPath=str(vp),
                rootReviewSha256=sha(vp), batches=batches,
                operationCounts=dict(Counter(p['action'] for p in ops)),
                nativeApiCalls=0, nativeDesignModified=False, manufacturingReady=False)
    out = (HERE / args.output).resolve()
    assert out.is_relative_to(HERE.resolve()) and out.suffix == '.json'
    out.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(manifest=str(out), sha256=sha(out),
                          stages=[b['stage'] for b in batches], operationCounts=plan['operationCounts'])))


if __name__ == '__main__':
    main()
