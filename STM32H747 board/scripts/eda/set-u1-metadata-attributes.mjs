const f=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/u1-multipart-metadata-repair.json');
const plan=JSON.parse(await f.text());
if(plan.targets.length!==4)throw new Error('Invalid U1 target count');
const pages={2:'e8a4e3fabe30ab59',3:'360993a3108b5759'};
const results=[];
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
for(const pageNumber of [2,3]){
const tab=await eda.dmt_EditorControl.openDocument(pages[pageNumber]);
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==pages[pageNumber])throw new Error('Wrong U1 page');
const originalRows=parse(await eda.sys_FileManager.getDocumentSource());
const targetIds=new Set(plan.targets.filter(t=>t.pdf_page===pageNumber).map(t=>t.native_component_id));
const generatedNullKeys=new Set(['Manufacturer','Manufacturer Part','Supplier','Supplier Part']);
const rows=originalRows.filter(r=>!(r.head.type==='ATTR'&&targetIds.has(r.body.parentId)&&generatedNullKeys.has(r.body.key)&&r.body.value===null));
const removedGeneratedNullAttributes=originalRows.length-rows.length;
let ticket=Math.max(...rows.map(r=>r.head.ticket||0));
let added=0;
for(const target of plan.targets.filter(t=>t.pdf_page===pageNumber)){
const component=rows.find(r=>r.head.id===target.native_component_id);
const attrs=rows.filter(r=>r.head.type==='ATTR'&&r.body.parentId===target.native_component_id);
if(component?.body.partId!==target.part_id||attrs.find(r=>r.body.key==='Designator')?.body.value!=='U1')throw new Error('Wrong U1 identity');
let seq=0;
for(const [key,value] of Object.entries(target.set_properties)){
if(!plan.strict_scope.allowed_property_keys.includes(key))throw new Error('Out-of-scope U1 metadata');
const old=attrs.find(r=>r.body.key===key);
if(old){old.body.value=value;continue;}
const id=target.native_component_id.slice(0,12)+'f'+String(++seq).padStart(3,'0');
if(rows.some(r=>r.head.id===id))throw new Error('Metadata id collision');
const body={...attrs.find(r=>r.body.key==='Device').body,key,value,keyVisible:false,valueVisible:false};
rows.push({head:{type:'ATTR',id,ticket:++ticket},body});
added++;
}
}
const source=rows.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))+'|').join('\n')+'\n';
if(!await eda.sys_FileManager.setDocumentSource(source))throw new Error('U1 metadata source rejected');
if(!await eda.sch_Document.save())throw new Error('U1 metadata save failed');
await eda.dmt_EditorControl.closeDocument(tab);
await eda.dmt_EditorControl.openDocument(pages[pageNumber]);
const live=await eda.sys_FileManager.getDocumentSource();
const after=parse(live);
for(const t of plan.targets.filter(t=>t.pdf_page===pageNumber)){for(const [key,value] of Object.entries(t.set_properties)){if(after.find(r=>r.head.type==='ATTR'&&r.body.parentId===t.native_component_id&&r.body.key===key)?.body.value!==value)throw new Error('Reloaded U1 metadata incorrect');}}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-u1-harmonized-page-'+pageNumber+'.epru',new Blob([live]),undefined,false);
results.push({page:pageNumber,added,removedGeneratedNullAttributes,sourceSaved});
}
return {results,ercPassed:await eda.sch_Drc.check(true,true,false)};
