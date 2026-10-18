const source=await eda.sys_FileManager.getDocumentSource();
if (!source) throw new Error('No active source');
const updated=await eda.sys_FileManager.setDocumentSource(source);
return {updated,sourceLength:source.length};
