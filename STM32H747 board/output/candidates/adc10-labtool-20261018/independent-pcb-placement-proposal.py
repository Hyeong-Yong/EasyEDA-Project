"""Read-only source analysis; emits only a non-executable placement proposal."""
from __future__ import annotations
import hashlib
import json
import math
import runpy
from collections import defaultdict
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString, box
from shapely.affinity import rotate, translate
from shapely.ops import unary_union
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MM = .0254
CLR = .1535  # .1524mm rule + .0011mm arc-screen approximation reserve
BASELINE_SOURCE = ROOT / 'output/validation/native-adc10-pcb-labtool_before-20261018.epru'
SOURCE = ROOT / 'output/validation/native-adc10-pcb-labtool_eco_applied-20261018.epru'
CHECK = ROOT / 'output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2'
READ = runpy.run_path(str(ROOT / 'output/candidates/adc-inline-wiring/audit-inline-final-project.py'))['read_snapshot']
G = runpy.run_path(str(ROOT / 'scripts/draft-adc10-bucket-placement-readonly-20261017.py'))


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def parse(p):
    rows = {}
    for s in p.read_text(encoding='utf8').splitlines():
        h, b = s.split('||', 1)
        h, b = json.loads(h), json.loads(b.rstrip('|'))
        rows[h['type'], str(h.get('id', ''))] = b
    return rows


def attrs_of(rows):
    a = defaultdict(dict)
    for (k, rid), b in rows.items():
        if k == 'ATTR': a[b['parentId']][b['key']] = b.get('value')
    return a


def world(shape, xy, angle): return translate(rotate(shape, angle, origin=(0, 0)), *xy)


def local_pad(b):
    d = b['defaultPad']
    if d.get('padType') == 'POLYGON':
        # Native polygon pads use footprint-local absolute paths, not pad-center
        # relative paths (the existing USB-C pad golden audit proves this).
        return Polygon(G['ring_path'](d['path']))
    if 'width' in d and 'height' in d:
        s = box(-d['width'] * MM / 2, -d['height'] * MM / 2, d['width'] * MM / 2, d['height'] * MM / 2)
    elif 'diameter' in d: s = Point(0, 0).buffer(d['diameter'] * MM / 2, resolution=32)
    else: raise ValueError(('Unsupported pad', d))
    return world(s, (b['centerX'] * MM, b['centerY'] * MM), b.get('padAngle', 0))


def footprint(doc):
    pads = {}
    drawn = defaultdict(list)
    for (k, rid), (_, b) in doc.items():
        if k == 'PAD': pads[str(b['num'])] = (local_pad(b), b)
        elif k == 'LINE' and b.get('layerId') in (3, 9, 48):
            drawn[b['layerId']].append(LineString([(b['startX'] * MM, b['startY'] * MM), (b['endX'] * MM, b['endY'] * MM)]).buffer(b.get('width', 0) * MM / 2 + 1e-7))
        elif k == 'POLY' and b.get('layerId') in (3, 9, 48):
            pts = G['ring_path'](b['path'])
            drawn[b['layerId']].append(Polygon(pts))
    bounds = unary_union([p[0] for p in pads.values()]).bounds
    # Assembly screen is native courtyard where present, otherwise a deliberately
    # conservative pad/silk envelope. It is not a new manufacturer-approved court.
    env = unary_union(drawn.get(48) or drawn.get(3) or [box(*bounds)]).envelope
    env = env.union(box(*bounds)).envelope.buffer(.15, join_style=2).envelope
    return pads, env


