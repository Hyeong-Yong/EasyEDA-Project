"""Offline one-via candidate for the preserved Bottom 70 mm2 GND piece."""
import ast
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path
from shapely.geometry import Point, Polygon, LineString

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
LAB = HERE.parent
RT = LAB / 'routing'
PLACEMENT = LAB / 'independent-pcb-placement-short-negative-commonpower-v4-proposal.json'
MODULES = [RT / n for n in ['frozen-local-ground-phase332-v2.json', 'commonpower-top-local-v5-short-fly-review.json',
                           'independent-raw5-bilayer-route-v2-shortvia.json', 'independent-optional-pump-three-ground-vias-v3.json']]
PORTS = RT / 'frozen-shared46-ports-v5.json'
FILLPLAN = HERE / 'local-static-fill-clearance-phase366-v4-commonv5-42ports-approved2notches.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
    source_plan = json.loads(FILLPLAN.read_text(encoding='utf8'))
    target = next(l for l in source_plan['fillCreateOperations'] if l['sourceParentPrimitiveId'] == 'a1d7888349e74585')
    target_shape = p['geom'](target['afterPath'])
    modules = [json.loads(q.read_text(encoding='utf8')) for q in MODULES]
    lines = [line for mod in modules for line in mod.get('newLineCreates', [])]
    combined_path = HERE / 'bottom-stitch-model-fixed-lines.json'
    combined_path.write_text(json.dumps({'newLineCreates': lines}, indent=2) + '\n', encoding='utf8')
    helper = ROOT / 'scripts/plan-adc10-labtool-via-ports-20261018.py'
    tree = ast.parse(helper.read_text(encoding='utf8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    stop = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'tree' for t in n.targets))
    fn.body = fn.body[:stop] + [ast.Return(value=ast.Call(func=ast.Name(id='locals', ctx=ast.Load()), args=[], keywords=[]))]
    tree.body = [n for n in tree.body if not isinstance(n, ast.If)]
    env = {'__file__': str(helper), '__name__': 'readonly_bottom_stitch_model'}
    exec(compile(ast.fix_missing_locations(tree), str(helper), 'exec'), env)
    argv = sys.argv
    sys.argv = ['model', '--placement', str(PLACEMENT), '--routes', str(combined_path)]
    try:
        m = env['main']()
    finally:
        sys.argv = argv
    port_data = json.loads(PORTS.read_text(encoding='utf8'))
    port_list = port_data.get('viasProposed', port_data.get('newViaCreates', []))
    vias = {v['key']: v for v in port_list}
    for mod in modules:
        for v in mod.get('newViaCreates', []):
            if v['key'] in vias:
                assert v == vias[v['key']] or (v['xyMm'] == vias[v['key']]['xyMm'] and v['net'] == vias[v['key']]['net'])
            vias[v['key']] = v
    copper = m['copper'][:]
    for v in vias.values():
        copper.append({'key': v['key'], 'net': v['net'].casefold(), 'shape': Point(v['xyMm']).buffer(v['viaDiameterMm'] / 2, resolution=64), 'layers': (1, 2, 15, 16, 17, 18)})
    assert len(m['drills']) == 799
    candidates = [(round(30.5 + .1 * x, 3), round(75 + .1 * y, 3)) for x in range(-10, 51) for y in range(-10, 91)]
    candidates.sort(key=lambda xy: math.dist(xy, (30.5, 75)))
    accepted = []
    tested = 0
    placement = json.loads(PLACEMENT.read_text(encoding='utf8'))
    courts = [Polygon(p['rectangle'](q['conservativeCourtBoundsMm'])) for q in placement['edits']]
    for xy in candidates:
        tested += 1
        center = Point(xy)
        via = center.buffer(.225, resolution=64)
        hole = center.buffer(.1, resolution=64)
        if not target_shape.covers(via.buffer(.05)):
            continue
        if any(via.distance(c) < .05 for c in courts):
            continue
        if any(o['net'] != 'gnd' and via.distance(o['shape']) < .17 for o in copper):
            continue
        if any(via.distance(s) < .06 for _, s in m['allpads']):
            continue
        old_gap = min(hole.distance(s) for _, s in m['drills'])
        new_gap = min(hole.distance(Point(v['xyMm']).buffer(v['holeDiameterMm'] / 2, resolution=64)) for v in vias.values())
        if old_gap < .301 or new_gap < .301:
            continue
        inner_contacts = [f['id'] for f in m['fills'] if f['net'].casefold() == 'gnd' and f['layerId'] in (15, 18) and f['valid'] and via.intersection(f['shape']).area > 1e-8]
        if not inner_contacts:
            continue
        cuts = [{'id': f['id'], 'layerId': f['layerId'], 'net': f['net'], 'valid': f['valid']} for f in m['fills']
                if f['net'].casefold() != 'gnd' and via.buffer(.17).intersects(f['shape'].envelope) and (not f['valid'] or via.buffer(.17).intersects(f['shape']))]
        if any(not f['valid'] for f in cuts):
            continue
        accepted.append({'key': 'BOTTOM_GND_LOBE_STITCH_CANDIDATE_' + str(len(accepted) + 1), 'net': 'GND', 'xyMm': list(xy),
                         'viaDiameterMm': .45, 'holeDiameterMm': .2, 'allLayers': [1, 2, 15, 16, 17, 18],
                         'minimumOriginal799DrillEdgeGapMm': old_gap, 'minimumReservedNewDrillEdgeGapMm': new_gap,
                         'nonGroundSourceAndModuleCopperGapMm': min(via.distance(o['shape']) for o in copper if o['net'] != 'gnd'),
                         'minimumAnyPadGapMm': min(via.distance(s) for _, s in m['allpads']),
                         'insideRetainedBottomLobeWithReserveMm': .05, 'inner15Or18GroundPlaneContacts': inner_contacts,
                         'requiresLocalFillAntipads': cuts, 'groundStubNeeded': False})
        if len(accepted) == 3:
            break
    result = {'schema': 'adc10-labtool-bottom70-ground-stitch-candidate-readonly-v1', 'screenPassed': bool(accepted),
              'targetLobeKey': target['key'], 'targetLobeAreaMm2': target['areaMm2'], 'targetLobeBoundsMm': target['boundsMm'],
              'fillPlanSha256': sha(FILLPLAN), 'placementSha256': sha(PLACEMENT), 'reservedPortPlanSha256': sha(PORTS),
              'modules': [{'path': str(q), 'sha256': sha(q)} for q in MODULES], 'originalDrills': 799, 'reservedNewVias': len(vias),
              'sitesTested': tested, 'candidates': accepted, 'nativeCalls': 0, 'nativeModified': False,
              'scope': 'Candidate only, no approval to create. V4 fixed-source model plus row332/common34/raw9/pump3 and reserved46 geometry. R202/C158 V5 pose and final shared routes must be rechecked.',
              'manufacturingApproved': False}
    output = HERE / 'bottom70-ground-stitch-candidates-v4-module-screen.json'
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'screenPassed': bool(accepted), 'report': str(output), 'sha256': sha(output), 'candidates': accepted}))


if __name__ == '__main__':
    main()
