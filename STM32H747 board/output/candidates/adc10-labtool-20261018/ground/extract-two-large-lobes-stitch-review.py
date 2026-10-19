"""Extract only the two parent-protected large local lobes for via-site review."""
import argparse
import json
import runpy
from pathlib import Path
from shapely.geometry import Point

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    plan = json.loads(args.manifest.read_text(encoding='utf8'))
    assert plan['passed']
    rows = P['G']['PARSE'](Path(plan['source']))
    old_plan = json.loads((HERE / 'local-static-fill-clearance-v6-final526-62vias-preserving.json').read_text(encoding='utf8'))
    replacements = {o['primitiveId']: o for o in plan['fillModifyOperations']}
    targets = [(1, 20.077817639411037), (2, 7.58451118903618)]
    lobes = []
    for layer, area in targets:
        match = [l for l in plan['fillCreateOperations'] if l['net'] == 'GND' and l['layerId'] == layer and abs(l['areaMm2'] - area) < 1e-8]
        assert len(match) == 1
        lobe = match[0]
        old = next(l for l in old_plan['fillCreateOperations'] if l['net'] == 'GND' and l['layerId'] == layer and abs(l['areaMm2'] - area) < 1e-8)
        nominal = P['geom'](lobe['afterPathsExplicitlyClosedForApi'])
        projections = []
        for (kind, rid), body in rows.items():
            if kind != 'FILL' or body.get('netName') != 'GND' or body.get('layerId') not in (15, 17, 18):
                continue
            paths = replacements[rid]['afterPathsExplicitlyClosedForApi'] if rid in replacements else body['path']
            shape = P['geom'](paths)
            if not shape.is_valid or not shape.intersects(nominal):
                continue
            overlap = shape.intersection(nominal).area
            if overlap <= 1e-12:
                continue
            contacts = []
            for (k, vid), via in rows.items():
                if k != 'VIA' or via.get('netName') != 'GND' or body['layerId'] in via.get('unusedInnerLayers', []):
                    continue
                center = Point(via['centerX'] * P['MM'], via['centerY'] * P['MM'])
                annulus = center.buffer(via['viaDiameter'] * P['MM'] / 2, resolution=32).difference(center.buffer(via['holeDiameter'] * P['MM'] / 2, resolution=32))
                if annulus.intersection(shape).area > 1e-12:
                    contacts.append(vid)
            projections.append({'primitiveId': rid, 'layerId': body['layerId'], 'valid': True,
                                'nominalProjectedOverlapAreaMm2': overlap,
                                'postMaskPathSha256': P['digest'](paths), 'originalGroundViaContacts': contacts,
                                'qualification': 'Projection only, not a cross-layer connection. A proposed plated via must actually contact this valid plane and pass all-layer clearance/drill/body checks.'})
        lobes.append({**lobe, 'pathExactVsV3': lobe['afterPathsExplicitlyClosedForApi'] == old['afterPathsExplicitlyClosedForApi'],
                      'projectedValidInnerGroundPlanes': projections,
                      'authorizedAction': 'At most one new0.45/0.20mm GND stitch per lobe, zero newLINE preferred; site still requires independent all-layer clearance/drill/body/noVIP and globalVSS proof.'})
    result = {'schema': 'protected-two-large-local-lobes-stitch-review-v1',
              'manifest': str(args.manifest.resolve()), 'manifestSha256': P['sha'](args.manifest),
              'source': plan['source'], 'sourceSha256': plan['sourceSha256'],
              'placement': plan['placement'], 'placementSha256': plan['placementSha256'], 'routes': plan['routes'],
              'lobes': lobes, 'nativeCalls': 0, 'nativeModified': False, 'deletionAuthorized': False}
    target = HERE / (args.output_prefix + '.json')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target),
                      'lobes': [{'key': l['key'], 'areaMm2': l['areaMm2'], 'boundsMm': l['boundsMm'],
                                 'pathExactVsV3': l['pathExactVsV3']} for l in lobes]}))


if __name__ == '__main__':
    main()
