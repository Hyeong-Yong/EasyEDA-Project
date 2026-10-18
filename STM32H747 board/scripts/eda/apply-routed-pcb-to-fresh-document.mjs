const uuid='6da689cbfc28e476';
const placementOnly=__taskArgs[0]==='placement_only';
let info=(await eda.dmt_Pcb.getAllPcbsInfo()).find(p=>p.uuid===uuid);
if(info?.name==='PCB2'){await eda.dmt_Pcb.modifyPcbName(uuid,'STM32H747_PCB_WORK');info=(await eda.dmt_Pcb.getAllPcbsInfo()).find(p=>p.uuid===uuid);}
if(info?.name!=='STM32H747_PCB_WORK')throw new Error('Dedicated fresh PCB staging identity mismatch '+JSON.stringify(info));
const tab=await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong fresh PCB');
const before=await eda.sys_FileManager.getDocumentSource();
const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-pcb/'+(placementOnly?'native-pcb-placed.epru':'native-pcb-routed.epru'));
const head=before.split('\n')[0].replace(/\|$/,'');
const source=(await file.text()).split(/\r?\n/).filter(l=>l.includes('||')&&(!placementOnly||!l.startsWith('{"type":"PAD",'))).map(l=>l.startsWith('{"type":"DOCHEAD"}')?head:l.replace(/\|$/,'')).join('|\n');
const beforeSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-fresh-pcb-before-route.epru',new Blob([before]),undefined,false);
if(!beforeSaved)throw new Error('Fresh PCB recovery source not saved');
const accepted=await eda.sys_FileManager.setDocumentSource(source);
const components=await eda.pcb_PrimitiveComponent.getAll(1);
const actual=await eda.sys_FileManager.getDocumentSource();
const counts={};
for(const l of actual.split('\n').filter(l=>l.includes('||'))){const h=JSON.parse(l.split('||')[0]);counts[h.type]=(counts[h.type]||0)+1;}
const captured=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-fresh-pcb-route-readback.epru',new Blob([actual]),undefined,false);
if(!accepted||components.length!==330)return {accepted,liveComponents:components.length,counts,captured,saved:false};
if((!placementOnly&&(counts.VIA!==634||counts.LAYER_PHYS!==13))||counts.PAD_NET!==1176)throw new Error('Routed PCB runtime counts incorrect');
const saved=await eda.pcb_Document.save();
await eda.dmt_EditorControl.closeDocument(tab);
const reopened=await eda.dmt_EditorControl.openDocument(uuid);
const live=(await eda.pcb_PrimitiveComponent.getAll(1)).length;
await eda.dmt_EditorControl.zoomToAllPrimitives(reopened);
return {accepted,placementOnly,liveComponents:components.length,reopenedComponents:live,counts,captured,saved};
