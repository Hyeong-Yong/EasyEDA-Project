const p=await eda.dmt_Project.getCurrentProjectInfo();
const pages=await eda.dmt_Schematic.getAllSchematicPagesInfo();
await eda.dmt_EditorControl.openDocument(pages[0].uuid);
await new Promise(r=>setTimeout(r,500));
const details=await eda.sch_Drc.check(true,true,true);
return {project:p.friendlyName,details,log:await eda.sys_Log.sort()};
