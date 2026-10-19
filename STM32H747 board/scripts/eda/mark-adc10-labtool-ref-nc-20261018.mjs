const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='360993a3108b5759';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong power page');
const rows=(await eda.sys_FileManager.getDocumentSource()).split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const ref=rows.find(r=>r.h.type==='ATTR'&&r.b.key==='Designator'&&r.b.value==='U9');
if(!ref)throw new Error('Reference U9 absent');
const part=rows.find(r=>r.h.type==='ATTR'&&r.b.parentId===ref.b.parentId&&r.b.key==='Value');
if(!part||!String(part.b.value).startsWith('REF5025'))throw new Error('U9 is not reviewed REF5025');
const expected=new Set(['1','3','7','8']),pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(ref.b.parentId);
const marked=[];
for(const pin of pins){if(expected.has(String(pin.pinNumber))){const ap=pin.toAsync();ap.setState_NoConnected(true);await ap.done();marked.push(String(pin.pinNumber));}}
if(marked.length!==4)throw new Error('NC marker count mismatch');
if(!await eda.sch_Document.save())throw new Error('Power page NC state not saved');
const source=await eda.sys_FileManager.getDocumentSource(),path=root+'/output/validation/native-adc10-labtool-page03-nc-20261018.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false))throw new Error('NC source capture failed');
return{marked,path,saved:true};
