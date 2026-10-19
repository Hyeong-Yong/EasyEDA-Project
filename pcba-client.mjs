import fs from 'node:fs/promises';
const [projectName,codePath,resultPath]=process.argv.slice(2);
const origin='http://127.0.0.1:49620';
const request=async(route,body)=>{
  const r=await fetch(origin+route,body?{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(45000)}:{signal:AbortSignal.timeout(4000)});
  const data=await r.json();if(!r.ok||data.success===false)throw Error(JSON.stringify(data));return data;
};
const health=await request('/health');if(health.service!=='easyeda-bridge')throw Error('Wrong service');
const inventory=await request('/eda-windows');const candidates=[];const states=[];
for(const w of inventory.windows??[]){
  try{const data=await request('/execute',{windowId:w.windowId,code:'return await eda.dmt_Project.getCurrentProjectInfo();'});const p=data.result;states.push({windowId:w.windowId,name:p?.friendlyName??p?.name,uuid:p?.uuid});if(p&&[p.name,p.friendlyName].includes(projectName))candidates.push({windowId:w.windowId,project:p});}catch(e){states.push({windowId:w.windowId,error:String(e)});}
}
if(projectName==='status'){console.log(JSON.stringify(states,null,2));process.exit(0);}
if(candidates.length!==1)throw Error('Project selection must be unique: '+JSON.stringify(states));
if(!codePath){console.log(JSON.stringify(candidates[0],null,2));process.exit(0);}
const c=candidates[0],code=await fs.readFile(codePath,'utf8');
const guard=`const __args=${JSON.stringify(process.argv.slice(5))};const __p=await eda.dmt_Project.getCurrentProjectInfo();if(!__p||__p.uuid!==${JSON.stringify(c.project.uuid)}||![__p.name,__p.friendlyName].includes(${JSON.stringify(projectName)}))throw Error('Project guard failed');`;
const result=await request('/execute',{windowId:c.windowId,code:guard+code});
if(resultPath)await fs.writeFile(resultPath,JSON.stringify({projectName,projectUuid:c.project.uuid,windowId:c.windowId,result:result.result},null,2));
console.log(JSON.stringify(resultPath?{saved:resultPath,projectName,projectUuid:c.project.uuid}:result.result,null,2));
