const pages=[];for(const page of ['e58bcc16379b10f4','e3a1c5f417017755']){
 await eda.dmt_EditorControl.openDocument(page);
 const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();if(d?.uuid!==page)throw new Error('Wrong schematic');
 pages.push({page,wires:(await eda.sch_PrimitiveWire.getAll()).map(w=>({id:w.getState_PrimitiveId(),net:w.getState_Net(),line:w.getState_Line()}))});
}return {pages};
