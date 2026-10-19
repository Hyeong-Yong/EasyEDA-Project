"""Independent offline QA: actual SYMBOL pin transforms and LINE topology.

No live API, native project writes, or library changes. Equal NET labels never
join geometric islands. All outputs are diagnostic, not fabrication approval.
"""
import copy
import hashlib
import json
import math
import re
import runpy
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'output/validation/native-adc10-sch-before-20261017.epru'
CANDIDATE = HERE / '06_ADC_TIMER_DAC_adc10_candidate.epru'
CHECKPOINT = ROOT / 'output/checkpoints/STM32H747_before_adc10_20261017.epro2'
NETLIST = ROOT / 'output/validation/native-adc10-before-Protel2-20261017.net'
BASE_SHA = '885b9eaa95591d23a652d521fa0c785f63d5eb836f148ad16f58402825c9cd45'
CANDIDATE_SHA = '2465cf49c7a91d2809a6aa050d1ca9fcbfbdebfefc42731f4fb43e02f7d842eb'
DNP_REFS = {'R158','R159','R160','R173','R174','R175','R176'}
TOL = 1e-5


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path):
    out = {}
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        if not raw.strip(): continue
        h, b = raw.split('||', 1)
        h, b = json.loads(h), json.loads(b.rstrip('|'))
        k = h['type'], h.get('id')
        assert k not in out, k
        out[k] = b
    return out


def libraries():
    with zipfile.ZipFile(CHECKPOINT) as z:
        data = z.read(next(n for n in z.namelist() if n.endswith('.epru'))).decode('utf-8-sig')
    out, current = {}, None
    for raw in data.splitlines():
        if not raw.strip(): continue
        h, payload = raw.split('||', 1)
        h, payload = json.loads(h), payload.rstrip('|')
        b = json.loads(payload) if payload else None
        if h['type'] == 'DOCHEAD':
            current = b['docType'], b['uuid']
            out.setdefault(current, {})
        k = h['type'], h.get('id')
        prev = out[current].get(k)
        if prev is None or h.get('ticket', 0) >= prev[0].get('ticket', 0):
            out[current][k] = h, b
    return {doc:{k:b for k,(h,b) in rows.items() if isinstance(b,dict)} for doc,rows in out.items()}


def attrs_for(rows):
    a = defaultdict(dict)
    for (kind,rid), b in rows.items():
        if kind == 'ATTR': a[b.get('parentId')][b.get('key')] = b.get('value')
    refs = {v['Designator']:rid for rid,v in a.items() if v.get('Designator')}
    return a, refs


def on(p,a,b):
    cross = (p[0]-a[0])*(b[1]-a[1])-(p[1]-a[1])*(b[0]-a[0])
    return abs(cross) <= TOL*max(1,math.dist(a,b)) and min(a[0],b[0])-TOL <= p[0] <= max(a[0],b[0])+TOL and min(a[1],b[1])-TOL <= p[1] <= max(a[1],b[1])+TOL


def actual_pins(rows, a, lib):
    out = {}
    for (kind,cid), c in rows.items():
        if kind != 'COMPONENT': continue
        ref = a[cid].get('Designator')
        if not ref: continue
        symbol = lib['SYMBOL',a[cid]['Symbol']]
        sa,_ = attrs_for(symbol)
        t = math.radians(c['rotation'])
        for (sk,sid),p in symbol.items():
            if sk != 'PIN' or p.get('partId',c['partId']) != c['partId']: continue
            number = str(sa[sid]['Pin Number'])
            x,y = p['x']*math.cos(t)+p['y']*math.sin(t),-p['x']*math.sin(t)+p['y']*math.cos(t)
            if c.get('isMirror'): x=-x
            key = ref,number
            assert key not in out, key
            out[key] = {'point':(round(c['x']+x,6),round(c['y']+y,6)), 'pinName':sa[sid].get('Pin Name'), 'symbol':a[cid]['Symbol']}
    return out


