const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC schematic page');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source||!source.includes('"uuid":"'+uuid+'"'))throw new Error('ADC source identity unavailable');
const path=root+'/output/validation/native-adc-inline-before-20261016.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('ADC baseline capture failed');
return{path,bytes:source.length};
