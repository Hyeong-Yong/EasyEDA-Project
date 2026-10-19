"""Independent prospective six-layer ADC/supply physical graph, no native API.

Pad geometry comes from the saved footprint documents and current native PCB
placement/PAD_NET records, not from route-planner connectivity assertions.
"""
import argparse
import hashlib
import json
import math
import re
import runpy
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from shapely.affinity import rotate, scale, translate
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
MM = .0254
CU = {1, 2, 15, 16, 17, 18}
H = runpy.run_path(str(HERE / 'independent-pcb-placement-proposal.py'))
P = runpy.run_path(str(HERE / 'ground/plan-local-static-fill-clearance.py'))
G = H['G']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def scoped(value, folder=HERE):
    p = Path(value)
    if not p.is_absolute():
        p = ROOT / p if str(p).replace('\\', '/').startswith('output/') else folder / p
    p = p.resolve()
    assert p.is_relative_to(folder.resolve()), ('OUT_OF_SCOPE', str(p))
    return p


def native_xy(xy):
    return tuple(round(v / MM, 4) * MM for v in xy)


def native_dimension(v):
    return round(round(v / MM, 8), 4) * MM


class UF:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        if self.p[a] != a:
            self.p[a] = self.find(self.p[a])
        return self.p[a]

    def join(self, a, b):
        self.p[self.find(a)] = self.find(b)


def pad_shape(pad):
    d = pad['defaultPad']
    typ = d.get('padType')
    if typ == 'POLYGON':
        shape = Polygon(G['ring_path'](d['path']))
    else:
        w = d.get('width', d.get('diameter', 0)) * MM
        h = d.get('height', d.get('diameter', 0)) * MM
        assert w > 0 and h > 0, ('UNKNOWN_PAD_DIMENSION', d)
        if typ in ('ELLIPSE', 'CIRCLE'):
            shape = scale(Point(0, 0).buffer(1, resolution=64), w / 2, h / 2)
        elif typ == 'OVAL':
            radius = min(w, h) / 2
            ends = [(-(w / 2 - radius), 0), (w / 2 - radius, 0)] if w >= h else [(0, -(h / 2 - radius)), (0, h / 2 - radius)]
            shape = LineString(ends).buffer(radius, resolution=64)
        elif typ == 'RECT':
            radius = min((d.get('radius', 0) or 0) * MM, w / 2, h / 2)
            shape = (box(-w / 2 + radius, -h / 2 + radius, w / 2 - radius, h / 2 - radius)
                     .buffer(radius, resolution=32)) if radius else box(-w / 2, -h / 2, w / 2, h / 2)
        else:
            raise ValueError(('UNSUPPORTED_PAD_TYPE', typ))
        shape = translate(rotate(shape, pad.get('padAngle', 0), origin=(0, 0)),
                          pad['centerX'] * MM, pad['centerY'] * MM)
    # Drilled pads have annular, not solid-disk, copper. Subtract the literal
    # local hole before the component's mirror/rotation/translation.
    hole = pad.get('hole') or {}
    w, h = hole.get('width', 0) * MM, hole.get('height', 0) * MM
    if w and h:
        if hole.get('holeType') in ('ROUND', 'SLOT', 'OVAL'):
            radius = min(w, h) / 2
            ends = [(-(w / 2 - radius), 0), (w / 2 - radius, 0)] if w >= h else [(0, -(h / 2 - radius)), (0, h / 2 - radius)]
            hs = LineString(ends).buffer(radius, resolution=64) if ends[0] != ends[1] else Point(0, 0).buffer(radius, resolution=64)
        elif hole.get('holeType') == 'RECT':
            hs = box(-w / 2, -h / 2, w / 2, h / 2)
        else:
            raise ValueError(('UNSUPPORTED_TARGET_PAD_HOLE', hole))
        hs = translate(rotate(hs, pad.get('padAngle', 0) + pad.get('relativeAngle', 0), origin=(0, 0)),
                       pad['centerX'] * MM, pad['centerY'] * MM)
        shape = shape.difference(hs)
    return shape


