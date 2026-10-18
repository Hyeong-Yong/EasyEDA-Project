await eda.dmt_EditorControl.openDocument('6e1143375f4d7b58');
const component = await eda.sch_PrimitiveComponent.create({libraryUuid:'project',uuid:'e8ed94a65b5ef18b'},200,200,undefined,0,false,true,true);
if (!component) throw new Error('Project device placement failed');
const source = await eda.sys_FileManager.getDocumentSource();
const removed = await eda.sch_PrimitiveComponent.delete(component);
if (!removed) throw new Error('Temporary format probe removal failed');
return {removed,source};
