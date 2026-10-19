const libraryUuid=await eda.lib_LibrariesList.getProjectLibraryUuid();if(libraryUuid!=='project')throw new Error('Current project library required');
const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/source-models/kicad/Capacitor_SMD.3dshapes/C_0402_1005Metric.step');
if(!file||file.size!==43502)throw new Error('Reviewed STEP file mismatch');
const named=new File([file],'STM32H747_C_0402_1005Metric.step',{type:'model/step'});
const ESYS_Unit={MILLIMETER:'mm'};
const result=await eda.lib_3DModel.create(libraryUuid,named,[],ESYS_Unit.MILLIMETER);
return {libraryUuid,name:named.name,result:result||null};
