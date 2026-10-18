"""Exact saved/readback state proof; lifecycle timeout is not concealed."""
import hashlib,json,runpy
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
PARSE=runpy.run_path(str(HERE/'audit-adc10-copper-cut-readback-20261018.py'))['parse']
APPLIED=ROOT/'output/validation/native-adc10-pcb-remaining6_lines_0-20261018.epru'
SAVED=ROOT/'output/validation/native-adc10-pcb-routed_drc0_saved-20261018.epru'
RELOAD=ROOT/'output/validation/native-adc10-pcb-routed_reopen_probe-20261018.epru'
IDS={'a1d7888349e74585','41fd0322eb2cc785','647c91cbbc161db2','23f25be226b43a88','c667926ae983cbc8','e680230ef8d2c5dd','a7cecc90c6e5b57b','daa2e5885d92eda0','ca6da24ce03912de','1cd997827b0241d6','2fb535085249015d','ef12098577a13cc7','4390d61d8c7f4f80','f9e70adc3ac35fbd','9bbb881293539c05','d8ad16a3b68b1fd9'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    a,_=PARSE(APPLIED);s,_=PARSE(SAVED);r,_=PARSE(RELOAD);errors=[]
    clean=lambda x:{k:b for k,b in x.items()if k[0]!='DOCHEAD'}
    if clean(a)!=clean(s):errors.append('Saved source differs from applied native state')
    if a.keys()!=r.keys():errors.append('Reload primitive membership changed')
    diffs=[]
    for k in a.keys()&r.keys():
        if k[0]=='DOCHEAD'or a[k]==r[k]:continue
        expected=dict(a[k]);allowed=k[0]=='FILL'and k[1]in IDS and a[k].get('refs')==[None]
        if allowed:expected['refs']=None
        if not allowed or r[k]!=expected:errors.append({'unqualifiedBodyDifference':k})
        diffs.append({'type':k[0],'id':k[1],'rule':'Exact inert FILL.refs [null]→null stored/reloaded normalization','passed':allowed and r[k]==expected})
    if{d['id']for d in diffs}!=IDS:errors.append('Unexpected normalized FILL ID set')
    ah=next(b for k,b in a.items()if k[0]=='DOCHEAD');rh=next(b for k,b in r.items()if k[0]=='DOCHEAD')
    if rh['uuid']!='0ac2a19168000d8e'or rh['docType']!='PCB'or rh['editVersion']!=ah['editVersion']:errors.append('Reload identity/editor mismatch')
    out=HERE/'adc10-routed-saved-reload-typed-preservation-independent-audit-20261018.json'
    report={'schema':'stm32h747-routed-saved-reload-typed-preservation-independent-20261018-v1','passed':not errors,'errors':errors,
        'applied':{'path':str(APPLIED),'sha256':sha(APPLIED)},'saved':{'path':str(SAVED),'sha256':sha(SAVED)},
        'readback':{'path':str(RELOAD),'sha256':sha(RELOAD)},'primitiveCount':len(r),'savedAllBodiesExact':clean(a)==clean(s),
        'qualifiedNormalizations':diffs,'everyOtherNativeBodyExact':not errors,'priorDochead':ah,'readbackDochead':rh,
        'newClientIsConsistentWithReload':ah['client']!=rh['client'],'lifecycleToolOutcome':'Close/open call timed out; source data alone does not prove lifecycle completion.',
        'liveAPICalls':0,'nativeFilesWritten':0,'limits':['Readback state is exactly preserved apart from16explicit inert refs normalizations; no geometry, nets, membership, rule or drill exception.',
            'Root independently verifies current active PCB UUID/UI document state. Preserve timeout evidence, do not rerun mutation merely to replace an ambiguous receipt.']}
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'errors':errors},indent=2))
    if errors:raise SystemExit(1)
if __name__=='__main__':main()
