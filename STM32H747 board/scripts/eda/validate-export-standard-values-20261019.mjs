// Read-only validation/export of the current STM32 project after reviewed saves.
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019/native'+(__taskArgs.includes('--final')?'/final':'');
const pages=['e8a4e3fabe30ab59','360993a3108b5759','c0b1ffcb620d758f','3c13ef086afba6f5','a07bf8e4331877a8'];
const [action,arg]=__taskArgs;
const save=async(name,file)=>{if(!file)throw Error('No file '+name);if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/'+name,file,undefined,false))throw Error('Save refused '+name);return {name,bytes:file.size};};
if(action==='erc'||action==='erc_final'){
 if(!pages.includes(arg))throw Error('Explicit page required');await eda.dmt_EditorControl.openDocument(arg);
 if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==arg)throw Error('Wrong page');
 await new Promise(r=>setTimeout(r,1200));
 const violations=await eda.sch_Drc.check(true,true,true);
 await save(action+'-'+arg+'.json',new Blob([JSON.stringify({page:arg,violations},null,2)]));
 await save(action+'-schematic-'+arg+'.epru',new Blob([await eda.sys_FileManager.getDocumentSource()]));
 return {page:arg,violations};
}
if(action==='project')return await save('STM32H747_standard_values_verified_20261019.epro2',await eda.sys_FileManager.getProjectFile('STM32H747_standard_values_verified_20261019',undefined,'epro2'));
await eda.dmt_EditorControl.openDocument('0ac2a19168000d8e');
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!=='0ac2a19168000d8e')throw Error('Wrong PCB');
await new Promise(r=>setTimeout(r,1200));
if(action==='drc'){const violations=await eda.pcb_Drc.check(true,true,true);await save('strict-drc.json',new Blob([JSON.stringify({strict:true,violations},null,2)]));return{violations};}
if(action==='source')return await save('pcb.epru',new Blob([await eda.sys_FileManager.getDocumentSource()]));
if(action==='bom')return await save('BOM_NATIVE.csv',await eda.pcb_ManufactureData.getBomFile('STM32H747_standard_values_20261019','csv'));
if(action==='cpl')return await save('CPL_NATIVE.csv',await eda.pcb_ManufactureData.getPickAndPlaceFile('STM32H747_standard_values_20261019','csv','mm'));
if(action==='gerber')return await save('GERBER_REVIEW_NOT_FOR_ORDER.zip',await eda.pcb_ManufactureData.getGerberFile('STM32H747_standard_values_20261019'));
throw Error('Unknown explicit action');
