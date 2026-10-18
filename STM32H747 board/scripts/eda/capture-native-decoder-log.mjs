const logs=await eda.sys_Log.sort();
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-decoder-log.json',new Blob([JSON.stringify(logs,null,2)]),undefined,false);
return {saved,count:logs.length,last:logs.slice(-18)};
