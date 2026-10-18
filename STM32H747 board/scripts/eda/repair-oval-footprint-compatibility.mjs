const ROOT='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board';
const reference=__taskArgs[0];
if(!['CN1','CN3','CN4'].includes(reference))throw new Error('Only verified capsule-pad footprints may be normalized');
const library=(await eda.dmt_Project.getCurrentProjectInfo()).uuid;
const mapFile=await eda.sys_FileSystem.readFileFromFileSystem(ROOT+'/output/validation/native-component-link-rebind-plan.json');
const item=JSON.parse(await mapFile.text()).library_map.footprint.find(x=>x.title.startsWith(reference+'_'));
if(!item)throw new Error('Verified imported footprint missing');
const tab=await eda.lib_Footprint.openInEditor(item.imported_uuid,library);
if(!tab)throw new Error('Footprint did not open');
await new Promise(r=>setTimeout(r,200));
const source=await eda.sys_FileManager.getDocumentSource();
function parse(s){return s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return {head:JSON.parse(h),body:raw?JSON.parse(raw):null};});}
const rows=parse(source);
if(rows.find(r=>r.head.type==='DOCHEAD')?.body.uuid!==item.imported_uuid)throw new Error('Refusing to change another active document');
const beforeSaved=await eda.sys_FileSystem.saveFileToFileSystem(ROOT+'/output/validation/native-'+reference+'-before-capsule-compatibility.epru',new Blob([source]),undefined,false);
if(!beforeSaved)throw new Error('Footprint recovery capture missing');
const pads=rows.filter(r=>r.head.type==='PAD');
const geometryBefore=JSON.stringify(pads.map(r=>({id:r.head.id,num:r.body.num,x:r.body.centerX,y:r.body.centerY,angle:r.body.padAngle,hole:r.body.hole,width:r.body.defaultPad.width,height:r.body.defaultPad.height,layer:r.body.layerId,plated:r.body.plated})));
let normalized=0;
for(const pad of pads){
if(pad.body.layerId===1&&pad.body.defaultPad.padType==='OVAL'){
pad.body.defaultPad={...pad.body.defaultPad,padType:'RECT',radius:100};normalized++;
}
}
const replacement=rows.map(r=>JSON.stringify(r.head)+'||'+(r.body===null?'':JSON.stringify(r.body))).join('|\n');
const accepted=await eda.sys_FileManager.setDocumentSource(replacement);
if(!accepted)return {reference,accepted,normalized,saved:false};
const actual=await eda.sys_FileManager.getDocumentSource();
const libraryUpdated=await eda.lib_Footprint.updateDocumentSource(item.imported_uuid,library,actual);
const saved=await eda.pcb_Document.save();
if(!saved)return {reference,accepted,normalized,libraryUpdated,saved:false};
const closed=await eda.dmt_EditorControl.closeDocument(tab);
const reopened=await eda.lib_Footprint.openInEditor(item.imported_uuid,library);
await new Promise(r=>setTimeout(r,200));
const afterSource=await eda.sys_FileManager.getDocumentSource();
const after=parse(afterSource);
if(after.find(r=>r.head.type==='DOCHEAD')?.body.uuid!==item.imported_uuid)throw new Error('Wrong verification document');
const afterPads=after.filter(r=>r.head.type==='PAD');
const geometryAfter=JSON.stringify(afterPads.map(r=>({id:r.head.id,num:r.body.num,x:r.body.centerX,y:r.body.centerY,angle:r.body.padAngle,hole:r.body.hole,width:r.body.defaultPad.width,height:r.body.defaultPad.height,layer:r.body.layerId,plated:r.body.plated})));
if(geometryBefore!==geometryAfter||afterPads.some(r=>r.body.layerId===1&&r.body.defaultPad.padType==='OVAL'))throw new Error('Footprint normalization did not persist or changed geometric/pad identities');
const captured=await eda.sys_FileSystem.saveFileToFileSystem(ROOT+'/output/validation/native-'+reference+'-capsule-compatible-reopened.epru',new Blob([afterSource]),undefined,false);
return {reference,uuid:item.imported_uuid,accepted,normalized,pads:afterPads.length,libraryUpdated,saved,closed,reopened,captured};
