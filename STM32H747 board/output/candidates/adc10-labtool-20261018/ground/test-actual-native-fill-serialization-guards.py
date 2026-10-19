"""Adversarial tests for the narrow public-API native serialization rule."""
import json
import argparse
import runpy
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = runpy.run_path(str(HERE / 'audit-actual-final-native-ground-power.py'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, default=HERE / 'actual-native-fill-serialization-adversarial-guard-tests.json')
    args = ap.parse_args()
    expected = [[.1234567, .2345678, 'L', 10.1234567, .2345678, 10.1234567, 10.2345678,
                 .1234567, 10.2345678, .1234567, .2345678]]
    actual = A['native_grid_paths'](expected)
    tests = [{'name': 'Exact native4dp serialization is accepted', 'passed': A['compare_known_api_paths'](expected, actual)['passed']}]
    shifted = [[v + 1 if isinstance(v, (int, float)) else v for v in r] for r in actual]
    tests.append({'name': 'Whole-shape shift is rejected', 'passed': not A['compare_known_api_paths'](expected, shifted)['passed']})
    drifted = [list(r) for r in actual]
    drifted[0][0] += .00001
    tests.append({'name': 'Unqualified subgrid single-vertex drift is rejected', 'passed': not A['compare_known_api_paths'](expected, drifted)['passed']})
    shifted_native = [[v + .0001 if isinstance(v, (int, float)) else v for v in r] for r in actual]
    tests.append({'name': 'A one-native-grid shape shift is rejected', 'passed': not A['compare_known_api_paths'](expected, shifted_native)['passed']})
    curves = [[-10, -10, 'L', 10, -10, 10, 10, -10, 10, -10, -10], ['CIRCLE', 0, 0, 1.2345678]]
    tests.append({'name': 'Curved native commands can remain byte-value exact', 'passed': A['compare_known_api_paths'](curves, curves)['passed']})
    changed_curve = [list(r) for r in curves]
    changed_curve[1][-1] += .00001
    tests.append({'name': 'Curve command numeric modification is rejected without rounding waiver', 'passed': not A['compare_known_api_paths'](curves, changed_curve)['passed']})
    tests.append({'name': 'Removing a hole is rejected', 'passed': not A['compare_known_api_paths'](curves, curves[:1])['passed']})
    report = {'schema': 'native-fill-serialization-adversarial-guard-tests-v1', 'passed': all(t['passed'] for t in tests),
              'tests': tests, 'auditorSha256': A['P']['sha'](HERE / 'audit-actual-final-native-ground-power.py'),
              'nativeCalls': 0, 'nativeModified': False}
    target = args.output
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(target), 'sha256': A['P']['sha'](target), **report}))


if __name__ == '__main__':
    main()
