const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',mode=__taskArgs[0];
if(!['title','rest'].includes(mode))throw new Error('Explicit reviewed silk direction stage required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),strings=before.filter(r=>r.h.type==='STRING');
if(strings.length!==21||strings.some(r=>r.b.layerId!==4))throw new Error('Unexpected J18 native strings');
const targets=mode==='title'?strings.filter(r=>r.b.text==='J18 SPI2'):strings.filter(r=>r.b.text!=='J18 SPI2');
if(targets.length!==(mode==='title'?1:20)||targets.some(r=>r.b.mirror!==true))throw new Error('Unexpected silk direction baseline');
const ids=new Set(targets.map(r=>r.h.id));
for(const r of targets){
 const p=await eda.pcb_PrimitiveString.get(r.h.id);
 if(!p||Array.isArray(p))throw new Error('J18 string unavailable');
 const a=p.toAsync();a.setState_X(r.b.x);a.setState_Y(r.b.y);a.setState_FontSize(r.b.fontSize);a.setState_LineWidth(r.b.strokeWidth);a.setState_Rotation(r.b.angle);a.setState_Mirror(false);await a.done();
}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),map=new Map(after.map(r=>[r.h.type+':'+r.h.id,r])),errors=[];
for(const r of before){if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type))continue;const e={...r.b};if(ids.has(r.h.id))e.mirror=false;const a=map.get(r.h.type+':'+r.h.id);if(canonical(e)!==canonical(a?.b))errors.push({id:r.h.id,type:r.h.type,expected:e,actual:a?.b});}
if(after.length!==before.length)errors.push({error:'record count'});
const path=root+'/output/validation/native-j18-direction-'+mode+'-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([afterSource]),undefined,false);
const receipt={mode,path,changes:targets.length,errors,saved:false};
if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-j18-direction-'+mode+'-receipt-20261016.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(!receipt.saved||errors.length)throw new Error('Silk direction preservation failed');return{saved:true,path,changes:targets.length,errors:0};
