const p=await eda.dmt_Project.getCurrentProjectInfo();
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/source-models/kicad/Capacitor_SMD.3dshapes/C_0402_1005Metric.step';
const file=await eda.sys_FileSystem.readFileFromFileSystem(path);
if(!file||file.size!==43502)throw new Error('Reviewed STEP source mismatch');
const ESYS_Unit={MILLIMETER:'mm'};
const uuids=await eda.lib_3DModel.create(p.uuid,file,[],ESYS_Unit.MILLIMETER);
return {targetProject:p.uuid,path,uuids:uuids||null};
