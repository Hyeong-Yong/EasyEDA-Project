const uuid='9a0a68d8722d6718';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong isolated PCB probe');
const EPCB_LayerId={TOP:1};
let result;
try{
const component=await eda.pcb_PrimitiveComponent.create({libraryUuid:'project',uuid:'cb86d3189a2b1e76'},EPCB_LayerId.TOP,500,500,0,false);
result={created:!!component,id:component?.getState_PrimitiveId(),footprint:component?.getState_Footprint()};
}catch(error){result={created:false,error:String(error),stack:String(error?.stack||'')};}
const source=await eda.sys_FileManager.getDocumentSource();
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-cn1-api-create.epru',new Blob([source]),undefined,false);
return {uuid,result,saved,liveComponents:(await eda.pcb_PrimitiveComponent.getAll()).length};
