await eda.dmt_EditorControl.openDocument('6cbee023e77e073a');
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
const records=source.split('\n').filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');return {head:JSON.parse(h),body:JSON.parse(b.replace(/\|$/,''))};});
const c1=records.find(r=>r.head.type==='ATTR'&&r.body.key==='Designator'&&r.body.value==='C1')?.body.parentId;
if(!c1)throw new Error('C1 missing');
const attrs=Object.fromEntries(records.filter(r=>r.head.type==='ATTR'&&r.body.parentId===c1).map(r=>[r.body.key,r.body.value]));
const footprint=await eda.lib_Footprint.getDocumentSource(attrs.Footprint,'project');
const symbol=await eda.lib_Symbol.getDocumentSource(attrs.Symbol,'project');
const directory='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/validation/';
const saved={};
if(footprint)saved.footprint=await eda.sys_FileSystem.saveFileToFileSystem(directory+'native-C1-footprint-runtime.efoo',new Blob([footprint]),undefined,false);
if(symbol)saved.symbol=await eda.sys_FileSystem.saveFileToFileSystem(directory+'native-C1-symbol-runtime.esym',new Blob([symbol]),undefined,false);
const components=await eda.sch_PrimitiveComponent.getAll(undefined,true);
const types={};
for(const c of components){const t=c.getState_ComponentType();types[t]=(types[t]||0)+1;}
const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c1);
const passed=await eda.sch_Drc.check(true,true,false);
return {c1,attrs,saved,footprintBytes:footprint?.length,symbolBytes:symbol?.length,pins,types,ercPassed:passed};
