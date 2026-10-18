const project = await eda.dmt_Project.getCurrentProjectInfo();
const before = await eda.dmt_Schematic.getAllSchematicPagesInfo();
const ESYS_ImportProjectImportOption = {IMPORT_DOCUMENT:'ImportDocument'};
const file = await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-schematics/STM32H747_MCU_BOARD_v19_schematics_draft.epro2');
if (!file) throw new Error('Draft package is unreadable');
const imported = await eda.sys_FileManager.importProjectByProjectFile(file,'EasyEDA Pro',{importOption:ESYS_ImportProjectImportOption.IMPORT_DOCUMENT},{operation:'Existing Project',existingProjectUuid:project.uuid});
if (!imported) throw new Error('Existing project import failed');
const pages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
return {imported,before:before.map(x=>({uuid:x.uuid,name:x.name})),after:pages.map(x=>({uuid:x.uuid,name:x.name,parent:x.parentSchematicUuid}))};
