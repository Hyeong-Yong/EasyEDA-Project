const [planName,expectedHash,stage,startArg,countArg]=__taskArgs;
if(!planName||!/^[a-z0-9_-]+\.json$/.test(planName)||!expectedHash||!/^[a-f0-9]{64}$/.test(expectedHash)||!stage||!/^[a-z0-9_-]{3,60}$/.test(stage))throw new Error('Reviewed scoped via plan and SHA256 required');
const start=Number(startArg||0),count=Number(countArg||1);
if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>250)throw new Error('Reviewed bounded via batch required');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const pcbUuid='0ac2a19168000d8e';
await eda.dmt_EditorControl.openDocument(pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/multilayer-route-clearance/'+planName);
if(!file)throw new Error('No reviewed plan');
const planText=await file.text();
const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(digest!==expectedHash)throw new Error('Via plan hash changed');
const plan=JSON.parse(planText);
if(plan.pcbUuid!==pcbUuid||!Array.isArray(plan.changes))throw new Error('Via plan identity changed');
const changes=plan.changes.slice(start,start+count);
if(changes.length!==count)throw new Error('Via batch outside approved manifest');
const parse=source=>source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||');return {head:JSON.parse(l.slice(0,i)),body:JSON.parse(l.slice(i+2).replace(/\|$/,''))};});
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const beforeSource=await eda.sys_FileManager.getDocumentSource();
const before=parse(beforeSource);
if(before[0]?.body.uuid!==pcbUuid||before.filter(r=>r.head.type==='RULE').length!==18||before.filter(r=>r.head.type==='VIA').length!==634)throw new Error('Protected via/rule inventory changed');
for(const [type,n]of Object.entries({COMPONENT:330,PAD_NET:1234,NET:280,PAD:4,LAYER:64,LAYER_PHYS:17,RULE_SELECTOR:280}))if(before.filter(r=>r.head.type===type).length!==n)throw new Error('Protected inventory changed '+type);
const frozenFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-before.epru');
if(!frozenFile)throw new Error('Frozen multilayer baseline missing');
const ruleRows=rows=>rows.filter(r=>['RULE','RULE_TEMPLATE','RULE_SELECTOR'].includes(r.head.type)).map(r=>[r.head.type,r.head.id,r.body]);
if(canonical(ruleRows(before))!==canonical(ruleRows(parse(await frozenFile.text()))))throw new Error('Selected multilayer rules changed');
const byId=new Map(before.map(r=>[r.head.type+':'+r.head.id,r]));
const selected=new Map();
for(const change of changes){
 if(change.type!=='VIA'||!/^[a-f0-9]{16}$/.test(change.id)||selected.has(change.id))throw new Error('Invalid or duplicate via target');
 const actual=byId.get('VIA:'+change.id);
 if(!actual||canonical(actual.body)!==canonical(change.before))throw new Error('Via baseline changed '+change.id);
 const prior={...change.before},next={...change.after};
 delete prior.viaDiameter;delete next.viaDiameter;
 if(canonical(prior)!==canonical(next))throw new Error('Only via copper diameter may change');
 if(Math.abs(change.before.holeDiameter*0.0254-0.2)>0.00001||change.after.viaDiameter>=change.before.viaDiameter||change.after.viaDiameter*0.0254<0.29999||change.after.viaDiameter*0.0254>0.40001||change.after.viaDiameter-change.after.holeDiameter<0.10/0.0254-0.00001)throw new Error('Via annulus/drill contract rejected');
 selected.set(change.id,change);
}
const beforePath=root+'/output/validation/native-multilayer-via-'+stage+'-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(beforePath,new Blob([beforeSource]),undefined,false))throw new Error('Scoped via recovery source not saved');
const results=[];
for(const change of changes){
 if(!await eda.pcb_PrimitiveVia.modify(change.id,{diameter:change.after.viaDiameter,holeDiameter:change.before.holeDiameter}))throw new Error('Via modify failed '+change.id);
 const current=await eda.pcb_PrimitiveVia.get(change.id);
 if(!current||Math.abs(current.getState_Diameter()-change.after.viaDiameter)>0.051||Math.abs(current.getState_HoleDiameter()-change.before.holeDiameter)>0.101)throw new Error('Via runtime verification failed '+change.id);
 results.push({id:change.id,diameter:current.getState_Diameter(),holeDiameter:current.getState_HoleDiameter()});
}
const afterSource=await eda.sys_FileManager.getDocumentSource();
const after=parse(afterSource);
const afterPath=root+'/output/validation/native-multilayer-via-'+stage+'-after.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('Via readback not saved');
const actualById=new Map(after.map(r=>[r.head.type+':'+r.head.id,r]));
const differences=[];
for(const row of before){
 const key=row.head.type+':'+row.head.id;
 const current=actualById.get(key);
 if(!current){differences.push({key,error:'missing'});continue;}
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(row.head.type))continue;
 const change=row.head.type==='VIA'?selected.get(row.head.id):null;
 const expected=change?change.after:row.body;
 const actualBody={...current.body};
 if(change&&Math.abs(actualBody.viaDiameter-expected.viaDiameter)<=0.000051)actualBody.viaDiameter=expected.viaDiameter;
 if(canonical(actualBody)!==canonical(expected))differences.push({key,expected,actual:current.body});
}
if(before.length!==after.length)differences.push({error:'record-count-changed',before:before.length,after:after.length});
const receipt={pcbUuid,stage,planName,planSha256:digest,start,count,results,beforePath,afterPath,differences,saved:false};
if(!differences.length)receipt.saved=await eda.pcb_Document.save();
const receiptPath=root+'/output/validation/native-multilayer-via-'+stage+'-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Via receipt save failed');
if(differences.length||!receipt.saved)throw new Error('Via preservation/save failed; inspect '+receiptPath);
return {pcbUuid,stage,start,count,saved:receipt.saved,receiptPath};
