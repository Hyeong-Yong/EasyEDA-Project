import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';

const root=path.resolve(import.meta.dirname,'../..');
const project='STM32H747 board/';
const manifestPath=project+'config/publication-manifest-20261019.json';
const pathspecPath=project+'output/analysis/git-publication-pathspec-20261019.nul';
const git=(...args)=>execFileSync('git',args,{cwd:root,maxBuffer:100_000_000}).toString('utf8');
const candidates=[...new Set(git('ls-files','--modified','--deleted','--others','--exclude-standard','-z').split('\0').filter(Boolean))];
const forced=[
 'output/checkpoints/STM32H747_3d_models_412_20261018.epro2',
 'output/checkpoints/STM32H747_before_3d_models_20261018.epro2',
 'output/checkpoints/STM32H747_labtool_adc10_routed_final_20261018.epro2',
 'output/validation/native-adc10-pcb-labtool_adc10_routed_final_saved-20261018.epru',
 'output/validation/native-adc10-labtool_schematic-Protel2-20261018.net',
 'output/validation/native-adc10-labtool-schematic-erc-details-final_routed-20261018.json',
 'output/validation/native-pcb-drc-0ac2a19168000d8e-labtool_ground_bridged_20261018.json',
 'output/validation/STM32H747_labtool_adc10_final_20261018_DIAGNOSTIC_NOT_FOR_FAB.zip',
 'output/validation/native-diagnostic-gerber-export-labtool_adc10_final_20261018-receipt.json',
 'output/validation/STM32H747_assembly_412_top_native_capture_20261018.jpg',
 'output/validation/STM32H747_assembly_412_bottom_native_capture_20261018.jpg',
 ...fs.readdirSync(path.join(root,project,'output/validation')).filter(n=>/^pcb-3d-.*\.epru$/.test(n)).map(n=>'output/validation/'+n),
].map(p=>project+p);
const ignoredAsTemporary=p=>/(^|\/)(?:\.tools|node_modules|__pycache__|tmp)(\/|$)|(^|\/)[^/]*_backup(\/|$)|\.(?:log|tmp|lock|pyc|pyo|nul)$|(?:-wal|-shm|-journal)$/.test(p)||(/(^|\/)backups\//.test(p)&&!p.endsWith('/.gitkeep'));
const excluded=candidates.filter(ignoredAsTemporary);
const selected=[...new Set([...candidates.filter(p=>!ignoredAsTemporary(p)),...forced])].filter(p=>p!==manifestPath&&p!==pathspecPath).sort();
const signatures=[
 /-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----/,
 /\bgh[pousr]_[A-Za-z0-9]{30,}\b/,
 /\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b/,
 /\bxox[baprs]-[A-Za-z0-9-]{25,}\b/,
 /\bAKIA[0-9A-Z]{16}\b/,
];
const textExtension=/\.(?:md|json|js|mjs|cjs|py|ps1|cmd|bat|txt|net|epru|esym|efoo|edevice|cir|inc|lib|sp|spice|xml|yaml|yml|toml|ts)$/i;
const files=[],secretHits=[];
for(const p of selected){
 const abs=path.resolve(root,p),rel=path.relative(root,abs);
 if(rel.startsWith('..')||path.isAbsolute(rel))throw new Error('Path outside repository: '+p);
 if(!fs.existsSync(abs)){files.push({path:p,deleted:true});continue;}
 const stat=fs.lstatSync(abs);
 if(!stat.isFile())throw new Error('Nonregular publication target: '+p);
 if(stat.size>=100*1024*1024)throw new Error('GitHub individual-file limit: '+p);
 const data=fs.readFileSync(abs),after=fs.statSync(abs);
 if(after.size!==stat.size||after.mtimeMs!==stat.mtimeMs)throw new Error('File changed while being read: '+p);
 const sha256=crypto.createHash('sha256').update(data).digest('hex');
 if(textExtension.test(p)&&signatures.some(re=>re.test(data.toString('utf8'))))secretHits.push(p);
 files.push({path:p,bytes:data.length,sha256});
}
if(secretHits.length)throw new Error('Potential credential signatures; inspect before publishing: '+JSON.stringify(secretHits));
const report={
 schema:'easyeda-whole-project-change-publication-20261019-v1',
 date:'2026-10-19',timezone:'Asia/Seoul',
 authorization:'User explicitly requested all repository project changes, including TEST_DAC8562.',
 baseCommit:git('rev-parse','HEAD').trim(),
 scope:'All nonignored project changes plus explicitly selected final STM32 validation/checkpoint deliverables.',
 files,selectedFilesIncludingThisManifest:files.length+1,
 totalBytesExcludingThisManifest:files.reduce((n,f)=>n+(f.bytes||0),0),
 forcedFinalPaths:forced,excludedTemporaryCandidates:excluded,
 alreadyIgnoredRuntimeAndCacheRemainExcluded:true,
 historicalAndPendingArtifactsAreArchivesNotManufacturingApproval:true,
 cadDocumentsAndBridgeProcessesModifiedByPublisher:false,
 recognizedCredentialSignatureHits:[],
 secretScanLimit:'High-confidence known signatures in selected readable text; not binary-secret or redistribution-rights certification.',
 selfHashIntentionallyOmitted:true,noGitMutationPerformedByGenerator:true,
};
fs.writeFileSync(path.join(root,manifestPath),JSON.stringify(report,null,2)+'\n');
fs.writeFileSync(path.join(root,pathspecPath),[...selected,manifestPath].join('\0')+'\0');
console.log(JSON.stringify({selectedFiles:report.selectedFilesIncludingThisManifest,totalBytes:report.totalBytesExcludingThisManifest,excludedTemporary:excluded.length,over50MiB:files.filter(f=>f.bytes>50*1024*1024).map(f=>({path:f.path,bytes:f.bytes})),manifestPath,pathspecPath,secretSignatureHits:0},null,2));
