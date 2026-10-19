const uuid='360993a3108b5759';
if(!await eda.dmt_EditorControl.openDocument(uuid))throw new Error('Power page open failed');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong document');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source||!source.includes('"uuid":"'+uuid+'"'))throw new Error('Source identity mismatch');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-adc10-labtool-page03-preapply-live-20261018.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('Capture failed');
return {path,characters:source.length};
