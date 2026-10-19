const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const queries=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/queries.json')).text());
const start=Number(__taskArgs[0]);if(!Number.isInteger(start)||start<0)throw Error('Explicit query start required');
const result=await Promise.all(queries.slice(start,start+6).map(async key=>({key,items:await eda.lib_Device.search(key,undefined,undefined,undefined,8,1)})));
const path=root+'/queries-'+start+'.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({readOnly:true,queriedAt:new Date().toISOString(),result},null,2)]),undefined,false))throw Error('Refuse overwrite');
return {path,counts:result.map(x=>({key:x.key,count:x.items.length}))};
