const schematic=await eda.dmt_Schematic.getSchematicInfo('dfec14d6b0ca29c3');
const first=schematic?.page?.find(p=>p.name.toLowerCase()==='02_mcu');
if(!first||schematic.page.length!==5)throw new Error('Five-page schematic not synchronized');
const tab=await eda.dmt_EditorControl.openDocument(first.uuid);
await new Promise(r=>setTimeout(r,1000));
const page=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(page?.uuid!==first.uuid)throw new Error('Wrong active schematic');
const source=await eda.sys_FileManager.getDocumentSource();
const counts={};
for(const line of source.split('\n')){if(!line.includes('||'))continue;const h=JSON.parse(line.split('||')[0]);counts[h.type]=(counts[h.type]||0)+1;}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-final-mcu-runtime.epru',new Blob([source],{type:'text/plain'}),undefined,false);
const all=await eda.sch_PrimitiveComponent.getAll(undefined,true);
const types={};
const references=[];
for(const c of all){const type=c.getState_ComponentType();types[type]=(types[type]||0)+1;if(references.length<18)references.push({id:c.getState_PrimitiveId(),ref:c.getState_Designator(),type});}
const saved=await eda.sch_Document.save();
const zoom=await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
const passed=await eda.sch_Drc.check(true,true,false);
return {schematic:{uuid:schematic.uuid,name:schematic.name,pages:schematic.page.map(p=>({uuid:p.uuid,name:p.name}))},counts,sourceSaved,saved,zoom,types,references,ercPassed:passed};
