const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8',[stage,kind]=__taskArgs;
const date=__taskArgs[2]||'20261017';
if(!/^202610(?:17|18)$/.test(date))throw new Error('Reviewed validation date required');
if(!stage||!/^[a-z0-9_-]{3,50}$/.test(stage)||!['erc','netlist'].includes(kind))throw new Error('Scoped ADC10 validation stage required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC page');
if(kind==='erc'){
 const started=Date.now(),passed=await eda.sch_Drc.check(true,true,false),logs=(await eda.sys_Log.sort()).filter(r=>Number(r.timestamp)>=started);
 const path=root+'/output/validation/native-adc10-'+stage+'-erc-'+date+'.json';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({passed,logs,started},null,2)]),undefined,false))throw new Error('ADC10 ERC report save failed');
 return{passed,path};
}
const ESYS_NetlistType={ALTIUM_DESIGNER:'Protel2'},file=await eda.sch_ManufactureData.getNetlistFile('STM32H747_adc10_'+stage+'_'+date,ESYS_NetlistType.ALTIUM_DESIGNER);
if(!file)throw new Error('ADC10 native netlist export failed');
const path=root+'/output/validation/native-adc10-'+stage+'-Protel2-'+date+'.net';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw new Error('ADC10 netlist save failed');
return{path,bytes:file.size};
