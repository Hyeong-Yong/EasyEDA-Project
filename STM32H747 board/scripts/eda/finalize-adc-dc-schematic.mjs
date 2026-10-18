const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8';
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('ADC page must remain active');
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const planFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/adc-dc-buffer/adc-dc-schematic-plan.json');
const plan=JSON.parse(await planFile.text());
const acceptedFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-adc-dc-accepted-20261016.epru');
if(!acceptedFile)throw new Error('Independently audited accepted source missing');
const before=parse(await acceptedFile.text());
const targets=plan.added.filter(r=>r.h.type==='ATTR'&&r.b.key==='NET');
const targetIds=new Set(targets.map(r=>r.h.id));
if(targets.length!==30||before.filter(r=>r.h.type==='COMPONENT').length!==143)throw new Error('Unexpected ADC finalization inventory');
for(const target of targets){
 const row=before.find(r=>r.h.id===target.h.id);
 if(row?.b.value!==target.b.value||row.b.parentId!==target.b.parentId)throw new Error('New ADC wire NET changed');
 const primitive=await eda.sch_PrimitiveAttribute.get(target.h.id);
 if(!primitive||Array.isArray(primitive))throw new Error('New NET attribute unavailable');
 const pending=primitive.toAsync();
 const ESCH_PrimitiveTextAlignMode={LEFT_BOTTOM:3};
 pending.setState_X(row.b.x);pending.setState_Y(row.b.y);pending.setState_AlignMode(ESCH_PrimitiveTextAlignMode.LEFT_BOTTOM);pending.setState_FontSize(0.001);await pending.done();
}
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),map=new Map(after.map(r=>[r.h.type+':'+r.h.id,r]));
const errors=[];
for(const r of before){
 if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;
 const actual=map.get(r.h.type+':'+r.h.id),expected={...r.b};
 if(targetIds.has(r.h.id))expected.fontSize=.001;
 if(!actual||canonical(actual.b)!==canonical(expected))errors.push(r.h.type+':'+r.h.id);
}
if(after.length!==before.length||errors.length)throw new Error('Only new NET font changes allowed '+errors.join(','));
if(!await eda.sch_Document.save())throw new Error('ADC save failed');
const path=root+'/output/validation/native-adc-dc-finalized-20261016.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('ADC finalized capture failed');
const tab=(await eda.dmt_SelectControl.getCurrentDocumentInfo()).tabId||uuid;
if(!await eda.dmt_EditorControl.closeDocument(tab))throw new Error('ADC close failed');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('ADC reopen failed');
const reopened=await eda.sys_FileManager.getDocumentSource();
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-adc-dc-reopened-20261016.epru',new Blob([reopened]),undefined,false))throw new Error('ADC reopened capture failed');
return{saved:true,netFontChanges:targets.length,finalizedPath:path,reopenedRecords:parse(reopened).length};
