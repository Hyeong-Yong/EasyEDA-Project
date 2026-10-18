"""Audit native schematic readback against the reviewed ADC10 candidate."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/candidates/adc10-dc-buffer-20261017'

def parse(path):
    rows = {}
    for line in Path(path).read_text(encoding='utf8').splitlines():
        if '||' not in line:
            continue
        raw_h, raw_b = line.split('||', 1)
        h = json.loads(raw_h)
        raw_b = raw_b[:-1] if raw_b.endswith('|') else raw_b
        b = json.loads(raw_b) if raw_b else ''
        key = h['type'], str(h.get('id', ''))
        if key not in rows or h.get('ticket', 0) >= rows[key][0].get('ticket', 0):
            rows[key] = h, b
    return {k: b for k, (_, b) in rows.items() if b != ''}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', required=True, type=Path)
    ap.add_argument('--tag', required=True)
    args = ap.parse_args()
    assert args.source.resolve().is_relative_to(ROOT.resolve())
    assert args.tag.replace('-', '').replace('_', '').isalnum()
    plan = json.loads((OUT / 'adc10-schematic-plan.json').read_text(encoding='utf8'))
    candidate_path = Path(plan['candidatePath'])
    assert sha(candidate_path) == plan['candidateSha256']
    expected, actual = parse(candidate_path), parse(args.source)
    added = {(r['h']['type'], r['h'].get('id', '')) for r in plan['added']}
    changed = {(r['type'], r['id']) for r in plan['changes']}
    errors, normalizations, aliases = [], [], []
    for k in list(expected.keys()-actual.keys()):
        if k[0] != 'ATTR' or k not in added:
            continue
        matches = [q for q in actual.keys()-expected.keys() if q[0]=='ATTR' and actual[q]==expected[k]]
        if len(matches) == 1:
            q = matches[0]
            aliases.append({'expected':k, 'native':q, 'rule':'new device metadata ATTR re-materialized with identical body'})
            actual[k] = actual.pop(q)
    if expected.keys() != actual.keys():
        errors.append({'missing': sorted(expected.keys()-actual.keys()), 'unexpected': sorted(actual.keys()-expected.keys())})
    for k in expected.keys() & actual.keys():
        a, b = expected[k], actual[k]
        if a == b:
            continue
        original_a = a
        a = dict(a)
        preliminary = []
        if k in added | changed and k[0] in {'ATTR','TEXT'} and a.get('strikeout') is False and 'strikeout' not in b:
            del a['strikeout']
            preliminary.append('false strikeout omitted by decoder')
        if k in added and k[0] == 'TEXT' and a.get('fillColor') is None and b.get('fillColor') == a.get('color'):
            a['fillColor'] = b['fillColor']
            preliminary.append('new text fillColor resolves to explicit foreground color')
        if k in changed and k[0] == 'COMPONENT':
            for f in ('x','y'):
                if isinstance(a.get(f), (int,float)) and isinstance(b.get(f), (int,float)) and a[f] != b[f] and abs(a[f]-b[f]) <= 1e-9:
                    a[f] = b[f]
                    preliminary.append(f+' floating-point serialization difference <= 1e-9 schematic units')
        if a == b:
            normalizations.append({'record':k, 'rule':'; '.join(preliminary), 'fields':[f for f in original_a.keys() | b.keys() if original_a.get(f,'__ABSENT__') != b.get(f,'__ABSENT__')]})
            continue
        fields = {f for f in a.keys() | b.keys() if a.get(f, '__ABSENT__') != b.get(f, '__ABSENT__')}
        rule = None
        if k[0] == 'DOCHEAD' and fields <= {'client', 'version', 'updateTime'}:
            rule = 'session header only'
        elif k[0] == 'LINE' and k in added and fields == {'strokeWidth'} and a.get('strokeWidth') == .6 and b.get('strokeWidth') is None:
            rule = 'new line 0.6 to null native default'
        elif k[0] == 'POLY' and fields == {'points'}:
            clean = lambda ps: [{f:v for f,v in p.items() if f != 'hashed'} for p in ps]
            if clean(a['points']) == clean(b['points']) and all(isinstance(p.get('hashed'), int) for p in b['points']):
                rule = 'point hash cache only; all coordinates exact'
        elif k[0] == 'ATTR' and fields == {'zIndex'} and a.get('key') in {'NET', 'Relevance'}:
            if isinstance(a.get('zIndex'), (int,float)) and isinstance(b.get('zIndex'), (int,float)) and 0 <= b['zIndex'] <= 100:
                rule = 'wire metadata display order only'
        if rule:
            normalizations.append({'record': k, 'rule': '; '.join(preliminary+[rule]), 'fields': sorted(fields), 'beforeZ':a.get('zIndex') if fields=={'zIndex'} else None, 'afterZ':b.get('zIndex') if fields=={'zIndex'} else None})
        else:
            errors.append({'record': k, 'fields': sorted(fields), 'expected':a, 'actual':b})
    report = {'passed': not errors, 'candidateSha256':sha(candidate_path), 'sourcePath':str(args.source), 'sourceSha256':sha(args.source), 'records':len(actual), 'recordMembershipExactAfterIdenticalNewMetadataAttrIdRemap':expected.keys()==actual.keys(), 'identicalNewMetadataAttrIdRemapCount':len(aliases), 'attrIdAliases':aliases, 'normalizationCounts':dict(Counter(n['rule'] for n in normalizations)), 'normalizations':normalizations, 'errors':errors}
    path = OUT / ('adc10-'+args.tag+'-normalization-audit.json')
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'normalizations','errors','attrIdAliases'}} | {'report':str(path), 'errorCount':len(errors), 'errorSummary':[{'record':e.get('record'), 'fields':e.get('fields')} for e in errors[:15]]}, indent=2))
    if errors:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
