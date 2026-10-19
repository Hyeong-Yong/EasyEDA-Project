"""Independent four-LINE GND corrective addendum audit, native calls zero.

Main 526-LINE/64-VIA execution evidence remains a separate, immutable chain.
This helper accepts exactly two TOP and two Inner17 GND LINE creates only.
"""
import argparse
import json
import math
import runpy
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
M = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-copper-readback-20261018.py'))
S = runpy.run_path(str(ROOT / 'scripts/audit-adc10-labtool-saved-delta-20261018.py'))
VIEW = {'DOCHEAD', 'CANVAS', 'ACTIVE_LAYER', 'ELE_PLACEHOLDER'}
COORD = {'startX', 'startY', 'endX', 'endY'}
APPROVED_CORRECTION_PLAN_SHA = '7e68822c1fc7000b0366b30edabbcd6124b4da6b4951a49b77f29b81530ba513'
APPROVAL_SHA = '40baf4eedd8f31805ed18384e5dbd47524d40222c5152644ff5f334b2b2bb3aa'


def covered_bridge_one(before, after, ops, created):
    """One explicit, root-approved SDK covered-create suppression, not a tolerance.

    The requested 8-mil capsule is contained in EACH of two unchanged, wider
    collinear capsules. The rational interval/radius proof makes adding this
    operation a physical copper no-op, although per-width centerline sets differ.
    No other absent create or cross-width substitution is permitted.
    """
    op = next(o for o in ops if o['key']=='LEGACY_GND_SEAM_BRIDGE_1')
    assert op == dict(action='line', type='LINE', key='LEGACY_GND_SEAM_BRIDGE_1',
        net='GND',layerId=1,startXYMil=[1777.9528,4316.252],endXYMil=[1777.9528,4318.8976],widthMil=8.0)
    ghost = next(c for c in created if c['key']==op['key'])['id']
    assert ghost=='1d2f4c979f086326' and ('LINE',ghost) not in before and ('LINE',ghost) not in after
    old = [('d22bf385d3281e2e','8635a46b8073f8a3c36dcbfcb225f3f0caacb3bcdeaab87763b6069c6e068170'),
           ('d7d16ee6a48fa28a','54ab50dfae6064a991e6e5e9a6831b0b424f7d39f962f494f2a71f0f9718c5ce')]
    f=lambda v:Fraction(str(v))
    witnesses=[]
    for rid,bodysha in old:
        body=before['LINE',rid]
        assert S['canonical'](body)==S['canonical'](after['LINE',rid]) and M['value_sha'](body)==bodysha
        assert body['netName']=='GND' and body['layerId']==1 and body['width']==15.748
        assert f(body['startX'])==f(body['endX'])==f(op['startXYMil'][0])==f(op['endXYMil'][0])
        lo,hi=sorted([f(body['startY']),f(body['endY'])])
        a,b=sorted([f(op['startXYMil'][1]),f(op['endXYMil'][1])])
        assert lo<=a<=b<=hi and f(op['widthMil'])<=f(body['width'])
        witnesses.append(dict(oldId=rid,oldBodySha256=bodysha,oldBody=body,
            oldAxisIntervalMil=[str(lo),str(hi)],newAxisIntervalMil=[str(a),str(b)],
            oldRadiusMil=str(f(body['width'])/2),newRadiusMil=str(f(op['widthMil'])/2),
            rationalAxisIntervalSubset=True,rationalRadiusSubset=True))
    for other in (o for o in ops if o['key']!=op['key']):
        rid=next(c for c in created if c['key']==other['key'])['id']
        assert ('LINE',rid) not in before and ('LINE',rid) in after
        body=after['LINE',rid]
        assert [body['startX'],body['startY']]==other['startXYMil'] and [body['endX'],body['endY']]==other['endXYMil']
        assert body['netName']==other['net'] and body['layerId']==other['layerId'] and body['width']==other['widthMil']
    added=set(after)-set(before)
    assert added=={('LINE',c['id']) for c in created if c['key']!=op['key']},'UNEXPECTED_ADDED_RECORD_OR_MISSING_NONREDUNDANT_CREATE'
    return dict(kind='root-approved-specific-exact-cross-width-capsule-covered-create-noop',
        approvedBy='Parent root explicitly approved only B1 covered-noop treatment in this corrective audit on 2026-10-18.',
        key=op['key'],requestedOperation=op,returnedNativeId=ghost,returnedIdAbsentBeforeAndAfter=True,
        witnesses=witnesses,exactAnalyticMinkowskiContainment=True,
        fullPlannedFourCapsulesUnionEqualsThreeActualCapsulesPlusBaseline=True,
        perWidthCenterlineSetEqualForSuppressedOperation=False,
        geometryToleranceMil=0,unqualifiedMissingCreatedIdAllowed=False)


