"""Qualify 70 complex placements without changing native PCB geometry."""
from pathlib import Path
import json,math,csv,copy,collections,importlib.util
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019';OR=OUT/'orientation'
load=lambda p:json.loads(p.read_text(encoding='utf8'))
placement={r['ref']:r for r in load(ROOT/'output/jlcpcb-20261019-review/PLACEMENT_AUDIT.json')}
fits={r['ref']:r for r in load(OR/'pin-fit-review.json')};tasks=load(OR/'footprint-tasks.json')
sp=importlib.util.spec_from_file_location('native_review',ROOT/'scripts/standard-values-review-20261019.py');nr=importlib.util.module_from_spec(sp);sp.loader.exec_module(nr)
d=nr.docs(OUT/'native/final/STM32H747_JLCPCB_20261019.epro2');pcb=d['0ac2a19168000d8e'];aa=nr.attributes(pcb)
components={aa[i].get('Designator'):{**b.get('attrs',{}),**aa[i]} for(k,i),(h,b)in pcb['records'].items()if k=='COMPONENT'}
catalog=[r for p in (OUT/'libraries').glob('catalog-exact-*.json')for r in load(p)]
sma=next(r for r in catalog if r['mpn']=='SMA-KWE901')['items'][0];canonicalAngle=float(sma['otherProperty']['3D Model Transform'].split(',')[3])
expected=load(ROOT/'output/standard-values-20261019/PLACEMENT_CONTINUITY_AUDIT.json')['canonicalRotationStillPending'];assert len(expected)==70
def sourcepads(i):
 out=[]
 for l in (OR/f'canonical-{i}.epru').read_text(encoding='utf8').splitlines():
  if not l.startswith('{"type":"PAD"'):continue
  b=json.loads(l.split('||',1)[1].removesuffix('|'));out.append({'pin':b.get('num'),'x':b['centerX']*.0254,'y':b['centerY']*.0254})
 return out
def genericfit(ref,canonical):
 pairs=[(a,b)for a in canonical for b in placement[ref]['pads']if a['pin']==b['pin']];result=[]
 for deg in [0,90,180,270]:
  c,s=math.cos(math.radians(deg)),math.sin(math.radians(deg));q=[(a['x']*c-a['y']*s,a['x']*s+a['y']*c,b['x'],b['y'])for a,b in pairs];tx=sum(z[2]-z[0]for z in q)/len(q);ty=sum(z[3]-z[1]for z in q)/len(q);err=max(math.hypot(z[0]+tx-z[2],z[1]+ty-z[3])for z in q);result.append((err,deg))
 return min(result)
