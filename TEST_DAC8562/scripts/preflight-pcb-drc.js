await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=='4e08f91f9a2c4fe4'||d.documentType!==3)throw new Error('Wrong PCB');
return {passed:await eda.pcb_Drc.check(true,true,false),details:await eda.pcb_Drc.check(true,true,true),source:await eda.sys_FileManager.getDocumentSource()};
