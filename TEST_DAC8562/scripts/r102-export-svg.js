await eda.dmt_EditorControl.openDocument('e3a1c5f417017755');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='e3a1c5f417017755'||d.documentType!==1)throw new Error('Wrong schematic');
const ESCH_ExportDocumentFileType={SVG:'SVG'};
const f=await eda.sch_ManufactureData.getExportDocumentFile('R102_Connected',ESCH_ExportDocumentFileType.SVG);
if(!f)throw new Error('Export failed');
return {saved:await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/r102-connection-fix/native-schematics.zip',f,undefined,false),size:f.size};
