const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('STM PCB required');
const all=await eda.pcb_PrimitiveComponent.getAll(),c=all.find(c=>c.getState_Designator()==='U3');if(!c)throw new Error('U3 missing');
const old=c.getState_OtherProperty()||{};if(old['3D Model'])throw new Error('Pilot must not overwrite an existing model');
const next={...old,'3D Model':'2351360292744dbc91885e7d69b823ec|0819f05c4eef4c71ace90d822a990e87','3D Model Title':'DFN-6_L3.0-W3.0-H1.0-P0.95'};
const a=c.toAsync();a.setState_OtherProperty(next);await a.done();
const refetched=(await eda.pcb_PrimitiveComponent.getAll()).find(c=>c.getState_Designator()==='U3');
return {ref:'U3',before:old,after:refetched.getState_OtherProperty(),saved:await eda.pcb_Document.save()};
