const name='STM32H747_PCB_LOAD_PROBE';
let info=(await eda.dmt_Pcb.getAllPcbsInfo()).find(p=>p.name===name);
let uuid=info?.uuid;
if(!uuid){uuid=await eda.dmt_Pcb.createPcb();if(!uuid)throw new Error('Scoped constructor probe creation failed');await new Promise(r=>setTimeout(r,1600));}
const tab=await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong constructor probe');
if(!info)await eda.dmt_Pcb.modifyPcbName(uuid,name);
const current=await eda.sys_FileManager.getDocumentSource();
const baseline=current.split(/\r?\n/).filter(l=>l.includes('||')&&!['COMPONENT','ATTR','PAD_NET','NET'].includes(JSON.parse(l.split('||')[0]).type)).map(l=>l.replace(/\|$/,'')).join('|\n');
const file=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/native-pcb/native-pcb-placed.epru');
const rows=(await file.text()).split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');return {head:JSON.parse(h),body:JSON.parse(b.replace(/\|$/,''))};});
const attrs=rows.filter(r=>r.head.type==='ATTR');
const result=[];
for(const reference of (__taskArgs[0]==='mixed_control'?['U5','CN3','CN4','CN1']:['npth_map_only','foot_only'].includes(__taskArgs[0])?['CN1']:['CN1','CN2','R1'])){
const id=attrs.find(r=>r.body.key==='Designator'&&r.body.value===reference)?.body.parentId;
if(!id)throw new Error('Probe reference not found');
const append=rows.filter(r=>r.head.type==='NET'||r.head.id===id||r.head.type==='ATTR'&&r.body.parentId===id&&(__taskArgs[0]!=='foot_only'||r.body.key!=='Device')||r.head.type==='PAD_NET'&&JSON.parse(r.head.id)[1]===id&&(__taskArgs[0]!=='npth_map_only'||JSON.parse(r.head.id)[2]!==''));
const source=baseline.replace(/\|$/,'')+'|\n'+append.map(r=>JSON.stringify(r.head)+'||'+JSON.stringify(r.body)).join('|\n');
const accepted=await eda.sys_FileManager.setDocumentSource(source);
const live=await eda.pcb_PrimitiveComponent.getAll();
const actual=await eda.sys_FileManager.getDocumentSource();
const saved=await eda.sys_FileSystem.saveFileToFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/native-constructor-probe-'+reference+'.epru',new Blob([actual]),undefined,false);
result.push({reference,accepted,liveComponents:live.length,liveReferences:live.map(c=>c.getState_Designator()),saved,omittedUnnumberedMap:__taskArgs[0]==='npth_map_only'});
}
return {uuid,name,tab,result};
