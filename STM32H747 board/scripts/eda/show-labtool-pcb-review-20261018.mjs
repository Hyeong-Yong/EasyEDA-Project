const uuid='0ac2a19168000d8e';
const region=__taskArgs[0]||'all';
const bounds={analog:[0,154,44,0],reference:[16,88,34,64],pump:[26,38,44,19]};
if(region!=='all'&&!bounds[region])throw new Error('Only scoped PCB review regions are supported');
const tab=await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong STM32 PCB');
const zoom=region==='all'
 ?await eda.dmt_EditorControl.zoomToAllPrimitives(tab)
 :await eda.dmt_EditorControl.zoomToRegion(...bounds[region].map(v=>v/.0254),tab);
return{pcbUuid:uuid,region,zoom,nativeElectricalDesignModified:false};
