await eda.dmt_EditorControl.openDocument('0ac2a19168000d8e');
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!=='0ac2a19168000d8e')throw Error('Wrong PCB');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/eco-preview-before.epru',new Blob([await eda.sys_FileManager.getDocumentSource()]),undefined,false))throw Error('Already previewed');
return {result:await eda.pcb_Document.importChanges('416c10313f778784')};
