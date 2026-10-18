await eda.dmt_EditorControl.openDocument('e8a4e3fabe30ab59');
await new Promise(r=>setTimeout(r,500));
const file=await eda.sch_ManufactureData.getSvgFile('STM32H747_260827_pages_2_to_6');
if(!file)throw new Error('Native SVG export failed');
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/'+file.name,file,undefined,false);
return {saved,name:file.name,bytes:file.size};
