const finalUuid='0ac2a19168000d8e';
const schematicUuid='416c10313f778784';
const board=await eda.dmt_Board.getBoardInfo('mcu_board');
if(board?.pcb?.uuid!==finalUuid||board?.schematic?.uuid!==schematicUuid)throw new Error('Final project association guard failed');
const backup=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/checkpoints/STM32H747_after_final_pcb_association_20261014.epro2');
if(!backup||backup.size<19500000)throw new Error('Audited full recovery checkpoint unavailable');
const all=await eda.dmt_Pcb.getAllPcbsInfo();
const removed=[];
for(const [uuid,name]of [['6da689cbfc28e476','STM32H747_PCB_WORK'],['9a0a68d8722d6718','STM32H747_PCB_LOAD_PROBE']]){
const info=all.find(p=>p.uuid===uuid);
if(!info)continue;
if(info.name!==name||info.parentBoardName)throw new Error('Own temporary PCB identity changed');
if(!await eda.dmt_Pcb.deletePcb(uuid))throw new Error('Own temporary PCB cleanup failed');
removed.push({uuid,name});
}
await new Promise(r=>setTimeout(r,800));
const after=await eda.dmt_Board.getBoardInfo('mcu_board');
const pages=await eda.dmt_Schematic.getAllSchematicPagesInfo();
const pcbs=await eda.dmt_Pcb.getAllPcbsInfo();
if(after?.pcb?.uuid!==finalUuid||after?.schematic?.uuid!==schematicUuid||pages.length!==5||pcbs.length!==1||pcbs[0].uuid!==finalUuid)throw new Error('Clean final project tree guard failed');
const tab=await eda.dmt_EditorControl.openDocument(finalUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==finalUuid||(await eda.pcb_PrimitiveComponent.getAll(1)).length!==330)throw new Error('Final native PCB model unavailable');
await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
const report={removed,board:after,pcbs,pages,recoverableCheckpoint:'output/checkpoints/STM32H747_after_final_pcb_association_20261014.epro2'};
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-own-probe-cleanup.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(report,null,2)]),undefined,false);
return {saved,path,removed,pcbCount:pcbs.length,pageCount:pages.length};
