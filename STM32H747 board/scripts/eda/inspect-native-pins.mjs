await eda.dmt_EditorControl.openDocument('884e9cee09bd3f65');
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
const designators=[];
for(const line of source.split('\n')){
if(!line.includes('||'))continue;
const [h,b]=line.split('||');
const head=JSON.parse(h),body=JSON.parse(b.replace(/\|$/,''));
if(head.type==='ATTR' && body.key==='Designator' && ['U1','R1','C1'].includes(body.value))designators.push({ref:body.value,id:body.parentId});
}
const result=[];
for(const item of designators){const pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(item.id);result.push({...item,pinCount:pins?.length,pins:pins?.slice(0,3)});}
return result;
