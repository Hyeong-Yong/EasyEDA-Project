const page=__taskArgs[0];
if(!['e8a4e3fabe30ab59','360993a3108b5759','c0b1ffcb620d758f','3c13ef086afba6f5','a07bf8e4331877a8'].includes(page))throw Error('Explicit page required');
await eda.dmt_EditorControl.openDocument(page);
await new Promise(r=>setTimeout(r,1200));
const started=Date.now(),violations=await eda.sch_Drc.check(true,true,true),logs=(await eda.sys_Log.sort()).slice(-15);
return {page,info:await eda.dmt_SelectControl.getCurrentDocumentInfo(),violations,logs};
