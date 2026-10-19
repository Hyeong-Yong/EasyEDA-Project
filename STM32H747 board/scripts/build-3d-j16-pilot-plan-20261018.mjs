import {readFile,writeFile} from 'node:fs/promises';import {resolve,dirname} from 'node:path';import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..','output/3d-models-20261018');const p=JSON.parse(await readFile(resolve(base,'component-3d-transform-candidates.json'),'utf8'));const t=p.targets.find(t=>t.ref==='J16');
const transform=[7/.0254,15.1/.0254,12.8980158/.0254,180,0,0,0,4.05/.0254,-3.4/.0254].join(',');
const entries=[{ref:t.ref,id:t.component_id,model:'96cf95a264794d81af2e5617ad1f8584|0819f05c4eef4c71ace90d822a990e87',title:'SMA-TH_SMA-KWE901',transform,evidence:'379OBJ pitch calibrated5.08mm; neck-Y rotated180 to+Y; pin pattern atnormalized+Y4.05; source case seatingplane3.4abovepin-tipminZ'}];
await writeFile(resolve(base,'j16-registered-pilot-plan.json'),JSON.stringify({entries,status:'PILOT_REQUIRES_NATIVE_OBJ_VERIFICATION'},null,2));console.log({ref:t.ref,transform});
