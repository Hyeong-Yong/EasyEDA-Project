const pcbUuid='3ca9811d1a42d086';
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==pcbUuid)throw new Error('Wrong dedicated PCB');
const original=await eda.sys_FileManager.getDocumentSource();
const source=__taskArgs[0]==='reserialize'?original.split(/\r?\n/).filter(l=>l.includes('||')).map(l=>{const [h,b]=l.split('||');const raw=b.replace(/\|$/,'');return JSON.stringify(JSON.parse(h))+'||'+JSON.stringify(JSON.parse(raw));}).join('|\n'):original;
const accepted=await eda.sys_FileManager.setDocumentSource(source);
return {accepted,bytes:source.length,unchangedSource:source===original,serializationOnly:__taskArgs[0]==='reserialize'};
