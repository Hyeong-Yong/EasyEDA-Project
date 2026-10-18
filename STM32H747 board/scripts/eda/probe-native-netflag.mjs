const flag=await eda.sch_PrimitiveComponent.createNetFlag('Power','+3V3',1800,-1200,0,false);
if(!flag)throw new Error('Native power-flag creation failed');
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-netflag-probe.epru',new Blob([source],{type:'text/plain'}),undefined,false);
const removed=await eda.sch_PrimitiveComponent.delete(flag);
return {saved,removed};
