"""Read-only independent native accepted electrical audit; no API calls."""
import argparse
import json
import math
import re
import runpy
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
M=runpy.run_path(str(HERE/'independent-adc10-candidate-graph-audit.py'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',default=str(ROOT/'output/validation/native-adc10-sch-accepted-20261017.epru'))
    parser.add_argument('--netlist',default=str(ROOT/'output/validation/native-adc10-accepted-Protel2-20261017.net'))
    parser.add_argument('--erc',default=str(ROOT/'output/validation/native-adc10-accepted-erc-20261017.json'))
    parser.add_argument('--tag',default='accepted')
    args=parser.parse_args()
    source,netlist,erc=Path(args.source).resolve(),Path(args.netlist).resolve(),Path(args.erc).resolve()
    contract_path=HERE/'independent-adc10-expected-full-pin-contract-20261017.json'
    c=json.loads(contract_path.read_text())
    expected={(p['ref'],str(p['number'])):p['net'] for p in c['expectedPins']}
    sha,parse,attrs_for=M['sha'],M['parse'],M['attrs_for']
    rows,candidate=parse(source),parse(M['CANDIDATE'])
    a,refs=attrs_for(rows)
    ca,crefs=attrs_for(candidate)
    lib=M['libraries']()
    pins=M['actual_pins'](rows,a,lib)
    cpins=M['actual_pins'](candidate,ca,lib)
    errors,tests=[],[]
    def check(ok,name,detail=None):
        t={'test':name,'passed':bool(ok)}
        if detail is not None:t['detail']=detail
        tests.append(t)
        if not ok:errors.append(t)
    check(sha(M['CANDIDATE'])==c['candidateSha256']==M['CANDIDATE_SHA'],'frozen proposed candidate and independent contract')
    parse_net=runpy.run_path(str(ROOT/'scripts/verify-native-netlist.py'))['parse_protel2']
    text=netlist.read_text(encoding='utf-8-sig')
    native_pins=parse_net(text)
    actual={(p['ref'],str(p['number'])):p['net'] for p in native_pins}
    check(len(native_pins)==len(actual)==1136,'actual native full netlist1136 unique connected pins')
    mismatch=[{'pin':k,'expected':expected.get(k),'native':actual.get(k)} for k in sorted(expected.keys()|actual.keys()) if expected.get(k)!=actual.get(k)]
    check(actual==expected,'actual full native netlist exactly independent1136-pin contract',mismatch)
    parts=set(re.findall(r'(?m)^\[\r?\nDESIGNATOR\r?\n([^\r\n]+)',text))
    oldtext=M['NETLIST'].read_text(encoding='utf-8-sig')
    oldparts=set(re.findall(r'(?m)^\[\r?\nDESIGNATOR\r?\n([^\r\n]+)',oldtext))
    newrefs={f'U{i}' for i in range(13,20)}|{f'C{i}' for i in range(106,120)}
    check(len(parts)==354 and parts==(oldparts-M['DNP_REFS'])|newrefs,'actual native354 physical parts exact membership')
    erc_data=json.loads(erc.read_text(encoding='utf-8-sig'))
    check(erc_data.get('passed') is True,'native ERC passed=true',erc_data)
    seg,islands,nets,at=M['graph'](rows,a)
    check(all(len(n)==1 for n in nets.values()),'native physical islands no mixed-net short')
    check(set(pins)==set(cpins),'native actual SYMBOL pin membership exactly proposed')
    page=[]
    for key,pin in pins.items():
        check(math.dist(pin['point'],cpins[key]['point'])<1e-5,'native actual pin coordinate equals proposed '+'.'.join(key))
        g=at(pin['point'])
        if key in expected:
            check(len(g['islands'])==1 and g['nets']==[expected[key]],'native physical pin '+'.'.join(key),{'point':pin['point'],'expected':expected[key],**g})
            page.append({'ref':key[0],'number':key[1],**pin,**g,'expected':expected[key]})
        elif a[refs[key[0]]].get('Convert to PCB')=='yes':
            check(not g['islands'],'native unnetlisted physical pin unconnected '+'.'.join(key),g)
    check(len(page)==237,'all237 native page-connected physical pins independently verified')
    # Preserve parentId/key/value semantics; native may regenerate ATTR IDs and
    # omit default formatting fields. Do not equate those with electrical change.
    check(refs==crefs,'native component reference-to-instance ownership exactly proposed')
    for ref,cid in refs.items():
        check(a[cid]==ca[cid],'native semantic ATTR dictionary exactly proposed '+ref)
        for field in ('partId','rotation','isMirror','attrs'):
            check(rows['COMPONENT',cid].get(field)==candidate['COMPONENT',cid].get(field),'native component binding '+ref+'.'+field)
    dnp=json.loads((HERE/'independent-seven-dnp-ownership-audit.json').read_text())
    dkeys={tuple(k) for k in dnp['deleteRecordKeys']}
    check(not dkeys&rows.keys(),'all196 original DNP ownership record IDs absent native')
    deletedids={rid for kind,rid in dkeys}
    check(not [rid for (kind,rid),b in rows.items() if kind=='ATTR' and b.get('parentId') in deletedids],'no native DNP/stub/ground orphan ATTRs')
    check(all(ref not in refs for ref in M['DNP_REFS']),'all7 DNP references absent native')
    report={'schema':'adc10-independent-native-electrical-graph-audit-20261017-v1','passed':not errors,
      'sourcePath':str(source),'sourceSha256':sha(source),'netlistPath':str(netlist),'netlistSha256':sha(netlist),
      'ercPath':str(erc),'ercSha256':sha(erc),'contractPath':str(contract_path),'contractSha256':sha(contract_path),
      'candidateSha256':sha(M['CANDIDATE']),'nativeFullConnectedPins':len(actual),'nativeFullPhysicalParts':len(parts),
      'nativePageConnectedPinsChecked':len(page),'nativePhysicalWireIslands':len(islands),'nativePagePinContract':page,
      'fullNativePinContractMismatches':mismatch,'nativeErcPassed':erc_data.get('passed') is True,
      'method':'Actual embedded SYMBOL pin coordinates plus LINE endpoint-on-segment topology, never joins by NET label. Full native Protel2 comparison against independently constructed1136-node contract.',
      'limitations':['Electrical/native graph audit only; root separately reviews strict representation normalization and full project protection.','No PCB ECO, firmware, raw-zero open detector, CAM or fabrication approval.'],
      'liveApiCalls':0,'nativeFilesWritten':0,'checks':tests,'errors':errors}
    out=HERE/f'independent-adc10-{args.tag}-native-graph-audit-20261017.json'
    out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'passed':not errors,'path':str(out),'sha256':sha(out),'sourceSha256':sha(source),'pins':len(actual),'physicalParts':len(parts),'pagePinsChecked':len(page),'errors':errors},indent=2))
    if errors:raise ValueError('Independent native ADC10 graph/netlist audit failed')


if __name__=='__main__':main()
