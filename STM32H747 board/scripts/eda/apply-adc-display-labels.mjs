const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC page');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(root+p);if(!f)throw new Error('Missing '+p);return await f.text();};
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const baseline=parse(await load('/output/validation/native-adc-dc-final-reopened-20261016.epru')),source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),map=new Map(before.map(r=>[r.h.type+':'+r.h.id,r]));
if(before.length!==baseline.length)throw new Error('ADC display baseline count changed');
for(const r of baseline)if(!['DOCHEAD','CANVAS'].includes(r.h.type)&&canonical(map.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))throw new Error('ADC display baseline changed '+r.h.id);
const plan=JSON.parse(await load('/output/candidates/adc-dc-buffer/adc-dc-18-display-attrs-plan.json'));
if(plan.pageUuid!==uuid||plan.edits.length!==18)throw new Error('ADC display plan identity changed');
for(const e of plan.edits){if(e.type!=='ATTR'||canonical(map.get('ATTR:'+e.id)?.b)!==canonical(e.before))throw new Error('ADC display target changed');const a={...e.before},b={...e.after};delete a.x;delete a.y;delete b.x;delete b.y;if(canonical(a)!==canonical(b))throw new Error('Only XY display changes allowed');}
const candidate=await load('/output/candidates/adc-dc-buffer/06_ADC_TIMER_DAC_display_labels_candidate.epru');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(candidate)))).map(x=>x.toString(16).padStart(2,'0')).join('');
if(hash!=='643b9f9cb8214bbe017a5a5ccf5a44a9705e0eafc6df1ee61715f48b9a4703fe')throw new Error('Reviewed display candidate changed');
if(!await eda.sys_FileManager.setDocumentSource(candidate)||!await eda.sch_Document.save())throw new Error('Display source/save failed');
await eda.dmt_EditorControl.closeDocument((await eda.dmt_SelectControl.getCurrentDocumentInfo()).tabId||uuid);
await eda.dmt_EditorControl.openDocument(uuid);
const finalSource=await eda.sys_FileManager.getDocumentSource(),after=parse(finalSource),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r])),targets=new Map(plan.edits.map(e=>[e.id,e.after])),errors=[];
for(const r of before){if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;const e=targets.get(r.h.id)||r.b,a=actual.get(r.h.type+':'+r.h.id);if(canonical(a?.b)!==canonical(e))errors.push({id:r.h.id,type:r.h.type,expected:e,actual:a?.b});}
if(after.length!==before.length)errors.push({error:'record count'});
const path=root+'/output/validation/native-adc-dc-display-final-reopened-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([finalSource]),undefined,false);
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-adc-display-labels-receipt-20261016.json',new Blob([JSON.stringify({saved:true,path,changes:18,errors},null,2)]),undefined,false);
if(errors.length)throw new Error('ADC display preservation failed '+errors.length);return{saved:true,path,changes:18,errors:0};
