const finalBoard=__taskArgs[0]==='final_board';
if(__taskArgs.length&& !finalBoard)throw new Error('Unsupported scoped PCB destination');
const uuid=finalBoard?'3ca9811d1a42d086':'6da689cbfc28e476';
const projectUuid='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
if((await eda.dmt_Project.getCurrentProjectInfo())?.uuid!==projectUuid)throw new Error('Wrong dedicated project');
const info=(await eda.dmt_Pcb.getAllPcbsInfo()).find(p=>p.uuid===uuid);
if(finalBoard){
  const board=(await eda.dmt_Board.getAllBoardsInfo()).find(b=>b.pcb?.uuid===uuid);
  if(!board||board.schematic?.uuid!=='416c10313f778784'||info?.parentBoardName!==board.name)throw new Error('Final PCB schematic association mismatch');
}else if(info?.name!=='STM32H747_PCB_WORK')throw new Error('Wrong dedicated staging PCB');
const tab=await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong active PCB');
function records(source){return source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||');return {head:JSON.parse(l.slice(0,i)),body:JSON.parse(l.slice(i+2).replace(/\|$/,''))};});}
function countsOf(rows){const counts={};for(const r of rows)counts[r.head.type]=(counts[r.head.type]||0)+1;return counts;}
const before=await eda.sys_FileManager.getDocumentSource();
const beforeRows=records(before);
if(beforeRows[0]?.body?.docType!=='PCB'||beforeRows[0]?.body?.uuid!==uuid)throw new Error('Active PCB source identity mismatch');
const stage=finalBoard?'final':'staging';
const backupSaved=await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-'+stage+'-pcb-before-compatible-routing.epru',new Blob([before]),undefined,false);
if(!backupSaved)throw new Error('PCB source recovery capture failed');
const layers=await eda.pcb_Layer.getAllLayers();
if([1,2,15,16,17,18].some(id=>!layers.some(l=>l.id===id&&l.type==='SIGNAL'))){
  if(!await eda.pcb_Layer.setTheNumberOfCopperLayers(6))throw new Error('Six-layer prerequisite failed');
  if(!await eda.pcb_Document.save())throw new Error('Six-layer prerequisite save failed');
}
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/native-pcb/native-pcb-routed-decoder-compatible.epru');
const input=records(await file.text());
if(input[0]?.body?.docType!=='PCB'||input[0]?.body?.uuid!=='6da689cbfc28e476')throw new Error('Compatible source identity is not verified staging PCB');
const expected={COMPONENT:330,PAD_NET:1176,NET:280,LINE:5424,ARC:2184,POLY:500,FILL:730,VIA:634,PAD:4,LAYER_PHYS:17};
function assertCounts(counts){for(const [kind,number]of Object.entries(expected))if(counts[kind]!==number)throw new Error('PCB '+kind+' count '+counts[kind]+' differs from '+number);}
assertCounts(countsOf(input));
const expectedPhys=new Map(input.filter(r=>r.head.type==='LAYER_PHYS').map(r=>[r.head.id,r.body]));
function assertPhys(rows){
 const actual=new Map(rows.filter(r=>r.head.type==='LAYER_PHYS').map(r=>[r.head.id,r.body]));
 for(const [id,body]of expectedPhys){const found=actual.get(id);if(!found)throw new Error('Physical stack entry missing '+id);for(const key of ['thickness','material','zIndex'])if(found[key]!==body[key])throw new Error('Physical stack changed '+id+' '+key);}
}
input[0]=beforeRows[0];
const source=input.map(r=>JSON.stringify(r.head)+'||'+JSON.stringify(r.body)).join('|\n');
const accepted=await eda.sys_FileManager.setDocumentSource(source);
const actual=await eda.sys_FileManager.getDocumentSource();
const actualRows=records(actual);
const counts=countsOf(actualRows);
const readbackSaved=await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-'+stage+'-pcb-compatible-readback.epru',new Blob([actual]),undefined,false);
if(!accepted)throw new Error('Compatible routing source rejected');
assertCounts(counts);assertPhys(actualRows);
if((await eda.pcb_PrimitiveComponent.getAll(1)).length!==330)throw new Error('Native component registry count mismatch');
const saved=await eda.pcb_Document.save();
if(!saved)throw new Error('Compatible routed PCB save failed');
await eda.dmt_EditorControl.closeDocument(tab);
const reopenedTab=await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong reopened routed PCB');
const reopenedSource=await eda.sys_FileManager.getDocumentSource();
const reopenedRows=records(reopenedSource);
const reopenedCounts=countsOf(reopenedRows);
assertCounts(reopenedCounts);assertPhys(reopenedRows);
const liveComponents=(await eda.pcb_PrimitiveComponent.getAll(1)).length;
if(liveComponents!==330)throw new Error('Reopened native component registry count mismatch');
const reopenedPath=root+'/output/validation/native-'+stage+'-pcb-compatible-reopened.epru';
const captured=await eda.sys_FileSystem.saveFileToFileSystem(reopenedPath,new Blob([reopenedSource]),undefined,false);
await eda.dmt_EditorControl.zoomToAllPrimitives(reopenedTab);
return {uuid,finalBoard,accepted,saved,readbackSaved,captured,reopenedPath,liveComponents,counts:reopenedCounts,manufacturingReady:false};
