await eda.dmt_EditorControl.openDocument('e58bcc16379b10f4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='e58bcc16379b10f4'||d.documentType!==1)throw new Error('Wrong schematic');
const f=await eda.sch_ManufactureData.getExportDocumentFile('DAC8562_final','PNG',
  {theme:'Black on White',lineWidth:'Always 1px'},'Current Schematic Page');
if(!f)throw new Error('Native schematic image export failed');
return {page:d.uuid,size:f.size,saved:await eda.sys_FileSystem.saveFileToFileSystem(
  'C:/Dev/EasyEDA/EasyEDA-Project/TEST_DAC8562/output/final-review/DAC8562.native.png',f,undefined,false)};
