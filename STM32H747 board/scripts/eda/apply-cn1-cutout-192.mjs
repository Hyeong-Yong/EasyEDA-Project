const expectedHash=__taskArgs[0],root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e';
if(!/^[a-f0-9]{64}$/.test(expectedHash||''))throw new Error('Reviewed CN1 cutout manifest SHA256 required');
const ids=['5b55024cb3a23233','6e8dd66b3e3db1b0','e94386c2e1a58187','f614cce4900c7115'];
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const manifestFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/candidates/cn1-cutout-192/cn1-cutout-192-plan.json');
if(!manifestFile)throw new Error('Reviewed cutout manifest missing');
const manifestText=await manifestFile.text(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(manifestText)))).map(b=>b.toString(16).padStart(2,'0')).join('');
if(hash!==expectedHash)throw new Error('CN1 cutout manifest changed');
const plan=JSON.parse(manifestText),changes=plan.changes;
if(plan.pcbUuid!==uuid||changes?.length!==4||changes.some(c=>c.type!=='POLY'||!ids.includes(c.id))||new Set(changes.map(c=>c.id)).size!==4)throw new Error('Only four approved cutout POLY records permitted');
const parse=s=>s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const p=l.indexOf('||');return{h:JSON.parse(l.slice(0,p)),b:JSON.parse(l.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const source=await eda.sys_FileManager.getDocumentSource(),before=parse(source),beforeMap=new Map(before.map(r=>[r.h.type+':'+r.h.id,r.b]));
const baselineFile=await eda.sys_FileSystem.readFileFromFileSystem(root+'/output/validation/native-cn1-cutout-192-before-20261016.epru');
if(!baselineFile)throw new Error('Reviewed pre-cutout source missing');
const baseline=parse(await baselineFile.text());
if(before[0]?.b.uuid!==uuid||before.length!==12732||baseline.length!==before.length)throw new Error('Pre-cutout source identity/inventory changed');
for(const r of baseline)if(!['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type)&&canonical(r.b)!==canonical(beforeMap.get(r.h.type+':'+r.h.id)))throw new Error('Unreviewed current PCB change '+r.h.type+':'+r.h.id);
const bounds=rows=>{const points=rows.flatMap(c=>[[c.path[0],c.path[1]],[c.path[3],c.path[4]]]);return{left:Math.min(...points.map(p=>p[0])),right:Math.max(...points.map(p=>p[0])),bottom:Math.min(...points.map(p=>p[1])),top:Math.max(...points.map(p=>p[1]))};};
for(const c of changes){
 if(canonical(beforeMap.get('POLY:'+c.id))!==canonical(c.before))throw new Error('Cutout target before body changed '+c.id);
 const a={...c.before},b={...c.after};delete a.path;delete b.path;
 if(canonical(a)!==canonical(b)||c.before.layerId!==11||c.before.width!==3.937)throw new Error('Cutout non-path field changed '+c.id);
 const p=c.after.path,q=c.before.path;
 if(p?.length!==5||p[2]!=='L'||p.filter(v=>typeof v==='number').length!==4||p.some(v=>typeof v==='number'&&(!Number.isFinite(v)||Math.abs(v)>10000)))throw new Error('Invalid cutout edge');
 if((q[0]===q[3])!==(p[0]===p[3])||(q[1]===q[4])!==(p[1]===p[4])||Math.sign(q[3]-q[0])!==Math.sign(p[3]-p[0])||Math.sign(q[4]-q[1])!==Math.sign(p[4]-p[1]))throw new Error('Cutout edge axis/orientation changed');
}
const oldBounds=bounds(changes.map(c=>c.before)),newBounds=bounds(changes.map(c=>c.after));
if(Math.abs((newBounds.right-newBounds.left)*.0254-1.92)>.000003||Math.abs((newBounds.top-newBounds.bottom)*.0254-1.92)>.000003||Math.abs((newBounds.right+newBounds.left)-(oldBounds.right+oldBounds.left))>1e-7||Math.abs((newBounds.top+newBounds.bottom)-(oldBounds.top+oldBounds.bottom))>1e-7)throw new Error('Approved 1.92-mm size/unchanged centre rejected');
const degree=new Map();for(const c of changes)for(const p of [[c.after.path[0],c.after.path[1]],[c.after.path[3],c.after.path[4]]]){const k=canonical(p);degree.set(k,(degree.get(k)||0)+1);}
if(degree.size!==4||[...degree.values()].some(v=>v!==2))throw new Error('Cutout is not an exactly closed four-edge rectangle');
const results=[];
for(const c of changes){
 const primitive=await eda.pcb_PrimitivePolyline.get(c.id);
 if(!primitive||Array.isArray(primitive))throw new Error('Reviewed cutout polyline unavailable '+c.id);
 const polygon=eda.pcb_MathPolygon.createPolygon(c.after.path);
 if(!polygon)throw new Error('Cutout polygon rejected '+c.id);
 const pending=primitive.toAsync();pending.setState_Polygon(polygon);pending.setState_LineWidth(c.before.width);
 await pending.done();results.push(c.id);
}
const afterSource=await eda.sys_FileManager.getDocumentSource(),after=parse(afterSource),actual=new Map(after.map(r=>[r.h.type+':'+r.h.id,r.b])),selected=new Map(changes.map(c=>[c.id,c])),differences=[],normalizations=[];
for(const r of before){
 if(['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type))continue;
 const c=r.h.type==='POLY'?selected.get(r.h.id):null,expected=c?c.after:r.b,current={...actual.get(r.h.type+':'+r.h.id)};
 if(c&&current.zIndex===-1&&expected.zIndex>=0){normalizations.push({id:r.h.id,field:'zIndex',before:expected.zIndex,after:-1});current.zIndex=expected.zIndex;}
 if(canonical(current)!==canonical(expected))differences.push({key:r.h.type+':'+r.h.id,expected,actual:actual.get(r.h.type+':'+r.h.id)});
}
for(const r of after)if(!beforeMap.has(r.h.type+':'+r.h.id))differences.push({error:'unexpected-record',row:r});
if(after.length!==before.length)differences.push({error:'record-count',before:before.length,after:after.length});
const afterPath=root+'/output/validation/native-cn1-cutout-192-after-20261016.epru';
if(!await eda.sys_FileSystem.saveFileToFileSystem(afterPath,new Blob([afterSource]),undefined,false))throw new Error('Cutout readback not saved');
const saved=!differences.length&&await eda.pcb_Document.save(),receiptPath=root+'/output/validation/native-cn1-cutout-192-apply-receipt-20261016.json';
if(!await eda.sys_FileSystem.saveFileToFileSystem(receiptPath,new Blob([JSON.stringify({uuid,manifestSha256:hash,approvedDate:'2026-10-16',results,oldBounds,newBounds,afterPath,differences,normalizations,saved},null,2)]),undefined,false))throw new Error('Cutout receipt not saved');
if(differences.length||!saved)throw new Error('Cutout preservation/save failed; inspect '+receiptPath);
return{uuid,modified:results.length,saved,receiptPath};
