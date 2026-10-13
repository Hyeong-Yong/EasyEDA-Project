await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='4e08f91f9a2c4fe4'||d.documentType!==3)throw new Error('Wrong PCB');
const ESYS_NetlistType={PROTEL2:'Protel2'};
return {netlist:await eda.pcb_Net.getNetlist(ESYS_NetlistType.PROTEL2),source:await eda.sys_FileManager.getDocumentSource()};
