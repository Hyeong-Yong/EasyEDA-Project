const pages=[];
for(const page of ['e58bcc16379b10f4','e3a1c5f417017755']){
 const tab=await eda.dmt_EditorControl.openDocument(page);
 const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
 if(d?.uuid!==page||d.documentType!==1)throw new Error('Wrong schematic page');
 if(!await eda.sch_Document.save())throw new Error('Cannot close unsaved page');
 await eda.dmt_EditorControl.closeDocument(tab);
 const reopened=await eda.dmt_EditorControl.openDocument(page);
 pages.push({page,saved:true,reopened,passed:await eda.sch_Drc.check(true,true,false),details:await eda.sch_Drc.check(true,true,true),source:await eda.sys_FileManager.getDocumentSource(),netlist:await eda.sch_Netlist.getNetlist('Protel2')});
}
return {project:p.friendlyName,pages};
