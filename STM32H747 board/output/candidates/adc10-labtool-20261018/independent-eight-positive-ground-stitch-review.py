"""Offline exact eight positive-bypass GND stitch search against frozen V2.

No live API/source mutation, no existing component movement, no FILL rewrite.
"""
import json
import math
import runpy
from collections import Counter
from pathlib import Path
from shapely.affinity import rotate, scale, translate
from shapely.geometry import Point, Polygon, LineString, box
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RT = HERE / 'routing'
H = runpy.run_path(str(HERE / 'independent-pcb-placement-proposal.py'))
A = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-proposed-power-graph-20261018.py'))
MM = .0254
CU = [1, 2, 15, 16, 17, 18]
ROUTE = RT / 'frozen-combined-routing-v2.json'
ROUTE_SHA = 'fef1c7280edc8412c5f154f9663580f4ef49695746fb35250433ad02e4f59ed3'
TARGETS = ['C120', 'C123', 'C126', 'C129', 'C138', 'C141', 'C144', 'C147']


def main():
    assert H['sha'](ROUTE) == ROUTE_SHA
    plan = json.loads(ROUTE.read_text(encoding='utf8'))
    source = Path(plan['sourcePath'])
    assert H['sha'](source) == plan['sourceSha256']
    rows = H['parse'](source)
    at = H['attrs_of'](rows)
    cp = ROOT / 'output/checkpoints/STM32H747_labtool_107_placed_v5b_wip_20261018.epro2'
    docs, _ = H['READ'](cp)
    pn = {}
    for (kind, rid), body in rows.items():
        if kind == 'PAD_NET':
            encoded = json.loads(rid)
            pn[encoded[1], str(encoded[2])] = body.get('padNet') or ''
    copper, pads, drills, courts, fills, endpoints = [], [], [], [], [], {}

    def add(key, net, shape, layers, new=False):
        if shape.is_empty:
            return
        assert shape.is_valid, key
        copper.append(dict(key=key, net=(net or '').casefold(), shape=shape,
                           layers=tuple(layers), new=new))

    for (kind, rid), body in rows.items():
        if kind == 'COMPONENT':
            ref = at[rid]['Designator']
            doc = docs['FOOTPRINT', at[rid]['Footprint']]
            xy, angle = (body['x'] * MM, body['y'] * MM), body['angle']
            _, local_court = H['footprint'](doc)
            if body['layerId'] == 2:
                local_court = scale(local_court, xfact=1, yfact=-1, origin=(0, 0))
            courts.append((ref, H['world'](local_court, xy, angle)))
            for (pk, pid), (_, pad) in doc.items():
                if pk != 'PAD':
                    continue
                shape = A['pad_shape'](pad)
                if body['layerId'] == 2:
                    shape = scale(shape, xfact=1, yfact=-1, origin=(0, 0))
                shape = H['world'](shape, xy, angle)
                net = pn.get((rid, str(pad['num'])), '')
                layers = CU if pad['layerId'] == 12 else [body['layerId']]
                if set(layers) & set(CU):
                    add('PAD:' + ref + ':' + str(pad['num']) + ':' + str(pid), net, shape, layers)
                    if not shape.is_empty:
                        pads.append(('PAD:' + ref + ':' + str(pad['num']), shape))
                    if ref in TARGETS and str(pad['num']) == '2':
                        assert net == 'GND'
                        endpoints[ref] = (shape.centroid.x, shape.centroid.y)
                hole = pad.get('hole') or {}
                w, h = hole.get('width', 0) * MM, hole.get('height', 0) * MM
                if w and h:
                    # Envelope conservatively contains the exact slot/round
                    # drill, so an accepted .301mm gap is not optimistic.
                    hs = box(-w / 2, -h / 2, w / 2, h / 2)
                    hs = H['world'](hs, (pad['centerX'] * MM, pad['centerY'] * MM),
                                    pad.get('padAngle', 0) + pad.get('relativeAngle', 0))
                    if body['layerId'] == 2:
                        hs = scale(hs, xfact=1, yfact=-1, origin=(0, 0))
                    drills.append(('DRILL:' + ref + ':' + str(pid), H['world'](hs, xy, angle)))
        elif kind == 'VIA':
            center = Point(body['centerX'] * MM, body['centerY'] * MM)
            add('VIA:' + rid, body['netName'], center.buffer(body['viaDiameter'] * MM / 2, resolution=32), CU)
            drills.append(('DRILL:VIA:' + rid, center.buffer(body['holeDiameter'] * MM / 2, resolution=64)))
        elif kind == 'PAD' and body.get('hole'):
            hole = body['hole']
            hs = box(-hole['width'] * MM / 2, -hole['height'] * MM / 2,
                     hole['width'] * MM / 2, hole['height'] * MM / 2)
            drills.append(('DRILL:FREE:' + rid, H['world'](hs,
                (body['centerX'] * MM, body['centerY'] * MM), body.get('padAngle', 0))))
        elif kind in ('LINE', 'ARC', 'CARC') and body.get('layerId') in CU:
            a, z = (body['startX'] * MM, body['startY'] * MM), (body['endX'] * MM, body['endY'] * MM)
            points = [a, z] if kind == 'LINE' else H['G']['arc'](a, z, body['angle'])
            add(kind + ':' + rid, body.get('netName'), LineString(points).buffer(body['width'] * MM / 2, resolution=32), [body['layerId']])
        elif kind == 'POLY' and body.get('layerId') in CU:
            add(kind + ':' + rid, body.get('netName'), LineString(H['G']['ring_path'](body['path'])).buffer(body['width'] * MM / 2, resolution=32), [body['layerId']])
        elif kind == 'FILL' and body.get('layerId') in CU:
            shape = A['P']['geom'](body['path'])
            fills.append(dict(id=rid, net=body.get('netName') or '', layerId=body['layerId'],
                              shape=shape, valid=shape.is_valid, widthMil=body['width']))
    assert len(drills) == 799, len(drills)
    assert set(endpoints) == set(TARGETS)
    for line in plan['newLineCreates']:
        add(line['key'], line['net'], LineString([line['startXYmm'], line['endXYmm']]).buffer(line['widthMm'] / 2, resolution=32), [line['layerId']], True)
    for via in plan['newViaCreates']:
        add(via['key'], via['net'], Point(via['xyMm']).buffer(.225, resolution=64), CU, True)
    tree = STRtree([c['shape'] for c in copper])
    ptree, dtree, ctree = STRtree([s for _, s in pads]), STRtree([s for _, s in drills]), STRtree([s for _, s in courts])
    vias, lines, failures, diagnostics = [], [], [], []
    for ref in TARGETS:
        padxy = endpoints[ref]
        preferred = (padxy[0], padxy[1] - 1.0)
        candidates = [(round(padxy[0] + dx * .1, 4), round(padxy[1] + dy * .1, 4))
                      for dx in range(-25, 26) for dy in range(-25, 26)
                      if .65 <= math.hypot(dx * .1, dy * .1) <= 2.6]
        candidates.sort(key=lambda xy: (math.dist(xy, preferred), math.dist(xy, padxy)))
        reasons, chosen = Counter(), None
        for xy in candidates:
            center = Point(xy)
            cu = center.buffer(.225, resolution=64)
            hole = center.buffer(.1, resolution=64)
            stub = LineString([padxy, xy]).buffer(.1016, resolution=32)
            if any(cu.intersects(courts[int(i)][1]) for i in ctree.query(cu)):
                reasons['BODY_OR_CONSERVATIVE_COURTYARD'] += 1
                continue
            if any(cu.distance(pads[int(i)][1]) < .06 for i in ptree.query(cu.buffer(.06))):
                reasons['NO_VIA_IN_PAD'] += 1
                continue
            if any(hole.distance(drills[int(i)][1]) < .301 for i in dtree.query(hole.buffer(.301))):
                reasons['ORIGINAL799_DRILL'] += 1
                continue
            if any(hole.distance(Point(v['xyMm']).buffer(.1, resolution=64)) < .301 for v in plan['newViaCreates'] + vias):
                reasons['RESERVED50_OR_EARLIER_NEW_DRILL'] += 1
                continue
            conflict = False
            for index in tree.query(cu.buffer(.171)):
                actor = copper[int(index)]
                required = .1535 if actor['new'] else .17
                if actor['net'] != 'gnd' and cu.distance(actor['shape']) < required:
                    conflict = True
                    break
            if conflict:
                reasons['ALL6_NON_FILL_VIA_CU'] += 1
                continue
            for index in tree.query(stub.buffer(.171)):
                actor = copper[int(index)]
                required = .1535 if actor['new'] else .17
                if 1 in actor['layers'] and actor['net'] != 'gnd' and stub.distance(actor['shape']) < required:
                    conflict = True
                    break
            if conflict:
                reasons['TOP_STUB_CU'] += 1
                continue
            # Require literal contact with a valid existing inner GND plane;
            # final combined-mask MCU-VSS proof is still mandatory.
            inner = [f for f in fills if f['layerId'] in (15, 17, 18) and f['net'] == 'GND'
                     and f['valid'] and f['shape'].intersection(cu).area > 1e-8]
            if not inner:
                reasons['NO_VALID_INNER_GND_CONTACT'] += 1
                continue
            chosen = xy, cu, hole, stub, inner
            break
        diagnostics.append(dict(ref=ref, rejected=dict(reasons)))
        if chosen is None:
            failures.append(dict(ref=ref, pin='2', padXYmm=list(padxy), reasons=dict(reasons)))
            continue
        xy, cu, hole, stub, inner = chosen
        via_key = 'POSITIVE_BYPASS_GND_' + ref
        cuts = [dict(id=f['id'], net=f['net'], layerId=f['layerId'], originalPolygonValid=f['valid'])
                for f in fills if f['net'].casefold() != 'gnd' and cu.buffer(.17).intersects(f['shape'].envelope)
                and (not f['valid'] or cu.buffer(.17).intersects(f['shape']))]
        old_gaps = [cu.distance(o['shape']) for o in copper if not o['new'] and o['net'] != 'gnd']
        new_gaps = [cu.distance(o['shape']) for o in copper if o['new'] and o['net'] != 'gnd']
        via = dict(key=via_key, net='GND', xyMm=list(xy), viaDiameterMm=.45, holeDiameterMm=.20, allLayers=CU,
                   pin=ref + ':2', minimumOldNonFillCopperGapMm=min(old_gaps),
                   minimumNewFrozenCopperGapMm=min(new_gaps),
                   minimumOriginal799DrillEdgeGapMm=min(hole.distance(s) for _, s in drills),
                   minimumReserved50DrillEdgeGapMm=min(hole.distance(Point(v['xyMm']).buffer(.1, resolution=64)) for v in plan['newViaCreates']),
                   minimumAnyPadGapMm=min(cu.distance(s) for _, s in pads),
                   noConservativeCourtyardIntersection=True,
                   minimumConservativeCourtyardGapMm=min(cu.distance(s) for _, s in courts),
                   requiresLocalFillAntipads=cuts,
                   originalInnerGroundContacts=[dict(fillId=f['id'], layerId=f['layerId'], contactAreaMm2=cu.intersection(f['shape']).area) for f in inner])
        line = dict(key=via_key + '_STUB', net='GND', layerId=1, widthMm=.2032,
                    startXYmm=list(padxy), endXYmm=list(xy), lengthMm=math.dist(padxy, xy),
                    role='Dedicated short GND return for positive OPA189 local bypass ' + ref + ':2')
        vias.append(via)
        lines.append(line)
        print(json.dumps(dict(ref=ref, xyMm=xy, stubMm=line['lengthMm'], oldGap=via['minimumOldNonFillCopperGapMm'], newGap=via['minimumNewFrozenCopperGapMm'])), flush=True)
    report = dict(schema='independent-eight-positive-bypass-ground-stitch-v3', passed=not failures and len(vias) == 8,
                  nativeCalls=0, nativeModified=False, manufacturingApproved=False,
                  sourcePath=str(source), sourceSha256=H['sha'](source),
                  protectedCombinedRoutePath=str(ROUTE), protectedCombinedRouteSha256=ROUTE_SHA,
                  placementPath=plan['placementPath'], placementSha256=plan['placementSha256'],
                  checkpointPath=str(cp), checkpointSha256=H['sha'](cp),
                  newViaCreates=vias, newLineCreates=lines, failures=failures, searchDiagnostics=diagnostics,
                  original640Vias799DrillsChanged=0, protectedPriorNewViaCount=50,
                  requirements=['Recombine with router-owned C103/U32/C160 correction and independently crosscheck all new routes/vias.',
                                'All6 local FILL antipads mandatory; do not delete the original target pad-bearing lobes.',
                                'Rerun all345 GND pads and retained lobes to actual MCU-VSS after final mask.',
                                'Native readback, strict DRC, save/reopen and final physical graphs before completion.'])
    out = RT / 'independent-eight-positive-ground-stitches-v3.json'
    assert not out.exists(), 'Keep existing report immutable; create a new version instead'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=report['passed'], path=str(out), sha256=H['sha'](out), vias=len(vias), lines=len(lines), failures=failures)), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
