const source = await eda.sys_FileManager.getDocumentSource();
return {lines:source?.split('\n').filter(x=>x.includes('6076539e0bb90016')||x.includes('Net-(D1-K)'))};