def main():
    rows = parse(SOURCE)
    oldattrs = attrs_of(rows)
    refs = {a['Designator']: cid for cid, a in oldattrs.items() if 'Designator' in a}
    original_rows = parse(BASELINE_SOURCE)
    original_attrs = attrs_of(original_rows)
    original_refs = {a['Designator']: cid for cid, a in original_attrs.items() if 'Designator' in a}
    padnets = {}
    for (kind, rid), b in rows.items():
        if kind == 'PAD_NET':
            encoded = json.loads(rid)
            padnets[encoded[1], str(encoded[2])] = b.get('padNet', '')
    plan = json.loads((HERE / 'schematic-plan.json').read_text(encoding='utf8'))
    sch = {}
    for p in plan['pages']:
        a = attrs_of(parse(Path(p['candidatePath'])))
        for cid, at in a.items():
            if at.get('Convert to PCB') == 'yes' and 'Designator' in at:
                sch[at['Designator']] = at
    newrefs = set(sch) - set(original_refs)
    # All 83 new UIDs/parts, including the reverse-protection D20.
    assert len(newrefs) == 83, (len(newrefs), sorted(newrefs))
    pre = [97, 98, 99, 106, 107, 108, 109, 110, 111, 112]
    rin = [137, 138, 139, 149, 150, 151, 161, 162, 163, 164]
    moved = {f'C{x}' for x in pre} | {f'R{x}' for x in rin} | {'U9', 'C103', 'C104', 'C105'}
    docs, _ = READ(CHECK)
    fps = {}
    for ref in newrefs | moved:
        cid = refs[ref]
        a = oldattrs[cid]
        assert rows['COMPONENT',cid]['attrs']['Unique ID'] == sch[ref]['Unique ID'], ref
        fps[ref] = footprint(docs['FOOTPRINT', a['Footprint']])
        for number in fps[ref][0]:
            assert (padnets.get((cid, number)) or None) == (plan['allPinContracts'][ref].get(number) or None), (ref, number, padnets.get((cid, number)), plan['allPinContracts'][ref].get(number))

    obstacles = []
    oldcourts = []
    eligible_routes = []
    fill_shapes = []
    invalid_fills = []
    def add(kind, rid, net, s, ref=None):
        if s.is_empty: return
        obstacles.append({'kind': kind, 'id': rid, 'net': net, 'shape': s, 'ref': ref})
    for (kind, rid), b in rows.items():
        if kind == 'COMPONENT' and b['layerId'] == 1:
            ref = oldattrs[rid]['Designator']
            if ref in moved or ref in newrefs: continue
            pp, env = footprint(docs['FOOTPRINT', oldattrs[rid]['Footprint']])
            xy = (b['x'] * MM, b['y'] * MM)
            oldcourts.append((ref, world(env, xy, b['angle'])))
            for pn, (s, pb) in pp.items():
                if pb['layerId'] not in (1, 12): continue
                add('PAD', rid + ':' + pn, '', world(s, xy, b['angle']), ref)
        elif kind == 'VIA':
            add('VIA', rid, b.get('netName'), Point(b['centerX'] * MM, b['centerY'] * MM).buffer(b['viaDiameter'] * MM / 2, resolution=24))
        elif kind in ('LINE', 'ARC') and b['layerId'] == 1:
            a, z = (b['startX'] * MM, b['startY'] * MM), (b['endX'] * MM, b['endY'] * MM)
            pts = G['arc'](a, z, b['angle']) if kind == 'ARC' else [a, z]
            net = b.get('netName', '')
            s = LineString(pts).buffer(b['width'] * MM / 2, resolution=8)
            if (('PRE' in net or 'DRV' in net or net == 'ADC_BIAS_2V5') and s.bounds[2] < 28):
                eligible_routes.append({'kind': kind, 'id': rid, 'net': net, 'shape': s, 'beforeBody': b})
            else: add(kind, rid, net, s)
        elif kind == 'FILL' and b['layerId'] == 1:
            rings = [G['ring_path'](p) for p in b['path']]
            s = Polygon(rings[0], rings[1:])
            if not s.is_valid:
                invalid_fills.append(rid)
                continue
            fill_shapes.append((rid, b.get('netName'), s))
            if b.get('netName') not in ('GND', 'ADC_BIAS_2V5'): add(kind, rid, b.get('netName'), s)
    shapes = [x['shape'] for x in obstacles]
    tree = STRtree(shapes)
    court_shapes = [x[1] for x in oldcourts]
    court_tree = STRtree(court_shapes)
    placed = []
    failure = []

    def evaluate(ref, xy, angle, role):
        pads, env = fps[ref]
        env = world(env, xy, angle)
        if not box(.4, .4, 99.6, 153.6).contains(env): return None
        if any(env.intersects(court_shapes[int(i)]) for i in court_tree.query(env)): return None
        if any(env.intersects(p['_court']) for p in placed): return None
        cuts, ground = set(), set()
        padout = []
        for number, (local, pb) in pads.items():
            s = world(local, xy, angle)
            buf = s.buffer(CLR, join_style=2)
            if any(buf.intersects(shapes[int(i)]) for i in tree.query(buf)): return None
            for p in placed:
                if any(buf.intersects(t) for t in p['_pads']): return None
            for q in eligible_routes:
                if buf.intersects(q['shape']): cuts.add((q['kind'], q['id']))
            for fid, net, fs in fill_shapes:
                if net == 'GND' and buf.intersects(fs): ground.add(fid)
                elif net == 'ADC_BIAS_2V5' and buf.intersects(fs): cuts.add(('FILL', fid))
            padout.append({'number': number, 'net': plan['allPinContracts'][ref].get(number), 'centerMm': [s.centroid.x, s.centroid.y], 'boundsMm': list(s.bounds)})
        return {'ref': ref, 'newPart': ref in newrefs, 'componentId': refs[ref], 'sourceBodyBefore': rows['COMPONENT',refs[ref]], 'actualPadNetContractVerified': True, 'uniqueId': sch[ref]['Unique ID'], 'footprintUuid': oldattrs[refs[ref]]['Footprint'], 'value': sch[ref].get('Value'), 'role': role, 'xyMm': list(xy), 'angle': angle, 'layerId': 1, 'set': {'x':xy[0]/MM,'y':xy[1]/MM,'rotation':angle,'layer':1}, 'pads': padout, 'conservativeCourtBoundsMm': list(env.bounds), 'requiresOldAFEGeometryRework': sorted([list(k) for k in cuts]), 'requiresLocalTopGroundVoidIds': sorted(ground), '_court': env, '_pads': [world(s, xy, angle) for s, _ in pads.values()]}

    def choose(ref, preferred, region, role, angles=(0, 90, 180, 270), step=.2):
        xs = [round(region[0] + step * i, 4) for i in range(round((region[2] - region[0]) / step) + 1)]
        ys = [round(region[1] + step * i, 4) for i in range(round((region[3] - region[1]) / step) + 1)]
        candidates = sorted(((x, y) for x in xs for y in ys), key=lambda q: (q[0] - preferred[0]) ** 2 + (q[1] - preferred[1]) ** 2)
        for xy in [preferred] + candidates:
            for angle in angles:
                p = evaluate(ref, xy, angle, role)
                if p is not None:
                    placed.append(p)
                    return p
        failure.append({'ref': ref, 'regionMm': region, 'role': role})
        return None

    # The board is a10x14mm-pitch analog-strip repetition. Preserve all10SMA,
    # finalOPA320,47ohmseriesresistor/longADCroute andMCU-side reservoirpositions.
    for i in range(10):
        row = 140 - 14 * i
        reg = (8.8, row - 7.8, 23.5, row + 3.0)
        choose(f'U{20+i}', (11, row - 3.5), (10.6, row - 3.9, 11.4, row - 3.1), 'bipolar GND-referenced follower', (0,))
        choose(f'C{pre[i]}', (8.8, row - 5.7), (8.5, row - 7.0, 15.0, row - 4.0), 'existing10nF input shunt; move close to follower+')
        choose(f'C{120+3*i}', (14.2, row - 2.5), (13.7, row - 4.0, 16.0, row - 1.8), '+5V_AFE local100nF follower decoupling')
        choose(f'C{121+3*i}', (14.2, row - 4.2), (13.7, row - 6.6, 16.4, row - 3.0), '-3V_AFE local100nF follower decoupling')
        choose(f'R{177+i}', (11.0, row + 1.2), (9.2, row + .7, 15.0, row + 3.4), '100k input-to-GND pulldown', (90, 0, 270, 180))
        choose(f'R{rin[i]}', (20.2, row - 4.5), (16.0, row - 7.4, 23.5, row - 3.5), 'existing4k postbuffer input resistor; relocate')
        choose(f'R{187+i}', (22.0, row - 4.8), (16.2, row - 7.6, 24.0, row - 3.5), '2.8k final inverting feedback')
        choose(f'C{122+3*i}', (22.0, row - 6.2), (16.2, row - 7.8, 24.0, row - 3.5), '10nF feedback LPF capacitor')

    # Re-use the former bias/reference patch for a central quiet-reference island.
    choose('U9', (23.2, 76.9), (21.5, 71.5, 30.5, 79.5), 'existingUID REF5025 replacement; SOIC8', (0, 90, 180, 270), .2)
    choose('U32', (23.4, 71.9), (21.5, 70.7, 27.5, 73.3), 'offset reference follower', (0, 180), .2)
    for ref, preferred, role in (
        ('C160', (28.6, 72.2), '100nF offset-buffer supply bypass'),
        ('C103', (20.4, 73.5), '1uF REF input bypass'), ('C104', (27.8, 78.3), '4.7uF REF ESR-controlled output'),
        ('C105', (27.8, 75.7), '1uF REF NR bypass'), ('R201', (27.0, 79.8), '1ohm REF capacitor ESR'),
        ('R202', (26.8, 73.2), '15.8k offset divider'), ('R203', (28.6, 73.2), '10k offset divider'),
        ('C158', (29.8, 71.7), '4.7uF offset-divider LPF'), ('R204', (27.0, 70.2), '1k offset-output isolation'),
        ('C159', (29.5, 82.5), '4.7uF common offset-output LPF')):
        choose(ref, preferred, (20.0, 66.0, 32.0, 86.0), role)

    # Switching power kept separate from the central reference. No bottom copper,
    # original vias, mounting holes or inner-plane polygons may be modified merely
    # to make this placement work.
    pwr = (27.5, 20.0, 40.5, 34.5)
    for ref, pref, role in (
        ('U30', (30.5, 29.8), 'TPS60403 charge pump'), ('U31', (36.7, 29.8), 'TPS723 negative LDO'),
        ('D20', (30.8, 33.2), 'negative-regulator reverse protection diode'),
        ('C151', (30.5, 26.5), 'charge-pump flying capacitor; shortestlocal loop'),
        ('C150', (27.8, 30.0), 'pump input capacitor'), ('R197', (27.8, 32.0), '4.7ohm pump-input isolator'),
        ('C152', (33.6, 29.4), 'pump output/LDO input capacitor'),
        ('C153', (39.3, 29.5), 'negative LDO output capacitor'), ('C154', (39.3, 26.8), 'negative LDO output bulk'),
        ('R198', (35.4, 26.3), '15.4k negative feedback divider'), ('R199', (37.7, 26.3), '10k negative feedback divider'),
        ('C155', (36.3, 24.8), '10nF LDO CFF'), ('R200', (28.8, 23.0), '4.7ohm positiveAFE isolator'),
        ('C156', (31.0, 22.5), 'positiveAFE reservoir'), ('C157', (33.3, 22.5), 'positiveAFE reservoir')):
        choose(ref, pref, pwr, role)

    selected = {p['ref'] for p in placed}
    missing = sorted(newrefs - selected)
    exports = [{k: v for k, v in p.items() if not k.startswith('_')} for p in placed]
    report = {
        'schema': 'adc10-labtool-independent-pcb-placement-proposal-20261018-v1',
        'status': 'CONDITIONAL_PLACEMENT_NOT_EXECUTABLE' if not missing and not failure else 'INCOMPLETE_PLACEMENT_REQUIRES_REFINEMENT',
        'sourcePath': str(SOURCE), 'sourceSha256': sha(SOURCE), 'originalPcbBaselinePath':str(BASELINE_SOURCE),'originalPcbBaselineSha256':sha(BASELINE_SOURCE),'checkpointPath': str(CHECK), 'checkpointSha256': sha(CHECK),
        'schematicPlanSha256': sha(HERE / 'schematic-plan.json'), 'newPartCountExpected': 83, 'newPartsProposed': len(newrefs & selected),
        'existingPartsRelocatedProposed': sorted(moved & selected), 'unplacedNewRefs': missing, 'failedSearches': failure,
        'nativeApiCalls': 0, 'designModified': False, 'manufacturingApproved': False,
        'existingVias640Preserved': True, 'existingDrills799Preserved': True, 'layers6Rules18Preserved': True,
        'screeningClearanceMm': CLR, 'protectedObstacles': {'topComponentPadsAndViasAndNonTargetRoutes': len(obstacles), 'componentCourts': len(oldcourts), 'topFills': len(fill_shapes), 'invalidTopFillsNotSilentlyRepaired': invalid_fills},
        'edits': exports,
        'eligibleOldAFERouteReworkInventory': [{k:v for k,v in q.items() if k != 'shape'} for q in eligible_routes],
        'conditions': ['This is NOT a live/API execution manifest. RebaseeverycomponentID/fullbodyagainstactualECOsourcebeforeapplying.', 'All83newparts screened against literal protectedTOPcopper/oldcomponentcourts andagainstnewpad/court peers. Anyunplacedpart is explicitlylisted;neverclaimcompleteuntilzero.', 'OldPRE/DRV/ADC_BIAS_2V5 geometry insideleft28mm is marked eligibleforboundedrework, notdeletedbythisanalysis. NativeECO mayrename/splitthoseobjects;reviewactualIDsandpincontractsfirst.', 'ExistingSMA,input3.32kresistors,finalOPA320/+3.3decaps,47ohmresistors,alllongpost47ADCtraces,andMCUreservoirlocationsarefixed.', 'EverylistedstaticTOPGNDfillneedsreviewedlocalpad/routeclearancevoids;noentire-plane regeneration andnoarbitraryinvalidpolygonrepair.', 'Packageenvelopesuseexactnativecourtyardswhenavailableelseconservativepad/silkenvelope+0.15mm;notclaimedfactoryassemblysignoff.', 'No routing or railphysicalconnectivityhasbeenproved. Decouplinglooplength,feedbackrouting,pumpflyingcaploop,signalreturn,planeanchors,fullnativeDRCandsaved/reopenednetlistchecksremainrequired.', 'Preserveall640baselineVIAs/799drills,4mountingholes,CN1,J18,6layers18rules,allunrelatedphysicalUIDs. NewroutingVIAsifneededmustbeexplicitlyreviewed;noneareproposedhere.', 'Commonpowerlowerregionhas8BOTTOMPG11/12/13routes;TOPplacementdoesnotauthorizechangingthem. Keepnativebottomcopperanddrillsbyteexact.'],
    }
    path = HERE / 'independent-pcb-placement-rebased-eco-proposal.json'
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf8')
    print(json.dumps({'path':str(path),'sha256':sha(path),'status':report['status'],'newParts':report['newPartsProposed'],'existingMoves':len(report['existingPartsRelocatedProposed']),'failures':failure},ensure_ascii=False))


if __name__ == '__main__': main()
