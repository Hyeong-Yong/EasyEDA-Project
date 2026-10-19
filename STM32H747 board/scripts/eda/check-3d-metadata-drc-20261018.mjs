const stage=__taskArgs[0]||'405';if(!/^[a-z0-9-]+$/.test(stage))throw new Error('Scoped stage required');
const doc=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(doc?.uuid!=='0ac2a19168000d8e')throw new Error('STM PCB must be current');
const details=await eda.pcb_Drc.check(true,false,true);if(!Array.isArray(details))throw new Error('Detailed DRC result missing');
const violations=details.reduce((n,d)=>n+Number(d.count||0),0);
const report={stage:'3d-model-metadata-only-'+stage,doc,strict:true,details,violations,passed:violations===0};
const path='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/output/3d-models-20261018/audits/native-drc-model-stage-'+stage+'.json';
const saved=await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([JSON.stringify(report,null,2)]),undefined,false);
return {saved,path,violations,counts:details.map(d=>({name:d.name,count:d.count}))};
