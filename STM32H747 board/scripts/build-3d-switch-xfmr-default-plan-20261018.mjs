import {readFile,writeFile} from 'node:fs/promises';import {resolve,dirname} from 'node:path';import {fileURLToPath} from 'node:url';
const base=resolve(dirname(fileURLToPath(import.meta.url)),'..','output/3d-models-20261018');const p=JSON.parse(await readFile(resolve(base,'component-3d-transform-candidates.json'),'utf8'));
const models={TR1:{uuid:'d691814482f84b87ab195e8d38090ed5',title:'XFMR-SMD_H1102N'},SW1:{uuid:'73b3a84ae74e462f8f90e36cc5fd3e32',title:'SW-SMD_4P-L6.0-W6.0-P4.50-LS8.6_TS014-TBW1FH7.5'}};
const entries=Object.entries(models).map(([ref,m])=>({ref,id:p.targets.find(t=>t.ref===ref).component_id,...m,libraryUuid:'0819f05c4eef4c71ace90d822a990e87',relation:'Package-equivalent visualization, not exact current BOM MPN. Must calibrate pin positions and body size before final.'}));
await writeFile(resolve(base,'switch-xfmr-default-model-plan.json'),JSON.stringify({entries,status:'TEMPORARY_DEFAULT_FRAME_FOR_MEASUREMENT',expectedCount:437},null,2));
