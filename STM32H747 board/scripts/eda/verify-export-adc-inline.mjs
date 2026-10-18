const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8',[stage,kind]=__taskArgs;
if(!['before','after'].includes(stage)||!['erc','netlist'].includes(kind))throw new Error('Explicit inline validation stage required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC page');
if(kind==='erc'){
 const passed=await eda.sch_Drc.check(true,true,false),logs=await eda.sys_Log.sort();
 const path=root+'/output/validation/native-adc-inline-'+stage+'-erc-20261016.json';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({passed,logs},null,2)]),undefined,false))throw new Error('Inline ERC report save failed');
 return{passed,path};
}
const ESYS_NetlistType={ALTIUM_DESIGNER:'Protel2'},file=await eda.sch_ManufactureData.getNetlistFile('STM32H747_adc_inline_'+stage+'_20261016',ESYS_NetlistType.ALTIUM_DESIGNER);
if(!file)throw new Error('Inline native netlist export failed');
const path=root+'/output/validation/native-adc-inline-'+stage+'-Protel2-20261016.net';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw new Error('Inline netlist file save failed');
return{path,bytes:file.size};
