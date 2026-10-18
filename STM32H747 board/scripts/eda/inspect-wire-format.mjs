const wire = await eda.sch_PrimitiveWire.create([1010,444.3,1010,449.3],'Net-(D1-K)','#009600',undefined,undefined);
if (!wire) throw new Error('Native wire creation failed');
const source = await eda.sys_FileManager.getDocumentSource();
const lines = source?.split('\n').filter(x => x.includes('WIRE') || x.includes('Net-(D1-K)'));
return {lines};
