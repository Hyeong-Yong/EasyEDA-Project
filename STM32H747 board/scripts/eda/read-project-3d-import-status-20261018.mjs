const libraryUuid=await eda.lib_LibrariesList.getProjectLibraryUuid();
const models=await eda.lib_3DModel.search('C_0402',libraryUuid,undefined,50,1);
return {libraryUuid,models};
