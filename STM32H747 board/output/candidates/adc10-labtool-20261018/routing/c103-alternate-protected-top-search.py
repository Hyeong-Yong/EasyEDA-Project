"""Bounded C103/C160 alternative search only; no native calls or source edits."""
import ast
import json
import math
from pathlib import Path
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent.parent
helper = HERE / 'independent-eight-positive-ground-stitch-review.py'
tree = ast.parse(helper.read_text(encoding='utf8'))
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
stop = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'tree' for t in n.targets))
fn.body = fn.body[:stop] + [ast.Return(value=ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[]))]
tree.body = [n for n in tree.body if not isinstance(n, ast.If)]
ns = {'__file__': str(helper), '__name__': 'c103_alternate_model'}
exec(compile(ast.fix_missing_locations(tree), str(helper), 'exec'), ns)


def main():
    m = ns['main']()
    h, a, mm = ns['H'], ns['A'], ns['MM']
    rows, attrs, docs = m['rows'], m['at'], m['docs']
    refs = {at['Designator']: cid for cid, at in attrs.items() if 'Designator' in at}
    copper = [q for q in m['copper'] if not q['key'].startswith(('PAD:C103:', 'PAD:C160:'))]
    ct = STRtree([q['shape'] for q in copper])
    courts = [(r, s) for r, s in m['courts'] if r not in ('C103', 'C160')]
    court_tree = STRtree([s for r, s in courts])
    local = {}
    for ref in ('C103', 'C160'):
        fp = docs['FOOTPRINT', attrs[refs[ref]]['Footprint']]
        pads, court = h['footprint'](fp)
        local[ref] = pads, court
    target = next(q for q in m['copper'] if q['key'].startswith('PAD:U9:2:'))['shape'].centroid
    vin = (target.x, target.y)
    probe = LineString([(22.4, 72.775), vin]).buffer(.1016)
    blockers = [dict(key=q['key'], net=q['net'], layers=q['layers'],
                     boundsMm=list(q['shape'].bounds), sourceOriginal=not q['new'])
                for q in copper if 1 in q['layers'] and q['net'] != '+5v_afe'
                and q['shape'].distance(probe) < .1535]
    candidates = {}
    reject = {}
    for ref in ('C103', 'C160'):
        pads, court = local[ref]
        accepted, stats = [], {}
        for angle in (0, 90, 180, 270):
            for ix in range(40):
                x = 24 + ix * .2
                for iy in range(31):
                    y = 69 + iy * .2
                    env = h['world'](court, (x, y), angle)
                    if any(env.intersects(courts[int(i)][1]) for i in court_tree.query(env)):
                        stats['court'] = stats.get('court', 0) + 1
                        continue
                    world, bad = {}, False
                    for num, (s, pb) in pads.items():
                        s = h['world'](s, (x, y), angle)
                        net = '+5v_afe' if num == '1' else 'gnd'
                        for index in ct.query(s.buffer(.17)):
                            actor = copper[int(index)]
                            if 1 in actor['layers'] and actor['net'] != net and s.distance(actor['shape']) < (.1535 if actor['new'] else .17):
                                bad = True
                                break
                        if bad:
                            break
                        world[num] = s
                    if bad:
                        stats['padCu'] = stats.get('padCu', 0) + 1
                        continue
                    center = world['1'].centroid
                    distance = math.dist((center.x, center.y), vin)
                    if ref == 'C103' and distance > 5:
                        stats['vinDistanceOver5mm'] = stats.get('vinDistanceOver5mm', 0) + 1
                        continue
                    accepted.append(dict(ref=ref, xyMm=[round(x, 4), round(y, 4)], angle=angle,
                                         signalXYmm=[center.x, center.y], groundXYmm=list(world['2'].centroid.coords)[0],
                                         directVinDistanceMm=distance, _pads=world, _court=env))
        accepted.sort(key=lambda p: (p['directVinDistanceMm'], math.dist(p['xyMm'], [28.8, 71.8])))
        candidates[ref] = accepted
        reject[ref] = stats
        print(ref, 'valid placements', len(accepted), flush=True)
    # Literal route probes protect every source/new copper net, including the
    # four-pin high-impedance AFE_OFFSET_FILTER network. Only C103/C160 pads are
    # removed because these are the only two proposed moved components.
    positive_obstacles = [q['shape'].buffer(.1535 + .1016, resolution=32) for q in copper
                          if 1 in q['layers'] and q['net'] != '+5v_afe'
                          and q['shape'].intersects(LineString([(24, 69), (32, 76)]).envelope.buffer(2))]
    blocked = unary_union(positive_obstacles)
    route_options = []
    for p in candidates['C103'][:200]:
        start = tuple(p['signalXYmm'])
        if Point(start).intersects(blocked):
            continue
        paths = [[start, vin]]
        for ix in range(36):
            x = 24 + ix * .2
            for iy in range(24):
                paths.append([start, (x, 70.5 + iy * .15), vin])
        paths.sort(key=lambda pts: sum(math.dist(a, b) for a, b in zip(pts, pts[1:])))
        best = next((pts for pts in paths if sum(math.dist(a, b) for a, b in zip(pts, pts[1:])) <= 5
                     and not LineString(pts).intersects(blocked)), None)
        if best:
            route_options.append(dict(placement=p, pathXYmm=best,
                                      lengthMm=sum(math.dist(a, b) for a, b in zip(best, best[1:]))))
    pair_options = []
    for option in sorted(route_options, key=lambda x: x['lengthMm']):
        p = option['placement']
        for q in candidates['C160']:
            if p['_court'].intersects(q['_court']):
                continue
            if any(s.distance(t) < .1535 for n, s in p['_pads'].items() for k, t in q['_pads'].items() if n != k):
                continue
            pair_options.append(dict(C103=p, C160=q, c103VinRouteXYmm=option['pathXYmm'],
                                     c103VinRouteLengthMm=option['lengthMm']))
            break
        if len(pair_options) >= 5:
            break
    def public(p):
        return {k: v for k, v in p.items() if not k.startswith('_')}
    output = dict(schema='c103-alternate-two-part-protected-top-space-exploration-v1',
                  nativeCalls=0, nativeModified=False, sourceSha256=m['plan']['sourceSha256'],
                  frozenV2Sha256=ns['ROUTE_SHA'], placementSha256=m['plan']['placementSha256'],
                  U9VinXYmm=vin, directLeftCandidateBlockers=blockers,
                  acceptedPlacements={k: len(v) for k, v in candidates.items()}, searchRejections=reject,
                  testedCenterRegionMm=[24, 69, 31.8, 75], gridMm=.2,
                  topOnlyC103VinUnder5mmRouteCount=len(route_options),
                  pairOptions=[dict(C103=public(v['C103']), C160=public(v['C160']),
                                    c103VinRouteXYmm=v['c103VinRouteXYmm'], c103VinRouteLengthMm=v['c103VinRouteLengthMm']) for v in pair_options],
                  conclusion=('PARTIAL_GEOMETRIC_OPTION_REQUIRES_BOTH_GND_STITCH_AND_FULL_POWER_TREE_REROUTE_REVIEW'
                              if pair_options else 'NO_TWO_PART_TOP_OPTION_FOUND_WITHIN_REVIEWED_BOUNDED_REGION'),
                  limitations=['This is an alternative-space search, not an executable placement or final route module.',
                               'Only C103/C160 positions were variable; original copper deletion and unrelated placement changes are not proposed.',
                               'No GND return/site is approved by this search; all6/drill screens and actual MCU-VSS connectivity remain required.',
                               'The left candidate is blocked by original +3V3 copper as recorded; moving only a new low-impedance AFE_REF_2V5 branch cannot remove that original obstruction.',
                               'A no-option result is bounded to the stated grid, region, conservative native courts and direct/one-bend TOP paths, not a proof that all possible layouts are impossible.'])
    out = HERE / 'routing/c103-alternate-protected-top-space-v1.json'
    assert not out.exists()
    out.write_text(json.dumps(output, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(path=str(out), sha256=h['sha'](out), pairOptions=len(pair_options),
                          routeOptions=len(route_options), blockers=blockers)), flush=True)


if __name__ == '__main__':
    main()
