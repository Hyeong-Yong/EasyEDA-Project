await eda.dmt_EditorControl.openDocument('e58bcc16379b10f4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='e58bcc16379b10f4'||d.documentType!==1)throw new Error('Wrong schematic');
const f=await eda.sch_ManufactureData.getExportDocumentFile('Preflight_Visual_Review','SVG');
if(!f)throw new Error('SVG export failed');
return {saved:await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/manufacturing-preflight/native-final-schematic-proof.zip',f,undefined,false),name:f.name,size:f.size};
