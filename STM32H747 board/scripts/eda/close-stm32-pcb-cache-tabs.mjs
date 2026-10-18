const expected=new Map([['0ac2a19168000d8e','MCU_BOARD_PCB'],['6da689cbfc28e476','STM32H747_PCB_WORK'],['9a0a68d8722d6718','STM32H747_PCB_LOAD_PROBE']]);
const library=(await eda.dmt_Project.getCurrentProjectInfo()).uuid;
const all=await eda.dmt_Pcb.getAllPcbsInfo();
const results=[];
for(const [uuid,name] of expected){
const info=all.find(p=>p.uuid===uuid);
if(!info)continue;
if(info.name.toLowerCase()!==name.toLowerCase())throw new Error('Refusing to close an unexpected PCB identity');
const closed=await eda.dmt_EditorControl.closeDocument(uuid+'@'+library);
results.push({uuid,name,closed});
}
for(const uuid of ['e2e3d06dac58c326','83fb62ef25d3eef1','8bd1ebd7c6524c9d','ae37a0fb8459ebec']){
results.push({uuid,footprint:true,closed:await eda.dmt_EditorControl.closeDocument(uuid+'@'+library)});
}
await new Promise(r=>setTimeout(r,2200));
return results;
