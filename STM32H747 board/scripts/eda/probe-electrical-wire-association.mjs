const wire=await eda.sch_PrimitiveWire.create([1205,-160,1170,-160],'Net-(U1B-PG0)','#009600',6,undefined);
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
if(!source)throw new Error('Native source missing');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-wire-association-probe.epru',new Blob([source],{type:'text/plain'}),undefined,false);
return {created:Boolean(wire),saved};
