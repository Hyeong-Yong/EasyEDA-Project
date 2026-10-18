const pageNumber=Number(__taskArgs[0]);
if(![2,3,4,5,6].includes(pageNumber))throw new Error('Explicit PDF page 2-6 required');
const planFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-component-link-rebind-plan.json');
if(!planFile)throw new Error('Native library map missing');
const plan=JSON.parse(await planFile.text());
if(plan.summary.errors!==0||plan.summary.component_instances!==486)throw new Error('Native library map invalid');
const page=plan.pages.find(p=>p.page===pageNumber);
const tab=await eda.dmt_EditorControl.openDocument(page.checkpoint_document_uuid);
await new Promise(r=>setTimeout(r,400));
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==page.checkpoint_document_uuid)throw new Error('Wrong dedicated schematic page');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source)throw new Error('Native source missing');
const rows=source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});
const index=new Map(rows.filter(r=>r.head.id).map(r=>[r.head.id,r]));
let bodyChanges=0,childChanges=0;
for(const instance of page.instances){
const component=index.get(instance.component_id);
if(component?.head.type!=='COMPONENT')throw new Error('Component identity mismatch');
for(const change of instance.changes){
const attr=index.get(change.attribute_id);
if(attr?.head.type!=='ATTR'||attr.body.parentId!==instance.component_id||attr.body.key!==change.key)throw new Error('Library attribute identity mismatch');
if(![change.old_uuid,change.new_uuid].includes(attr.body.value))throw new Error('Unexpected child library UUID');
if(attr.body.value!==change.new_uuid){attr.body.value=change.new_uuid;childChanges++;}
const field=change.key+'Name';
const packed=component.body.attrs?.[field];
if(packed===undefined||packed==='')continue;
if(typeof packed!=='string')throw new Error('Library name metadata is not JSON string');
const metadata=JSON.parse(packed);
if(![change.old_uuid,change.new_uuid].includes(metadata.uuid))throw new Error('Unexpected body library UUID');
if(metadata.uuid!==change.new_uuid){metadata.uuid=change.new_uuid;component.body.attrs[field]=JSON.stringify(metadata);bodyChanges++;}
}
}
const replacement=rows.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))+'|').join('\n')+'\n';
const accepted=await eda.sys_FileManager.setDocumentSource(replacement);
if(!accepted)return {page:pageNumber,accepted:false,bodyChanges,childChanges};
const saved=await eda.sch_Document.save();
if(!saved)throw new Error('Durable schematic repair not saved');
await eda.dmt_EditorControl.closeDocument(tab);
await eda.dmt_EditorControl.openDocument(page.checkpoint_document_uuid);
await new Promise(r=>setTimeout(r,400));
const after=await eda.sys_FileManager.getDocumentSource();
const verified=new Map(after.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const head=JSON.parse(h),raw=b.replace(/\|$/,'');return [head.id,{head,body:raw?JSON.parse(raw):null}];}));
let verifiedBody=0,verifiedChild=0;
for(const instance of page.instances){
const component=verified.get(instance.component_id);
for(const change of instance.changes){
if(verified.get(change.attribute_id)?.body.value!==change.new_uuid)throw new Error('Reloaded child UUID incorrect');
verifiedChild++;
const packed=component.body.attrs?.[change.key+'Name'];
if(packed){if(JSON.parse(packed).uuid!==change.new_uuid)throw new Error('Reloaded body UUID incorrect');verifiedBody++;}
}
}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-durable-page-'+pageNumber+'.epru',new Blob([after]),undefined,false);
return {page:pageNumber,accepted,saved,bodyChanges,childChanges,verifiedBody,verifiedChild,sourceSaved};
