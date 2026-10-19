const p=await eda.dmt_Project.getCurrentProjectInfo();
const pages=await eda.dmt_Schematic.getAllSchematicPagesInfo();
const b=p.data.find(x=>x.itemType==='Board');
const target=pages.find(x=>x.parentSchematicUuid===b.schematic.uuid);
await eda.dmt_EditorControl.openDocument(target.uuid);
await new Promise(r=>setTimeout(r,500));
const details=await eda.sch_Drc.check(true,false,true);
const passed=await eda.sch_Drc.check(true,false,false);
return {project:p.friendlyName,details,passed,log:await eda.sys_Log.sort()};
