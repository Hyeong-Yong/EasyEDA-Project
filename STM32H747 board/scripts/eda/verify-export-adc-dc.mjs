const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
await eda.dmt_EditorControl.openDocument('a07bf8e4331877a8');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!=='a07bf8e4331877a8')throw new Error('Wrong ADC page');
const kind=__taskArgs[0];
if(kind==='erc'){
 const passed=await eda.sch_Drc.check(true,true,false);
 const logs=await eda.sys_Log.sort();
 const path=root+'/output/validation/native-adc-dc-erc-20261016.json';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({passed,logs},null,2)]),undefined,false))throw new Error('ERC report not saved');
 return{passed,path};
}
if(kind==='netlist'){
 const ESYS_NetlistType={ALTIUM_DESIGNER:'Protel2'};
 const file=await eda.sch_ManufactureData.getNetlistFile('STM32H747_adc_dc_20261016',ESYS_NetlistType.ALTIUM_DESIGNER);
 if(!file)throw new Error('ADC netlist export failed');
 const path=root+'/output/validation/native-adc-dc-Protel2-20261016.net';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw new Error('ADC netlist not saved');
 return{path,bytes:file.size};
}
if(kind==='svg'){
 const file=await eda.sch_ManufactureData.getSvgFile('STM32H747_adc_dc_20261016');
 if(!file)throw new Error('ADC SVG export failed');
 const path=root+'/output/validation/native-adc-dc-svg-20261016.zip';
 if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw new Error('ADC SVG not saved');
 return{path,bytes:file.size};
}
throw new Error('Explicit ERC/netlist/SVG stage required');
