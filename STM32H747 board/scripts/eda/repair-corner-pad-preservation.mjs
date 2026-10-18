const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const file=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-corner-pads-receipt-20261016.json'),receipt=JSON.parse(await file.text());
if(receipt.saved!==false||receipt.errors.length!==4||receipt.errors.some(e=>!e.key?.startsWith('PAD:')))throw new Error('Unexpected pad recovery');
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const retryFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-corner-pads-preservation-receipt-20261016.json'),retry=JSON.parse(await retryFile.text());
if(retry.saved!==false||retry.errors.length!==4)throw new Error('Unexpected coordinate-rounding recovery');
const retryMap=new Map(retry.errors.map(e=>[e.key,e.actual]));
const before=parse(await eda.sys_FileManager.getDocumentSource()),map=new Map(before.map(r=>[r.h.type+':'+r.h.id,r]));
const EPCB_PrimitivePadShapeType={ELLIPSE:'ELLIPSE'};
for(const e of receipt.errors){
 if(canonical(map.get(e.key)?.b)!==canonical(retryMap.get(e.key)))throw new Error('Pad recovery current state changed');
 const p=await eda.pcb_PrimitivePad.get(e.key.slice(4)),a=p.toAsync();
 a.setState_X(e.expected.centerX);a.setState_Y(e.expected.centerY);
 a.setState_Pad([EPCB_PrimitivePadShapeType.ELLIPSE,e.expected.defaultPad.width,e.expected.defaultPad.height]);
 a.setState_SolderMaskAndPasteMaskExpansion(null);await a.done();
}
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r])),targets=new Map(receipt.errors.map(e=>[e.key,e.expected])),errors=[];
for(const r of before){if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type))continue;const key=r.h.type+':'+r.h.id,e=targets.get(key)||r.b,a=actual.get(key);if(canonical(a?.b)!==canonical(e))errors.push({key,expected:e,actual:a?.b});}
if(after.length!==before.length)errors.push({error:'record count'});
const path=root+'/output/validation/native-corner-pads-preserved-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false);
let saved=false;if(!errors.length)saved=await eda.pcb_Document.save();
const result={saved,path,errors};
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-corner-pads-preservation-receipt-20261016.json',new Blob([JSON.stringify(result,null,2)]),undefined,false);
if(!saved||errors.length)throw new Error('Pad preservation recovery incomplete');return{saved,path,errors:0};
