import {readFile,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..','output/3d-models-20261018');
const candidates=JSON.parse(await readFile(resolve(base,'component-3d-transform-candidates.json'),'utf8'));
const families={
 '0402C':{uuid:'6034de4795654a0c8c74309dab7cb0b9',title:'0402C',mm:[1,.5,.5],evidence:'C1 native UI size verified'},
 '0402R':{uuid:'efdecb7dae4442949d28eecaf748420f',title:'R0402_L1.0-W0.5-H0.4',mm:[1,.5,.4]},
 '0603C':{uuid:'624118aa3cc7497086c383c2d72e0852',title:'C0603_L1.6-W0.8-H0.8',mm:[1.6,.8,.8]},
 '0603R':{uuid:'6aa93b2ff91b4b1ca9ff134ea14ab162',title:'R0603_L1.6-W0.8-H0.5',mm:[1.6,.8,.5]},
 '0805C':{uuid:'8c88e81f49c6409b980720ec8953afb6',title:'C0805_L2.0-W1.3-H1.3',mm:[2,1.3,1.3]},
 '1206C':{uuid:'02d7240ddd1f4fa09203e2ae369f23c6',title:'C1206_L3.2-W1.6-H1.3',mm:[3.2,1.6,1.3]}
};
const lib='0819f05c4eef4c71ace90d822a990e87';
const entries=candidates.targets.filter(t=>families[t.model_candidate.family]).map(t=>{
 const f=families[t.model_candidate.family],r=t.registration;
 const transform=[...f.mm.map(x=>x/.0254),r.local_rotation_z_deg,0,0,...r.local_offset_mm.map(x=>x/.0254)].map(n=>Number(n.toFixed(8))).join(',');
 return {ref:t.ref,id:t.component_id,footprintUuid:t.footprint_uuid,family:t.model_candidate.family,model:f.uuid+'|'+lib,title:f.title,transform,relation:'package-equivalent visualization; not manufacturer-specific mechanical certification'};
});
if(entries.length!==337)throw new Error('Passive scope count mismatch '+entries.length);
await writeFile(resolve(base,'passive-3d-apply-plan.json'),JSON.stringify({entries,families,library:lib,expectedCount:437,scope:'3D metadata only'},null,2));
console.log(JSON.stringify({entries:entries.length,counts:Object.fromEntries(Object.keys(families).map(f=>[f,entries.filter(e=>e.family===f).length]))},null,2));
