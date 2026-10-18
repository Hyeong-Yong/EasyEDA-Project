const pcbUuid='3ca9811d1a42d086';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const rule=await eda.pcb_Drc.getCurrentRuleConfiguration();
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-rule-config-before.json',new Blob([JSON.stringify(rule,null,2)]),undefined,false);
return {saved,name:rule?.name,keys:Object.keys(rule?.config??{})};
