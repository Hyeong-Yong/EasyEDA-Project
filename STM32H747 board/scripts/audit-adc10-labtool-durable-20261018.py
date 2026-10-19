"""Read-only saved-checkpoint durability and whole-project scope audit.

Materializes highest-ticket native tombstones; does not reopen or rewrite the
project. Runtime-only no-op selectors are listed individually, never treated
as permission to change a selected design rule.
"""
import argparse
import hashlib
import json
import re
import runpy
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
H = runpy.run_path(str(ROOT / 'output/candidates/adc-inline-wiring/audit-inline-final-project.py'))
U = H['UTIL']
PCB = ('PCB', '0ac2a19168000d8e')
BASE = ROOT / 'output/checkpoints/STM32H747_labtool_pcb_eco_wip_20261018.epro2'
EMPTY = dict(ruleOrder=4, ruleKeyValue={}, copperValue={}, innerPlaneValue={})


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def scoped_path(value, suffix):
    p = (ROOT / value).resolve()
    assert p.is_relative_to((ROOT / 'output').resolve()) and p.suffix == suffix
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--checkpoint', required=True)
    ap.add_argument('--source', required=True)
    ap.add_argument('--stage', required=True)
    args = ap.parse_args()
    assert re.fullmatch(r'[a-z0-9_]{3,60}', args.stage)
    cp = scoped_path(args.checkpoint, '.epro2')
    source = scoped_path(args.source, '.epru')
    before, bt = H['read_snapshot'](BASE)
    after, at = H['read_snapshot'](cp)
    body = U['bodies']
    errors = []
    if before.keys() != after.keys():
        errors.append(dict(documentSetChanged=True))
    changed = sorted(k for k in before.keys() & after.keys() if body(before[k]) != body(after[k]))
    if changed != [PCB]:
        errors.append(dict(changedDocumentsNotExactlyPcb=changed))
    headers = []
    for doc in before.keys() & after.keys():
        a = next(b for (kind, _), (_, b) in before[doc].items() if kind == 'DOCHEAD')
        b = next(b for (kind, _), (_, b) in after[doc].items() if kind == 'DOCHEAD')
        fields = [f for f in a.keys() | b.keys() if a.get(f) != b.get(f)]
        if fields:
            allowed = set(fields) <= {'client', 'version', 'updateTime'}
            headers.append(dict(document=doc, fields=fields, allowed=allowed))
            if not allowed:
                errors.append(dict(unclassifiedDocheadChange=doc, fields=fields))
    match = U['source_matches_snapshot'](source, after[PCB])
    native, stored = U['native_source'](source), body(after[PCB])
    derived, unclassified = [], []
    for discrepancy in match['errors']:
        k = tuple(discrepancy.get('sourceOnly', []))
        valid = False
        if len(k) == 2 and k[0] == 'RULE_SELECTOR' and native.get(k) == EMPTY:
            selector = json.loads(k[1])
            if selector[0] == 'RULE_SELECTOR' and selector[1][0] == 'NET':
                net = selector[1][1]
                if re.fullmatch(r'(?:ADC_J(?:[2-9]|10|11)_.+|ADC_OFFSET_0V97|AFE_.+|[+-][35]V_AFE)', net):
                    valid = any(t == 'NET' and json.loads(rid) == ['NET', net] for t, rid in stored)
                    if valid:
                        derived.append(dict(record=k, net=net, exactRuntimeBody=EMPTY,
                                            rule='Runtime-only no-op inheritance; selected global RULE bodies must remain exact'))
        if not valid:
            unclassified.append(discrepancy)
    match['errors'] = unclassified
    match['normalizations'].extend(derived)
    match['passed'] = not unclassified
    match['normalizationRuleCounts'] = dict(Counter(n['rule'] for n in match['normalizations']))
    if unclassified:
        errors.append(dict(nativeSourceVsStoredCheckpoint=unclassified))
    old = body(before[PCB])
    protected = {}
    for typ in ('RULE', 'RULE_TEMPLATE', 'LAYER', 'LAYER_PHYS', 'PAD', 'PAD_NET', 'ARC', 'POLY', 'STRING'):
        a = {k: v for k, v in old.items() if k[0] == typ}
        b = {k: v for k, v in stored.items() if k[0] == typ}
        protected[typ] = dict(count=len(b), bodyExact=a == b)
        if a != b:
            errors.append(dict(protectedPrimitiveChanged=typ))
    if protected['RULE']['count'] != 18 or protected['PAD_NET']['count'] != 1523:
        errors.append('Unexpected selected RULE/PAD_NET counts')
    comp = {k: v for k, v in stored.items() if k[0] == 'COMPONENT'}
    if len(comp) != 437:
        errors.append('Expected 437 physical components')
    footprint_links = [(rid, v['value']) for (typ, rid), v in stored.items() if typ == 'ATTR' and v.get('key') == 'Footprint']
    missing_footprints = [(rid, uid) for rid, uid in footprint_links if ('FOOTPRINT', uid) not in after]
    if len(footprint_links) != 437 or missing_footprints:
        errors.append(dict(footprintLinks=len(footprint_links), missing=missing_footprints))
    with zipfile.ZipFile(BASE) as a, zipfile.ZipFile(cp) as b:
        metadata_exact = json.loads(a.read('project2.json')) == json.loads(b.read('project2.json'))
    if not metadata_exact:
        errors.append('project2.json changed')
    report = dict(schema='labtool-adc10-saved-native-durability-scope-audit-v1', passed=not errors,
                  baselineCheckpoint=dict(path=str(BASE), sha256=sha(BASE)),
                  checkpoint=dict(path=str(cp), sha256=sha(cp)),
                  nativeSource=dict(path=str(source), sha256=sha(source)),
                  documentCount=len(after), changedDesignDocuments=changed,
                  nonTargetDocumentBodiesExact=len(before) - 1,
                  sessionHeaderChanges=headers, projectMetadataExact=metadata_exact,
                  storedPcbMatchesNativeReadback=match, protected=protected,
                  physicalParts=len(comp), footprintLinks=len(footprint_links),
                  missingFootprints=missing_footprints,
                  historicalTombstoneCounts=dict(before=len(bt['historicalEmptyBodyTombstones']),
                                                 after=len(at['historicalEmptyBodyTombstones'])),
                  errors=errors, nativeCalls=0, manufacturingReady=False)
    out = HERE / f'independent-durable-{args.stage}-audit.json'
    assert not out.exists(), 'Append new review stage; do not overwrite prior evidence'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=not errors, report=str(out), sha256=sha(out),
                          docs=len(after), changed=changed, errors=errors[:5])))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
