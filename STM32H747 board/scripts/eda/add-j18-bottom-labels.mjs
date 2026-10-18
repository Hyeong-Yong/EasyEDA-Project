const root='C:/Dev/EasyEDA/EasyEDA-Project/STM32H747 board',uuid='0ac2a19168000d8e',mode=__taskArgs[0];
if(!['first','rest','title'].includes(mode))throw new Error('Explicit J18 labeling stage required');
await eda.dmt_EditorControl.openDocument(uuid);
if((await eda.dmt_Pcb.getCurrentPcbInfo())?.uuid!==uuid)throw new Error('Wrong dedicated PCB');
const pins=[{n:1,x:47.765,h:'1 PD3',f:'SCK'},{n:2,x:47.765,h:'2 PB15',f:'MOSI'},{n:3,x:45.225,h:'3',f:'GND'},{n:4,x:45.225,h:'4 PC7',f:'CSn'},{n:5,x:42.685,h:'5',f:'GND'},{n:6,x:42.685,h:'6',f:'GND'},{n:7,x:40.145,h:'7',f:'GND'},{n:8,x:40.145,h:'8',f:'GND'},{n:9,x:37.605,h:'9',f:'+3V3'},{n:10,x:37.605,h:'10',f:'+3V3'}];
const labels=pins.flatMap(p=>[{pin:p.n,x:p.x,y:p.n%2?1.15:8.2,text:p.h,size:.65},{pin:p.n,x:p.x,y:p.n%2?2.15:9.2,text:p.f,size:.9}]);
const parse=s=>s.split(/\r?\n/).filter(x=>x.includes('||')).map(x=>{const p=x.indexOf('||');return{h:JSON.parse(x.slice(0,p)),b:JSON.parse(x.slice(p+2).replace(/\|$/,''))};});
const canonical=v=>JSON.stringify(v,(_,q)=>q&&typeof q==='object'&&!Array.isArray(q)?Object.fromEntries(Object.entries(q).sort(([a],[b])=>a.localeCompare(b))):q);
const beforeSource=await eda.sys_FileManager.getDocumentSource(),before=parse(beforeSource),strings=before.filter(r=>r.h.type==='STRING');
if(strings.length!==({first:0,rest:1,title:20})[mode])throw new Error('Unexpected existing native string inventory');
const EPCB_LayerId={BOTTOM_SILKSCREEN:4},EPCB_PrimitiveStringAlignMode={CENTER:5};
const selected=mode==='first'?labels.slice(0,1):mode==='rest'?labels.slice(1):[{pin:null,x:42.685,y:10.5,text:'J18 SPI2',size:.9}],created=[];
for(const l of selected){
 const p=await eda.pcb_PrimitiveString.create(EPCB_LayerId.BOTTOM_SILKSCREEN,l.x/.0254,l.y/.0254,l.text,'default',l.size/.0254,.12/.0254,EPCB_PrimitiveStringAlignMode.CENTER,0,false,0,true,false);
 if(!p)throw new Error('J18 string create failed '+l.text);
 created.push({...l,id:p.getState_PrimitiveId()});
}
const source=await eda.sys_FileManager.getDocumentSource(),after=parse(source),map=new Map(after.map(r=>[r.h.type+':'+r.h.id,r])),errors=[];
for(const r of before)if(!['DOCHEAD','CANVAS','ACTIVE_LAYER'].includes(r.h.type)&&canonical(map.get(r.h.type+':'+r.h.id)?.b)!==canonical(r.b))errors.push({key:r.h.type+':'+r.h.id,error:'protected record changed'});
const actual=created.map(c=>({planned:c,actual:map.get('STRING:'+c.id)}));
if(after.length!==before.length+selected.length)errors.push({error:'record count'});
for(const c of actual){const b=c.actual?.b;if(!b||b.text!==c.planned.text||b.layerId!==EPCB_LayerId.BOTTOM_SILKSCREEN||b.mirror!==true)errors.push({error:'string identity/mirror',...c});}
const path=root+'/output/validation/native-j18-bottom-'+mode+'-20261016.epru';
await eda.sys_FileSystem.saveFileToFileSystem(path,new Blob([source]),undefined,false);
const receipt={mode,path,created:actual,errors,saved:false};
if(!errors.length)receipt.saved=await eda.pcb_Document.save();
await eda.sys_FileSystem.saveFileToFileSystem(root+'/output/validation/native-j18-bottom-'+mode+'-receipt-20261016.json',new Blob([JSON.stringify(receipt,null,2)]),undefined,false);
if(errors.length||!receipt.saved)throw new Error('J18 label preservation failed');
return receipt;
