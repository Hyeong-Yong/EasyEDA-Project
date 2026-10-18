import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root=path.resolve(import.meta.dirname,'..'),[sourceName,countArg]=process.argv.slice(2),count=Number(countArg);
if(!/^native-adc10-pcb-strip_routes_lines_[0-9]+-20261018\.epru$/.test(sourceName||'')||!Number.isInteger(count)||count<1||count>204)throw new Error('Scoped actual route capture and prefix count required');
const basePath=path.join(root,'output/validation/native-adc10-pcb-strip_routes_fill-20261018.epru'),sourcePath=path.join(root,'output/validation',sourceName),manifestPath=path.join(root,'output/candidates/adc10-pcb-finish-20261018/strip/adc10-strip-phase2-rebased-closed-operations-20261018.json');
const sha=s=>crypto.createHash('sha256').update(s).digest('hex'),read=p=>fs.readFileSync(p,'utf8'),canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const parse=s=>new Map(s.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const i=l.indexOf('||'),h=JSON.parse(l.slice(0,i));return[h.type+':'+h.id,{h,b:JSON.parse(l.slice(i+2).replace(/\|$/,''))}];}));
const mt=read(manifestPath),bt=read(basePath),st=read(sourcePath),plan=JSON.parse(mt),before=parse(bt),after=parse(st),errors=[];
if(sha(mt)!=='717e616c61c0c9ce6220ff8a6f4221496b1b0189c034cf8ce7717b57aaf3ba24'||sha(bt)!=='0ffaee75d7d2fac6e6f70ee4c06296583564c4bd25b3be173e53540297415ede')throw new Error('Frozen reviewed input changed');
for(const[k,r]of before)if(!k.startsWith('DOCHEAD:')&&canonical(after.get(k)?.b)!==canonical(r.b))errors.push({key:k,issue:'protected-body-changed-or-merged; use independent union auditor'});
const round=v=>Number(v.toFixed(4)),key=b=>{const p=[[round(b.startX),round(b.startY)],[round(b.endX),round(b.endY)]].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);return canonical([b.layerId,b.netName,round(b.width),p]);},expected=new Map(),actual=new Map();
for(const o of plan.newLineCreates.slice(0,count)){const k=key({layerId:o.layerId,netName:o.net,width:o.widthMil,startX:o.startXMil,startY:o.startYMil,endX:o.endXMil,endY:o.endYMil});expected.set(k,(expected.get(k)||0)+1);}
const added=[...after].filter(([k])=>!before.has(k)&&!k.startsWith('DOCHEAD:'));
for(const[k,r]of added){if(r.h.type!=='LINE'){errors.push({key:k,issue:'unexpected-non-LINE'});continue;}const b=r.b,extra=Object.keys(b).filter(f=>!['partitionId','groupId','netName','layerId','startX','startY','endX','endY','width','locked','zIndex'].includes(f));if(extra.length||b.partitionId!==''||b.groupId!==0||b.locked!==false||b.zIndex!==-1)errors.push({key:k,issue:'unexpected-new-LINE-fields'});const q=key(b);actual.set(q,(actual.get(q)||0)+1);}
for(const[k,n]of expected)if(actual.get(k)!==n)errors.push({geometry:k,expected:n,actual:actual.get(k)||0});
for(const[k,n]of actual)if(expected.get(k)!==n&&!expected.has(k))errors.push({geometry:k,issue:'unexpected-geometry',count:n});
const report={passed:errors.length===0,prefixCount:count,basePath,baselineSha256:sha(bt),sourcePath,sourceSha256:sha(st),manifestPath,manifestSha256:sha(mt),protectedDesignBodiesExact:before.size-1,addedLineRecords:added.length,normalization:'Only new requested endpoint/width values round to4decimalmil; endpoints may reverse without changing copper',requiresUnionAuditorIfMerged:true,errors};
const out=path.join(root,'output/candidates/adc10-pcb-finish-20261018/strip',`root-unmerged-prefix-${count}-audit-20261018.json`);fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,errors:errors.slice(0,3),report:out},null,2));if(errors.length)process.exitCode=1;
