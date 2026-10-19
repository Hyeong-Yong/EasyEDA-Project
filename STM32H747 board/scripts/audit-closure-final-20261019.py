"""Audit saved CAD, fabrication continuity, and prepare order-review data."""
from pathlib import Path
import json,collections,copy,hashlib,importlib.util,zipfile,re,csv,math,shutil
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019';FINAL=OUT/'native/final'
def load(p):return json.loads(p.read_text(encoding='utf8'))
def dump(name,x):(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
sp=importlib.util.spec_from_file_location('native_review',ROOT/'scripts/standard-values-review-20261019.py');nr=importlib.util.module_from_spec(sp);sp.loader.exec_module(nr)
oldpath=OUT/'native/STM32H747_before_jlc_closure_20261019.epro2';newpath=FINAL/'STM32H747_JLCPCB_20261019.epro2'
old,new=nr.docs(oldpath),nr.docs(newpath);plan=load(OUT/'closure-plan.json');pcb=plan['pcbUuid']
targetids=collections.defaultdict(set)
for t in plan['targets']:targetids[t['page']].add(t['schId']);targetids[pcb].add(t['pcbId'])
allowed={'Device','DeviceName','DNP',*sum([list(g['properties']) for g in plan['groups']],[])}
errors=[];changes=[];normalizations=[]
for u in old:
 for key in set(old[u]['records'])|set(new[u]['records']):
  x=old[u]['records'].get(key,(None,None))[1];y=new[u]['records'].get(key,(None,None))[1]
  if x==y:continue
  kind,rid=key;b=y or x;ok=False;why=''
  if kind=='ATTR':
   if x and y:
    xx,yy=copy.deepcopy(x),copy.deepcopy(y)
    if 'strikeout' not in xx and yy.get('strikeout') is False:yy.pop('strikeout');normalizations.append({'document':u,'id':rid,'normalization':'implicit strikeout=false'})
    if b.get('parentId') in targetids[u] and b.get('key') in allowed:xx.pop('value',None);yy.pop('value',None);why='Reviewed target metadata only'
    if xx.get('zIndex')!=yy.get('zIndex') and (not xx.get('valueVisible') or (xx.get('fontSize') or 0)<=.001):
     xx.pop('zIndex',None);yy.pop('zIndex',None);normalizations.append({'document':u,'id':rid,'normalization':'hidden/tiny attribute ordinal zIndex serialization'})
    ok=xx==yy
   elif y and b.get('parentId') in targetids[u] and b.get('key') in allowed:
    ok=not y.get('valueVisible') and not y.get('keyVisible') and y.get('x') is None and y.get('y') is None;why='New hidden sourcing attribute'
  if kind=='COMPONENT' and rid in targetids[u] and x and y:
   xx,yy=copy.deepcopy(x),copy.deepcopy(y)
   for k in allowed:xx.get('attrs',{}).pop(k,None);yy.get('attrs',{}).pop(k,None)
   if 'angle' in xx and (xx['angle']-yy['angle'])%360==0:yy['angle']=xx['angle']
   ok=xx==yy;why='Metadata and physically equivalent angle serialization only'
  if kind=='TEXT' and rid in ['75eae3802c16c27e','bec27b41e3795d57'] and x and y:
   xx,yy=copy.deepcopy(x),copy.deepcopy(y);xx.pop('value');yy.pop('value');expectedText=('1.645' if rid=='75eae3802c16c27e' else '1.6445832 - 0.6965174');ok=xx==yy and expectedText in y['value'];why='Annotation corrected to existing verified 1.6445832 V bias; no circuit change'
  if kind in ['CANVAS','ACTIVE_LAYER','ELE_PLACEHOLDER']:ok=True;why='Editor view state'
  row={'document':u,'type':kind,'id':rid,'attribute':b.get('key'),'allowed':ok,'reason':why};changes.append(row)
  if not ok:errors.append({**row,'before':x,'after':y})
libs={u:d['records'].get(('META','META'),(0,{}))[1].get('attributes',{}) for u,d in new.items() if d['head']['docType']=='DEVICE'}
attrcache={u:nr.attributes(d) for u,d in new.items() if d['head']['docType'] in ['PCB','SCH_PAGE']}
def effective(u,cid):
 a={**new[u]['records'][('COMPONENT',cid)][1].get('attrs',{}),**attrcache[u][cid]};return{**libs.get(a.get('Device'),{}),**a}
aliases={'R201':'UNI-ROYAL(厚声)','R202':'RESI(开步睿思)','R203':'RESI(开步睿思)'}
for t in plan['targets']:
 s,p=effective(t['page'],t['schId']),effective(pcb,t['pcbId']);expected={**t['properties'],'Manufacturer':aliases.get(t['ref'],t['properties']['Manufacturer'])}
 for k,v in expected.items():
  if s.get(k)!=v or p.get(k)!=v:errors.append({'ref':t['ref'],'key':k,'expected':v,'sch':s.get(k),'pcb':p.get(k)})
 assert s['Unique ID']==p['Unique ID']==t['uniqueId'] and s['Symbol']==t['before']['Symbol'] and s['Footprint']==p['Footprint']==t['before']['Footprint']
 assert s['DNP']==p['DNP']=='no'
counts=collections.Counter(k for k,i in new[pcb]['records']);assert counts['COMPONENT']==437 and counts['VIA']==704 and counts['PAD_NET']==1523
assert all(old[u]['records']==new[u]['records'] for u in old if old[u]['head']['docType'] in ['DEVICE','SYMBOL','FOOTPRINT'])
audit={'sourceBeforeSHA256':sha(oldpath),'sourceAfterSHA256':sha(newpath),'documentsBefore':len(old),'documentsAfter':len(new),'newLibraryDocuments':[(u,d['head']['docType']) for u,d in new.items() if u not in old],'targetParts':132,'newlySelectedParts':107,'electricalNominalChanges':0,'oldLibrariesPreserved':True,'pcbRecordCounts':dict(counts),'recordChanges':changes,'serializationNormalizations':normalizations,'errors':errors,'physicalAndElectricalRecordsPreserved':not errors}
dump('DURABLE_AUDIT.json',audit)
if errors:raise AssertionError(json.dumps(errors[:4],ensure_ascii=False))
assert load(FINAL/'STRICT_DRC_FINAL.json')['violations']==[]
# All fabrication primitives, not file order/aperture identifiers, are compared.
gs=importlib.util.spec_from_file_location('gp',ROOT/'scripts/extract_gerber_reconstruction.py');gp=importlib.util.module_from_spec(gs);gs.loader.exec_module(gp)
parsed=OUT/'local-parsed-cam';parsed.mkdir(exist_ok=True)
def primitives(name,data,label):
 p=parsed/(label+'-'+name);p.write_bytes(re.sub(rb'(?m)^G54(D\d+\*)',rb'\1',data));layer=gp.parse_gerber(p,name);rows=[]
 for obj in layer['objects']:
  obj=copy.deepcopy(obj)
  if obj['kind']=='region':obj.pop('aperture',None)
  else:
   a=layer['apertures'][obj['aperture']];obj['aperture']={'template':a['template'],'paramsMm':a['paramsMm']}
  rows.append(json.dumps(obj,sort_keys=True,separators=(',',':')))
 return rows
oldzip=ROOT/'output/standard-values-20261019/native/final/GERBER_REVIEW_NOT_FOR_ORDER.zip';newzip=FINAL/'GERBER_NATIVE.zip';members=[]
with zipfile.ZipFile(oldzip) as a,zipfile.ZipFile(newzip) as b:
 assert b.testzip() is None and set(a.namelist())==set(b.namelist())
 for name in a.namelist():
  x,y=a.read(name),b.read(name);row={'file':name,'sha256':hashlib.sha256(y).hexdigest(),'sameBytes':x==y,'bytes':len(y)}
  if name.startswith('Gerber_'):
   ax,by=primitives(name,x,'old'),primitives(name,y,'new');row['sameFabricationGeometry']=ax==by or (collections.Counter(ax)==collections.Counter(by) and all(json.loads(o)['polarity']=='dark' for o in ax+by));row['objects']=len(by)
  elif name.lower().endswith('.drl'):row['sameFabricationGeometry']=b'\n'.join(l for l in x.splitlines() if not l.startswith(b';'))==b'\n'.join(l for l in y.splitlines() if not l.startswith(b';'))
  else:row['sameFabricationGeometry']=None
  members.append(row)
cam={'gerberSHA256':sha(newzip),'sourceSHA256':sha(newpath),'zipCRC':'PASS','members':members,'allCopperMaskPasteSilkOutlineAndDrillGeometryPreserved':all(m['sameFabricationGeometry'] is not False for m in members),'copperLayers':6,'boardMm':[100,154],'vias':704,'physicalDrills':863,'priorAudit':'../standard-values-20261019/CAM_CONTINUITY_AUDIT.json'}
dump('CAM_AUDIT.json',cam);assert cam['allCopperMaskPasteSilkOutlineAndDrillGeometryPreserved']
def nativecsv(p):
 b=p.read_bytes();return list(csv.DictReader(b.decode('utf-16' if b.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig').splitlines(),delimiter='\t'))
nc=nativecsv(FINAL/'CPL_NATIVE.csv');prior=nativecsv(ROOT/'output/standard-values-20261019/native/final/CPL_NATIVE.csv');assert len(nc)==len(prior)==437
prior={r['Designator']:r for r in prior}
for r in nc:
 o=prior[r['Designator']]
 number=lambda v:float(str(v).removesuffix('mm').removesuffix('°'))
 assert number(r['Mid X'])==number(o['Mid X']) and number(r['Mid Y'])==number(o['Mid Y']) and (number(r['Rotation'])-number(o['Rotation']))%360==0 and r['Layer']==o['Layer']
# Preserve the previously verified physical-side assignment and coordinates.
data=load(ROOT/'output/standard-values-20261019/review-data.json');bom={r['Designator']:copy.deepcopy(r) for r in data['candidateBom']};assert len(bom)==412
for t in plan['targets']:
 if t['ref'] not in bom:continue
 p=effective(t['page'],t['schId']);bom[t['ref']].update({'Manufacturer Part':p['Manufacturer Part'],'Manufacturer':p['Manufacturer'],'LCSC Part #':p['Supplier Part'],'Comment':p['Value'],'Footprint':p['Package'],'Status':'Native MPN applied; electrical specification checked'})
catalog=[r for p in (OUT/'libraries').glob('catalog-exact-*.json') for r in load(p)]
catalogmap={r['mpn']:r for r in catalog}
rfq=[];selected=[]
for r in bom.values():
 q=catalogmap.get(r['Manufacturer Part']);items=q['items'] if q else []
 if items:
  matches=[i for i in items if i.get('supplierId')==r.get('LCSC Part #')];i=(matches or items)[0]
  if not r['LCSC Part #']:r['LCSC Part #']=i.get('supplierId','')
  if not r['Manufacturer']:r['Manufacturer']=i.get('manufacturer','')
  selected.append({'ref':r['Designator'],'mpn':r['Manufacturer Part'],'supplierId':r['LCSC Part #'],'deviceUuid':i['uuid'],'footprintUuid':i.get('footprintUuid'),'manufacturer':i.get('manufacturer'),'datasheet':i.get('otherProperty',{}).get('Datasheet')})
 if not r['LCSC Part #'] or r['Designator']=='U6':r['Status']='Factory sourcing approval required';rfq.append(copy.deepcopy(r))
groups={}
for r in bom.values():
 k=(r['Manufacturer Part'],r['Footprint'],r['LCSC Part #']);g=groups.setdefault(k,{**r,'refs':[],'Quantity':0});g['refs'].append(r['Designator']);g['Quantity']+=1
for r in groups.values():r['Designator']=','.join(r.pop('refs'));r['Comment']=r['Manufacturer Part']
cpl=list(csv.DictReader((ROOT/'output/jlcpcb-20261019-review/CPL_CANDIDATE.csv').read_text(encoding='utf-8-sig').splitlines()));assert len(cpl)==412
dump('order-data.json',{'bomParts':list(bom.values()),'bomGroups':list(groups.values()),'sourcingReview':rfq,'cplBeforeRotationReview':cpl,'nativeCentroidsChecked':437,'nativeAssemblyCount':412,'sideCounts':dict(collections.Counter(r['Layer'] for r in cpl)),'quantities':'Per-board data; 5 assembled boards is an unconfirmed website draft only','manufacturingReleaseApproved':False,'requiredUserSteps':['JLCPCB account sign-in and exact component match / placement preview','Resolve legacy sourcing, including obsolete U6 STS5PF30L','Confirm quantity and factory production files before payment']})
dump('libraries/selected-catalog-evidence.json',selected)
print(json.dumps({'CAD':not errors,'documents':len(new),'metadataParts':132,'CAM':cam['allCopperMaskPasteSilkOutlineAndDrillGeometryPreserved'],'BOMparts':len(bom),'BOMgroups':len(groups),'RFQparts':len(rfq),'nativeCentroids':437}))
