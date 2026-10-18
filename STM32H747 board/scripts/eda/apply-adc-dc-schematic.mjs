const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8';
const expected=__taskArgs[0];
if(!/^[a-f0-9]{64}$/.test(expected||''))throw new Error('Reviewed ADC candidate SHA256 required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC schematic');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(root+p);if(!f)throw new Error('Missing reviewed file '+p);return await f.text();};
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const candidate=await load('/output/candidates/adc-dc-buffer/06_ADC_TIMER_DAC_dc_buffer_candidate.epru');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(candidate)))).map(x=>x.toString(16).padStart(2,'0')).join('');
const plan=JSON.parse(await load('/output/candidates/adc-dc-buffer/adc-dc-schematic-plan.json'));
if(hash!==expected||hash!==plan.candidateSha256||plan.pageUuid!==uuid||plan.electricalContract.dcCoupled!==true||plan.electricalContract.seriesCouplingCapacitors!==0)throw new Error('ADC plan identity/contract changed');
const before=parse(await load('/output/validation/native-adc-dc-before-page-6-20261016.epru'));
const source=await eda.sys_FileManager.getDocumentSource(),current=parse(source),map=new Map(current.map(r=>[r.h.type+':'+r.h.id,r]));
if(current.length!==before.length||current[0]?.b.uuid!==uuid)throw new Error('ADC source inventory changed');
for(const r of before)if(!['DOCHEAD','CANVAS'].includes(r.h.type)&&canonical(r.b)!==canonical(map.get(r.h.type+':'+r.h.id)?.b))throw new Error('Unreviewed schematic change '+r.h.type+':'+r.h.id);
if(!await eda.sys_FileManager.setDocumentSource(candidate))throw new Error('ADC source update rejected');
const target=parse(candidate),changed=new Set(plan.changes.map(r=>r.type+':'+r.id)),added=new Set(plan.added.map(r=>r.h.type+':'+r.h.id));
const critical={COMPONENT:['partId','x','y','rotation','isMirror','attrs'],ATTR:['key','value','parentId','keyVisible','valueVisible'],LINE:['startX','startY','endX','endY','lineGroup'],TEXT:['x','y','value','fontSize'],WIRE:[]};
const verify=async stage=>{
 const actualSource=await eda.sys_FileManager.getDocumentSource(),actual=parse(actualSource),actualMap=new Map(actual.map(r=>[r.h.type+':'+r.h.id,r])),errors=[];
 if(actual.length!==target.length||actual[0]?.b.uuid!==uuid)errors.push({error:'identity-or-count',expected:target.length,actual:actual.length});
 for(const r of target){
  const key=r.h.type+':'+r.h.id,a=actualMap.get(key);
  if(!a){errors.push({key,error:'missing'});continue;}
  if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;
  if(!changed.has(key)&&!added.has(key)){if(canonical(a.b)!==canonical(r.b))errors.push({key,error:'protected-body-change'});continue;}
  for(const field of critical[r.h.type]||[])if(canonical(a.b[field])!==canonical(r.b[field]))errors.push({key,field,expected:r.b[field],actual:a.b[field]});
 }
 for(const r of plan.deleted)if(actualMap.has(r.h.type+':'+r.h.id))errors.push({key:r.h.type+':'+r.h.id,error:'obsolete-record-remains'});
 const path=root+'/output/validation/native-adc-dc-'+stage+'-20261016.epru';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([actualSource]),undefined,false))throw new Error('ADC verification capture failed');
 const receiptPath=root+'/output/validation/native-adc-dc-'+stage+'-receipt-20261016.json';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,candidateSha256:hash,stage,recordCount:actual.length,errors},null,2)]),undefined,false))throw new Error('ADC verification receipt failed');
 if(errors.length)throw new Error('ADC source verification failed; inspect '+receiptPath);
 return {path,recordCount:actual.length,errors:0};
};
const accepted=await verify('accepted');
if(!await eda.sch_Document.save())throw new Error('ADC schematic save failed');
const info=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(!await eda.dmt_EditorControl.closeDocument(info.tabId||uuid))throw new Error('ADC saved page close failed');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('ADC reopen failed');
const reopened=await verify('reopened');
return{saved:true,accepted,reopened,components:plan.components.length,newComponents:plan.components.filter(c=>c.new).length};
