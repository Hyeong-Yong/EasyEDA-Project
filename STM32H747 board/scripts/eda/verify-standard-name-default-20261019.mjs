const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
await eda.dmt_EditorControl.openDocument(plan.pcbUuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==plan.pcbUuid)throw Error('Wrong PCB');
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x),before=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/name-sync-before.epru')).text()),after=parse(await eda.sys_FileManager.getDocumentSource()),ids=new Set(plan.pcbTargets.map(t=>t.componentId)),errors=[];let n=0;
for(const key of new Set([...before.keys(),...after.keys()])){const a=before.get(key),b=after.get(key);if((a||b).h.type==='DOCHEAD'||c(a?.b)===c(b?.b))continue;let ok=false;if(a&&b&&a.h.type==='COMPONENT'&&ids.has(a.h.id)&&a.b.attrs.Name===a.b.attrs.Value&&!Object.hasOwn(b.b.attrs,'Name')){const x=structuredClone(a.b);delete x.attrs.Name;ok=c(x)===c(b.b);if(ok)n++;}if(!ok)errors.push(key);}
if(n!==25)errors.push('Default Name normalization count '+n);
await new Promise(r=>setTimeout(r,1200));const violations=await eda.pcb_Drc.check(true,true,true);
await eda.sys_FileSystem.saveFileToFileSystem(root+'/native/strict-drc-final.json',new Blob([JSON.stringify({strict:true,violations},null,2)]),undefined,false);
if(violations.length)errors.push('Strict DRC not zero');
const receipt={defaultNameExpressions:25,errors,saved:false};if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/name-default-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Name default or DRC validation failed');return receipt;
