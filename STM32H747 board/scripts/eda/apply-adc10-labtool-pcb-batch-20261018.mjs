const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
const [stage,manifestRelative,manifestHash,priorRelative,priorHash]=__taskArgs;
const currentProject=await eda.dmt_Project.getCurrentProjectInfo();
if((currentProject?.name!=='STM32H747_MCU_BOARD_v19'&&currentProject?.friendlyName!=='STM32H747_MCU_BOARD_v19')||currentProject?.uuid!=='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c')throw new Error('Explicit STM32 project name/UUID guard rejected');
if(!/^[a-z0-9_]{3,55}$/.test(stage||'')||!manifestRelative?.startsWith('output/candidates/adc10-labtool-20261018/')||!manifestRelative.endsWith('.json')||manifestRelative.includes('..')||!priorRelative?.startsWith('output/validation/')||!priorRelative.endsWith('.epru')||priorRelative.includes('..')||![manifestHash,priorHash].every(v=>/^[a-f0-9]{64}$/.test(v||'')))throw new Error('Explicit reviewed scoped inputs required');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(root+'/'+p);if(!f)throw new Error('Missing '+p);return f.text();};
const hash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))).map(v=>v.toString(16).padStart(2,'0')).join('');
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const parse=s=>{const rows=s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||'),v=l.slice(i+2).replace(/\|$/,'');return{h:JSON.parse(l.slice(0,i)),b:v?JSON.parse(v):''};});const map=new Map(rows.map(r=>[r.h.type+':'+(r.h.id||''),r]));if(map.size!==rows.length)throw new Error('Duplicate native record keys');return{rows,map};};
const view=new Set(['DOCHEAD','CANVAS','ACTIVE_LAYER','ELE_PLACEHOLDER']);
const sameComponent=(a,b)=>{if(!a)return false;const c={...a};for(const k of ['x','y'])if(Math.abs(c[k]-b[k])<.0001001)c[k]=b[k];if(Math.abs(((c.angle-b.angle)%360+360)%360)<1e-8)c.angle=b.angle;return canonical(c)===canonical(b);};
const mt=await load(manifestRelative),pt=await load(priorRelative);
if(await hash(mt)!==manifestHash||await hash(pt)!==priorHash)throw new Error('Reviewed input hash changed');
const plan=JSON.parse(mt),batch=plan.batches?.find(b=>b.stage===stage);
if(plan.PCBRequired!==uuid||!batch||!Array.isArray(batch.operations)||batch.operations.length<1||batch.operations.length>60)throw new Error('Unexpected bounded operation batch');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong PCB');
const baseline=parse(pt),beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource);
for(const[k,r]of baseline.map)if(!view.has(r.h.type)&&canonical(before.map.get(k)?.b)!==canonical(r.b))throw new Error('Frozen predecessor changed '+k);
for(const[k,r]of before.map)if(!view.has(r.h.type)&&!baseline.map.has(k))throw new Error('Unexpected predecessor record '+k);
if(before.rows.find(r=>r.h.type==='DOCHEAD')?.b.uuid!==uuid||before.rows.filter(r=>r.h.type==='COMPONENT').length!==437)throw new Error('PCB identity/437-part count changed');
const ids=new Set(),targets=new Map(),routeNets=new Set();
const inner15Approved=[[[40.3,31.7],[13.8,35.5]],[[13.8,35.5],[12.2,36.9]],[[12.2,36.9],[8.9,37.5]]].map(pair=>pair.map(xy=>xy.map(v=>Math.round(v/.0254*10000)/10000)));
const reviewedGroundSeamPairs=[[[1818.88,4322.1576],[1818.88,4316.2516]],[[2078.8013,3116.24],[2078.8013,3110.334]]];
const finitePoint=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
const oldReferenceSupplyLeaves=new Set(['8f2d79e61b91a9c3','bdbacbd270c676c0','894fec9d56a4bbbf','0074ee2853c5f528','8bed767bd15efcb1','c38941e71664641b']);
for(const op of batch.operations){
 if(op.id){const k=op.type+':'+op.id;if(ids.has(k))throw new Error('Duplicate operation '+k);ids.add(k);targets.set(k,op);if(canonical(before.map.get(k)?.b)!==canonical(op.beforeBody))throw new Error('Operation original body changed '+k);}
 if(op.action==='delete'){if(op.type!=='LINE'||!(/^ADC(?:[123]_(?:PRE|DRV)[1-4]|_BIAS_2V5)$/i.test(op.beforeBody.netName||'')||op.beforeBody.netName==='+3V3'&&oldReferenceSupplyLeaves.has(op.id)))throw new Error('Deletion outside reviewed old AFE copper');}
 else if(op.action==='rename'){if(op.type!=='LINE'||canonical({...op.beforeBody,netName:op.afterBody?.netName})!==canonical(op.afterBody)||!/^ADC(?:_J(?:[2-9]|10|11)_(?:RAW|DRV)|_OFFSET_0V97)$/.test(op.afterBody.netName||''))throw new Error('Non-net LINE change');}
 else if(op.action==='place'){if(op.type!=='COMPONENT'||op.beforeBody.attrs?.['Unique ID']!==op.uniqueId||op.afterBody.attrs?.['Unique ID']!==op.uniqueId||op.afterBody.layerId!==1||canonical({...op.beforeBody,x:op.afterBody.x,y:op.afterBody.y,angle:op.afterBody.angle,layerId:1})!==canonical(op.afterBody))throw new Error('Placement changes physical identity');}
 else if(op.action==='fill'){if(op.type!=='FILL'||!Array.isArray(op.afterPath)||!op.localClearanceOnly)throw new Error('Unreviewed fill edit');for(const p of op.afterPath)if(typeof p[0]==='number'&&(p.at(-2)!==p[0]||p.at(-1)!==p[1]))throw new Error('Unclosed API contour');}
 else if(op.action==='fill_create'){if(op.type!=='FILL'||!op.localClearanceOnly||!op.net||![1,2,15,16,17,18].includes(op.layerId)||!Array.isArray(op.afterPath)||!(op.widthMil>=0&&op.widthMil<=1))throw new Error('Invalid preserved local copper lobe');for(const p of op.afterPath)if(typeof p[0]==='number'&&(p.at(-2)!==p[0]||p.at(-1)!==p[1]))throw new Error('Unclosed lobe API contour');}
 else if(op.action==='line'){const innerException=op.layerId===15&&op.net==='-3V_AFE'&&Math.abs(op.widthMil-.25/.0254)<1e-7&&inner15Approved.some(pair=>canonical(pair)===canonical([op.startXYMil,op.endXYMil]));const seamException=manifestHash==='7e68822c1fc7000b0366b30edabbcd6124b4da6b4951a49b77f29b81530ba513'&&stage==='ground_seam0'&&op.layerId===17&&op.net==='GND'&&op.widthMil===8&&reviewedGroundSeamPairs.some(pair=>canonical(pair)===canonical([op.startXYMil,op.endXYMil]));if(op.type!=='LINE'||!([1,2].includes(op.layerId)||innerException||seamException)||!Number.isFinite(op.widthMil)||!(op.widthMil>=6)||!op.net||!finitePoint(op.startXYMil)||!finitePoint(op.endXYMil))throw new Error('Invalid scoped route geometry');routeNets.add(op.net);}
 else if(op.action==='via'){if(op.type!=='VIA'||!op.net||![op.diameterMil,op.drillMil].every(Number.isFinite)||!(op.diameterMil>=op.drillMil+4)||!(op.drillMil>=7.87)||!finitePoint(op.xyMil))throw new Error('Invalid reviewed new via');}
 else throw new Error('Unsupported action');
}
const touched=[],created=[],issues=[],changes=[];let failure=null;
const journalPath=root+'/output/candidates/adc10-labtool-20261018/native-pcb-'+stage+'-journal.json';
const journal=async state=>{if(!await eda.sys_FileSystem.saveFileToFileSystem(journalPath,new Blob([JSON.stringify({stage,state,manifestRelative,manifestHash,priorRelative,priorHash,touched,created,failure,neverBlindlyRetry:true},null,2)]),undefined,false))throw new Error('Operation journal save failed');};
await journal('prepared-before-native-mutation');
try{
 const deletes=batch.operations.filter(o=>o.action==='delete');
 if(deletes.length){if(!await eda.pcb_PrimitiveLine.delete(deletes.map(o=>o.id)))throw new Error('Old AFE LINE removal failed');touched.push(...deletes.map(o=>({type:o.type,id:o.id,action:o.action})));}
 for(const op of batch.operations){
  if(op.action==='delete')continue;
  if(op.action==='rename'){const p=await eda.pcb_PrimitiveLine.get(op.id);if(!p)throw new Error('LINE identity missing');const a=p.toAsync();a.setState_Net(op.afterBody.netName);await a.done();}
  else if(op.action==='place'){const p=await eda.pcb_PrimitiveComponent.get(op.id);if(!p||p.getState_Designator()!==op.ref)throw new Error('Component identity mismatch '+op.ref);const a=p.toAsync();a.setState_X(op.afterBody.x);a.setState_Y(op.afterBody.y);a.setState_Rotation(op.afterBody.angle);a.setState_Layer(1);await a.done();}
  else if(op.action==='fill'){const p=eda.pcb_MathPolygon.createComplexPolygon(op.afterPath);if(!p||!await eda.pcb_PrimitiveFill.modify(op.id,{complexPolygon:p}))throw new Error('Local clearance polygon rejected');}
  else if(op.action==='fill_create'){const polygon=eda.pcb_MathPolygon.createComplexPolygon(op.afterPath);if(!polygon)throw new Error('Preserved local lobe polygon rejected');const p=await eda.pcb_PrimitiveFill.create(op.layerId,polygon,op.net,0,op.widthMil,false);if(!p)throw new Error('Preserved local copper lobe creation failed');created.push({key:op.key,type:'FILL',id:p.getState_PrimitiveId()});}
  else if(op.action==='line'){const p=await eda.pcb_PrimitiveLine.create(op.net,op.layerId,...op.startXYMil,...op.endXYMil,op.widthMil,false);if(!p)throw new Error('New LINE rejected');created.push({key:op.key,type:'LINE',id:p.getState_PrimitiveId()});}
  else if(op.action==='via'){const p=await eda.pcb_PrimitiveVia.create(op.net,...op.xyMil,op.drillMil,op.diameterMil);if(!p)throw new Error('New VIA rejected');created.push({key:op.key,type:'VIA',id:p.getState_PrimitiveId()});}
  touched.push({type:op.type,id:op.id||null,ref:op.ref||null,key:op.key||null,action:op.action});
  if(['fill','fill_create'].includes(op.action)||touched.length%10===0)await journal('partial-awaiting-readback');
 }
}catch(e){failure=String(e?.message||e);}
await journal(failure?'native-operation-failed-recapture-required':'operations-completed-awaiting-readback');
let source,after;
try{source=await eda.sys_FileManager.getDocumentSource();after=parse(source);}
catch(e){failure='Post-operation readback failed: '+String(e?.message||e);await journal('readback-failed-recapture-required');throw new Error(failure+'; DO NOT RETRY; journal='+journalPath);}
for(const c of created){
 const op=batch.operations.find(o=>o.key===c.key&&o.type===c.type),r=after.map.get(c.type+':'+c.id)?.b;
 if(c.type==='VIA'){
  const close=(a,b)=>Number.isFinite(a)&&Math.abs(a-b)<=.0001001;
  if(!r||r.netName!==op.net||!close(r.centerX,op.xyMil[0])||!close(r.centerY,op.xyMil[1])||!close(r.holeDiameter,op.drillMil)||!close(r.viaDiameter,op.diameterMil)||r.viaType!=='NORMAL'||r.locked!==false)issues.push({key:c.key,issue:'created-via-readback-mismatch'});
 }else if(c.type==='FILL'){
  if(!r||r.netName!==op.net||r.layerId!==op.layerId||Math.abs(r.width-op.widthMil)>.0001001||r.fillStyle!=='SOLID'||r.locked!==false)issues.push({key:c.key,issue:'created-fill-identity-readback-mismatch'});
 }
}
const movedIds=new Set(batch.operations.filter(o=>o.action==='place').map(o=>o.id));
const selectedOldNets=new Set(batch.operations.filter(o=>['delete','rename'].includes(o.action)).map(o=>o.beforeBody.netName.toUpperCase()));
const usedAfterNets=new Set(after.rows.filter(r=>!['NET','RULE_SELECTOR'].includes(r.h.type)).flatMap(r=>[r.b?.netName,r.b?.padNet]).filter(v=>typeof v==='string').map(v=>v.toUpperCase()));
const emptyNetBody={netType:null,specialColor:null,retLine:true,differentialName:null,isPositiveNet:false,equalLengthGroupName:null};
const emptySelectorBody={ruleOrder:4,ruleKeyValue:{},copperValue:{},innerPlaneValue:{}};
const isAutomaticEmptyNetCleanup=r=>{
 if(!['NET','RULE_SELECTOR'].includes(r.h.type))return false;
 let id;try{id=JSON.parse(r.h.id);}catch{return false;}
 const n=r.h.type==='NET'&&id[0]==='NET'?id[1]:r.h.type==='RULE_SELECTOR'&&id[0]==='RULE_SELECTOR'&&id[1]?.[0]==='NET'?id[1][1]:null;
 if(typeof n!=='string'||!/^(?:ADC(?:[123]_(?:PRE|DRV)[1-4]|_BIAS_2V5)|NET-\(J(?:[2-9]|10|11)-IN\))$/i.test(n)||!selectedOldNets.has(n.toUpperCase())||usedAfterNets.has(n.toUpperCase()))return false;
 return canonical(r.b)===canonical(r.h.type==='NET'?emptyNetBody:emptySelectorBody);
};
for(const[k,r]of before.map){
 if(view.has(r.h.type))continue;
 const actual=after.map.get(k)?.b;if(canonical(actual)===canonical(r.b))continue;
 const op=targets.get(k),fields=actual?Object.keys({...r.b,...actual}).filter(f=>canonical(r.b[f])!==canonical(actual[f])):['missing'];
 let allowed=false,requiresGeometryAudit=false;
 if(op?.action==='delete')allowed=actual===undefined;
 else if(actual===undefined&&isAutomaticEmptyNetCleanup(r))allowed=true;
 else if(op?.action==='rename')allowed=canonical(actual)===canonical(op.afterBody);
 else if(op?.action==='place')allowed=sameComponent(actual,op.afterBody);
 else if(op?.action==='fill'){allowed=!!actual&&fields.every(f=>['path','refs','zIndex'].includes(f));requiresGeometryAudit=true;}
 else if(r.h.type==='ATTR'&&movedIds.has(r.b.parentId))allowed=!!actual&&fields.every(f=>['x','y','angle','layerId'].includes(f));
 else if(r.h.type==='LINE'&&(routeNets.has(r.b.netName)||selectedOldNets.has(r.b.netName?.toUpperCase()))){allowed=!actual||fields.every(f=>['startX','startY','endX','endY','width','zIndex','refs'].includes(f));requiresGeometryAudit=true;}
 changes.push({key:k,fields,allowed,requiresGeometryAudit});if(!allowed)issues.push({key:k,fields});
}
for(const[k,r]of after.map)if(!before.map.has(k)&&!view.has(r.h.type)){
 const known=created.some(p=>p.type===r.h.type&&p.id===r.h.id);
 const allowed=known||r.h.type==='LINE'&&(routeNets.has(r.b.netName)||selectedOldNets.has(r.b.netName?.toUpperCase()));
 if(!allowed)issues.push({key:k,issue:'unexpected-new-record'});
}
const path=root+'/output/validation/native-adc10-pcb-labtool_'+stage+'-20261018.epru';
const receiptPath=root+'/output/candidates/adc10-labtool-20261018/native-pcb-'+stage+'-receipt.json';
const receipt={stage,manifestRelative,manifestHash,priorRelative,priorHash,path,sourceSha256:await hash(source),touched,created,changes,issues,failure,containmentPassed:!failure&&!issues.length,requiresIndependentGeometryAudit:changes.some(c=>c.requiresGeometryAudit)||created.length>0,saved:false,manufacturingReady:false};
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false)||!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Evidence save failed; inspect actual PCB before any retry');
await journal(failure||issues.length?'readback-issues-stop':'captured-requires-independent-geometry-audit');
if(failure||issues.length)throw new Error('STOP: '+(failure||JSON.stringify(issues.slice(0,10)))+'; actual='+path+'; receipt='+receiptPath);
return{stage,path,sourceSha256:receipt.sourceSha256,receiptPath,containmentPassed:true,requiresIndependentGeometryAudit:receipt.requiresIndependentGeometryAudit,touched:touched.length,created:created.length,saved:false};
