const configFile=await eda.sys_FileSystem.readFileFromFileSystem('C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board/config/easyeda-project.json');
const config=JSON.parse(await configFile.text());
const project=(await eda.dmt_Project.getCurrentProjectInfo()).uuid;
const result=[];
for(const page of config.pages){
const closed=await eda.dmt_EditorControl.closeDocument(page.uuid+'@'+project);
result.push({page:page.sourcePdfPage,uuid:page.uuid,closed});
}
return result;
