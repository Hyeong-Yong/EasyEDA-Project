await eda.dmt_EditorControl.openDocument('6e1143375f4d7b58');
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
if (!source) throw new Error('Source missing');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/nativeblank-6e-getter.epru',new Blob([source],{type:'text/plain'}),undefined,false);
return {saved,bytes:source.length};
