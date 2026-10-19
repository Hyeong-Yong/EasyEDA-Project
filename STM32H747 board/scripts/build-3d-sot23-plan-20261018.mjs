import {readFile,writeFile} from 'node:fs/promises';import {resolve,dirname} from 'node:path';import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..','output/3d-models-20261018');
const p=JSON.parse(await readFile(resolve(base,'component-3d-transform-candidates.json'),'utf8'));
const extentMil=[118.6043327140808,114.17300375461578,49.176399515904485];
const entries=p.targets.filter(t=>t.model_candidate.family==='SOT23_5_DBV').map(t=>({ref:t.ref,id:t.component_id,footprintUuid:t.footprint_uuid,family:'SOT23_5_DBV',model:'400e88a480ad4616a631bf409c145270|0819f05c4eef4c71ace90d822a990e87',title:'SOT-23-5_L2.9-W1.6-H1.1-LS2.8-P0.95_1',transform:[...extentMil,t.registration.local_rotation_z_deg,0,0,...t.registration.local_offset_mm.map(x=>x/.0254)].join(','),evidence:'Native U10 model manager default extents + preview alignment; 3 leads left with pin1 upper-left; full mesh XYZ preserved',relation:'SOT23-5 package-equivalent, not exact MPN markings'}));
if(entries.length!==23)throw new Error('SOT23-5 count mismatch');
await writeFile(resolve(base,'sot23-5-3d-apply-plan.json'),JSON.stringify({entries,expectedCount:437,scope:'3D metadata only'},null,2));console.log({count:entries.length});
