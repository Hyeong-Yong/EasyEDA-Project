await eda.dmt_EditorControl.openDocument('e8a4e3fabe30ab59');
await new Promise(r=>setTimeout(r,500));
const page=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(page?.uuid!=='e8a4e3fabe30ab59')throw new Error('Wrong MCU page');
return {page:{uuid:page.uuid,name:page.name},ercPassed:await eda.sch_Drc.check(true,true,false)};
