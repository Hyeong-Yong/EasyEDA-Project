"""Evidence from saved native sources, exact pin maps and unchanged PCB copper."""
import copy,hashlib,importlib.util,json,re,sys,zipfile
from collections import Counter,defaultdict
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
s=importlib.util.spec_from_file_location('m',root/'scripts/readability-model.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
read=lambda p:json.loads(p.read_text(encoding='utf8'))
sc=read(out/'native-validation.json');pcb=read(out/'pcb-restored-rule.json')
def pinmap(text):
 result={}
 for block in re.findall(r'\(\s*\n(.*?)\n\)',text,re.S):
  rows=block.splitlines();net=rows[0].strip()
  for row in rows[1:]:
   a=re.match(r'([^\s-]+)-([^\s]+)',row.strip())
   if a:result[a[1]+'.'+a[2].split('-')[0]]=net
 return result
current=pinmap(sc['pages'][0]['netlist']);prior=pinmap(read(root/'output/readability/native-validation.json')['pages'][0]['netlist'])
differences={k:{'lastCommittedSchematic':prior.get(k),'currentSchematic':current.get(k)} for k in set(prior)|set(current) if prior.get(k)!=current.get(k)}
assert differences=={'R102.1':{'lastCommittedSchematic':'MCU_RECEIVE_A','currentSchematic':'$2N434'}},differences
(out/'source-audit.json').write_text(json.dumps({'pinNets':{k:[v] for k,v in current.items()},'nativeProtelAuthority':True},indent=2),encoding='utf8')
before=read(root/'output/preflight-before-pages.json')
bd=next(iter(m.io.documents(before['pages'][1]['source']).values()));fd=next(iter(m.io.documents(sc['pages'][1]['source']).values()));ba=m.io.attrs(bd)
r102=next(i for (t,i),(_,p) in bd['records'].items() if t=='COMPONENT' and ba.get(i,{}).get('Designator')=='R102')
protected=[]
for key,(_,p) in bd['records'].items():
 if key==('COMPONENT',r102) or p.get('parentId')==r102 or key==('WIRE','2499435c58e74be8') or p.get('parentId')=='2499435c58e74be8' or p.get('lineGroup')=='2499435c58e74be8':
  assert fd['records'][key][1]==p,('Protected R102 changed',key);protected.append(list(key))
pd=next(iter(m.io.documents(pcb['source']).values()));pa=m.io.attrs(pd)
oldpd=next(iter(m.io.documents(read(out/'pcb-reopened.json')['source']).values()));changed=[]
for key in set(oldpd['records'])|set(pd['records']):
 a=oldpd['records'].get(key,(None,None))[1];b=pd['records'].get(key,(None,None))[1]
 if a==b:continue
 assert key==('RULE','["RULE","SOLDER","solderMaskExpansion"]'),('Unexpected PCB geometry change',key)
 ac=copy.deepcopy(a);bc=copy.deepcopy(b)
 assert ac['ruleContext'].pop('padTopExpan')==2 and bc['ruleContext'].pop('padTopExpan')==1
 assert ac==bc,('Unexpected manufacturing rule edit',key)
 changed.append({'id':key[1],'before':a,'after':b})
assert len(changed)==0,('Native mask rule edit did not persist; retain original CAD rule',changed)
footprints={p['Designator']:p['Footprint'] for p in pa.values() if p.get('Designator') and p.get('Footprint')}
parts={};instances=0
for pg in sc['pages']:
 doc=next(iter(m.io.documents(pg['source']).values()));aa=m.io.attrs(doc)
 for (t,i),(_,p) in doc['records'].items():
  a=aa.get(i,{})
  if t!='COMPONENT' or not a.get('Designator'):continue
  instances+=1;ref=a['Designator']
  if ref in parts:continue
  fp=footprints[ref];f=m.LIB[fp];value=a.get('Value') or a.get('Name')
  if value=='={Manufacturer Part}':value=a.get('Manufacturer Part')
  if value=='={Value}':value=a.get('Value')
  notes=[]
  if a.get('Supplier')=='Manual procurement':notes.append('Exact MPN manual procurement; library generic part is not an approved substitute. Stock/lead time not reserved.')
  if ref=='J1':notes.append('Samtec SSW-105-02-G-D: 2.54mm pitch/rows, straight 2x5 female; existing 1.100mm holes and 1.7mm pads retained. Match cable/header height before purchase.')
  if ref=='Q2':notes.append('Nexperia Not For Design In / NRND; not confirmed discontinued. Retained prototype part, replacement recommended for future production.')
  if str(a.get('Manufacturer Part','')).startswith('RG1608N'):notes.append('Susumu RG1608N W=0.05%, N=10ppm; exact T5 packing procurement required. Gain/offset calibration still required.')
  parts[ref]={'ref':ref,'page':'DAC8562' if pg['page']=='e58bcc16379b10f4' else 'DAC_MCU','value':value,'manufacturer':a.get('Manufacturer'),'manufacturerPart':a.get('Manufacturer Part'),'supplier':a.get('Supplier'),'supplierPart':a.get('Supplier Part') or None,'tolerance':a.get('Tolerance'),'tcr':a.get('Temperature Coefficient'),'footprintUuid':fp,'footprintName':f['head'].get('title') or f['head'].get('name'),'notes':notes}
assert len(parts)==154 and instances==158
groups=defaultdict(list)
for ref,p in parts.items():groups[(p['manufacturerPart'],p['footprintUuid'],p['supplierPart'],p['value'])].append(ref)
bom=[{**parts[refs[0]],'refs':sorted(refs),'quantity':len(refs)} for refs in groups.values()]
(out/'BOM-confirmed.json').write_text(json.dumps({'physicalPartCount':154,'symbolInstanceCount':158,'groupCount':len(bom),'meaningOfConfirmed':'Design MPN and package selected; no stock reservation, assembler acceptance or purchase order. Q2 NRND explicitly retained.','parts':list(parts.values()),'grouped':bom},ensure_ascii=False,indent=2),encoding='utf8')
mask_changes={'scope':'DFM Gerber reference only; U3 virtual mask set to 1mil','referenceGerberExpansionMm':.0254,'nativeFootprintRetainsExpansionMil':2.008,'nativeMaskCorrectionPersisted':False,'bottomPasteAndViaRulesUnchanged':True,'limitation':'Virtual pad and source rule edits were not serialized in the project export. Actual CAD footprint master must be updated and its regenerated CAM reviewed before fabrication.'}
native_zip=out/'DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber.zip';oldzip=root/'output/final-review/DAC8562_DAC_MCU_100x100_final_Gerber.zip'
def normalized(b):return '\n'.join(l for l in b.decode().splitlines() if not l.startswith(('G04',';')))
with zipfile.ZipFile(native_zip) as nz,zipfile.ZipFile(oldzip) as oz:
 unchanged=[n for n in nz.namelist() if n.endswith(('.GTL','.GBL','.GKO','.DRL')) and normalized(nz.read(n))==normalized(oz.read(n))]
 expected=[n for n in nz.namelist() if n.endswith(('.GTL','.GBL','.GKO','.DRL'))]
 cam_serialization_differences=sorted(set(expected)-set(unchanged))
pcattrs=[p for (t,i),(_,p) in pd['records'].items() if t=='ATTR' and p.get('key')=='Designator' and p.get('valueVisible')]
text_sizes=Counter(round(p.get('fontSize',0)*.0254,4) for p in pcattrs)
result={'date':'2026-10-13','schematicWarnings':sc['pages'][0]['details'],'cadWarningInterpretation':'One global schematic warning: protected R102.1 singleton $2N434 confirmed. The same global warning is returned when either schematic page is active; do not add these two counts.',
 'schematicPinDifferencesFromPriorCommittedValidNetlist':differences,'protectedR102PayloadsUnchanged':protected,
 'pcbPadNetCopperGeometryUnchanged':True,'onlyPcbManufacturingAttributeEdits':changed,'dacMaskExpansion':mask_changes,
 'nativeCamFilesEquivalentAfterRemovingComments':unchanged,'nativeCamSerializationDifferencesRequireGeometryComparison':cam_serialization_differences,
 'componentDesignatorSilkFontHeightsMm':dict(text_sizes),'silkLegibilityLimitation':'JLC recommendation >=1.0mm height and 0.15mm stroke: retained densely packed designator fonts are smaller; some text is clipped for pad clearance. Assembly drawing/native ref map required, manufacturer silkscreen review pending.',
 'nativePrimitiveCounts':dict(Counter(k[0] for k in pd['records'])),'bomGroups':len(bom),'fabricationReleased':False}
(out/'preflight-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k not in ('onlyPcbManufacturingAttributeEdits','protectedR102PayloadsUnchanged','nativePrimitiveCounts','dacMaskExpansion')},ensure_ascii=False,indent=2))
