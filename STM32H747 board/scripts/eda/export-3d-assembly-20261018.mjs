const stage=__taskArgs[0];if(!/^[a-z0-9_-]+$/.test(stage))throw new Error('Scoped 3D export name required');
const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('STM PCB must be current');
const file=await eda.pcb_ManufactureData.get3DFile('STM32H747_'+stage,'obj',['Component Model'],'Parts',false);
if(!file||file.size<1000)throw new Error('Native 3D assembly export missing');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/STM32H747_'+stage+'_'+file.name;
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false);
return {saved,path,bytes:file.size,name:file.name};
