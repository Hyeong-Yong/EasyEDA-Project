const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a3627e2915fe61c1',pcbUuid='0ac2a19168000d8e',projectUuid='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const base=root+'/output/candidates/multilayer-route-clearance/';
const file=await eda.sys_FileSystem.readFileFromFileSystem(base+'u4-land036-candidate.epru');
if(!file)throw new Error('Reviewed complete U4 source missing');
const source=await file.text(),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(source)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(digest!=='1d9258eeb67268383cb9b60cd41e0b11e9002e1e6bb96e2a087d318c77f367f1')throw new Error('U4 candidate changed');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return {h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const rows=parse(source),pads=rows.filter(r=>r.h.type==='PAD');
if(rows.length!==121||rows[0]?.b.uuid!==uuid||rows[0]?.b.docType!=='FOOTPRINT'||pads.length!==90)throw new Error('U4 footprint identity/inventory rejected');
const baselineFile=await eda.sys_FileSystem.readFileFromFileSystem(base+'u4-land036-before.epru');
if(!baselineFile)throw new Error('Complete U4 baseline missing');
const baseline=parse(await baselineFile.text());
for(let i=0;i<rows.length;i++){
 const a=rows[i],b=baseline[i],actual=structuredClone(a.b);
 if(canonical(a.h)!==canonical(b.h))throw new Error('Footprint record identity changed');
 if(a.h.type==='PAD'){
  if(b.b.layerId!==1||b.b.hole!==null||b.b.defaultPad.width!==16||b.b.defaultPad.height!==16||a.b.defaultPad.width!==14.173228||a.b.defaultPad.height!==14.173228)throw new Error('U4 land geometry rejected');
  actual.defaultPad=b.b.defaultPad;
 }
 if(canonical(actual)!==canonical(b.b))throw new Error('U4 non-land field changed '+a.h.id);
}
await eda.dmt_EditorControl.openDocument(pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource);
const component=before.find(r=>r.h.type==='COMPONENT'&&r.h.id==='3de4fa6d5f5df65c');
if(!component||!before.some(r=>r.h.type==='ATTR'&&r.b.parentId===component.h.id&&r.b.key==='Footprint'&&r.b.value===uuid)||!before.some(r=>r.h.type==='ATTR'&&r.b.parentId===component.h.id&&r.b.key==='Designator'&&r.b.value==='U4'))throw new Error('U4 library binding rejected');
const beforePath=root+'/output/validation/native-multilayer-u4-land036-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(beforePath,new Blob([beforeSource]),undefined,false))throw new Error('U4 recovery source not saved');
await eda.dmt_EditorControl.closeDocument(uuid+'@'+projectUuid);
const updated=await eda.lib_Footprint.updateDocumentSource(uuid,projectUuid,source);
await eda.dmt_EditorControl.openDocument(pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong PCB after U4 update');
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b])),differences=[];
for(const r of before)if(!['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type)&&canonical(r.b)!==canonical(actual.get(r.h.type+':'+r.h.id)))differences.push(r.h.type+':'+r.h.id);
if(before.length!==after.length)differences.push('record-count');
const afterPath=root+'/output/validation/native-multilayer-u4-land036-after.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('U4 readback not saved');
const saved=!differences.length&&await eda.pcb_Document.save();
const receiptPath=root+'/output/validation/native-multilayer-u4-land036-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,pcbUuid,candidateSha256:digest,updated,saved,beforePath,afterPath,differences,requiredGate:'Full project export and save/reopen must prove 90 exact .36-mm lands, all other footprint records and PCB records unchanged.'},null,2)]),undefined,false))throw new Error('U4 receipt not saved');
if(differences.length||!saved)throw new Error('U4 protected PCB body/save failed; inspect '+receiptPath);
return {uuid,updated,saved,receiptPath};
