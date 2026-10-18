const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
const [mode,startArg,countArg]=__taskArgs,start=Number(startArg||0),count=Number(countArg||2);
if(!['pads','fills'].includes(mode)||!Number.isInteger(start)||!Number.isInteger(count)||count<1||count>2)throw new Error('Explicit bounded corner change required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(root+p);if(!f)throw new Error('Missing '+p);return await f.text();};
const planText=await load('/output/candidates/corner-holes-inward/plan.json');
const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(planText)))).map(x=>x.toString(16).padStart(2,'0')).join('');
if(hash!=='a598937b8be3dc5132fb338377308fa85c6f7d468a55fe5fed902fabad431ab4')throw new Error('Reviewed corner plan changed');
const plan=JSON.parse(planText);
if(plan.pcb_uuid!==uuid||plan.pad_changes.length!==4||plan.fill_changes.length!==6)throw new Error('Corner plan identity changed');
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const samePath=(a,b)=>Array.isArray(a)&&Array.isArray(b)?a.length===b.length&&a.every((v,i)=>samePath(v,b[i])):typeof a==='number'&&typeof b==='number'?Math.abs(a-b)<=.000051:a===b;
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),byId=new Map(before.map(r=>[r.h.type+':'+r.h.id,r]));
const changes=mode==='pads'?plan.pad_changes:plan.fill_changes.slice(start,start+count);
if(mode==='fills'&&changes.length!==count)throw new Error('Fill batch outside plan');
if(mode==='pads'){
 const frozen=parse(await load('/output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru'));
 if(before.length!==frozen.length)throw new Error('PCB baseline count changed');
 for(const r of frozen)if(!['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type)&&canonical(byId.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))throw new Error('PCB baseline changed '+r.h.type+':'+r.h.id);
}
for(const c of changes)if(canonical(byId.get(c.type+':'+c.id)?.b)!==canonical(c.before))throw new Error('Corner target baseline changed '+c.id);
const stage=mode==='pads'?'pads':'fills-'+start+'-'+count;
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-corner-'+stage+'-before-20261016.epru',new Blob([beforeSource]),undefined,false);
for(const c of changes){
 if(mode==='pads'){
  const primitive=await eda.pcb_PrimitivePad.get(c.id);
  if(!primitive||Array.isArray(primitive))throw new Error('Corner pad unavailable');
  const pending=primitive.toAsync();
  pending.setState_X(c.after.centerX);pending.setState_Y(c.after.centerY);
  await pending.done();
 }else{
  const polygon=eda.pcb_MathPolygon.createComplexPolygon(c.after.path);
  if(!polygon||!await eda.pcb_PrimitiveFill.modify(c.id,{complexPolygon:polygon}))throw new Error('Corner fill update failed '+c.id);
 }
}
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),map=new Map(after.map(r=>[r.h.type+':'+r.h.id,r]));
const targets=new Map(changes.map(c=>[c.type+':'+c.id,c])),errors=[],normalizations=[];
for(const r of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type))continue;
 const key=r.h.type+':'+r.h.id,c=targets.get(key),a=map.get(key),expected=c?.after||r.b,body={...a?.b};
 if(c?.type==='FILL'){
  if(samePath(body.path,expected.path))body.path=expected.path;
  if(body.zIndex===-1&&expected.zIndex>=0){normalizations.push({id:c.id,field:'zIndex'});body.zIndex=expected.zIndex;}
  if(expected.refs===null&&canonical(body.refs)==='[null]'){normalizations.push({id:c.id,field:'refs'});body.refs=null;}
 }
 if(!a||canonical(body)!==canonical(expected))errors.push({key,expected,actual:a?.b});
}
if(after.length!==before.length)errors.push({error:'record count',before:before.length,after:after.length});
const path=root+'/output/validation/native-corner-'+stage+'-after-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false);
const receipt={mode,start,count,planSha256:hash,path,normalizations,errors,saved:false};
if(!errors.length)receipt.saved=await eda.pcb_Document.save();
const receiptPath=root+'/output/validation/native-corner-'+stage+'-receipt-20261016.json';
await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw new Error('Corner preservation/save failed; inspect '+receiptPath);
return{saved:true,stage,path,normalizations,errors:0};
