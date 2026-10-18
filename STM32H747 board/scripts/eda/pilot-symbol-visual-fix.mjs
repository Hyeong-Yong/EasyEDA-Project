const planFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-component-link-rebind-plan.json');
const plan=JSON.parse(await planFile.text());
const item=plan.library_map.symbol.find(x=>x.title.startsWith('C1_'));
if(!item)throw new Error('Exact imported C1 symbol missing');
const library=(await eda.dmt_Project.getCurrentProjectInfo()).uuid;
if(library!=='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c')throw new Error('Only dedicated project library may be edited');
const tab=await eda.lib_Symbol.openInEditor(item.imported_uuid,library);
if(!tab)throw new Error('C1 symbol not opened');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source.includes(item.imported_uuid))throw new Error('Current symbol UUID mismatch');
const beforeSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-C1-symbol-before-visual-fix.epru',new Blob([source]),undefined,false);
if(!beforeSaved)throw new Error('Symbol recovery source not saved');
const rows=source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});
let filledGlyphs=0,pins=0;
const numbers=new Map(rows.filter(r=>r.head.type==='ATTR'&&['NUMBER','Pin Number'].includes(r.body.key)).map(r=>[r.body.parentId,r.body.value]));
for(const r of rows){
if(r.head.type==='POLY'&&r.body.fillStyle==='SOLID'&&(r.body.strokeWidth===null||r.body.strokeWidth===0)){
r.body.strokeWidth=0.001;r.body.strokeColor=r.body.fillColor;filledGlyphs++;
}else if(r.head.type==='PIN'){
r.body.length=0.001;pins++;
}else if(r.head.type==='ATTR'&&['NAME','Pin Name'].includes(r.body.key)&&!r.body.value&&numbers.has(r.body.parentId)){
r.body.value=String(numbers.get(r.body.parentId));r.body.keyVisible=false;r.body.valueVisible=false;
}
}
if(pins!==2)throw new Error('C1 pilot must contain exactly two unchanged electrical endpoints');
const replacement=rows.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))).join('|\n');
const updated=await eda.sys_FileManager.setDocumentSource(replacement);
if(!updated)return {updated:false,library,symbol:item.imported_uuid};
const actual=await eda.sys_FileManager.getDocumentSource();
const saved=await eda.lib_Symbol.updateDocumentSource(item.imported_uuid,library,actual);
const editorSaved=await eda.sch_Document.save();
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-C1-symbol-visual-fixed.epru',new Blob([actual]),undefined,false);
return {library,symbol:item.imported_uuid,tab,updated,saved,editorSaved,sourceSaved,filledGlyphs,pins};
