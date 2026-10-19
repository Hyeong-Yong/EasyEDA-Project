import {execFileSync} from 'node:child_process';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const inventory=JSON.parse(await readFile(resolve(base,'output/3d-models-20261018/inventory/components-437.json'),'utf8'));
const groups=new Map();
for(const c of inventory)if(!c.dnp&&c.part_number&&!c.ref.startsWith('TP')&&!groups.has(c.package_group))groups.set(c.package_group,c.part_number);
const keys=process.argv.slice(2).length?process.argv.slice(2):[...groups.values()];
const dir=resolve(base,'output/3d-models-20261018/system-parts');await mkdir(dir,{recursive:true});
for(let i=0;i<keys.length;i+=4){
  const batch=keys.slice(i,i+4);
  const out=JSON.parse(execFileSync(process.execPath,[resolve(base,'scripts/easyeda-safe-client.mjs'),'execute-file','scripts/eda/query-part-models-20261018.mjs',JSON.stringify(batch)],{encoding:'utf8',timeout:45000,maxBuffer:12e6}));
  if(!out.ok)throw new Error('Guarded part search failed');
  for(const r of out.result.results){await writeFile(resolve(dir,r.key.replace(/[^A-Za-z0-9_-]/g,'_')+'.json'),JSON.stringify({library:out.result.lib,...r},null,2));console.log(r.key+': '+r.candidates.map(c=>c.item.name+' / '+c.footprint.name+' / '+(c.item.model3D?.uuid||c.item.model3DUuid||'no-device-model')).join('; '));}
}
