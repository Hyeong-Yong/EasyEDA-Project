"""Read-only3941-document checkpoint durability/scope comparison for3D work."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import runpy
import zipfile

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'audit_model_metadata.py'))
ROOT,OUT=M['ROOT'],M['OUT']
PCB=('PCB','0ac2a19168000d8e')

def read(path):
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        src=z.read(next(n for n in names if n.endswith('.epru'))).decode('utf-8-sig')
        metadata=json.loads(z.read('project2.json'))
        images={n:hashlib.sha256(z.read(n)).hexdigest() for n in names if n.startswith('IMAGE/') and not n.endswith('/')}
    docs={};current=None;historic=0
    for line in src.splitlines():
        if not line.strip():
            continue
        rawh,rawb=line.split('||',1)
        h=json.loads(rawh)
        s=rawb.rstrip('|')
        b=json.loads(s) if s else None
        if h['type']=='DOCHEAD':
            assert b is not None
            current=(b['docType'],b['uuid'])
            docs.setdefault(current,{})
        assert current is not None
        k=(h['type'],str(h.get('id','')))
        previous=docs[current].get(k)
        if previous is None or h.get('ticket',0)>=previous[0].get('ticket',0):
            docs[current][k]=(h,b)
        historic+=b is None
    effective=0
    bodies={}
    for d,rows in docs.items():
        bodies[d]={k:b for k,(h,b) in rows.items() if b is not None}
        effective+=sum(b is None for h,b in rows.values())
    return bodies,metadata,images,{'historical_empty_body_tombstones':historic,'effective_latest_tombstones':effective}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before',type=Path,default=ROOT/'output/checkpoints/STM32H747_before_3d_models_20261018.epro2')
    ap.add_argument('--after',type=Path,required=True)
    ap.add_argument('--source',type=Path,required=True)
    ap.add_argument('--stage',required=True)
    ap.add_argument('--classify-exact-inherited-serialization',action='store_true',help='Accept only identical preexistingnative/checkpointrepresentations andexact2knownemptyNETadditions; rawdifferencesremainreported')
    ap.add_argument('--expected-model-count',type=int,choices=[407,412],default=407)
    ap.add_argument('--native-metadata-audit',type=Path,default=OUT/'audits/model-metadata-calibrated407-reviewed.json')
    args=ap.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]{1,70}',args.stage)
    paths=[p.resolve() for p in [args.before,args.after,args.source]]
    assert all(p.is_relative_to(ROOT.resolve()) for p in paths)
    before,after,source=paths
    assert M['sha'](before)=='10b0d1abb13e9c5842c3baa35e960feea852cfd9a909c7628b65704e48f47f10','Frozenbefore3Dcheckpointchanged'
    a,am,ai,at=read(before)
    b,bm,bi,bt=read(after)
    errors=[]
    if a.keys()!=b.keys():
        errors.append({'document_set_changed':{'missing':sorted(a.keys()-b.keys()),'added':sorted(b.keys()-a.keys())}})
    if len(a)!=3941 or len(b)!=3941:
        errors.append({'unexpected_document_count':[len(a),len(b)]})
    changed=[];session=[]
    for d in sorted(a.keys()&b.keys()):
        da={k:v for k,v in a[d].items() if k[0]!='DOCHEAD'}
        db={k:v for k,v in b[d].items() if k[0]!='DOCHEAD'}
        if da!=db:
            changed.append(d)
        ah=next(v for k,v in a[d].items() if k[0]=='DOCHEAD')
        bh=next(v for k,v in b[d].items() if k[0]=='DOCHEAD')
        fields=[k for k in ah.keys()|bh.keys() if ah.get(k)!=bh.get(k)]
        if fields:
            allowed=set(fields)<={'client','updateTime','version'}
            session.append({'document':d,'fields':fields,'allowed_session_only':allowed})
            if not allowed:
                errors.append({'dochead_non_session_changed':d,'fields':fields})
    exact_empty_net_additions=[]
    allowed_fp_docs={('FOOTPRINT','6bb29ef4f7785623'),('FOOTPRINT','e2e3d06dac58c326')}
    for d in changed:
        if d not in allowed_fp_docs:
            continue
        da={k:v for k,v in a[d].items() if k[0]!='DOCHEAD'}
        db={k:v for k,v in b[d].items() if k[0]!='DOCHEAD'}
        key=('NET','["NET",""]')
        if db.keys()-da.keys()=={key} and not da.keys()-db.keys() and all(da[k]==db[k] for k in da) and db[key]==M['EMPTY_NET_BODY']:
            exact_empty_net_additions.append({'document':d,'record':key,'added_body':db[key]})
    excluded_default_docs={tuple(e['document']) for e in exact_empty_net_additions} if args.classify_exact_inherited_serialization else set()
    if [d for d in changed if d not in excluded_default_docs]!=[PCB]:
        errors.append({'changed_design_documents_not_exactly_PCB_or_exact_reviewed2emptyNETdefaults':changed})
    if am!=bm:
        errors.append({'project2_json_changed':True})
    native,_=M['parse'](source)
    stored=b[PCB]
    source_only=native.keys()-stored.keys()
    checkpoint_only=stored.keys()-native.keys()
    mismatched=[k for k in native.keys()&stored.keys() if native[k]!=stored[k]]
    native_difference={'source_only':[{'record':k,'body':native[k]} for k in sorted(source_only)],
                       'checkpoint_only':[{'record':k,'body':stored[k]} for k in sorted(checkpoint_only)],
                       'changed':[{'record':k,'native':native[k],'checkpoint':stored[k]} for k in sorted(mismatched)]}
    def differences(n,s):
        return {'source_only':{k:n[k] for k in n.keys()-s.keys() if k[0]!='DOCHEAD'},
                'checkpoint_only':{k:s[k] for k in s.keys()-n.keys() if k[0]!='DOCHEAD'},
                'changed':{k:(n[k],s[k]) for k in n.keys()&s.keys() if k[0]!='DOCHEAD' and n[k]!=s[k]}}
    baseline_native,_=M['parse'](M['BASELINE'])
    inherited_before=differences(baseline_native,a[PCB])
    inherited_after=differences(native,stored)
    exact_inherited=inherited_before==inherited_after
    # Nativehistory placeholders are count bookkeeping, not primitives; editor
    # ACTIVE_LAYER is selection, never LAYER/RULE. Freeze and validate every
    # such entry instead of calling all raw representations identical.
    bookkeeping=[];bookkeeping_ok=True
    for phase,rows in [('before_checkpoint',a[PCB]),('after_checkpoint',stored),('before_native',baseline_native),('after_native',native)]:
        for k,v in rows.items():
            if k[0]=='ELE_PLACEHOLDER':
                valid=set(v)=={'dataType','max'} and isinstance(v['dataType'],str) and isinstance(v['max'],int) and v['max']>=0
                bookkeeping.append({'phase':phase,'record':k,'body':v,'valid_count_bookkeeping':valid})
                bookkeeping_ok=bookkeeping_ok and valid
            elif k[0]=='ACTIVE_LAYER':
                valid=set(v)=={'layerId'} and isinstance(v['layerId'],int)
                bookkeeping.append({'phase':phase,'record':k,'body':v,'valid_selection_only':valid})
                bookkeeping_ok=bookkeeping_ok and valid
    def protected_representation(d):
        return {category:{k:v for k,v in values.items() if k[0] not in {'ELE_PLACEHOLDER','ACTIVE_LAYER'}} for category,values in d.items()}
    exact_inherited_protected=protected_representation(inherited_before)==protected_representation(inherited_after)
    # DOCHEADidentity stillchecked; sessionclient/time/version/userpresence
    # are not design/electrical records. No geometryfieldisremovedhere.
    nhead=native['DOCHEAD',''];shead=stored['DOCHEAD','']
    head_ok=all(nhead.get(k)==shead.get(k) for k in ['docType','uuid','editVersion']) and set(k for k in nhead.keys()|shead.keys() if nhead.get(k)!=shead.get(k))<={'client','updateTime','version','user'}
    if any(native_difference.values()) and not (args.classify_exact_inherited_serialization and exact_inherited_protected and bookkeeping_ok and head_ok):
        errors.append({'stored_PCB_vs_native_readback_diff_counts':{k:len(v) for k,v in native_difference.items()},'exact_inherited_representation_differences':exact_inherited,'protected_representations_exact_inherited':exact_inherited_protected,'bookkeeping_schema_valid':bookkeeping_ok,'DOCHEAD_identity_ok':head_ok})
    reference_model_audit=args.native_metadata_audit.resolve()
    assert reference_model_audit.is_relative_to(OUT.resolve())
    audit=json.loads(reference_model_audit.read_text(encoding='utf-8'))
    if not audit['passed'] or audit['source']['sha256']!=M['sha'](source):
        errors.append({'audited_native_source_stale_or_failed':True})
    attrs=M['refs'](stored)[1]
    cref=M['refs'](stored)[0]
    applied={ref for ref,cid in cref.items() if stored['COMPONENT',cid].get('attrs',{}).get('3D Model')}
    inventory=json.loads((HERE/'components-437.json').read_text())
    fitted={p['ref'] for p in inventory if not p['dnp'] and not p['ref'].startswith('TP')}
    missing=fitted-applied
    local5={'CN1','CN2','CN3','CN4','L1'}
    expected_unlinked=local5 if args.expected_model_count==407 else set()
    if len(applied)!=args.expected_model_count or missing!=expected_unlinked:
        errors.append({'unexpected_fitted_model_missing':sorted(missing),'model_count':len(applied)})
    preview_changed=[n for n in sorted(ai.keys()|bi.keys()) if ai.get(n)!=bi.get(n)]
    report={'schema':'stm32-3d-saved-checkpoint-whole-project-scope-v1','passed':not errors,
      'before':{'path':str(before.relative_to(ROOT)),'bytes':before.stat().st_size,'sha256':M['sha'](before)},
      'after':{'path':str(after.relative_to(ROOT)),'bytes':after.stat().st_size,'sha256':M['sha'](after)},
      'native_source':{'path':str(source.relative_to(ROOT)),'sha256':M['sha'](source)},
      'document_counts':{'before':len(a),'after':len(b),'by_type':dict(Counter(d[0] for d in b))},
      'changed_design_documents_excluding_session_DOCHEAD':changed,'non_PCB_document_design_bodies_exact':all(a[d]==b[d] or {k:v for k,v in a[d].items() if k[0]!='DOCHEAD'}=={k:v for k,v in b[d].items() if k[0]!='DOCHEAD'} for d in a.keys()&b.keys() if d!=PCB),
      'exact_2_footprint_empty_NET_defaults_classified':exact_empty_net_additions,
      'non_PCB_raw_design_documents_unchanged_count':len(b)-1-len([d for d in changed if d!=PCB]),
      'non_PCB_design_geometry_and_connections_unchanged':len(changed)==1+len(exact_empty_net_additions),
      'non_PCB_document_count':len(b)-1,'session_DOCHEAD_changes':session,'project2_metadata_exact':am==bm,
      'preview_image_changes':preview_changed,'stored_PCB_exactly_matches_native_readback':not any(native_difference.values()),
      'classified_exact_inherited_serialization':args.classify_exact_inherited_serialization,
      'all_non_DOCHEAD_native_checkpoint_difference_IDs_and_both_bodies_exactly_same_as_pre3D_baseline':exact_inherited,
      'all_protected_design_representation_difference_IDs_and_both_bodies_exactly_same_as_pre3D_baseline':exact_inherited_protected,
      'inherited_representation_method':'For every nonbookkeepingnative-vs-checkpoint discrepancy, compare exact ID AND both native/stored fullbodies before3D vs after3D. FILLpaths/refs and64derivedselectors remain byte-value-equivalent to the inherited pair; no pathgeometry tolerance used.',
      'explicit_placeholder_and_active_selection_bookkeeping':bookkeeping,
      'bookkeeping_schema_valid':bookkeeping_ok,
      'inherited_difference_counts':{k:len(v) for k,v in inherited_after.items()},
      'stored_native_DOCHEAD_identity_valid':head_ok,
      'stored_native_difference':native_difference,'latest_ticket_tombstones':{'before':at,'after':bt},
      'model_count':len(applied),'fitted_physical_target_count':len(fitted),'unlinked_fitted_refs':sorted(missing),
      'local5_blocked_and_unlinked':missing==local5,'all412_model_metadata_linked':len(applied)==412 and not missing,
      'all412_visual_readiness_asserted_by_this_file_audit':False,
      'native_metadata_audit':{'path':str(reference_model_audit.relative_to(ROOT)),'sha256':M['sha'](reference_model_audit),'passed':audit['passed']},
      'native_calls':0,'errors':errors,'limits':[f'{len(applied)}native models are linked; fittedrefs stillunlinked:'+','.join(sorted(missing))+'.','No native close/reopen, rendering,3Dmodel fit or manufacturing approval is asserted by this saved-file audit.']}
    target=OUT/'audits'/f'checkpoint-scope-{args.stage}.json'
    assert not target.exists()
    target.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'passed':not errors,'report':str(target.relative_to(ROOT)),'sha256':M['sha'](target),
                      'after_sha256':M['sha'](after),'docs':len(b),'changed_design_docs':changed,'models':len(applied),'unlinked':sorted(missing),'errors':errors}))
    if errors:
        raise SystemExit(1)

if __name__=='__main__':
    main()
