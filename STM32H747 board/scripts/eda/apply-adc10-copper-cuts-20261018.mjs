const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',projectName='STM32H747_MCU_BOARD_v19';
const [stage,reviewedHash]=__taskArgs,stages=['isolate','rename_1','rename_2','r164'],stageIndex=stages.indexOf(stage);
if(stageIndex<0||!/^[a-f0-9]{64}$/.test(reviewedHash||''))throw new Error('Reviewed copper-cut stage and manifest SHA256 required');
const info=await eda.dmt_Project.getCurrentProjectInfo();
if((info?.friendlyName||info?.name)!==projectName)throw new Error('Wrong project: no PCB operation permitted');
if(!await eda.dmt_EditorControl.openDocument(uuid))throw new Error('Could not open approved STM32H747 PCB');
const active=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(active?.uuid!==uuid)throw new Error('Wrong active PCB document');
const load=async path=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(path);if(!f)throw new Error('Missing reviewed file '+path);return await f.text();};
const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))).map(v=>v.toString(16).padStart(2,'0')).join('');
const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a.localeCompare(b))):v);
const parse=value=>{const rows=value.split(/\r?\n/).filter(v=>v.includes('||')).map(v=>{const p=v.indexOf('||'),b=v.slice(p+2).replace(/\|$/,'');return{h:JSON.parse(v.slice(0,p)),b:b?JSON.parse(b):''};});const map=new Map(rows.map(r=>[r.h.type+':'+r.h.id,r]));if(map.size!==rows.length)throw new Error('Native source contains duplicate identities');return{rows,map};};
const manifestPath=root+'/output/candidates/adc10-pcb-finish-20261018/adc10-copper-cut-execution-manifest-fresh-20261018.json',manifestText=await load(manifestPath);
if(await hash(manifestText)!==reviewedHash)throw new Error('Reviewed copper-cut manifest changed');
const plan=JSON.parse(manifestText);
if(!plan.passedPreflightGuards||plan.projectNameRequired!==projectName||plan.PCBRequired!==uuid||plan.existingCopperOperations.length!==40||plan.scope.deleteBiasLINE!==10||plan.scope.deleteExclusiveMIXFILL!==10||plan.scope.renameUpstreamPRELINE!==20||plan.scope.VIADeletes!==0)throw new Error('Unexpected reviewed copper-cut scope');
const baselinePath=root+'/output/validation/native-adc10-pcb-baseline-20261018.epru',baselineText=await load(baselinePath);
if(await hash(baselineText)!==plan.sourceSha256)throw new Error('Fresh frozen PCB baseline changed');
const baseline=parse(baselineText),ops=plan.existingCopperOperations,fillDeletes=ops.filter(o=>o.action==='delete'&&o.type==='FILL'),lineDeletes=ops.filter(o=>o.action==='delete'&&o.type==='LINE'),renames=ops.filter(o=>o.action==='modify'&&o.type==='LINE'),move=plan.R164Correction,owned=plan.R164ExpectedOwnedATTRs;
if(fillDeletes.length!==10||lineDeletes.length!==10||renames.length!==20||owned.length!==3||move.ref!=='R164'||move.deltaMmYUp[0]!==0||move.deltaMmYUp[1]!==-0.05)throw new Error('Primitive membership does not match reviewed40cuts+R164');
for(const o of ops){const r=baseline.map.get(o.type+':'+o.id);if(canonical(r?.b)!==canonical(o.beforeBody))throw new Error('Manifest original body mismatch '+o.type+':'+o.id);if(o.action==='modify'){const a={...o.beforeBody,netName:o.afterBody.netName};if(canonical(a)!==canonical(o.afterBody)||o.beforeBody.layerId!==1)throw new Error('Unexpected non-net LINE change '+o.id);}}
if(canonical(baseline.map.get('COMPONENT:'+move.id)?.b)!==canonical(move.beforeBody))throw new Error('R164 original component guard mismatch');
for(const a of owned)if(canonical(baseline.map.get('ATTR:'+a.id)?.b)!==canonical(a.beforeBody))throw new Error('R164 original owned ATTR guard mismatch '+a.id);
const expected=(completed)=>{const out=new Map(baseline.rows.map(r=>[r.h.type+':'+r.h.id,r.b]));if(completed>=0){for(const o of [...fillDeletes,...lineDeletes])out.delete(o.type+':'+o.id);}if(completed>=1)for(const o of renames.slice(0,10))out.set('LINE:'+o.id,o.afterBody);if(completed>=2)for(const o of renames.slice(10))out.set('LINE:'+o.id,o.afterBody);if(completed>=3){out.set('COMPONENT:'+move.id,move.afterBody);for(const a of owned)out.set('ATTR:'+a.id,a.expectedAfterBody);}return out;};
const compare=(actual,target)=>{const issues=[];for(const [key,body]of target){if(key.startsWith('DOCHEAD:'))continue;const value=actual.map.get(key);if(!value)issues.push({key,issue:'missing'});else if(canonical(value.b)!==canonical(body))issues.push({key,issue:'body-different'});}for(const key of actual.map.keys())if(!key.startsWith('DOCHEAD:')&&!target.has(key))issues.push({key,issue:'unexpected'});return issues;};
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),beforeIssues=compare(before,expected(stageIndex-1));
if(beforeIssues.length)throw new Error('Guard-all failed BEFORE any mutation; do not skip or repeat a stage: '+JSON.stringify(beforeIssues.slice(0,20)));
if(before.rows.find(r=>r.h.type==='DOCHEAD')?.b.uuid!==uuid||before.rows.filter(r=>r.h.type==='COMPONENT').length!==354)throw new Error('Live source PCB/354part identity changed');
const EPCB_LayerId={TOP:1};
const touched=[],receiptPath=root+'/output/candidates/adc10-pcb-finish-20261018/native-copper-cut-'+stage+'-receipt-20261018.json',sourcePath=root+'/output/validation/native-adc10-pcb-copper_'+stage+'-20261018.epru';
let actualSource='',actual=null,afterIssues=[],caught=null;
try{
if(stage==='isolate'){
for(const o of fillDeletes){const p=await eda.pcb_PrimitiveFill.get(o.id);if(!p||p.getState_PrimitiveId()!==o.id)throw new Error('FILL API identity unavailable '+o.id);}
for(const o of lineDeletes){const p=await eda.pcb_PrimitiveLine.get(o.id);if(!p||p.getState_PrimitiveId()!==o.id)throw new Error('Bias LINE API identity unavailable '+o.id);}
if(!await eda.pcb_PrimitiveFill.delete(fillDeletes.map(o=>o.id)))throw new Error('Exclusive mixer FILL deletion failed; inspect actual source before any retry');
touched.push(...fillDeletes.map(o=>({type:o.type,id:o.id,action:'delete'})));
if(!await eda.pcb_PrimitiveLine.delete(lineDeletes.map(o=>o.id)))throw new Error('Dedicated bias LINE deletion failed; inspect actual source before any retry');
touched.push(...lineDeletes.map(o=>({type:o.type,id:o.id,action:'delete'})));
}else if(stage==='rename_1'||stage==='rename_2'){
const selected=stage==='rename_1'?renames.slice(0,10):renames.slice(10);
for(const o of selected){const p=await eda.pcb_PrimitiveLine.get(o.id);if(!p||p.getState_PrimitiveId()!==o.id)throw new Error('PRE LINE API identity unavailable '+o.id);}
for(const o of selected){const p=await eda.pcb_PrimitiveLine.get(o.id),a=p.toAsync(),b=o.afterBody;a.setState_StartX(b.startX);a.setState_StartY(b.startY);a.setState_EndX(b.endX);a.setState_EndY(b.endY);a.setState_LineWidth(b.width);a.setState_Layer(EPCB_LayerId.TOP);a.setState_PrimitiveLock(b.locked);a.setState_Net(b.netName);await a.done();touched.push({type:'LINE',id:o.id,action:'net-only',net:b.netName});}
}else{
const p=await eda.pcb_PrimitiveComponent.get(move.id);if(!p||p.getState_Designator()!=='R164')throw new Error('R164 API identity unavailable');
const a=p.toAsync(),b=move.afterBody;a.setState_X(b.x);a.setState_Y(b.y);a.setState_Rotation(b.angle);a.setState_Layer(EPCB_LayerId.TOP);await a.done();touched.push({type:'COMPONENT',id:move.id,ref:'R164',action:'Y-minus0.05mm'});
}
actualSource=await eda.sys_FileManager.getDocumentSource();actual=parse(actualSource);afterIssues=compare(actual,expected(stageIndex));
if(afterIssues.length)throw new Error('Post-stage exact source audit failed; STOP before further edits: '+JSON.stringify(afterIssues.slice(0,20)));
}catch(e){caught=String(e?.message||e);if(!actualSource){actualSource=await eda.sys_FileManager.getDocumentSource();actual=parse(actualSource);afterIssues=compare(actual,expected(stageIndex));}}
const receipt={schema:'stm32h747-adc10-copper-cut-native-receipt-20261018-v1',stage,manifestPath,manifestSha256:reviewedHash,baselinePath,baselineSha256:plan.sourceSha256,sourcePath,sourceSha256:await hash(actualSource),passed:!caught&&afterIssues.length===0,error:caught,touched,afterIssues,afterRecordCount:actual.rows.length,physicalParts:actual.rows.filter(r=>r.h.type==='COMPONENT').length,saved:false,newRoutesApplied:false,manufacturingReady:false,recoveryCheckpoint:'STM32H747_before_pcb_route_20261018.epro2',recoveryWarning:'No native transaction/automatic rollback promised. On timeout or partial failure inspect captured actual source and receipt before another operation. Do not blindly rerun a stage.'};
if(!await eda.sys_FileSystem.saveFileToFileSystem(sourcePath,new Blob([actualSource]),undefined,false))throw new Error('Actual post-stage source capture failed; no retry or further edit before inspection');
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Post-stage audit receipt capture failed; inspect actual source before further edits');
if(caught)throw new Error(caught+'; actualSource='+sourcePath+'; receipt='+receiptPath);
return{stage,passed:true,sourcePath,receiptPath,sourceSha256:receipt.sourceSha256,touched:touched.length,records:actual.rows.length,saved:false,nextStage:stages[stageIndex+1]||'independent-readback-audit-before-placement',manufacturingReady:false};
