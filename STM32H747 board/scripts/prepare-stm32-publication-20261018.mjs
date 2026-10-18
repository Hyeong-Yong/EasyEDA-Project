import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const root=path.resolve(import.meta.dirname,'..'),inputName=process.argv[2];
if(!/^config\/[a-z0-9_-]+\.json$/.test(inputName||''))throw new Error('Explicit reviewed publication input JSON required');
const read=p=>fs.readFileSync(path.join(root,p),'utf8'),input=JSON.parse(read(inputName)),sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
if(input.scope!=='STM32H747 board'||input.routingVerified!==true||input.manufacturingReady!==false||!Array.isArray(input.evidencePaths))throw new Error('Unverified or out-of-scope publication input');
const drc=JSON.parse(read(input.finalDrc));if(drc.passed!==true||drc.violations!==0||drc.pcbUuid!=='0ac2a19168000d8e')throw new Error('Final strict native DRC is not zero');
const paths=new Set(),add=p=>{p=p.replaceAll('\\','/');const abs=path.resolve(root,p),rel=path.relative(root,abs);if(rel.startsWith('..')||path.isAbsolute(rel)||!fs.statSync(abs).isFile())throw new Error('Invalid scoped publication target '+p);if(/(^|\/)(\.tools|tmp|node_modules|__pycache__)(\/|$)|_backup\/|\.(?:pyc|pyo|log|tmp|lock)$/.test(p))throw new Error('Runtime/cache in explicit publication scope '+p);paths.add(p);};
const old=JSON.parse(read('output/candidates/git-publication-20261018/git-publication-plan-readonly-20261018.json'));
for(const f of old.proposedCurrentAllowlist.pathsAndSizes)if(!f.path.startsWith('output/'))add(f.path);
const walk=(directory,accept)=>{for(const e of fs.readdirSync(path.join(root,directory),{withFileTypes:true})){const p=directory+'/'+e.name;if(e.isDirectory()){if(!['__pycache__','node_modules','.tools','tmp'].includes(e.name))walk(p,accept);}else if(e.isFile()&&accept(p))add(p);}};
walk('scripts',p=>/\.(?:mjs|js|py|ps1|bat|cmd|json|txt)$/.test(p));
walk('config',p=>/\.(?:md|json|txt)$/.test(p)&&p!=='config/publication-manifest-20261018.json');
// Candidate history contains many superseded 30-40 MB plane manifests. Publish
// only the explicitly reviewed final evidence, not every intermediate draft.
walk('output/candidates/adc10-pcb-finish-20261018',p=>/\.(?:py|mjs)$/.test(p));
for(const p of input.evidencePaths)add(p);add(input.finalDrc);add(inputName);
const files=[...paths].sort().map(p=>{const abs=path.join(root,p),bytes=fs.statSync(abs).size;if(bytes>=100*1024*1024)throw new Error('GitHub size limit requires explicit alternative: '+p);return{path:p,bytes,sha256:sha(abs)};});
const patterns=[/-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----/,/\bgh[pousr]_[A-Za-z0-9]{30,}\b/,/\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b/,/\bxox[baprs]-[A-Za-z0-9-]{25,}\b/,/\bAKIA[0-9A-Z]{16}\b/],hits=[];
for(const f of files)if(/\.(?:md|json|py|mjs|js|ps1|bat|cmd|txt|net|epru)$/.test(f.path)){const t=read(f.path);if(patterns.some(re=>re.test(t)))hits.push(f.path);}
if(hits.length)throw new Error('Potential secret signature; inspect locally before publishing: '+JSON.stringify(hits));
const manifestPath='config/publication-manifest-20261018.json',specPath='output/analysis/git-publication-pathspec-20261018.nul';
const report={schema:'stm32h747-selective-git-publication-20261018-v1',scope:'STM32H747 board',inputPath:inputName,files,selectedFiles:files.length+1,bytes:files.reduce((s,f)=>s+f.bytes,0),selfPath:manifestPath,selfHashIntentionallyOmitted:true,routingVerified:true,manufacturingReady:false,strictNativeDrcPath:input.finalDrc,secretSignatureHits:[],secretScanLimit:'Recognized signatures in selected readable text only; binary artifacts not certified secret-free.',exclusions:'TEST_DAC8562, unrelated en/, runtime, cache, auto-backups and bulk intermediate outputs are not staged. No files deleted.',noGitMutationPerformed:true};
fs.writeFileSync(path.join(root,manifestPath),JSON.stringify(report,null,2)+'\n');fs.writeFileSync(path.join(root,specPath),[...files.map(f=>'STM32H747 board/'+f.path),'STM32H747 board/'+manifestPath].join('\0')+'\0');
console.log(JSON.stringify({selectedFiles:report.selectedFiles,bytes:report.bytes,manifest:path.join(root,manifestPath),pathspec:path.join(root,specPath),over50MiB:files.filter(f=>f.bytes>50*1024*1024).map(f=>({path:f.path,bytes:f.bytes})),secretSignatureHits:0,noGitMutationPerformed:true},null,2));
