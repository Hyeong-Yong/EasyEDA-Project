import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {Workbook,SpreadsheetFile}=await import(process.env.PCBA_ARTIFACT_MODULE||'@oai/artifact-tool');
const out=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../output/standard-values-20261019');
const read=async name=>JSON.parse(await fs.readFile(path.join(out,name),'utf8'));
const [data,groups,analysis]=await Promise.all(['review-data.json','resistor-table.json','circuit-review.json'].map(read));
const wb=Workbook.create(),s=wb.worksheets.add('저항 검토');
s.getRange('A1:J1').merge();s.getRange('A1').values=[['STM32H747 표준 저항 검토 — 제조·실장 승인 전']];
s.getRange('A2:J2').merge();s.getRange('A2').values=[['25개 품번 적용 · 13개 값 변경 · 나머지 신규 107개 품번은 구매 후보입니다.']];
s.getRange('A3:J3').merge();s.getRange('A3').values=[['엄격 PCB DRC 0 · ERC 오류 0 / 공급사 속성 경고 1그룹(5개) · 복합/극성 70개 회전 확인 필요']];
s.getRange('A4:J4').merge();s.getRange('A4').values=[['재고: 2026-10-19 LCSC 공개 페이지 확인 수치. 예약·JLC 실장 재고 확보가 아닙니다. R201은 카탈로그 400 ppm/K로 계산했습니다.']];
const gh=['Refs','Qty/board','Before','After','Tolerance','TCR','Power','Package','MPN','LCSC','Stock','Stock date','Source','Status'];
const gr=[gh,...groups.map(g=>gh.map(k=>g[k]))];s.getRangeByIndexes(5,0,gr.length,gh.length).values=gr;
s.getRange('A1:J1').format.fill='#17455C';s.getRange('A1:J1').format.font.color='#FFFFFF';s.getRange('A3:J4').format.fill='#FFF1DC';
s.getRangeByIndexes(5,0,1,gh.length).format.fill='#DDEAF3';s.getUsedRange().format.columnWidth=19;s.getRange('A:A').format.columnWidth=45;s.getRange('I:I').format.columnWidth=33;s.getRange('M:N').format.columnWidth=48;s.getUsedRange().format.wrapText=true;s.getUsedRange().format.autofitRows();s.freezePanes.freezeRows(6);
const csv=rows=>'\uFEFF'+rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n')+'\r\n';
await fs.writeFile(path.join(out,'STANDARD_RESISTORS_REVIEW.csv'),csv(s.getRangeByIndexes(5,0,gr.length,gh.length).values));
const tables=[
 {name:'BOM 후보',file:'BOM_CANDIDATE_REVIEW_ONLY.csv',headers:['Comment','Designator','Footprint','Manufacturer Part','Manufacturer','LCSC Part #','Quantity','Status'],rows:data.candidateBom},
 {name:'기타 구매 후보',file:'OTHER_PARTS_PROPOSALS.csv',headers:['Designator','Specified value','Tolerance','Voltage','TCR','Package','Proposed MPN','LCSC Part #','Manufacturer','Evidence','Approval'],rows:data.proposedParts}
];
for(const t of tables){const sh=wb.worksheets.add(t.name),rows=[t.headers,...t.rows.map(r=>t.headers.map(k=>r[k]??''))];sh.getRangeByIndexes(0,0,rows.length,t.headers.length).values=rows;sh.getRangeByIndexes(0,0,1,t.headers.length).format.fill='#17455C';sh.getRangeByIndexes(0,0,1,t.headers.length).format.font.color='#FFFFFF';sh.getUsedRange().format.columnWidth=23;sh.getUsedRange().format.wrapText=true;sh.getUsedRange().format.autofitRows();sh.freezePanes.freezeRows(1);const actual=sh.getRangeByIndexes(0,0,rows.length,t.headers.length).values;if(JSON.stringify(rows)!==JSON.stringify(actual))throw Error('Table readback mismatch '+t.name);await fs.writeFile(path.join(out,t.file),csv(actual));}
const c=wb.worksheets.add('회로 비교');
c.getRange('A1:D12').values=[['명목 비교','기존','선정값','단위'],['입력 저항',4000,4020,'Ω'],['피드백 저항',2800,2800,'Ω'],['분압 상단',15800,14700,'Ω'],['분압 하단',10000,9310,'Ω'],['REF5025',2.5,2.5,'V'],['이득 크기','','','V/V'],['0 V 입력 출력','','','V'],['−2 V 입력 출력','','','V'],['0 V 입력 출력','','','V'],['+2 V 입력 출력','','','V'],['합성 −3 dB 대역',analysis.before.normalized3dBBandwidthHz,analysis.after.normalized3dBBandwidthHz,'Hz (외부 해석)']];
c.getRange('B7:C11').formulas=[['=B3/B2','=C3/C2'],['=B6*B5/(B4+B5)*(1+B7)','=C6*C5/(C4+C5)*(1+C7)'],['=B8+2*B7','=C8+2*C7'],['=B8','=C8'],['=B8-2*B7','=C8-2*C7']];
c.getRange('A15:D16').values=[['이득 크기 변화','','','%'],['영점 출력 변화','','','mV']];c.getRange('C15:C16').formulas=[['=(C7/B7-1)*100'],['=(C8-B8)*1000']];
c.getRange('A19:D19').merge();c.getRange('A19').values=[['이상적인 증폭기·명목 커패시터의 저항 비교입니다. 실측 잡음·기동·전체 ADC 오차 또는 제조 승인이 아닙니다. VIN은 실제 SMA 전압입니다.']];
c.getRange('A1:D1').format.fill='#17455C';c.getRange('A1:D1').format.font.color='#FFFFFF';c.getRange('A:A').format.columnWidth=29;c.getRange('B:C').format.columnWidth=24;c.getRange('D:D').format.columnWidth=25;c.getUsedRange().format.wrapText=true;c.getRange('B7:C16').setNumberFormat('0.000000');c.getUsedRange().format.autofitRows();
wb.recalculate();const gain=c.getRange('C7').values[0][0],zero=c.getRange('C8').values[0][0];
if(typeof gain!=='number'||Math.abs(gain+analysis.after.dcSignalGainAtSma)>1e-12||Math.abs(zero-analysis.after.zeroInputOutputV)>1e-12)throw Error('Calculated comparison mismatch');
const preview=await wb.render({sheetName:'회로 비교',range:'A1:D19',scale:1,format:'png'});await fs.writeFile(path.join(out,'workbook-preview.png'),new Uint8Array(await preview.arrayBuffer()));
const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(path.join(out,'STANDARD_VALUES_REVIEW.xlsx'));
await fs.writeFile(path.join(out,'workbook-verification.json'),JSON.stringify({sheets:4,bomRows:data.candidateBom.length,proposalRows:data.proposedParts.length,formulaGain:gain,formulaZeroV:zero,candidateMissingMpn:data.candidateBom.filter(r=>!r['Manufacturer Part']).length},null,2));
console.log(JSON.stringify({file:path.join(out,'STANDARD_VALUES_REVIEW.xlsx'),bomRows:data.candidateBom.length,proposalRows:data.proposedParts.length,gain,zero}));
