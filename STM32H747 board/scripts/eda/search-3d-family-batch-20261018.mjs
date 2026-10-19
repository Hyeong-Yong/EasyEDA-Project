const keys=JSON.parse(__taskArgs[0]||'[]');
if(!Array.isArray(keys)||keys.length<1||keys.length>12||keys.some(k=>typeof k!=='string'||k.length>100))throw new Error('1-12 model keys required');
const lib=await eda.lib_LibrariesList.getSystemLibraryUuid();
const results=await Promise.all(keys.map(async key=>({key,models:await eda.lib_3DModel.search(key,undefined,undefined,30,1)})));
const name=__taskArgs[1];if(!/^[a-z0-9_-]+$/.test(name))throw new Error('Scoped batch name required');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/'+name+'.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({lib,results},null,2)],{type:'application/json'}),undefined,false);
return {saved,path,summary:results.map(r=>({key:r.key,models:r.models.map(m=>({uuid:m.uuid,name:m.name}))}))};
