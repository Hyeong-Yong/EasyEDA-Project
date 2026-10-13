// DFM reference, never a fabrication release: R102 connection remains protected.
await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='4e08f91f9a2c4fe4'||d.documentType!==3)throw new Error('Wrong PCB');
const details=await eda.pcb_Drc.check(true,true,true);
if(details.length!==1||details[0].name!=='Netlist Error'||details[0].count!==1)throw new Error('Unexpected PCB DRC errors');
const f=await eda.pcb_ManufactureData.getGerberFile('DAC8562_DFM_REFERENCE_R102_PENDING');
if(!f)throw new Error('Gerber export failed');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/manufacturing-preflight/DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber.zip',f,undefined,false);
if(!saved)throw new Error('Destination exists or export failed');
return {saved,name:f.name,size:f.size,fabricationReleased:false,details};
