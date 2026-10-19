const keys=JSON.parse(__taskArgs[0]||'[]');
if(!Array.isArray(keys)||keys.length<1||keys.length>8||keys.some(k=>typeof k!=='string'||k.length>100))throw new Error('1-8 part search keys required');
const lib=await eda.lib_LibrariesList.getSystemLibraryUuid();
const results=await Promise.all(keys.map(async key=>{
  let found;try{found=await eda.lib_Device.search(key);}catch(e){return {key,error:String(e),detail:JSON.stringify(e),candidates:[]};}
  const candidates=[];
  for(const item of found.slice(0,3)){
    const fp=item.footprint||{uuid:item.footprintUuid,libraryUuid:item.libraryUuid,name:item.footprintName};
    let source;
    if(fp.uuid){try{source=await eda.lib_Footprint.getDocumentSource(fp.uuid);}catch(e){source={error:String(e),detail:JSON.stringify(e)};}}
    candidates.push({item,footprint:fp,source});
  }
  return {key,candidates};
}));
return {lib,results};
