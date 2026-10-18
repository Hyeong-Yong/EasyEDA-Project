const uuid='6da689cbfc28e476';
if((await eda.dmt_Project.getCurrentProjectInfo())?.uuid!=='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c')throw new Error('Wrong dedicated project');
const tab=await eda.dmt_EditorControl.openDocument(uuid);
const info=await eda.dmt_Pcb.getCurrentPcbInfo();
if(info?.uuid!==uuid||info.name!=='STM32H747_PCB_WORK')throw new Error('Wrong dedicated PCB staging');
await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
return info;
