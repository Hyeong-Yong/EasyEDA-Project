const uuid='6da689cbfc28e476';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated staging PCB');
const components=await eda.pcb_PrimitiveComponent.getAll();
const list=components.map(c=>({id:c.getState_PrimitiveId(),reference:c.getState_Designator()}));
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-fresh-pcb-live-component-list.json',new Blob([JSON.stringify({uuid,count:list.length,components:list},null,2)]),undefined,false);
return {saved,count:list.length,first:list.slice(0,5),last:list.slice(-12)};
