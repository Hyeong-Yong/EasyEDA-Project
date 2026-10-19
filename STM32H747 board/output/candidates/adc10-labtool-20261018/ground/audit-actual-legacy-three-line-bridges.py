"""Exact three durable bridges plus one request contained in old GND traces."""
import json
import runpy
from pathlib import Path
from shapely.geometry import LineString, Point

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
ROOT = P['ROOT']
BEFORE = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire13-20261018.epru'
AFTER = ROOT / 'output/validation/native-adc10-pcb-labtool_ground_seam0-20261018.epru'
CONTRACT = HERE.parent / 'routing/frozen-legacy-ground-four-line-corrective-addendum-v1.json'


def main():
    assert P['sha'](BEFORE) == '74d29fb7f5d3579cbf12ef085f26059cad63b86aff5a3dcf8dff8a0cfaf92bfb'
    assert P['sha'](AFTER) == '49d21b37803cd04e82c401f8c3b05d1e702e17519a1b12de9db6c68d623e72d7'
    assert P['sha'](CONTRACT) == '801e10de9ece1ae57c80c13e289277377e80d4576874acaa3d80ddb56a1c6da9'
    before, after = P['G']['PARSE'](BEFORE), P['G']['PARSE'](AFTER)
    contract = json.loads(CONTRACT.read_text())
    added = set(after) - set(before)
    assert len(added) == 3 and all(k[0] == 'LINE' for k in added)
    assert not set(before) - set(after)
    altered = [k for k in before if before[k] != after[k]]
    assert altered == [('DOCHEAD', None)], altered

    def line_shape(b):
        return LineString([(b['startX'] * P['MM'], b['startY'] * P['MM']),
                           (b['endX'] * P['MM'], b['endY'] * P['MM'])]).buffer(b['width'] * P['MM'] / 2, resolution=128)

    def actor(kind, rid):
        b = after[kind, rid]
        assert b['netName'] == 'GND'
        if kind == 'FILL':
            s = P['geom'](b['path'])
            assert s.is_valid
            return s
        p = Point(b['centerX'] * P['MM'], b['centerY'] * P['MM'])
        return p.buffer(b['viaDiameter'] * P['MM'] / 2, resolution=128).difference(p.buffer(b['holeDiameter'] * P['MM'] / 2, resolution=128))

    results, matched = [], set()
    for op in contract['selectedCandidateLines']:
        a, z = op['startXYMil'], op['endXYMil']
        native = [(k, b) for k, b in after.items() if k[0] == 'LINE' and b['netName'] == 'GND' and b['layerId'] == op['layerId'] and b['width'] == 8 and
                  (b['startX'], b['startY'], b['endX'], b['endY']) == (a[0], a[1], z[0], z[1])]
        target = actor(op['targetKind'], op['targetId'])
        anchor = actor(op['anchoredCandidateKind'], op['anchoredCandidateId'])
        if native:
            assert len(native) == 1 and native[0][0] in added
            key, b = native[0]
            matched.add(key)
            shape = line_shape(b)
            ta, aa = shape.intersection(target).area, shape.intersection(anchor).area
            assert ta > 0 and aa > 0
            results.append({'key': op['key'], 'actualNativeLineId': key[1], 'actualBody': b,
                            'actualCoordinatesWidthLayerNetExactVsFrozen': True,
                            'rawTargetOverlapMm2': ta, 'rawAnchorOverlapMm2': aa,
                            'noFillPenUsed': True, 'viaHoleExcluded': True})
        else:
            assert op['key'] == 'LEGACY_GND_SEAM_BRIDGE_1'
            wanted = LineString([op['startXYmm'], op['endXYmm']]).buffer(op['widthMm'] / 2, resolution=128)
            covers = []
            for rid in ['d22bf385d3281e2e', 'd7d16ee6a48fa28a']:
                b = after['LINE', rid]
                assert before['LINE', rid] == b and b['netName'] == 'GND' and b['layerId'] == 1
                s = line_shape(b)
                missing = wanted.difference(s).area
                ta, aa = s.intersection(target).area, s.intersection(anchor).area
                assert missing == 0 and ta > 0 and aa > 0
                covers.append({'oldLineId': rid, 'oldBodyExact': True, 'requestedCapsuleOutsideOldCopperMm2': missing,
                               'oldTraceOverlapTarget70dMm2': ta, 'oldTraceOverlapD1ViaAnnulusMm2': aa})
            results.append({'key': op['key'], 'notAPersistedNewLine': True,
                            'fullyCoveredByEachUnchangedOldTrace': covers})
    assert matched == added
    report = {'schema': 'actual-three-line-and-contained-fourth-request-audit-v1', 'passed': True,
              'actualSource': str(AFTER), 'actualSourceSha256': P['sha'](AFTER), 'beforeSourceSha256': P['sha'](BEFORE),
              'contractSha256': P['sha'](CONTRACT), 'generatorSha256': P['sha'](Path(__file__)),
              'requestedLineCount': 4, 'persistedNewLineCount': 3, 'unchangedOldBodiesExceptDochead': True,
              'removedOldRecords': 0, 'newDrills': 0, 'newFills': 0, 'newVias': 0, 'bridgeProofs': results,
              'nativeCalls': 0, 'nativeModified': False, 'strictNativeDrcIsSeparateGate': True}
    out = HERE / 'actual-seam0-three-line-positive-nominal-and-covered-fourth-audit.json'
    out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(out), 'sha256': P['sha'](out), 'passed': True}))


if __name__ == '__main__':
    main()
