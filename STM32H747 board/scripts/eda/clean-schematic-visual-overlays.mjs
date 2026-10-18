const pageNumber=Number(__taskArgs[0]);
const companyOnly=__taskArgs[1]==='company_only';
if(![2,3,4,5,6].includes(pageNumber))throw new Error('Explicit PDF page 2-6 required');
const planFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-svg-overlay-repair-plan.json');
const plan=JSON.parse(await planFile.text());
const configFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/config/easyeda-project.json');
const config=JSON.parse(await configFile.text());
const page=config.pages.find(p=>p.sourcePdfPage===pageNumber);
const repair=plan.pages.find(p=>p.pdf_page===pageNumber);
if(!page||!repair||repair.strict_company_repair.target_ids.length!==13)throw new Error('Exact company removal plan missing');
const tab=await eda.dmt_EditorControl.openDocument(page.uuid);
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==page.uuid)throw new Error('Wrong dedicated schematic page');
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
const before=await eda.sys_FileManager.getDocumentSource();
const records=parse(before);
const remove=new Set(repair.strict_company_repair.target_ids);
let removed=0;
const remaining=records.filter(r=>{
if(!remove.has(r.head.id))return true;
if(r.head.type!=='POLY'||r.body.fillColor!=='#840000')throw new Error('Company glyph identity/style mismatch');
const points=r.body.points;
if(!points?.length||points.some(p=>p.x<1439||p.x>1577||p.y<1023||p.y>1049))throw new Error('Company glyph outside exact title band');
removed++;return false;
});
if(![0,13].includes(removed))throw new Error('Partial company glyph presence is unexpected');
if(removed){
const source=remaining.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))).join('|\n');
if(!await eda.sys_FileManager.setDocumentSource(source))throw new Error('Company glyph source repair rejected');
}
const current=parse(await eda.sys_FileManager.getDocumentSource());
const wireIds=new Set(current.filter(r=>r.head.type==='WIRE').map(r=>r.head.id));
const wireNets=current.filter(r=>r.head.type==='ATTR'&&r.body.key==='NET'&&wireIds.has(r.body.parentId));
let hidden=0;
for(let i=0;!companyOnly&&i<wireNets.length;i+=8){
const batch=wireNets.slice(i,i+8).filter(r=>r.body.valueVisible||r.body.keyVisible);
const results=await Promise.all(batch.map(r=>eda.sch_PrimitiveAttribute.modify(r.head.id,{keyVisible:false,valueVisible:false})));
if(results.some(r=>!r))throw new Error('Wire label visibility update failed');
hidden+=batch.length;
}
if(!await eda.sch_Document.save())throw new Error('Visual cleanup save failed');
await eda.dmt_EditorControl.closeDocument(tab);
await eda.dmt_EditorControl.openDocument(page.uuid);
const afterSource=await eda.sys_FileManager.getDocumentSource();
const after=parse(afterSource);
const map=new Map(after.filter(r=>r.head.id).map(r=>[r.head.id,r]));
for(const id of remove)if(map.has(id))throw new Error('Removed company glyph reappeared');
for(const r of wireNets){const a=map.get(r.head.id);if(a?.body.value!==r.body.value||a.body.parentId!==r.body.parentId||(!companyOnly&&(a.body.valueVisible||a.body.keyVisible)))throw new Error('Reloaded wire label visibility/net changed');}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-visual-clean-page-'+pageNumber+'.epru',new Blob([afterSource]),undefined,false);
return {page:pageNumber,companyOnly,removedCompanyGlyphs:removed,hiddenWireLabels:hidden,wireNetsChecked:wireNets.length,sourceSaved};
