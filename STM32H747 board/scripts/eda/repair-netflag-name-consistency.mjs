const info=await eda.dmt_Schematic.getSchematicInfo('416c10313f778784');
if(info?.page?.length!==5)throw new Error('Final schematic missing');
const changed=[];
for(const page of info.page){
await eda.dmt_EditorControl.openDocument(page.uuid);
await new Promise(r=>setTimeout(r,300));
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==page.uuid)throw new Error('NetFlag repair focus changed');
const source=await eda.sys_FileManager.getDocumentSource();
const records=source.split('\n').filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});
const attrs=records.filter(r=>r.head.type==='ATTR');
for(const global of attrs.filter(r=>r.body.key==='Global Net Name')){
const name=attrs.find(r=>r.body.parentId===global.body.parentId&&r.body.key==='Name');
if(!name)throw new Error('Native NetFlag Name missing');
if(name.body.value===global.body.value)continue;
if(!await eda.sch_PrimitiveAttribute.modify(name.head.id,{value:global.body.value}))throw new Error('Native NetFlag Name consistency update failed');
changed.push({page:page.uuid,parent:global.body.parentId,before:name.body.value,after:global.body.value});
}
await eda.sch_Document.save();
}
return {changed};
