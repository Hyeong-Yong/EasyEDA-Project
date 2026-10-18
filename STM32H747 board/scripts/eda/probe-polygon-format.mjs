const polygon = await eda.sch_PrimitivePolygon.create([0,0,2,0,2,2,0,2,0,0],'#840000','#840000',undefined,undefined);
if (!polygon) throw new Error('Polygon creation failed');
await new Promise(r=>setTimeout(r,500));
const source=await eda.sys_FileManager.getDocumentSource();
const lines=source.split('\n').filter(x=>x.includes('POLY')||x.includes('path')||x.includes('points'));
const removed=await eda.sch_PrimitivePolygon.delete(polygon);
return {lines,removed};
