const own=globalThis.__STM32H747_PUBLIC_3D_LIBRARY_20261018_V1__;
if(!own||own.libraryTitle!=='STM32H747_3D_LOCAL5_20261018'||own.result?.libraryUuid!=='extend_lib_STM32H747_3D_LOCAL5_20261018')throw new Error('Expected STM32-only public library registration missing');
const plan=own.result.applyPlan;
if(plan.entries.length!==5||plan.expectedProjectUuid!=='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c')throw new Error('Pinned private model plan mismatch');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/local5-session-model-plan.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}),undefined,false);
return {saved,path,libraryUuid:plan.libraryUuid,refs:plan.entries.map(e=>e.ref)};
