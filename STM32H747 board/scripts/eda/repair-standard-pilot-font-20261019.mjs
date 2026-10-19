// Attribute fontSize API uses a different scale from the native source (x100).
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
await eda.dmt_EditorControl.openDocument('a07bf8e4331877a8');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!=='a07bf8e4331877a8')throw Error('Wrong page');
const src=await eda.sys_FileManager.getDocumentSource();
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-font-repair-before.epru',new Blob([src]),undefined,false))throw Error('Already attempted');
for(const id of ['bd54bd6a193d563c','bdceb9fb41bf50bf'])if(!await eda.sch_PrimitiveAttribute.modify(id,{fontSize:0.048}))throw Error('Font repair failed');
const afterSource=await eda.sys_FileManager.getDocumentSource();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-font-repair-after.epru',new Blob([afterSource]),undefined,false);
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const baseline=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/stage-pilot-before.epru')).text()),after=parse(afterSource);
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x),allowed=new Set(['Value','Name','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Part Number','Datasheet','Tolerance','Temperature Coefficient','Power Rating','Description','Package']);
const errors=[],changes=[];
for(const key of new Set([...baseline.keys(),...after.keys()])){const a=baseline.get(key),b=after.get(key);if(c(a?.b)===c(b?.b))continue;const r=b||a;if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;let ok=false;if(r.h.type==='ATTR'&&r.b.parentId==='8aca3284ddf555cd'&&allowed.has(r.b.key)){const x={...(a?.b||r.b)},y={...(b?.b||r.b)};delete x.value;delete y.value;ok=c(x)===c(y);}changes.push({id:r.h.id,key:r.b.key,allowed:ok});if(!ok)errors.push(changes.at(-1));}
const receipt={changes,errors,saved:false};if(!errors.length)receipt.saved=await eda.sch_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-font-repair-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Font repair audit failed, do not retry');return {saved:receipt.saved,changedRecords:changes.length,errors};
