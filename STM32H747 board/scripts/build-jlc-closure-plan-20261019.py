"""Bind reviewed stocked MPNs without changing the electrical values or pads."""
from pathlib import Path
import collections,hashlib,importlib.util,json,re
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019';OLD=ROOT/'output/standard-values-20261019'
sp=importlib.util.spec_from_file_location('native_io',ROOT/'scripts/standard-values-review-20261019.py');io=importlib.util.module_from_spec(sp);sp.loader.exec_module(io)
docs=io.docs(OUT/'native/STM32H747_before_jlc_closure_20261019.epro2');data=json.loads((OLD/'review-data.json').read_text(encoding='utf8'))
parts={}
for r in data['proposedParts']:parts[r['Designator']]={'mpn':r['Proposed MPN'],'lcsc':r['LCSC Part #'],'package':r['Package'],'wasProposal':True}
for r in json.loads((OLD/'standard-resistors-final-specs.json').read_text(encoding='utf8')):parts[r['ref']]={'mpn':r['mpn'],'lcsc':r['lcsc'],'package':'0402','wasProposal':False}
replacements=[]
for ref,p in parts.items():
    if p['lcsc'] in ['C15849','C1779']:
        code,mpn=('C59782','CL10B105KO8NNNC') if p['lcsc']=='C15849' else ('C3039701','CL21B475KOFNFNE')
        replacements.append({'ref':ref,'before':dict(p),'after':{'mpn':mpn,'lcsc':code},'reason':'Original requires X7R. Earlier candidate is X5R; select same nominal capacitance/package, X7R, rated voltage >=10V.'});p.update(mpn=mpn,lcsc=code)
stock={}
for name in ['107-parts-live-stock.json','replacement-x7r-stock.json']:
    for p in json.loads((OUT/'stock'/name).read_text(encoding='utf8'))['parts']:stock[p['code']]=p
for p in json.loads((OLD/'selected-stock-evidence.json').read_text(encoding='utf8'))['parts']:
    stock[p['lcsc']]={'code':p['lcsc'],'mpn':p['mpn'],'manufacturer':p['manufacturer'],'specifications':p['catalogSpecifications'],'description':p['description'],'datasheet':p.get('manufacturerDatasheetURL'),'url':p['url'],'stock':p['stockAtCheck']}
def scalar(v):
    v=str(v).replace('Ω','').replace('F','').replace('V','').replace('±','').replace('%','').replace(' ','').replace('or greater','')
    n=re.search(r'([\d.]+)([kmunp]?)',v);return float(n[1])*{'':1,'k':1e3,'m':1e-3,'u':1e-6,'n':1e-9,'p':1e-12}[n[2]]
targets=[];groups={};pcb=docs['0ac2a19168000d8e'];pa=io.attributes(pcb)
pcb_by_ref={a['Designator']:(cid,{**pcb['records'][('COMPONENT',cid)][1].get('attrs',{}),**a}) for cid,a in pa.items() if a.get('Designator')}
for uid,doc in docs.items():
    if doc['head']['docType']!='SCH_PAGE':continue
    for cid,a in io.attributes(doc).items():
        ref=a.get('Designator')
        if ref not in parts:continue
        p=parts[ref];st=stock[p['lcsc']];spec=st['specifications'];assert st['mpn']==p['mpn']
        sv=spec.get('Resistance',spec.get('Capacitance'));assert abs(scalar(a['Value'])/scalar(sv)-1)<1e-9,(ref,a['Value'],sv)
        assert spec['Package']==p['package']
        if a.get('Tolerance'):assert scalar(spec['Tolerance'])<=scalar(a['Tolerance'])
        if ref.startswith('C'):
            assert spec['Temperature Coefficient'] in a['Dielectric'].replace('/NP0',''),(ref,a,spec)
            assert scalar(spec['Voltage Rating'])>=scalar(a['Voltage Rating'])
        props={'Value':a['Value'],'Name':'={Value}','Package':p['package'],'Manufacturer':st['manufacturer'],'Manufacturer Part':p['mpn'],'Supplier':'LCSC','Supplier Part':p['lcsc'],'Part Number':p['mpn'],'Datasheet':st.get('datasheet') or st['url'],'Tolerance':spec['Tolerance'],'Description':st['description']}
        if ref.startswith('C'):props.update({'Dielectric':a['Dielectric'],'Voltage Rating':spec['Voltage Rating']})
        else:props.update({'Temperature Coefficient':spec['Temperature Coefficient'],'Power Rating':'62.5mW' if spec['Power(Watts)']=='63mW' else spec['Power(Watts)']})
        gid='g'+str(len(groups)) if p['mpn'] not in groups else groups[p['mpn']]['id']
        if p['mpn'] not in groups:groups[p['mpn']]={'id':gid,'mpn':p['mpn'],'name':'STM_JLC_20261019_'+p['mpn'],'symbol':a['Symbol'],'footprint':a['Footprint'],'properties':props,'refs':[]}
        g=groups[p['mpn']];assert g['symbol']==a['Symbol'] and g['footprint']==a['Footprint'] and g['properties']==props,(ref,'Group properties differ')
        g['refs'].append(ref);pcid,pattrs=pcb_by_ref[ref];assert pattrs['Unique ID']==a['Unique ID'] and pattrs['Footprint']==a['Footprint']
        targets.append({'ref':ref,'page':uid,'schId':cid,'pcbId':pcid,'uniqueId':a['Unique ID'],'before':a,'pcbBefore':pattrs,'group':g['id'],'properties':props,'wasProposal':p['wasProposal']})
assert len(targets)==132 and sum(t['wasProposal'] for t in targets)==107 and len(replacements)==12 and len(groups)==16
plan={'schema':'jlc-closure-plan-v1','projectName':'STM32H747_MCU_BOARD_v19','projectUuid':'4d4671fe9a78f6b1578521c2dc6be53db20dc0cc6cb10fdfc81febaa87f5af94','pcbUuid':'0ac2a19168000d8e','baselineSHA256':hashlib.sha256((OUT/'native/STM32H747_before_jlc_closure_20261019.epro2').read_bytes()).hexdigest(),'groups':list(groups.values()),'targets':targets,'replacements':replacements,'electricalValuesOrGeometryChangesAllowed':False}
(OUT/'closure-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'groups':len(groups),'targets':len(targets),'proposalParts':107,'x7rCorrections':12},ensure_ascii=False))
