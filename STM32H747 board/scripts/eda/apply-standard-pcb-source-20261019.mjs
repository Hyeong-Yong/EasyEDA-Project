// Native PCB document source patch, limited to 25 COMPONENT.attrs objects.
// Used after native component APIs omitted the Tolerance field. Does not update
// master footprints or reinterpret footprint-format source.
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
if(plan.projectUuid!==__p.uuid||plan.pcbTargets.length!==25||plan.netGeometryChangesAllowed!==false)throw Error('Plan guard');
await eda.dmt_EditorControl.openDocument(plan.pcbUuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==plan.pcbUuid)throw Error('Wrong page');
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
const source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),targets=new Map(plan.pcbTargets.map(t=>[t.componentId,t]));
const nativeBaseline=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/baseline-pcb.epru')).text());
const expected=new Map();
for(const t of targets.values()){
 const r=before.get('COMPONENT:'+t.componentId);if(!r||r.b.attrs?.['Unique ID']!==t.beforeAttrs['Unique ID'])throw Error('Identity changed '+t.ref);
 for(const [k,v] of Object.entries(t.geometry)){
  const bv=nativeBaseline.get('COMPONENT:'+t.componentId)?.b[k];
  if(k==='angle'&&((bv-v)%360)===0){if(r.b[k]!==bv)throw Error('Native baseline angle changed '+t.ref);}
  else if(bv!==v||r.b[k]!==v)throw Error('Geometry changed '+t.ref+' '+k);
 }
 const v=r.b.attrs.Value;if(v!==(t.ref==='R137'?t.spec.value:t.spec.oldValue))throw Error('Unexpected value '+t.ref);
 const s=t.spec;expected.set(t.componentId,{Value:s.value,Name:s.value,Manufacturer:s.manufacturer,'Manufacturer Part':s.mpn,Supplier:'LCSC','Supplier Part':s.lcsc,'Part Number':s.mpn,Datasheet:s.Datasheet,Tolerance:s.Tolerance,'Temperature Coefficient':s['Temperature Coefficient'],'Power Rating':s['Power Rating'],Description:s.Description,Package:s.Package});
}
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-source-before.epru',new Blob([source]),undefined,false))throw Error('Already attempted');
let n=0;
const candidate=source.split(/\r?\n/).map(l=>{const p=l.indexOf('||');if(p<0)return l;const h=JSON.parse(l.slice(0,p));if(h.type!=='COMPONENT'||!targets.has(h.id))return l;const b=JSON.parse(l.slice(p+2).replace(/\|$/,''));Object.assign(b.attrs,expected.get(h.id));n++;return l.slice(0,p+2)+JSON.stringify(b)+'|';}).join('\n');
if(n!==25)throw Error('Candidate target count');
const proposed=parse(candidate);for(const [key,a] of before){const b=proposed.get(key);if(!b)throw Error('Candidate removed record');if(c(a.b)===c(b.b))continue;if(a.h.type!=='COMPONENT'||!targets.has(a.h.id))throw Error('Candidate out of scope');const x=structuredClone(a.b),y=structuredClone(b.b);for(const k of Object.keys(expected.get(a.h.id))){delete x.attrs[k];delete y.attrs[k];}if(c(x)!==c(y))throw Error('Candidate geometry changed');}
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-source-proposed.epru',new Blob([candidate]),undefined,false);
if(!await eda.sys_FileManager.setDocumentSource(candidate))throw Error('Native source apply rejected; do not retry');
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),errors=[];
for(const key of new Set([...proposed.keys(),...after.keys()])){const a=proposed.get(key),b=after.get(key);if((a||b).h.type==='DOCHEAD')continue;if(c(a?.b)!==c(b?.b))errors.push({key});}
for(const [id,attrs] of expected){const a=after.get('COMPONENT:'+id)?.b.attrs||{};for(const [k,v] of Object.entries(attrs))if(a[k]!==v)errors.push({id,key:k,expected:v,actual:a[k]});}
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-source-after.epru',new Blob([afterSource]),undefined,false);
const receipt={targets:25,recordsBefore:before.size,recordsAfter:after.size,exactProposedReadback:errors.length===0,errors,saved:false};if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pcb-source-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Native source readback failed; inspect receipt');return receipt;
