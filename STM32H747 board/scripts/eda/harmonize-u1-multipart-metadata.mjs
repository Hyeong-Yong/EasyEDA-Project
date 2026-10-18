const f=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/u1-multipart-metadata-repair.json');
const plan=JSON.parse(await f.text());
if(plan.schema!=='stm32h747-u1-multipart-metadata-repair-v1'||plan.targets.length!==4)throw new Error('U1 repair proposal invalid');
const pages={2:'e8a4e3fabe30ab59',3:'360993a3108b5759'};
const results=[];
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
for(const pageNumber of [2,3]){
await eda.dmt_EditorControl.openDocument(pages[pageNumber]);
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==pages[pageNumber])throw new Error('U1 repair target changed');
const before=parse(await eda.sys_FileManager.getDocumentSource());
for(const target of plan.targets.filter(t=>t.pdf_page===pageNumber)){
const c=before.find(r=>r.head.id===target.native_component_id);
const designator=before.find(r=>r.head.type==='ATTR'&&r.body.parentId===target.native_component_id&&r.body.key==='Designator');
if(c?.head.type!=='COMPONENT'||c.body.partId!==target.part_id||designator?.body.value!=='U1')throw new Error('Wrong U1 multipart identity');
if(Object.keys(target.set_properties).some(k=>!plan.strict_scope.allowed_property_keys.includes(k)))throw new Error('U1 repair property out of scope');
const updated=await eda.sch_PrimitiveComponent.modify(target.native_component_id,{otherProperty:target.set_properties});
if(!updated)throw new Error('U1 property repair rejected');
}
const after=parse(await eda.sys_FileManager.getDocumentSource());
for(const record of before.filter(r=>!['DOCHEAD','COMPONENT','ATTR'].includes(r.head.type))){
const live=after.find(r=>r.head.id===record.head.id);
if(!live||JSON.stringify(live.body)!==JSON.stringify(record.body))throw new Error('Unexpected non-metadata geometry/electrical change');
}
for(const target of plan.targets.filter(t=>t.pdf_page===pageNumber)){
const b=before.find(r=>r.head.id===target.native_component_id).body;
const a=after.find(r=>r.head.id===target.native_component_id).body;
for(const key of ['x','y','rotation','isMirror','partId'])if(a[key]!==b[key])throw new Error('U1 geometry changed');
for(const [key,value] of Object.entries(target.set_properties)){
const found=after.find(r=>r.head.type==='ATTR'&&r.body.parentId===target.native_component_id&&r.body.key===key);
if(found?.body.value!==value)throw new Error('U1 property postcondition failed');
}
for(const record of before.filter(r=>r.head.type==='ATTR'&&r.body.parentId===target.native_component_id&&!plan.strict_scope.allowed_property_keys.includes(r.body.key))){
const live=after.find(r=>r.head.id===record.head.id);
if(live?.body.value!==record.body.value)throw new Error('U1 identity/binding/electrical attribute changed');
}
}
const source=await eda.sys_FileManager.getDocumentSource();
const saved=await eda.sch_Document.save();
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-u1-harmonized-page-'+pageNumber+'.epru',new Blob([source]),undefined,false);
results.push({page:pageNumber,saved,sourceSaved,components:plan.targets.filter(t=>t.pdf_page===pageNumber).length});
}
return {results,ercPassed:await eda.sch_Drc.check(true,true,false)};
