const retained='dfec14d6b0ca29c3';
const candidates=[['f761590e40a058a2','mcu_board'],['8747fc63c8747bac','mcu_board_1'],['08a4061442156cf9','mcu_board_2'],['37baa8be6370f504','mcu_board_3']];
const all=await eda.dmt_Schematic.getAllSchematicsInfo();
const final=all.find(s=>s.uuid===retained);
if(!final||final.page?.length!==5)throw new Error('Retained schematic missing');
const project=await eda.dmt_Project.getCurrentProjectInfo();
const backup=await eda.sys_FileManager.getProjectFileByProjectUuid(project.uuid,'STM32H747_before_checkpoint_cleanup_20261014',undefined,'epro2');
if(!backup||backup.size<1000000)throw new Error('Complete recovery backup failed');
const backupSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/checkpoints/STM32H747_before_checkpoint_cleanup_20261014.epro2',backup,undefined,false);
if(!backupSaved)throw new Error('Recovery backup was not saved');
const removed=[];
for(const [uuid,name] of candidates){
const item=all.find(s=>s.uuid===uuid);
if(!item)continue;
if(item.name.toLowerCase()!==name||item.parentBoardName)throw new Error('Temporary schematic identity changed');
if(!await eda.dmt_Schematic.deleteSchematic(uuid))throw new Error('Temporary schematic deletion failed');
removed.push({uuid,name:item.name});
await new Promise(r=>setTimeout(r,300));
}
await eda.dmt_EditorControl.openDocument(final.page.find(p=>p.name.toLowerCase()==='02_mcu').uuid);
await new Promise(r=>setTimeout(r,500));
const renamed=await eda.dmt_Schematic.modifySchematicName(retained,'MCU_BOARD');
const reordered=await eda.dmt_Schematic.reorderSchematicPages(retained,[...final.page].sort((a,b)=>a.name.localeCompare(b.name)));
await new Promise(r=>setTimeout(r,500));
return {backupSaved,backupBytes:backup.size,removed,renamed,reordered,remaining:(await eda.dmt_Schematic.getAllSchematicsInfo()).map(s=>({uuid:s.uuid,name:s.name,pages:s.page.map(p=>({uuid:p.uuid,name:p.name}))}))};
