const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',stage=__taskArgs[0];
if(!/^[a-z0-9_-]{3,50}$/.test(stage||''))throw new Error('Scoped save stage required');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Approved PCB must remain active');
if(!await eda.pcb_Document.save())throw new Error('Native PCB save failed');
const source=await eda.sys_FileManager.getDocumentSource(),path=root+'/output/validation/native-adc10-pcb-'+stage+'_saved-20261018.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('Saved PCB capture failed');
return{saved:true,path,manufacturingReady:false};
