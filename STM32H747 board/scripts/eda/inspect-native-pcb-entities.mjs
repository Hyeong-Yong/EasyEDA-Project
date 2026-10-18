const pcbUuid='3ca9811d1a42d086';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const components=await eda.pcb_PrimitiveComponent.getAll();
const top=await eda.pcb_PrimitiveComponent.getAll(1);
const source=await eda.sys_FileManager.getDocumentSource();
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-current-entities.epru',new Blob([source]),undefined,false);
return {count:components.length,topCount:top.length,sourceSaved,sample:top.slice(0,1)};
