const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const [stage]=__taskArgs;if(!['sch','pcb'].includes(stage))throw Error('Explicit stage');
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
const changes={R197:{Value:'4.7Ω'},R200:{Value:'4.7Ω'},R201:{Value:'1.2Ω',Manufacturer:'UNI-ROYAL(厚声)',Tolerance:'±1%','Temperature Coefficient':'±400ppm/℃',Description:'REF5025 output capacitor series ESR resistor; 1.2 ohm, 1%, 0402, 62.5mW; conservative catalog TCR 400 ppm/K'},R202:{Value:'14.7kΩ',Manufacturer:'RESI(开步睿思)',Tolerance:'±0.1%','Temperature Coefficient':'±10ppm/℃'},R203:{Value:'9.31kΩ',Manufacturer:'RESI(开步睿思)',Tolerance:'±0.1%','Temperature Coefficient':'±10ppm/℃'}};
const targets=(stage==='sch'?plan.pages['360993a3108b5759'].targets:plan.pcbTargets.filter(t=>Object.hasOwn(changes,t.ref)));
const page=stage==='sch'?'360993a3108b5759':plan.pcbUuid;
await eda.dmt_EditorControl.openDocument(page);if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==page)throw Error('Wrong page');
function parse(s){const m=new Map();for(const l of s.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p));m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(l.slice(p+2).replace(/\|$/,''))});}return m;}
const c=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x),source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),ids=new Set(targets.map(t=>t.componentId));
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/catalog-'+stage+'-before.epru',new Blob([source]),undefined,false))throw Error('Already attempted');
if(stage==='sch')for(const t of targets){
 const attr=new Map([...before.values()].filter(r=>r.h.type==='ATTR'&&r.b.parentId===t.componentId).map(r=>[r.b.key,r]));
 if(attr.get('Manufacturer Part')?.b.value!==t.spec.mpn)throw Error('MPN changed');
 for(const [key,value] of Object.entries(changes[t.ref])){const a=attr.get(key);if(!a||!await eda.sch_PrimitiveAttribute.modify(a.h.id,{value}))throw Error('Attribute missing '+t.ref+' '+key);}
 if(!await eda.sch_PrimitiveAttribute.modify(attr.get('Supplier Part').h.id,{value:t.spec.lcsc}))throw Error('Supplier reset failed');
}else{
 const mapped=new Map(targets.map(t=>[t.componentId,t]));
 const candidate=source.split(/\r?\n/).map(l=>{const p=l.indexOf('||');if(p<0)return l;const h=JSON.parse(l.slice(0,p)),t=mapped.get(h.id);if(h.type!=='COMPONENT'||!t)return l;const b=JSON.parse(l.slice(p+2).replace(/\|$/,''));if(b.attrs['Manufacturer Part']!==t.spec.mpn)throw Error('MPN changed');Object.assign(b.attrs,changes[t.ref]);b.attrs.Name=changes[t.ref].Value;return l.slice(0,p+2)+JSON.stringify(b)+'|';}).join('\n');
 if(!await eda.sys_FileManager.setDocumentSource(candidate))throw Error('Native source rejected');
}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),errors=[],delta=[];
for(const key of new Set([...before.keys(),...after.keys()])){const a=before.get(key),b=after.get(key);if(c(a?.b)===c(b?.b))continue;const r=b||a;if(r.h.type==='DOCHEAD')continue;let ok=false;
 if(stage==='sch'&&a&&b&&r.h.type==='ATTR'&&ids.has(r.b.parentId)){const t=targets.find(t=>t.componentId===r.b.parentId);if(Object.hasOwn(changes[t.ref],r.b.key)){const x={...a.b},y={...b.b};delete x.value;delete y.value;ok=c(x)===c(y)&&b.b.value===changes[t.ref][r.b.key];}}
 if(stage==='pcb'&&a&&b&&r.h.type==='COMPONENT'&&ids.has(r.h.id)){const t=targets.find(t=>t.componentId===r.h.id),x=structuredClone(a.b),y=structuredClone(b.b);for(const k of [...Object.keys(changes[t.ref]),'Name']){delete x.attrs[k];delete y.attrs[k];}ok=c(x)===c(y);}
 delta.push({key,allowed:ok});if(!ok)errors.push(key);
}
for(const t of targets){const values={...after.get('COMPONENT:'+t.componentId).b.attrs};for(const {h,b} of after.values())if(h.type==='ATTR'&&b.parentId===t.componentId)values[b.key]=b.value;
 for(const [k,v] of Object.entries(changes[t.ref])){if(stage==='pcb'&&k==='Tolerance'&&!Object.hasOwn(values,k))continue;if(values[k]!==v)errors.push({ref:t.ref,key:k,expected:v,actual:values[k]});}
 if(values['Supplier Part']!==t.spec.lcsc)errors.push({ref:t.ref,key:'Supplier Part'});
}
await eda.sys_FileSystem.saveFileToFileSystem(root+'/catalog-'+stage+'-after.epru',new Blob([afterSource]),undefined,false);
const receipt={stage,changes,delta,errors,saved:false};if(!errors.length)receipt.saved=await (stage==='pcb'?eda.pcb_Document:eda.sch_Document).save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/catalog-'+stage+'-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Catalog normalization audit failed');return {stage,saved:receipt.saved,errors};
