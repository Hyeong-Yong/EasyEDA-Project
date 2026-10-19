const tabId=await eda.dmt_EditorControl.openDocument('0ac2a19168000d8e');
if(!tabId)throw new Error('STM32 PCB did not open');
const document=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(document?.uuid!=='0ac2a19168000d8e'||document?.documentType!==3)throw new Error('Expected the actual STM32 PCB document');
const components=await eda.pcb_PrimitiveComponent.getAll();
if(components.length!==437)throw new Error('Unexpected physical component count');
const c1=components.find(c=>c.getState_Designator()==='C1');
if(!c1)throw new Error('C1 not found');
return {document,componentCount:components.length,c1:{id:c1.getState_PrimitiveId(),other:c1.getState_OtherProperty()}};
