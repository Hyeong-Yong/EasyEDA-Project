import fs from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const [action, ...args] = process.argv.slice(2);
let windowId = process.env.EDA_REVISION_WINDOW;
const desiredProject = process.env.EDA_REVISION_PROJECT || (['import','validate','replace-import','export-final','export-native','reopen'].includes(action) ? path.basename(path.resolve(args[0])).replace(/\.epro2$/, '') : action==='clean-copy'?args[0]:'DAC8562_power_accuracy_revision');
async function resolveWindow() {
  const inventory=await (await fetch('http://127.0.0.1:49620/eda-windows')).json();
  for(const w of inventory.windows){
    const v=await (await fetch('http://127.0.0.1:49620/execute',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({windowId:w.windowId,code:'const p=await eda.dmt_Project.getCurrentProjectInfo(); return {name:p?.friendlyName};'})})).json();
    if(v.success&&v.result?.name===desiredProject){windowId=w.windowId;return;}
  }
  throw new Error('No connected editor for '+desiredProject);
}
async function run(code) {
  if(!windowId) await resolveWindow();
  const r = await fetch('http://127.0.0.1:49620/execute', {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({code,windowId})});
  const v = await r.json();
  if(!v.success&&v.error?.includes('no longer connected')){windowId=undefined;await resolveWindow();return run(code);}
  if (!v.success) throw new Error(JSON.stringify(v));
  return v.result;
}
if (action === 'search') {
  const v = await run(`const out={}; for(const k of ${JSON.stringify(args)}) out[k]=await eda.lib_Device.search(k,undefined,undefined,undefined,10,1); return out;`);
  const f = path.join(root, 'output/validated-revision/library/search-results.json');
  let prior = {};
  try { prior = JSON.parse(await fs.readFile(f,'utf8')); } catch {}
  await fs.writeFile(f,JSON.stringify({...prior,...v},null,2));
  console.log(JSON.stringify(Object.fromEntries(Object.entries(v).map(([k,a])=>[k,a.map(x=>({uuid:x.uuid,name:x.name,mpn:x.manufacturerId,supplier:x.supplierId,library:x.libraryUuid,footprint:x.footprintName,properties:{value:x.otherProperty?.Value,tolerance:x.otherProperty?.Tolerance,tcr:x.otherProperty?.['Temperature Coefficient']}}))])),null,2));
} else if (action === 'code') {
  const v = await run(await fs.readFile(args[0],'utf8'));
  if (args[1]) await fs.writeFile(args[1],JSON.stringify(v,null,2));
  console.log(JSON.stringify(v,null,2));
} else if (action === 'export-library') {
  const items = JSON.parse(await fs.readFile(path.join(root,'output/validated-revision/library/selected.json'),'utf8'));
  for (const [key, dev] of Object.entries(items)) {
    const destination = path.join(root,'output/validated-revision/library',key+'.elibz2').replaceAll('\\','/');
    const v=await run(`const f=await eda.sys_FileManager.getDeviceFileByDeviceUuid(${JSON.stringify(dev.uuid)},${JSON.stringify(dev.libraryUuid)},"elibz2"); return {name:f?.name,size:f?.size,saved:f?await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(destination)},f,undefined,true):false};`);
    console.log(key,JSON.stringify(v));
    if (!v.saved) throw new Error('Library export failed: '+key);
  }
} else if (action === 'import') {
  const destination=path.resolve(args[0]).replaceAll('\\','/');
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo(); if(!p||!p.friendlyName.includes("revision"))throw new Error("Not an isolated revision project"); const f=await eda.sys_FileSystem.readFileFromFileSystem(${JSON.stringify(destination)}); const ESYS_ImportProjectImportOption={IMPORT_DOCUMENT:"ImportDocument"}; const result=await eda.sys_FileManager.importProjectByProjectFile(f,"EasyEDA Pro",{importOption:ESYS_ImportProjectImportOption.IMPORT_DOCUMENT},{operation:"Existing Project",existingProjectUuid:p.uuid});return {imported:result,project:await eda.dmt_Project.getCurrentProjectInfo()};`);
  await fs.writeFile(path.join(path.dirname(destination),'live-import.json'),JSON.stringify(v,null,2));
  console.log(JSON.stringify({imported:v.imported,boards:v.project?.data?.map(b=>({name:b.name,schematic:b.schematic?.uuid,pages:b.schematic?.page?.map(p=>({name:p.name,uuid:p.uuid}))}))},null,2));
} else if (action === 'validate') {
  const folder=path.resolve(args[0]);
  const expected=JSON.parse(await fs.readFile(path.join(folder,'expected-connectivity.json'),'utf8'));
  const result=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo(); const b=p?.data?.find(b=>b.name===${JSON.stringify(expected.name)}); if(!b?.schematic)throw new Error("Target schematic not found"); let pages=[];for(let attempt=0;attempt<8;attempt++){pages=(await eda.dmt_Schematic.getAllSchematicPagesInfo()).filter(x=>x.parentSchematicUuid===b.schematic.uuid);if(pages.length===${expected.pages.length})break;await new Promise(r=>setTimeout(r,500));}if(pages.length!==${expected.pages.length})throw new Error("Import not settled: incomplete page count"); const out=[]; for(const pg of pages){const tab=await eda.dmt_EditorControl.openDocument(pg.uuid);await new Promise(r=>setTimeout(r,500));const source=await eda.sys_FileManager.getDocumentSource(); const attrs={}; const ids=[]; for(const line of source.split("\\n")){if(!line.includes("||"))continue;const [a,z]=line.split("||");let h,v;try{h=JSON.parse(a);v=JSON.parse(z.replace(/\\|$/,""));}catch{continue;}if(h.type==="ATTR"){(attrs[v.parentId]??={})[v.key]=v.value;}if(h.type==="COMPONENT")ids.push(h.id);}const nc=${JSON.stringify(expected.noConnectPins)};const applied=[];for(const id of ids){const name=attrs[id]?.Designator;const needed=nc.filter(x=>x.designator===name);if(!needed.length)continue;const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);for(const pin of pins??[]){const number=pin.getState_PinNumber();if(needed.some(x=>x.pin===number)){const a=pin.toAsync();a.setState_NoConnected(true);await a.done();applied.push(name+"."+number);}}}const saved=await eda.sch_Document.save();const details=await eda.sch_Drc.check(true,false,true);const passed=await eda.sch_Drc.check(true,false,false);const ESYS_NetlistType={PROTEL2:"Protel2"};const netlist=await eda.sch_Netlist.getNetlist(ESYS_NetlistType.PROTEL2);out.push({page:pg.name,uuid:pg.uuid,tab,saved,appliedNoConnect:applied,passed,details,netlist,source:await eda.sys_FileManager.getDocumentSource()});}return {project:p.friendlyName,uuid:p.uuid,schematicUuid:b.schematic.uuid,pages:out};`);
  await fs.writeFile(path.join(folder,'live-validation.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({project:result.project,pages:result.pages.map(p=>({page:p.page,uuid:p.uuid,saved:p.saved,passed:p.passed,nc:p.appliedNoConnect,details:p.details,netlistLength:p.netlist?.length}))},null,2));
} else if(action === 'clean-copy') {
  const keep=args[0];
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo(); if(!p?.friendlyName.includes("revision")||!p.data.some(b=>b.name===${JSON.stringify(keep)}))throw new Error("Refusing to clean anything except a verified revision copy");const removed=[];for(const b of p.data){if(b.itemType!=="Board"||b.name===${JSON.stringify(keep)})continue;if(b.schematic)await eda.dmt_Schematic.deleteSchematic(b.schematic.uuid);if(b.pcb)await eda.dmt_Pcb.deletePcb(b.pcb.uuid);await eda.dmt_Board.deleteBoard(b.name);removed.push(b.name);}return {removed,project:await eda.dmt_Project.getCurrentProjectInfo()};`);
  console.log(JSON.stringify({removed:v.removed,remaining:v.project?.data?.map(b=>b.name)},null,2));
} else if(action === 'replace-import') {
  const folder=path.resolve(args[0]);const expected=JSON.parse(await fs.readFile(path.join(folder,'expected-connectivity.json'),'utf8'));
  const native=path.join(folder,expected.name+'.epro2').replaceAll('\\','/');
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.friendlyName!==${JSON.stringify(expected.name)})throw new Error("Not the intended revision copy");for(const b of p.data){if(b.itemType==="Board"){if(b.schematic)await eda.dmt_Schematic.deleteSchematic(b.schematic.uuid);if(b.pcb)await eda.dmt_Pcb.deletePcb(b.pcb.uuid);await eda.dmt_Board.deleteBoard(b.name);}else if(b.itemType==="Panel")await eda.dmt_Panel.deletePanel(b.uuid);}const f=await eda.sys_FileSystem.readFileFromFileSystem(${JSON.stringify(native)});const ESYS_ImportProjectImportOption={IMPORT_DOCUMENT:"ImportDocument"};const imported=await eda.sys_FileManager.importProjectByProjectFile(f,"EasyEDA Pro",{importOption:ESYS_ImportProjectImportOption.IMPORT_DOCUMENT},{operation:"Existing Project",existingProjectUuid:p.uuid});return {imported,project:await eda.dmt_Project.getCurrentProjectInfo()};`);
  await fs.writeFile(path.join(folder,'live-import.json'),JSON.stringify(v,null,2));console.log(JSON.stringify({imported:v.imported},null,2));
} else if(action === 'export-final') {
  const folder=path.resolve(args[0]); const name=path.basename(folder);
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.friendlyName!==${JSON.stringify(name)})throw new Error("Wrong revision");const pages=await eda.dmt_Schematic.getAllSchematicPagesInfo();const exports=[];for(let i=0;i<pages.length;i++){const pg=pages[i];await eda.dmt_EditorControl.openDocument(pg.uuid);await eda.sch_Document.save();const ESCH_ExportDocumentFileType={SVG:"SVG"};const image=await eda.sch_ManufactureData.getExportDocumentFile("page-"+(i+1),ESCH_ExportDocumentFileType.SVG,{theme:"Black on White",lineWidth:"Always 1px"},"Current Schematic Page");exports.push({page:pg.name,name:image?.name,size:image?.size,saved:image?await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(folder.replaceAll('\\','/')+'/')}+"page-"+(i+1)+".svg",image,undefined,true):false});}const f=await eda.sys_FileManager.getProjectFileByProjectUuid(p.uuid,${JSON.stringify(name)},undefined,"epro2");const saved=f?await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(path.join(folder,name+'.epro2').replaceAll('\\','/'))},f,undefined,true):false;return {project:p.friendlyName,uuid:p.uuid,nativeExportSaved:saved,nativeSize:f?.size,images:exports};`);
  await fs.writeFile(path.join(folder,'export-verification.json'),JSON.stringify(v,null,2));console.log(JSON.stringify(v,null,2));
} else if(action === 'export-native') {
  const folder=path.resolve(args[0]); const name=path.basename(folder);const target=path.join(folder,name+'.epro2').replaceAll('\\','/');
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.friendlyName!==${JSON.stringify(name)})throw new Error("Wrong revision");const f=await eda.sys_FileManager.getProjectFileByProjectUuid(p.uuid,${JSON.stringify(name)},undefined,"epro2");return {project:p.friendlyName,uuid:p.uuid,saved:f?await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(target)},f,undefined,true):false,size:f?.size};`);
  await fs.writeFile(path.join(folder,'export-verification.json'),JSON.stringify(v,null,2));console.log(JSON.stringify(v,null,2));
} else if(action==='reopen') {
  const folder=path.resolve(args[0]); const name=path.basename(folder);
  const v=await run(`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.friendlyName!==${JSON.stringify(name)})throw new Error("Wrong revision");const pages=await eda.dmt_Schematic.getAllSchematicPagesInfo();const out=[];for(const pg of pages){const tab=await eda.dmt_EditorControl.openDocument(pg.uuid);const saved=await eda.sch_Document.save();const closed=await eda.dmt_EditorControl.closeDocument(tab);const reopened=await eda.dmt_EditorControl.openDocument(pg.uuid);await new Promise(r=>setTimeout(r,500));const details=await eda.sch_Drc.check(true,false,true);const passed=await eda.sch_Drc.check(true,false,false);out.push({name:pg.name,pageUuid:pg.uuid,saved,closed,reopened,details,passed});}return {project:p.friendlyName,pages:out};`);
  await fs.writeFile(path.join(folder,'save-reopen-verification.json'),JSON.stringify(v,null,2));console.log(JSON.stringify(v,null,2));
} else throw new Error('Unknown action');
