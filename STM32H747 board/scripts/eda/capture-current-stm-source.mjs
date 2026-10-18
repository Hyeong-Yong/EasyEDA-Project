const name=__taskArgs[0];
if(!name||!/^[a-z0-9_-]{3,70}$/.test(name))throw new Error('Scoped source capture name required');
const source=await eda.sys_FileManager.getDocumentSource();
if(!source)throw new Error('Native source missing');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/'+name+'.epru',new Blob([source]),undefined,false);
return {saved,bytes:source.length};