def graph(rows,a):
    seg = []
    for (kind,rid),b in rows.items():
        if kind != 'LINE': continue
        net = a[b['lineGroup']].get('NET')
        assert net is not None, (rid,'missing wire NET')
        seg.append({'id':rid,'wire':b['lineGroup'],'net':net,'a':(b['startX'],b['startY']),'b':(b['endX'],b['endY'])})
    parent=list(range(len(seg)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    def union(i,j): parent[find(j)]=find(i)
    for i,s in enumerate(seg):
        for j in range(i):
            q=seg[j]
            if any(on(p,q['a'],q['b']) for p in (s['a'],s['b'])) or any(on(p,s['a'],s['b']) for p in (q['a'],q['b'])): union(i,j)
    islands=defaultdict(list)
    for i,s in enumerate(seg): islands[find(i)].append(s)
    nets={i:set(s['net'] for s in ss) for i,ss in islands.items()}
    def at(point):
        touch=sorted({find(i) for i,s in enumerate(seg) if on(point,s['a'],s['b'])})
        return {'islands':touch,'nets':sorted({n for i in touch for n in nets[i]})}
    return seg,islands,nets,at


def geometry_points(k,b):
    pts=[]
    if b.get('x') is not None and b.get('y') is not None: pts.append((b['x'],b['y']))
    if k[0]=='LINE': pts.extend([(b['startX'],b['startY']),(b['endX'],b['endY'])])
    if k[0]=='POLY': pts.extend((p['x'],p['y']) for p in b.get('points',[]))
    return pts


def main():
    errors,tests=[],[]
    def check(ok,name,detail=None):
        row={'test':name,'passed':bool(ok)}
        if detail is not None: row['detail']=detail
        tests.append(row)
        if not ok: errors.append(row)
    check(sha(BASE)==BASE_SHA,'fresh baseline SHA frozen')
    check(sha(CANDIDATE)==CANDIDATE_SHA,'final proposed candidate SHA frozen')
    before,rows=parse(BASE),parse(CANDIDATE)
    olda,oldrefs=attrs_for(before)
    a,refs=attrs_for(rows)
    lib=libraries()
    oldpins,pins=actual_pins(before,olda,lib),actual_pins(rows,a,lib)
    check(len(refs)==len([v for v in a.values() if v.get('Designator')]),'unique page reference designators')

    # Explicit independent channel table, not generated from the candidate plan.
    definitions=[
      ('J2','R137','R140','R141','C80','U10','C97','C100','TP1','ADC1_INP0',1,1),
      ('J3','R138','R142','R143','C81','U11','C98','C101','TP2','ADC1_INP1',1,2),
      ('J4','R139','R144','R145','C82','U12','C99','C102','TP3','ADC1_INP16',1,3),
      ('J5','R149','R152','R153','C86','U13','C106','C113','TP4','ADC2_INP3',2,1),
      ('J6','R150','R154','R155','C87','U14','C107','C114','TP5','ADC2_INP12',2,2),
      ('J7','R151','R156','R157','C88','U15','C108','C115','TP6','ADC2_INP13',2,3),
      ('J8','R161','R165','R166','C93','U16','C109','C116','TP7','ADC3_INP2',3,1),
      ('J9','R162','R167','R168','C94','U17','C110','C117','TP8','ADC3_INP6',3,2),
      ('J10','R163','R169','R170','C95','U18','C111','C118','TP9','ADC3_INP7',3,3),
      ('J11','R164','R171','R172','C96','U19','C112','C119','TP10','ADC3_INP8',3,4)]
    parse_net=runpy.run_path(str(ROOT/'scripts/verify-native-netlist.py'))['parse_protel2']
    old_nodes=parse_net(NETLIST.read_text(encoding='utf-8-sig'))
    original={(p['ref'],str(p['number'])):p['net'] for p in old_nodes}
    check(len(original)==len(old_nodes)==1087,'baseline full native netlist exactly1087 unique connected pins')
    expected={k:v for k,v in original.items() if k[0] not in DNP_REFS}
    explicit={}
    groups_by_channel=[]
    for j,rb,ri,rs,co,u,cp,cd,tp,adc,bank,n in definitions:
        pre,drv=f'ADC{bank}_PRE{n}',f'ADC{bank}_DRV{n}'
        groups={'raw':[(j,'1'),(ri,'1')], 'pre':[(ri,'2'),(rb,'1'),(u,'3'),(cp,'1')],
          'driver':[(u,'1'),(u,'4'),(rs,'1')], 'adc':[(rs,'2'),(co,'1'),(tp,'1')],
          'vplus':[(u,'5'),(cd,'1')], 'bias':[(rb,'2')],
          'ground':[(j,'2'),(u,'2'),(cp,'2'),(co,'2'),(cd,'2')]}
        labels={'raw':original[j,'1'],'pre':pre,'driver':drv,'adc':adc,'vplus':'+3V3','bias':'ADC_BIAS_2V5','ground':'GND'}
        for g,ks in groups.items():
            for k in ks: explicit[k]=labels[g]
        groups_by_channel.append((j,bank,n,groups,labels))
    expected.update(explicit)
    removed=sorted(original.keys()-expected.keys())
    added=sorted(expected.keys()-original.keys())
    rewired=[{'ref':r,'number':n,'before':original[r,n],'expected':expected[r,n]} for r,n in sorted(original.keys()&expected.keys()) if original[r,n]!=expected[r,n]]
    check(len(expected)==1136,'independent expected full netlist1136 pins')
    check(removed==sorted((r,n) for r in DNP_REFS for n in ('1','2')),'exact14 DNP pins removed')
    check(len(added)==63 and len(rewired)==28,'exact63 new pins and28 existing changed pins')
    contract={'schema':'adc10-independent-full-pin-contract-20261017-v1','baselineNetlistPath':str(NETLIST),'baselineNetlistSha256':sha(NETLIST),
      'candidatePath':str(CANDIDATE),'candidateSha256':sha(CANDIDATE),'expectedConnectedPins':1136,'expectedPhysicalParts':354,
      'removedPins':[{'ref':r,'number':n,'before':original[r,n]} for r,n in removed],
      'changedExistingPins':rewired,'newPins':[{'ref':r,'number':n,'net':expected[r,n]} for r,n in added],
      'expectedPins':[{'ref':r,'number':n,'net':v} for (r,n),v in sorted(expected.items())],
      'scope':'Offline proposed contract only; native ERC, export, save/reopen comparison required. No PCB ECO or fabrication approval.'}
    contract_path=HERE/'independent-adc10-expected-full-pin-contract-20261017.json'
    contract_path.write_text(json.dumps(contract,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'earlyContractPath':str(contract_path),'sha256':sha(contract_path),'pins':len(expected),'rewired':len(rewired),'added':len(added),'removed':len(removed)}),flush=True)

    seg,islands,nets,at=graph(rows,a)
    check(all(len(v)==1 for v in nets.values()),'no physical mixed-net island', {str(k):sorted(v) for k,v in nets.items() if len(v)!=1})
    check(all(('WIRE',b['lineGroup']) in rows for (k,rid),b in rows.items() if k=='LINE'),'all LINE owners exist')
    page_data=[]
    for key,data in pins.items():
        actual=at(data['point'])
        if key in expected:
            check(len(actual['islands'])==1 and actual['nets']==[expected[key]],'actual physical pin '+'.'.join(key),{'point':data['point'],'expected':expected[key],**actual})
            page_data.append({'ref':key[0],'number':key[1],**data,**actual,'expected':expected[key]})
        elif a[refs[key[0]]].get('Convert to PCB')=='yes':
            check(not actual['islands'],'unnetlisted pin remains physically unconnected '+'.'.join(key),actual)
    expected_page={k for k in expected if k[0] in refs}
    check(expected_page <= pins.keys(),'every expected page pin exists in actual SYMBOL')
    check(len(page_data)==len(expected_page),'all expected connected page pins checked')
    pdata={(p['ref'],p['number']):p for p in page_data}
    channel_reports=[]
    for idx,(j,bank,n,groups,labels) in enumerate(groups_by_channel):
        roots={}
        for g,ks in groups.items():
            ii=sorted({v for k in ks for v in pdata[k]['islands']})
            if g not in ('ground',): check(len(ii)==1,f'{j} {g} one real geometric island',ii)
            roots[g]=ii
        signal=[roots[g][0] for g in ('raw','pre','driver','adc')]
        check(len(set(signal))==4,f'{j} raw/pre/driver/ADC four distinct real islands')
        for g in ('pre','driver'):
            roots_with_name=[i for i,nn in nets.items() if labels[g] in nn]
            check(len(roots_with_name)==1,f'{j} {g} has no name-only disconnected island',roots_with_name)
        off=(0,335,665,1005)[n-1]
        port=(500+off,{1:200,2:370,3:540}[bank])
        check(at(port)['islands']==roots['adc'],f'{j} ADC port anchor electrically reached',port)
        outlines=[rid for (k,rid),b in rows.items() if k=='POLY' and b.get('strokeColor')=='#840000' and len(b.get('points',[]))==7 and any(math.dist(port,(p['x'],p['y']))<TOL for p in b['points'])]
        check(len(outlines)==1,f'{j} real ADC port outline on wire',outlines)
        channel_reports.append({'sma':j,'bank':bank,'channel':n,'groups':{g:{'pins':ks,'net':labels[g],'physicalIslands':roots[g]} for g,ks in groups.items()},'adcPortPoint':port,'outlineIds':outlines})

    # Independently frozen DNP ownership, with literal before bodies.
    dnp=json.loads((HERE/'independent-seven-dnp-ownership-audit.json').read_text())
    dnpkeys={tuple(k) for k in dnp['deleteRecordKeys']}
    deleted=before.keys()-rows.keys()
    changed={k for k in before.keys()&rows.keys() if before[k]!=rows[k]}
    new=rows.keys()-before.keys()
    check(len(dnpkeys)==196 and dnpkeys <= deleted,'all196 independently owned DNP records deleted')
    check(not dnpkeys&rows.keys(),'DNP ownership absent in candidate')
    check(all(ch['ref'] not in refs for ch in dnp['channels']),'all7 DNP refs absent')
    for ch in dnp['channels']:
        for rec in ch['deleteRecordsWithExactBodyChecks']:
            check(before[tuple(rec['key'])]==rec['body'],'DNP frozen body '+str(rec['key']))
        wid=ch['sharedPreWireGroupToPreserve']['key'][1]
        check(('WIRE',wid) in rows and rows['WIRE',wid]==before['WIRE',wid],ch['ref']+' shared PRE WIRE body retained')

    # All additional deletions must be wire primitives on the seven old input
    # chains, or an obsolete +3V3 flag owned by those exact bias wire islands.
    target_old_refs={ref for d in definitions[3:] for ref in d[:5]}|{d[8] for d in definitions[3:]}
    target_wire_ids=set()
    for (ref,num),p in oldpins.items():
        if ref not in target_old_refs: continue
        for (k,rid),b in before.items():
            if k=='LINE' and on(p['point'],(b['startX'],b['startY']),(b['endX'],b['endY'])): target_wire_ids.add(b['lineGroup'])
    flag_ids=set()
    for (k,rid),b in before.items():
        if k!='COMPONENT' or olda[rid].get('Global Net Name')!='+3V3' or (k,rid) not in deleted: continue
        check(olda[rid].get('Convert to PCB')=='no','removed supply flag is nonphysical '+rid)
        flag_pin_points=[p['point'] for (ref,num),p in oldpins.items() if ref==olda[rid].get('Designator')]
        touching={line['lineGroup'] for (kk,rr),line in before.items() if kk=='LINE' and any(on(pt,(line['startX'],line['startY']),(line['endX'],line['endY'])) for pt in flag_pin_points)}
        check(bool(touching) and touching <= target_wire_ids,'obsolete main3V3 flag owned by old target bias wire '+rid,sorted(touching))
        flag_ids.add(rid)
    check(len(flag_ids)==7,'exactly7 obsolete main3V3 flags removed')
    extra_delete=[]
    for k in sorted(deleted-dnpkeys):
        b=before[k]
        allowed=(k[0]=='LINE' and b['lineGroup'] in target_wire_ids) or (k[0]=='COMPONENT' and k[1] in flag_ids) or (k[0]=='ATTR' and b.get('parentId') in flag_ids)
        check(allowed,'extra deletion belongs only rebuilt channel wire/obsolete bias flag '+str(k))
        extra_delete.append({'key':k,'classification':'rebuilt target LINE' if k[0]=='LINE' else 'obsolete target3V3 flag/owned ATTR','parent':b.get('parentId',b.get('lineGroup'))})

    # Bindings and values are independently matched against existing verified
    # ADC1 role templates, including packed UUIDs rather than only ATTR strings.
    role_templates=['R137','R140','R141','C80','U10','C97','C100']
    expected_values=['6.8k','6.8k','47','2.2nF','OPA320AIDBVR','10nF','100nF']
    semantic_keys=('Device','Symbol','Footprint','Value','DNP','Add into BOM','Convert to PCB')
    bindings=[]
    for definition in definitions:
        selected=[definition[i] for i in (1,2,3,4,5,6,7)]
        for ref,template,value in zip(selected,role_templates,expected_values):
            cid,tid=refs[ref],oldrefs[template]
            check(a[cid].get('Value')==value,'role value '+ref,value)
            check({k:a[cid].get(k) for k in semantic_keys}=={k:olda[tid].get(k) for k in semantic_keys},'exact runtime template semantics '+ref,template)
            cb=rows['COMPONENT',cid]
            for field,attr in (('DeviceName','Device'),('FootprintName','Footprint'),('SymbolName','Symbol')):
                if cb.get('attrs',{}).get(field):
                    packed=json.loads(cb['attrs'][field])
                    check(packed.get('uuid')==a[cid][attr],'packed UUID consistent '+ref+'.'+field)
            check(('DEVICE',a[cid]['Device']) in lib and ('SYMBOL',a[cid]['Symbol']) in lib and ('FOOTPRINT',a[cid]['Footprint']) in lib,'all existing runtime libraries present '+ref)
            device=lib['DEVICE',a[cid]['Device']]
            metas=[b for (k,rid),b in device.items() if k=='META']
            check(len(metas)==1 and metas[0].get('attributes',{}).get('Symbol')==a[cid]['Symbol'] and metas[0].get('attributes',{}).get('Footprint')==a[cid]['Footprint'],'DEVICE META symbol/footprint consistent '+ref)
            bindings.append({'ref':ref,'template':template,'value':value,'device':a[cid]['Device'],'symbol':a[cid]['Symbol'],'footprint':a[cid]['Footprint']})
    oldphysical={olda[cid]['Designator'] for (k,cid) in before if k=='COMPONENT' and olda[cid].get('Convert to PCB')=='yes'}
    physical={a[cid]['Designator'] for (k,cid) in rows if k=='COMPONENT' and a[cid].get('Convert to PCB')=='yes'}
    newrefs={f'U{i}' for i in range(13,20)}|{f'C{i}' for i in range(106,120)}
    check(oldphysical-physical==DNP_REFS and physical-oldphysical==newrefs,'physical page membership7 removed21 new')
    fullparts=set(re.findall(r'(?m)^\[\r?\nDESIGNATOR\r?\n([^\r\n]+)',NETLIST.read_text()))
    check(len(fullparts)==340 and len((fullparts-DNP_REFS)|newrefs)==354,'full physical component count340 to354')

    # Literal protection scopes, derived from original geometry, not plan keys.
    protected={}
    for name,rect,component_refs in [('REF',(980,710,1450,865),{'U9','C103','C104','C105'}),('J18',(780,820,1010,1010),{'J18'}),('ADC1',(180,80,1240,250),{d[i] for d in definitions[:3] for i in range(9)})]:
        x0,y0,x1,y1=rect
        keys={k for k,b in before.items() if (pts:=geometry_points(k,b)) and all(x0<=x<=x1 and y0<=y<=y1 for x,y in pts)}
        cids={oldrefs[r] for r in component_refs}
        keys|={('COMPONENT',cid) for cid in cids}
        wids={before[k]['lineGroup'] for k in keys if k[0]=='LINE'}
        keys|={('WIRE',wid) for wid in wids}
        keys|={k for k,b in before.items() if k[0]=='ATTR' and b.get('parentId') in cids|wids}
        exceptions=[]
        for k in keys:
            old,newbody=before[k],rows.get(k)
            if name=='REF' and k[0]=='TEXT' and newbody is not None and old!=newbody:
                value=newbody.get('value')
                if value in {'ADC1/ADC2/ADC3 bias - 2026-10-17','Shared 2.5 V bias: 10 inputs, not VDDA/VREF+'}:
                    check({f:v for f,v in old.items() if f!='value'}=={f:v for f,v in newbody.items() if f!='value'},'root-approved REF caption value-only '+str(k))
                    exceptions.append({'key':k,'before':old.get('value'),'after':value})
                    continue
            check(newbody==old,name+' protected literal body '+str(k))
        if name=='REF': check(len(exceptions)==2,'exactly2 authorized REF caption updates')
        protected[name]={'recordCount':len(keys),'valueOnlyExceptions':exceptions,'rectangle':rect,'componentRefs':sorted(component_refs)}

    # The ONLY remaining moved auxiliary blocks preserve electrical semantics;
    # verify exact translations for every changed row in their original scopes.
    aux=[]
    for name,rect,dy in [('TIMER',(180,520,1200,625),95),('DAC/MCO',(180,635,700,730),100)]:
        x0,y0,x1,y1=rect
        eligible={k for k,b in before.items() if (pts:=geometry_points(k,b)) and all(x0<=x<=x1 and y0<=y<=y1 for x,y in pts)}
        translated=[]
        for k in eligible & changed:
            expectedbody=copy.deepcopy(before[k])
            for field in ('y','startY','endY','dotY1','dotY2'):
                if expectedbody.get(field) is not None: expectedbody[field]+=dy
            for p in expectedbody.get('points',[]): p['y']+=dy
            check(rows[k]==expectedbody,name+' exact translation only '+str(k))
            translated.append(k)
        check(bool(translated),name+' auxiliary block moved')
        aux.append({'name':name,'sourceRectangle':rect,'deltaY':dy,'translatedRecords':translated})
    # All unchanged original components retain binding attributes, except the28
    # approved R/C replacements; moved auxiliary attributes only change layout.
    rebound={d[i] for d in definitions[3:] for i in (1,2,3,4)}
    for ref in oldphysical & physical - rebound:
        cid=refs[ref]
        check(a[cid]==olda[cid],'remaining component semantic ATTRs unchanged '+ref)

    plan=json.loads((HERE/'adc10-schematic-plan.json').read_text())
    pnew={(r['h']['type'],r['h'].get('id')):r['b'] for r in plan['added']}
    pdel={(r['h']['type'],r['h'].get('id')):r['b'] for r in plan['deleted']}
    pchg={(r['type'],r['id']):(r['before'],r['after']) for r in plan['changes']}
    check(set(pnew)==new and set(pdel)==deleted and set(pchg)==changed,'manifest exact membership agrees independent delta')
    check(all(rows[k]==v for k,v in pnew.items()) and all(before[k]==v for k,v in pdel.items()) and all(before[k]==v[0] and rows[k]==v[1] for k,v in pchg.items()),'all manifest literal bodies agree independent delta')
    report={'schema':'adc10-independent-actual-symbol-line-candidate-audit-20261017-v1','passed':not errors,
      'candidatePath':str(CANDIDATE),'candidateSha256':sha(CANDIDATE),'baselinePath':str(BASE),'baselineSha256':sha(BASE),
      'checkpointPath':str(CHECKPOINT),'checkpointSha256':sha(CHECKPOINT),'method':'Actual embedded SYMBOL pins transformed into canvas coordinates; LINE endpoint-on-segment joins only. Equal NET labels never join islands; interior-only crossings are not joined.',
      'counts':{'baselineRecords':len(before),'candidateRecords':len(rows),'changed':len(changed),'deleted':len(deleted),'added':len(new),'physicalWireIslands':len(islands),'pageConnectedPinsChecked':len(page_data),'pagePhysicalPartsBefore':len(oldphysical),'pagePhysicalPartsAfter':len(physical),'expectedFullConnectedPins':1136,'expectedFullPhysicalParts':354},
      'fullPinContractPath':str(contract_path),'fullPinContractSha256':sha(contract_path),'changedExistingPins':rewired,'addedPins':len(added),'removedPins':len(removed),
      'channelChecks':channel_reports,'pagePinContract':page_data,'protectedScopes':protected,'auxiliaryTranslations':aux,
      'bindings':bindings,'independentDnpDeletedRecords':len(dnpkeys),'extraDeletionClassification':extra_delete,
      'nonTargetOriginalLiteralExactRecords':sum(k in rows and rows[k]==b for k,b in before.items() if k not in changed|deleted),
      'allLibrariesReusedFromCheckpoint':True,'liveApiCalls':0,'nativeFilesWritten':0,'pcbMutated':False,
      'limitations':['Candidate QA only; native ERC, netlist export, save/reopen still required.','No open-SMA-to-raw-ADC0 detector implemented; existing floating-input2.5V behavior retained.','No PCB ECO, firmware changes, CAM clearance or fabrication approval.'],
      'checks':tests,'errors':errors}
    out=HERE/'independent-adc10-candidate-graph-audit-20261017.json'
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'candidateSha256':sha(CANDIDATE),'counts':report['counts'],'errors':errors},indent=2))
    if errors: raise ValueError('Independent ADC10 candidate audit failed')


if __name__=='__main__': main()
