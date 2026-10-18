const pageUuid='e8a4e3fabe30ab59';
const tab=await eda.dmt_EditorControl.openDocument(pageUuid);
await eda.dmt_EditorControl.zoomToAllPrimitives();
return {tab,page:await eda.dmt_Schematic.getCurrentSchematicPageInfo()};
