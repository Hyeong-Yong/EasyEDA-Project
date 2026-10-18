const [planName,expectedHash,stage,startArg,countArg,recoveryStage]=__taskArgs;
if(!planName||!/^[a-z0-9_-]+\.json$/.test(planName)||!expectedHash||!/^[a-f0-9]{64}$/.test(expectedHash)||!stage||!/^[a-z0-9_-]{3,60}$/.test(stage))throw new Error('Reviewed scoped width plan and SHA256 required');
const start=Number(startArg||0),count=Number(countArg||1);
if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>80)throw new Error('Reviewed bounded width batch required');
if(recoveryStage&&!/^[a-z0-9_-]{3,60}$/.test(recoveryStage))throw new Error('Invalid recovery stage');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/multilayer-route-clearance/'+planName);
if(!file)throw new Error('No reviewed width plan');
const planText=await file.text();
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(hash!==expectedHash)throw new Error('Width plan hash changed');
const plan=JSON.parse(planText),changes=plan.changes?.slice(start,start+count);
if(plan.pcbUuid!==uuid||changes?.length!==count)throw new Error('Width plan identity/batch changed');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return {h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
let beforeSource=await eda.sys_FileManager.getDocumentSource();
if(recoveryStage){
 const receiptFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-widths-'+recoveryStage+'-receipt.json');
 const receipt=receiptFile&&JSON.parse(await receiptFile.text());
 if(!receipt||receipt.saved!==false||receipt.planSha256!==hash||receipt.start!==start||receipt.count!==count)throw new Error('Recovery receipt identity rejected');
 const recoveryFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-widths-'+recoveryStage+'-before.epru');
 if(!recoveryFile)throw new Error('Recovery baseline missing');
 beforeSource=await recoveryFile.text();
}
const before=parse(beforeSource),counts={};
for(const row of before)counts[row.h.type]=(counts[row.h.type]||0)+1;
if(before[0]?.b.uuid!==uuid)throw new Error('Source identity changed');
for(const [type,n]of Object.entries({COMPONENT:330,PAD_NET:1234,NET:280,VIA:634,PAD:4,LAYER:64,LAYER_PHYS:17,RULE:18,RULE_SELECTOR:280}))if(counts[type]!==n)throw new Error('Protected inventory changed '+type);
const frozenFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-before.epru');
if(!frozenFile)throw new Error('Frozen multilayer baseline missing');
const ruleRows=rows=>rows.filter(r=>['RULE','RULE_TEMPLATE','RULE_SELECTOR'].includes(r.h.type)).map(r=>[r.h.type,r.h.id,r.b]);
if(canonical(ruleRows(before))!==canonical(ruleRows(parse(await frozenFile.text()))))throw new Error('Selected multilayer rules changed');
const beforeMap=new Map(before.map(r=>[r.h.type+':'+r.h.id,r.b])),selected=new Map();
for(const c of changes){
 const field=c.type==='VIA'?'viaDiameter':c.type==='LINE'?'width':null,key=c.type+':'+c.id;
 if(!field||!/^[a-f0-9]{16}$/.test(c.id)||selected.has(key)||canonical(beforeMap.get(key))!==canonical(c.before))throw new Error('Width baseline/target rejected '+key);
 const prior={...c.before},next={...c.after};delete prior[field];delete next[field];
 if(canonical(prior)!==canonical(next)||c.after[field]>=c.before[field])throw new Error('Only a copper width/diameter reduction is allowed '+key);
 if(c.type==='VIA'&&(Math.abs(c.before.holeDiameter*.0254-.2)>.00001||c.after.viaDiameter*.0254<.30999||c.after.viaDiameter-c.after.holeDiameter<.10/.0254-.00001))throw new Error('Via/drill/annulus contract rejected '+key);
 if(c.type==='LINE'&&(![1,2,15,16,17,18].includes(c.before.layerId)||c.after.width*.0254<.12999))throw new Error('Track minimum/layer rejected '+key);
 if(c.type==='LINE'&&/GND|VDD|VCC|\+3V3|\+5V|\+12V|EARTH|VBAT/.test(c.before.netName)&&c.before.width*.0254>=.2&&c.after.width*.0254<.19999)throw new Error('Power-track neck rejected '+key);
 selected.set(key,c);
}
const beforePath=root+'/output/validation/native-multilayer-widths-'+stage+'-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(beforePath,new Blob([beforeSource]),undefined,false))throw new Error('Width recovery source not saved');
if(!recoveryStage)for(const c of changes){
 if(c.type==='VIA'){
  if(!await eda.pcb_PrimitiveVia.modify(c.id,{diameter:c.after.viaDiameter,holeDiameter:c.before.holeDiameter,x:c.before.centerX,y:c.before.centerY}))throw new Error('Via width modify failed '+c.id);
 }else if(!await eda.pcb_PrimitiveLine.modify(c.id,{lineWidth:c.after.width,startX:c.before.startX,startY:c.before.startY,endX:c.before.endX,endY:c.before.endY}))throw new Error('Track width modify failed '+c.id);
}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b])),differences=[],expectedLines=[],actualLines=[],nativeNormalizations=[];
for(const row of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(row.h.type))continue;
 const key=row.h.type+':'+row.h.id,c=selected.get(key),expected=c?c.after:row.b,current={...actual.get(key)};
 const field=c?.type==='VIA'?'viaDiameter':c?.type==='LINE'?'width':null;
 if(field&&Math.abs(current[field]-expected[field])<=.000051)current[field]=expected[field];
 if(canonical(current)!==canonical(expected)){
  if(row.h.type==='LINE'){
   expectedLines.push({id:row.h.id,b:expected});
   if(actual.has(key))actualLines.push({id:row.h.id,b:actual.get(key)});
  }else differences.push({key,expected,actual:actual.get(key)});
 }
}
for(const row of after)if(!beforeMap.has(row.h.type+':'+row.h.id)){
 if(row.h.type==='LINE'&&row.b.zIndex===-1)actualLines.push({id:row.h.id,b:row.b});
 else differences.push({error:'unexpected-record',row});
}
const lineGroup=b=>{const v={...b};for(const k of ['startX','startY','endX','endY','zIndex','width'])delete v[k];return canonical(v);};
const covered=(line,candidates)=>{
 const b=line.b,dx=b.endX-b.startX,dy=b.endY-b.startY,len=Math.hypot(dx,dy),intervals=[];
 if(!len)return false;
 for(const other of candidates){
  const c=other.b;if(lineGroup(b)!==lineGroup(c)||c.width<b.width-.000051)continue;
  if(Math.abs(dx*(c.startY-b.startY)-dy*(c.startX-b.startX))/len>1e-7||Math.abs(dx*(c.endY-b.startY)-dy*(c.endX-b.startX))/len>1e-7)continue;
  const a=((c.startX-b.startX)*dx+(c.startY-b.startY)*dy)/len,z=((c.endX-b.startX)*dx+(c.endY-b.startY)*dy)/len;
  intervals.push([Math.min(a,z),Math.max(a,z)]);
 }
 intervals.sort((a,b)=>a[0]-b[0]);let end=0;
 for(const [a,z]of intervals){if(a>end+1e-7)break;if(z>end)end=z;if(end>=len-1e-7)return true;}
 return false;
};
if(expectedLines.length||actualLines.length){
 const allExpectedLines=before.filter(r=>r.h.type==='LINE').map(r=>({id:r.h.id,b:selected.get('LINE:'+r.h.id)?.after||r.b}));
 const allActualLines=after.filter(r=>r.h.type==='LINE').map(r=>({id:r.h.id,b:r.b}));
 const equivalent=expectedLines.length&&actualLines.length&&expectedLines.every(l=>covered(l,allActualLines))&&actualLines.every(l=>covered(l,allExpectedLines));
 const allMetadataPermitted=actualLines.every(l=>!beforeMap.has('LINE:'+l.id)||l.b.zIndex===beforeMap.get('LINE:'+l.id).zIndex);
 if(!equivalent||!allMetadataPermitted)differences.push({error:'line-union-not-equivalent',expectedLines,actualLines,equivalent,allMetadataPermitted});
 else nativeNormalizations.push({kind:'collinear-copper-union-with-unchanged-lines',expectedLines,actualLines,centrelineToleranceMil:1e-7,widthQuantizationToleranceMil:.000051});
}
if(after.length-before.length!==actualLines.filter(l=>!beforeMap.has('LINE:'+l.id)).length-expectedLines.filter(l=>!actual.has('LINE:'+l.id)).length)differences.push({error:'unexplained-record-count',before:before.length,after:after.length});
const afterPath=root+'/output/validation/native-multilayer-widths-'+stage+'-after.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('Width readback not saved');
const saved=!differences.length&&await eda.pcb_Document.save();
const receiptPath=root+'/output/validation/native-multilayer-widths-'+stage+'-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,stage,start,count,planName,planSha256:hash,beforePath,afterPath,recoveryStage:recoveryStage||null,differences,nativeNormalizations,saved},null,2)]),undefined,false))throw new Error('Width receipt not saved');
if(differences.length||!saved)throw new Error('Width preservation/save failed; inspect '+receiptPath);
return {uuid,stage,start,count,saved,receiptPath};
