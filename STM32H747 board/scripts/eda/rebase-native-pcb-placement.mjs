const pcbUuid='3ca9811d1a42d086';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const input=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-pcb/native-pcb-placed.epru');
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
const placed=new Map(parse(await input.text()).filter(r=>r.head.id).map(r=>[r.head.id,r]));
const current=await eda.sys_FileManager.getDocumentSource();
const records=parse(current);
let components=0,attributes=0;
for(const record of records){
if(record.head.type==='COMPONENT'){
const desired=placed.get(record.head.id);
if(desired?.head.type!=='COMPONENT')throw new Error('PCB placement identity missing');
record.body.x=desired.body.x;record.body.y=desired.body.y;record.body.angle=desired.body.angle;components++;
}else if(record.head.type==='ATTR'){
const desired=placed.get(record.head.id);
if(desired?.head.type!=='ATTR'||desired.body.value!==record.body.value)throw new Error('PCB attribute identity changed');
record.body.x=desired.body.x;record.body.y=desired.body.y;attributes++;
}
}
if(components!==330||attributes!==990)throw new Error('PCB rebase identity counts wrong');
const source=records.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))).join('|\n');
const accepted=await eda.sys_FileManager.setDocumentSource(source);
if(!accepted)return {accepted:false,components,attributes};
const saved=await eda.pcb_Document.save();
await eda.dmt_EditorControl.zoomToAllPrimitives(pcbUuid);
return {accepted,saved,components,attributes};
