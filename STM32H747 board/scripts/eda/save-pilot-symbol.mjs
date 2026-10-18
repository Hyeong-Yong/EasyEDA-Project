const symbol='480221a36a8c0287';
const library=(await eda.dmt_Project.getCurrentProjectInfo()).uuid;
if(library!=='761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c')throw new Error('Wrong dedicated project library');
const source=await eda.sys_FileManager.getDocumentSource();
const head=JSON.parse(source.split('\n')[0].split('||')[1].replace(/\|$/,''));
if(head.uuid!==symbol)throw new Error('Wrong current symbol document');
const updated=await eda.lib_Symbol.updateDocumentSource(symbol,library,source);
return {symbol,library,updated};
