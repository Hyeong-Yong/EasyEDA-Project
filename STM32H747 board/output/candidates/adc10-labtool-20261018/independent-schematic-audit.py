"""Read-only candidate topology audit; only its sibling JSON report is written."""
import copy
import hashlib
import json
import math
import runpy
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLAN = HERE / 'schematic-plan.json'
CHECK = ROOT / 'output/checkpoints/STM32H747_before_labtool_afe_20261018.epro2'
LIBCHECK = ROOT / 'output/checkpoints/STM32H747_labtool_protection_libraries_20261018.epro2'
G = runpy.run_path(str(HERE.parent / 'adc10-dc-buffer-20261017/independent-adc10-candidate-graph-audit.py'))
READER = runpy.run_path(str(ROOT / 'scripts/build-adc10-labtool-libraries-20261018.py'))['read_snapshot']
CHANNELS = [
    (2,'ADC1_INP0',137,140,141,80,97,100), (3,'ADC1_INP1',138,142,143,81,98,101),
    (4,'ADC1_INP16',139,144,145,82,99,102), (5,'ADC2_INP3',149,152,153,86,106,113),
    (6,'ADC2_INP12',150,154,155,87,107,114), (7,'ADC2_INP13',151,156,157,88,108,115),
    (8,'ADC3_INP2',161,165,166,93,109,116), (9,'ADC3_INP6',162,167,168,94,110,117),
    (10,'ADC3_INP7',163,169,170,95,111,118), (11,'ADC3_INP8',164,171,172,96,112,119)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def body_rows(rows):
    return {(h['type'], h.get('id')): b for h,b in rows.values()}


def rv(value):
    v=str(value).lower().replace('ohm','').strip()
    return float(v[:-1])*{'k':1e3,'m':1e6}[v[-1]] if v[-1:] in ('k','m') else float(v)


def expected_channels():
    expected={}
    for i,(j,adc,rb,ri,rs,c,cp,cd) in enumerate(CHANNELS):
        raw,pre,buf,summ,drv=[f'ADC_J{j}_{s}' for s in ['RAW','FILTER','BUF','SUM','DRV']]
        row={f'J{j}':{1:raw,2:'GND'},f'R{177+i}':{1:'GND',2:raw},f'R{ri}':{1:raw,2:pre},
            f'C{cp}':{1:pre,2:'GND'},f'U{20+i}':{1:buf,2:'-3V_AFE',3:pre,4:buf,5:'+5V_AFE'},
            f'C{120+i*3}':{1:'+5V_AFE',2:'GND'},f'C{121+i*3}':{1:'-3V_AFE',2:'GND'},
            f'R{rb}':{1:buf,2:summ},f'U{10+i}':{1:drv,2:'GND',3:'ADC_OFFSET_0V97',4:summ,5:'+3V3'},
            f'C{cd}':{1:'+3V3',2:'GND'},f'R{187+i}':{1:summ,2:drv},f'C{122+i*3}':{1:summ,2:drv},
            f'R{rs}':{1:drv,2:adc},f'C{c}':{1:adc,2:'GND'},f'TP{j-1}':{1:adc}}
        expected.update({r:{str(n):net for n,net in ns.items()} for r,ns in row.items()})
    return expected


def expected_power():
    # R201 is electrically symmetric, but actual 90-degree pin1 is bottom.
    rows={'D20':{1:'-3V_AFE',2:'AFE_VNEG_RAW'},'U30':{1:'AFE_VNEG_RAW',2:'AFE_PUMP_IN',3:'AFE_FLY_N',4:'GND',5:'AFE_FLY_P'},
        'R197':{1:'+5V',2:'AFE_PUMP_IN'},'C150':{1:'AFE_PUMP_IN',2:'GND'},'C151':{1:'AFE_FLY_N',2:'AFE_FLY_P'},
        'C152':{1:'AFE_VNEG_RAW',2:'GND'},'U31':{1:'GND',2:'AFE_VNEG_RAW',3:'AFE_VNEG_RAW',4:'AFE_NEG_FB',5:'-3V_AFE'},
        'C153':{1:'-3V_AFE',2:'GND'},'C154':{1:'-3V_AFE',2:'GND'},'R198':{1:'-3V_AFE',2:'AFE_NEG_FB'},
        'R199':{1:'GND',2:'AFE_NEG_FB'},'C155':{1:'AFE_NEG_FB',2:'-3V_AFE'},'R200':{1:'+5V',2:'+5V_AFE'},
        'C156':{1:'+5V_AFE',2:'GND'},'C157':{1:'+5V_AFE',2:'GND'},
        'U9':{1:None,2:'+5V_AFE',3:None,4:'GND',5:'AFE_REF_NR',6:'AFE_REF_2V5',7:None,8:None},
        'C103':{1:'+5V_AFE',2:'GND'},'R201':{1:'AFE_REF_ESR',2:'AFE_REF_2V5'},'C104':{1:'AFE_REF_ESR',2:'GND'},
        'C105':{1:'AFE_REF_NR',2:'GND'},'R202':{1:'AFE_REF_2V5',2:'AFE_OFFSET_FILTER'},
        'R203':{1:'GND',2:'AFE_OFFSET_FILTER'},'C158':{1:'AFE_OFFSET_FILTER',2:'GND'},
        'U32':{1:'AFE_OFFSET_BUFFER',2:'GND',3:'AFE_OFFSET_FILTER',4:'AFE_OFFSET_BUFFER',5:'+5V_AFE'},
        'R204':{1:'AFE_OFFSET_BUFFER',2:'ADC_OFFSET_0V97'},'C159':{1:'ADC_OFFSET_0V97',2:'GND'},'C160':{1:'+5V_AFE',2:'GND'}}
    return {r:{str(n):net for n,net in ns.items()} for r,ns in rows.items()}


def native_readback(candidate,actual_path,lib,power=False):
    """Typed decoder normalization only; no electrical field is waived."""
    actual=G['parse'](actual_path)
    source_sha=sha(actual_path)
    a,refs=G['attrs_for'](candidate)
    b,brefs=G['attrs_for'](actual)
    differences=[]
    normal=[]
    owner_attrs=defaultdict(list)
    for k,v in candidate.items():
        if k[0]=='ATTR':owner_attrs[v.get('parentId')].append((k,v))
    for key in candidate.keys()|actual.keys():
        if key not in candidate or key not in actual:
            differences.append({'record':key,'reason':'record membership changed'})
            continue
        old,new=candidate[key],actual[key]
        if old==new:continue
        expected=copy.deepcopy(old)
        kind,rid=key
        def record(rule,field,detail=None):
            normal.append({'record':key,'rule':rule,'field':field,**({'detail':detail} if detail is not None else {})})
        if kind=='DOCHEAD':
            for field in ('client','version','updateTime'):
                if old.get(field)!=new.get(field):expected[field]=new[field];record('native document session metadata',field)
        if kind=='LINE' and old.get('strokeWidth')==.6 and new.get('strokeWidth') is None:
            expected['strokeWidth']=None;record('native default wire stroke0.6 represented null','strokeWidth')
        if kind=='POLY' and old.get('points')!=new.get('points'):
            stripped=lambda v:[{k:x for k,x in p.items() if k!='hashed'} for p in v]
            if stripped(old['points'])==stripped(new['points']):
                expected['points']=copy.deepcopy(new['points']);record('point hash cache recomputed; all actual XY exact','points',{'points':len(old['points'])})
        if kind=='COMPONENT':
            for field in ('x','y'):
                if old.get(field)!=new.get(field) and isinstance(old.get(field),(int,float)) and new.get(field)==round(old[field],6) and abs(old[field]-new[field])<=1e-9:
                    expected[field]=new[field];record('decimal float serialization at six-place source precision',field,{'absoluteDelta':abs(old[field]-new[field])})
            oa,na=old.get('attrs',{}),new.get('attrs',{})
            if 'SymbolName' in oa and 'SymbolName' not in na and {k:v for k,v in oa.items() if k!='SymbolName'}==na:
                packed=json.loads(oa['SymbolName'])
                if packed['uuid']==a[rid].get('Symbol')==b[rid].get('Symbol') and ('SYMBOL',packed['uuid']) in lib:
                    expected['attrs']=copy.deepcopy(na);record('redundant packed SymbolName omitted; explicit runtime Symbol attr unchanged','attrs.SymbolName')
        if kind=='ATTR':
            if old.get('strikeout') is False and 'strikeout' not in new:
                expected.pop('strikeout',None);record('false strikeout default omitted','strikeout')
            if old.get('key') in {'NET','Relevance'} and old.get('fillColor') is None and new.get('fillColor')==old.get('color')=='#000080':
                expected['fillColor']=new['fillColor'];record('native wire-metadata text fill defaults to its unchanged color','fillColor')
            if old.get('key') in {'NET','Relevance'} and old.get('zIndex')==9000 and ('WIRE',old.get('parentId')) in candidate:
                line_count=sum(k[0]=='LINE' and v.get('lineGroup')==old['parentId'] for k,v in candidate.items())
                wire_net=a[old['parentId']].get('NET','')
                branch_child=1 if wire_net.startswith('ADC_J') and wire_net.endswith(('_SUM','_DRV')) else 0
                native_z=line_count+(2 if old['key']=='NET' else 1)+branch_child
                if new.get('zIndex')==native_z:
                    expected['zIndex']=native_z;record('native wire metadata z-order derived from owner LINE count and SUM/DRV branch child','zIndex',{'ownerLines':line_count,'branchChild':branch_child,'nativeValue':native_z})
                elif power and isinstance(new.get('zIndex'),int) and 1<=new['zIndex']<=line_count+8:
                    expected['zIndex']=new['zIndex'];record('frozen native power-wire display child order only; exact geometry and NET retained','zIndex',{'ownerLines':line_count,'nativeValue':new['zIndex']})
            meta_z={'Description':20,'Datasheet Revision':21}
            if old.get('key') in meta_z and old.get('zIndex')==100 and a[old.get('parentId')].get('Value')=='OPA189IDBVR' and new.get('zIndex')==meta_z[old['key']]:
                expected['zIndex']=new['zIndex'];record('new OPA189 descriptive metadata append display order20/21','zIndex')
                for field in ('fontWeight','italic','underline','fillColor'):
                    if field not in old and field in new and new[field] is None:
                        expected[field]=None;record('native null display default inserted for new descriptive metadata',field)
            if power and ('COMPONENT',old.get('parentId')) in candidate:
                own=owner_attrs[old['parentId']]
                symbol=lib['SYMBOL',a[old['parentId']]['Symbol']]
                drawable=sum(k[0] in {'PIN','POLY','RECT','ELLIPSE','ARC','TEXT','LINE','BEZIER'} for k in symbol)
                source_base=next((v.get('zIndex') for k,v in own if v.get('key')=='Add into BOM'),None)
                if isinstance(source_base,(int,float)):
                    delta=drawable-source_base
                    defaults=[k for k,v in own if v.get('zIndex')==100]
                    max_prior=max(v.get('zIndex',0)+delta for k,v in own if v.get('zIndex')!=100)
                    proposed=max_prior+defaults.index(key)+1 if key in defaults else old.get('zIndex',0)+delta
                    if old.get('zIndex')!=new.get('zIndex') and new.get('zIndex')==proposed:
                        expected['zIndex']=new['zIndex'];record('native component attribute display order derived from actual symbol drawable count and appended metadata','zIndex',{'drawables':drawable,'sourceBase':source_base,'nativeValue':proposed})
                if old.get('x') is None and old.get('y') is None and not old.get('valueVisible'):
                    for field in ('fontWeight','italic','underline','fillColor'):
                        if field not in old and field in new and new[field] is None:
                            expected[field]=None;record('native null hidden-metadata display default inserted',field)
        if kind=='TEXT' and old.get('fillColor') is None and new.get('fillColor')==old.get('color')=='#006666':
            expected['fillColor']=new['fillColor'];record('native text fill defaults to unchanged text color','fillColor')
        if expected!=new:
            differences.append({'record':key,'reason':'unclassified body fields','fields':[f for f in expected.keys()|new.keys() if (f in expected)!=(f in new) or expected.get(f)!=new.get(f)]})
    cp,ap=G['actual_pins'](candidate,a,lib),G['actual_pins'](actual,b,lib)
    _,ci,cn,cat=G['graph'](candidate,a)
    _,ai,an,aat=G['graph'](actual,b)
    pin_errors=[]
    for key in cp.keys()|ap.keys():
        if key not in cp or key not in ap:
            pin_errors.append({'pin':key,'reason':'actual symbol pin membership changed'});continue
        if cp[key]!=ap[key] or cat(cp[key]['point'])['nets']!=aat(ap[key]['point'])['nets']:
            pin_errors.append({'pin':key,'candidate':cp[key],'actual':ap[key],'candidateNets':cat(cp[key]['point'])['nets'],'actualNets':aat(ap[key]['point'])['nets']})
    mixed=[sorted(n) for n in an.values() if len(n)>1]
    return {'passed':not differences and not pin_errors and not mixed and source_sha==sha(actual_path),
        'path':str(actual_path),'sha256':source_sha,'candidateRecords':len(candidate),'actualRecords':len(actual),
        'normalizationCounts':dict(Counter(n['rule'] for n in normal)),'normalizations':normal,
        'unclassifiedDifferences':differences,'actualPinCount':len(ap),'actualPinChanges':pin_errors,'actualMixedNetIslands':mixed,
        'allElectricalValuesPinMappingsNetNamesAndLibraryUuidsPreserved':not differences and not pin_errors}


def preapply_power_live():
    baseline_path=HERE/'power-baseline.epru'
    candidate_path=HERE/'03_MCU_POWER_labtool_candidate.epru'
    live_path=ROOT/'output/validation/native-adc10-labtool-page03-preapply-live-20261018.epru'
    baseline,candidate,live=[G['parse'](p) for p in (baseline_path,candidate_path,live_path)]
    absent={('META','META'):{'title':'03_MCU_POWER','schematic':'416c10313f778784','source':'','zIndex':2.5}}
    for n in range(1,6):absent['ELE_PLACEHOLDER','placeholder'+str(n)]={'dataType':'POLY' if n==1 else 'ATTR','max':13 if n==1 else 1}
    special_z={'858f17e72ae452c2':21,'bde0f811bea954b8':40,'076c30117d285334':26,'34a45ee74684584e':39,
        'e574b6bf11705c7f':23,'1e29aaccaa9851c2':38,'e58d3310a13552eb':24,'dba2d5910ba1578d':28,
        '51ffd4d13e955c7b':25,'7d4569dc743f5b97':43,'a4f787310ec25dd7':27,'76e5449d3dc95110':25,'9f11af71af4f534b':30}
    errors=[];norm=[]
    if baseline.keys()-live.keys()!=absent.keys() or live.keys()-baseline.keys():errors.append({'recordMembershipDifferenceNotExactlySixCheckpointOnlyRecords':True})
    if any(baseline.get(k)!=v for k,v in absent.items()):errors.append({'sixAbsentRecordBodiesNotExact':True})
    a,refs=G['attrs_for'](baseline)
    for k in baseline.keys()&live.keys():
        old,new=baseline[k],live[k]
        if old==new:continue
        x=copy.deepcopy(old)
        def record(rule,field):norm.append({'record':k,'rule':rule,'field':field,'beforePresent':field in old,'before':old.get(field),'afterPresent':field in new,'after':new.get(field),'ownerRef':a[old.get('parentId')].get('Designator') if k[0]=='ATTR' else None})
        if k[0]=='DOCHEAD':
            for f in ('client','updateTime','version'):
                if old.get(f)!=new.get(f):x[f]=new[f];record('native session identity/timestamp, same page UUID and type',f)
            if old.get('user')=={} and 'user' not in new:x.pop('user');record('empty session user object omitted','user')
        if k[0]=='ATTR':
            if old.get('strikeout') is None and new.get('strikeout') is False:
                x['strikeout']=False;record('missing/null false-default strikeout materialized false','strikeout')
            if k[1] in special_z:
                if old.get('groupId')=='' and 'groupId' not in new:x.pop('groupId');record('empty grouping metadata omitted','groupId')
                if old.get('zIndex')==1 and new.get('zIndex')==special_z[k[1]]:x['zIndex']=new['zIndex'];record('frozen13 legacy component-attribute display-order defaults','zIndex')
        if k==('RECT','d1644bed38ff5bd9'):
            for f in ('partId','groupId'):
                if old.get(f)=='' and f not in new:x.pop(f);record('blank page-rectangle library/group default omitted',f)
            if old.get('strokeColor')=='' and new.get('strokeColor') is None:x['strokeColor']=None;record('empty transparent stroke represented null','strokeColor')
        if x!=new:errors.append({'record':k,'unclassifiedFields':[f for f in x.keys()|new.keys() if (f in x)!=(f in new) or x.get(f)!=new.get(f)]})
    protected=[k for k in baseline if k[0] in {'COMPONENT','POLY','WIRE','LINE','CANVAS'}]
    protected_diff=[k for k in protected if baseline[k]!=live.get(k)]
    if protected_diff:errors.append({'geometryOrOwnerBodyChanges':protected_diff})
    candidate_base_diff=[k for k in baseline if candidate.get(k)!=baseline[k]]
    candidate_deleted=baseline.keys()-candidate.keys()
    candidate_added=candidate.keys()-baseline.keys()
    if candidate_base_diff or candidate_deleted or len(candidate_added)!=658:errors.append({'candidateNotPure658RecordAddition':{'changed':candidate_base_diff,'deleted':sorted(candidate_deleted),'addedCount':len(candidate_added)}})
    lib={d:body_rows(r) for d,r in READER(LIBCHECK).items()}
    aa,_=G['attrs_for'](baseline);la,_=G['attrs_for'](live)
    bp,lp=G['actual_pins'](baseline,aa,lib),G['actual_pins'](live,la,lib)
    _,_,_,ba=G['graph'](baseline,aa);_,_,_,lat=G['graph'](live,la)
    pindiff=[{'pin':k,'before':bp.get(k),'after':lp.get(k),'beforeNets':ba(bp[k]['point'])['nets'] if k in bp else None,'afterNets':lat(lp[k]['point'])['nets'] if k in lp else None}
             for k in bp.keys()|lp.keys() if bp.get(k)!=lp.get(k) or (k in bp and k in lp and ba(bp[k]['point'])['nets']!=lat(lp[k]['point'])['nets'])]
    if pindiff:errors.append({'actualPhysicalPinOrNetChanges':pindiff})
    ncounts=dict(Counter(v['rule'] for v in norm))
    data={'schema':'adc10-labtool-page03-preapply-live-normalization-20261018-v1','passed':not errors,
        'baselinePath':str(baseline_path),'baselineSha256':sha(baseline_path),'livePath':str(live_path),'liveSha256':sha(live_path),
        'candidatePath':str(candidate_path),'candidateSha256':sha(candidate_path),
        'counts':{'baseline':len(baseline),'live':len(live),'candidate':len(candidate),'shared':len(baseline.keys()&live.keys()),'candidateAddedOnly':len(candidate_added),'proposedAdditionsOnlyRuntimePayload':len(live)+len(candidate_added)},
        'exactAbsentCheckpointOnlyRecords':[{'record':k,'body':v} for k,v in absent.items()],
        'allExistingComponentsPolysLinesWiresAndCanvasBodiesExact':not protected_diff,
        'exactGeometryBodyCount':len(protected),'actualSymbolPins':len(bp),'actualSymbolPinAndNetDifferences':pindiff,
        'normalizationCounts':ncounts,'normalizations':norm,'candidateOldRecordBodyChanges':candidate_base_diff,
        'candidateOldRecordDeletions':sorted(candidate_deleted),'errors':errors,
        'recommendedGuard':'Require exact shared keyset after excluding only these six frozen checkpoint-only identities; compare every other shared body with only the typed per-field normalizations enumerated here. Never relax electrical or geometry fields.',
        'recommendedPayload':'Do not overwrite frozen candidate/plan. In memory retain all1970 actual live records byte-for-body, append only658 records absent from stored baseline. Expected2628 records. This is exactly the reviewed additive design and preserves all live legacy display metadata; exclude the six stored-only records by not restoring them.',
        'nativeApiCalled':False,'nativeSourceModified':False,'candidateOrPlanModified':False}
    report_path=HERE/'independent-schematic-audit.json'
    report=json.loads(report_path.read_text(encoding='utf8'))
    report['preapplyPage03LiveComparison']=data
    report['passed']=report['passed'] and data['passed']
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':data['passed'],'report':str(report_path),'sha256':sha(report_path),'counts':data['counts'],
        'normalizationCounts':ncounts,'actualSymbolPins':len(bp),'errors':errors},indent=2))
    if errors:raise ValueError('Preapply page03 baseline normalization audit failed')


