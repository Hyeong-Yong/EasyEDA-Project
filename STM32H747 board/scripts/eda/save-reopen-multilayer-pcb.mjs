const stage=__taskArgs[0],recoverySourceName=__taskArgs[1];
if(!stage||!/^[a-z0-9_-]{3,60}$/.test(stage))throw new Error('Scoped reopen stage required');
if(recoverySourceName&&!/^native-multilayer-fill-[a-z0-9_-]+-after\.epru$/.test(recoverySourceName))throw new Error('Invalid scoped reopen recovery source');
const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',projectUuid='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c';
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return {h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
let beforeSource=await eda.sys_FileManager.getDocumentSource();
if(recoverySourceName){const recovery=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/'+recoverySourceName);if(!recovery)throw new Error('Reopen recovery source missing');beforeSource=await recovery.text();}
const before=parse(beforeSource);
if(!await eda.pcb_Document.save())throw new Error('PCB save failed');
await eda.dmt_EditorControl.closeDocument(uuid+'@'+projectUuid);
if(!await eda.dmt_EditorControl.openDocument(uuid))throw new Error('PCB reopen failed');
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong reopened PCB');
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),counts={};
for(const row of after)counts[row.h.type]=(counts[row.h.type]||0)+1;
for(const [type,n]of Object.entries({COMPONENT:330,PAD_NET:1234,NET:280,VIA:634,PAD:4,LAYER:64,LAYER_PHYS:17,RULE:18,RULE_SELECTOR:280}))if(counts[type]!==n)throw new Error('Protected reopened inventory changed '+type);
const byId=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b]));
const differences=[];
const nativeNormalizations=[];
const deduplicateExactL=path=>{
 if(!Array.isArray(path)||path[2]!=='L'||path.slice(3).some(v=>typeof v!=='number')||(path.length-3)%2)return null;
 const result=path.slice(0,3);let x=path[0],y=path[1];
 for(let i=3;i<path.length;i+=2){if(path[i]===x&&path[i+1]===y)continue;result.push(path[i],path[i+1]);x=path[i];y=path[i+1];}
 return result;
};
for(const row of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(row.h.type))continue;
 const actual={...byId.get(row.h.type+':'+row.h.id)};
 if(row.h.type==='FILL'&&row.b.zIndex===-1&&actual.zIndex===-1&&canonical(row.b.path)!==canonical(actual.path)){
  const normalized=row.b.path.map(deduplicateExactL);
  if(normalized.every(Boolean)&&canonical(normalized)===canonical(actual.path)){nativeNormalizations.push({id:row.h.id,field:'path',kind:'exact-consecutive-duplicate-coordinate-removal',contoursBefore:row.b.path.length,contoursAfter:actual.path.length,removedCoordinatePairs:row.b.path.reduce((n,p,i)=>n+(p.length-normalized[i].length)/2,0),geometryTolerance:0});actual.path=row.b.path;}
 }
 if(row.h.type==='FILL'&&row.b.zIndex===-1&&actual.zIndex===-1&&Array.isArray(row.b.refs)&&row.b.refs.length===1&&row.b.refs[0]===null&&actual.refs===null){nativeNormalizations.push({id:row.h.id,field:'refs',before:row.b.refs,after:null});actual.refs=row.b.refs;}
 if(canonical(row.b)!==canonical(actual))differences.push(row.h.type+':'+row.h.id);
}
if(before.length!==after.length)differences.push('record-count');
const path=root+'/output/validation/native-multilayer-'+stage+'-reopened.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([afterSource]),undefined,false))throw new Error('Reopened source not saved');
const receiptPath=root+'/output/validation/native-multilayer-'+stage+'-reopen-receipt.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,stage,path,recoverySourceName:recoverySourceName||null,counts,differences,nativeNormalizations},null,2)]),undefined,false))throw new Error('Reopen receipt not saved');
if(differences.length)throw new Error('Reopen changed protected PCB data; inspect '+receiptPath);
return {uuid,stage,path,counts,preserved:true};
