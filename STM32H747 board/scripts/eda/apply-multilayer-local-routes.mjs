const [planName,expectedHash,stage,recoveryStage,repairId]=__taskArgs;
const approved={'u4-bga-escape-complete-plan.json':{hash:'21474c8ee8d60919b15b74bed1c59eae880ea1a9e857085cd8928f7519e13ccb',count:27},'u1-r17-dogleg-plan.json':{hash:'bda30af280320839f3f58e9a2e2c4800654a9c41bd42e16165c5332280fb7d33',count:2},'c23-reroute-plan.json':{hash:'ca8aca23f8e05dfba68831c31009c8f459f149d7163806200405c2e789208ece',count:2}};
if(!approved[planName]||expectedHash!==approved[planName].hash||!stage||!/^[a-z0-9_-]{3,60}$/.test(stage))throw new Error('Reviewed local route manifest/hash required');
if(recoveryStage&&!/^[a-z0-9_-]{3,60}$/.test(recoveryStage))throw new Error('Invalid route recovery stage');
if(repairId&&(!recoveryStage||planName!=='u4-bga-escape-complete-plan.json'||repairId!=='a2a2c1fc45da3946'))throw new Error('Only reviewed final D30-centre correction is permitted');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/multilayer-route-clearance/'+planName);
if(!file)throw new Error('Local route plan missing');
const planText=await file.text(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(hash!==expectedHash)throw new Error('Local route manifest changed');
const plan=JSON.parse(planText),changes=plan.changes;
if(plan.pcbUuid!==uuid||changes?.length!==approved[planName].count)throw new Error('Local route identity/inventory rejected');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return{h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
let beforeSource=await eda.sys_FileManager.getDocumentSource();
if(recoveryStage){
 const receiptFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-routes-'+recoveryStage+'-receipt.json');
 const receipt=receiptFile&&JSON.parse(await receiptFile.text());
 if(!receipt||receipt.saved!==false||receipt.planSha256!==hash||receipt.count!==changes.length)throw new Error('Route recovery receipt identity rejected');
 const recoveryFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-routes-'+recoveryStage+'-before.epru');
 if(!recoveryFile)throw new Error('Route recovery baseline missing');
 beforeSource=await recoveryFile.text();
}
const before=parse(beforeSource),beforeMap=new Map(before.map(r=>[r.h.type+':'+r.h.id,r.b])),counts={};
for(const row of before)counts[row.h.type]=(counts[row.h.type]||0)+1;
for(const [type,n]of Object.entries({COMPONENT:330,PAD_NET:1234,NET:280,VIA:634,PAD:4,LAYER:64,LAYER_PHYS:17,RULE:18,RULE_SELECTOR:280}))if(counts[type]!==n)throw new Error('Protected route inventory changed '+type);
const frozen=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-before.epru');
const rules=r=>r.filter(x=>['RULE','RULE_TEMPLATE','RULE_SELECTOR'].includes(x.h.type)).map(x=>[x.h.type,x.h.id,x.b]);
if(!frozen||canonical(rules(before))!==canonical(rules(parse(await frozen.text()))))throw new Error('Selected multilayer rules changed');
const selected=new Map();
for(const c of changes){
 if(c.type!=='LINE'||!/^[a-f0-9]{16}$/.test(c.id)||selected.has(c.id)||canonical(beforeMap.get('LINE:'+c.id))!==canonical(c.before))throw new Error('Route baseline rejected '+c.id);
 const a={...c.before},b={...c.after};for(const key of ['startX','startY','endX','endY','width']){delete a[key];delete b[key];}
 if(canonical(a)!==canonical(b)||![1,2].includes(c.after.layerId)||c.after.width*.0254<.12999||c.after.width>c.before.width+.000051)throw new Error('Route protected field/width/layer changed '+c.id);
 for(const field of ['startX','startY','endX','endY'])if(!Number.isFinite(c.after[field])||Math.abs(c.after[field]-c.before[field])>20)throw new Error('Route exceeds bounded local displacement '+c.id);
 if(/GND|VDD|VCC|\+3V3|\+5V|\+12V|EARTH|VBAT/.test(c.before.netName)&&c.before.width*.0254>=.2&&c.after.width*.0254<.19999)throw new Error('Power neck rejected '+c.id);
 selected.set(c.id,c);
}
const beforePath=root+'/output/validation/native-multilayer-routes-'+stage+'-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(beforePath,new Blob([beforeSource]),undefined,false))throw new Error('Route recovery source not saved');
if(repairId){
 const current=parse(await eda.sys_FileManager.getDocumentSource()).find(r=>r.h.type==='LINE'&&r.h.id===repairId),c=selected.get(repairId);
 if(!current||canonical(current.b)!==canonical(c.before))throw new Error('Final D30 correction baseline rejected');
}
for(const c of changes.filter(c=>!recoveryStage||c.id===repairId))if(!await eda.pcb_PrimitiveLine.modify(c.id,{startX:c.after.startX,startY:c.after.startY,endX:c.after.endX,endY:c.after.endY,lineWidth:c.after.width}))throw new Error('Local route modify failed '+c.id);
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b])),differences=[],nativeNormalizations=[];
const covered=(b,candidates)=>{
 const dx=b.endX-b.startX,dy=b.endY-b.startY,len=Math.hypot(dx,dy),intervals=[];
 if(!len)return false;
 const metadata=v=>{const q={...v};for(const k of ['startX','startY','endX','endY','width','zIndex'])delete q[k];return canonical(q);};
 for(const {b:c}of candidates){
  if(metadata(c)!==metadata(b)||c.width<b.width-.000051)continue;
  if(Math.abs(dx*(c.startY-b.startY)-dy*(c.startX-b.startX))/len>1e-7||Math.abs(dx*(c.endY-b.startY)-dy*(c.endX-b.startX))/len>1e-7)continue;
  const a=((c.startX-b.startX)*dx+(c.startY-b.startY)*dy)/len,z=((c.endX-b.startX)*dx+(c.endY-b.startY)*dy)/len;intervals.push([Math.min(a,z),Math.max(a,z)]);
 }
 intervals.sort((a,b)=>a[0]-b[0]);let end=0;for(const [a,z]of intervals){if(a>end+1e-7)break;if(z>end)end=z;if(end>=len-1e-7)return true;}return false;
};
for(const r of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type))continue;
 const c=r.h.type==='LINE'?selected.get(r.h.id):null,expected=c?c.after:r.b,current={...actual.get(r.h.type+':'+r.h.id)};
 if(r.h.type==='LINE'&&!actual.has('LINE:'+r.h.id)&&covered(expected,after.filter(r=>r.h.type==='LINE'))){nativeNormalizations.push({kind:'redundant-collinear-copper-removed',id:r.h.id,expected,centrelineToleranceMil:1e-7,widthQuantizationToleranceMil:.000051});continue;}
 if(c)for(const field of ['startX','startY','endX','endY','width'])if(Math.abs(current[field]-expected[field])<=.000051)current[field]=expected[field];
 if(canonical(current)!==canonical(expected))differences.push({key:r.h.type+':'+r.h.id,expected,actual:actual.get(r.h.type+':'+r.h.id)});
}
for(const r of after)if(!beforeMap.has(r.h.type+':'+r.h.id))differences.push({error:'unexpected-record',row:r});
if(before.length-after.length!==nativeNormalizations.length)differences.push({error:'record-count',before:before.length,after:after.length});
const afterPath=root+'/output/validation/native-multilayer-routes-'+stage+'-after.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('Route readback not saved');
const saved=!differences.length&&await eda.pcb_Document.save(),receiptPath=root+'/output/validation/native-multilayer-routes-'+stage+'-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,stage,planName,planSha256:hash,count:changes.length,recoveryStage:recoveryStage||null,repairId:repairId||null,beforePath,afterPath,differences,nativeNormalizations,saved},null,2)]),undefined,false))throw new Error('Route receipt not saved');
if(differences.length||!saved)throw new Error('Route preservation/save failed; inspect '+receiptPath);
return{uuid,stage,count:changes.length,saved,receiptPath};
