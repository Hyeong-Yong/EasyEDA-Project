const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
await eda.dmt_EditorControl.openDocument('0ac2a19168000d8e');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!=='0ac2a19168000d8e')throw Error('Wrong page');
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const src=await eda.sys_FileManager.getDocumentSource();
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-metadata-repair-before.epru',new Blob([src]),undefined,false))throw Error('Already attempted');
const comp=await eda.pcb_PrimitiveComponent.get('8a92a6903fad3d44');if(!comp||comp.getState_Designator()!=='R137')throw Error('Wrong component');
await comp.setAttribute('Supplier Part','C852810',false,false);
await comp.setAttribute('Tolerance','0.1%',false,false);
const afterSource=await eda.sys_FileManager.getDocumentSource();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-metadata-repair-after.epru',new Blob([afterSource]),undefined,false);
const baseline=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/stage-pcb_pilot-before.epru')).text()),after=parse(afterSource);
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x),allowed=new Set(['Value','Name','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Part Number','Datasheet','Tolerance','Temperature Coefficient','Power Rating','Description','Package']);
const errors=[],changes=[];
for(const key of new Set([...baseline.keys(),...after.keys()])){const a=baseline.get(key),b=after.get(key);if(c(a?.b)===c(b?.b))continue;const r=b||a;if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;let ok=false;if(r.h.type==='COMPONENT'&&r.h.id==='8a92a6903fad3d44'&&a&&b){const x=structuredClone(a.b),y=structuredClone(b.b);for(const k of allowed){delete x.attrs[k];delete y.attrs[k];}ok=c(x)===c(y);}if(r.h.type==='ATTR'&&r.b.parentId==='8a92a6903fad3d44'&&allowed.has(r.b.key)){const x={...(a?.b||r.b)},y={...(b?.b||r.b)};delete x.value;delete y.value;ok=c(x)===c(y)&&!r.b.valueVisible&&!r.b.keyVisible;}changes.push({id:r.h.id,type:r.h.type,key:r.b.key,allowed:ok});if(!ok)errors.push(changes.at(-1));}
const attr={...after.get('COMPONENT:8a92a6903fad3d44').b.attrs};for(const {h,b} of after.values())if(h.type==='ATTR'&&b.parentId==='8a92a6903fad3d44')attr[b.key]=b.value;
for(const [k,v] of Object.entries({'Value':'4.02k','Supplier Part':'C852810',Tolerance:'0.1%','Manufacturer Part':'RT0402BRD074K02L'}))if(attr[k]!==v)errors.push({key:k,expected:v,actual:attr[k]});
const receipt={changes,errors,saved:false};if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-metadata-repair-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('PCB repair audit failed; do not retry');return receipt;
