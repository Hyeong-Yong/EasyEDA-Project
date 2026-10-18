const [planName,expectedHash,stage,startArg,countArg,recoveryStage]=__taskArgs;
if(!planName||!/^[a-z0-9_-]+\.json$/.test(planName)||!expectedHash||!/^[a-f0-9]{64}$/.test(expectedHash)||!stage||!/^[a-z0-9_-]{3,60}$/.test(stage))throw new Error('Reviewed scoped fill plan and SHA256 required');
const start=Number(startArg||0),count=Number(countArg||1);
if(!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>8)throw new Error('Reviewed bounded fill batch required');
if(recoveryStage&&!/^[a-z0-9_-]{3,60}$/.test(recoveryStage))throw new Error('Invalid fill recovery stage');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const pcbUuid='0ac2a19168000d8e';
await eda.dmt_EditorControl.openDocument(pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/multilayer-fill-clearance/'+planName);
if(!file)throw new Error('No reviewed fill plan');
const planText=await file.text();
const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(digest!==expectedHash)throw new Error('Fill plan hash changed');
const plan=JSON.parse(planText);
if(plan.pcbUuid!==pcbUuid||!Array.isArray(plan.changes))throw new Error('Fill plan identity changed');
const changes=plan.changes.slice(start,start+count);
if(changes.length!==count)throw new Error('Fill batch outside approved manifest');
const parse=source=>source.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||');return {head:JSON.parse(l.slice(0,i)),body:JSON.parse(l.slice(i+2).replace(/\|$/,''))};});
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const samePath=(a,b)=>Array.isArray(a)&&Array.isArray(b)?a.length===b.length&&a.every((v,i)=>samePath(v,b[i])):typeof a==='number'&&typeof b==='number'?Math.abs(a-b)<=0.000051:a===b;
let beforeSource=await eda.sys_FileManager.getDocumentSource();
if(recoveryStage){
 const receiptFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-fill-'+recoveryStage+'-receipt.json');
 const receipt=receiptFile&&JSON.parse(await receiptFile.text());
 if(!receipt||receipt.saved!==false||receipt.planSha256!==digest||receipt.start!==start||receipt.count!==count)throw new Error('Fill recovery receipt identity rejected');
 const recoveryFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-fill-'+recoveryStage+'-before.epru');
 if(!recoveryFile)throw new Error('Fill recovery baseline missing');
 beforeSource=await recoveryFile.text();
}
const before=parse(beforeSource);
if(before[0]?.body.uuid!==pcbUuid||before.filter(r=>r.head.type==='RULE').length!==18||before.filter(r=>r.head.type==='FILL').length!==730)throw new Error('Protected fill/rule inventory changed');
for(const [type,n]of Object.entries({COMPONENT:330,PAD_NET:1234,NET:280,VIA:634,PAD:4,LAYER:64,LAYER_PHYS:17,RULE_SELECTOR:280}))if(before.filter(r=>r.head.type===type).length!==n)throw new Error('Protected inventory changed '+type);
const frozenFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-multilayer-before.epru');
if(!frozenFile)throw new Error('Frozen multilayer baseline missing');
const ruleRows=rows=>rows.filter(r=>['RULE','RULE_TEMPLATE','RULE_SELECTOR'].includes(r.head.type)).map(r=>[r.head.type,r.head.id,r.body]);
if(canonical(ruleRows(before))!==canonical(ruleRows(parse(await frozenFile.text()))))throw new Error('Selected multilayer rules changed');
const byId=new Map(before.map(r=>[r.head.type+':'+r.head.id,r]));
const selected=new Map();
for(const change of changes){
 if(change.type!=='FILL'||!/^[a-f0-9]{16}$/.test(change.id)||selected.has(change.id))throw new Error('Invalid or duplicate fill target');
 const actual=byId.get('FILL:'+change.id);
 if(!actual||canonical(actual.body)!==canonical(change.before))throw new Error('Fill baseline changed '+change.id);
 const prior={...change.before},next={...change.after};delete prior.path;delete next.path;
 if(canonical(prior)!==canonical(next)||!Array.isArray(change.after.path)||!change.after.path.length||!change.after.path.every(Array.isArray)||![1,2,15,16,17,18].includes(change.after.layerId))throw new Error('Only existing copper fill path may change');
 if(!change.after.path.every(p=>p.length>=3&&p.every(v=>typeof v==='number'?Number.isFinite(v)&&Math.abs(v)<10000:['L','ARC','CARC','C','R','CIRCLE'].includes(v))))throw new Error('Invalid fill contour coordinate');
 selected.set(change.id,change);
}
const beforePath=root+'/output/validation/native-multilayer-fill-'+stage+'-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(beforePath,new Blob([beforeSource]),undefined,false))throw new Error('Scoped fill recovery source not saved');
const results=[];
if(!recoveryStage)for(const change of changes){
 const polygon=eda.pcb_MathPolygon.createComplexPolygon(change.after.path);
 if(!polygon)throw new Error('Invalid complex polygon '+change.id);
 if(!await eda.pcb_PrimitiveFill.modify(change.id,{complexPolygon:polygon}))throw new Error('Fill modify failed '+change.id);
 results.push({id:change.id,contours:change.after.path.length});
}
const afterSource=await eda.sys_FileManager.getDocumentSource();
const after=parse(afterSource);
const afterPath=root+'/output/validation/native-multilayer-fill-'+stage+'-after.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('Fill readback not saved');
const actualById=new Map(after.map(r=>[r.head.type+':'+r.head.id,r]));
const differences=[];
const nativeNormalizations=[];
for(const row of before){
 const key=row.head.type+':'+row.head.id,current=actualById.get(key);
 if(!current){differences.push({key,error:'missing'});continue;}
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(row.head.type))continue;
 const change=row.head.type==='FILL'?selected.get(row.head.id):null,expected=change?change.after:row.body,actualBody={...current.body};
 if(change&&samePath(actualBody.path,expected.path))actualBody.path=expected.path;
 if(change&&actualBody.zIndex===-1&&Number(expected.zIndex)>=0){nativeNormalizations.push({id:row.head.id,field:'zIndex',before:expected.zIndex,after:-1});actualBody.zIndex=expected.zIndex;}
 if(change&&expected.refs===null&&Array.isArray(actualBody.refs)&&actualBody.refs.length===1&&actualBody.refs[0]===null){nativeNormalizations.push({id:row.head.id,field:'refs',before:null,after:actualBody.refs});actualBody.refs=null;}
 if(canonical(actualBody)!==canonical(expected))differences.push({key,expected,actual:current.body});
}
if(before.length!==after.length)differences.push({error:'record-count-changed',before:before.length,after:after.length});
const receipt={pcbUuid,stage,planName,planSha256:digest,start,count,results,recoveryStage:recoveryStage||null,beforePath,afterPath,differences,nativeNormalizations,saved:false};
if(!differences.length)receipt.saved=await eda.pcb_Document.save();
const receiptPath=root+'/output/validation/native-multilayer-fill-'+stage+'-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Fill receipt save failed');
if(differences.length||!receipt.saved)throw new Error('Fill preservation/save failed; inspect '+receiptPath);
return {pcbUuid,stage,start,count,saved:receipt.saved,receiptPath};
