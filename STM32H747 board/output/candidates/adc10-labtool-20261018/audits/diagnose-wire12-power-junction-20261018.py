"""Exact two-diagonal shared junction diagnosis only; no waiver/native repair."""
import json
import runpy
from decimal import Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parents[2]
M = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-copper-readback-20261018.py'))
NET = '+5V_AFE'


def coords(body):
    return tuple(F(str(body[k])) for k in ('startX', 'startY', 'endX', 'endY'))


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def main():
    mp = HERE / 'pcb-final-copper-v5-execution.json'
    manifest = M['load'](mp)
    prior_path = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire11-20261018.epru'
    actual_path = ROOT / 'output/validation/native-adc10-pcb-labtool_copper_wire12-20261018.epru'
    assert M['sha'](actual_path) == '00f0707624248ec16b99ee47a638e63608764652c3ddeb12a1f4af890104910d'
    base, prior, actual = M['source'](Path(manifest['sourcePath'])), M['source'](prior_path), M['source'](actual_path)
    ops = []
    for batch in manifest['batches']:
        ops.extend(batch['operations'])
        if batch['stage'] == 'copper_wire12':
            break
    keys = ['LABTOOL_PWR_0029', 'LABTOOL_LOCAL_0333']
    lines = [next(o for o in ops if o.get('key') == key) for key in keys]
    ac = [tuple(F(str(v)) for v in o['startXYMil'] + o['endXYMil']) for o in lines]
    a, c, d, e = ac[0][:2], ac[0][2:], ac[1][:2], ac[1][2:]
    first, second = (c[0] - a[0], c[1] - a[1]), (e[0] - d[0], e[1] - d[1])
    delta = d[0] - a[0], d[1] - a[1]
    denominator = cross(first, second)
    t, u = cross(delta, second) / denominator, cross(delta, first) / denominator
    assert 0 < t < 1 and 0 < u < 1
    intersection = a[0] + t * first[0], a[1] + t * first[1]
    b = tuple(M['exact_q4_fraction'](v) for v in intersection)
    assert b == (F('1189.5335'), F('914.9902'))
    ids = [['67638d82c151ff5c', '69b01f23e1e41d14'], ['0fafc554d4913fb3', '1d1d25791ed7a65e']]
    details = []
    for op, segment, split_ids in zip(lines, ac, ids):
        p, q = segment[:2], segment[2:]
        normalized = [(*p, *b), (*b, *q)]
        width = M['q'](op['widthMil'])
        for rid, required in zip(split_ids, normalized):
            body = actual['LINE', rid]
            assert coords(body) == required and body['netName'] == NET and body['layerId'] == 1 and body['width'] == width
            assert body['partitionId'] == '' and body['groupId'] == 0 and body['locked'] is False and body['zIndex'] == -1
        with localcontext() as ctx:
            ctx.prec = 70
            def dec(v):return Decimal(v.numerator) / Decimal(v.denominator)
            vx, vy = q[0] - p[0], q[1] - p[1]
            normal = abs(dec(vx * (b[1] - p[1]) - vy * (b[0] - p[0]))) / dec(vx * vx + vy * vy).sqrt()
        details.append(dict(plannedKey=op['key'], plannedOperation=op, plannedOperationSha256=M['value_sha'](op),
                            originalACmil=[float(v) for v in segment], widthMilRequested=op['widthMil'], widthMilSerialized=width,
                            actualSplitIds=split_ids, actualSplitBodies={rid:actual['LINE',rid] for rid in split_ids},
                            actualSplitBodySha256={rid:M['value_sha'](actual['LINE',rid]) for rid in split_ids},
                            normalizedSegmentsMil=[[float(v) for v in s] for s in normalized],
                            maximumNormalDeviationMm=float(normal * Decimal('.0254'))))
    old_id = 'ca3d603b687e06c4'
    assert coords(prior['LINE', old_id]) == ac[1]
    expected, observed = [], []
    for (kind, rid), body in base.items():
        if kind == 'LINE' and body.get('netName') == NET and body.get('layerId') == 1:
            expected.append((rid, coords(body), F(str(body['width']))))
    for op in ops:
        if op['action'] == 'line' and op['net'] == NET and op['layerId'] == 1:
            expected.append((op['key'], tuple(F(str(v)) for v in op['startXYMil'] + op['endXYMil']), F(str(M['q'](op['widthMil'])))))
    for (kind, rid), body in actual.items():
        if kind == 'LINE' and body.get('netName') == NET and body.get('layerId') == 1:
            observed.append((rid, coords(body), F(str(body['width']))))
    normalized = [x for x in expected if x[0] not in keys]
    for detail in details:
        normalized.extend((detail['plannedKey'] + ':' + str(i), tuple(F(str(v)) for v in s), F(str(detail['widthMilSerialized'])))
                          for i, s in enumerate(detail['normalizedSegmentsMil']))
    proofs = []
    for width in sorted({x[2] for x in expected + observed}):
        def union(entries):return M['canonical_segments']([tuple(float(v) for v in s) for _, s, w in entries if w == width])
        raw, adjusted, got = union(expected), union(normalized), union(observed)
        proofs.append(dict(widthMil=float(width), originalExpectedEqual=raw == got, normalizedExpectedExact=adjusted == got,
                           originalSupportCount=len(raw), normalizedSupportCount=len(adjusted), actualSupportCount=len(got)))
    assert all(p['normalizedExpectedExact'] for p in proofs)
    protected = {kind: dict(count=sum(k[0] == kind for k in prior), bodyExact={k:v for k,v in prior.items() if k[0] == kind}
        == {k:v for k,v in actual.items() if k[0] == kind}) for kind in
        ['COMPONENT','ATTR','PAD_NET','VIA','FILL','RULE','RULE_TEMPLATE','LAYER','LAYER_PHYS','PAD','ARC','POLY','STRING','NET','RULE_SELECTOR']}
    assert all(p['bodyExact'] for p in protected.values())
    failed_path = HERE / 'audits/copper-readback-copper_wire12-20261018T083414155154Z-117a5fef.json'
    assert M['sha'](failed_path) == 'ef36357a29e40d91f84790c0710657d350d52d6ba7827b34c7ca93349db98072'
    failed = M['load'](failed_path)
    assert len(failed['errors']) == 2 and all(x['code'] == 'LINE_UNION_NOT_EXACT' and x['net'] == NET for x in failed['errors'])
    output = dict(schema='focused-wire12-double-diagonal-native-junction-diagnostic-v1', nativeCalls=0, nativeModified=False,
                  approvalGranted=False, primaryAuditStillFailed=True, physicalOriginalExactEqualityClaimed=False,
                  manifestPath=str(mp), manifestSha256=M['sha'](mp), net=NET, layerId=1,
                  priorSourcePath=str(prior_path), priorSourceSha256=M['sha'](prior_path),
                  actualSourcePath=str(actual_path), actualSourceSha256=M['sha'](actual_path),
                  failedOriginalAuditPath=str(failed_path), failedOriginalAuditSha256=M['sha'](failed_path),
                  oldPriorCrossingId=old_id, oldPriorCrossingBody=prior['LINE',old_id],
                  oldPriorCrossingBodySha256=M['value_sha'](prior['LINE',old_id]),
                  exactIntersectionMil=[str(v) for v in intersection], actualSerializedJunctionMil=[float(v) for v in b],
                  perAxisRoundingDeltaMil=[float(v-z) for v,z in zip(b,intersection)],
                  q4MilRoundOfRationalIntersectionExact=True, segmentIntersectionParameters=[str(t),str(u)],
                  maximumPerAxisGridBoundMil=.00005, withinPerAxisBound=all(abs(v-z)<=F(1,20000) for v,z in zip(b,intersection)),
                  segments=details, allPerWidthNormalizedUnionsExact=True, perWidthProofs=proofs, protectedNonLineBodies=protected,
                  existingWire10QualificationUnchanged=all(actual['LINE',rid] == prior['LINE',rid] for rid in ['06e4e9cdd77323ba','e037cb9f75a626cf']),
                  otherNetsLayersWidthsExactFromFailedFullAudit=all(p.get('normalizedNativeGeometryExact',p['exactRationalCenterlineUnionEqual'])
                      for p in failed['lineGeometryProofs'] if not (p['net']==NET and p['layerId']==1 and p['widthMil'] in (8,15.748))),
                  physicalCopperAreaDifference='Not a qualification criterion. Approximate Minkowski measurements may be reported separately; original physical equality is NOT claimed.',
                  requirements=['Root hash-pinned exact-case approval required before auditor normalization.',
                    'Only these two planned segments and four actual full bodies/IDs at independently calculated q4 intersection may be normalized.',
                    'All other per-width/net/layer geometry exact and all original-body/rule/pin protections remain mandatory.',
                    'Foreign-copper/all863-drill clearance, native full DRC, final saved bridge and whole-project audits remain separate gates.'])
    out = HERE / 'audits/wire12-power-junction-diagnostic-v1.json'
    assert not out.exists()
    out.write_text(json.dumps(output, indent=2)+'\n', encoding='utf8')
    print(json.dumps(dict(report=str(out), sha256=M['sha'](out), exactIntersectionMil=output['exactIntersectionMil'],
                         junction=output['actualSerializedJunctionMil'], deltaMil=output['perAxisRoundingDeltaMil'],
                         deviations=[d['maximumNormalDeviationMm'] for d in details], normalizedProofs=proofs,
                         priorCrossingBodySha256=output['oldPriorCrossingBodySha256'])), flush=True)


if __name__ == '__main__':
    main()
