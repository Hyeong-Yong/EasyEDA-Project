// ECO preview identified Name literal versus schematic ={Value} expressions.
// Synchronize only these 25 metadata values; leave all physical records intact.
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
await eda.dmt_EditorControl.openDocument(plan.pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==plan.pcbUuid)throw Error('Wrong PCB');
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const src=await eda.sys_FileManager.getDocumentSource(),before=parse(src),ids=new Map(plan.pcbTargets.map(t=>[t.componentId,t]));
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/name-sync-before.epru',new Blob([src]),undefined,false))throw Error('Already attempted');
let n=0;const candidate=src.split(/\r?\n/).map(l=>{const p=l.indexOf('||');if(p<0)return l;const h=JSON.parse(l.slice(0,p)),t=ids.get(h.id);if(h.type!=='COMPONENT'||!t)return l;const b=JSON.parse(l.slice(p+2).replace(/\|$/,''));if(b.attrs['Manufacturer Part']!==t.spec.mpn||b.attrs.Name!==b.attrs.Value)throw Error('Target changed '+t.ref);b.attrs.Name='={Value}';n++;return l.slice(0,p+2)+JSON.stringify(b)+'|';}).join('\n');
if(n!==25||!await eda.sys_FileManager.setDocumentSource(candidate))throw Error('Name sync failed');
const afterSrc=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSrc),expected=parse(candidate),errors=[];
for(const key of new Set([...expected.keys(),...after.keys()]))if((expected.get(key)||after.get(key)).h.type!=='DOCHEAD'&&c(expected.get(key)?.b)!==c(after.get(key)?.b))errors.push(key);
const receipt={nameExpressions:25,errors,saved:false};if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/name-sync-after.epru',new Blob([afterSrc]),undefined,false);
await eda.sys_FileSystem.saveFileToFileSystem(root+'/name-sync-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Name sync readback failed');return receipt;