def final_native():
    report_path=HERE/'independent-schematic-audit.json'
    report=json.loads(report_path.read_text(encoding='utf8'))
    plan=json.loads(PLAN.read_text(encoding='utf8'))
    final_path=ROOT/'output/checkpoints/STM32H747_labtool_schematic_verified_20261018.epro2'
    before={d:body_rows(r) for d,r in READER(CHECK).items()}
    final={d:body_rows(r) for d,r in READER(final_path).items()}
    lib=final
    vdir=ROOT/'output/validation'
    accepted03=vdir/'native-adc10-labtool-page03-accepted-20261018.epru'
    nc03=vdir/'native-adc10-labtool-page03-nc-20261018.epru'
    accepted06=vdir/'native-adc10-labtool-page06-accepted-20261018.epru'
    old03=G['parse'](HERE/'power-baseline.epru')
    candidate03=G['parse'](HERE/'03_MCU_POWER_labtool_candidate.epru')
    live03=G['parse'](vdir/'native-adc10-labtool-page03-preapply-live-20261018.epru')
    append_expected={**live03,**{k:b for k,b in candidate03.items() if k not in old03}}
    r03=native_readback(append_expected,accepted03,lib,power=True)
    r06=native_readback(G['parse'](HERE/'06_ADC_TIMER_DAC_labtool_candidate.epru'),accepted06,lib)
    errors=[]
    if not r03['passed']:errors.append({'native03Readback':{'unclassified':r03['unclassifiedDifferences'],'pinErrors':r03['actualPinChanges']}})
    if not r06['passed']:errors.append({'native06Readback':{'unclassified':r06['unclassifiedDifferences'],'pinErrors':r06['actualPinChanges']}})
    a03,n03=G['parse'](accepted03),G['parse'](nc03)
    na,nrefs=G['attrs_for'](n03)
    ncpins=G['actual_pins'](n03,na,lib)
    u9=nrefs['U9'];sym=lib['SYMBOL',na[u9]['Symbol']];sa,_=G['attrs_for'](sym)
    ref_pin_ids={str(sa[rid]['Pin Number']):rid for (kind,rid),b in sym.items() if kind=='PIN'}
    nc_expected={u9+'-'+ref_pin_ids[n]:ncpins['U9',n]['point'] for n in ('1','3','7','8')}
    added_nc=n03.keys()-a03.keys()
    nc_details=[]
    for k in added_nc:
        b=n03[k];parent=b.get('parentId');point=(b.get('x'),b.get('y'))
        ok=k[0]=='ATTR' and b.get('key')=='NO_CONNECT' and b.get('value')=='yes' and parent in nc_expected and point==nc_expected[parent]
        nc_details.append({'record':k,'body':b,'valid':ok})
        if not ok:errors.append({'unexpectedNoConnectAddition':nc_details[-1]})
    nc_changed=[k for k in a03.keys()&n03.keys() if k[0]!='DOCHEAD' and a03[k]!=n03[k]]
    if len(added_nc)!=4 or nc_changed or a03.keys()-n03.keys():errors.append({'noConnectScopeNotExactlyFourAttrs':{'added':len(added_nc),'changed':nc_changed,'deleted':list(a03.keys()-n03.keys())}})
    def stripped(rows):return {k:b for k,b in rows.items() if k[0] not in {'DOCHEAD','CANVAS','ACTIVE_LAYER'}}
    targets={('SCH_PAGE','360993a3108b5759'),('SCH_PAGE','a07bf8e4331877a8')}
    new=set(final)-set(before)
    maps=[json.loads((HERE/'libraries/runtime-library-map.json').read_text(encoding='utf8')),
          json.loads((HERE/'libraries/reverse-protection/runtime-library-map.json').read_text(encoding='utf8'))]
    expected_new={(kind,info['uuid']) for m in maps for group,kind in [('symbols','SYMBOL'),('footprints','FOOTPRINT'),('devices','DEVICE')] for info in m[group].values()}
    if new!=expected_new or len(new)!=17 or set(before)-set(final):errors.append({'unexpectedDocumentMembership':{'new':sorted(new),'expected':sorted(expected_new),'removed':sorted(set(before)-set(final))}})
    changed_other=[]
    for d in set(before)&set(final)-targets:
        if stripped(before[d])!=stripped(final[d]):changed_other.append(d)
    if changed_other:errors.append({'nonTargetDocumentBodyChanges':changed_other})
    library_at_import={d:body_rows(r) for d,r in READER(LIBCHECK).items()}
    changed_newlibs=[d for d in expected_new if stripped(library_at_import[d])!=stripped(final[d])]
    if changed_newlibs:errors.append({'newImportedLibrariesChangedAfterImport':changed_newlibs})
    # Native canvas export omits persisted page-tree/placeholder records.  The
    # native decoder also regenerates display caches; electrical content below
    # is checked independently at every actual saved SYMBOL pin.
    page_checks=[];before_uids={};after_uids={};original_nets={};actual_nets={}
    nettext=(vdir/'native-adc10-labtool_schematic-Protel2-20261018.net').read_text(encoding='utf-8-sig')
    parser=runpy.run_path(str(ROOT/'scripts/verify-native-netlist.py'))['parse_protel2']
    nodes=parser(nettext);export={(p['ref'],str(p['number'])):p['net'] for p in nodes}
    blocks={}
    for block in __import__('re').findall(r'(?ms)^\[\s*\n(.*?)^\]',nettext):
        lines=[x.strip() for x in block.splitlines()]
        while lines and not lines[0]:lines.pop(0)
        while lines and (not lines[-1] or lines[-1]=='*'):lines.pop()
        values={lines[i]:lines[i+1] for i in range(0,len(lines)-1,2)}
        ref=values.get('DESIGNATOR')
        if not ref or ref in blocks:errors.append({'duplicateOrMissingNetlistComponentRef':ref})
        blocks[ref]=values
    physical_refs=set(blocks)
    for state,snapshot,uids,nets_out in [('before',before,before_uids,original_nets),('final',final,after_uids,actual_nets)]:
        for d,rows in snapshot.items():
            if d[0]!='SCH_PAGE':continue
            aa,refs=G['attrs_for'](rows)
            pp=G['actual_pins'](rows,aa,lib)
            _,islands,nn,at=G['graph'](rows,aa)
            mixed=[sorted(n) for n in nn.values() if len(n)>1]
            if state=='final' and mixed:errors.append({'savedPageMixedNet':{'page':d[1],'nets':mixed}})
            for ref,cid in refs.items():
                if aa[cid].get('Convert to PCB')=='yes':
                    uid=aa[cid].get('Unique ID')
                    if ref in uids and uids[ref]!=uid:errors.append({'splitPartUidConflict':[state,ref]})
                    uids[ref]=uid
            for key,p in pp.items():
                if key[0] not in physical_refs:continue
                ns=at(p['point'])['nets']
                if len(ns)>1:errors.append({'actualPinMixedNets':{'state':state,'pin':key,'nets':ns}})
                if ns:
                    if key in nets_out and nets_out[key]!=ns[0]:errors.append({'duplicatePhysicalPinNetConflict':[state,key,nets_out[key],ns[0]]})
                    nets_out[key]=ns[0]
            if state=='final':page_checks.append({'page':d[1],'actualSymbolPins':len(pp),'wireIslands':len(islands),'mixedNetIslands':mixed})
    uid_diffs=[{'ref':ref,'before':uid,'after':after_uids.get(ref)} for ref,uid in before_uids.items() if uid!=after_uids.get(ref)]
    if len(before_uids)!=354 or len(after_uids)!=437 or len(set(after_uids.values()))!=437 or uid_diffs:errors.append({'physicalUidContract':{'before':len(before_uids),'after':len(after_uids),'differences':uid_diffs}})
    if len(export)!=len(nodes) or len(export)!=1342 or export!=actual_nets:errors.append({'fullNativeNetlistPinMismatch':{'exportCount':len(export),'sourceCount':len(actual_nets),'missing':sorted(actual_nets.keys()-export.keys()),'added':sorted(export.keys()-actual_nets.keys()),'changed':[{'pin':k,'source':actual_nets[k],'netlist':export[k]} for k in actual_nets.keys()&export.keys() if actual_nets[k]!=export[k]]}})
    expected={**expected_channels(),**expected_power()}
    target_pin_mismatch=[]
    for ref,pns in expected.items():
        for number,net in pns.items():
            got=actual_nets.get((ref,number))
            if got!=net:target_pin_mismatch.append({'ref':ref,'pin':number,'expected':net,'actual':got})
    if target_pin_mismatch:errors.append({'savedTargetPinContractMismatch':target_pin_mismatch})
    unrelated=[{'pin':k,'before':n,'after':actual_nets.get(k)} for k,n in original_nets.items() if k[0] not in expected and actual_nets.get(k)!=n]
    if unrelated:errors.append({'nonTargetOriginalConnectedPinsChanged':unrelated})
    block_errors=[{'ref':r,'reason':'source UID differs netlist header'} for r,v in blocks.items() if v.get('Unique ID')!=after_uids.get(r)]
    if len(blocks)!=437 or block_errors:errors.append({'netlistPhysicalComponents':{'count':len(blocks),'errors':block_errors}})
    erc=json.loads((vdir/'native-adc10-labtool_schematic-erc-20261018.json').read_text(encoding='utf8'))
    if erc.get('passed') is not True or erc.get('logs'):errors.append({'ercNotPassed':erc})
    semantic_checks=[]
    def source_signature(rows):
        aa,_=G['attrs_for'](rows)
        result={}
        for k,b in rows.items():
            if k[0] in {'DOCHEAD','CANVAS','ACTIVE_LAYER','META','ELE_PLACEHOLDER'}:continue
            x=copy.deepcopy(b)
            if k[0]=='POLY':
                for p in x.get('points',[]):p.pop('hashed',None)
            if k[0]=='COMPONENT' and 'SymbolName' in x.get('attrs',{}):
                packed=json.loads(x['attrs']['SymbolName'])
                if packed.get('uuid')==aa[k[1]].get('Symbol'):x['attrs'].pop('SymbolName')
            if k[0]=='ATTR':
                for f in ('zIndex','strikeout','fillColor','groupId'):x.pop(f,None)
                for f in ('fontWeight','italic','underline'):
                    if x.get(f) in (None,False):x.pop(f,None)
            if k[0]=='LINE' and x.get('strokeWidth') in (None,.6):x.pop('strokeWidth',None)
            if k[0]=='TEXT' and x.get('fillColor') in (None,x.get('color')):x.pop('fillColor',None)
            if k[0]=='RECT':
                for f in ('partId','groupId'):
                    if x.get(f) in (None,''):x.pop(f,None)
                if x.get('strokeColor') in (None,''):x['strokeColor']=None
            def geometry(v,key=None):
                if isinstance(v,dict):return {kk:geometry(vv,kk) for kk,vv in v.items()}
                if isinstance(v,list):return [geometry(vv,key) for vv in v]
                if key in {'x','y','startX','startY','endX','endY','dotX1','dotY1','dotX2','dotY2'} and isinstance(v,(int,float)):return round(v,9)
                return v
            result[k]=geometry(x)
        return result
    for page,path in [('360993a3108b5759',nc03),('a07bf8e4331877a8',accepted06)]:
        source=source_signature(G['parse'](path));stored=source_signature(final['SCH_PAGE',page])
        diffs=[{'record':k,'fields':[f for f in source.get(k,{}).keys()|stored.get(k,{}).keys() if source.get(k,{}).get(f)!=stored.get(k,{}).get(f)]} for k in source.keys()|stored.keys() if source.get(k)!=stored.get(k)]
        semantic_checks.append({'page':page,'source':str(path),'sourceSha256':sha(path),'sourceSemanticRecords':len(source),'storedSemanticRecords':len(stored),'differences':diffs,'passed':not diffs})
        if diffs:errors.append({'nativeSourceToSavedCheckpointSemanticDifference':semantic_checks[-1]})
    data={'schema':'adc10-labtool-final-native-schematic-full-checkpoint-audit-20261018-v1','passed':not errors,
        'checkpoint':str(final_path),'checkpointSha256':sha(final_path),'baselineCheckpointSha256':sha(CHECK),
        'documentCounts':{'before':len(before),'final':len(final),'newLibraries':len(new),'nonTargetExistingPreserved':len(before)-len(targets)},
        'newLibraryCounts':dict(Counter(d[0] for d in new)),'nonTargetDocumentBodyChanges':changed_other,'newLibraryBodyChanges':changed_newlibs,
        'pcbBodyUnchangedBeforeEco':all(stripped(before[d])==stripped(final[d]) for d in before if d[0]=='PCB'),
        'otherThreeSchematicPagesUnchanged':all(stripped(before[d])==stripped(final[d]) for d in before if d[0]=='SCH_PAGE' and d not in targets),
        'native03Readback':r03,'native06Readback':r06,'refNoConnectMarkers':nc_details,'noConnectOtherBodyChanges':nc_changed,
        'nativeSourceToSavedCheckpointComparisons':semantic_checks,
        'fullPhysicalPartsBefore':len(before_uids),'fullPhysicalPartsAfter':len(after_uids),'all354OriginalPhysicalUidsPreserved':not uid_diffs,
        'fullConnectedPinsNativeNetlist':len(export),'fullConnectedPinsActualSavedSource':len(actual_nets),'netlistMatchesAllActualSourcePins':export==actual_nets,
        'savedTargetPinMismatches':target_pin_mismatch,'nonTargetOriginalConnectedPinChanges':unrelated,'pages':page_checks,
        'nativeErcPassed':erc.get('passed'),'netlistSha256':sha(vdir/'native-adc10-labtool_schematic-Protel2-20261018.net'),
        'errors':errors,'nativeApiCalls':0,'pcbEcoApplied':False,'manufacturingApproved':False}
    report['finalNativeSchematic']=data
    report['passed']=not report.get('errors') and report.get('preapplyPage03LiveComparison',{}).get('passed',True) and data['passed']
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':data['passed'],'report':str(report_path),'sha256':sha(report_path),'documentCounts':data['documentCounts'],
        'parts':len(after_uids),'pins':len(export),'native03Unclassified':r03['unclassifiedDifferences'],'errors':errors},indent=2))
    if errors:raise ValueError('Final native schematic audit failed')


