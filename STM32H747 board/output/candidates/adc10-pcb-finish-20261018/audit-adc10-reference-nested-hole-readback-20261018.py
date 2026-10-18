"""Fail-closed proof of one reviewed redundant keepout-contour removal only."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import explain_validity

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
M = runpy.run_path(str(HERE / 'audit-adc10-strip-dc-graph-ground-20261018.py'))
PARSE, BM = M['M']['parse'], M['BM']
BASE = ROOT / 'output/validation/native-adc10-pcb-ref_courtyard-20261018.epru'
BASE_SHA = '5a7aa8d85268aac8c31347c53b1f236ea521b1d94dc2899157037839bf832668'
FK = 'FILL', 'e680230ef8d2c5dd'
MM = .0254


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True)
    ap.add_argument('--allow-observed-duplicate-collapse', action='store_true')
    args = ap.parse_args()
    source = Path(args.source).resolve()
    assert sha(BASE) == BASE_SHA
    before, _ = PARSE(BASE)
    actual, _ = PARSE(source)
    checks, errors = [], []

    def check(ok, test, detail=None):
        item = {'test': test, 'passed': bool(ok)}
        if detail is not None: item['detail'] = detail
        checks.append(item)
        if not ok: errors.append(item)

    check(before.keys() == actual.keys(), 'Exact primitive membership')
    protected = {k: b for k, b in before.items() if k != FK and k[0] != 'DOCHEAD'}
    diffs = [k for k, b in protected.items() if actual.get(k) != b]
    check(not diffs, 'Every non-target native body exact, including all LINEs/components/attrs/vias/drills/pins/rules/stack', diffs)
    b, a = before[FK], actual[FK]
    check({k:v for k,v in b.items() if k != 'path'} == {k:v for k,v in a.items() if k != 'path'}, 'Target FILL all non-path fields exact')
    check(len(b['path']) == 222 and len(a['path']) == 221, 'Exactly one of222 contours removed')
    expected_paths = b['path'][:221]
    qualified_collapse = None
    if args.allow_observed_duplicate_collapse:
        observed = expected_paths[220]
        check(observed[36107:36111] == [864.1732, 3022.5354, 864.1732, 3022.5354],
              'Only observed exact consecutive duplicate point qualifies at retained path220 tokens36109..36110')
        expected_paths = list(expected_paths)
        expected_paths[220] = observed[:36109]+observed[36111:]
        qualified_collapse = {'pathIndex': 220, 'removedTokenIndices': [36109, 36110],
            'pointMil': [864.1732, 3022.5354], 'reason': 'Exact consecutive duplicate point; no coordinate or nonduplicate vertex changed'}
    check(a['path'] == expected_paths, 'Only path221 removed and optional exact observed duplicate collapsed; all remaining arrays exact')
    br = [BM['polyline'](p) for p in b['path']]
    ar = [BM['polyline'](p) for p in a['path']]
    contained = Polygon(br[221]); containing = Polygon(br[220])
    check(containing.contains(contained), 'Removed keepout fully nested inside retained clearance hole220')
    # The user-approved intended copper semantics are explicitly outer-minus-UNION(keepouts).
    # This is a proof of that intention, not a claim about native/CAM compound fill rules.
    intended_before = Polygon(br[0]).difference(unary_union([Polygon(r) for r in br[1:]]))
    literal_after = Polygon(ar[0], ar[1:])
    check(literal_after.is_valid, 'After polygon valid without buffer(0) or any repair', explain_validity(literal_after))
    xor = intended_before.symmetric_difference(literal_after).area*MM*MM
    addition = literal_after.difference(intended_before).area*MM*MM
    deletion = intended_before.difference(literal_after).area*MM*MM
    check(xor == 0 and addition == 0 and deletion == 0, 'Exactly preserves intended outer-minus-UNION keepouts, no intended copper added or removed',
          {'XORmm2': xor, 'copperAddedMm2': addition, 'copperRemovedMm2': deletion})
    tag = '-duplicate-qualified' if args.allow_observed_duplicate_collapse else ''
    out = HERE / f'adc10-reference-nested-hole-native{tag}-independent-audit-20261018.json'
    report = {'schema': 'stm32h747-reference-nested-hole-independent-20261018-v1', 'passed': not errors,
        'sourcePath': str(source), 'sourceSha256': sha(source), 'baselinePath': str(BASE), 'baselineSha256': BASE_SHA,
        'protectedNativeBodies': len(protected), 'removedPathIndex': 221, 'removedContourAreaMm2': contained.area*MM*MM,
        'qualifiedDuplicateCollapse': qualified_collapse,
        'removedContourBoundsMm': [v*MM for v in contained.bounds], 'mainGNDTopologyValid': literal_after.is_valid,
        'intendedCopperXORmm2': xor, 'checks': checks, 'errors': errors, 'liveAPICalls': 0, 'nativeFilesWritten': 0,
        'limitations': ['Copper equivalence is explicitly against intended outer-minus-UNION keepout semantics, not an unproven generic compound-path fill rule.',
            'Native strict DRC and final Gerber/CAM must separately confirm actual physical encoding. No fabrication approval.',
            'Full actual34-ground-pad and10-channel literal connectivity proof is a separate report rerun on this source.']}
    out.write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'passed': not errors, 'path': str(out), 'sha256': sha(out), 'sourceSha256': sha(source),
        'protectedNativeBodies': len(protected), 'failedTests': [e['test'] for e in errors]}, indent=2))
    if errors: raise SystemExit(1)


if __name__ == '__main__': main()
