await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='4e08f91f9a2c4fe4'||d.documentType!==3)throw new Error('Wrong PCB');
const pins=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId('fc8ccfce00069d14');
if(!pins||pins.length!==10)throw new Error('Expected DAC U3 MSOP10 pins');
const changes=[];
for(const pin of pins){
 const before=pin.getState_SolderMaskAndPasteMaskExpansion();
 const desired={...before,topSolderMask:0.025/0.0254};
 const a=pin.toAsync();a.setState_SolderMaskAndPasteMaskExpansion(desired);await a.done();
 changes.push({pad:pin.getState_PadNumber(),before,after:pin.getState_SolderMaskAndPasteMaskExpansion()});
}
await eda.pcb_Document.save();
await eda.dmt_EditorControl.closeDocument('4e08f91f9a2c4fe4');
await eda.dmt_EditorControl.openDocument('4e08f91f9a2c4fe4');
const reopened=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId('fc8ccfce00069d14');
return {changes,reopened:reopened.map(pin=>({pad:pin.getState_PadNumber(),mask:pin.getState_SolderMaskAndPasteMaskExpansion()})),details:await eda.pcb_Drc.check(true,true,true),source:await eda.sys_FileManager.getDocumentSource()};
