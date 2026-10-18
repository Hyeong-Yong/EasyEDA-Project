const pageNumber=Number(__taskArgs[0]);
if(![2,3,4,5,6].includes(pageNumber))throw new Error('Explicit PDF page required');
const configFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/config/easyeda-project.json');
const config=JSON.parse(await configFile.text());
const page=config.pages.find(p=>p.sourcePdfPage===pageNumber);
const tab=await eda.dmt_EditorControl.openDocument(page.uuid);
if((await eda.dmt_Schematic.getCurrentSchematicPageInfo())?.uuid!==page.uuid)throw new Error('Wrong schematic page');
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
const rows=parse(await eda.sys_FileManager.getDocumentSource());
const wireIds=new Set(rows.filter(r=>r.head.type==='WIRE').map(r=>r.head.id));
const attrs=rows.filter(r=>r.head.type==='ATTR'&&r.body.key==='NET'&&wireIds.has(r.body.parentId));
if(__taskArgs[1]==='pilot')attrs.splice(1);
for(const attr of attrs)attr.body.fontSize=0.001;
const source=rows.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))).join('|\n');
if(!await eda.sys_FileManager.setDocumentSource(source))throw new Error('Wire label font repair rejected');
if(!await eda.sch_Document.save())throw new Error('Wire font repair not saved');
await eda.dmt_EditorControl.closeDocument(tab);
await eda.dmt_EditorControl.openDocument(page.uuid);
const actual=await eda.sys_FileManager.getDocumentSource();
const after=new Map(parse(actual).filter(r=>r.head.id).map(r=>[r.head.id,r]));
for(const attr of attrs){const a=after.get(attr.head.id);if(a?.body.value!==attr.body.value||a.body.fontSize!==0.001)throw new Error('Reloaded wire label font/net incorrect');}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-wire-font-page-'+pageNumber+'.epru',new Blob([actual]),undefined,false);
return {page:pageNumber,wireLabels:attrs.length,sourceSaved};
