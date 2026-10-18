const project = await eda.dmt_Project.getCurrentProjectInfo();
const before = await eda.dmt_Schematic.getAllSchematicsInfo();
const ESYS_ImportProjectImportOption={IMPORT_DOCUMENT:'ImportDocument'};
const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-schematics/STM32H747_MCU_BOARD_v19_schematics_native.epro2');
if (!file) throw new Error('Native schematic package missing');
const imported=await eda.sys_FileManager.importProjectByProjectFile(file,'EasyEDA Pro',{importOption:ESYS_ImportProjectImportOption.IMPORT_DOCUMENT},{operation:'Existing Project',existingProjectUuid:project.uuid});
if (!imported) throw new Error('Native import failed');
return {imported,before:before.map(s=>({uuid:s.uuid,name:s.name})),after:(await eda.dmt_Schematic.getAllSchematicsInfo()).map(s=>({uuid:s.uuid,name:s.name,pages:s.page?.map(p=>({uuid:p.uuid,name:p.name}))}))};