class GraphAudit:
    def __init__(self):
        self.actors = defaultdict(list)
        self.pads = defaultdict(list)
        self.barrels = []
        self.errors = []
        self.excluded = []
        self.report = {'schema': 'labtool-independent-proposed-physical-power-signal-graph-v1',
                       'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False}

    def add(self, net, layer, shape, key, kind, pin=None, proposed=False):
        if shape.is_empty or layer not in CU:
            return
        assert shape.is_valid, ('INVALID_ACTOR', key, explain_validity(shape))
        item = dict(key=key, kind=kind, net=net, layer=layer, shape=shape, pin=pin, proposed=proposed)
        self.actors[net, layer].append(item)
        if pin:
            self.pads[net].append(item)

    def run(self, routes_path, checkpoint, fills_path=None):
        route_sha = sha(routes_path)
        plan = read(routes_path)
        source_path = scoped(plan['sourcePath'], ROOT / 'output/validation')
        placement_path = scoped(plan['placementPath'])
        assert sha(source_path) == plan['sourceSha256'] and sha(placement_path) == plan['placementSha256']
        source_sha, placement_sha, checkpoint_sha = sha(source_path), sha(placement_path), sha(checkpoint)
        rows = H['parse'](source_path)
        attrs = H['attrs_of'](rows)
        docs, _ = H['READ'](checkpoint)
        padnets = {}
        for (kind, rid), b in rows.items():
            if kind == 'PAD_NET':
                p = json.loads(rid)
                padnets[p[1], str(p[2])] = b.get('padNet')
        nets = {o['net'] for o in plan['newLineCreates']} - {'GND', '+3V3'}
        nets |= {n for n in padnets.values() if isinstance(n, str) and re.fullmatch(r'ADC[123]_INP\d+', n)}
        modifications, lobes = {}, []
        if fills_path:
            fills = read(fills_path)
            assert fills['sourceSha256'] == source_sha
            assert fills['passed'] is True and not fills['blocked']
            modifications = {o['primitiveId']: o for o in fills['fillModifyOperations']}
            lobes = fills['fillCreateOperations']
        for (kind, cid), body in rows.items():
            if kind == 'COMPONENT':
                at = attrs[cid]
                fp = docs['FOOTPRINT', at['Footprint']]
                xy, angle = (body['x'] * MM, body['y'] * MM), body['angle']
                for (pk, pid), (_, pad) in fp.items():
                    if pk != 'PAD':
                        continue
                    num = str(pad['num'])
                    net = padnets.get((cid, num))
                    if net not in nets:
                        continue
                    assert not pad.get('specialPad'), ('SPECIAL_TARGET_PAD_REQUIRES_EXPLICIT_MODEL', at['Designator'], num)
                    shape = pad_shape(pad)
                    if body['layerId'] == 2:
                        shape = scale(shape, xfact=1, yfact=-1, origin=(0, 0))
                    shape = H['world'](shape, xy, angle)
                    layer = pad['layerId']
                    if layer in (1, 2) and body['layerId'] == 2:
                        layer = 3 - layer
                    layers = CU - set(pad.get('unusedInnerLayers', [])) if layer == 12 else {layer}
                    key, pin = f'PAD:{cid}:{pid}', at['Designator'] + ':' + num
                    for layer in layers:
                        self.add(net, layer, shape, key, 'PAD', pin=pin)
                    if pad.get('layerId') == 12 and pad.get('plated'):
                        self.barrels.append((net, key, shape, layers))
            elif kind == 'VIA' and body.get('netName') in nets:
                center = Point(body['centerX'] * MM, body['centerY'] * MM)
                shape = center.buffer(body['viaDiameter'] * MM / 2, resolution=64).difference(
                    center.buffer(body['holeDiameter'] * MM / 2, resolution=64))
                layers = CU - set(body.get('unusedInnerLayers', []))
                for layer in layers:
                    self.add(body['netName'], layer, shape, 'VIA:' + cid, 'VIA')
                self.barrels.append((body['netName'], 'VIA:' + cid, shape, layers))
            elif body.get('netName') in nets and body.get('layerId') in CU:
                net, layer = body['netName'], body['layerId']
                if kind in ('LINE', 'ARC', 'CARC'):
                    a, b = (body['startX'] * MM, body['startY'] * MM), (body['endX'] * MM, body['endY'] * MM)
                    pts = [a, b] if kind == 'LINE' else G['arc'](a, b, body['angle'])
                    self.add(net, layer, LineString(pts).buffer(body['width'] * MM / 2, resolution=32), kind + ':' + cid, kind)
                elif kind == 'POLY':
                    self.add(net, layer, LineString(G['ring_path'](body['path'])).buffer(body['width'] * MM / 2, resolution=32), kind + ':' + cid, kind)
                elif kind == 'FILL':
                    path = modifications[cid]['afterPath'] if cid in modifications else body['path']
                    shape = P['geom'](path)
                    if not shape.is_valid:
                        self.excluded.append(dict(key=kind + ':' + cid, net=net, layerId=layer,
                                                  reason=explain_validity(shape), noRepair=True))
                        continue
                    self.add(net, layer, shape.buffer(body['width'] * MM / 2, resolution=32), kind + ':' + cid, kind)
        for lobe in lobes:
            if lobe['net'] in nets:
                self.add(lobe['net'], lobe['layerId'], P['geom'](lobe['afterPath']).buffer(lobe['widthMil'] * MM / 2),
                         lobe['key'], 'NEW_FILL', proposed=True)
        for line in plan['newLineCreates']:
            if line['net'] not in nets:
                continue
            shape = LineString([native_xy(line['startXYmm']), native_xy(line['endXYmm'])]).buffer(
                native_dimension(line['widthMm']) / 2, resolution=32)
            self.add(line['net'], line['layerId'], shape, line['key'], 'NEW_LINE', proposed=True)
        for via in plan['newViaCreates']:
            if via['net'] not in nets:
                continue
            center = Point(native_xy(via['xyMm']))
            shape = center.buffer(native_dimension(via['viaDiameterMm']) / 2, resolution=64).difference(
                center.buffer(native_dimension(via['holeDiameterMm']) / 2, resolution=64))
            assert set(via.get('allLayers', CU)) == CU
            for layer in CU:
                self.add(via['net'], layer, shape, via['key'], 'NEW_VIA', proposed=True)
            self.barrels.append((via['net'], via['key'], shape, CU))
        print('Independent physical actor model ready', len(nets), 'nets', flush=True)
        components, trees, uf = {}, {}, UF()
        for key, actors in self.actors.items():
            united = unary_union([a['shape'] for a in actors])
            parts = [united] if united.geom_type == 'Polygon' else [p for p in united.geoms if p.geom_type == 'Polygon']
            components[key] = parts
            trees[key] = STRtree(parts)

        def members(net, shape, layers):
            result = []
            for layer in layers:
                key = net, layer
                for index in trees.get(key, STRtree([])).query(shape):
                    index = int(index)
                    if components[key][index].intersection(shape).area > 1e-12:
                        result.append((net, layer, index))
            return result

        for net, key, shape, layers in self.barrels:
            for member in members(net, shape, layers):
                uf.join(('BARREL', key), member)
        results, pin_roots, pin_nets = [], defaultdict(set), {}
        for net in sorted(nets):
            groups = defaultdict(set)
            for pad in self.pads[net]:
                roots = {uf.find(m) for m in members(net, pad['shape'], [pad['layer']])}
                assert roots, ('PAD_OWN_COPPER_NOT_FOUND', pad['pin'])
                for root in roots:
                    groups[repr(root)].add(pad['pin'])
                    pin_roots[pad['pin']].add(root)
                pin_nets[pad['pin']] = net
            group_list = [sorted(v) for _, v in sorted(groups.items())]
            ok = len(groups) == 1
            if not ok:
                self.errors.append(dict(code='SAME_NET_PHYSICAL_DISCONNECTION', net=net, padGroups=group_list))
            results.append(dict(net=net, connected=ok, physicalPadCount=sum(len(v) for v in groups.values()),
                                uniquePins=len({p for v in groups.values() for p in v}), physicalPadGroups=group_list))
        # Check literal intersections, not only different text NET names. This
        # catches a power filter bypass and the former Inner15/RAW via crossing.
        intersections = []
        for layer in sorted(CU):
            actors = [a for (net, ly), aa in self.actors.items() if ly == layer for a in aa]
            tree = STRtree([a['shape'] for a in actors])
            seen = set()
            for i, a in enumerate(actors):
                if not a['proposed']:
                    continue
                for j in tree.query(a['shape']):
                    j = int(j)
                    b = actors[j]
                    pair = tuple(sorted((a['key'], b['key'])))
                    if i == j or a['net'] == b['net'] or pair in seen:
                        continue
                    seen.add(pair)
                    if a['shape'].intersects(b['shape']):
                        intersections.append(dict(layerId=layer, a=a['key'], netA=a['net'], b=b['key'], netB=b['net'],
                                                  overlapAreaMm2=a['shape'].intersection(b['shape']).area))
        if intersections:
            self.errors.append(dict(code='DIFFERENT_NET_LITERAL_COPPER_INTERSECTION', conflicts=intersections))

        def expect_group(title, net, pins):
            missing = [p for p in pins if pin_nets.get(p) != net]
            common = set.intersection(*(pin_roots[p] for p in pins)) if not missing else set()
            ok = not missing and bool(common)
            if not ok:
                self.errors.append(dict(code='FUNCTIONAL_POWER_OR_REFERENCE_GROUP_FAILED', title=title,
                                        net=net, missingOrWrongNet=missing, pins=pins))
            return dict(title=title, net=net, pins=pins, allSameLiteralCopperComponent=ok)
        power = [
            expect_group('RAW +5 reaches both independent RC inputs', '+5V', ['CN1:1', 'R197:1', 'R200:1']),
            expect_group('Filtered +5 from R200 output to all bipolar buffers and reference', '+5V_AFE',
                         ['R200:2', 'C103:1', 'U9:2', 'U32:5', 'C160:1'] + [f'U{i}:5' for i in range(20, 30)]),
            expect_group('Pump input after R197', 'AFE_PUMP_IN', ['R197:2', 'U30:2', 'C150:1']),
            expect_group('Pump negative raw into LDO IN and EN', 'AFE_VNEG_RAW', ['U30:1', 'C152:1', 'U31:2', 'U31:3', 'D20:2']),
            expect_group('LDO output to all negative buffer supplies', '-3V_AFE',
                         ['U31:5', 'C153:1', 'C154:1', 'D20:1', 'R198:1', 'C155:2'] + [f'U{i}:2' for i in range(20, 30)]),
            expect_group('Negative LDO feedback divider', 'AFE_NEG_FB', ['U31:4', 'R198:2', 'R199:2', 'C155:1']),
            expect_group('Flying cap negative node', 'AFE_FLY_N', ['U30:3', 'C151:1']),
            expect_group('Flying cap positive node', 'AFE_FLY_P', ['U30:5', 'C151:2']),
            expect_group('Reference 2.5V output reaches offset divider and ESR branch', 'AFE_REF_2V5', ['U9:6', 'R202:1', 'R201:2']),
            expect_group('Reference output ESR isolation branch', 'AFE_REF_ESR', ['R201:1', 'C104:1']),
            expect_group('Reference noise reduction pin', 'AFE_REF_NR', ['U9:5', 'C105:1']),
            expect_group('Divider/filter reaches buffer positive input', 'AFE_OFFSET_FILTER', ['R202:2', 'R203:2', 'C158:1', 'U32:3']),
            expect_group('Offset follower output and feedback to output isolation resistor', 'AFE_OFFSET_BUFFER', ['U32:1', 'U32:4', 'R204:1']),
            expect_group('R204 output reaches all ten final OPA320 positive inputs', 'ADC_OFFSET_0V97',
                         ['R204:2', 'C159:1'] + [f'U{i}:3' for i in range(10, 20)]),
        ]
        values = {}
        for (kind, cid), body in rows.items():
            if kind == 'COMPONENT' and attrs[cid].get('Designator') in {'R197', 'R200', 'R201', 'R202', 'R203', 'R204'}:
                values[attrs[cid]['Designator']] = body['attrs'].get('Value')
        required_values = {'R197': '4.7', 'R200': '4.7', 'R201': '1.0', 'R202': '15.8k', 'R203': '10.0k', 'R204': '1.00k'}
        if values != required_values:
            self.errors.append(dict(code='FUNCTIONAL_RC_VALUES_CHANGED', actual=values, expected=required_values))
        assert sha(routes_path) == route_sha and sha(source_path) == source_sha and sha(placement_path) == placement_sha
        self.report.update(passed=not self.errors, sourcePath=str(source_path), sourceSha256=source_sha,
                           routesPath=str(routes_path), routesSha256=route_sha,
                           placementPath=str(placement_path), placementSha256=placement_sha,
                           checkpointPath=str(checkpoint), checkpointSha256=checkpoint_sha,
                           fillsPath=str(fills_path) if fills_path else None,
                           fillsSha256=sha(fills_path) if fills_path else None,
                           watchedNetCount=len(nets), allSameNetPadGraphsPass=all(r['connected'] for r in results),
                           netGraphs=results, specificPowerAndReferenceChains=power,
                           relevantResistorValues=values, differentNetLiteralIntersections=intersections,
                           excludedOriginalInvalidGeometryNoRepair=self.excluded,
                           newLineCount=len(plan['newLineCreates']), newViaCount=len(plan['newViaCreates']),
                           plannedLineLayers=dict(Counter(o['layerId'] for o in plan['newLineCreates'])),
                           sourceOriginalViaCount=sum(k[0] == 'VIA' for k in rows),
                           expectedTotalViaCount=640 + len(plan['newViaCreates']),
                           expectedTotalDrillCount=799 + len(plan['newViaCreates']),
                           padLayerShapeCounts={str(k): sum(len(v) for (n, l), v in self.actors.items() if l == k) for k in sorted(CU)},
                           errors=self.errors, limitations=[
                               'Prospective physical copper graph using planned 4dp-mil native coordinates; not an actual native readback.',
                               'No equality-of-net-label joins; only same-layer literal copper overlap and plated barrel joins.',
                               'No graph edge is inserted across a resistor, capacitor, LDO, charge pump, reference IC, or op amp; separate nodes and actual pins prove the intended component sequence.',
                               'GND/retained +3V3, minimum clearance, orphan planes, all-six-layer antipad adequacy, strict native DRC, analog noise/stability, and manufacturing approval require separate final audits.',
                               'Without --fills the static-fill changes have not been incorporated: this is scoped non-ground signal/supply connectivity only.' if not fills_path else 'Uses the exact supplied final static-fill plan; native/CAM readback remains required.'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--routes', required=True)
    ap.add_argument('--fills')
    ap.add_argument('--checkpoint', default='output/checkpoints/STM32H747_labtool_107_placed_v5b_wip_20261018.epro2')
    args = ap.parse_args()
    audit = GraphAudit()
    try:
        audit.run(scoped(args.routes), scoped(args.checkpoint, ROOT / 'output/checkpoints'), scoped(args.fills) if args.fills else None)
    except Exception as exc:
        import traceback
        audit.errors.append(dict(code='FAIL_CLOSED_EXCEPTION', message=str(exc), traceback=traceback.format_exc()))
        audit.report.update(passed=False, errors=audit.errors)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = HERE / 'audits' / f'proposed-power-graph-{stamp}-{uuid.uuid4().hex[:8]}.json'
    path.parent.mkdir(exist_ok=True)
    audit.report.update(auditorPath=str(Path(__file__).resolve()), auditorSha256=sha(Path(__file__)),
                        auditedUtc=datetime.now(timezone.utc).isoformat())
    with path.open('x', encoding='utf8') as f:
        json.dump(audit.report, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(json.dumps(dict(passed=audit.report['passed'], report=str(path), sha256=sha(path),
                          nets=audit.report.get('watchedNetCount'), errors=audit.errors[:3]), ensure_ascii=False), flush=True)
    return 0 if audit.report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
