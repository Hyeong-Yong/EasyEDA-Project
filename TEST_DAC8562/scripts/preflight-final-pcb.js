await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=='4e08f91f9a2c4fe4'||d.documentType!==3)throw new Error('Wrong PCB');
if(!await eda.pcb_Document.save())throw new Error('Cannot close unsaved PCB');
await eda.dmt_EditorControl.closeDocument('4e08f91f9a2c4fe4');
const reopened=await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
return {saved:true,reopened,passed:await eda.pcb_Drc.check(true,true,false),details:await eda.pcb_Drc.check(true,true,true),source:await eda.sys_FileManager.getDocumentSource()};
