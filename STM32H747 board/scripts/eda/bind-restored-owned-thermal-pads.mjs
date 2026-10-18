const expectedAdded=Number(__taskArgs[0]);
if(![1,4,8].includes(expectedAdded))throw new Error('Reviewed thermal drill count required');
const uuid='0ac2a19168000d8e';
const projectUuid='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const receiptInputs=[['native-U5-direct-thermal-pad-create-receipt.json','b098cceac55eab69','0c0d782d6b7f0167',1]];
if(expectedAdded>=4)receiptInputs.push(['native-U5-remaining-direct-thermal-pads-receipt.json','b098cceac55eab69','0c0d782d6b7f0167',3]);
if(expectedAdded===8)receiptInputs.push(['native-U7-remaining-direct-thermal-pads-receipt.json','15077d1eac66847c','ae8670f38e12646e',4]);
const knownIds=new Set();
for(const [name,footprint,parent,count]of receiptInputs){const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/'+name);if(!file)throw new Error('Native thermal create receipt missing');const receipt=JSON.parse(await file.text());if(receipt.uuid!==footprint||!receipt.expected||!receipt.saved||receipt.added?.length!==count)throw new Error('Native thermal create receipt changed');for(const pad of receipt.added)knownIds.add(parent+pad.id);}
if(knownIds.size!==expectedAdded)throw new Error('Actual native-created thermal identities are not unique');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid||(await eda.dmt_Project.getCurrentProjectInfo())?.uuid!==projectUuid)throw new Error('Wrong final PCB for thermal net assignment');
const pads=await eda.pcb_PrimitivePad.getAll();
const targets=[['U5','0c0d782d6b7f0167','25','e25',[[2043.3071,1448.8189],[2043.3071,1503.937],[2094.4882,1448.8189],[2094.4882,1503.937]]],['U7','ae8670f38e12646e','33','e33',[[2976.378,2583.6614],[2976.378,2666.3386],[3059.0551,2583.6614],[3059.0551,2666.3386]]]];
const results=[];
for(const [reference,parent,number,centralId,centers]of targets){
  const central=pads.find(p=>p.getState_PrimitiveId()===parent+centralId);
  if(!central||central.getState_PadNumber()!==number||central.getState_Net()!=='GND')throw new Error('Central thermal net identity mismatch');
  const extra=pads.filter(p=>p.getState_PrimitiveId().startsWith(parent)&&p.getState_PrimitiveId()!==parent+centralId&&p.getState_PadNumber()===number);
  const required=reference==='U5'?Math.min(expectedAdded,4):(expectedAdded===8?4:0);
  if(extra.length!==required)throw new Error('Unexpected restored thermal child count');
  for(const p of extra){
    const id=p.getState_PrimitiveId();
    if(!knownIds.has(id))throw new Error('Thermal PAD ID was not created by the reviewed native API operation');
    if(p.getState_Layer()!==12||!p.getState_Metallization()||p.getState_Hole()?.[0]!=='ROUND'||Math.abs(p.getState_Hole()[1]-11.811)>.001||p.getState_Pad()?.[0]!=='ELLIPSE'||!centers.some(([x,y])=>Math.abs(p.getState_X()-x)<.051&&Math.abs(p.getState_Y()-y)<.051)||!['','GND'].includes(p.getState_Net()))throw new Error('Restored thermal pad geometry/net guard failed');
    const before=p.getState_Net();
    if(before==='')await eda.pcb_PrimitivePad.modify(id,{net:'GND'});
    const refreshed=await eda.pcb_PrimitivePad.get(id);
    if(refreshed?.getState_Net()!=='GND')throw new Error('Restored thermal GND assignment failed');
    results.push({reference,id,number,before,after:refreshed.getState_Net(),x:refreshed.getState_X(),y:refreshed.getState_Y()});
  }
}
if(results.length!==expectedAdded||!await eda.pcb_Document.save())throw new Error('Thermal assignment save failed');
const path=root+'/output/validation/native-thermal-pad-net-binding-'+expectedAdded+'.json';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify({pcbUuid:uuid,expectedAdded,results},null,2)]),undefined,false);
return {path,expectedAdded,results};
