"""Add traceable, unreserved sourcing proposals without editing CAD values."""
from pathlib import Path
import collections, json
ROOT=Path(__file__).resolve().parent
for folder in ['STM32H747 board','TEST_DAC8562']:
    base=ROOT/folder/'output/jlcpcb-20261019-review';native=base/'native'
    data=json.loads((base/'review-data.json').read_text(encoding='utf8'))
    matches={}
    for name in ['search-passives.json','search-final-passives.json',*[p.name for p in native.glob('package-basis-*.json')]]:
        path=native/name
        if not path.exists():continue
        for row in json.loads(path.read_text(encoding='utf8'))['result']:
            exact=[x for x in row['items'] if x.get('manufacturerId','').casefold()==row['key'].casefold()]
            if exact:matches[row['key']]=exact[0]
    proposals=[];candidate=[];unresolved=[]
    for p in data['parts']:
        if p['excluded']:continue
        target=p['mpn'];proposed=False
        if not target and folder=='STM32H747 board':
            v=p['value'];t=p['tolerance'];tc=p['tcr']
            if v=='10nF':target='GRM1555C1E103JE01D'
            elif v=='100nF':target='CL05B104KO5NNNC'
            elif v=='1uF':target='CL10A105KB8NNNC'
            elif v=='4.7uF':target='CL21A475KAQNNNE'
            elif v=='3.32k':target='RT0402BRD073K32L'
            elif v=='100k':target='RT0402BRD07100KL'
            elif v=='47':target='0402WGF470JTCE'
            elif v=='15.4k':target='RT0402BRD0715K4L'
            elif v=='10.0k' and '25' in tc:target='RT0402BRD0710KL'
            elif v=='1.00k':target='RT0402FRD071KL'
            proposed=bool(target)
        match=matches.get(target,{});lcsc=p['lcsc'] or match.get('supplierId','')
        if not target:unresolved.append(p)
        row={'Comment':' '.join(x for x in [p['value'],p['tolerance'],p['voltage'],p['tcr']] if x),'Designator':p['ref'],'Footprint':p['package'],'Manufacturer Part':target,'Manufacturer':p['manufacturer'] or match.get('manufacturer',''),'LCSC Part #':lcsc,'Quantity':1,'Status':'Specification unresolved - HOLD' if not target else 'Proposed new MPN; verify stock/package' if proposed else 'Exact MPN; verify stock/package'}
        candidate.append(row)
        if proposed:
            assert match and match['supplierId'].startswith('C'),target
            proposals.append({'Designator':p['ref'],'Specified value':p['value'],'Tolerance':p['tolerance'],'Voltage':p['voltage'],'TCR':p['tcr'],'Package':p['package'],'Proposed MPN':target,'LCSC Part #':match['supplierId'],'Manufacturer':match.get('manufacturer',''),'Evidence':'native/search-passives.json or native/search-final-passives.json','Approval':'Sourcing proposal only; no CAD change or stock reservation'})
    data['candidateBom']=candidate;data['proposedParts']=proposals
    data['unresolvedParts']=[{'Designator':p['ref'],'Value':p['value'],'Package':p['package'],'Tolerance':p['tolerance'],'TCR':p['tcr'],'Reason':'No confirmed exact MPN meeting all specified requirements'} for p in unresolved]
    data['summary']['proposedNewMpnParts']=len(proposals)
    data['summary']['unresolvedAfterProposals']=len(unresolved)
    data['summary']['bomCandidateQualification']='Per-component candidate BOM; proposed selections are external to CAD. Unresolved rows are explicitly held. Do not automatically match by value alone.'
    (base/'review-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    print(folder,'proposals',len(proposals),'unresolved',len(unresolved))
summaries=[json.loads((ROOT/f/'output/jlcpcb-20261019-review/review-data.json').read_text(encoding='utf8'))['summary'] for f in ['STM32H747 board','TEST_DAC8562']]
(ROOT/'output/jlcpcb-order-20261019/summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf8')
