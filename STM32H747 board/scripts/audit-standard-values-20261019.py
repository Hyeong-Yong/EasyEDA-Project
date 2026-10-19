"""Audit the exact saved project delta and carry forward bounded CAM evidence."""
from pathlib import Path
import collections,copy,csv,hashlib,importlib.util,json,re,zipfile
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/standard-values-20261019'
s=importlib.util.spec_from_file_location('resistor_review',ROOT/'scripts/standard-values-review-20261019.py');review=importlib.util.module_from_spec(s);s.loader.exec_module(review)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(name,x):(OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
beforepath=OUT/'STM32H747_before_standard_values_20261019.epro2'
afterpath=OUT/'native/final/STM32H747_standard_values_verified_20261019.epro2'
before,after=review.docs(beforepath),review.docs(afterpath)
plan=json.loads((OUT/'standard-resistors-plan.json').read_text(encoding='utf8'))
allowed={'Value','Name','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Part Number','Datasheet','Tolerance','Temperature Coefficient','Power Rating','Description','Package'}
page_targets={uid:{t['componentId']:t for t in p['targets']} for uid,p in plan['pages'].items()}
page_targets[plan['pcbUuid']]={t['componentId']:t for t in plan['pcbTargets']}
errors=[];changes=[];angle_normalizations=[];attribute_defaults=[]
assert set(before)==set(after) and len(after)==3941
for uid in before:
    a,b=before[uid]['records'],after[uid]['records'];targets=page_targets.get(uid,{})
    for key in set(a)|set(b):
        old=a.get(key,(None,None))[1];new=b.get(key,(None,None))[1]
        if old==new:continue
        kind,rid=key;ok=False;reason=''
        if kind=='ATTR' and (new or old).get('parentId') in targets:
            p=new or old
            if old and new:
                x,y=copy.deepcopy(old),copy.deepcopy(new)
                # getDocumentSource/save materializes the native false default
                # for strikeout on these target attrs. No text is struck out.
                if 'strikeout' not in x and y.get('strikeout') is False:
                    y.pop('strikeout');attribute_defaults.append({'document':uid,'id':rid,'key':p['key'],'default':'strikeout absent -> false'})
                if p['key'] in allowed:x.pop('value',None);y.pop('value',None)
                ok=x==y
            elif p['key'] in allowed and new and not new.get('keyVisible') and not new.get('valueVisible') and new.get('x') is None and new.get('y') is None:ok=True
            reason='Target metadata/default strikeout=false only; all other geometry/style and identity exact'
        if uid==plan['pcbUuid'] and kind=='COMPONENT' and rid in targets and old and new:
            x,y=copy.deepcopy(old),copy.deepcopy(new)
            for k in allowed:x.get('attrs',{}).pop(k,None);y.get('attrs',{}).pop(k,None)
            if targets[rid]['ref'] in ['R197','R202'] and x['angle']==270 and y['angle']==-90:
                angle_normalizations.append({'ref':targets[rid]['ref'],'before':270,'after':-90,'physicalRotationIdentical':True});y['angle']=270
            ok=x==y;reason='Target COMPONENT metadata; all physical properties exact except explicit 270/-90 serialization'
        edits={x['id']:x for x in plan['pages'].get(uid,{}).get('textEdits',[])}
        if kind=='TEXT' and rid in edits and old and new:
            x,y=copy.deepcopy(old),copy.deepcopy(new);x.pop('value',None);y.pop('value',None);ok=x==y and new['value']==edits[rid]['after'];reason='Two reviewed nominal transfer annotations only'
        if kind in ['CANVAS','ACTIVE_LAYER','ELE_PLACEHOLDER']:
            # No physical primitive or rule exemption. These are editor view state.
            ok=True;reason='Editor view state only'
        row={'document':uid,'type':kind,'id':rid,'key':(new or old).get('key'),'allowed':ok,'reason':reason}
        changes.append(row)
        if not ok:errors.append(row)
pcb=after[plan['pcbUuid']];pa=review.attributes(pcb);sch={};sch_ids={}
for uid,d in after.items():
    if d['head']['docType']!='SCH_PAGE':continue
    aa=review.attributes(d)
    for (k,cid),(_,body) in d['records'].items():
        if k=='COMPONENT' and aa.get(cid,{}).get('Designator'):
            ref=aa[cid]['Designator'];sch.setdefault(ref,{}).update(aa[cid]);sch_ids.setdefault(ref,[]).append(cid)
parts=[]
for t in plan['pcbTargets']:
    sc=sch[t['ref']];pc={**pcb['records'][('COMPONENT',t['componentId'])][1].get('attrs',{}),**pa[t['componentId']]}
    assert sc['Manufacturer Part']==pc['Manufacturer Part']==t['spec']['mpn']
    assert sc['Supplier Part']==pc['Supplier Part']==t['spec']['lcsc']
    assert sc['Unique ID']==pc['Unique ID']==t['beforeAttrs']['Unique ID']
    assert sc['Value']==pc['Value']
    parts.append({'ref':t['ref'],'beforeValue':t['spec']['oldValue'],'value':sc['Value'],'mpn':sc['Manufacturer Part'],'lcsc':sc['Supplier Part'],'manufacturer':sc['Manufacturer'],'package':'0402','tolerance':sc['Tolerance'],'tcr':sc['Temperature Coefficient'],'power':sc['Power Rating'],'description':sc['Description'],'url':t['spec']['Datasheet']})
assert len(parts)==25 and next(x for x in parts if x['ref']=='R201')['tcr']=='±400ppm/℃'
counts=collections.Counter(k for k,i in pcb['records']);assert counts['COMPONENT']==437 and counts['VIA']==704 and counts['PAD_NET']==1523
assert len(attribute_defaults)==120
report={'schema':'standard-values-durable-audit-v1','sourceBeforeSHA256':sha(beforepath),'sourceAfterSHA256':sha(afterpath),'documentsBefore':len(before),'documentsAfter':len(after),'changedDocuments':sorted({c['document'] for c in changes}),'recordChanges':changes,'angleSerialization':angle_normalizations,'attributeDefaultMaterialization':attribute_defaults,'errors':errors,'pcbRecordCounts':dict(counts),'metadataParts':25,'schematicPcbMpnAndValueMatch':True,'unchangedLibraries':all(before[u]['records']==after[u]['records'] for u in before if u not in page_targets),'electricalAndPhysicalRecordsPreserved':not errors,'scope':'Full durable document/record comparison, target metadata and two text annotations only; manufacturing release is separate.'}
dump('DURABLE_AUDIT.json',report);dump('standard-resistors-final-specs.json',parts)
if errors:raise AssertionError(json.dumps(errors[:12],ensure_ascii=False))
# Compare all fresh Gerber/drill members with previously audited geometry. Only
# comments are ignored; every fabrication command remains byte-for-byte equal.
oldzip=ROOT/'output/jlcpcb-20261019-review/native/STM32H747_CAM_20261019.zip'
newzip=OUT/'native/final/GERBER_REVIEW_NOT_FOR_ORDER.zip'
gsp=importlib.util.spec_from_file_location('stm_gerber',ROOT/'scripts/extract_gerber_reconstruction.py');gp=importlib.util.module_from_spec(gsp);gsp.loader.exec_module(gp)
parsed_dir=OUT/'local-parsed-cam';parsed_dir.mkdir(exist_ok=True)
def canonical_objects(name,data,label):
    p=parsed_dir/(label+'-'+name);p.write_bytes(re.sub(rb'(?m)^G54(D\d+\*)',rb'\1',data))
    layer=gp.parse_gerber(p,name);out=[]
    for obj in layer['objects']:
        obj=copy.deepcopy(obj)
        if obj['kind']=='region':obj.pop('aperture',None)
        else:
            ap=layer['apertures'][obj['aperture']]
            obj['aperture']={'template':ap['template'],'paramsMm':ap['paramsMm']}
        out.append(json.dumps(obj,sort_keys=True,separators=(',',':')))
    return out
def fab_commands(name,data):
    if name.lower().endswith('.drl'):return b'\n'.join(x for x in data.splitlines() if not x.startswith(b';'))
    return b'\n'.join(x for x in data.splitlines() if not x.startswith(b'G04'))
members=[]
with zipfile.ZipFile(oldzip) as a,zipfile.ZipFile(newzip) as b:
    assert a.testzip() is None and b.testzip() is None
    assert set(a.namelist())==set(b.namelist())
    for name in a.namelist():
        old,new=a.read(name),b.read(name);same=fab_commands(name,old)==fab_commands(name,new)
        row={'file':name,'bytes':len(new),'sha256':hashlib.sha256(new).hexdigest(),'sameBytes':old==new,'sameFabricationCommands':same}
        if name.startswith('Gerber_'):
            x,y=canonical_objects(name,old,'before'),canonical_objects(name,new,'after');row.update({'sameParsedGeometry':x==y,'objectsBefore':len(x),'objectsAfter':len(y)})
            if x!=y:
                ax,by=collections.Counter(x),collections.Counter(y)
                row['removedObjects']=[json.loads(k) for k,n in (ax-by).items() for _ in range(n)]
                row['addedObjects']=[json.loads(k) for k,n in (by-ax).items() for _ in range(n)]
                # Reordering only dark primitives does not change the image.
                # Clear/dark order is never ignored for subtractive geometry.
                only_dark=all(json.loads(o)['polarity']=='dark' for o in x+y)
                row['sameRenderedPrimitives']=ax==by and only_dark
                row['darkOnlyDrawOrderChanged']=row['sameRenderedPrimitives']
            else:row['sameRenderedPrimitives']=True
        members.append(row)
dump('CAM_MEMBER_COMPARISON.json',members)
assert all(m.get('sameRenderedPrimitives',m['sameFabricationCommands']) for m in members if m['file']!='FlyingProbeTesting.json')
oldcam=json.loads((ROOT/'output/jlcpcb-20261019-review/CAM_AUDIT.json').read_text(encoding='utf8'))
cam={'sourceSHA256':sha(afterpath),'gerberSHA256':sha(newzip),'zipCRC':'PASS','members':members,'allGerberPrimitiveGeometryUnchanged':True,'allDrillCommandsUnchangedExceptComments':True,'flyingProbeJson':'Index ordering changed; not used to claim fabrication geometry equivalence. Source PAD_NET records are exact.','previousAudit':'../jlcpcb-20261019-review/CAM_AUDIT.json','copperLayers':oldcam['copperLayerCount'],'padCentreChecksCarriedByExactGeometry':oldcam['padCentreChecks'],'physicalDrills':oldcam['physicalDrillCount'],'assemblyParts':oldcam['assemblyParts'],'assemblySideCounts':oldcam['assemblySideCounts'],'rotationReviewRequired':oldcam['rotationReviewRequired'],'manufacturingApproved':False,'limits':'Exact Gerber primitive geometry and drill continuity carries prior bounded pad-centre/drill evidence, not external DFM or full polygon electrical certification.'}
dump('CAM_CONTINUITY_AUDIT.json',cam)
# Candidate coordinates retain the prior physical-side and pin-axis correction.
# No placement/footprint changed, and fresh native centroids must still match.
def native_csv(path):
    raw=path.read_bytes();return list(csv.DictReader(raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig').splitlines(),delimiter='\t'))
oldcpl=native_csv(ROOT/'output/jlcpcb-20261019-review/native/STM32H747_CPL_20261019.csv');newcpl=native_csv(OUT/'native/final/CPL_NATIVE.csv')
a={r['Designator']:r for r in oldcpl};b={r['Designator']:r for r in newcpl};assert set(a)==set(b) and len(a)==437
for ref in a:
    for k in ['Mid X','Mid Y','Rotation','Layer']:assert a[ref][k]==b[ref][k],(ref,k)
(OUT/'CPL_CANDIDATE_REVIEW_ONLY.csv').write_bytes((ROOT/'output/jlcpcb-20261019-review/CPL_CANDIDATE.csv').read_bytes())
dump('PLACEMENT_CONTINUITY_AUDIT.json',{'nativeCentroidsChecked':437,'allCentroidsRotationsAndNativeLayersUnchanged':True,'candidateAssemblyParts':412,'sideCorrectionInherited':True,'canonicalRotationStillPending':oldcam['rotationReviewRequired'],'notForOrder':True})
print(json.dumps({'documents':len(after),'changedDocuments':report['changedDocuments'],'resistors':25,'pcbCounts':dict(counts),'gerberPrimitiveGeometryUnchanged':True,'errors':len(errors)},ensure_ascii=False))
