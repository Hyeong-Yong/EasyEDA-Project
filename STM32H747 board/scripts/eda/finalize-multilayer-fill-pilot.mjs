const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',id='378b6a6933052c9a';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-fill-pilot01-before.epru');
const planFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/multilayer-fill-clearance/multilayer-fill-clearance-pilot.json');
if(!file||!planFile)throw new Error('Pilot evidence missing');
const planText=await planFile.text();
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(hash!=='2dcd6e68b00a46c0cb542e4fc9c9096e395cd9fc1854f7e0ad389c3311d32492')throw new Error('Pilot manifest changed');
const plan=JSON.parse(planText),change=plan.changes[0];
if(plan.changes.length!==1||change.id!==id)throw new Error('Pilot target changed');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return {h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const before=parse(await file.text()),afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource);
if(before.length!==after.length)throw new Error('Pilot record inventory changed');
const actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b]));
for(const row of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(row.h.type))continue;
 const expected=row.h.type==='FILL'&&row.h.id===id?{...change.after,zIndex:-1,refs:[null]}:row.b;
 if(canonical(actual.get(row.h.type+':'+row.h.id))!==canonical(expected))throw new Error('Pilot protected data mismatch '+row.h.type+':'+row.h.id);
}
if(!await eda.pcb_Document.save())throw new Error('Verified fill pilot save failed');
const path=root+'/output/validation/native-multilayer-fill-pilot01-verified-receipt.json';
const receipt={pcbUuid:uuid,id,saved:true,fullSourceVerified:true,nonTargetBodyDifferences:0,pathOnlyGeometryChange:true,nativeNormalizations:{zIndex:[change.before.zIndex,-1],refs:[null,[null]]},sourcePath:root+'/output/validation/native-multilayer-fill-pilot01-after.epru',drc:{clearance:2117,connection:0,report:'native-pcb-drc-0ac2a19168000d8e-multilayer_fill_pilot.json'}};
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Pilot verification receipt not saved');
return {saved:true,path};
