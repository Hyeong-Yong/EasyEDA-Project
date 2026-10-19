const codes=['C852810','C2692906','C2103244','C44198','C2693067','C2692924'];
const result=await Promise.all(codes.map(async code=>({code,items:await eda.lib_Device.searchByProperties({supplierId:code},undefined,undefined,undefined,3,1)})));
await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019/selected-library-properties.json',new Blob([JSON.stringify(result,null,2)]),undefined,false);
return result.map(x=>({code:x.code,count:x.items.length}));
