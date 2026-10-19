"""Read-only final actual nominal/pen seam evidence; no native operations."""
import argparse
import json
import runpy
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shapely.ops import nearest_points

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
ROOT = P['ROOT']
BASE = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v6_saved-20261018.epru'
CP = ROOT / 'output/checkpoints/STM32H747_labtool_107_placed_v6_wip_20261018.epro2'
LEGACY = ['70d49360e5e3892f', '1d12bb8046962a4c', '1e87af6d1a83be6a']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--prefix', required=True)
    ap.add_argument('--addendum', type=Path)
    args = ap.parse_args()
    assert Path(args.prefix).name == args.prefix
    source_sha = P['sha'](args.source)
    rows = P['G']['PARSE'](args.source)
    before = P['G']['PARSE'](BASE)
    mapping = json.loads((HERE / 'actual-via2-focused-fill-serialization-geometry-only-audit.json').read_text())['actualRetainedFillMappings']
    selections = [(m['plannedKey'], m['actualNativeFillId']) for m in mapping]
    selections += [('EXISTING_' + rid, rid) for rid in LEGACY]
    queries = []
    for key, rid in selections:
        body = rows['FILL', rid]
        queries.append({'key': key, 'existingNativePrimitiveId': rid, 'net': body['netName'],
                        'layerId': body['layerId'], 'widthMil': body['width'],
                        'afterPathsExplicitlyClosedForApi': body['path']})
    poses = HERE / (args.prefix + '-actual-library-context.json')
    poses.write_text(json.dumps({'checkpointPath': str(CP), 'edits': []}, indent=2) + '\n')
    context = {'passed': True, 'source': str(args.source.resolve()), 'sourceSha256': source_sha,
               'placement': str(poses), 'placementSha256': P['sha'](poses),
               'routes': [], 'fillModifyOperations': [], 'fillCreateOperations': [],
               'auditExistingFillPrimitives': queries}
    if args.addendum:
        context['routes'] = [{'path': str(args.addendum.resolve()), 'sha256': P['sha'](args.addendum)}]
    context_path = HERE / (args.prefix + '-actual-graph-input.json')
    context_path.write_text(json.dumps(context, indent=2) + '\n')
    seams = []
    for rid in LEGACY:
        b = rows['FILL', rid]
        nominal = P['geom'](b['path'])
        near = []
        for (kind, other), body in rows.items():
            if kind != 'FILL' or other == rid or body.get('netName') != 'GND' or body.get('layerId') != b['layerId']:
                continue
            shape = P['geom'](body['path'])
            if not shape.is_valid:
                continue
            pts = nearest_points(nominal, shape)
            near.append({'id': other, 'distanceMm': nominal.distance(shape),
                         'nearestPointsMm': [list(p.coords)[0] for p in pts],
                         'baselineDistanceMm': P['geom'](before['FILL', rid]['path']).distance(P['geom'](before['FILL', other]['path'])) if ('FILL', other) in before else None})
        seams.append({'id': rid, 'layerId': b['layerId'], 'bodyExactVsBaseline': before['FILL', rid] == b,
                      'closestNominalGroundFills': sorted(near, key=lambda n: n['distanceMm'])[:2]})

    def run(net, ignore_pen):
        suffix = ('-gnd' if net == 'GND' else '-3v3') + ('-without-pen' if ignore_pen else '-with-pen')
        cmd = [sys.executable, str(HERE / 'audit-local-ground-lobe-connectivity.py'), '--manifest', str(context_path),
               '--net', net, '--output-prefix', args.prefix + suffix]
        if net != 'GND':
            cmd += ['--anchor-pad', 'U3:4']
        if ignore_pen:
            cmd.append('--ignore-fill-pen')
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        path = HERE / (args.prefix + suffix + '.json')
        report = json.loads(path.read_text())
        return {'net': net, 'ignoreFillPen': ignore_pen, 'path': str(path), 'sha256': P['sha'](path),
                'loadConnectivityPassed': report['loadConnectivityPassed'],
                'physicalPads': len(report.get('allPhysicalGroundPads', report.get('allPhysicalNetPads', []))),
                'nativeVias': len(report['originalViaAnchorAudit']),
                'unanchoredNativeVias': report['unanchoredOriginalViaIds'],
                'unanchoredPads': report.get('unanchoredTargetGroundPhysicalPads', report.get('unanchoredTargetNetPhysicalPads', [])) + report.get('unanchoredNonTargetGroundPhysicalPads', report.get('unanchoredNonTargetNetPhysicalPads', [])),
                'unanchoredQueriedFills': [x['key'] for x in report['lobesSortedByArea'] if not x.get('reachesActualMCUVssA17', x.get('reachesOriginalPowerSourcePad'))],
                'queriedFillCount': report['lobeCount']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(run, net, ignore) for net in ['GND', '+3V3'] for ignore in [False, True]]
        graphs = [f.result() for f in futures]
    assert P['sha'](args.source) == source_sha
    report = {'schema': 'actual-final-fill-pen-comparison-and-seam-evidence-v1', 'source': str(args.source.resolve()),
              'sourceSha256': source_sha, 'checkpointSha256': P['sha'](CP), 'seams': seams, 'graphs': graphs,
              'optionalProspectiveAddendum': str(args.addendum) if args.addendum else None,
              'nativeCalls': 0, 'nativeModified': False, 'strictNativeDrcRemainsSeparateGate': True,
              'allGraphsLoadConnected': all(g['loadConnectivityPassed'] for g in graphs)}
    target = HERE / (args.prefix + '-comparison.json')
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'graphs': graphs}), flush=True)


if __name__ == '__main__':
    main()
