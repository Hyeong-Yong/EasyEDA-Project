const key=__taskArgs[0];
if(!key||key.length>100)throw new Error('Model search keyword required');
const libraryUuid=await eda.lib_LibrariesList.getSystemLibraryUuid();
const models=await eda.lib_3DModel.search(key,libraryUuid,undefined,20,1);
return {libraryUuid,key,models};
