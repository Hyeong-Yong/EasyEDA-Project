const source=await eda.sys_FileManager.getDocumentSource();
return source.split('\n').filter(x=>x.startsWith('{"type":"POLY"')||x.startsWith('{"type":"RECT"')).slice(0,4).map(x=>x.slice(0,2400));
