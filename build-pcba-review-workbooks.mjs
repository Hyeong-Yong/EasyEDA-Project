import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const { Workbook, SpreadsheetFile } = await import(process.env.PCBA_ARTIFACT_MODULE || '@oai/artifact-tool');

const root=path.dirname(fileURLToPath(import.meta.url));
const folders=['STM32H747 board','TEST_DAC8562'];
const results=[];
const csv=rows=>'\uFEFF'+rows.map(row=>row.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\r\n')+'\r\n';
for(const folder of folders){
  const out=path.join(root,folder,'output/jlcpcb-20261019-review');
  const data=JSON.parse(await fs.readFile(path.join(out,'review-data.json'),'utf8'));
  const wb=Workbook.create();
  const status=wb.worksheets.add('Read first');
  const notice=[['PCBA preparation review — NOT FOR ORDER'],['Board',data.summary.board],['Source checkpoint',data.summary.source],['Source SHA256',data.summary.sourceSHA256],['All physical parts',data.summary.physicalParts],['Assembly candidates',data.summary.assemblyParts],['Excluded',data.summary.excluded],['BOM groups',data.summary.bomGroups],['Exact MPN missing in CAD',data.summary.noExactMpn],['CAD LCSC IDs missing',data.summary.noLcscMatch],['New MPN proposals',data.summary.proposedNewMpnParts],['Remaining unresolved',data.summary.unresolvedAfterProposals],[],['RELEASE HOLDS'],...data.summary.holds.map(x=>[x]),[],['Placement qualification',data.summary.placementQualification],['Procurement qualification',data.summary.stockQualification]];
  const width=2;status.getRangeByIndexes(0,0,notice.length,width).values=notice.map(r=>[r[0]??'',r[1]??'']);
  status.getRange('A1:B1').merge();status.getRange('A1').values=[['PCBA REVIEW — NOT FOR ORDER']];
  status.getRange('A1:B1').format.fill='#9C2323';status.getRange('A1:B1').format.font.color='#FFFFFF';
  status.getRange('A:A').format.columnWidth=34;status.getRange('B:B').format.columnWidth=105;
  for(let i=14;i<14+data.summary.holds.length;i++){status.getRangeByIndexes(i,0,1,2).merge();}
  status.getUsedRange().format.wrapText=true;status.getUsedRange().format.autofitRows();
  const tables=[
    {name:'BOM',file:'BOM_REVIEW.csv',rows:data.bom,headers:['Comment','Designator','Footprint','Quantity','Manufacturer Part','Manufacturer','LCSC Part #','Review status']},
    {name:'Placement source',file:'PLACEMENT_SOURCE_NOT_CPL.csv',rows:data.sourceCoordinates,headers:['Designator','Source X (mm)','Source Y (mm)','Layer','Source angle (deg)','Qualification']},
    {name:'Excluded',file:'EXCLUDED.csv',rows:data.parts.filter(p=>p.excluded).map(p=>({Designator:p.ref,Value:p.value,Reason:p.exclusion_reason})),headers:['Designator','Value','Reason']},
    {name:'Procurement',file:'PROCUREMENT_REVIEW.csv',rows:data.parts.filter(p=>!p.excluded).map(p=>({Designator:p.ref,Value:p.value,Package:p.package,MPN:p.mpn,Manufacturer:p.manufacturer,'LCSC Part #':p.lcsc,'Tolerance':p.tolerance,'Voltage':p.voltage,'TCR':p.tcr,Notes:p.notes||'Stock and supplier package mapping not verified'})),headers:['Designator','Value','Package','MPN','Manufacturer','LCSC Part #','Tolerance','Voltage','TCR','Notes']},
    {name:'BOM candidate',file:'BOM_CANDIDATE.csv',rows:data.candidateBom,headers:['Comment','Designator','Footprint','Manufacturer Part','Manufacturer','LCSC Part #','Quantity','Status']},
    {name:'Proposed parts',file:'PROPOSED_PARTS.csv',rows:data.proposedParts,headers:['Designator','Specified value','Tolerance','Voltage','TCR','Package','Proposed MPN','LCSC Part #','Manufacturer','Evidence','Approval']},
    {name:'Unresolved',file:'UNRESOLVED_PARTS.csv',rows:data.unresolvedParts,headers:['Designator','Value','Package','Tolerance','TCR','Reason']}
  ];
  for(const table of tables){
    const sheet=wb.worksheets.add(table.name);
    const rows=[table.headers,...table.rows.map(o=>table.headers.map(h=>o[h]??''))];
    sheet.getRangeByIndexes(0,0,rows.length,table.headers.length).values=rows;
    sheet.getRangeByIndexes(0,0,1,table.headers.length).format.fill='#183C55';
    sheet.getRangeByIndexes(0,0,1,table.headers.length).format.font.color='#FFFFFF';
    sheet.freezePanes.freezeRows(1);sheet.getUsedRange().format.columnWidth=22;
    sheet.getUsedRange().format.wrapText=true;sheet.getUsedRange().format.autofitRows();
    if(table.name==='BOM'){sheet.getRange('B:B').format.columnWidth=68;sheet.getRange('D:D').setNumberFormat('0');}
    if(table.name==='Placement source'){sheet.getRange('B:C').setNumberFormat('0.000000');sheet.getRange('F:F').format.columnWidth=40;}
    if(table.name==='Procurement')sheet.getRange('J:J').format.columnWidth=60;
    const actual=sheet.getRangeByIndexes(0,0,rows.length,table.headers.length).values;
    if(JSON.stringify(actual)!==JSON.stringify(rows))throw Error('Workbook data mismatch '+table.name);
    // CSV sidecars are serialized from the authored/verified worksheet values.
    await fs.writeFile(path.join(out,table.file),csv(actual),'utf8');
  }
  wb.recalculate();
  const preview=await wb.render({sheetName:'Read first',autoCrop:'all',scale:1,format:'png'});
  await fs.writeFile(path.join(out,'workbook-preview.png'),new Uint8Array(await preview.arrayBuffer()));
  const check=await wb.inspect({kind:'sheet',include:'id,name',maxResults:8});
  await fs.writeFile(path.join(out,'workbook-inspection.json'),JSON.stringify(check,null,2));
  const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(path.join(out,'PCBA_REVIEW.xlsx'));
  results.push({board:data.summary.board,rows:data.summary.assemblyParts,file:path.join(out,'PCBA_REVIEW.xlsx')});
}
console.log(JSON.stringify(results));
