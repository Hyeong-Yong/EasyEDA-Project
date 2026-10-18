const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Saved PCB must remain active');
if(!await eda.dmt_EditorControl.closeDocument((await eda.dmt_SelectControl.getCurrentDocumentInfo()).tabId||uuid))throw new Error('Saved PCB close failed');
if(!await eda.dmt_EditorControl.openDocument(uuid))throw new Error('Saved PCB reopen failed');
const source=await eda.sys_FileManager.getDocumentSource(),path=root+'/output/validation/native-adc10-pcb-oriented_reopened-20261017.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('Reopened oriented PCB capture failed');
return{path,manufacturingReady:false};
