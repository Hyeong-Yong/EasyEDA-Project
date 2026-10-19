"""Local sufficient anchor witnesses against an already audited whole ground graph."""
import argparse
import json
import runpy
from pathlib import Path
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    manifest_path = HERE / 'local-static-fill-clearance-v6-routingv4-526-62vias-preserving.json'
    graph_path = HERE / 'local-ground-lobe-connectivity-v6-routingv4-526-62vias.json'
    assert P['sha'](manifest_path) == '7a8c66abfa32ae896645c998828b199f66068224cd1648545d0b69562eecfa86'
    assert P['sha'](graph_path) == '26d61300c601186ff2ede9395325f0d035ba2e09c70069edea7e9e25c9b5236f'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    graph = json.loads(graph_path.read_text(encoding='utf8'))
    assert graph['loadConnectivityPassed']
    rooted = {r['id'] for r in graph['originalViaAnchorAudit'] if r['reachesSelectedSourcePad']}
    assert len(rooted) == 199
    rows = P['G']['PARSE'](Path(manifest['source']))
    replacements = {o['primitiveId']: o for o in manifest['fillModifyOperations']}
    lobe_map = {l['key']: l for l in manifest['fillCreateOperations']}
    candidates = json.loads(args.candidates.read_text(encoding='utf8'))
    if isinstance(candidates, dict):
        if 'candidates' in candidates:
            candidates = candidates['candidates']
        else:
            candidates = [{'key': v['key'], 'lobeKey': v['targetPreservedLobeKey'], 'xyMm': v['xyMm'],
                           'diameterMm': v['viaDiameterMm'], 'holeDiameterMm': v['holeDiameterMm']}
                          for v in candidates['newViaCreates']]
    results = []
    for candidate in candidates:
        lobe = lobe_map[candidate['lobeKey']]
        xy = candidate['xyMm']
        diameter, hole = candidate.get('diameterMm', .45), candidate.get('holeDiameterMm', .2)
        center = Point(xy)
        annulus = center.buffer(diameter / 2, resolution=64).difference(center.buffer(hole / 2, resolution=64))
        lobe_physical = P['geom'](lobe['afterPathsExplicitlyClosedForApi']).buffer(lobe['widthMil'] * P['MM'] / 2)
        witnesses = []
        for (kind, rid), body in rows.items():
            if kind != 'FILL' or body.get('netName') != 'GND' or body.get('layerId') not in (15, 17, 18):
                continue
            paths = replacements[rid]['afterPathsExplicitlyClosedForApi'] if rid in replacements else body['path']
            shape = P['geom'](paths)
            if not shape.is_valid:
                continue
            overlap = annulus.intersection(shape).area
            if overlap <= 1e-12:
                continue
            for vid in sorted(rooted):
                via = rows['VIA', vid]
                if body['layerId'] in via.get('unusedInnerLayers', []):
                    continue
                c = Point(via['centerX'] * P['MM'], via['centerY'] * P['MM'])
                old_annulus = c.buffer(via['viaDiameter'] * P['MM'] / 2, resolution=64).difference(c.buffer(via['holeDiameter'] * P['MM'] / 2, resolution=64))
                original_contact = shape.intersection(old_annulus).area
                if original_contact > 1e-12:
                    witnesses.append({'planeId': rid, 'layerId': body['layerId'],
                                      'validConnectedPolygon': True, 'postMaskPathSha256': P['digest'](paths),
                                      'candidateAnnulusOverlapAreaMm2': overlap,
                                      'existingViaId': vid, 'existingViaAnnulusOverlapAreaMm2': original_contact,
                                      'existingViaActuallyAnchoredToMcuVss': True})
                    break
        results.append({'candidate': candidate, 'annulusFullyCoveredByPreservedLobe': lobe_physical.covers(annulus),
                        'lobeAnnulusOverlapAreaMm2': lobe_physical.intersection(annulus).area,
                        'anchorWitnesses': witnesses,
                        'anchorProofPassed': lobe_physical.intersection(annulus).area > 1e-12 and bool(witnesses)})
    report = {'schema': 'large-two-ground-lobe-stitch-local-anchor-witness-audit-v1',
              'passed': all(r['anchorProofPassed'] for r in results), 'results': results,
              'manifestSha256': P['sha'](manifest_path), 'graphSha256': P['sha'](graph_path),
              'candidatesSha256': P['sha'](args.candidates), 'nativeCalls': 0, 'nativeModified': False,
              'scope': 'Sufficient DC anchor proof only. SourceV4 graph establishes each witness oldvia reaches MCUVSS via actual Cu/barrels. Independent all-layer copper/drill/body/noVIP and final whole-net graph are still mandatory.'}
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target), 'passed': report['passed'], 'results': results}))


if __name__ == '__main__':
    main()