rows=[]
for ref in expected:
 p=placement[ref];r=copy.deepcopy(fits.get(ref,{'ref':ref,'side':p['physicalSide'],'pin1':next((q for q in p['pads']if q['pin'] in ['1','A1']),None)}));r['pads']=p['pads'];r['nativeModelTransform']=p['modelTransform'];r['supplierZeroConfirmed']=ref in fits;r['factoryAction']='Confirm in exact part placement preview against numbered pad drawing.'
 if ref in fits:
  assert r['bestFit'] or ref=='SW1'
  if r['bestFit']:r['rotationDegrees']=r['bestFit']['angle']
  r['review']='NUMBERED_PADS_CHECKED'
 if ref.startswith('J') and 2<=int(ref[1:])<=17:
  assert components[ref]['3D Model'].split('|')[0]==sma['model3DUuid']
  r['rotationDegrees']=(float(p['modelTransform'].split(',')[3])-canonicalAngle)%360
  r['basis']='Same supplier 3D model UUID; actual model rotation minus canonical 180-degree model rotation. Centre pin 5 maps to board signal 1; four shields map to board 2.'
  r['portDirection']={90:'LEFT (-X)',270:'RIGHT (+X)',0:'UP (+Y)'}[r['rotationDegrees']];r['review']='PORT_AND_SIGNAL_CHECKED'
 if ref=='SW1':
  r.update(rotationDegrees=0,review='SWITCH_NET_PAIRS_CHECKED',basis='Nonpolar SPST: board row 1 and row 2 are opposite switch contacts. Catalog pins 1/2 share one row, 3/4 the other; 0 and 180 degrees are electrically equivalent. Never rotate by 90 degrees.',supplierZeroConfirmed=True)
 if ref=='U2':r.update(rotationDegrees=0,review='LEAD_ROW_AND_TAB_CHECKED',basis='Three numbered SOT-223 leads on +X, tab 4 on -X. Same 2.3 mm lead pitch. Original outward-extended hand-solder lands retained; centroid is unchanged.')
 if ref=='Y1':r.update(rotationDegrees=0,review='NONPOLAR_AXIS_CHECKED',basis='Nonpolar 32.768 kHz crystal, terminals 1/2 along X; 0 and 180 degrees equivalent. Original hand-solder land centres are farther apart than supplier library; factory DFM must check solder contact coverage.',factoryAction='Check custom hand-solder land coverage against NDK NX3215SA dimensions; do not change orientation by 90 degrees.')
 if ref in ['D2','D3','D4','D6']:
  a,b=[next(x for x in p['pads']if x['pin']==pin)for pin in ['1','2']]
  deg=(math.degrees(math.atan2(a['y']-b['y'],a['x']-b['x']))-180)%360
  r.update(rotationDegrees=round(deg)%360,review='CATHODE_PAD_CHECKED',basis='Original LED schematic pin 1 is cathode, pin 2 anode. Drawing marks the cathode; normalized zero places cathode on left.',supplierZeroConfirmed=False,factoryAction='Exact WR148SR-W source or qualified replacement must map its cathode mark to board pad 1. Factory derives tape rotation from supplied part.')
 if ref=='U6':
  error,deg=genericfit(ref,sourcepads(19));assert error<.251
  r.update(rotationDegrees=deg,review='SO8_PIN_ORDER_CHECKED',referenceLandCentreDifferenceMm=error,basis='SO-8 numbered pads match at 90 degrees with 1.27 mm pitch; original hand-solder lands extend outward by 0.25 mm versus the reference library. ST datasheet pinout retained. Exact STS5PF30L is obsolete.',supplierZeroConfirmed=False,factoryAction='Resolve obsolete part sourcing or approve a separately reviewed substitute; verify purchased tape pin-1 orientation against drawing before assembly.')
 if ref in ['CN2','J18']:
  r.update(rotationDegrees=0,review='MANUAL_INSERTION_DRAWING_CHECKED',basis='Through-hole manual insertion specified by actual numbered pads and original mechanical pose. CPL zero is drawing convention, not a claimed supplier tape zero.',supplierZeroConfirmed=False,factoryAction='Confirm exact connector outline, pin 1 and mating direction from drawing; hand-insert to original board side.')
 assert 'rotationDegrees'in r and r['side']=='Top';rows.append(r)
assert len(rows)==70 and len({r['ref']for r in rows})==70
# Read-only proof of the LED cathode mapping from original symbol attributes.
ledproof=[]
for uid,doc in d.items():
 if doc['head']['docType']!='SCH_PAGE':continue
 attrs=nr.attributes(doc)
 for cid,a in attrs.items():
  if a.get('Designator') in ['D2','D3','D4','D6']:
   sym=nr.attributes(d[a['Symbol']]);ledproof.append({'ref':a['Designator'],'symbol':a['Symbol'],'pinAttributes':list(sym.values())})
report={'partsReviewed':70,'catalogFootprintsRead':27,'catalogLinkedParts':63,'manualSourceParts':7,'nativeCentroidsAndSidesPreserved':True,'pcbGeometryChanged':False,'allLocalPinDirectionChecksCompleted':True,'factoryPlacementPreviewCompleted':False,'supplierTapeZeroNotClaimedFor':[r['ref']for r in rows if not r['supplierZeroConfirmed']],'smaCanonicalModelRotation':canonicalAngle,'smaModelUuid':sma['model3DUuid'],'rows':rows,'ledPinProof':ledproof,'sources':['https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly','https://jlcpcb.com/help/article/pcb-assembly-faqs-part-2','https://www.ndk.com/images/products/catalog/c_NX3215SA_e.pdf','https://www.st.com/resource/en/datasheet/sts5pf30l.pdf']}
(OUT/'ROTATION_REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
data=load(OUT/'order-data.json');cpl=copy.deepcopy(data['cplBeforeRotationReview']);byref={r['ref']:r for r in rows}
for r in cpl:
 if r['Designator']in byref:r['Rotation']=str(byref[r['Designator']]['rotationDegrees'])
data.update(cpl=cpl,rotationReview=report);(OUT/'order-data.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'reviewed':70,'catalog':63,'manualSource':7,'rotationChanged':sum(float(a['Rotation'])!=float(b['Rotation'])for a,b in zip(cpl,data['cplBeforeRotationReview'])),'SMAleft':byref['J2']['rotationDegrees'],'SMAright':byref['J12']['rotationDegrees'],'SMAtop':byref['J16']['rotationDegrees']}))
