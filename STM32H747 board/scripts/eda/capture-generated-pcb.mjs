const pcbUuid='3ca9811d1a42d086';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source)throw new Error('PCB source missing');
const counts={};
for(const line of source.split('\n')){if(!line.includes('||'))continue;const h=JSON.parse(line.split('||')[0]);counts[h.type]=(counts[h.type]||0)+1;}
if(counts.COMPONENT!==330)throw new Error('Generated PCB physical component count '+counts.COMPONENT);
const saved=await eda.pcb_Document.save();
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-generated.epru',new Blob([source]),undefined,false);
return {saved,sourceSaved,counts};
