const configs={'DAC8562 module':{folder:'TEST_DAC8562',pcb:'4e08f91f9a2c4fe4',pages:['e58bcc16379b10f4','e3a1c5f417017755']},'STM32H747_MCU_BOARD_v19':{folder:'STM32H747 board',pcb:'0ac2a19168000d8e',pages:['e8a4e3fabe30ab59','360993a3108b5759','c0b1ffcb620d758f','3c13ef086afba6f5','a07bf8e4331877a8']}};
const p=await eda.dmt_Project.getCurrentProjectInfo(),cfg=configs[p.friendlyName];if(!cfg)throw Error('Unknown project');
const [action,stage]=__args;if(!/^[a-zA-Z0-9_-]{2,70}$/.test(stage||''))throw Error('Explicit output stage required');
const root='C:/Dev/EasyEDA/EasyEDA-Project/'+cfg.folder+'/output/jlcpcb-20261019-review/native';
const save=async(suffix,file)=>{if(!file)throw Error('No file');const path=root+'/'+stage+suffix;if(!await eda.sys_FileSystem.saveFileToFileSystem(path,file,undefined,false))throw Error('Save refused '+path);return{path,bytes:file.size};};
if(action==='project'){return await save('.epro2',await eda.sys_FileManager.getProjectFile(stage,undefined,'epro2'));}
if(action==='erc'){const result=[];for(const page of cfg.pages){await eda.dmt_EditorControl.openDocument(page);result.push({page,violations:await eda.sch_Drc.check(true,true,true)});}return result;}
await eda.dmt_EditorControl.openDocument(cfg.pcb);if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==cfg.pcb)throw Error('Wrong PCB');
if(action==='drc')return {violations:await eda.pcb_Drc.check(true,true,true)};
if(action==='source')return await save('.epru',new Blob([await eda.sys_FileManager.getDocumentSource()]));
if(action==='cpl')return await save('.csv',await eda.pcb_ManufactureData.getPickAndPlaceFile(stage,'csv','mm'));
if(action==='bom')return await save('.csv',await eda.pcb_ManufactureData.getBomFile(stage,'csv'));
if(action==='gerber')return await save('.zip',await eda.pcb_ManufactureData.getGerberFile(stage));
if(action==='save')return {saved:await eda.pcb_Document.save()};
if(action==='switch-stm')return {opened:await eda.dmt_Project.openProject('4d4671fe9a78f6b1578521c2dc6be53db20dc0cc6cb10fdfc81febaa87f5af94')};
if(action==='switch-dac')return {opened:await eda.dmt_Project.openProject('dd59729173ceab597e015b7842a752ad416a6b41fb9eba8523f1bdbee791bf03')};
throw Error('Unknown action');
