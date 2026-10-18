const pcbUuid='6da689cbfc28e476';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong scoped staging PCB');
const rule=await eda.pcb_Drc.getCurrentRuleConfiguration();
const details=await eda.pcb_Drc.check(true,false,true);
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-drc-staging-details.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({pcbUuid,rule,details},null,2)]),undefined,false);
return {saved,path,isArray:Array.isArray(details),count:Array.isArray(details)?details.length:null};
