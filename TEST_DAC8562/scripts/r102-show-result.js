const opened=await eda.dmt_EditorControl.openDocument('e3a1c5f417017755');
const d=await eda.dmt_SelectControl.getCurrentDocumentInfo();
if(d?.uuid!=='e3a1c5f417017755'||d.documentType!==1)throw new Error('Wrong schematic');
return {opened,page:'DAC_MCU',passed:await eda.sch_Drc.check(true,true,false),details:await eda.sch_Drc.check(true,true,true)};
