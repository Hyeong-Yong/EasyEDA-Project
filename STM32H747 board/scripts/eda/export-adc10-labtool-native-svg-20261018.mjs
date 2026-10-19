const uuid='a07bf8e4331877a8';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong schematic');
const file=await eda.sch_ManufactureData.getSvgFile('STM32H747_labtool_schematic_20261018');
if(!file)throw new Error('Native SVG export failed');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-adc10-labtool-schematics-svg-20261018.zip';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw new Error('Native SVG not saved');
return {path,bytes:file.size};
