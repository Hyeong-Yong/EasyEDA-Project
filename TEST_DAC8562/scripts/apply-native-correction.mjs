import fs from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const out=path.join(root,'output/schematic-correction');
const plans=JSON.parse(await fs.readFile(path.join(out,'native-operations.json'),'utf8'));
for(const plan of plans){
 const file=plan.page==='e58bcc16379b10f4'?'DAC8562.corrected-source.txt':'DAC_MCU.corrected-source.txt';
 const attrs=new Map();
 for(const line of (await fs.readFile(path.join(out,file),'utf8')).replace(/\r\n/g,'\n').split('\n')){if(!line.includes('||'))continue;const [a,b]=line.split('||');const h=JSON.parse(a);if(h.type==='ATTR')attrs.set(h.id,JSON.parse(b.replace(/\|$/,'')));}
 for(const attr of plan.attributes){const p=attrs.get(attr.id);attr.parent=p.parentId;attr.key=p.key;}
}
const inventory=await(await fetch('http://127.0.0.1:49620/eda-windows')).json();
if(inventory.count!==1)throw new Error('One connected window is required');
const windowId=inventory.windows[0].windowId;
const projectUuid='dd59729173ceab597e015b7842a752ad416a6b41fb9eba8523f1bdbee791bf03';
let journal=[];
try{journal=JSON.parse(await fs.readFile(path.join(out,'native-operation-journal.json'),'utf8'));}catch{}
async function execute(page,code){
  const guard=`const p=await eda.dmt_Project.getCurrentProjectInfo();if(p?.uuid!==${JSON.stringify(projectUuid)})throw new Error("Wrong original project");await eda.dmt_EditorControl.openDocument(${JSON.stringify(page)});const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!==${JSON.stringify(page)}||d.documentType!==1)throw new Error("Wrong schematic page");`;
  const r=await(await fetch('http://127.0.0.1:49620/execute',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({windowId,code:guard+code})})).json();
  if(!r.success)throw new Error(JSON.stringify(r));
  return r.result;
}
async function step(page,key,code){
  if(journal.some(x=>x.key===page+':'+key))return;
  const result=await execute(page,code);
  journal.push({key:page+':'+key,result});
  await fs.writeFile(path.join(out,'native-operation-journal.json'),JSON.stringify(journal,null,2));
  console.log(page,key,JSON.stringify(result));
}
for(const plan of plans){
 const page=plan.page;
 await step(page,'delete-wires',`return {deleted:${plan.deleteWires.length}?await eda.sch_PrimitiveWire.delete(${JSON.stringify(plan.deleteWires)}):true};`);
 await step(page,'delete-components',`return {deleted:${plan.deleteComponents.length}?await eda.sch_PrimitiveComponent.delete(${JSON.stringify(plan.deleteComponents)}):true};`);
 await step(page,'delete-texts',`return {deleted:${plan.deleteTexts.length}?await eda.sch_PrimitiveText.delete(${JSON.stringify(plan.deleteTexts)}):true};`);
 for(let i=0;i<plan.components.length;i+=5){
  const chunk=plan.components.slice(i,i+5);
  await step(page,'components-'+i,`const result=[];for(const o of ${JSON.stringify(chunk)}){const c=await eda.sch_PrimitiveComponent.create(o.device,o.item.x,-o.item.y,o.item.partId,o.item.rotation,o.item.isMirror,true,true);if(!c)throw new Error("Creation failed: "+o.props.Designator);const a=c.toAsync();a.setState_Designator(o.props.Designator);a.setState_Name(o.props.Name);a.setState_UniqueId(o.props["Unique ID"]);a.setState_Manufacturer(o.props.Manufacturer);a.setState_ManufacturerId(o.props["Manufacturer Part"]);a.setState_Supplier(o.props.Supplier);a.setState_SupplierId(o.props["Supplier Part"]);const extra={...c.getState_OtherProperty()};for(const [k,v]of Object.entries(o.props)){if(v!==null&&!['Device','Symbol','Footprint','3D Model','3D Model Title','3D Model Transform','Designator','Name','Unique ID','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Add into BOM','Convert to PCB'].includes(k))extra[k]=v;}a.setState_OtherProperty(extra);await a.done();const attrs=await eda.sch_PrimitiveAttribute.getAll(c.getState_PrimitiveId());for(const prop of attrs){const target=o.style[prop.getState_Key()];if(!target)continue;const ap=prop.toAsync();ap.setState_X(target.x);ap.setState_Y(-target.y);ap.setState_FontName('Arial');ap.setState_FontSize(target.fontSize??6);ap.setState_ValueVisible(true);await ap.done();}result.push({desiredId:o.id,actualId:c.getState_PrimitiveId(),name:o.props.Designator});}return result;`);
 }
 for(let i=0;i<plan.attributes.length;i+=15){
  const chunk=plan.attributes.slice(i,i+15);
  await step(page,'attributes-'+i,`const result=[];for(const o of ${JSON.stringify(chunk)}){const all=await eda.sch_PrimitiveAttribute.getAll(o.parent);const prop=all.find(x=>x.getState_Key()===o.key);if(!prop)throw new Error("Missing attribute "+o.id);const a=prop.toAsync();a.setState_Value(String(o.value));await a.done();result.push(o.id);}return {updated:result.length};`);
 }
 if(plan.moveComponents?.length)await step(page,'frame-position',`for(const o of ${JSON.stringify(plan.moveComponents)}){const c=await eda.sch_PrimitiveComponent.get(o.id);const a=c.toAsync();a.setState_X(o.x);a.setState_Y(-o.y);await a.done();}return true;`);
 for(let i=0;i<plan.wires.length;i+=15){
  const chunk=plan.wires.slice(i,i+15);
  await step(page,'wires-'+i,`const result=[];for(const o of ${JSON.stringify(chunk)}){const lines=o.segments.map(s=>s.map((v,i)=>i%2?-v:v));const w=await eda.sch_PrimitiveWire.create(lines,o.net||undefined);if(!w)throw new Error("Wire rejected "+o.id+" "+o.net);if(o.net){const attrs=await eda.sch_PrimitiveAttribute.getAll(w.getState_PrimitiveId());const n=attrs.find(x=>x.getState_Key()==='NET');if(n){const a=n.toAsync();a.setState_ValueVisible(true);a.setState_FontSize(5);await a.done();}}result.push({desiredId:o.id,actualId:w.getState_PrimitiveId()});}return {count:result.length,wires:result};`);
 }
 await step(page,'texts',`const ESCH_PrimitiveTextAlignMode={LEFT_BOTTOM:3};const current=await eda.sys_FileManager.getDocumentSource();for(const o of ${JSON.stringify(plan.texts)}){if(current.includes(JSON.stringify(o.value)))continue;const t=await eda.sch_PrimitiveText.create(o.x,-o.y,o.value,o.rotation??0,o.color??'#243746',o.fontFamily??'Arial',o.fontSize??9,o.fontWeight??false,false,false,ESCH_PrimitiveTextAlignMode.LEFT_BOTTOM);if(!t)throw new Error("Text failed");}return true;`);
}
