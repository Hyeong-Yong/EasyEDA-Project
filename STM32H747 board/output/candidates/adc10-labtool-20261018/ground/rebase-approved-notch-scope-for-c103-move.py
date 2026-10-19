"""Rebase exact reviewed FILL scope after only the authorized C103 pose move."""
import argparse
import json
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
P = runpy.run_path(str(HERE / 'plan-local-static-fill-clearance.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output-prefix', required=True)
    args = ap.parse_args()
    assert Path(args.output_prefix).name == args.output_prefix
    old_scope = HERE / 'approved-bottom-five-actor-notch-scope-v5b.json'
    scope = json.loads(old_scope.read_text(encoding='utf8'))
    old_path = P['ROOT'] / 'output/validation/native-adc10-pcb-labtool_107_placed_v5b_saved-20261018.epru'
    assert P['sha'](old_path) == '568ca754e9ff92d9df6cf5f96e3384811f9ad6038404410ce7ca4c843d80296b'
    before, after = P['G']['PARSE'](old_path), P['G']['PARSE'](args.source)
    attrs = {b['parentId']: b['value'] for (kind, rid), b in before.items() if kind == 'ATTR' and b.get('key') == 'Designator'}
    cid = next(cid for cid, ref in attrs.items() if ref == 'C103')
    errors, differences = [], []
    for key in set(before) | set(after):
        if key[0] in {'DOCHEAD', 'CANVAS'}:
            continue
        a, b = before.get(key), after.get(key)
        if a == b:
            continue
        if a is None or b is None:
            errors.append({'key': key, 'reason': 'Unexpected native design record addition/deletion'})
            continue
        fields = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
        allowed = key == ('COMPONENT', cid) or (key[0] == 'ATTR' and a.get('parentId') == cid and b.get('parentId') == cid)
        fields_ok = set(fields) <= ({'x', 'y', 'angle', 'layerId'} if key[0] == 'COMPONENT' else {'x', 'y', 'angle'})
        if not allowed or not fields_ok:
            errors.append({'key': key, 'fields': fields, 'reason': 'Outside authorized C103 rigid pose/display-only move'})
        differences.append({'type': key[0], 'id': key[1], 'fields': fields})
    for rid, entry in scope.items():
        assert P['digest'](before['FILL', rid]) == entry['beforeBodySha256']
        assert before['FILL', rid] == after['FILL', rid]
        entry['rebaseAudit'] = {'oldScopeSha256': P['sha'](old_scope), 'oldSourceSha256': P['sha'](old_path),
                              'authorizedSourcePoseChange': 'C103 only; reviewed FILL body and exact actor masks unchanged'}
        entry['sourceSha256Required'] = P['sha'](args.source)
    report = {'schema': 'exact-notch-scope-c103-source-rebase-v1', 'passed': not errors,
              'source': str(args.source.resolve()), 'sourceSha256': P['sha'](args.source),
              'oldSourceSha256': P['sha'](old_path), 'oldScopeSha256': P['sha'](old_scope),
              'differences': differences, 'errors': errors, 'nativeCalls': 0, 'nativeModified': False,
              'scopeGeometryChanged': False, 'actorMaskApprovalBroadened': False}
    report_path = HERE / (args.output_prefix + '-audit.json')
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    if errors:
        raise ValueError('C103-only source rebase failed: ' + json.dumps(errors))
    output = HERE / (args.output_prefix + '.json')
    output.write_text(json.dumps(scope, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': True, 'scope': str(output), 'sha256': P['sha'](output),
                      'audit': str(report_path), 'auditSha256': P['sha'](report_path), 'differences': differences}))


if __name__ == '__main__':
    main()
