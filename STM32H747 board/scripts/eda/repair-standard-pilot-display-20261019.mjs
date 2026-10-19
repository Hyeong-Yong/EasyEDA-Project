// One-time recovery of the component API's attribute-layout side effect.
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/standard-values-20261019';
await eda.dmt_EditorControl.openDocument('a07bf8e4331877a8');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!=='a07bf8e4331877a8')throw Error('Wrong page');
function parse(src){const m=new Map();for(const l of src.split(/\r?\n/)){const p=l.indexOf('||');if(p<0)continue;const h=JSON.parse(l.slice(0,p)),raw=l.slice(p+2).replace(/\|$/,'');if(raw)m.set(h.type+':'+(h.id||''),{h,b:JSON.parse(raw)});}return m;}
const canonical=v=>JSON.stringify(v,(_,x)=>x&&typeof x==='object'&&!Array.isArray(x)?Object.fromEntries(Object.entries(x).sort(([a],[b])=>a.localeCompare(b))):x);
const baseline=parse(await (await eda.sys_FileSystem.readFileFromFileSystem(root+'/stage-pilot-before.epru')).text());
const current=await eda.sys_FileManager.getDocumentSource();
if(!await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-display-repair-before.epru',new Blob([current]),undefined,false))throw Error('Repair already attempted');
const aligns={LEFT_TOP:1,LEFT_MIDDLE:2,LEFT_BOTTOM:3,CENTER_TOP:4,CENTER_MIDDLE:5,CENTER_BOTTOM:6,RIGHT_TOP:7,RIGHT_MIDDLE:8,RIGHT_BOTTOM:9};
for(const {h,b} of baseline.values())if(h.type==='ATTR'&&b.parentId==='8aca3284ddf555cd'){
 const p={x:b.x,y:b.y,rotation:b.rotation,color:b.color,fontName:b.fontFamily,fontSize:b.fontSize,bold:b.fontWeight,italic:b.italic,underLine:b.underline,alignMode:b.align===null?null:aligns[b.align],fillColor:b.fillColor,keyVisible:b.keyVisible,valueVisible:b.valueVisible};
 if(!await eda.sch_PrimitiveAttribute.modify(h.id,p))throw Error('Attribute repair failed '+h.id);
}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),errors=[],changes=[];
const allowed=new Set(['Value','Name','Manufacturer','Manufacturer Part','Supplier','Supplier Part','Part Number','Datasheet','Tolerance','Temperature Coefficient','Power Rating','Description','Package']);
for(const key of new Set([...baseline.keys(),...after.keys()])){const a=baseline.get(key),b=after.get(key);if(canonical(a?.b)===canonical(b?.b))continue;const r=b||a;if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;let ok=false;if(r.h.type==='ATTR'&&r.b.parentId==='8aca3284ddf555cd'&&allowed.has(r.b.key)){const x={...(a?.b||r.b)},y={...(b?.b||r.b)};delete x.value;delete y.value;ok=canonical(x)===canonical(y);}changes.push({id:r.h.id,type:r.h.type,key:r.b.key,allowed:ok});if(!ok)errors.push(changes.at(-1));}
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-display-repair-after.epru',new Blob([afterSource]),undefined,false);
const receipt={changes,errors,saved:false};if(!errors.length)receipt.saved=await eda.sch_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/pilot-display-repair-receipt.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw Error('Repair audit failed; inspect receipt, do not retry');return receipt;
