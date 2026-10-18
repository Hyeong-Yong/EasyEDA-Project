const pages=['3278c4b2f6c424d2','c1fb7bedd62e38c3'];
const repaired=[];
for(const uuid of pages){
await eda.dmt_EditorControl.openDocument(uuid);
await new Promise(r=>setTimeout(r,500));
const page=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(page?.uuid!==uuid)throw new Error('Wrong power driver page');
const all=await eda.sch_PrimitiveComponent.getAll();
for(const component of all){
const ref=component.getState_Designator();
if(!ref?.startsWith('#FLG'))continue;
const before=component.getState_AddIntoPcb();
const changed=await eda.sch_PrimitiveComponent.modify(component,{addIntoPcb:false,addIntoBom:false});
if(!changed)throw new Error('Power-driver PCB exclusion failed');
const refreshed=await eda.sch_PrimitiveComponent.get(component.getState_PrimitiveId());
repaired.push({ref,before,after:refreshed?.getState_AddIntoPcb()});
}
const source=await eda.sys_FileManager.getDocumentSource();
await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-power-exclusion-'+uuid+'.epru',new Blob([source]),undefined,false);
await eda.sch_Document.save();
}
return {repaired};
