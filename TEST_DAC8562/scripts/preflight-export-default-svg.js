await eda.dmt_EditorControl.openDocument('e58bcc16379b10f4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=='e58bcc16379b10f4')throw new Error('Wrong page');
const f=await eda.sch_ManufactureData.getExportDocumentFile('Manufacturing_Preflight','SVG');
if(!f)throw new Error('Native SVG export unavailable');
return {saved:await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/manufacturing-preflight/native-schematic-export.zip',f,undefined,false),name:f.name,size:f.size};
