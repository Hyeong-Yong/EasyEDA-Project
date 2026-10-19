const name=__taskArgs[0];if(!/^[a-z0-9-]+$/.test(name))throw new Error('Scoped plan name required');
const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('STM PCB must be current');
const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/'+name+'.json');if(!file)throw new Error('Missing plan');const plan=JSON.parse(await file.text());
const all=await eda.pcb_PrimitiveComponent.getAll();if(all.length!==437||!plan.entries?.length||plan.entries.length>60)throw new Error('Scoped model count invalid');
const byId=new Map(all.map(c=>[c.getState_PrimitiveId(),c]));const before=[];
for(const e of plan.entries){const c=byId.get(e.id);if(!c||c.getState_Designator()!==e.ref)throw new Error('Component identity changed '+e.ref);const old=c.getState_OtherProperty()||{};if(old['3D Model']||String(old.DNP).toLowerCase()==='yes'||e.ref.startsWith('TP'))throw new Error('Target must be fitted, unbound physical part '+e.ref);if(!/^[0-9a-f]+$/.test(e.uuid)||e.libraryUuid!=='0819f05c4eef4c71ace90d822a990e87')throw new Error('Only observed system models allowed');before.push({ref:e.ref,id:e.id,other:old});}
for(const e of plan.entries){const c=byId.get(e.id),a=c.toAsync();a.setState_OtherProperty({...c.getState_OtherProperty(),'3D Model':e.uuid+'|'+e.libraryUuid,'3D Model Title':e.title});await a.done();}
const saved=await eda.pcb_Document.save();if(!saved)throw new Error('PCB save failed');
const receipt={saved,name,before,entries:plan.entries};const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/'+name+'-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(receipt,null,2)],{type:'application/json'}),undefined,false))throw new Error('Receipt not saved');return {saved,path,count:plan.entries.length};
