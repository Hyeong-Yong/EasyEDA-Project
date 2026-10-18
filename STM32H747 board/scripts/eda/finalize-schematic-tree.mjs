const retained='416c10313f778784';
const obsolete='dfec14d6b0ca29c3';
const final=await eda.dmt_Schematic.getSchematicInfo(retained);
if(final?.page?.length!==5)throw new Error('Final five-page schematic missing');
const expected={'02_mcu':99,'03_mcu_power':98,'04_sdram':18,'05_enet_usb_vcp':138,'06_adc_timer_dac':133};
const checked=[];
for(const page of [...final.page].sort((a,b)=>a.name.localeCompare(b.name))){
await eda.dmt_EditorControl.openDocument(page.uuid);
await new Promise(r=>setTimeout(r,500));
const active=await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if(active?.uuid!==page.uuid)throw new Error('Final schematic focus changed');
const source=await eda.sys_FileManager.getDocumentSource();
const count=source.split('\n').filter(l=>l.startsWith('{"type":"COMPONENT"')).length;
if(count!==expected[page.name.toLowerCase()])throw new Error('Final component instance count mismatch');
if(active.titleBlockData&&Object.keys(active.titleBlockData).length>0){
if(!await eda.dmt_Schematic.modifySchematicPageTitleBlock(false,{}))throw new Error('Existing default drawing could not be hidden');
}
checked.push({uuid:page.uuid,name:page.name,components:count,defaultDrawingAbsent:!active.titleBlockData||Object.keys(active.titleBlockData).length===0});
}
const project=await eda.dmt_Project.getCurrentProjectInfo();
const backup=await eda.sys_FileManager.getProjectFileByProjectUuid(project.uuid,'STM32H747_before_final_cleanup_20261014',undefined,'epro2');
if(!backup||backup.size<1000000)throw new Error('Final recovery backup failed');
const backupSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/checkpoints/STM32H747_before_final_cleanup_20261014.epro2',backup,undefined,false);
if(!backupSaved)throw new Error('Final recovery backup not saved');
const old=await eda.dmt_Schematic.getSchematicInfo(obsolete);
if(old&&(old.name.toLowerCase()!=='mcu_board'||old.parentBoardName))throw new Error('Obsolete checkpoint identity changed');
const removed=old?await eda.dmt_Schematic.deleteSchematic(obsolete):true;
if(!removed)throw new Error('Obsolete checkpoint removal failed');
await eda.dmt_EditorControl.openDocument(final.page.find(p=>p.name.toLowerCase()==='02_mcu').uuid);
await new Promise(r=>setTimeout(r,500));
const renamed=await eda.dmt_Schematic.modifySchematicName(retained,'MCU_BOARD');
const reordered=await eda.dmt_Schematic.reorderSchematicPages(retained,[...final.page].sort((a,b)=>a.name.localeCompare(b.name)));
return {retained,checked,backupSaved,backupBytes:backup.size,removed,renamed,reordered};
