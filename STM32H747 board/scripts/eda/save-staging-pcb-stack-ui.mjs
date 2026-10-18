const uuid='6da689cbfc28e476';
const projectUuid='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
if((await eda.dmt_Project.getCurrentProjectInfo())?.uuid!==projectUuid)throw new Error('Wrong dedicated project');
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated staging PCB');
const saved=await eda.pcb_Document.save();
if(!saved)throw new Error('UI physical-stack PCB save failed');
await eda.dmt_EditorControl.closeDocument(uuid+'@'+projectUuid);
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong reopened staging PCB');
const source=await eda.sys_FileManager.getDocumentSource();
const counts={};
const physics=[];
for(const line of source.split(/\r?\n/).filter(l=>l.includes('||'))){const i=line.indexOf('||');const head=JSON.parse(line.slice(0,i));const body=JSON.parse(line.slice(i+2).replace(/\|$/,''));counts[head.type]=(counts[head.type]||0)+1;if(head.type==='LAYER_PHYS')physics.push({id:head.id,...body});}
const liveComponents=(await eda.pcb_PrimitiveComponent.getAll(1)).length;
if(liveComponents!==330||counts.ARC!==2184||counts.LINE!==5424||counts.FILL!==730||counts.POLY!==500||counts.VIA!==634||counts.LAYER_PHYS!==17)throw new Error('Staging routing/stack runtime contract changed');
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-staging-pcb-stack-ui-reopened.epru';
const captured=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false);
return {saved,captured,path,liveComponents,counts,physics};
