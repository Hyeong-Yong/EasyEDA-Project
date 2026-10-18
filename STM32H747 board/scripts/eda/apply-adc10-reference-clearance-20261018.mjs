const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Approved PCB must remain active');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(p);if(!f)throw new Error('Missing '+p);return await f.text();},hash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))).map(v=>v.toString(16).padStart(2,'0')).join('');
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q),parse=s=>new Map(s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||'),h=JSON.parse(l.slice(0,i));return[h.type+':'+h.id,{h,b:JSON.parse(l.slice(i+2).replace(/\|$/,''))}];}));
const manifestPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/adc10-reference-courtyard-correction-20261018.json',mt=await load(manifestPath),manifestHash='526d89e8e62a11fa5d389bb5434828ed068b75eda322830c82d8c29ff1836261';
if(await hash(mt)!==manifestHash)throw new Error('Reviewed REF correction changed');const plan=JSON.parse(mt);
const bt=await load(root+'/output/validation/native-adc10-pcb-strip_routes_lines_5-20261018.epru');if(await hash(bt)!==plan.sourceSha256)throw new Error('Reviewed REF source changed');
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),baseline=parse(bt);
if(before.size!==baseline.size)throw new Error('Current PCB membership differs from reviewed REF source');for(const[k,r]of baseline)if(!k.startsWith('DOCHEAD:')&&canonical(before.get(k)?.b)!==canonical(r.b))throw new Error('Current PCB differs '+k);
if(plan.componentMoves.length!==3||plan.deleteOnlyNewPhase2Lines.length!==7||plan.newLineCreates.length!==8||plan.fillPathUpdates.length!==1||plan.clearanceConflicts.length||!plan.APIPathsExplicitlyClosed)throw new Error('Unexpected REF correction scope');
const ids=new Set(plan.componentMoves.map(o=>o.componentId)),deletes=new Set(plan.deleteOnlyNewPhase2Lines.map(o=>o.id)),fill=plan.fillPathUpdates[0];
for(const o of plan.componentMoves)if(canonical(before.get('COMPONENT:'+o.componentId)?.b)!==canonical(o.beforeBody))throw new Error('REF component changed '+o.ref);
for(const o of plan.deleteOnlyNewPhase2Lines)if(canonical(before.get('LINE:'+o.id)?.b)!==canonical(o.beforeBody))throw new Error('REF new LINE changed '+o.id);
if(canonical(before.get('FILL:'+fill.id)?.b)!==canonical(fill.sourceBodyBefore))throw new Error('REF GND fill changed');
for(const p of fill.afterPath)if(typeof p[0]==='number'&&(p.at(-2)!==p[0]||p.at(-1)!==p[1]))throw new Error('Unclosed REF API contour');
const polygon=eda.pcb_MathPolygon.createComplexPolygon(fill.afterPath);if(!polygon)throw new Error('Invalid REF polygon');
if(!await eda.pcb_PrimitiveLine.delete([...deletes]))throw new Error('REF obsolete leaf removal failed');
const EPCB_LayerId={TOP:1};for(const o of plan.componentMoves){const p=await eda.pcb_PrimitiveComponent.get(o.componentId);if(!p||p.getState_Designator()!==o.ref)throw new Error('REF component identity failed');const a=p.toAsync();a.setState_X(o.afterBody.x);a.setState_Y(o.afterBody.y);a.setState_Rotation(o.afterBody.angle);a.setState_Layer(EPCB_LayerId.TOP);await a.done();}
if(!await eda.pcb_PrimitiveFill.modify(fill.id,{complexPolygon:polygon}))throw new Error('REF local GND cut failed');
const created=[];for(const o of plan.newLineCreates){const p=await eda.pcb_PrimitiveLine.create(o.net,EPCB_LayerId.TOP,o.startXMil,o.startYMil,o.endXMil,o.endYMil,o.widthMil,false);if(!p)throw new Error('REF leaf create failed '+o.key);created.push({key:o.key,id:p.getState_PrimitiveId()});}
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),issues=[],changes=[];
for(const[k,r]of before){if(k.startsWith('DOCHEAD:'))continue;const b=after.get(k)?.b;if(canonical(b)===canonical(r.b))continue;const fields=b?Object.keys({...r.b,...b}).filter(f=>canonical(r.b[f])!==canonical(b[f])):['missing'];let allowed=false;
if(r.h.type==='LINE'&&deletes.has(r.h.id))allowed=!b;
else if(r.h.type==='COMPONENT'&&ids.has(r.h.id)){const o=plan.componentMoves.find(o=>o.componentId===r.h.id),e={...o.afterBody,x:Number(o.afterBody.x.toFixed(4)),y:Number(o.afterBody.y.toFixed(4))};allowed=canonical(b)===canonical(e);}
else if(r.h.type==='ATTR'&&ids.has(r.b.parentId))allowed=fields.every(f=>['x','y','angle','layerId'].includes(f));
else if(k==='FILL:'+fill.id)allowed=!!b&&fields.every(f=>['path','refs','zIndex'].includes(f));changes.push({key:k,fields,allowed});if(!allowed)issues.push({key:k,fields});}
for(const[k,r]of after)if(!before.has(k)&&!k.startsWith('DOCHEAD:')&&(r.h.type!=='LINE'||r.b.layerId!==1||!['+3V3','ADC_BIAS_2V5'].includes(r.b.netName)))issues.push({key:k,issue:'unexpected-new-record'});
const path=root+'/output/validation/native-adc10-pcb-ref_courtyard-20261018.epru',receiptPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/native-ref-courtyard-receipt-20261018.json',receipt={manifestPath,manifestHash,path,sourceSha256:await hash(source),containmentPassed:issues.length===0,issues,changes,created,requiresIndependentGeometryAndGraphAudit:true,saved:false,manufacturingReady:false};
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false)||!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('REF evidence capture failed');if(issues.length)throw new Error('REF containment failed '+JSON.stringify(issues)+'; actual='+path);
return{path,sourceSha256:receipt.sourceSha256,containmentPassed:true,receiptPath,requiresIndependentGeometryAndGraphAudit:true};
