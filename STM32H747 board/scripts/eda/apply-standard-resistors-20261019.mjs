const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
const plan=JSON.parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/standard-resistors-plan.json')).text());
if(plan.schema!=='standard-resistors-20261019-v1'||plan.projectUuid!==__p.uuid||plan.netGeometryChangesAllowed!==false||plan.specs.length!==25)throw Error('Plan guard failed');
const stage=__taskArgs[0];
const cfg={pilot:{page:'a07bf8e4331877a8',refs:['R137']},adc_rest:{page:'a07bf8e4331877a8',exclude:['R137']},power:{page:'360993a3108b5759'},pcb_pilot:{page:plan.pcbUuid,refs:['R137']},pcb_rest:{page:plan.pcbUuid,exclude:['R137']}}[stage];
if(!cfg)throw Error('Explicit reviewed stage required');
const isPcb=stage.startsWith('pcb_');let targets=isPcb?plan.pcbTargets:plan.pages[cfg.page].targets;
if(cfg.refs)targets=targets.filter(x=>cfg.refs.includes(x.ref));if(cfg.exclude)targets=targets.filter(x=>!cfg.exclude.includes(x.ref));
await eda.dmt_EditorControl.openDocument(cfg.page);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==cfg.page)throw Error('Wrong document');
const canonical=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
function parse(src){const m=new Map();for(const line of src.split(/\r?\n/)){const pos=line.indexOf('||');if(pos<0)continue;const h=JSON.parse(line.slice(0,pos)),raw=line.slice(pos+2).replace(/\|$/,'');if(!raw)continue;const b=JSON.parse(raw);if(typeof b==='object')m.set(h.type+':'+(h.id||''),{h,b});}return m;}
function attrs(m){const a=new Map();for(const {h,b} of m.values())if(h.type==='ATTR'){if(!a.has(b.parentId))a.set(b.parentId,{});a.get(b.parentId)[b.key]=b.value;}return a;}
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),ba=attrs(before);
for(const t of targets){const r=before.get('COMPONENT:'+t.componentId);if(!r)throw Error('Missing target '+t.ref);const a={...(r.b.attrs||{}),...(ba.get(t.componentId)||{})};
 if(a.Designator!==t.ref||a['Unique ID']!==t.beforeAttrs['Unique ID']||a.Footprint!==t.beforeAttrs.Footprint)throw Error('Identity changed '+t.ref);
 const value=a.Value??a.Name;if(value!==t.spec.oldValue)throw Error('Value changed '+t.ref+':'+value);
 if(a['Manufacturer Part'])throw Error('MPN already set; do not repeat '+t.ref);
 for(const [k,v] of Object.entries(t.geometry))if(r.b[k]!==v)throw Error('Geometry changed '+t.ref+' '+k);
}
const startedPath=root+'/stage-'+stage+'-before.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(startedPath,new Blob([beforeSource]),undefined,false))throw Error('Stage already attempted; inspect receipts before recovery');
const allowedKeys=new Set(['Value','Name','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Part Number','Datasheet','Tolerance','Temperature Coefficient','Power Rating','Description','Package']);
const ids=new Set(targets.map(t=>t.componentId));
// Native component.modify reflows SCH attributes. Restore pre-existing display
// state explicitly; SCH attribute fontSize is 1/100 of source fontSize in 3.2.206.
const aligns={LEFT_TOP:1,LEFT_MIDDLE:2,LEFT_BOTTOM:3,CENTER_TOP:4,CENTER_MIDDLE:5,CENTER_BOTTOM:6,RIGHT_TOP:7,RIGHT_MIDDLE:8,RIGHT_BOTTOM:9};
for(const t of targets){const s=t.spec;
 const property={manufacturer:s.manufacturer,manufacturerId:s.mpn,supplier:'LCSC',supplierId:s.lcsc,otherProperty:{Value:s.value,'Part Number':s.mpn,Datasheet:s.Datasheet,Tolerance:s.Tolerance,'Temperature Coefficient':s['Temperature Coefficient'],'Power Rating':s['Power Rating'],Description:s.Description,Package:s.Package}};
 if(isPcb)property.name=s.value;
 const updated=await (isPcb?eda.pcb_PrimitiveComponent:eda.sch_PrimitiveComponent).modify(t.componentId,property);if(!updated)throw Error('Metadata update rejected '+t.ref);
 if(!isPcb)for(const {h,b} of before.values())if(h.type==='ATTR'&&b.parentId===t.componentId){
  if(b.align!==null&&!Object.hasOwn(aligns,b.align))throw Error('Unsupported alignment '+b.align);
  const display={x:b.x,y:b.y,rotation:b.rotation,color:b.color,fontName:b.fontFamily,fontSize:b.fontSize===null?null:b.fontSize/100,bold:b.fontWeight,italic:b.italic,underLine:b.underline,alignMode:b.align===null?null:aligns[b.align],fillColor:b.fillColor,keyVisible:b.keyVisible,valueVisible:b.valueVisible};
  if(!await eda.sch_PrimitiveAttribute.modify(h.id,display))throw Error('Display preservation failed '+t.ref+' '+b.key);
 }
}
const textEdits=stage==='adc_rest'?(plan.pages[cfg.page].textEdits||[]):[];
for(const t of textEdits){if(before.get('TEXT:'+t.id)?.b.value!==t.before)throw Error('Text baseline changed');if(!await eda.sch_PrimitiveText.modify(t.id,{content:t.after}))throw Error('Text update failed');}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),aa=attrs(after),changes=[];
await eda.sys_FileSystem.saveFileToFileSystem(root+'/stage-'+stage+'-after.epru',new Blob([afterSource]),undefined,false);
const errors=[];
for(const key of new Set([...before.keys(),...after.keys()])){
 const a=before.get(key),b=after.get(key);if(canonical(a?.b)===canonical(b?.b))continue;
 const r=b||a;if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;
 let allowed=false;
 if(r.h.type==='ATTR'&&ids.has(r.b.parentId)&&allowedKeys.has(r.b.key)){
  const x={...(a?.b||r.b)},y={...(b?.b||r.b)};delete x.value;delete y.value;allowed=canonical(x)===canonical(y);
 }
 if(isPcb&&r.h.type==='COMPONENT'&&ids.has(r.h.id)&&a&&b){
  const x=structuredClone(a.b),y=structuredClone(b.b);for(const k of allowedKeys){if(x.attrs)delete x.attrs[k];if(y.attrs)delete y.attrs[k];}allowed=canonical(x)===canonical(y);
 }
 const te=textEdits.find(t=>t.id===r.h.id);
 if(r.h.type==='TEXT'&&te&&a&&b){const x={...a.b},y={...b.b};delete x.value;delete y.value;allowed=canonical(x)===canonical(y)&&b.b.value===te.after;}
 changes.push({type:r.h.type,id:r.h.id,key:r.b.key,parentId:r.b.parentId,allowed});if(!allowed)errors.push(changes.at(-1));
}
for(const t of targets){const r=after.get('COMPONENT:'+t.componentId),a={...(r?.b.attrs||{}),...(aa.get(t.componentId)||{})};
 const expected={Value:t.spec.value,'Manufacturer Part':t.spec.mpn,'Supplier Part':t.spec.lcsc,Tolerance:t.spec.Tolerance,'Temperature Coefficient':t.spec['Temperature Coefficient'],'Power Rating':t.spec['Power Rating']};
 for(const [k,v] of Object.entries(expected))if(a[k]!==v)errors.push({ref:t.ref,key:k,expected:v,actual:a[k]});
 for(const [k,v] of Object.entries(t.geometry))if(r.b[k]!==v)errors.push({ref:t.ref,geometry:k});
}
const receipt={stage,page:cfg.page,targets:targets.map(t=>t.ref),changes,errors,saved:false};
if(!errors.length)receipt.saved=await (isPcb?eda.pcb_Document:eda.sch_Document).save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/stage-'+stage+'-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Stage audit failed; inspect saved receipt; DO NOT retry stage');
return {stage,page:cfg.page,targets:targets.length,changedRecords:changes.length,saved:receipt.saved,errors:0};
