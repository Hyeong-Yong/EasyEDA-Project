const uuid='0ac2a19168000d8e';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong final PCB');
const pads=await eda.pcb_PrimitivePad.getAll();
const selected=pads.filter(p=>p.getState_PrimitiveId().startsWith('8dfdc04036ba85c3')).map(p=>({id:p.getState_PrimitiveId(),padNumber:p.getState_PadNumber(),x:p.getState_X(),y:p.getState_Y(),pad:p.getState_Pad()}));
const report={pcbUuid:uuid,totalPads:pads.length,selected};
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-cn1-runtime-pads.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(report,null,2)]),undefined,false);
return {saved,path,totalPads:pads.length,selectedPads:selected.length};
