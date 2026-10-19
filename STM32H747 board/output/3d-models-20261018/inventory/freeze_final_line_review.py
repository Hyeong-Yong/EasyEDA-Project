"""Freeze one exact observed final native LINE reserialization case.

No native calls/CAD writes. Inspection is the default. Final acceptance needs
explicit expected record counts and the inspected source SHA supplied by root.
Only zIndex is omitted, only while exact rational centerline/net/layer/width/
all other metadata interval unions are identical. Full IDs/bodies are frozen.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'audit_model_metadata.py'))
ROOT,OUT=M['ROOT'],M['OUT']

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--stage',required=True)
    ap.add_argument('--approve-inspected-source-sha256')
    ap.add_argument('--expected-deleted',type=int)
    ap.add_argument('--expected-added',type=int)
    ap.add_argument('--expected-changed',type=int)
    args=ap.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]{1,70}',args.stage)
    source=args.source.resolve()
    assert source.is_relative_to(ROOT.resolve())
    assert M['sha'](M['BASELINE'])==M['BASE_SHA']
    a,_=M['parse'](M['BASELINE'])
    b,_=M['parse'](source)
    added,deleted=b.keys()-a.keys(),a.keys()-b.keys()
    changed=[k for k in a.keys()&b.keys() if a[k]!=b[k]]
    delta={'added_lines':[{'record':list(k),'body':b[k]} for k in sorted(added) if k[0]=='LINE'],
           'deleted_lines':[{'record':list(k),'body':a[k]} for k in sorted(deleted) if k[0]=='LINE'],
           'changed_line_bodies':[{'record':list(k),'before':a[k],'after':b[k]} for k in sorted(changed) if k[0]=='LINE']}
    exact=M['line_unions'](a,{'zIndex'})==M['line_unions'](b,{'zIndex'})
    full=M['line_unions'](a)==M['line_unions'](b)
    counts={'deleted':len(delta['deleted_lines']),'added':len(delta['added_lines']),'changed':len(delta['changed_line_bodies'])}
    current_sha=M['sha'](source)
    approved=args.approve_inspected_source_sha256 is not None
    if approved:
        assert args.approve_inspected_source_sha256==current_sha,'Explicit sourceSHA does not match inspected file'
        assert None not in [args.expected_deleted,args.expected_added,args.expected_changed], 'Approved case needs all3 exact expected counts'
        assert counts=={'deleted':args.expected_deleted,'added':args.expected_added,'changed':args.expected_changed}, 'Unexpected LINE case counts'
        assert exact,'Net/layer/width/physical centerline or other protected LINE metadata changed'
        assert all(r['body'].get('zIndex')==-1 for r in delta['added_lines']),'Added LINEzIndex is not native-1 case'
        assert not delta['changed_line_bodies'],'Changed-body LINEs need separate case interpretation; this tool freezes split/replacement cases only'
    review={'schema':'stm32-native-final-frozen-line-case-v1','status':'APPROVED_EXACT_CASE' if approved else 'INSPECT_ONLY_NOT_APPROVED',
      'baseline_sha256':M['BASE_SHA'],'reviewed_source':str(source.relative_to(ROOT)), 'reviewed_source_sha256':current_sha,
      'strict_line_id_and_body_preservation':not any(counts.values()),'all_metadata_line_union_preservation':full,
      'observed_exact_geometry_and_non_display_metadata_union_preserved':exact,
      # Audit-compatible acceptance field deliberately stays FALSE for drafts.
      'exact_geometry_and_non_display_metadata_union_preserved':approved and exact,
      'allowed_omitted_metadata_fields':['zIndex'] if approved else [],'line_delta':delta,'counts':counts,
      'deleted_lines_by_net':dict(Counter(r['body'].get('netName') for r in delta['deleted_lines'])),
      'added_lines_by_net':dict(Counter(r['body'].get('netName') for r in delta['added_lines'])),
      'method':'Fraction(str(native decimal)) exact infinite-line support and closed-interval unions, grouped by every noncoordinateLINEbodyfield exceptzIndex. No geometric tolerance or coordinate rounding.',
      'approval_basis':'SourceSHA andexactdeleted/added/changedcounts explicitly supplied afterinspection; exact fullLINEID/bodydelta frozen. Future case reuse requires exactdelta identity.' if approved else 'Not approved: review thisfullcase and supply exactsourceSHA/counts to create a separate approved stage.',
      'reusable_only_if_exact_delta_matches':True,'cad_modified_by_review':False}
    target=OUT/'audits'/f'line-reserialization-{args.stage}.json'
    assert not target.exists(),'Never overwrite an observed/reviewed case'
    target.write_text(json.dumps(review,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'path':str(target.relative_to(ROOT)),'sha256':M['sha'](target),'status':review['status'],'source_sha256':current_sha,
                      'counts':counts,'exact_physical_and_non_display_union':exact,'exact_allmetadata_union':full,
                      'deleted_nets':review['deleted_lines_by_net']}))

if __name__=='__main__':
    main()
