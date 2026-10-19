"""Focused exported drill/outline/bottom-label regression, not fab approval."""
import argparse
import hashlib
import importlib.util
import json
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'output/candidates/adc10-labtool-20261018'
BASE = ROOT / 'output/validation/STM32H747_adc10_routed_20261018_DIAGNOSTIC_NOT_FOR_FAB.zip'
BASE_SHA = 'af168c61f367eaa980b4e9140824e6c2cf6ee3e718466cae9c51a08004ce9405'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def drillkey(x):
    return (x.category, tuple(round(v, 5) for v in x.center_mm), round(x.diameter_mm, 5),
            tuple(round(v, 5) for v in x.start_mm) if x.start_mm else None,
            tuple(round(v, 5) for v in x.end_mm) if x.end_mm else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--zip-sha', required=True)
    ap.add_argument('--manifest', required=True)
    ap.add_argument('--manifest-sha', required=True)
    args = ap.parse_args()
    new = (ROOT / args.zip).resolve()
    planpath = (ROOT / args.manifest).resolve()
    assert new.is_relative_to((ROOT / 'output/validation').resolve()) and new.suffix == '.zip'
    assert planpath.is_relative_to(HERE.resolve()) and planpath.suffix == '.json'
    assert sha(BASE) == BASE_SHA and sha(new) == args.zip_sha and sha(planpath) == args.manifest_sha
    plan = json.loads(planpath.read_text(encoding='utf8'))
    assert plan['PCBRequired'] == '0ac2a19168000d8e'
    expected = [o for b in plan['batches'] for o in b['operations'] if o['action'] == 'via']
    assert len(expected) == plan['operationCounts']['via']
    drill = module('labtool_drill_parser', 'audit-diagnostic-gerber-drill-zip.py')
    geom = module('labtool_outline_parser', 'audit-cn1-cutout-gerber-20261016.py')
    before, _, _ = drill.read_candidate_zip(BASE)
    after, _, _ = drill.read_candidate_zip(new)
    a, b = Counter(map(drillkey, before)), Counter(map(drillkey, after))
    lost, added = a - b, b - a
    additions = [x for x in after if drillkey(x) in added]
    matches = []
    for v in expected:
        xy = [t * .0254 for t in v['xyMil']]
        hits = [x for x in additions if x.kind == 'round' and x.plated_class == 'pth'
                and math.dist(xy, x.center_mm) < .00002
                and abs(x.diameter_mm - v['drillMil'] * .0254) < .00002]
        matches.append(dict(key=v['key'], net=v['net'], expectedXYmm=xy,
                            matchedXYmm=list(hits[0].center_mm) if len(hits) == 1 else None,
                            passed=len(hits) == 1))
    parser = geom.load_parser()
    with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(new) as current:
        outline, old_outline, new_outline = geom.gerber_identity(
            geom.OUTLINE_MEMBER, old.read(geom.OUTLINE_MEMBER), current.read(geom.OUTLINE_MEMBER), parser)
        gbo = 'Gerber_BottomSilkscreenLayer.GBO'
        oldsilk = geom.parsed(old.read(gbo), gbo, parser)
        newsilk = geom.parsed(current.read(gbo), gbo, parser)
        silk_lost = Counter(geom.object_hashes(oldsilk)) - Counter(geom.object_hashes(newsilk))
        copper_names = [n for n in current.namelist() if n.lower().endswith(('.gtl', '.gbl', '.g1', '.g2', '.g3', '.g4'))]
    checks = dict(all799OriginalDrillsPreserved=len(before) == 799 and not lost,
                  expectedNewPthCount=sum(added.values()) == len(expected) == len(additions),
                  expectedExportedPhysicalDrillCount=len(after) == 799 + len(expected),
                  everyNewNativeViaMatchesExport=all(x['passed'] for x in matches),
                  oldMechanicalOutlineExact=outline['status'] == 'pass' and len(new_outline['objects']) == 8,
                  priorVerifiedBottomSilkStrokesRetained=not silk_lost,
                  sixCopperLayerMembers=len(copper_names) == 6)
    report = dict(schema='labtool-adc10-focused-diagnostic-gerber-regression-v1',
                  passed=all(checks.values()), checks=checks,
                  baseline=dict(path=str(BASE), sha256=sha(BASE)),
                  current=dict(path=str(new), sha256=sha(new)),
                  executionManifest=dict(path=str(planpath), sha256=sha(planpath)),
                  beforeDrills=len(before), afterDrills=len(after),
                  lostOriginalDrills=list(lost.items()), newViaMatches=matches,
                  copperMembers=copper_names,
                  outlineExactResolvedObjects=outline['resolved_geometry_object_sequence_exact'],
                  bottomSilk=dict(oldObjectCount=len(oldsilk['objects']), newObjectCount=len(newsilk['objects']),
                                  lostStrokeCount=sum(silk_lost.values()),
                                  qualification='Inherits prior actual-backside readability verification only if the exact resolved stroke multiset is retained.'),
                  nativeCalls=0, manufacturingApproved=False,
                  limitations=['Focused drill/outline/silkscreen export check only, not full copper CAM clearance or signal-integrity validation.',
                               'Existing inner-layer export/CAM caveats and hardware noise/startup/settling validation are not cleared by this report.'])
    out = HERE / 'independent-diagnostic-gerber-regression.json'
    assert not out.exists(), 'Do not overwrite prior export evidence'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(passed=report['passed'], report=str(out), sha256=sha(out), checks=checks)))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
