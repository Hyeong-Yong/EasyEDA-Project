const schematic='416c10313f778784';
const pcbUuid='3ca9811d1a42d086';
const all=await eda.dmt_Board.getAllBoardsInfo();
let board=all.find(b=>b.schematic?.uuid===schematic&&b.pcb?.uuid===pcbUuid);
let boardName=board?.name;
if(!boardName){
if(all.some(b=>b.schematic?.uuid===schematic||b.pcb?.uuid===pcbUuid))throw new Error('Unexpected existing board association');
boardName=await eda.dmt_Board.createBoard(schematic,pcbUuid);
if(!boardName)throw new Error('Dedicated STM32H747 board association failed');
await new Promise(r=>setTimeout(r,1000));
}
await eda.dmt_EditorControl.openDocument(pcbUuid);
await new Promise(r=>setTimeout(r,800));
const current=await eda.dmt_Pcb.getCurrentPcbInfo();
if(current?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const imported=await eda.pcb_Document.importChanges(schematic);
if(!imported)return {boardName,pcbUuid,imported:false};
await new Promise(r=>setTimeout(r,800));
const source=await eda.sys_FileManager.getDocumentSource();
const counts={};
for(const line of source.split('\n')){if(!line.includes('||'))continue;const head=JSON.parse(line.split('||')[0]);counts[head.type]=(counts[head.type]||0)+1;}
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-generated.epru',new Blob([source]),undefined,false);
const saved=await eda.pcb_Document.save();
return {boardName,pcbUuid,imported,sourceSaved,saved,counts};
