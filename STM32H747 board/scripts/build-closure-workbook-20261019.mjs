import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {Workbook,SpreadsheetFile}=await import(process.env.PCBA_ARTIFACT_MODULE||'@oai/artifact-tool');
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../output/jlcpcb-closure-20261019');
const read=async name=>JSON.parse(await fs.readFile(path.join(out,name),'utf8'));
const [d,p,r,s,w]=await Promise.all(['order-data.json','closure-plan.json','ROTATION_REVIEW.json','stock/native-supplier-stock-proof.json','WARNING_REVIEW_5.json'].map(read));
const wb=Workbook.create();
const csv=rows=>'\uFEFF'+rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n')+'\r\n';
const summary=wb.worksheets.add('주문 검토');
const rows=[['STM32H747 주문 자료 검토','2026-10-19'],['상태','로컬 검증 완료 / 공장 매칭·제조 승인 대기'],['신규 구매 후보',107],['원본에 반영한 선정 부품',132],['실장 부품/보드',412],['BOM 그룹',69],['Top 실장',333],['Bottom 실장',79],['회전 검토',70],['CPL 회전 수정',59],['엄격 PCB DRC',0],['ERC 경고 그룹',5],['JLC 품번 미확정 기존 부품',139],['구매품 방향 최종 대조',7],['수량','미확정: 웹 견적은 PCB5/실장5 임시'],['재고','2026-10-19 JLCEDA 실장 창고 스냅샷 / 예약 아님'],['필수 후속','로그인, U6 단종품 조달, BOM 매칭, 실장 미리보기·DFM 승인']];
summary.getRangeByIndexes(0,0,rows.length,2).values=rows;summary.getRange('A:A').format.columnWidth=32;summary.getRange('B:B').format.columnWidth=80;summary.getUsedRange().format.wrapText=true;summary.getUsedRange().format.autofitRows();summary.getRange('A1:B1').format.fill='#183E54';summary.getRange('A1:B1').format.font.color='#FFFFFF';summary.getRange('A2:B2').format.fill='#FFF0D1';
const stock=Object.fromEntries(s.map(x=>[x.supplierId,x]));
const selected=p.targets.filter(x=>x.wasProposal).map(x=>({'Designator':x.ref,'Value':x.properties.Value,'Package':x.properties.Package,'MPN':x.properties['Manufacturer Part'],'Manufacturer':x.properties.Manufacturer,'LCSC Part #':x.properties['Supplier Part'],'Tolerance':x.properties.Tolerance,'Dielectric':x.properties.Dielectric??'','Voltage':x.properties['Voltage Rating']??'','TCR':x.properties['Temperature Coefficient']??x.properties.TCR??'','Power':x.properties['Power Rating']??'','JLC SMT stock':stock[x.properties['Supplier Part']].jlcSmtStock,'Review':'Exact MPN saved; custom land preserved; factory match pending'}));
const rotation=r.rows.map(x=>({'Designator':x.ref,'MPN':d.bomParts.find(y=>y.Designator===x.ref)['Manufacturer Part'],'Layer':x.side,'Rotation':x.rotationDegrees,'Pin 1 X':x.pin1?.x??'','Pin 1 Y':x.pin1?.y??'','Catalog linked':x.supplierZeroConfirmed?'Yes':'Purchased-part zero pending','Check':x.review,'Factory action':x.factoryAction}));
const sourcegroups=d.bomGroups.filter(x=>!x['LCSC Part #']||x.Designator.split(',').includes('U6'));
const tables=[
 {name:'BOM JLCPCB',file:'BOM_JLCPCB.csv',headers:['Comment','Designator','Footprint','LCSC Part #','Manufacturer Part','Manufacturer','Quantity'],rows:d.bomGroups},
 {name:'部品 412',file:'PARTS_REVIEW_412.csv',headers:['Designator','Comment','Footprint','Manufacturer Part','Manufacturer','LCSC Part #','Quantity','Status'],rows:d.bomParts},
 {name:'선정 107',file:'PURCHASE_SELECTIONS_107.csv',headers:Object.keys(selected[0]),rows:selected},
 {name:'조달 요청',file:'SOURCING_REVIEW.csv',headers:['Designator','Comment','Footprint','Manufacturer Part','Manufacturer','Quantity','Status'],rows:sourcegroups},
 {name:'회전 검토 70',file:'ROTATION_REVIEW_70.csv',headers:Object.keys(rotation[0]),rows:rotation},
 {name:'CPL 412',file:'CPL_JLCPCB_REVIEW.csv',headers:['Designator','Mid X','Mid Y','Layer','Rotation'],rows:d.cpl},
 {name:'경고 부품 5',file:'WARNING_REVIEW_5.csv',headers:['Designator','MPN','Review','Disposition'],rows:w.originalParts},
 {name:'실장 재고 16',file:'SELECTED_STOCK_16.csv',headers:['MPN','LCSC Part #','Qty per board','LCSC stock','JLC SMT stock','Observed','Reserved'],rows:s.map(x=>({'MPN':x.mpn,'LCSC Part #':x.supplierId,'Qty per board':x.qtyPerBoard,'LCSC stock':x.lcscStock??'Unknown','JLC SMT stock':x.jlcSmtStock,'Observed':x.observedDateKST,'Reserved':'No'}))}
];
for(const t of tables){const sh=wb.worksheets.add(t.name),rows=[t.headers,...t.rows.map(r=>t.headers.map(k=>r[k]??''))];sh.getRangeByIndexes(0,0,rows.length,t.headers.length).values=rows;sh.getRangeByIndexes(0,0,1,t.headers.length).format.fill='#183E54';sh.getRangeByIndexes(0,0,1,t.headers.length).format.font.color='#FFFFFF';sh.getUsedRange().format.columnWidth=24;sh.getUsedRange().format.wrapText=true;sh.getUsedRange().format.autofitRows();sh.freezePanes.freezeRows(1);const actual=sh.getRangeByIndexes(0,0,rows.length,t.headers.length).values;if(JSON.stringify(actual)!==JSON.stringify(rows))throw Error('Workbook readback mismatch: '+t.name);await fs.writeFile(path.join(out,t.file),csv(actual));}
const png=await wb.render({sheetName:'주문 검토',range:'A1:B17',scale:1.2,format:'png'});await fs.writeFile(path.join(out,'workbook-preview.png'),new Uint8Array(await png.arrayBuffer()));
await(await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,'JLCPCB_ORDER_REVIEW.xlsx'));
await fs.writeFile(path.join(out,'workbook-verification.json'),JSON.stringify({sheets:tables.length+1,bomGroups:d.bomGroups.length,parts:d.bomParts.length,bomQuantity:d.bomGroups.reduce((n,r)=>n+r.Quantity,0),newSelections:selected.length,rotations:rotation.length,cpl:d.cpl.length,sourcingParts:sourcegroups.reduce((n,r)=>n+r.Quantity,0),allExportedCsvFromReadBackWorksheetValues:true},null,2));
console.log('Workbook and 8 verified CSV files exported.');
