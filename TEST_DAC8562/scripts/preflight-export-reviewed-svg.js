await eda.dmt_EditorControl.openDocument('e58bcc16379b10f4');
const f=await eda.sch_ManufactureData.getExportDocumentFile('Manufacturing_Preflight_Reviewed','SVG');
if(!f)throw new Error('SVG export unavailable');
return {saved:await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/manufacturing-preflight/native-reviewed-schematics.zip',f,undefined,false),name:f.name,size:f.size};
