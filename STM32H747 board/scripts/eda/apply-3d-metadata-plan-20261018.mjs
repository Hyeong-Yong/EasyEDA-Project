const name=__taskArgs[0],start=Number(__taskArgs[1]),count=Number(__taskArgs[2]);
if(!/^[a-z0-9-]+$/.test(name)||!Number.isInteger(start)||start<0||!Number.isInteger(count)||count<1||count>60)throw new Error('Scoped model plan and batch required');
const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('STM PCB must be current');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/'+name+'.json';
const file=await eda.sys_FileSystem.readFileFromFileSystem(path);if(!file)throw new Error('Missing plan');const plan=JSON.parse(await file.text());
const all=await eda.pcb_PrimitiveComponent.getAll();if(all.length!==437)throw new Error('Component count changed');
const byId=new Map(all.map(c=>[c.getState_PrimitiveId(),c]));const entries=plan.entries.slice(start,start+count);
if(!entries.length)throw new Error('Empty batch');const before=[];
for(const e of entries){
 const c=byId.get(e.id);if(!c||c.getState_Designator()!==e.ref)throw new Error('Component identity changed: '+e.ref);
 const old=c.getState_OtherProperty()||{};if(String(old.DNP).toLowerCase()==='yes'||e.ref.startsWith('TP'))throw new Error('Excluded component in plan');
 const nums=e.transform.split(',').map(Number);if(nums.length!==9||nums.some(n=>!Number.isFinite(n))||nums.slice(0,3).some(n=>n<=0))throw new Error('Invalid model transform');
 const own=globalThis.__STM32H747_PUBLIC_3D_LIBRARY_20261018_V1__;
 const privateEntry=own?.result?.applyPlan?.entries?.find(p=>p.ref===e.ref&&p.id===e.id&&p.model===e.model&&p.transform===e.transform&&p.title===e.title);
 const privateAllowed=name==='local5-session-model-plan'&&plan.libraryUuid==='extend_lib_STM32H747_3D_LOCAL5_20261018'&&own?.result?.libraryUuid===plan.libraryUuid&&Boolean(privateEntry);
 if(!/^[0-9a-f]+\|[0-9a-f]+$/.test(e.model)&&!privateAllowed)throw new Error('Qualified model reference required');
 before.push({ref:e.ref,id:e.id,other:{...old}});
}
for(const e of entries){const c=byId.get(e.id),old=c.getState_OtherProperty()||{};const a=c.toAsync();a.setState_OtherProperty({...old,'3D Model':e.model,'3D Model Title':e.title,'3D Model Transform':e.transform});await a.done();}
const readback=await eda.pcb_PrimitiveComponent.getAll();
for(const e of entries){const c=readback.find(c=>c.getState_PrimitiveId()===e.id),old=before.find(b=>b.id===e.id).other,now=c.getState_OtherProperty()||{};
 if(now['3D Model']!==e.model||now['3D Model Transform']!==e.transform)throw new Error('Model readback mismatch '+e.ref);
 for(const key of Object.keys(old).filter(k=>!['3D Model','3D Model Title','3D Model Transform'].includes(k)))if(JSON.stringify(old[key])!==JSON.stringify(now[key]))throw new Error('Non-3D property changed '+e.ref+' '+key);
}
const saved=await eda.pcb_Document.save();if(!saved)throw new Error('PCB save failed');
const receipt={plan:name,start,count:entries.length,refs:entries.map(e=>e.ref),before,saved,afterModels:entries};
const receiptPath='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/'+name+'-receipt-'+start+'.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)],{type:'application/json'}),undefined,false))throw new Error('Receipt save failed');
return {saved,receiptPath,modified:entries.length,refs:entries.map(e=>e.ref)};
