const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',[startText,countText,stage,reviewedHash]=__taskArgs,start=Number(startText),count=Number(countText);
if(!((start===0&&count===1&&stage==='orientation_probe')||(start===1&&count===19&&stage==='oriented'))||!/^[a-f0-9]{64}$/.test(reviewedHash||''))throw new Error('Reviewed orientation batch required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_SelectControl.getCurrentDocumentInfo())?.uuid!==uuid)throw new Error('Wrong PCB');
const f=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/analysis/adc10-passive-orientation-plan-20261017.json');
if(!f)throw new Error('Orientation plan absent');
const raw=await f.text(),digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))).map(x=>x.toString(16).padStart(2,'0')).join('');
if(digest!==reviewedHash)throw new Error('Orientation manifest changed');
const plan=JSON.parse(raw),source=await eda.sys_FileManager.getDocumentSource(),rows=source.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};}),map=new Map(rows.map(r=>[r.h.type+':'+r.h.id,r]));
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
if(plan.edits.length!==20)throw new Error('Unexpected orientation count');
const edits=plan.edits.slice(start,start+count),EPCB_LayerId={TOP:1};
for(const e of edits){if(canonical(map.get('COMPONENT:'+e.componentId)?.b)!==canonical(e.sourceBodyBefore))throw new Error('Orientation baseline changed '+e.ref);if(e.set.layer!==EPCB_LayerId.TOP||e.set.x!==e.sourceBodyBefore.x||e.set.y!==e.sourceBodyBefore.y||![90,270].includes(e.set.rotation))throw new Error('Unexpected orientation target');}
for(const e of edits){const p=await eda.pcb_PrimitiveComponent.get(e.componentId);if(!p||p.getState_Designator()!==e.ref)throw new Error('Orientation API identity mismatch '+e.ref);const a=p.toAsync();a.setState_X(e.set.x);a.setState_Y(e.set.y);a.setState_Rotation(e.set.rotation);a.setState_Layer(EPCB_LayerId.TOP);await a.done();}
const actual=await eda.sys_FileManager.getDocumentSource(),path=root+'/output/validation/native-adc10-pcb-'+stage+'-20261017.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([actual]),undefined,false))throw new Error('Oriented source not captured');
return{path,changedRefs:edits.map(e=>e.ref),saved:false,manufacturingReady:false};
