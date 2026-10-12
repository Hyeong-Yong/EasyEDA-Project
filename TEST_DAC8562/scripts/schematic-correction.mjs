import fs from 'node:fs/promises';
import path from 'node:path';
const root = path.resolve(import.meta.dirname, '..');
const targetUuid = 'dd59729173ceab597e015b7842a752ad416a6b41fb9eba8523f1bdbee791bf03';
const output = path.join(root, 'output/schematic-correction');
await fs.mkdir(output, {recursive:true});
const [action, ...args] = process.argv.slice(2);
const inventory = await (await fetch('http://127.0.0.1:49620/eda-windows')).json();
if(inventory.count!==1) throw new Error('Exactly one connected EasyEDA window is required.');
const windowId = inventory.windows[0].windowId;
async function run(code) {
  const guard=`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.uuid!==${JSON.stringify(targetUuid)}||p.friendlyName!=="DAC8562 module")throw new Error("Refusing to modify a different project");`;
  const response=await (await fetch('http://127.0.0.1:49620/execute',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({windowId,code:guard+code})})).json();
  if(!response.success) throw new Error(JSON.stringify(response));
  return response.result;
}
let result;
if(action==='code') {
  result=await run(await fs.readFile(args[0],'utf8'));
} else if(action==='seed') {
  const selected=JSON.parse(await fs.readFile(path.join(root,'output/validated-revision/library/selected.json'),'utf8'));
  const devices=args.map(key=>({key,libraryUuid:selected[key].libraryUuid,uuid:selected[key].uuid}));
  result=await run(`await eda.dmt_EditorControl.openDocument("e3a1c5f417017755");const created=[];for(const [i,d] of ${JSON.stringify(devices)}.entries()){const c=await eda.sch_PrimitiveComponent.create({libraryUuid:d.libraryUuid,uuid:d.uuid},200+i*200,200,undefined,0,false,true,true);if(!c)throw new Error("Cannot load device "+d.key);const a=c.toAsync();a.setState_Designator("SEED_"+d.key);await a.done();created.push({key:d.key,id:c.getState_PrimitiveId()});}return {created};`);
} else if(action==='export') {
  const destination=path.resolve(args[0]).replaceAll('\\','/');
  result=await run(`const f=await eda.sys_FileManager.getProjectFileByProjectUuid(p.uuid,"DAC8562 module",undefined,"epro2");if(!f)throw new Error("Export unavailable");return {saved:await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(destination)},f,undefined,false),size:f.size};`);
} else if(action==='apply-page') {
  if(!['e58bcc16379b10f4','e3a1c5f417017755'].includes(args[0])) throw new Error('Only the two original schematic pages are allowed.');
  const source=(await fs.readFile(args[1],'utf8')).replace(/\r\n/g,'\n').trim().replace(/\|$/,'');
  result=await run(`await eda.dmt_EditorControl.openDocument(${JSON.stringify(args[0])});const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!==${JSON.stringify(args[0])}||d.documentType!==1)throw new Error("Wrong active schematic page");const applied=await eda.sys_FileManager.setDocumentSource(${JSON.stringify(source)});if(!applied)throw new Error("Source rejected");return {applied,page:d.uuid};`);
} else if(action==='sync-netlist') {
  const v=JSON.parse(await fs.readFile(path.join(output,'erc-final-validation.json'),'utf8'));
  if(v.pages.some(p=>!p.passed||p.details.length)) throw new Error('Schematic ERC is not clean');
  result=await run(`await eda.dmt_EditorControl.openDocument("4e08f91f9a2c4fe4");const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=="4e08f91f9a2c4fe4"||d.documentType!==3)throw new Error("Wrong PCB");const ESYS_NetlistType={PROTEL2:"Protel2"};return {updated:await eda.pcb_Net.setNetlist(ESYS_NetlistType.PROTEL2,${JSON.stringify(v.pages[0].netlist)}),components:(await eda.pcb_PrimitiveComponent.getAll()).length};`);
} else if(action==='apply-pcb') {
  await fs.access(path.join(output,'DAC8562 module_schematic_ERC_clean.eprj2'));
  const source=(await fs.readFile(args[0],'utf8')).replace(/\r\n/g,'\n').trim().replace(/\|$/,'');
  if(!source.includes('"docType":"PCB"')&&!source.includes('"docType": "PCB"')) throw new Error('Expected PCB source');
  result=await run(`await eda.dmt_EditorControl.openDocument("4e08f91f9a2c4fe4");const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=="4e08f91f9a2c4fe4"||d.documentType!==3)throw new Error("Wrong PCB");const applied=await eda.sys_FileManager.setDocumentSource(${JSON.stringify(source)});if(!applied)throw new Error("PCB source rejected");return {applied,components:(await eda.pcb_PrimitiveComponent.getAll()).length,pads:(await eda.pcb_PrimitivePad.getAll()).length};`);
} else if(action==='seed-pcb-model') {
  const seeds=JSON.parse(await fs.readFile(path.join(root,'output/pcb-two-zone/seed-references.json'),'utf8')).slice(Number(args[0]),Number(args[1]));
  result=await run(`const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=="4e08f91f9a2c4fe4"||d.documentType!==3)throw new Error("Wrong PCB");const EPCB_LayerId={TOP:1};const loaded=[];for(const [i,s] of ${JSON.stringify(seeds)}.entries()){const c=await eda.pcb_PrimitiveComponent.create({uuid:s.uuid,libraryUuid:s.libraryUuid},EPCB_LayerId.TOP,20000+i*1000,20000,0,false);if(!c)throw new Error("Cannot load footprint "+s.name);loaded.push({name:s.name,id:c.getState_PrimitiveId()});}return {loaded};`);
} else if(action==='export-dsn') {
  const destination=path.resolve(args[0]).replaceAll('\\','/');
  result=await run(`const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!=="4e08f91f9a2c4fe4"||d.documentType!==3)throw new Error("Wrong PCB");const f=await eda.pcb_ManufactureData.getDsnFile("two-zone");if(!f)throw new Error("DSN export failed");return {saved:await eda.sys_FileSystem.saveFileToFileSystem(${JSON.stringify(destination)},f,undefined,false),size:f.size};`);
} else throw new Error('Unknown action: '+action);
if(action==='code'&&args[1]) await fs.writeFile(args[1],JSON.stringify(result,null,2));
const summary=result?.source?{...Object.fromEntries(Object.entries(result).filter(([k])=>!['source','netlist','components','pads'].includes(k))),sourceLength:result.source.length}:result?.pages?{...result,pages:result.pages.map(({source,netlist,...p})=>({...p,sourceLength:source?.length,netlistLength:netlist?.length}))}:result?.netlist?{...Object.fromEntries(Object.entries(result).filter(([k])=>k!=='netlist')),netlistLength:result.netlist.length}:result;
console.log(JSON.stringify(summary,null,2));
