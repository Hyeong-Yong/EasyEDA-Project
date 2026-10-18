const requestedPage=Number(__taskArgs[0]);
if(![2,3,4,5,6].includes(requestedPage))throw new Error('Explicit PDF page argument 2-6 is required');
const planFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-component-link-rebind-plan.json');
if(!planFile)throw new Error('Verified library rebind plan missing');
const plan=JSON.parse(await planFile.text());
if(plan.summary.errors!==0||plan.summary.component_instances!==486)throw new Error('Rebind plan validation failed');
const selected=plan.pages.find(p=>p.page===requestedPage);
if(!selected)throw new Error('Rebind page missing');
await eda.dmt_EditorControl.openDocument(selected.checkpoint_document_uuid);
await new Promise(r=>setTimeout(r,500));
const current=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(current?.uuid!==selected.checkpoint_document_uuid)throw new Error('Rebind target page changed');
function recordsOf(source){
return new Map(source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const head=JSON.parse(h);const raw=b.replace(/\|$/,'');return [head.id,{head,body:raw?JSON.parse(raw):null}];}));
}
const source=await eda.sys_FileManager.getDocumentSource();
const records=recordsOf(source);
const changes=[];
let skipped=0;
for(const instance of selected.instances){
for(const change of instance.changes){
const record=records.get(change.attribute_id);
if(record?.head.type!=='ATTR'||record.body.parentId!==instance.component_id||record.body.key!==change.key)throw new Error('Rebind attribute identity mismatch');
if(record.body.value===change.new_uuid){skipped++;continue;}
if(record.body.value!==change.old_uuid)throw new Error('Unexpected existing library reference');
changes.push(change);
}
}
for(let start=0;start<changes.length;start+=8){
const batch=changes.slice(start,start+8);
const results=await Promise.all(batch.map(c=>eda.sch_PrimitiveAttribute.modify(c.attribute_id,{value:c.new_uuid})));
if(results.some(r=>!r))throw new Error('Native library reference update rejected');
}
const verified=await eda.sys_FileManager.getDocumentSource();
const after=recordsOf(verified);
for(const instance of selected.instances){for(const c of instance.changes){if(after.get(c.attribute_id)?.body.value!==c.new_uuid)throw new Error('Native library reference verification failed');}}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-rebound-page-'+requestedPage+'.epru',new Blob([verified]),undefined,false);
const saved=await eda.sch_Document.save();
return {page:requestedPage,uuid:current.uuid,changed:changes.length,alreadyCorrect:skipped,verifiedAttributes:selected.instances.reduce((n,i)=>n+i.changes.length,0),sourceSaved,saved};