def main():
    plan=json.loads(PLAN.read_text(encoding='utf8'))
    frozen_plan_sha=sha(PLAN)
    lib={d:body_rows(r) for d,r in READER(LIBCHECK).items()}
    original={d:body_rows(r) for d,r in READER(CHECK).items()}
    fresh_adc=ROOT/'output/validation/native-adc10-sch-labtool_before-20261018.epru'
    original['SCH_PAGE','a07bf8e4331877a8']=G['parse'](fresh_adc)
    tests,errors,warnings=[],[],[]
    def check(ok,name,detail=None):
        row={'test':name,'passed':bool(ok)}
        if detail is not None: row['detail']=detail
        tests.append(row)
        if not ok: errors.append(row)
    check(plan['checkpointSha256']==sha(CHECK),'source checkpoint SHA agrees')
    expected={**expected_channels(),**expected_power()}
    check(set(plan['allPinContracts'])==set(expected),'independent177 target part set agrees root plan')
    root_diff=[]
    for ref,contract in expected.items():
        if plan['allPinContracts'].get(ref)!=contract:
            root_diff.append({'ref':ref,'root':plan['allPinContracts'].get(ref),'independent':contract})
    check(not root_diff,'root pin contract matches independent electrical pin contract',root_diff)
    page_reports=[]
    native_accepted=None
    all_target_data={}
    full_before_parts,full_after_parts={},{}
    before_uids,after_uids={},{}
    global_original_pins={}
    global_new_pins={}
    current_pages={p['pageUuid']:p for p in plan['pages']}
    for doc_id,base in original.items():
        if doc_id[0]!='SCH_PAGE': continue
        old_a,old_refs=G['attrs_for'](base)
        old_pins=G['actual_pins'](base,old_a,lib)
        old_seg,old_islands,old_nets,old_at=G['graph'](base,old_a)
        for ref,cid in old_refs.items():
            if old_a[cid].get('Convert to PCB')=='yes':
                full_before_parts[ref]=(doc_id[1],cid)
                before_uids[ref]=old_a[cid].get('Unique ID')
        if doc_id[1] not in current_pages:
            for key,p in old_pins.items():
                if old_a[old_refs[key[0]]].get('Convert to PCB')=='yes':
                    global_original_pins[key]=old_at(p['point'])['nets']
                    global_new_pins[key]=old_at(p['point'])['nets']
            full_after_parts.update({r:v for r,v in full_before_parts.items() if v[0]==doc_id[1]})
            after_uids.update({r:before_uids[r] for r,v in full_before_parts.items() if v[0]==doc_id[1]})
            continue
        pplan=current_pages[doc_id[1]]
        if pplan.get('baselinePath'):
            plan_base=G['parse'](Path(pplan['baselinePath']))
            check(sha(Path(pplan['baselinePath']))==pplan['baselineSha256'],'frozen plan baseline SHA '+doc_id[1])
            canonical={k:b for k,b in base.items() if k[0] not in {'DOCHEAD','CANVAS','ACTIVE_LAYER'}}
            check(canonical=={k:b for k,b in plan_base.items() if k[0] not in {'DOCHEAD','CANVAS','ACTIVE_LAYER'}},'plan baseline has only view differences from independently captured original '+doc_id[1])
            base=plan_base
        path=Path(pplan['candidatePath'])
        candidate_hash=sha(path)
        check(candidate_hash==pplan['candidateSha256'],'candidate SHA '+doc_id[1])
        rows=G['parse'](path)
        a,refs=G['attrs_for'](rows)
        pins=G['actual_pins'](rows,a,lib)
        seg,islands,nets,at=G['graph'](rows,a)
        if doc_id[1]=='a07bf8e4331877a8':
            actual_path=ROOT/'output/validation/native-adc10-labtool-page06-accepted-20261018.epru'
            native_accepted=native_readback(rows,actual_path,lib)
            check(native_accepted['passed'],'actual accepted page06 preserves every non-view semantic field under exact typed defaults',
                {'unclassified':native_accepted['unclassifiedDifferences'],'pinErrors':native_accepted['actualPinChanges'],'mixedNet':native_accepted['actualMixedNetIslands']})
        check(len(refs)==len([v for v in a.values() if v.get('Designator')]),'unique reference '+doc_id[1])
        mixed=[{'island':i,'nets':sorted(ns),'segments':ss} for i,ss in islands.items() if len(ns:=nets[i])>1]
        check(not mixed,'no geometric mixed-net short '+doc_id[1],mixed)
        check(all(('WIRE',v['lineGroup']) in rows for (k,rid),v in rows.items() if k=='LINE'),'all LINE wire owners exist '+doc_id[1])
        touched_islands={i for p in pins.values() for i in at(p['point'])['islands']}
        new_wire_ids={rid for kind,rid in rows.keys()-base.keys() if kind=='WIRE'}
        unanchored=[{'island':i,'nets':sorted(nets[i]),'lines':[s['id'] for s in ss]}
                    for i,ss in islands.items() if any(s['wire'] in new_wire_ids for s in ss) and i not in touched_islands]
        check(not unanchored,'no newly added wire island dangling from all actual symbol pins '+doc_id[1],unanchored)
        pdata=[]
        for (ref,n),p in pins.items():
            actual=at(p['point'])
            if ref in expected:
                goal=expected[ref].get(n,'MISSING_INDEPENDENT_PIN')
                check(n in expected[ref],'all target physical pin numbers included '+ref+'.'+n)
                ok=(not actual['islands']) if goal is None else len(actual['islands'])==1 and actual['nets']==[goal]
                check(ok,'actual target pin '+ref+'.'+n,{'point':p['point'],'expected':goal,**actual})
                all_target_data[ref,n]={'page':doc_id[1],**p,**actual,'expected':goal}
                pdata.append({'ref':ref,'number':n,**p,**actual,'expected':goal})
            if a[refs[ref]].get('Convert to PCB')=='yes':
                global_new_pins[ref,n]=actual['nets']
        for key,p in old_pins.items():
            if old_a[old_refs[key[0]]].get('Convert to PCB')=='yes':global_original_pins[key]=old_at(p['point'])['nets']
        for ref,cid in refs.items():
            if a[cid].get('Convert to PCB')=='yes':
                check(ref not in full_after_parts,'global unique physical reference '+ref)
                full_after_parts[ref]=(doc_id[1],cid)
                after_uids[ref]=a[cid].get('Unique ID')
        untouched_pin_diffs=[]
        for key,p in old_pins.items():
            ref,n=key
            if ref in expected or old_a[old_refs[ref]].get('Convert to PCB')!='yes':continue
            if key not in pins or at(pins[key]['point'])['nets']!=old_at(p['point'])['nets']:
                untouched_pin_diffs.append({'ref':ref,'number':n,'oldPoint':p['point'],'newPoint':pins.get(key,{}).get('point'),'before':old_at(p['point'])['nets'],'after':at(pins[key]['point'])['nets'] if key in pins else 'MISSING'})
        check(not untouched_pin_diffs,'all non-target original pin nets preserved '+doc_id[1],untouched_pin_diffs)
        deleted=base.keys()-rows.keys()
        changed={k for k in base.keys()&rows.keys() if base[k]!=rows[k]}
        added=rows.keys()-base.keys()
        delta_mismatches={name:sorted(set(map(tuple,pplan[name]))^actual,key=str) for name,actual in [('changed',changed),('deleted',deleted),('added',added)]}
        check(not any(delta_mismatches.values()),'plan literal delta membership exact '+doc_id[1],delta_mismatches)
        if doc_id[1]=='360993a3108b5759':check(not changed and not deleted,'all original power page records preserved literally')
        role_values={ref:a[cid].get('Value') for ref,cid in refs.items() if ref in expected}
        page_reports.append({'page':doc_id[1],'candidatePath':str(path),'candidateSha256':candidate_hash,
            'records':len(rows),'originalLiteralExactRecords':sum(k in rows and rows[k]==b for k,b in base.items()),
            'changed':len(changed),'deleted':len(deleted),'added':len(added),'physicalWireIslandCount':len(islands),
            'mixedNetIslands':mixed,'targetPins':pdata,'nonTargetPinDifferences':untouched_pin_diffs,'roleValues':role_values})
    check(set((r,n) for r,ns in expected.items() for n in ns)==set(all_target_data),'all independent target pins exist exactly once across two pages')
    # The signal chain must be literal wires within a channel, not label jumps.
    for j,adc,rb,ri,rs,c,cp,cd in CHANNELS:
        for name in ['RAW','FILTER','BUF','SUM','DRV','ADC']:
            net=adc if name=='ADC' else f'ADC_J{j}_{name}'
            roots={tuple(p['islands']) for p in all_target_data.values() if p['expected']==net}
            check(len(roots)==1 and len(next(iter(roots),()))==1,f'J{j} {name} one real geometric island',sorted(roots))
    # Compare component attributes/pins to the true runtime SYMBOL, not plan text.
    power_values=next(p['roleValues'] for p in page_reports if p['page']=='360993a3108b5759')
    adc_values=next(p['roleValues'] for p in page_reports if p['page']=='a07bf8e4331877a8')
    channel_math=[]
    for i,(j,adc,rb,ri,rs,c,cp,cd) in enumerate(CHANNELS):
        gain=-rv(adc_values[f'R{187+i}'])/rv(adc_values[f'R{rb}'])
        check(math.isclose(gain,-.7,rel_tol=1e-12),'actual resistor gain J'+str(j),gain)
        check(adc_values[f'U{20+i}']=='OPA189IDBVR' and adc_values[f'U{10+i}']=='OPA320AIDBVR','correct actual opamp part roles J'+str(j))
        check(rv(adc_values[f'R{177+i}'])==100000,'SMA pulldown100k J'+str(j))
        check(rv(adc_values[f'R{ri}'])==3320 and adc_values[f'C{cp}']=='10nF','input RC3.32k/10nF J'+str(j))
        check(adc_values[f'C{122+i*3}']=='10nF','parallel Rf capacitor10nF J'+str(j))
        check(rv(adc_values[f'R{rs}'])==47 and adc_values[f'C{c}']=='10nF','ADC reservoir47ohm/10nF J'+str(j))
        vplus=2.5*rv(power_values['R203'])/(rv(power_values['R202'])+rv(power_values['R203']))
        offset=(1-gain)*vplus
        channel_math.append({'sma':'J'+str(j),'gainNominal':gain,'offsetNominalV':offset,'adcAtMinus2V':offset-2*gain,'adcAtPlus2V':offset+2*gain,
            'openSmaIdealV':0,'openAdcIdealV':offset,'inputFilterPoleWith50OhmSourceHz':1/(2*math.pi*(3320+50*100000/100050)*1e-8),
            'feedbackSignalPoleHz':1/(2*math.pi*rv(adc_values[f'R{187+i}'])*1e-8)})
    vneg=-1.186*(1+rv(power_values['R198'])/rv(power_values['R199']))
    check(math.isclose(vneg,-3.01244,abs_tol=1e-9),'actual negative LDO divider voltage',vneg)
    # Verify opamp supply electrical types from actual imported SYMBOLs.
    supply_types=[]
    for ref in [f'U{x}' for x in range(20,30)]+['U32']:
        pin=all_target_data[ref,'2']
        sr=lib['SYMBOL',pin['symbol']]
        sa,_=G['attrs_for'](sr)
        matched=[sa[rid].get('Pin Type') for (kind,rid),b in sr.items() if kind=='PIN' and str(sa[rid].get('Pin Number'))=='2']
        check(matched==['Power'],'OPA189 V- Pin Type is Power '+ref,matched)
        supply_types.append({'ref':ref,'negativeSupplyPinType':matched})
    check(all(not all_target_data['U9',n]['islands'] for n in ('1','3','7','8')),'REF5025 DNC1/8 and unused TEMP3/NC7 truly unconnected')
    check(not set(full_before_parts)-set(full_after_parts),'all original physical refs retained including moved REF components')
    check(len(full_after_parts)==437,'full physical part count354 to437',len(full_after_parts))
    check(all(before_uids.values()) and all(after_uids.values()),'all old and proposed physical components have Unique ID')
    check(len(set(after_uids.values()))==len(after_uids),'all437 proposed physical Unique IDs globally unique')
    uid_diffs=[{'ref':r,'before':u,'after':after_uids.get(r)} for r,u in before_uids.items() if u!=after_uids.get(r)]
    check(not uid_diffs,'all354 original physical Unique IDs preserved for guarded PCB ECO',uid_diffs)
    warnings.append('47ohm/10nF ideal full-scale16-bit half-LSB RC settling is5.538us; text>=5us is only a starting value, not guaranteed16-bit hardware acquisition.')
    warnings.append('TPS723 reverse-current/power-down protection must be reviewed; local output capacitance exceeds input capacitance. A negative-LDO bypass diode, if fitted, has anode IN and cathode OUT.')
    warnings.append('TPS723 Cff10nF x R19815.4k =154us, above TI <50us no-startup-increase guideline; additional startup time is possible.')
    warnings.append('OPA189 requires4.5V minimum total supply; single-supply offset follower and +2V common-mode require loaded +5V_AFE>=4.5V. Include feed-resistor drop and source tolerance in power-budget validation.')
    warnings.append('MCU VDDA/VREF+ remain on original+3V3 domain; removing SMA bias injection does not independently eliminate ADC reference noise.')
    check(sha(PLAN)==frozen_plan_sha,'plan remained frozen during independent audit')
    report={'schema':'adc10-labtool-independent-schematic-audit-20261018-v1','passed':not errors,
        'planSha256':frozen_plan_sha,'checkpointSha256':sha(CHECK),'libraryCheckpointSha256':sha(LIBCHECK),
        'freshAdcBaseline':str(fresh_adc),'freshAdcBaselineSha256':sha(fresh_adc),
        'method':'Actual runtime SYMBOL pin transforms plus literal LINE endpoint-on-segment/T joins. NET-name equality never joins physical islands; interior-only crossings are not joined.',
        'independentContractPartCount':len(expected),'independentTargetPinCount':len(all_target_data),
        'rootContractDifferences':root_diff,'fullPhysicalPartsBefore':len(full_before_parts),'fullPhysicalPartsAfter':len(full_after_parts),
        'originalPhysicalUniqueIdsPreserved':not uid_diffs,'physicalUniqueIdDifferences':uid_diffs,
        'fullPhysicalConnectedPinsBefore':sum(bool(v) for v in global_original_pins.values()),
        'fullPhysicalConnectedPinsAfter':sum(bool(v) for v in global_new_pins.values()),
        'independentExpectedContract':expected,'pages':page_reports,'channelMath':channel_math,'negativeLdoNominalV':vneg,
        'nativeAcceptedPage06':native_accepted,
        'idealAdcHalfLsb16BitSettlingUs':47*1e-8*math.log(2**17)*1e6,'supplyPinTypes':supply_types,
        'warnings':warnings,'errors':errors,'tests':tests,'nativeApiCalls':0,'nativeFilesModified':0,'pcbModified':False,'manufacturingApproved':False}
    path=HERE/'independent-schematic-audit.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':report['passed'],'report':str(path),'sha256':sha(path),'errorCount':len(errors),
        'rootContractDifferences':root_diff,'mixedNetIslands':[{ 'page':p['page'],'nets':[v['nets'] for v in p['mixedNetIslands']]} for p in page_reports],
        'failedTests':[e['test'] for e in errors],'fullPhysicalPartsAfter':len(full_after_parts),'fullConnectedPinsAfter':report['fullPhysicalConnectedPinsAfter']},ensure_ascii=False,indent=2))
    if errors:raise ValueError('Independent labtool schematic candidate audit failed')


if __name__=='__main__':
    final_native() if '--final-native' in sys.argv else preapply_power_live() if '--preapply03-live' in sys.argv else main()
