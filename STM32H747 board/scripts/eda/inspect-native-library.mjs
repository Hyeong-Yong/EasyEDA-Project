const libraryUuid = await eda.lib_LibrariesList.getProjectLibraryUuid();
const pages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
const source = await eda.sys_FileManager.getDocumentSource();
return {libraryUuid,pages:pages.map(x=>({uuid:x.uuid,name:x.name})),sourcePrefix:source?.slice(0,2000),sourceBytes:source?.length};
