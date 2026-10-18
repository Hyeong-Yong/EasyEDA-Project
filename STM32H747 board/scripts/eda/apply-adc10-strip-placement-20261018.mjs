const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
const stage=__taskArgs[0],mode=['fill_v2','fill_v3'].includes(stage)?'fill':stage,reviewedHash=__taskArgs[1],stages=['place1','place2','place3','place4','fill'];
if(!stages.includes(mode)||!/^[a-f0-9]{64}$/.test(reviewedHash||''))throw new Error('Reviewed placement stage/hash required');
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Approved PCB must be active');
const load=async p=>{const f=await eda.sys_FileSystem.readFileFromFileSystem(p);if(!f)throw new Error('Missing '+p);return await f.text();};
const hash=async s=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))).map(v=>v.toString(16).padStart(2,'0')).join('');
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const sameComponent=(actual,expected)=>{if(!actual)return false;const b={...actual};for(const k of ['x','y']){if(b[k]===expected[k]||b[k]===Number(expected[k].toFixed(4)))b[k]=expected[k];}if(((b.angle%360)+360)%360===((expected.angle%360)+360)%360)b.angle=expected.angle;return canonical(b)===canonical(expected);};
const parse=s=>new Map(s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||'),h=JSON.parse(l.slice(0,i)),v=l.slice(i+2).replace(/\|$/,'');return[h.type+':'+h.id,{h,b:v?JSON.parse(v):''}];}));
const planPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/'+(stage==='fill_v3'?'adc10-strip-phase1-explicit-closed-API-polygon-20261018.json':'adc10-strip-phase1-placement-pad-clearance-20261018.json'),planText=await load(planPath);
if(await hash(planText)!==reviewedHash)throw new Error('Placement manifest changed');
const plan=JSON.parse(planText);
if(plan.PCBRequired!==uuid||plan.componentPlacements.length!==34||plan.fillPathUpdates.length!==1||plan.newLineCreates.length)throw new Error('Unexpected placement-only scope');
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),index=stages.indexOf(mode),selected=mode==='fill'?[]:plan.componentPlacements.slice(index*10,(index+1)*10),ids=new Set(selected.map(p=>p.componentId));
for(let i=0;i<plan.componentPlacements.length;i++){const p=plan.componentPlacements[i],already=i<index*10;const expected=already?p.afterBody:p.beforeBody;if(!sameComponent(before.get('COMPONENT:'+p.componentId)?.b,expected))throw new Error('Placement sequence/body mismatch '+p.ref);}
const fill=plan.fillPathUpdates[0];
if(canonical(before.get('FILL:'+fill.id)?.b)!==canonical(fill.sourceBodyBefore))throw new Error('TOP GND FILL changed before reviewed clearance cut');
const EPCB_LayerId={TOP:1},EPCB_PrimitiveFillMode={SOLID:0},touched=[];
if(mode!=='fill')for(const p of selected){const v=await eda.pcb_PrimitiveComponent.get(p.componentId);if(!v||v.getState_Designator()!==p.ref)throw new Error('Component identity failed '+p.ref);const a=v.toAsync();a.setState_X(p.afterBody.x);a.setState_Y(p.afterBody.y);a.setState_Rotation(p.afterBody.angle);a.setState_Layer(EPCB_LayerId.TOP);await a.done();touched.push(p.ref);}
else{for(const p of fill.afterPath)if(typeof p[0]==='number'&&(p.at(-2)!==p[0]||p.at(-1)!==p[1]))throw new Error('API requires explicit closed contour before any FILL mutation');const polygon=eda.pcb_MathPolygon.createComplexPolygon(fill.afterPath);if(!polygon)throw new Error('Invalid reviewed clearance polygon');if(!await eda.pcb_PrimitiveFill.modify(fill.id,{complexPolygon:polygon}))throw new Error('GND clearance update failed');touched.push(fill.id);}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),issues=[],changes=[];
for(const[k,r]of before){if(k.startsWith('DOCHEAD:'))continue;const actual=after.get(k)?.b;if(canonical(actual)===canonical(r.b))continue;const fields=actual?Object.keys({...r.b,...actual}).filter(f=>canonical(r.b[f])!==canonical(actual[f])):['missing'];let allowed=false;if(r.h.type==='COMPONENT'&&ids.has(r.h.id)){const p=selected.find(p=>p.componentId===r.h.id);allowed=sameComponent(actual,p.afterBody);}else if(r.h.type==='ATTR'&&ids.has(r.b.parentId))allowed=fields.every(f=>['x','y','angle','layerId'].includes(f));else if(mode==='fill'&&k==='FILL:'+fill.id)allowed=fields.every(f=>['path','zIndex'].includes(f));changes.push({key:k,fields,allowed});if(!allowed)issues.push({key:k,fields});}
for(const k of after.keys())if(!before.has(k)&&!k.startsWith('DOCHEAD:'))issues.push({key:k,issue:'unexpected-new-record'});
if(mode==='fill'&&canonical(after.get('FILL:'+fill.id)?.b.path)!==canonical(fill.afterPath))issues.push({key:'FILL:'+fill.id,issue:'polygon-normalization-needs-independent-geometry-audit'});
const path=root+'/output/validation/native-adc10-pcb-strip_'+stage+'-20261018.epru',receiptPath=root+'/output/candidates/adc10-pcb-finish-20261018/strip/native-'+stage+'-receipt-20261018.json';
const receipt={stage,manifestSha256:reviewedHash,passed:issues.length===0,path,sourceSha256:await hash(afterSource),touched,changes,issues,saved:false,manufacturingReady:false};
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([afterSource]),undefined,false)||!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify(receipt,null,2)]),undefined,false))throw new Error('Placement evidence capture failed; inspect live state before retry');
if(issues.length)throw new Error('Placement postflight failed '+JSON.stringify(issues.slice(0,12))+'; actual='+path);
return{stage,passed:true,touched,sourceSha256:receipt.sourceSha256,path,receiptPath,saved:false};