def run(args):
    pp = M['scoped'](args.correction_plan, HERE)
    rp = M['scoped'](args.receipt, HERE)
    assert args.correction_plan_sha == APPROVED_CORRECTION_PLAN_SHA and M['sha'](pp) == APPROVED_CORRECTION_PLAN_SHA
    assert M['sha'](rp) == args.receipt_sha
    plan, receipt = M['load'](pp), M['load'](rp)
    assert plan['PCBRequired'] == '0ac2a19168000d8e' and len(plan['batches']) == 1
    batch = plan['batches'][0]
    ops = batch['operations']
    assert len(ops) == 4 and Counter(o['layerId'] for o in ops) == {1:2, 17:2}
    assert len({o['key'] for o in ops}) == 4
    for o in ops:
        assert o['action'] == 'line' and o['type'] == 'LINE' and o['net'] == 'GND'
        assert math.isfinite(o['widthMil']) and o['widthMil'] >= 6
        assert len(o['startXYMil']) == len(o['endXYMil']) == 2 and o['startXYMil'] != o['endXYMil']
        assert all(isinstance(v, (int,float)) and math.isfinite(v) and v == M['q'](v)
                   for xy in (o['startXYMil'],o['endXYMil']) for v in xy)
    base_path = M['scoped'](plan['sourcePath'], ROOT / 'output/validation')
    assert M['sha'](base_path) == plan['sourceSha256']
    assert plan['sourceSha256']=='74d29fb7f5d3579cbf12ef085f26059cad63b86aff5a3dcf8dff8a0cfaf92bfb'
    routes_path = M['scoped'](plan['routesPath'],HERE)
    assert M['sha'](routes_path)==plan['routesSha256']=='801e10de9ece1ae57c80c13e289277377e80d4576874acaa3d80ddb56a1c6da9'
    route=M['load'](routes_path)
    compiled=[dict(action='line',type='LINE',key=o['key'],net=o['net'],layerId=o['layerId'],
                   startXYMil=[round(v/.0254,4) for v in o['startXYmm']],
                   endXYMil=[round(v/.0254,4) for v in o['endXYmm']],widthMil=round(o['widthMm']/.0254,8))
              for o in route['newLineCreates']]
    assert compiled==ops,'FOUR_EXPLICIT_ROUTE_OPERATIONS_CHANGED'
    prefix = S['run'](SimpleNamespace(audited_report=args.main_audit, audited_report_sha=args.main_audit_sha,
        manifest=args.main_manifest, manifest_sha=args.main_manifest_sha, saved=str(base_path), saved_sha=plan['sourceSha256']))
    assert prefix['passed'], ('MAIN_TO_CORRECTION_BASE_BRIDGE_FAILED', prefix['errors'])
    assert prefix['lastAuditedStage'] == 'copper_wire13'
    main_manifest = M['load'](Path(prefix['manifestPath']))
    assert main_manifest['operationCounts']['line']==526 and main_manifest['operationCounts']['via']==64
    approval_path=HERE/'root-four-ground-seam-bridge-review.json'
    assert M['sha'](approval_path)==APPROVAL_SHA
    approval=M['load'](approval_path)
    assert approval['schema']=='root-four-specific-ground-seam-bridges-native-approval-v1'
    assert approval['approvedForBoundedNativeApplication'] is True
    assert approval['sourceSha256']==plan['sourceSha256'] and approval['mainCompleteCopperAuditSha256']==args.main_audit_sha
    assert approval['executionProposalSha256']==args.correction_plan_sha and approval['frozenRouteSha256']==plan['routesSha256']
    assert approval['wholePourRegenerationAuthorized'] is False and approval['stage']==batch['stage']
    for pathkey,hashkey in [('positiveNominalOverlapProof','positiveNominalOverlapProofSha256'),('prospectiveGraphProof','prospectiveGraphProofSha256')]:
        assert M['sha'](M['scoped'](approval[pathkey],HERE))==approval[hashkey]
    assert receipt['stage'] == batch['stage'] and receipt['manifestHash'] == args.correction_plan_sha
    assert M['scoped'](receipt['manifestRelative'], HERE) == pp
    assert M['scoped'](receipt['priorRelative'], ROOT / 'output/validation') == base_path
    assert receipt['priorHash'] == plan['sourceSha256'] and not receipt.get('failure')
    wanted = Counter(('line','LINE',o['key']) for o in ops)
    got = Counter((o['action'],o['type'],o.get('key')) for o in receipt['touched'])
    assert got == wanted, 'CORRECTION_TOUCHED_OPERATION_MISMATCH'
    assert Counter((o['type'],o['key']) for o in receipt['created']) == Counter(('LINE',o['key']) for o in ops)
    assert all(isinstance(o.get('id'),str) and o['id'] for o in receipt['created'])
    actual_path = M['scoped'](receipt['path'], ROOT / 'output/validation')
    assert M['sha'](actual_path) == receipt['sourceSha256']
    before, after = M['source'](base_path), M['source'](actual_path)
    covered_noop=covered_bridge_one(before,after,ops,receipt['created'])
    for guard in plan['requireBeforeGuards']:
        body=before[guard['kind'],guard['id']]
        assert body==guard['beforeBody'] and M['value_sha'](body)==guard['bodySha256'],('FROZEN_BEFORE_GUARD_CHANGED',guard['id'])
    errors, exact, changed = [], Counter(), []
    layers = {1,17}
    metadata = defaultdict(list)
    for (kind,rid),body in before.items():
        if kind == 'LINE' and body.get('netName') == 'GND' and body.get('layerId') in layers:
            metadata[body['layerId']].append({k:v for k,v in body.items() if k not in COORD})
    for key in before.keys() | after.keys():
        kind,rid = key
        a,b = before.get(key),after.get(key)
        if kind in VIEW:
            continue
        if a is not None and b is not None and S['canonical'](a) == S['canonical'](b):
            exact[kind] += 1
            continue
        target_old = kind == 'LINE' and a and a.get('netName') == 'GND' and a.get('layerId') in layers
        target_new = kind == 'LINE' and b and b.get('netName') == 'GND' and b.get('layerId') in layers
        if target_old:
            if b is not None:
                fields = S['field_changes'](a,b)
                if not set(fields) <= COORD:
                    errors.append(dict(code='OLD_GND_LINE_METADATA_CHANGED',id=rid,fields=fields))
            changed.append(dict(type=kind,id=rid,change='removed-for-possible-exact-merge' if b is None else 'geometry'))
        elif a is None and target_new:
            meta = {k:v for k,v in b.items() if k not in COORD}
            default = (b.get('partitionId')=='' and b.get('groupId')==0 and b.get('locked') is False
                       and b.get('zIndex',-1)==-1 and b.get('refs') in (None,[None])
                       and not set(b)-COORD-{'partitionId','groupId','locked','netName','layerId','width','zIndex','refs'})
            inherited = any(S['canonical'](meta)==S['canonical'](m) for m in metadata[b['layerId']])
            if not(default or inherited):
                errors.append(dict(code='NEW_GND_LINE_NONDEFAULT_METADATA',id=rid,metadata=meta))
            changed.append(dict(type=kind,id=rid,change='new-created-or-native-exact-merge'))
        else:
            errors.append(dict(code='UNAUTHORIZED_RECORD_CHANGE',type=kind,id=rid,
                               fields=S['field_changes'](a,b) if a is not None and b is not None else ['added' if a is None else 'removed']))
    # DOCHEAD is not blanket-ignored: the same saved-bridge session whitelist
    # applies. Every other nonview record was compared above without tolerance.
    heads = lambda r:{k:v for k,v in r.items() if k[0]=='DOCHEAD'}
    header_compare = S['compare_rows'](heads(before), heads(after))
    errors.extend(header_compare['errors'])
    counts_before,counts_after = Counter(k[0] for k in before),Counter(k[0] for k in after)
    for counts in (counts_before,counts_after):
        if counts['VIA']!=704 or counts['COMPONENT']!=437 or counts['RULE']!=18 or counts['PAD_NET']!=1523:
            errors.append(dict(code='PROTECTED_COUNT_MISMATCH',counts=dict(counts)))
    geometry = M['Audit']()
    # B1 is absent as an independent record, but its full physical capsule is
    # already in the exact unchanged baseline. Only this proven redundant op is
    # removed from per-width centerline comparison; all other geometry is exact.
    geometry.lines(before, after, [o for o in ops if o['key']!=covered_noop['key']])
    errors.extend(geometry.errors)
    assert all(not p['rootSpecificJunctionNormalizationApplied'] for p in geometry.report['lineGeometryProofs'])
    return dict(schema='labtool-four-ground-line-corrective-readback-v1',passed=not errors,errors=errors,
        nativeApiCalls=0,nativeDesignModified=False,manufacturingReady=False,
        mainAuditPath=prefix['finalCopperAuditPath'],mainAuditSha256=prefix['finalCopperAuditSha256'],
        mainManifestPath=prefix['manifestPath'],mainManifestSha256=prefix['manifestSha256'],
        mainAuditedCapturePath=prefix['lastAuditedCapturePath'],mainAuditedCaptureSha256=prefix['lastAuditedCaptureSha256'],
        correctionPlanPath=str(pp),correctionPlanSha256=M['sha'](pp),correctionStage=batch['stage'],
        rootApprovalPath=str(approval_path),rootApprovalSha256=APPROVAL_SHA,
        correctionReceiptPath=str(rp),correctionReceiptSha256=M['sha'](rp),
        correctionBasePath=str(base_path),correctionBaseSha256=M['sha'](base_path),
        correctionActualPath=str(actual_path),correctionActualSha256=M['sha'](actual_path),
        createdKeyToNativeId=receipt['created'],plannedOperations=ops,
        coveredCreateNoopProof=covered_noop,actualIndependentNewLineRecords=3,
        exactUnchangedBodyCounts=dict(exact),allowedGeometryRecordChanges=changed,
        originalCounts=dict(counts_before),actualCounts=dict(counts_after),
        lineGeometryProofs=geometry.report['lineGeometryProofs'],qualifiedWidthSerializations=geometry.normalizations,
        correctionBaseBridge=prefix,docheadChanges=header_compare['docheadChanges'],
        mainLineCreates=526,separateCorrectiveLineCreates=4,combinedPlannedLineCreates=530,newViasInAddendum=0,
        geometryToleranceMil=0,scopeQualification='Separate four-GND-LINE requested addendum; three native LINE records and the one explicit B1 analytic capsule-covered no-op. Main manifest still contains only 526 LINE and 64 VIA creates. All original VIA/FILL/parts/pin-net/rule/layer/mechanical bodies exact; only exact-rational same-width GND LINE splits/merges on TOP/Inner17 may occur. No junction normalization is used for this correction. DRC, final topology, save/durable/CAM checks remain separate.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['main-audit','main-audit-sha','main-manifest','main-manifest-sha','correction-plan','correction-plan-sha','receipt','receipt-sha']:
        ap.add_argument('--'+name,required=True)
    args=ap.parse_args()
    try: report=run(args)
    except Exception as e:
        report=dict(schema='labtool-four-ground-line-corrective-readback-v1',passed=False,
                    errors=[dict(code='FAIL_CLOSED_EXCEPTION',message=str(e),traceback=traceback.format_exc())],
                    nativeApiCalls=0,nativeDesignModified=False,manufacturingReady=False)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out=HERE/'audits'/f'four-ground-correction-readback-{stamp}-{uuid.uuid4().hex[:8]}.json'
    report.update(auditedUtc=datetime.now(timezone.utc).isoformat(),correctionAuditorPath=str(Path(__file__).resolve()),
                  correctionAuditorSha256=M['sha'](Path(__file__)))
    with out.open('x',encoding='utf8') as handle:
        json.dump(report,handle,indent=2,ensure_ascii=False);handle.write('\n')
    print(json.dumps(dict(passed=report['passed'],report=str(out),sha256=M['sha'](out),errors=report['errors'][:5]),ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
