const tab = await eda.dmt_EditorControl.openDocument('ba2a89cb45c7ef63');
await new Promise(r=>setTimeout(r,1000));
const page = await eda.dmt_Schematic.getCurrentSchematicPageInfo();
if (page?.uuid !== 'ba2a89cb45c7ef63') throw new Error('Imported page not active');
const source = await eda.sys_FileManager.getDocumentSource();
const counts = {};
for (const line of source.split('\n')) {
  if (!line.includes('||')) continue;
  const head=JSON.parse(line.split('||')[0]);
  counts[head.type]=(counts[head.type]||0)+1;
}
const saved = await eda.sch_Document.save();
const zoom = await eda.dmt_EditorControl.zoomToAllPrimitives(tab);
return {page:{uuid:page.uuid,name:page.name},saved,zoom,counts,sourceLength:source.length};
