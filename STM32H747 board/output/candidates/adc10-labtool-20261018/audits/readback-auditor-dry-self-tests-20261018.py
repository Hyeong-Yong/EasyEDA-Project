"""Dry positive/negative tests, native/API calls zero; unique report only."""
import ast
import copy
import json
import runpy
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROOT = HERE.parents[2]
FILE = ROOT / 'scripts/audit-adc10-labtool-copper-readback-20261018.py'
M = runpy.run_path(str(FILE))


def main():
    ast.parse(FILE.read_text(encoding='utf8'))
    source = ROOT / 'output/validation/native-adc10-pcb-labtool_107_placed_v6_saved-20261018.epru'
    assert M['sha'](source) == 'a5d126649aa3e03dd0b74baa5e412d03c2a6ae93466b0fc4e04010f37232e9f9'
    rows = M['source'](source)
    results = []
    def test(name, condition):
        results.append(dict(name=name, passed=bool(condition)))
    audit = M['Audit']()
    audit.records(rows, rows, [], {})
    audit.lines(rows, rows, [])
    test('All_actual_V6_protected_bodies_exact_no_tolerance', not audit.errors)
    segment = M['canonical_segments']
    test('Exact_diagonal_split_merge_reversal_and_duplicates',
         segment([(0, 0, 2, 2)]) == segment([(2, 2, 1, 1), (0, 0, 1, 1), (0, 0, 1, 1)]))
    test('Off_line_endpoint_0p0001mil_rejected', segment([(0, 0, 2, 2)]) != segment([(0, 0, 2, 2.0001)]))
    test('Additional_branch_not_lost_by_union', segment([(0, 0, 2, 2)]) != segment([(0, 0, 2, 2), (1, 1, 1, 2)]))
    test('Inner15_float_expression_same_approved_q4mil_pair',
         M['approved_inner15_pair']([13.8, 35.5], [12.200000000000001, 36.900000000000006]))
    test('Inner15_obviously_nonapproved_segment_rejected',
         not M['approved_inner15_pair']([13.8, 35.5], [12.3, 36.9]))
    test('Inner15_same_q4mil_but_raw_change_over_1e12mm_rejected',
         not M['approved_inner15_pair']([13.8, 35.5], [12.2 + 1e-11, 36.9]))
    outer = [0, 0, 'L', 20, 0, 20, 20, 0, 20, 0, 0]
    hole = [5, 5, 'L', 6, 5, 6, 6, 5, 6, 5, 5]
    hole2 = [10, 10, 'L', 11, 10, 11, 11, 10, 11, 10, 10]
    duplicate_collinear = [20, 20, 'L', 20, 0, 10, 0, 0, 0, 0, 0, 0, 20, 20, 20]
    a = M['Audit']()
    test('Fill_cyclic_closure_duplicate_collinear_and_hole_order_exact',
         a.fill_geometry('DRY', [outer, hole, hole2], [duplicate_collinear, hole2, hole]) and not a.errors)
    arbitrary = [0, 0, 'L', 20, 0, 20, 20.0001, 0, 20, 0, 0]
    a = M['Audit']()
    test('Fill_unplanned_vertex_0p0001mil_rejected', not a.fill_geometry('DRY_BAD', [outer], [arbitrary]))
    requested = [[.12345678, 0, 'L', 10, 0, 10, 10, 0, 10, .12345678, 0]]
    a = M['Audit']()
    test('Only_explicit_native_4dp_serialization_qualified',
         a.fill_geometry('DRY_GRID', requested, M['quantized_path'](requested)) and not a.errors)
    op = dict(net='GND', xyMil=[100, 200], diameterMil=.45 / .0254, drillMil=.2 / .0254)
    via = dict(partitionId='', groupId=0, locked=False, netName='GND', ruleName='', centerX=100, centerY=200,
               holeDiameter=M['q'](op['drillMil']), viaDiameter=M['q'](op['diameterMil']), viaType='NORMAL',
               topSolderExpansion=None, bottomSolderExpansion=None, unusedInnerLayers=[])
    a = M['Audit'](); a.new_via(op, via, 'DRY')
    test('New_045_020_all6_via_serialization_accepted', not a.errors)
    a = M['Audit'](); a.new_via(op, dict(via, unusedInnerLayers=[15]), 'DRY_BAD')
    test('New_via_inner_copper_omission_rejected', bool(a.errors))
    for typ in ('COMPONENT', 'VIA', 'RULE', 'PAD_NET'):
        key = next(k for k in rows if k[0] == typ)
        changed = dict(rows)
        changed[key] = dict(rows[key])
        if typ == 'COMPONENT': changed[key]['x'] += .0001
        elif typ == 'VIA': changed[key]['centerX'] += .0001
        else: changed[key]['__unapproved_dry_field'] = True
        a = M['Audit'](); a.records(rows, changed, [], {})
        test('Protected_' + typ + '_mutation_rejected', any(e['code'] == 'PROTECTED_BODY_CHANGED' for e in a.errors))
    review_path = HERE / 'root-wire10-junction-serialization-review.json'
    if review_path.exists():
        assert M['sha'](review_path) == M['JUNCTION_REVIEW_SHA']
        review = M['load'](review_path)
        diagnostic = M['load'](HERE / review['diagnosticPath'])
        manifest = M['load'](HERE / 'pcb-final-copper-v5-execution.json')
        op = next(o for b in manifest['batches'] for o in b['operations'] if o.get('key') == review['plannedKey'])
        actual = M['source'](Path(diagnostic['actualSourcePath']))
        def proof(op_arg=None, actual_arg=None, horizontal_arg=None):
            return M['focused_junction_proof'](op if op_arg is None else op_arg,
                diagnostic['oldWideHorizontalBody'] if horizontal_arg is None else horizontal_arg,
                diagnostic['oldWideVerticalBody'], actual if actual_arg is None else actual_arg,
                review, diagnostic['actualNewBodies'])
        test('Focused_junction_exact_reference_case_accepted', proof()['normalizedNativeGeometryExact'])
        def rejects(call):
            try: call()
            except AssertionError: return True
            return False
        rid = review['actualSplitIds'][0]
        for sign in (-1, 1):
            modified = dict(actual); modified['LINE', rid] = dict(actual['LINE', rid])
            modified['LINE', rid]['endX'] += sign * .0001
            test('Focused_B_' + ('minus' if sign < 0 else 'plus') + '_one_native_grid_rejected',
                 rejects(lambda m=modified: proof(actual_arg=m)))
        for field, value in [('startX', 1157.4804), ('width', 8.0001), ('netName', 'GND'), ('layerId', 2)]:
            modified = dict(actual); modified['LINE', rid] = dict(actual['LINE', rid], **{field: value})
            test('Focused_actual_' + field + '_change_rejected', rejects(lambda m=modified: proof(actual_arg=m)))
        moved = copy.deepcopy(op); moved['endXYMil'][0] += .0001
        test('Focused_planned_C_shift_rejected', rejects(lambda: proof(op_arg=moved)))
        changed_horizontal = dict(diagnostic['oldWideHorizontalBody'])
        changed_horizontal['startY'] += .0001
        test('Focused_original_crossing_segment_changed_rejected',
             rejects(lambda: proof(horizontal_arg=changed_horizontal)))
        changed_horizontal = dict(diagnostic['oldWideHorizontalBody'])
        changed_horizontal['width'] += .0001
        test('Focused_original_wide_width_changed_rejected',
             rejects(lambda: proof(horizontal_arg=changed_horizontal)))
    pair_path = HERE / 'root-wire12-junction-serialization-review.json'
    if pair_path.exists():
        assert M['sha'](pair_path) == M['PAIR_JUNCTION_REVIEW_SHA']
        pair = M['load'](pair_path)
        diag = M['load'](HERE / pair['diagnosticPath'])
        manifest = M['load'](HERE / 'pcb-final-copper-v5-execution.json')
        pair_ops = [next(o for b in manifest['batches'] for o in b['operations'] if o.get('key') == s['plannedKey']) for s in pair['segments']]
        pa = M['source'](Path(diag['actualSourcePath']))
        def pair_proof(ops_arg=None, actual_arg=None, prior_arg=None):
            return M['focused_paired_junction_proof'](pair_ops if ops_arg is None else ops_arg,
                diag['oldPriorCrossingBody'] if prior_arg is None else prior_arg,
                pa if actual_arg is None else actual_arg, pair)
        test('Pair_exact_two_diagonals_shared_q4junction_accepted', pair_proof()['normalizedNativeGeometryExact'])
        for i, segment in enumerate(pair['segments']):
            rid = segment['actualSplitIds'][0]
            for sign in (-1, 1):
                bad = dict(pa);bad['LINE', rid] = dict(pa['LINE', rid]);bad['LINE', rid]['endY'] += sign * .0001
                test(f'Pair_segment{i}_B_one_grid_{sign}_rejected', rejects(lambda b=bad: pair_proof(actual_arg=b)))
            for field, value in [('width', segment['widthMilSerialized']+.0001), ('netName','GND'), ('layerId',2)]:
                bad = dict(pa);bad['LINE', rid] = dict(pa['LINE', rid], **{field:value})
                test(f'Pair_segment{i}_{field}_change_rejected', rejects(lambda b=bad: pair_proof(actual_arg=b)))
            changed_ops = copy.deepcopy(pair_ops);changed_ops[i]['startXYMil'][0] += .0001
            test(f'Pair_segment{i}_planned_endpoint_shift_rejected', rejects(lambda o=changed_ops: pair_proof(ops_arg=o)))
        prior_bad = dict(diag['oldPriorCrossingBody']);prior_bad['endY'] += .0001
        test('Pair_prior_crossing_body_changed_rejected', rejects(lambda: pair_proof(prior_arg=prior_bad)))
    report = dict(schema='readback-auditor-dry-self-tests-v1', passed=all(r['passed'] for r in results),
                  nativeCalls=0, nativeModified=False, auditorPath=str(FILE), auditorSha256=M['sha'](FILE),
                  actualV6SourcePath=str(source), actualV6SourceSha256=M['sha'](source),
                  tests=results, testCount=len(results), realCopperReadbackAudited=False,
                  limits='Synthetic acceptance/rejection tests plus identity of all frozen actual V6 source bodies; not approval of native copper implementation.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = HERE / 'audits' / f'readback-dry-tests-{stamp}-{uuid.uuid4().hex[:8]}.json'
    with out.open('x', encoding='utf8') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print(json.dumps(dict(passed=report['passed'], report=str(out), sha256=M['sha'](out), tests=len(results))))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
