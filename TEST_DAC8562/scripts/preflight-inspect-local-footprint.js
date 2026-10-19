const opened=await eda.dmt_EditorControl.openDocument('bb80514b4aacee07');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='bb80514b4aacee07'||d.documentType!==4)return {opened,document:d,localFootprintOpened:false};
return {opened,document:d,localFootprintOpened:true,source:await eda.sys_FileManager.getDocumentSource()};
