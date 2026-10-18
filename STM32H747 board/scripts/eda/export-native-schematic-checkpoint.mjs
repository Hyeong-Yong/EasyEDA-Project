const ESYS_NetlistType={EASYEDA_PRO:'EasyEDA'};
let netlist;
try{
const source=await eda.sch_Netlist.getNetlist(ESYS_NetlistType.EASYEDA_PRO);
if(typeof source!=='string' || !source.length) throw new Error('Legacy netlist returned empty');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-schematic-netlist-legacy.json',new Blob([source],{type:'text/plain'}),undefined,false);
netlist={saved,bytes:source.length,prefix:source.slice(0,120)};
}catch(error){netlist={error:String(error)};}
const svg=await eda.sch_ManufactureData.getSvgFile('STM32H747_native_schematics');
const svgSaved=svg?await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-schematics-svg.zip',svg,undefined,false):false;
return {netlist,svgSaved,svg:svg?{name:svg.name,size:svg.size}:null};
