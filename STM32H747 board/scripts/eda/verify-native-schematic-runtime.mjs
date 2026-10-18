const tab=await eda.dmt_EditorControl.openDocument('884e9cee09bd3f65');
await new Promise(r=>setTimeout(r,1000));
const page=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(page?.uuid!=='884e9cee09bd3f65') throw new Error('Wrong native page');
const source=await eda.sys_FileManager.getDocumentSource();
const counts={};
for(const line of source.split('\n')) {if(!line.includes('||')) continue;const h=JSON.parse(line.split('||')[0]);counts[h.type]=(counts[h.type]||0)+1;}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-mcu-runtime.epru',new Blob([source],{type:'text/plain'}),undefined,false);
const saved=await eda.sch_Document.save();
const zoom=await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
const ESYS_NetlistType={EASYEDA_PRO:'EasyEDA'};
let netlist;
try {
const file=await eda.sch_ManufactureData.getNetlistFile('STM32H747_260827',ESYS_NetlistType.EASYEDA_PRO);
if(!file) throw new Error('Native netlist file missing');
const exported=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-schematic-netlist.json',file,undefined,false);
netlist={exported,name:file.name,bytes:file.size};
} catch(error) {netlist={error:String(error)};}
return {page:{uuid:page.uuid,name:page.name},saved,zoom,counts,sourceSaved,netlist};
