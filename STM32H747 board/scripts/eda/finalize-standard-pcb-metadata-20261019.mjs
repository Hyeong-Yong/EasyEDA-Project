// Review the exact native normalization: Tolerance is omitted from COMPONENT.attrs
// on 22 footprints. The authoritative SCH properties and BOM retain it. No
// geometry/identity exception is permitted; no change to the rules or copper.
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
await eda.dmt_EditorControl.openDocument(plan.pcbUuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==plan.pcbUuid)throw Error('Wrong PCB');
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
const intended=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/pcb-source-proposed.epru')).text()),actualSource=await eda.sys_FileManager.getDocumentSource(),actual=parse(actualSource),targets=new Map(plan.pcbTargets.map(t=>[t.componentId,t])),errors=[],normalizations=[];
for(const key of new Set([...intended.keys(),...actual.keys()])){
 const a=intended.get(key),b=actual.get(key);if((a||b).h.type==='DOCHEAD'||c(a?.b)===c(b?.b))continue;
 let reviewed=false;
 if(a&&b&&a.h.type==='COMPONENT'&&targets.has(a.h.id)&&a.b.attrs.Tolerance===targets.get(a.h.id).spec.Tolerance&&!Object.hasOwn(b.b.attrs,'Tolerance')){
  const x=structuredClone(a.b);delete x.attrs.Tolerance;reviewed=c(x)===c(b.b);if(reviewed)normalizations.push({ref:targets.get(a.h.id).ref,id:a.h.id,key:'Tolerance',intended:a.b.attrs.Tolerance,actual:'omitted by native PCB serialization; retained in schematic and BOM'});
 }
 if(!reviewed)errors.push(key);
}
if(normalizations.length!==22)errors.push('Unexpected normalization count '+normalizations.length);
const receipt={targets:25,normalizations,errors,saved:false};if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-final-source.epru',new Blob([await eda.sys_FileManager.getDocumentSource()]),undefined,false);
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-finalize-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Final PCB metadata audit failed');return {targets:25,reviewedNativeOmissions:normalizations.length,saved:receipt.saved,errors};
