"""Read-only, prospective six-layer DC copper/barrel graph for retained lobes."""
import argparse
import hashlib
import json
import runpy
from collections import Counter
from pathlib import Path

from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import explain_validity

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
MM, G = P['MM'], P['G']
CU = [1, 2, 15, 16, 17, 18]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, key):
        self.parent.setdefault(key, key)
        if self.parent[key] != key:
            self.parent[key] = self.find(self.parent[key])
        return self.parent[key]

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output-prefix', default='local-ground-lobe-connectivity')
    ap.add_argument('--net', default='GND')
    ap.add_argument('--anchor-pad')
    ap.add_argument('--anchor-via')
    ap.add_argument('--ignore-fill-pen', action='store_true')
    args = ap.parse_args()
    anchor_pad = args.anchor_pad or ('U1:A17' if args.net == 'GND' else None)
    if not anchor_pad:
        raise ValueError('Non-ground network requires its original physical power-source --anchor-pad')
    anchor_via = args.anchor_via or ('3b7988d562c902b4' if args.net == 'GND' else None)
    reach_key = 'reachesActualMCUVssA17' if args.net == 'GND' else 'reachesOriginalPowerSourcePad'
    if Path(args.output_prefix).name != args.output_prefix:
        raise ValueError('Output prefix must be a filename')
    frozen = sha(args.manifest)
    plan = json.loads(args.manifest.read_text(encoding='utf8'))
    if not plan.get('passed'):
        raise ValueError('Electrical graph requires a complete, unblocked preserving clearance plan')
    generator_sha = sha(Path(__file__))
    geometry_helper_sha = sha(HERE / 'plan-local-static-fill-clearance.py')
    source = Path(plan['source'])
    assert sha(source) == plan['sourceSha256']
    placement_path = Path(plan['placement'])
    assert sha(placement_path) == plan['placementSha256']
    placement = json.loads(placement_path.read_text(encoding='utf8'))
    rows = G['PARSE'](source)
    ground_anchors = P['anchor_shapes'](rows, placement, args.net)
    expected_physical_pads = set()
    for (kind, rid), b in rows.items():
        if kind == 'PAD_NET' and b.get('padNet') == args.net:
            _, cid, num, pad_id = json.loads(rid)
            expected_physical_pads.add((cid, pad_id))
    covered_physical_pads = {(a['physicalOwnerId'], a['physicalPadPrimitiveId']) for a in ground_anchors if a['kind'] == 'PAD'}
    assert expected_physical_pads == covered_physical_pads, 'Selected-net physical PAD_NET geometry coverage is incomplete'
    expected_original_vias = {rid for (kind, rid), b in rows.items() if kind == 'VIA' and b.get('netName') == args.net}
    covered_original_vias = {a['id'] for a in ground_anchors if a['kind'] == 'VIA'}
    assert expected_original_vias == covered_original_vias, 'Selected-net original VIA geometry coverage is incomplete'
    bylayer = {l: [] for l in CU}
    replacements = {op['primitiveId']: op for op in plan['fillModifyOperations']}
    audit_lobes = plan.get('fillCreateOperations', []) + plan.get('auditExistingFillPrimitives', [])
    excluded = []

    def add(kind, rid, layer, s, **extra):
        if s.is_empty:
            return
        if not s.is_valid:
            excluded.append({'kind': kind, 'id': rid, 'layerId': layer, 'reason': explain_validity(s)})
            return
        bylayer[layer].append({'kind': kind, 'id': rid, 'shape': s, **extra})

    for (kind, rid), b in rows.items():
        layer = b.get('layerId')
        if b.get('netName') != args.net or layer not in CU:
            continue
        if kind == 'FILL':
            paths = replacements[rid]['afterPathsExplicitlyClosedForApi'] if rid in replacements else b['path']
            s = P['geom'](paths)
            if not s.is_valid:
                excluded.append({'kind': kind, 'id': rid, 'layerId': layer, 'reason': explain_validity(s), 'noRepair': True})
                continue
            radius = 0 if args.ignore_fill_pen else (b.get('width', 0) or 0) * MM / 2
            add(kind, rid, layer, s.buffer(radius) if radius else s)
        elif kind in ('LINE', 'ARC', 'CARC'):
            a, z = (b['startX'] * MM, b['startY'] * MM), (b['endX'] * MM, b['endY'] * MM)
            pts = G['arc'](a, z, b.get('angle', 0)) if kind != 'LINE' else [a, z]
            add(kind, rid, layer, LineString(pts).buffer(b['width'] * MM / 2, resolution=32))
        elif kind == 'POLY':
            pts = G['ring_path'](b['path'])
            add(kind, rid, layer, LineString(pts).buffer(b.get('width', 0) * MM / 2, resolution=32))
    for lobe in plan.get('fillCreateOperations', []):
        if lobe.get('net') != args.net:
            continue
        s = P['geom'](lobe['afterPathsExplicitlyClosedForApi'])
        if not s.is_valid:
            raise ValueError('Invalid reviewed local lobe: ' + lobe['key'])
        radius = 0 if args.ignore_fill_pen else lobe['widthMil'] * MM / 2
        add('NEW_FILL_LOBE', lobe['key'], lobe['layerId'], s.buffer(radius) if radius else s)
    for a in ground_anchors:
        for layer in a['layerIds']:
            if layer in CU:
                add(a['kind'], a['id'], layer, a['shape'])
    for rp in plan['routes']:
        path = Path(rp['path'])
        assert sha(path) == rp['sha256']
        route = json.loads(path.read_text(encoding='utf8'))
        for i, line in enumerate(route.get('newLineCreates', route.get('lineCreates', []))):
            if line.get('net') != args.net:
                continue
            a = line.get('startXYmm') or [v * MM for v in line['startXYmil']]
            b = line.get('endXYmm') or [v * MM for v in line['endXYmil']]
            w = line.get('widthMm', line.get('widthMil', 0) * MM)
            add('PLANNED_GND_LINE', line.get('key', str(i)), line['layerId'], LineString([a, b]).buffer(w / 2, resolution=32))
        vias = route.get('viaCreates', route.get('newViaCreates', route.get('viasProposed', route.get('plannedVias', []))))
        if isinstance(vias, int):
            assert vias == 0
            vias = []
        for i, via in enumerate(vias):
            if via.get('net') != args.net:
                continue
            xy = via.get('xyMm') or [v * MM for v in via['xyMil']]
            diameter = via.get('diameterMm', via.get('viaDiameterMm', via.get('diameterMil', 0) * MM))
            hole = via.get('holeDiameterMm', via.get('holeDiameterMil', 0) * MM)
            assert diameter > hole > 0
            center = Point(xy)
            annulus = center.buffer(diameter / 2, resolution=64).difference(center.buffer(hole / 2, resolution=64))
            key = via.get('key', 'PLANNED_GND_VIA_' + str(i))
            duplicate = next((a for a in ground_anchors if a['kind'] == 'VIA' and a['id'] == key), None)
            if duplicate is not None:
                assert duplicate['shape'].equals(annulus), 'Conflicting repeated planned GND via geometry'
                continue
            anchor = {'kind': 'VIA', 'id': key, 'layerIds': CU, 'shape': annulus, 'plannedNewVia': True}
            ground_anchors.append(anchor)
            for layer in CU:
                add('PLANNED_GND_VIA', key, layer, annulus)
    components, trees, primitive_trees = {}, {}, {}
    print('Build six-layer physical ' + args.net + ' unions', flush=True)
    for layer in CU:
        united = unary_union([a['shape'] for a in bylayer[layer]])
        if united.geom_type == 'Polygon':
            components[layer] = [united]
        else:
            components[layer] = [s for s in united.geoms if s.geom_type == 'Polygon']
        trees[layer] = STRtree(components[layer])
        primitive_trees[layer] = STRtree([a['shape'] for a in bylayer[layer]])
    uf = UnionFind()

    def memberships(shape, layers):
        out = []
        for layer in layers:
            if layer not in CU:
                continue
            for idx in trees[layer].query(shape):
                if components[layer][int(idx)].intersection(shape).area > 1e-12:
                    out.append((layer, int(idx)))
        return out

    for a in ground_anchors:
        if a['kind'] != 'VIA' and not a.get('platedThroughPad'):
            continue
        members = memberships(a['shape'], a['layerIds'])
        barrel = ('BARREL', a['kind'], a.get('physicalOwnerId'), a.get('physicalPadPrimitiveId'), a['id'])
        for member in members:
            uf.join(barrel, member)
    mcu = [a for a in ground_anchors if a['kind'] == 'PAD' and a['id'] == anchor_pad]
    if not mcu:
        raise ValueError('Actual selected-net source pad missing: ' + anchor_pad)
    mcu_members = {m for a in mcu for m in memberships(a['shape'], a['layerIds'])}
    mcu_roots = {uf.find(m) for m in mcu_members}
    via_roots = {a['id']: {uf.find(m) for m in memberships(a['shape'], a['layerIds'])} for a in ground_anchors if a['kind'] == 'VIA'}
    original_via_ids = {a['id'] for a in ground_anchors if a['kind'] == 'VIA' and not a.get('plannedNewVia')}
    planned_via_ids = {a['id'] for a in ground_anchors if a['kind'] == 'VIA' and a.get('plannedNewVia')}
    if anchor_via and not (via_roots.get(anchor_via, set()) & mcu_roots):
        raise ValueError('Original selected-net fanout via did not anchor to actual source pad')
    results = []
    for lobe in audit_lobes:
        if lobe.get('net') != args.net:
            continue
        layer = lobe['layerId']
        nominal = P['geom'](lobe['afterPathsExplicitlyClosedForApi'])
        radius = 0 if args.ignore_fill_pen else lobe['widthMil'] * MM / 2
        physical = nominal.buffer(radius) if radius else nominal
        members = memberships(physical, [layer])
        roots = {uf.find(m) for m in members}
        contacts = []
        for idx in primitive_trees[layer].query(physical):
            a = bylayer[layer][int(idx)]
            if a['kind'] == 'NEW_FILL_LOBE' and a['id'] == lobe['key']:
                continue
            if a['kind'] == 'FILL' and a['id'] == lobe.get('existingNativePrimitiveId'):
                continue
            overlap = a['shape'].intersection(physical).area
            if overlap > 1e-12:
                contacts.append({'kind': a['kind'], 'id': a['id'], 'overlapAreaMm2': overlap})
        ties = sorted(v for v, rr in via_roots.items() if roots & rr)
        results.append({'key': lobe['key'], 'layerId': layer, 'nominalAreaMm2': nominal.area,
                        'boundsMm': list(nominal.bounds), 'allSameLayerPhysicalCopperContacts': contacts,
                        'directSameLayerContactCounts': dict(Counter(c['kind'] for c in contacts)),
                        'sameLayerCopperComponents': members, reach_key: bool(roots & mcu_roots),
                        'sameGraphOriginalGroundViaIds': [v for v in ties if v in original_via_ids],
                        'sameGraphPlannedGroundViaIds': [v for v in ties if v not in original_via_ids],
                        'noSameLayerCopperContactDetected': not contacts,
                        'containsGroundPadContact': any(c['kind'] == 'PAD' for c in contacts),
                        'containsGroundViaContact': any(c['kind'] == 'VIA' for c in contacts),
                        'separatedOnlyByReviewedLocalCuts': True,
                        'deletionAuthorized': False, 'requiresAnchorOrExplicitRemovalReview': not bool(roots & mcu_roots)})
    results.sort(key=lambda x: (x['nominalAreaMm2'], x['key']))
    target_refs = set(json.loads((HERE.parent / 'independent-schematic-audit.json').read_text(encoding='utf8'))['independentExpectedContract'])
    all_ground_pads = []
    for a in ground_anchors:
        if a['kind'] != 'PAD':
            continue
        members = memberships(a['shape'], a['layerIds'])
        roots = {uf.find(m) for m in members}
        all_ground_pads.append({'pin': a['id'], 'physicalPadPrimitiveId': a.get('physicalPadPrimitiveId'),
                            'proposedMovedComponent': a.get('proposedMovedComponent'),
                            'isTarget177Component': a['id'].split(':')[0] in target_refs,
                            'boundsMm': list(a['shape'].bounds), 'sameLayerCopperComponents': members,
                            reach_key: bool(roots & mcu_roots)})
    target_pads = [p for p in all_ground_pads if p['isTarget177Component']]
    assert sha(args.manifest) == frozen, 'Input manifest changed during graph audit'
    assert sha(source) == plan['sourceSha256'], 'Native source input changed during graph audit'
    assert sha(placement_path) == plan['placementSha256'], 'Placement input changed during graph audit'
    for rp in plan['routes']:
        assert sha(Path(rp['path'])) == rp['sha256'], 'Routing input changed during graph audit'
    assert sha(Path(__file__)) == generator_sha, 'Graph auditor changed during run'
    assert sha(HERE / 'plan-local-static-fill-clearance.py') == geometry_helper_sha, 'Geometry helper changed during run'
    report = {'schema': 'adc10-labtool-local-ground-lobe-six-layer-contact-audit-v1',
              'analysisCompleted': True, 'net': args.net, 'allLobesMcuAnchored': all(r[reach_key] for r in results),
              'fillPenInterpretation': 'nominal polygon only; no stroke expansion' if args.ignore_fill_pen else 'polygon expanded by half native FILL width',
              'allPhysicalLoadPadsSourceAnchored': all(p[reach_key] for p in all_ground_pads),
              'allOriginalSelectedNetViasSourceAnchored': all(bool(via_roots[v] & mcu_roots) for v in original_via_ids),
              'allPlannedSelectedNetViasSourceAnchored': all(bool(via_roots[v] & mcu_roots) for v in planned_via_ids),
              'loadConnectivityPassed': all(p[reach_key] for p in all_ground_pads) and all(bool(rr & mcu_roots) for rr in via_roots.values()),
              'generatorSha256': generator_sha, 'geometryHelperSha256': geometry_helper_sha,
              'physicalPadNetGeometryCoverage': {'expectedCount': len(expected_physical_pads),
                                               'coveredCount': len(covered_physical_pads), 'omitted': [], 'exact': True},
              'originalViaGeometryCoverage': {'expectedCount': len(expected_original_vias),
                                               'coveredCount': len(covered_original_vias), 'omitted': [], 'exact': True},
              'manifest': str(args.manifest.resolve()), 'manifestSha256': frozen, 'sourceSha256': sha(source),
              'placementSha256': sha(placement_path), 'MCUVssPhysicalPad': anchor_pad, 'MCUVssFanoutVia': anchor_via,
              'mcuAnchorSurfaceComponents': sorted(mcu_members), 'lobeCount': len(results),
              'mcuAnchoredLobeCount': sum(r[reach_key] for r in results),
              'unanchoredLobeCount': sum(not r[reach_key] for r in results),
              'targetGroundPhysicalPads': target_pads,
              'unanchoredTargetGroundPhysicalPads': [p for p in target_pads if not p[reach_key]],
              'allPhysicalGroundPads': all_ground_pads,
              'unanchoredNonTargetGroundPhysicalPads': [p for p in all_ground_pads if not p['isTarget177Component'] and not p[reach_key]],
              'originalViaAnchorAudit': [{'id': v, 'reachesSelectedSourcePad': bool(via_roots[v] & mcu_roots)} for v in sorted(original_via_ids)],
              'unanchoredOriginalViaIds': sorted(v for v in original_via_ids if not (via_roots[v] & mcu_roots)),
              'plannedViaAnchorAudit': [{'id': v, 'reachesSelectedSourcePad': bool(via_roots[v] & mcu_roots)} for v in sorted(planned_via_ids)],
              'unanchoredPlannedViaIds': sorted(v for v in planned_via_ids if not (via_roots[v] & mcu_roots)),
              'lobesSortedByArea': results, 'excludedOriginalInvalidGeometryNoRepair': excluded,
              'nonGroundLobesRetainedButNotJoinedIntoGroundGraph': [{k: v for k, v in l.items() if k not in {'afterPath', 'afterPathsExplicitlyClosedForApi'}} for l in audit_lobes if l.get('net') != args.net],
              'sixLayerComponentCounts': {str(k): len(v) for k, v in components.items()},
              'physicalActorCounts': {str(k): dict(Counter(a['kind'] for a in v)) for k, v in bylayer.items()},
              'nativeCalls': 0, 'nativeModified': False, 'manufacturingApproved': False,
              'limitations': ['Conservative source geometry graph: no equality-of-NET-name joins. Only actual same-layer copper overlap and plated barrel contacts join regions.', 'Invalid original FILLs are retained and excluded without repair, so a reported missing anchor can need focused original-geometry/CAM review.', 'This establishes DC copper connectivity only, not return impedance, analog noise, narrow-neck fabrication, or native DRC completion.']}
    if args.net != 'GND':
        report['schema'] = 'adc10-labtool-selected-power-net-six-layer-contact-audit-v1'
        renames = {'allLobesMcuAnchored': 'allLobesSourceAnchored', 'MCUVssPhysicalPad': 'originalPowerSourcePhysicalPad',
                   'MCUVssFanoutVia': 'originalPowerSourceFanoutVia', 'mcuAnchorSurfaceComponents': 'sourcePadSurfaceComponents',
                   'mcuAnchoredLobeCount': 'sourceAnchoredLobeCount', 'targetGroundPhysicalPads': 'targetNetPhysicalPads',
                   'unanchoredTargetGroundPhysicalPads': 'unanchoredTargetNetPhysicalPads',
                   'allPhysicalGroundPads': 'allPhysicalNetPads', 'unanchoredNonTargetGroundPhysicalPads': 'unanchoredNonTargetNetPhysicalPads',
                   'nonGroundLobesRetainedButNotJoinedIntoGroundGraph': 'otherNetLobesRetainedButNotJoinedIntoSelectedNetGraph'}
        for old, new in renames.items():
            report[new] = report.pop(old)
        for r in results:
            for old, new in [('sameGraphOriginalGroundViaIds', 'sameGraphOriginalPowerViaIds'),
                             ('sameGraphPlannedGroundViaIds', 'sameGraphPlannedPowerViaIds'),
                             ('containsGroundPadContact', 'containsSelectedNetPadContact'),
                             ('containsGroundViaContact', 'containsSelectedNetViaContact')]:
                r[new] = r.pop(old)
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': sha(target), 'lobes': len(results), 'anchored': sum(r[reach_key] for r in results), 'unanchored': report['unanchoredLobeCount']}), flush=True)


if __name__ == '__main__':
    main()
