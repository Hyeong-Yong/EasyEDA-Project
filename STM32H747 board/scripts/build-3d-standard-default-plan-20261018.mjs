import {readFile,writeFile} from 'node:fs/promises';import {resolve,dirname} from 'node:path';import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..','output/3d-models-20261018');const p=JSON.parse(await readFile(resolve(base,'standard-model-candidate-registry.json'),'utf8'));
const entries=p.targets.filter(t=>t.ref!=='U3').map(t=>({ref:t.ref,id:t.component_id,family:t.family,uuid:t.model_uuid,libraryUuid:t.model_library_uuid,title:t.model_title}));
if(entries.length!==26)throw new Error('Expected26 remaining standardbodies');await writeFile(resolve(base,'standard-default-model-plan.json'),JSON.stringify({entries,status:'TEMPORARY_DEFAULT_FRAME_FOR_RAW_NATIVE_OBJ_MEASUREMENT',expectedCount:437},null,2));console.log({entries:entries.length});
