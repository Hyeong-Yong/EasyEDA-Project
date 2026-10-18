const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8',expectedHash=__taskArgs[0];
if(!/^[a-f0-9]{64}$/.test(expectedHash||''))throw new Error('Reviewed inline candidate hash required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC page');
const load=async path=>{const file=await eda.sys_FileSystem.readFileFromFileSystem(root+path);if(!file)throw new Error('Missing reviewed file '+path);return await file.text();};
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const baseline=parse(await load('/output/validation/native-adc-inline-before-20261016.epru')),source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),beforeMap=new Map(before.map(r=>[r.h.type+':'+r.h.id,r]));
if(before.length!==baseline.length||before[0]?.b.uuid!==uuid)throw new Error('Inline baseline count/identity changed');
for(const r of baseline)if(!['DOCHEAD','CANVAS'].includes(r.h.type)&&canonical(beforeMap.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))throw new Error('Inline baseline changed '+r.h.type+':'+r.h.id);
const candidate=await load('/output/candidates/adc-inline-wiring/06_ADC_TIMER_DAC_inline_candidate.epru');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(candidate)))).map(x=>x.toString(16).padStart(2,'0')).join('');
if(hash!==expectedHash)throw new Error('Reviewed inline candidate changed');
const target=parse(candidate),targetMap=new Map(target.map(r=>[r.h.type+':'+r.h.id,r]));
if(target[0]?.b.uuid!==uuid||target[0]?.b.docType!=='SCH_PAGE')throw new Error('Invalid target page');
const refs=rows=>rows.filter(r=>r.h.type==='ATTR'&&r.b.key==='Designator').map(r=>r.b.value).filter(v=>v&&!v.startsWith('#')).sort();
const beforeRefs=refs(before).filter(v=>!['R146','R147','R148'].includes(v));
if(canonical(beforeRefs)!==canonical(refs(target))||refs(target).some(v=>['R146','R147','R148'].includes(v)))throw new Error('Only DNP physical reference deletion allowed');
for(const r of target.filter(r=>r.h.type==='COMPONENT')){
 const old=beforeMap.get('COMPONENT:'+r.h.id);if(!old)throw new Error('No new component allowed in redraw');
 const a={...old.b},b={...r.b};delete a.x;delete a.y;delete b.x;delete b.y;
 if(canonical(a)!==canonical(b))throw new Error('Surviving component electrical identity changed '+r.h.id);
}
if(!await eda.sys_FileManager.setDocumentSource(candidate))throw new Error('Inline source rejected');
const actualSource=await eda.sys_FileManager.getDocumentSource(),actual=parse(actualSource),map=new Map(actual.map(r=>[r.h.type+':'+r.h.id,r])),errors=[];
for(const r of target){if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;const key=r.h.type+':'+r.h.id,a=map.get(key);if(canonical(a?.b)!==canonical(r.b))errors.push({key,expected:r.b,actual:a?.b});}
for(const r of actual)if(!targetMap.has(r.h.type+':'+r.h.id))errors.push({key:r.h.type+':'+r.h.id,error:'unexpected record'});
if(actual.length!==target.length)errors.push({error:'record count',expected:target.length,actual:actual.length});
const path=root+'/output/validation/native-adc-inline-accepted-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([actualSource]),undefined,false);
const receipt={uuid,candidateSha256:hash,sourcePath:path,expectedRecords:target.length,actualRecords:actual.length,errors,saved:false};
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-adc-inline-accepted-receipt-20261016.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
return{uuid,sourcePath:path,expectedRecords:target.length,actualRecords:actual.length,errors:errors.map(e=>({key:e.key,error:e.error})),saved:false};
