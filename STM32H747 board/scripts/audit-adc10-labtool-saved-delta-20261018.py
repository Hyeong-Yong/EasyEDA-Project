"""Bridge a final independently audited copper capture to a saved capture.

Read-only, standard-library only. No native API, project writes, geometry
normalization, tolerance, or cached proof is used. Outputs are new audit files.
"""
import argparse
import hashlib
import json
import traceback
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
VALIDATION = ROOT / 'output/validation'
PCB = '0ac2a19168000d8e'
VIEW = {'CANVAS', 'ACTIVE_LAYER', 'ELE_PLACEHOLDER'}
DOCHEAD_SESSION = {'client', 'version', 'updateTime'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def scoped(value, folder):
    p = Path(value)
    if not p.is_absolute():
        p = ROOT / p if str(p).replace('\\', '/').startswith('output/') else folder / p
    p = p.resolve()
    assert p.is_relative_to(folder.resolve()), ('OUTSIDE_SCOPE', str(p))
    return p


def source(path):
    rows = {}
    for no, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        if '||' not in line:
            continue
        h, body = line.split('||', 1)
        h = json.loads(h)
        key = h['type'], h.get('id')
        assert key not in rows, ('DUPLICATE_NATIVE_KEY', no, key)
        body = json.loads(body.removesuffix('|'))
        assert isinstance(body, dict), ('NONMATERIALIZED_BODY', no, key)
        rows[key] = body
    heads = [b for (kind, _), b in rows.items() if kind == 'DOCHEAD']
    assert len(heads) == 1 and heads[0].get('uuid') == PCB and heads[0].get('docType') == 'PCB'
    return rows


def field_changes(before, after):
    absent = {'__AUDIT_MISSING_FIELD__': True}
    return [k for k in sorted(before.keys() | after.keys())
            if canonical(before.get(k, absent)) != canonical(after.get(k, absent))]


def compare_rows(before, after):
    errors, headers = [], []
    exact = Counter()
    ignored = []
    for key in sorted(before.keys() | after.keys(), key=str):
        kind, rid = key
        a, b = before.get(key), after.get(key)
        if kind in VIEW:
            if a != b:
                ignored.append(dict(type=kind, id=rid, change='added' if a is None else 'removed' if b is None else 'body'))
            continue
        if a is None or b is None:
            errors.append(dict(code='NONVIEW_RECORD_SET_CHANGED', type=kind, id=rid,
                               change='added' if a is None else 'removed'))
            continue
        if kind == 'DOCHEAD':
            changed = field_changes(a, b)
            allowed = set(changed) <= DOCHEAD_SESSION
            headers.append(dict(type=kind, id=rid, changedFields=changed, allowed=allowed,
                                before={k: a.get(k) for k in changed}, after={k: b.get(k) for k in changed}))
            if not allowed:
                errors.append(dict(code='DOCHEAD_NONSESSION_FIELD_CHANGED', fields=changed))
        elif canonical(a) != canonical(b):
            errors.append(dict(code='NONVIEW_BODY_CHANGED', type=kind, id=rid,
                               fields=field_changes(a, b),
                               beforeBodySha256=hashlib.sha256(canonical(a).encode()).hexdigest(),
                               afterBodySha256=hashlib.sha256(canonical(b).encode()).hexdigest()))
        else:
            exact[kind] += 1
    return dict(errors=errors, exactNonViewBodyCounts=dict(exact), docheadChanges=headers,
                ignoredViewChanges=ignored, ignoredViewTypes=sorted(VIEW),
                originalCounts=dict(Counter(k[0] for k in before)), savedCounts=dict(Counter(k[0] for k in after)))


def run(args):
    apath = scoped(args.audited_report, HERE / 'audits')
    mpath = scoped(args.manifest, HERE)
    saved = scoped(args.saved, VALIDATION)
    assert sha(apath) == args.audited_report_sha, 'FINAL_AUDIT_REPORT_HASH_MISMATCH'
    assert sha(mpath) == args.manifest_sha, 'FINAL_EXECUTION_MANIFEST_HASH_MISMATCH'
    assert sha(saved) == args.saved_sha, 'SAVED_CAPTURE_HASH_MISMATCH'
    audit, manifest = load(apath), load(mpath)
    assert audit['schema'] == 'stm32h747-independent-copper-readback-v1'
    assert audit['passed'] is True and not audit['errors'], 'FINAL_COPPER_AUDIT_NOT_PASSED'
    assert manifest['schema'] == 'stm32h747-labtool-reviewed-copper-bounded-execution-v1'
    assert manifest['PCBRequired'] == PCB
    assert audit['stage'] == manifest['batches'][-1]['stage'], 'NOT_FINAL_CUMULATIVE_STAGE'
    assert audit['manifestSha256'] == args.manifest_sha and scoped(audit['manifestPath'], HERE) == mpath
    assert audit['baselineSha256'] == manifest['sourceSha256']
    assert audit['completedOperationCounts'] == manifest['operationCounts'], 'FINAL_AUDIT_OPERATION_COVERAGE_MISMATCH'
    auditor = scoped(audit['auditorPath'], ROOT / 'scripts')
    assert sha(auditor) == audit['auditorSha256'], 'FINAL_COPPER_AUDITOR_CODE_HASH_MISMATCH'
    junction = audit.get('specificJunctionReview')
    junctions = audit.get('specificJunctionReviews') or ([junction] if junction else [])
    assert len(junctions) <= 2 and len({j['sha256'] for j in junctions}) == len(junctions)
    for junction in junctions:
        assert junction['sha256'] in {'90aab429165937b7b16143fc041defbb12ffe92b176bdb65ffd184dd806d6918',
                                     'f3425d761d6434e76fa992c5dd500e7e3b79f97759bcb2c87d0868d81bc90f00'}
        assert junction['nativeGeometryChangeAuthorized'] is False and junction['globalToleranceAuthorized'] is False
        assert junction['originalPhysicalExactEqualityClaimed'] is False
        for path_key, hash_key in [('path', 'sha256'), ('diagnosticPath', 'diagnosticSha256'),
                                   ('failedOriginalAuditPath', 'failedOriginalAuditSha256')]:
            assert sha(scoped(junction[path_key], HERE)) == junction[hash_key], ('JUNCTION_EVIDENCE_CHANGED', path_key)
    for path_key, hash_key in [('routesPath', 'routesSha256'), ('fillsPath', 'fillsSha256'),
                               ('rootReviewPath', 'rootReviewSha256')]:
        assert sha(scoped(manifest[path_key], HERE)) == manifest[hash_key], ('REVIEWED_INPUT_CHANGED', path_key)
    baseline = scoped(manifest['sourcePath'], VALIDATION)
    assert sha(baseline) == manifest['sourceSha256']
    evidence = audit['receiptEvidence']
    assert len(evidence) == len(manifest['batches']), 'FINAL_RECEIPT_CHAIN_INCOMPLETE'
    previous, previous_sha = baseline, sha(baseline)
    receipt_chain = []
    for stage, item in zip(manifest['batches'], evidence):
        assert item['stage'] == stage['stage'], 'RECEIPT_STAGE_ORDER_CHANGED'
        rp = scoped(item['receiptPath'], HERE)
        assert sha(rp) == item['receiptSha256'], 'AUDITED_RECEIPT_CHANGED'
        r = load(rp)
        assert r['stage'] == stage['stage'] and r['manifestHash'] == args.manifest_sha
        assert scoped(r['manifestRelative'], HERE) == mpath
        assert scoped(r['priorRelative'], VALIDATION) == previous and r['priorHash'] == previous_sha
        assert not r.get('failure'), 'AUDITED_RECEIPT_HAS_FAILURE'
        capture = scoped(item['capturePath'], VALIDATION)
        assert scoped(r['path'], VALIDATION) == capture
        assert sha(capture) == item['captureSha256'] == r['sourceSha256'], 'AUDITED_CAPTURE_CHANGED'
        receipt_chain.append(dict(stage=r['stage'], receiptPath=str(rp), receiptSha256=sha(rp),
                                  capturePath=str(capture), captureSha256=sha(capture)))
        previous, previous_sha = capture, sha(capture)
    assert scoped(audit['actualPath'], VALIDATION) == previous and audit['actualSha256'] == previous_sha
    last_main_path, last_main_sha = previous, previous_sha
    correction = None
    correction_path = getattr(args, 'correction_audit', None)
    correction_sha = getattr(args, 'correction_audit_sha', None)
    assert bool(correction_path) == bool(correction_sha), 'CORRECTION_AUDIT_PATH_AND_HASH_BOTH_REQUIRED'
    if correction_path:
        capath = scoped(correction_path, HERE / 'audits')
        assert sha(capath) == correction_sha, 'CORRECTION_AUDIT_HASH_MISMATCH'
        correction = load(capath)
        assert correction['schema'] == 'labtool-four-ground-line-corrective-readback-v1'
        assert correction['passed'] is True and not correction['errors']
        assert correction['mainAuditSha256'] == args.audited_report_sha
        assert correction['mainManifestSha256'] == args.manifest_sha
        assert scoped(correction['mainAuditedCapturePath'], VALIDATION) == previous
        assert correction['mainAuditedCaptureSha256'] == previous_sha
        assert correction['geometryToleranceMil'] == 0
        assert correction['mainLineCreates'] == 526 and correction['separateCorrectiveLineCreates'] == 4
        assert correction['newViasInAddendum'] == 0
        assert correction['correctionBaseBridge']['passed'] is True
        for path_key, hash_key, folder in [
            ('correctionPlanPath','correctionPlanSha256',HERE),
            ('correctionReceiptPath','correctionReceiptSha256',HERE),
            ('correctionBasePath','correctionBaseSha256',VALIDATION),
            ('correctionActualPath','correctionActualSha256',VALIDATION),
            ('correctionAuditorPath','correctionAuditorSha256',ROOT / 'scripts')]:
            assert sha(scoped(correction[path_key], folder)) == correction[hash_key], ('CORRECTION_EVIDENCE_CHANGED',path_key)
        previous = scoped(correction['correctionActualPath'], VALIDATION)
        previous_sha = correction['correctionActualSha256']
        correction = dict(auditPath=str(capath),auditSha256=sha(capath),
                          mainManifestLineCreates=526,separateAddendumLineCreates=4,
                          correctionStage=correction['correctionStage'],
                          correctionActualPath=str(previous),correctionActualSha256=previous_sha,
                          mainManifestNotExpanded=True)
    comparison = compare_rows(source(previous), source(saved))
    counts = comparison['savedCounts']
    if counts.get('COMPONENT') != 437 or counts.get('RULE') != 18 or counts.get('VIA') != 640 + manifest['operationCounts']['via']:
        comparison['errors'].append(dict(code='FINAL_PHYSICAL_COUNT_MISMATCH', counts=counts))
    return dict(schema='labtool-final-audited-to-saved-pcb-body-bridge-v1',
                passed=not comparison['errors'], **comparison,
                finalCopperAuditPath=str(apath), finalCopperAuditSha256=sha(apath),
                finalCopperAuditorPath=str(auditor), finalCopperAuditorSha256=sha(auditor),
                manifestPath=str(mpath), manifestSha256=sha(mpath),
                lastMainAuditedStage=audit['stage'], lastMainAuditedCapturePath=str(last_main_path), lastMainAuditedCaptureSha256=last_main_sha,
                lastAuditedStage=correction['correctionStage'] if correction else audit['stage'],
                lastAuditedCapturePath=str(previous), lastAuditedCaptureSha256=previous_sha,
                savedCapturePath=str(saved), savedCaptureSha256=sha(saved),
                fullAuditedReceiptChain=receipt_chain,
                inheritedSpecificSerializationQualifications=junctions,
                separateFourLineCorrectiveAudit=correction,
                geometryNormalizationAllowed=False, coordinateToleranceMil=0,
                nativeApiCalls=0, nativeDesignModified=False, manufacturingReady=False,
                scopeQualification='Exact canonical JSON body bridge only. No copper geometry, VIA, LINE, FILL, component, rule, netlist or metadata changes are accepted. Only CANVAS/ACTIVE_LAYER/ELE_PLACEHOLDER view records and DOCHEAD client/version/updateTime may differ. Strict DRC/checkpoint/CAM/analog verification remains separate.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audited-report', required=True)
    ap.add_argument('--audited-report-sha', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--manifest-sha', required=True)
    ap.add_argument('--saved', required=True)
    ap.add_argument('--saved-sha', required=True)
    ap.add_argument('--correction-audit', help='Optional separately passed four-GND-LINE corrective audit; does not expand main manifest')
    ap.add_argument('--correction-audit-sha')
    args = ap.parse_args()
    try:
        report = run(args)
    except Exception as e:
        report = dict(schema='labtool-final-audited-to-saved-pcb-body-bridge-v1', passed=False,
                      errors=[dict(code='FAIL_CLOSED_EXCEPTION', message=str(e), traceback=traceback.format_exc())],
                      nativeApiCalls=0, nativeDesignModified=False, manufacturingReady=False)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = HERE / 'audits' / f'final-saved-delta-{stamp}-{uuid.uuid4().hex[:8]}.json'
    out.parent.mkdir(exist_ok=True)
    report.update(auditedUtc=datetime.now(timezone.utc).isoformat(),
                  bridgeAuditorPath=str(Path(__file__).resolve()), bridgeAuditorSha256=sha(Path(__file__)))
    with out.open('x', encoding='utf8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
    print(json.dumps(dict(passed=report['passed'], report=str(out), sha256=sha(out),
                          errors=report['errors'][:5]), ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
