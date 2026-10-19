"""Find one GND stitch per exact reviewed large lobe, no native/API writes."""
import argparse
import ast
import json
import math
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent.parent
ROUTE_SHA = 'c255e19d838132efe682fb9c024dd53e017a4fd0119a17732983efafc1f34048'
FANOUT = '3b7988d562c902b4'


def model():
    helper = HERE / 'independent-eight-positive-ground-stitch-review.py'
    text = helper.read_text(encoding='utf8').replace('STM32H747_labtool_107_placed_v5b_wip_20261018.epro2',
                                                   'STM32H747_labtool_107_placed_v6_wip_20261018.epro2')
    tree = ast.parse(text)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    stop = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'tree' for t in n.targets))
    fn.body = fn.body[:stop] + [ast.Return(value=ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[]))]
    tree.body = [n for n in tree.body if not isinstance(n, ast.If)]
    env = {'__file__': str(helper), '__name__': 'two_lobe_independent_model'}
    exec(compile(ast.fix_missing_locations(tree), str(helper), 'exec'), env)
    env['ROUTE'] = HERE / 'routing/frozen-combined-routing-v4.json'
    env['ROUTE_SHA'] = ROUTE_SHA
    return env, env['main']()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mask', required=True)
    ap.add_argument('--mask-sha', required=True)
    args = ap.parse_args()
    env, m = model()
    h, a, mm = env['H'], env['A'], env['MM']
    maskpath = Path(args.mask)
    if not maskpath.is_absolute():
        maskpath = HERE / maskpath
    assert maskpath.resolve().is_relative_to(HERE.resolve())
    assert h['sha'](maskpath) == args.mask_sha
    mask = json.loads(maskpath.read_text(encoding='utf8'))
    assert mask['sourceSha256'] == m['plan']['sourceSha256']
    assert any(r['sha256'] == ROUTE_SHA for r in mask['routes'])
    assert mask['passed'] and not mask['blocked']
    graphpath = HERE / 'ground/local-ground-lobe-connectivity-v6-routingv4-526-62vias.json'
    graphsha = '26d61300c601186ff2ede9395325f0d035ba2e09c70069edea7e9e25c9b5236f'
    assert h['sha'](graphpath) == graphsha
    graph = json.loads(graphpath.read_text(encoding='utf8'))
    assert graph['manifestSha256'] == args.mask_sha and graph['sourceSha256'] == m['plan']['sourceSha256']
    anchored_ids = {v['id'] for v in graph['originalViaAnchorAudit'] if v['reachesSelectedSourcePad']}
    assert len(anchored_ids) == 199 and not graph['unanchoredOriginalViaIds']
    rows, attrs, docs = m['rows'], m['at'], m['docs']
    cu, pads, drills, courts, fills = m['copper'], m['pads'], m['drills'], m['courts'], m['fills']
    vias = m['plan']['newViaCreates']
    assert len(vias) == 62 and len(drills) == 799
    ct, pt, dt, bt = STRtree([x['shape'] for x in cu]), STRtree([s for k, s in pads]), STRtree([s for k, s in drills]), STRtree([s for k, s in courts])
    fan = rows['VIA', FANOUT]
    assert fan['netName'] == 'GND'
    fanxy = (fan['centerX'] * mm, fan['centerY'] * mm)
    fan_shape = Point(fanxy).buffer(fan['viaDiameter'] * mm / 2, resolution=64).difference(
        Point(fanxy).buffer(fan['holeDiameter'] * mm / 2, resolution=64))
    # Independent literal TOP connection from the retained original fanout VIA
    # into actual U1:A17. No label/name-based connection is inserted.
    u1id = next(cid for cid, at in attrs.items() if at.get('Designator') == 'U1')
    u1 = rows['COMPONENT', u1id]
    u1fp = docs['FOOTPRINT', attrs[u1id]['Footprint']]
    pad = next(p for (k, _), (_, p) in u1fp.items() if k == 'PAD' and str(p['num']) == 'A17')
    pnet = m['pn'][u1id, 'A17']
    assert pnet == 'GND'
    u1pad = h['world'](a['pad_shape'](pad), (u1['x'] * mm, u1['y'] * mm), u1['angle'])
    local_ground = [x['shape'] for x in cu if not x['new'] and x['net'] == 'gnd' and 1 in x['layers']
                    and x['shape'].intersects(u1pad.union(fan_shape).envelope.buffer(.8))]
    united = unary_union(local_ground + [u1pad, fan_shape])
    components = [united] if united.geom_type == 'Polygon' else list(united.geoms)
    fan_to_mcu = any(s.intersection(u1pad).area > 1e-12 and s.intersection(fan_shape).area > 1e-12 for s in components)
    assert fan_to_mcu, 'Original fanout VIA cannot be proved to actual U1:A17 from literal TOP pad/trace copper'
    modifications = {o['primitiveId']: o for o in mask['fillModifyOperations']}
    old_ground_vias = {}
    for rid in anchored_ids:
        body = rows['VIA', rid]
        center = Point(body['centerX'] * mm, body['centerY'] * mm)
        old_ground_vias[rid] = (body, center.buffer(body['viaDiameter'] * mm / 2, resolution=64).difference(
            center.buffer(body['holeDiameter'] * mm / 2, resolution=64)))
    seas = []
    for f in fills:
        if f['net'] != 'GND' or f['layerId'] not in (15, 17, 18) or not f['valid']:
            continue
        regions = [('ORIGINAL_UNMODIFIED', f['id'], f['shape'])]
        if f['id'] in modifications:
            regions = [('MODIFIED_PARENT', f['id'], a['P']['geom'](modifications[f['id']]['afterPath']))]
            regions += [('PRESERVED_LOBE', q['key'], a['P']['geom'](q['afterPath'])) for q in mask['fillCreateOperations']
                        if q['sourceParentPrimitiveId'] == f['id']]
        for kind, key, shape in regions:
            contacts = [rid for rid, (body, annulus) in old_ground_vias.items()
                        if f['layerId'] not in body.get('unusedInnerLayers', [])
                        and shape.intersection(annulus).area > 1e-12] if shape.is_valid else []
            if contacts:
                seas.append(dict(originalFillId=f['id'], layerId=f['layerId'], finalKind=kind, finalKey=key,
                                 shape=shape, originalShape=f['shape'], anchoredOldViaIds=contacts))
    assert seas, 'No valid final inner GND polygon reaches actual MCU fanout'
    target_lobes = []
    for layer, area, preferred in [(1, 20.077817639411, (18.5, 74.8)), (2, 7.584511189036, (29.2, 32.5))]:
        selected = [q for q in mask['fillCreateOperations'] if q['net'] == 'GND' and q['layerId'] == layer
                    and abs(q['areaMm2'] - area) < 1e-7]
        assert len(selected) == 1, ('Exact reviewed lobe not unique', layer, area, [(q['key'], q['areaMm2']) for q in selected])
        q = selected[0]
        shape = a['P']['geom'](q['afterPath'])
        assert shape.is_valid
        target_lobes.append((q, shape, preferred))
    newvias, failures, evidence = [], [], []
    for lobe, polygon, preferred in target_lobes:
        bounds = polygon.bounds
        points = [(round(bounds[0] + .1 * ix, 4), round(bounds[1] + .1 * iy, 4))
                  for ix in range(math.ceil((bounds[2] - bounds[0]) / .1) + 1)
                  for iy in range(math.ceil((bounds[3] - bounds[1]) / .1) + 1)]
        points.sort(key=lambda p: math.dist(p, preferred))
        rejected, chosen, choices = {}, None, []
        def reject(reason):
            rejected[reason] = rejected.get(reason, 0) + 1
        for xy in points:
            center = Point(xy)
            via = center.buffer(.225, resolution=64)
            hole = center.buffer(.1, resolution=64)
            if not polygon.contains(via.buffer(.02)):
                reject('OUTSIDE_TARGET_LOBE')
                continue
            if any(via.intersects(courts[int(i)][1]) for i in bt.query(via)):
                reject('BODY_OR_CONSERVATIVE_COURTYARD')
                continue
            if any(via.distance(pads[int(i)][1]) < .06 for i in pt.query(via.buffer(.06))):
                reject('VIA_IN_PAD')
                continue
            if any(hole.distance(drills[int(i)][1]) < .301 for i in dt.query(hole.buffer(.301))):
                reject('ORIGINAL799_DRILL')
                continue
            if any(hole.distance(Point(v['xyMm']).buffer(.1, resolution=64)) < .301 for v in vias + newvias):
                reject('RESERVED62_OR_NEW_DRILL')
                continue
            bad = []
            for index in ct.query(via.buffer(.171)):
                other = cu[int(index)]
                required = .1535 if other['new'] else .17
                if other['net'] != 'gnd' and via.distance(other['shape']) < required:
                    bad.append(other['key'])
            if bad:
                reject('ALL6_NON_FILL_COPPER')
                continue
            anchors = [s for s in seas if s['originalShape'].intersection(via).area > 1e-8
                       and s['shape'].intersection(via).area > 1e-8]
            if not anchors:
                reject('NO_FINAL_INNER_MCU_SEA')
                continue
            choices.append((xy, via, hole, anchors))
            if len(choices) == 3:
                break
        chosen = choices[0] if choices else None
        if chosen is None:
            failures.append(dict(lobeKey=lobe['key'], rejected=rejected))
            continue
        xy, via, hole, anchors = chosen
        cuts = [dict(id=f['id'], net=f['net'], layerId=f['layerId'], originalPolygonValid=f['valid'])
                for f in fills if f['net'].casefold() != 'gnd' and via.buffer(.17).intersects(f['shape'].envelope)
                and (not f['valid'] or via.buffer(.17).intersects(f['shape']))]
        item = dict(key='FINAL_FLOATING_TOP20_GND_STITCH' if lobe['layerId'] == 1 else 'FINAL_FLOATING_BOTTOM7_GND_STITCH',
                    net='GND', xyMm=list(xy), viaDiameterMm=.45, holeDiameterMm=.20, allLayers=env['CU'],
                    targetPreservedLobeKey=lobe['key'], targetLobeLayer=lobe['layerId'],
                    entireViaInsideTargetLobe=True,
                    minimumOldNonFillCopperGapMm=min(via.distance(x['shape']) for x in cu if not x['new'] and x['net'] != 'gnd'),
                    minimumNewFrozenCopperGapMm=min(via.distance(x['shape']) for x in cu if x['new'] and x['net'] != 'gnd'),
                    minimumOriginal799DrillEdgeGapMm=min(hole.distance(s) for k, s in drills),
                    minimumReserved62DrillEdgeGapMm=min(hole.distance(Point(v['xyMm']).buffer(.1, resolution=64)) for v in vias),
                    minimumAnyPadCuGapMm=min(via.distance(s) for k, s in pads),
                    minimumConservativeCourtyardGapMm=min(via.distance(s) for k, s in courts),
                    requiresLocalFillAntipads=cuts)
        newvias.append(item)
        anchors_public = [dict(originalFillId=s['originalFillId'], layerId=s['layerId'], finalKind=s['finalKind'],
                               finalKey=s['finalKey'], candidateOriginalContactAreaMm2=s['originalShape'].intersection(via).area,
                               candidateFinalContactAreaMm2=s['shape'].intersection(via).area,
                               sourceAnchoredOriginalViaIds=s['anchoredOldViaIds'],
                               originalViaAnchorGraphSha256=graphsha) for s in anchors]
        evidence.append(dict(viaKey=item['key'], targetLobeKey=lobe['key'], targetLobeAreaMm2=polygon.area,
                             targetLobeBoundsMm=list(polygon.bounds),
                             targetAnnulusContactAreaMm2=via.difference(hole).intersection(polygon).area,
                             directSamePolygonInnerMCUAnchors=anchors_public, rejectedCandidates=rejected,
                             alternativeSitesNotAuthorizedForCreation=[dict(xyMm=list(v[0]),
                                 contacts=[dict(layerId=s['layerId'], finalKey=s['finalKey'],
                                                sourceAnchoredOriginalViaIds=s['anchoredOldViaIds']) for s in v[3]])
                                 for v in choices[1:]]))
        print(json.dumps(dict(viaKey=item['key'], xyMm=xy, anchors=anchors_public)), flush=True)
    output = dict(schema='final-two-large-floating-ground-stitches-v1', passed=not failures and len(newvias) == 2,
                  nativeCalls=0, nativeModified=False, manufacturingApproved=False,
                  sourcePath=str(m['source']), sourceSha256=m['plan']['sourceSha256'],
                  routesPath=str(env['ROUTE']), routesSha256=ROUTE_SHA,
                  placementPath=m['plan']['placementPath'], placementSha256=m['plan']['placementSha256'],
                  maskPath=str(maskpath), maskSha256=args.mask_sha,
                  existingWholeGroundGraphPath=str(graphpath), existingWholeGroundGraphSha256=graphsha,
                  checkpointPath=str(m['cp']), checkpointSha256=h['sha'](m['cp']),
                  newViaCreates=newvias, newLineCreates=[], failures=failures,
                  MCUVssPhysicalPad='U1:A17', originalMCUVssFanoutVia=FANOUT,
                  originalFanoutHasLiteralTopConnectionToMCUVss=fan_to_mcu,
                  originalFanoutXYmm=list(fanxy), lobeAndInnerPlaneProofs=evidence,
                  original640Vias799DrillsChanged=0, reservedPreviousNewViaCount=62,
                  targetLargeLobesDeleted=0, originalFillRegeneration=False,
                  requirements=['Root exact-site approval before native use.',
                                'Merge 2 vias with final526/62 routes and rebuild bounded all6 antipads; preserve both target lobes.',
                                'Final source/CAM/nativeDRC and all345GND/+3V3/702+2via connectivity audits remain required.'])
    out = HERE / 'routing/final-two-floating-ground-stitches-v1b.json'
    assert not out.exists(), 'Append a new filename rather than overwrite evidence'
    out.write_text(json.dumps(output, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(path=str(out), sha256=h['sha'](out), passed=output['passed'], failures=failures)), flush=True)
    return 0 if output['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
