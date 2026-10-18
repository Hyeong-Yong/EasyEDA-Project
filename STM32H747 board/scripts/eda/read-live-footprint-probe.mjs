await eda.dmt_EditorControl.openDocument('e8a4e3fabe30ab59');
await new Promise(r=>setTimeout(r,400));
const components=await eda.sch_PrimitiveComponent.getAll();
const result=[];
for(const ref of ['C1','R1']){
const component=components.find(c=>c.getState_Designator()===ref);
if(!component)throw new Error('Footprint probe component missing');
const footprint=component.getState_Footprint();
if(footprint?.libraryUuid!=='project')throw new Error('Footprint is not bound to local project');
const source=await eda.lib_Footprint.getDocumentSource(footprint.uuid,'project');
if(!source)throw new Error('Bound native footprint source unavailable');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-bound-'+ref+'-footprint.efoo',new Blob([source]),undefined,false);
result.push({ref,footprint,saved,bytes:source.length});
}
return result;
