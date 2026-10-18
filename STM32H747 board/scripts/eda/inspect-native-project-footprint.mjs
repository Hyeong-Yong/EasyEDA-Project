const library=await eda.lib_LibrariesList.getProjectLibraryUuid();
if(!library)throw new Error('Current project library unavailable');
const footprintUuid='e2e3d06dac58c326';
const tab=await eda.dmt_EditorControl.openLibraryDocument(library,'4',footprintUuid);
if(!tab)return {library,opened:false};
const source=await eda.sys_FileManager.getDocumentSource();
if(!source||!source.includes(footprintUuid))throw new Error('Footprint document source identity not confirmed');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-project-C1-footprint.epru',new Blob([source]),undefined,false);
return {library,tab,saved,bytes:source.length};
