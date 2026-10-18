const pcbUuid='0ac2a19168000d8e';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const id='e917297287b005ea';
const via=await eda.pcb_PrimitiveVia.get(id);
if(!via)throw new Error('Pilot via missing');
const source=await eda.sys_FileManager.getDocumentSource();
const row=source.split(/\r?\n/).find(l=>l.startsWith('{"type":"VIA"')&&l.includes('"id":"'+id+'"'));
return {id,runtime:{diameter:via.getState_Diameter(),holeDiameter:via.getState_HoleDiameter(),x:via.getState_X(),y:via.getState_Y(),net:via.getState_Net()},sourceRecord:row};
