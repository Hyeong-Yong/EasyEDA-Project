const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('Actual STM PCB must be current');
const comps=await eda.pcb_PrimitiveComponent.getAll();
const ref=__taskArgs[0]||'C1';
const c=comps.find(c=>c.getState_Designator()===ref);
return {doc,count:comps.length,id:c.getState_PrimitiveId(),other:c.getState_OtherProperty()};
