const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
const [stage,fileName,manifestHash,priorPath,priorHash]=__taskArgs;
if(!/^(fill|lines_[0-9]{1,2})$/.test(stage||'')||!/^[a-zA-Z0-9_-]+\.json$/.test(fileName||'')||![manifestHash,priorHash].every(x=>/^[a-f0-9]{64}$/.test(x||''))||!priorPath?.startsWith(root+'/output/validation/')||!priorPath.endsWith('.epru'))throw new Error('Reviewed scoped route stage/manifest/frozen predecessor required');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Approved PCB must remain active');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(p);if(!f)throw new Error('Missing '+p);return await f.text();};
const hash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))).map(v=>v.toString(16).padStart(2,'0')).join('');
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const parse=s=>new Map(s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||'),h=JSON.parse(l.slice(0,i)),v=l.slice(i+2).replace(/\|$/,'');return[h.type+':'+h.id,{h,b:v?JSON.parse(v):''}];}));
const manifestPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/'+fileName,mt=await load(manifestPath),pt=await load(priorPath);
if(await hash(mt)!==manifestHash||await hash(pt)!==priorHash)throw new Error('Reviewed route/predecessor file changed');
const plan=JSON.parse(mt),baseline=parse(pt),beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource);
if(!Array.isArray(plan.newLineCreates)||plan.newLineCreates.length!==204||plan.fillPathUpdates?.length!==1||plan.geometryConflicts?.length)throw new Error('Unexpected reviewed strip routing scope');
for(const[k,r]of baseline)if(!k.startsWith('DOCHEAD:')&&canonical(before.get(k)?.b)!==canonical(r.b))throw new Error('Frozen predecessor changed '+k);
if(before.size!==baseline.size)throw new Error('Frozen predecessor membership changed');
const fill=plan.fillPathUpdates[0],EPCB_LayerId={TOP:1},created=[];
if(stage==='fill'){
if(canonical(before.get('FILL:'+fill.id)?.b)!==canonical(fill.sourceBodyBefore))throw new Error('Rebased GND FILL body changed');
for(const p of fill.afterPath)if(typeof p[0]==='number'&&(p.at(-2)!==p[0]||p.at(-1)!==p[1]))throw new Error('API requires explicitly closed polygon');
const polygon=eda.pcb_MathPolygon.createComplexPolygon(fill.afterPath);if(!polygon)throw new Error('Invalid reviewed routing clearances');
if(!await eda.pcb_PrimitiveFill.modify(fill.id,{complexPolygon:polygon}))throw new Error('Reviewed routing clearance edit failed');
}else{
const index=Number(stage.slice(6)),ops=plan.newLineCreates.slice(index*40,(index+1)*40);if(!ops.length)throw new Error('Routing batch outside reviewed204segments');
for(const op of ops){if(op.layer!=='TOP'||op.layerId!==EPCB_LayerId.TOP||op.widthMil<6||op.primitiveLock!==false)throw new Error('Unexpected routing geometry '+op.key);}
for(const op of ops){const p=await eda.pcb_PrimitiveLine.create(op.net,EPCB_LayerId.TOP,op.startXMil,op.startYMil,op.endXMil,op.endYMil,op.widthMil,false);if(!p)throw new Error('Routing LINE create failed '+op.key);created.push({key:op.key,id:p.getState_PrimitiveId()});}
}
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),issues=[],changes=[];
const targetNets=new Set(plan.newLineCreates.map(o=>o.net));
for(const[k,r]of before){if(k.startsWith('DOCHEAD:'))continue;const b=after.get(k)?.b;if(canonical(b)===canonical(r.b))continue;const fields=b?Object.keys({...r.b,...b}).filter(f=>canonical(r.b[f])!==canonical(b[f])):['missing'];let allowed=false;if(stage==='fill'&&k==='FILL:'+fill.id)allowed=!!b&&fields.every(f=>['path','refs','zIndex'].includes(f));if(stage!=='fill'&&r.h.type==='LINE'&&targetNets.has(r.b.netName))allowed=!b;changes.push({key:k,fields,allowed});if(!allowed)issues.push({key:k,fields});}
const added=[];for(const[k,r]of after)if(!before.has(k)&&!k.startsWith('DOCHEAD:')){if(stage==='fill'||r.h.type!=='LINE'||r.b.layerId!==EPCB_LayerId.TOP||!targetNets.has(r.b.netName))issues.push({key:k,issue:'unexpected-new-record'});else added.push(k);}
const path=root+'/output/validation/native-adc10-pcb-strip_routes_'+stage+'-20261018.epru',receiptPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/native-routes-'+stage+'-receipt-20261018.json';
const receipt={stage,manifestPath,manifestHash,priorPath,priorHash,path,sourceSha256:await hash(source),created,added,changes,issues,containmentPassed:issues.length===0,requiresIndependentCopperUnionAudit:true,saved:false,manufacturingReady:false};
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false)||!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Routing evidence capture failed; inspect actual before retry');
if(issues.length)throw new Error('Routing containment failed '+JSON.stringify(issues.slice(0,10))+'; actual='+path);
return{stage,containmentPassed:true,path,sourceSha256:receipt.sourceSha256,created:created.length,newLineRecords:added.length,changedRecords:changes.length,receiptPath,requiresIndependentCopperUnionAudit:true};
