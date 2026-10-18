const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='a07bf8e4331877a8';
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('ADC page must remain active');
const load=async path=>{const file=await eda.sys_FileSystem.readFileFromFileSystem(root+path);if(!file)throw new Error('Missing reviewed file '+path);return await file.text();};
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const target=parse(await load('/output/candidates/adc-inline-wiring/06_ADC_TIMER_DAC_inline_candidate.epru')),accepted=parse(await load('/output/validation/native-adc-inline-accepted-20261016.epru')),plan=JSON.parse(await load('/output/candidates/adc-inline-wiring/adc-inline-schematic-plan.json'));
if(plan.candidateSha256!=='b09110fc407485b51ff163c14a40e47d18dff5f66ee3b86cc3bd44a7bc5c4adf'||target.length!==2764||accepted.length!==2764)throw new Error('Reviewed inline inventory changed');
const addedLines=new Set(plan.added.filter(r=>r.h.type==='LINE').map(r=>r.h.id)),expectedById=new Map(target.map(r=>[r.h.type+':'+r.h.id,r])),acceptedById=new Map(accepted.map(r=>[r.h.type+':'+r.h.id,r])),normalizations=[],errors=[];
const withoutHash=points=>points.map(p=>{const q={...p};delete q.hashed;return q;});
for(const r of target){
 if(['DOCHEAD','CANVAS'].includes(r.h.type))continue;
 const key=r.h.type+':'+r.h.id,a=acceptedById.get(key),b={...a?.b};
 if(r.h.type==='POLY'&&canonical(b.points)!==canonical(r.b.points)&&canonical(withoutHash(b.points))===canonical(withoutHash(r.b.points))){b.points=r.b.points;normalizations.push({id:r.h.id,type:'POLY',field:'points.hashed'});}
 if(r.h.type==='LINE'&&addedLines.has(r.h.id)&&r.b.strokeWidth===.6&&b.strokeWidth===null){b.strokeWidth=.6;normalizations.push({id:r.h.id,type:'LINE',field:'strokeWidth'});}
 if(r.h.type==='ATTR'&&['NET','Relevance'].includes(r.b.key)&&b.zIndex!==r.b.zIndex){const allowed=([7,6,2,3].indexOf(r.b.zIndex)>=0)&&(([7,6].includes(r.b.zIndex)&&b.zIndex===r.b.zIndex-1)||(r.b.zIndex===2&&b.zIndex===7)||(r.b.zIndex===3&&b.zIndex===8));if(allowed){b.zIndex=r.b.zIndex;normalizations.push({id:r.h.id,type:'ATTR',field:'zIndex'});}}
 if(!a||canonical(b)!==canonical(r.b))errors.push({key,error:'unclassified normalization'});
}
for(const r of accepted)if(!expectedById.has(r.h.type+':'+r.h.id))errors.push({error:'unexpected accepted record'});
for(const [type,count]of Object.entries({POLY:65,LINE:69,ATTR:12}))if(normalizations.filter(n=>n.type===type).length!==count)errors.push({error:'normalization count',type,count});
const current=parse(await eda.sys_FileManager.getDocumentSource()),currentMap=new Map(current.map(r=>[r.h.type+':'+r.h.id,r]));
for(const r of accepted)if(!['DOCHEAD','CANVAS'].includes(r.h.type)&&canonical(currentMap.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))errors.push({key:r.h.type+':'+r.h.id,error:'current differs from audited accepted'});
if(current.length!==accepted.length)errors.push({error:'current record count'});
if(errors.length)throw new Error('Inline finalization refused '+JSON.stringify(errors));
if(!await eda.sch_Document.save())throw new Error('Inline schematic save failed');
await eda.dmt_EditorControl.closeDocument((await eda.dmt_SelectControl.getCurrentDocumentInfo()).tabId||uuid);
await eda.dmt_EditorControl.openDocument(uuid);
const reopenedSource=await eda.sys_FileManager.getDocumentSource(),reopened=parse(reopenedSource),map=new Map(reopened.map(r=>[r.h.type+':'+r.h.id,r]));
for(const r of accepted)if(!['DOCHEAD','CANVAS'].includes(r.h.type)&&canonical(map.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))errors.push({key:r.h.type+':'+r.h.id,error:'reopen changed accepted body'});
if(reopened.length!==accepted.length)errors.push({error:'reopened record count',expected:accepted.length,actual:reopened.length});
const path=root+'/output/validation/native-adc-inline-reopened-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([reopenedSource]),undefined,false);
const receipt={saved:true,path,recordCount:reopened.length,normalizations,errors};
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-adc-inline-finalization-receipt-20261016.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length)throw new Error('Inline save/reopen preservation failed');return{saved:true,path,records:reopened.length,errors:0};
