const pcbUuid='3ca9811d1a42d086';
const f=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-pcb/native-pcb-routed.epru');
if(!f)throw new Error('Strictly validated routed source not available');
const source=await f.text();
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
const candidate=parse(source);
if(candidate.find(r=>r.head.type==='DOCHEAD')?.body.uuid!==pcbUuid)throw new Error('Routed PCB UUID mismatch');
function count(rows,type){return rows.filter(r=>r.head.type===type).length;}
if(count(candidate,'COMPONENT')!==330||count(candidate,'PAD_NET')!==1176||count(candidate,'VIA')!==634||count(candidate,'LAYER_PHYS')!==13)throw new Error('Routed PCB structural count mismatch');
await eda.dmt_EditorControl.openDocument(pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const beforeSource=await eda.sys_FileManager.getDocumentSource();
const before=parse(beforeSource);
const ids=new Map(candidate.filter(r=>r.head.id).map(r=>[r.head.id,r]));
for(const record of before.filter(r=>['PAD_NET','NET','RULE','RULE_TEMPLATE'].includes(r.head.type))){
const desired=ids.get(record.head.id);
if(!desired||desired.head.type!==record.head.type||JSON.stringify(desired.body)!==JSON.stringify(record.body))throw new Error('Protected PCB electrical/rule data changed');
}
for(const old of before.filter(r=>r.head.type==='COMPONENT')){
const desired=ids.get(old.head.id);
if(desired?.head.type!=='COMPONENT')throw new Error('Physical PCB identity missing');
if(JSON.stringify(desired.body.attrs)!==JSON.stringify(old.body.attrs)||desired.body.layerId!==old.body.layerId)throw new Error('Physical PCB identity properties changed');
}
const backupSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-before-routing-apply.epru',new Blob([beforeSource]),undefined,false);
if(!backupSaved)throw new Error('PCB recovery source not saved');
const accepted=await eda.sys_FileManager.setDocumentSource(source);
if(!accepted)return {accepted:false};
const saved=await eda.pcb_Document.save();
if(!saved)throw new Error('Routed PCB not saved');
await eda.dmt_EditorControl.closeDocument(pcbUuid);
const tab=await eda.dmt_EditorControl.openDocument(pcbUuid);
await new Promise(r=>setTimeout(r,600));
const actual=await eda.sys_FileManager.getDocumentSource();
const after=parse(actual);
const counts={};
for(const r of after)counts[r.head.type]=(counts[r.head.type]||0)+1;
if(counts.COMPONENT!==330||counts.PAD_NET!==1176||counts.VIA!==634||counts.LAYER_PHYS!==13)throw new Error('Reloaded routed PCB count mismatch');
const activeCopper=after.filter(r=>r.head.type==='LAYER'&&[1,2,15,16,17,18].includes(r.body.layerId));
if(activeCopper.length!==6||activeCopper.some(r=>!r.body.use))throw new Error('Six copper layers not enabled');
const sourceSaved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-pcb-routed-runtime.epru',new Blob([actual]),undefined,false);
await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
return {accepted,saved,sourceSaved,counts,activeCopperLayers:activeCopper.map(r=>r.body.layerId)};
