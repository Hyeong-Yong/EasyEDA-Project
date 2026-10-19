const uuid='a07bf8e4331877a8';
const stage=__taskArgs[0];
if(stage&&!/^[a-z0-9_]{3,40}$/.test(stage))throw new Error('Scoped ERC evidence stage required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong ADC page');
const violations=await eda.sch_Drc.check(true,true,true);
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-adc10-labtool-schematic-erc-details'+(stage?'-'+stage:'')+'-20261018.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({violations},null,2)]),undefined,false))throw new Error('ERC detail save failed');
return{path,count:violations.length};
