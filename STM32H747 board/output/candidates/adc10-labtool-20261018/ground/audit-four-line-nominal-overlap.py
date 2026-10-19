"""Independent raw-FILL/annulus positive-overlap proof for four frozen bridges."""
import argparse
import json
import runpy
from pathlib import Path
from shapely.geometry import Point, LineString

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--addendum', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    source_sha = P['sha'](args.source)
    addendum_sha = P['sha'](args.addendum)
    assert addendum_sha == '801e10de9ece1ae57c80c13e289277377e80d4576874acaa3d80ddb56a1c6da9'
    contract = json.loads(args.addendum.read_text())
    rows = P['G']['PARSE'](args.source)

    def shape(kind, rid):
        b = rows[kind, rid]
        assert b['netName'] == 'GND'
        if kind == 'FILL':
            s = P['geom'](b['path'])
            assert s.is_valid
            return s
        assert kind == 'VIA'
        p = Point(b['centerX'] * P['MM'], b['centerY'] * P['MM'])
        return p.buffer(b['viaDiameter'] * P['MM'] / 2, resolution=128).difference(
            p.buffer(b['holeDiameter'] * P['MM'] / 2, resolution=128))

    proof = []
    for op in contract['selectedCandidateLines']:
        line = LineString([op['startXYmm'], op['endXYmm']]).buffer(op['widthMm'] / 2, resolution=128)
        target_area = line.intersection(shape(op['targetKind'], op['targetId'])).area
        anchor_area = line.intersection(shape(op['anchoredCandidateKind'], op['anchoredCandidateId'])).area
        proof.append({'key': op['key'], 'target': op['targetId'], 'anchor': op['anchoredCandidateId'],
                      'targetOverlapMm2': target_area, 'anchorOverlapMm2': anchor_area,
                      'positiveBoth': target_area > 0 and anchor_area > 0})
    assert all(p['positiveBoth'] for p in proof)
    assert P['sha'](args.source) == source_sha and P['sha'](args.addendum) == addendum_sha
    report = {'schema': 'four-line-positive-nominal-copper-overlap-v1', 'passed': True,
              'source': str(args.source.resolve()), 'sourceSha256': source_sha, 'addendumSha256': addendum_sha,
              'generatorSha256': P['sha'](Path(__file__)), 'noFillPenBufferUsed': True,
              'viaHoleExcluded': True, 'bridgeProofs': proof, 'nativeCalls': 0,
              'nativeModified': False, 'strictNativeDrcRequired': True}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(args.output), 'sha256': P['sha'](args.output), 'passed': True}))


if __name__ == '__main__':
    main()
