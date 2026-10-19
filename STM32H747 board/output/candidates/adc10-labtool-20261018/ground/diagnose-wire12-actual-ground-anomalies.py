"""Partial actual-wire12 diagnosis; expected unfinished stubs are not a PASS."""
import json
import runpy
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))
ROOT = P['ROOT']
SOURCE = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire12-20261018.epru'
CP = ROOT / 'output/checkpoints/STM32H747_labtool_107_placed_v6_wip_20261018.epro2'
FROZEN = HERE / 'local-static-fill-clearance-v6-routingv5-approved116-omission-final.json'
TARGETS = ['70d49360e5e3892f', '1d12bb8046962a4c', '1e87af6d1a83be6a']
VIA = 'e0f0dcd1975e7708'


def main():
    assert P['sha'](SOURCE) == '00f0707624248ec16b99ee47a638e63608764652c3ddeb12a1f4af890104910d'
    actual = P['G']['PARSE'](SOURCE)
    frozen = json.loads(FROZEN.read_text(encoding='utf8'))
    before = P['G']['PARSE'](Path(frozen['source']))
    prior_map = json.loads((HERE / 'actual-via2-focused-fill-serialization-geometry-only-audit.json').read_text(encoding='utf8'))
    mapped = {m['actualNativeFillId']: m['plannedKey'] for m in prior_map['actualRetainedFillMappings']}
    planned = {l['key']: l for l in frozen['fillCreateOperations']}
    metadata, audits = [], []
    for rid in TARGETS:
        b = actual['FILL', rid]
        shape = P['geom'](b['path'])
        key = mapped.get(rid)
        entry = {'id': rid, 'layerId': b['layerId'], 'net': b['netName'], 'widthMil': b['width'],
                 'boundsMm': list(shape.bounds), 'valid': shape.is_valid, 'areaMm2': shape.area,
                 'existedBeforeThisLabtoolCopper': ('FILL', rid) in before,
                 'beforeBodyExactIfExisting': before.get(('FILL', rid)) == b if ('FILL', rid) in before else None,
                 'plannedKey': key, 'sourceParentPrimitiveId': planned[key]['sourceParentPrimitiveId'] if key else None,
                 'actualBodySha256': P['digest'](b)}
        metadata.append(entry)
        audits.append({'key': key or 'EXISTING_' + rid, 'existingNativePrimitiveId': rid,
                       'net': b['netName'], 'layerId': b['layerId'], 'widthMil': b['width'],
                       'afterPathsExplicitlyClosedForApi': b['path']})
    v = actual['VIA', VIA]
    metadata.append({'id': VIA, 'type': 'VIA', 'net': v['netName'],
                     'xyMm': [v['centerX'] * P['MM'], v['centerY'] * P['MM']],
                     'diameterMm': v['viaDiameter'] * P['MM'], 'holeMm': v['holeDiameter'] * P['MM'],
                     'unusedInnerLayers': v.get('unusedInnerLayers', []), 'bodyExactVsBaseline': before['VIA', VIA] == v})
    print(json.dumps({'initialExactMapping': metadata}), flush=True)
    placement_path = HERE / 'wire12-partial-actual-library-context.json'
    placement_path.write_text(json.dumps({'checkpointPath': str(CP), 'edits': []}, indent=2) + '\n', encoding='utf8')
    context = {'passed': True, 'source': str(SOURCE), 'sourceSha256': P['sha'](SOURCE),
               'placement': str(placement_path), 'placementSha256': P['sha'](placement_path),
               'routes': [], 'fillModifyOperations': [], 'fillCreateOperations': [],
               'auditExistingFillPrimitives': audits,
               'scope': 'Known-partial actual-wire12 graph only;6lastGNDstubs remain uncreated. This is not final connection approval.'}
    context_path = HERE / 'wire12-partial-actual-graph-input.json'
    context_path.write_text(json.dumps(context, indent=2) + '\n', encoding='utf8')
    result = subprocess.run([sys.executable, str(HERE / 'audit-local-ground-lobe-connectivity.py'),
                             '--manifest', str(context_path), '--output-prefix', 'wire12-partial-direct-actual-ground'], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    graph_path = HERE / 'wire12-partial-direct-actual-ground.json'
    graph = json.loads(graph_path.read_text(encoding='utf8'))
    report = {'schema': 'wire12-partial-actual-outside-afe-ground-diagnosis-v1', 'finalPassClaim': False,
              'nativeCalls': 0, 'nativeModified': False, 'sourceSha256': P['sha'](SOURCE),
              'mapping': metadata, 'graph': str(graph_path), 'graphSha256': P['sha'](graph_path),
              'unanchoredOriginalGroundViaIds': graph['unanchoredOriginalViaIds'],
              'unanchoredTargetGroundPads': graph['unanchoredTargetGroundPhysicalPads'],
              'unanchoredNonTargetGroundPads': graph['unanchoredNonTargetGroundPhysicalPads'],
              'targetFillAnchorResults': graph['lobesSortedByArea'],
              'knownUncreatedGndStubRefs': ['C126', 'C129', 'C138', 'C141', 'C144', 'C147']}
    target = HERE / 'wire12-partial-outside-afe-ground-diagnosis.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': P['sha'](target),
                      'unanchoredVias': graph['unanchoredOriginalViaIds'],
                      'fillResults': [{'key': r['key'], 'anchored': r['reachesActualMCUVssA17'],
                                       'contactCounts': r['directSameLayerContactCounts']} for r in graph['lobesSortedByArea']]}), flush=True)


if __name__ == '__main__':
    main()
