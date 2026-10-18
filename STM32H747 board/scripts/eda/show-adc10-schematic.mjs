const uuid='a07bf8e4331877a8',tab=await eda.dmt_EditorControl.openDocument(uuid);
if(!tab||(await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Could not show saved ADC10 schematic');
await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
return{uuid,shown:true,pcbStage:'Saved WIP, placement and routing not complete'};
