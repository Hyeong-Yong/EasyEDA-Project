"""Validate and package the JLCPCB review handoff; never approves production."""
from pathlib import Path
import json,csv,hashlib,zipfile,collections,html,shutil,sqlite3
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output/jlcpcb-closure-20261019'
load=lambda n:json.loads((OUT/n).read_text(encoding='utf-8-sig'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def table(n):
 with (OUT/n).open(encoding='utf-8-sig',newline='')as f:return list(csv.DictReader(f))
bom=table('BOM_JLCPCB.csv');cpl=table('CPL_JLCPCB_REVIEW.csv');parts=table('PARTS_REVIEW_412.csv');rot=table('ROTATION_REVIEW_70.csv');purchase=table('PURCHASE_SELECTIONS_107.csv');rfq=table('SOURCING_REVIEW.csv')
assert len(bom)==69 and sum(int(x['Quantity'])for x in bom)==412
assert len(cpl)==len(parts)==len({x['Designator']for x in cpl})==412
assert {x['Designator']for x in cpl}=={x['Designator']for x in parts}=={r for x in bom for r in x['Designator'].split(',')}
assert len(rot)==70 and len(purchase)==107 and sum(int(x['Quantity'])for x in rfq)==139
assert collections.Counter(x['Layer']for x in cpl)=={'Top':333,'Bottom':79}
assert all(0<=float(r['Rotation'])<360 and 0<=float(r['Mid X'])<=100 and 0<=float(r['Mid Y'])<=154 for r in cpl)
excluded={'C33','R61','R64','R98','R125','R126'};assert not(excluded&{r['Designator']for r in cpl})
d=load('order-data.json');old={r['Designator']:r for r in d['cplBeforeRotationReview']}
assert all(all(r[k]==old[r['Designator']][k]for k in ['Mid X','Mid Y','Layer'])for r in cpl)
assert sum(float(r['Rotation'])!=float(old[r['Designator']]['Rotation'])for r in cpl)==59
assert load('DURABLE_AUDIT.json')['errors']==[] and load('CAM_AUDIT.json')['allCopperMaskPasteSilkOutlineAndDrillGeometryPreserved']
assert load('native/final/STRICT_DRC_FINAL.json')['violations']==[]
assert all(r['jlcSmtStock']>0 for r in load('stock/native-supplier-stock-proof.json'))
assert load('DELIVERY_STATUS.json')['manufacturingReleaseApproved'] is False
native=ROOT/'native-project/STM32H747_MCU_BOARD_v19.eprj2'
con=sqlite3.connect(native.resolve().as_uri()+'?mode=ro',uri=True)
assert con.execute('pragma quick_check').fetchall()==[('ok',)]
assert con.execute('select uuid,name from projects').fetchall()==[('4d4671fe9a78f6b1578521c2dc6be53db20dc0cc6cb10fdfc81febaa87f5af94','STM32H747_MCU_BOARD_v19')]
con.close()

notes='''STM32H747 - JLCPCB MANUAL MATCH / PLACEMENT REVIEW PACKAGE
2026-10-19 | Per-board quantities. LOCAL REVIEW COMPLETE / FACTORY RELEASE PENDING.

UPLOAD ORDER
1. GERBER_NATIVE.zip -> PCB quotation / CAM review.
2. Select Standard PCBA, Both Sides; use exact manufacturer part numbers.
3. BOM_JLCPCB.csv -> parts matching (69 groups, 412 parts per board).
4. CPL_JLCPCB_REVIEW.csv -> placement review (333 Top, 79 Bottom).
5. Provide ASSEMBLY_PIN1_REVIEW.pdf, SOURCING_REVIEW.csv and this note to factory review.

FACTORY REVIEW REQUIRED BEFORE PRODUCTION
- 139 original parts have no confirmed JLC assembly SKU. Use exact MPN Manual Match or
  qualified Global Sourcing. No substitute, omission or footprint change is approved.
- U6 STS5PF30L is obsolete/out of production per ST. Procurement/substitution decision
  remains pending. Do not place the order with U6 silently excluded.
- CN2, D2, D3, D4, D6, J18, U6: local pin/cathode direction checked, exact purchased-part
  tape zero not asserted. Use numbered-pad drawings and confirm purchased-part preview.
- LED pin 1 = cathode, pin 2 = anode; same mapping in native schematic symbol.
- Y1 nonpolar X-axis, U2 SOT-223 and U6 SO-8 extended hand-solder lands: check contact
  coverage against exact part dimensions and process before assembly.
- J2-J11 left SMA ports CPL90; J12-J15/J17 right CPL270; J16 upper CPL0.
- All CPL XY and sides preserved. Bottom drawing is mirrored for viewing only.
  CPL uses original top-view coordinates. Do not mirror CPL or add another 180 degrees.
- Native all-parts CPL has 437 rows. DO NOT upload CPL_NATIVE.csv as assembly input.
- Excluded: C33, R61, R64, R98, R125, R126 DNP; 19 bare test pads.

PCB / ASSEMBLY SETTINGS FOR FINAL CONFIRMATION
6 layers; finished outline100x154mm. 1.6mm/ENIG/FR4 quotation draft.
Native minimum via hole0.2mm, minimum via pad0.31mm; select matching capability.
Preserve original 6-layer sequence, net planes and impedance-sensitive geometry.
Confirm production files and parts placement = YES. Automatic approvals disabled.
Match mixed SMT/THT assembly.
JLC two5mm edge rails give process outline110x154mm; finished board remains100x154mm.
Confirm depanel service, rail/fiducial placement and connector clearances.
CN1 internal square cutout1.92x1.92mm and diameter1.30mm hole must be preserved.
Keep corner holes and J18 bottom markings. Do not change CAD dimensions for defaults.
Final PCB/PCBA quantity, stackup, DFM and factory production files are unapproved.
Website5PCB/5PCBA is an unconfirmed draft; no payment/order was made.

VERIFIED LOCALLY
Strict PCB DRC0; native ERC fatal0/error0, supplier-property warning5groups remain.
Original5 warning parts R197/R200/R201/R202/R203 have exact reviewed part/spec metadata.
132 selected parts saved in both schematic and PCB;107 newly selected,12 X7R corrections.
70 directional parts checked;59 CPL rotations changed. All copper/mask/paste/silk/
outline/drill manufacturing geometry matches prior verified source.437 physical parts,
704 vias,863 unique physical drills. Stock is a2026-10-19 snapshot, not reserved.

REFERENCES
https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly
https://jlcpcb.com/help/article/pcb-assembly-faqs-part-2
https://jlcpcb.com/help/article/how-to-use-jlcpcb-global-sourcing-parts-service
https://www.st.com/en/power-transistors/sts5pf30l.html
https://www.st.com/resource/en/datasheet/sts5pf30l.pdf
https://www.ndk.com/images/products/catalog/c_NX3215SA_e.pdf
'''
(OUT/'ORDER_NOTES.txt').write_text(notes,encoding='utf-8')
shutil.copyfile(OUT/'native/erc-ui_current.json',OUT/'native/final/ERC_FINAL.json')
files=['native/final/GERBER_NATIVE.zip','BOM_JLCPCB.csv','CPL_JLCPCB_REVIEW.csv','ASSEMBLY_PIN1_REVIEW.pdf','SOURCING_REVIEW.csv','ORDER_NOTES.txt','ORDER_SETTINGS.json','DELIVERY_STATUS.json','PURCHASE_SELECTIONS_107.csv','ROTATION_REVIEW_70.csv','WARNING_REVIEW_5.csv','SELECTED_STOCK_16.csv']
manifest={'purpose':'Factory review package. Not approved for production.','files':[{'file':n,'bytes':(OUT/n).stat().st_size,'sha256':sha(OUT/n)}for n in files],
 'savedNativeSource':{'file':'native/final/STM32H747_JLCPCB_20261019.epro2','sha256':sha(OUT/'native/final/STM32H747_JLCPCB_20261019.epro2')},
 'editableNativeProject':{'file':'../../native-project/STM32H747_MCU_BOARD_v19.eprj2','sha256':sha(ROOT/'native-project/STM32H747_MCU_BOARD_v19.eprj2')}}
(OUT/'FILE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
archive=OUT/'STM32H747_JLCPCB_FACTORY_REVIEW.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED)as z:
 for n in files:z.write(OUT/n,'GERBER_NATIVE.zip'if n.startswith('native/')else n)
 z.write(OUT/'FILE_MANIFEST.json','FILE_MANIFEST.json')
with zipfile.ZipFile(archive)as z:assert z.testzip() is None
validation={'BOMgroups':69,'assemblyParts':412,'newSelections':107,'orientationReviewed':70,'rotationChanges':59,'sourcingParts':139,'Top':333,'Bottom':79,'XYandSidesPreserved':True,'exclusionsPreserved':True,'CSVheadersAndNumbers':'PASS','nativeDatabaseQuickCheck':'PASS','zipCRC':'PASS','archiveSHA256':sha(archive),'productionApproved':False}
(OUT/'PACKAGE_VALIDATION.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')

esc=lambda x:html.escape(str(x))
def tr(values):return '<tr>'+''.join('<td>'+esc(x)+'</td>'for x in values)+'</tr>'
warnings=load('WARNING_REVIEW_5.json')
warnrows=''.join(tr([x['Designator'],x['MPN'],x['Review']])for x in warnings['originalParts'])
stockrows=''.join(tr([x['mpn'],x['supplierId'],x['qtyPerBoard'],f"{x['jlcSmtStock']:,}",'예약 안 됨'])for x in load('stock/native-supplier-stock-proof.json'))
rotrows=''.join(tr([x['Designator'],x['MPN'],x['Rotation'],x['Catalog linked'],x['Factory action']])for x in rot)
rfqrows=''.join(tr([x['Designator'],x['Manufacturer Part'],x['Quantity'],x['Footprint']])for x in rfq)
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>STM32H747 JLCPCB 주문 검토</title>
<style>:root{font-family:Segoe UI,Malgun Gothic,sans-serif;color:#183e54;background:#edf2f5}body{max-width:1200px;margin:auto;padding:36px}header{background:#183e54;color:white;padding:32px;border-radius:15px}h1{font-size:30px;margin:8px 0}h2{font-size:22px;margin-top:36px}.muted{color:#647681}header .muted{color:#bfd5e0}.notice{padding:20px;background:#fff1d9;border-left:5px solid #bc7720;border-radius:8px;line-height:1.8}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:20px 0}.card{padding:22px;background:white;border-radius:10px}.number{font-size:32px;font-weight:700;color:#176f98}a{color:#12678d}nav{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}nav a{background:#fff;padding:13px;border-radius:7px;text-decoration:none;border:1px solid #c8d9e2}table{border-collapse:collapse;width:100%;background:white;font-size:13px}td,th{text-align:left;padding:12px;border-bottom:1px solid #dde7ec;vertical-align:top}th{background:#dae8ef;position:sticky;top:0}.scroll{overflow:auto;max-height:520px;border-radius:8px}li{margin:10px 0;line-height:1.7}section{margin:25px 0}details{background:#fff;padding:18px;border-radius:9px;margin:18px 0}summary{font-weight:700;cursor:pointer}img{max-width:100%;border:1px solid #ccdbe3;border-radius:7px}code{font-size:12px;word-break:break-all}@media(max-width:800px){body{padding:15px}.cards{grid-template-columns:repeat(2,1fr)}}input{padding:11px;width:95%;margin:15px 0;border:1px solid #b8cedb;border-radius:6px}</style>
<header><div class="muted">STM32H747 · 2026-10-19</div><h1>JLCPCB 주문 자료 검토</h1><p>신규 품번과 회전을 원본·카탈로그·제조 파일로 대조했습니다.</p></header>
<div class="cards"><div class="card"><div class="number">107</div>신규 구매 후보 선정</div><div class="card"><div class="number">70</div>핀·극성·방향 대조</div><div class="card"><div class="number">59</div>CPL 회전 수정</div><div class="card"><div class="number">412</div>보드당 실장 부품</div></div>
<div class="notice"><b>로컬 자료 검증 완료 · 공장 매칭 및 제조 승인 대기</b><br>기존 부품 139개는 JLC 실장 품번 매칭이 필요합니다. U6(STS5PF30L)는 단종품으로 조달 방침이 미확정입니다. 기존 조달품 7개는 실제 구매품 방향을 최종 대조해야 합니다. 로그인·부품 매칭·미리보기·DFM을 마치기 전에는 생산을 승인하지 마세요.</div>
<nav><a href="STM32H747_JLCPCB_FACTORY_REVIEW.zip">공장 검토용 파일 묶음</a><a href="JLCPCB_ORDER_REVIEW.xlsx">전체 검토표</a><a href="ASSEMBLY_PIN1_REVIEW.pdf">핀 1·조립도 8페이지</a><a href="native/final/GERBER_NATIVE.zip">Gerber ZIP</a><a href="BOM_JLCPCB.csv">BOM</a><a href="CPL_JLCPCB_REVIEW.csv">수정 CPL</a><a href="SOURCING_REVIEW.csv">미확정 조달표</a></nav>
<h2>검토 결과</h2><ul><li>132개 선정 부품의 품번·정격을 회로도와 PCB에 저장했습니다. 이번에 107개를 새로 확정했고, 커패시터 12개는 X5R 후보를 X7R 사양의 실제 품번으로 수정했습니다. 이번 작업에서 회로 명목값은 바꾸지 않았습니다.</li><li>엄격 PCB DRC 0건, ERC 치명·오류 0건입니다. 공급사 라이브러리와 기존 사용자 정의 심볼·풋프린트의 차이로 <b>ERC 경고 5그룹은 남아 있습니다.</b> 5부품 경고를 모두 제거한 것으로 표현하지 않습니다.</li><li>27종 카탈로그 풋프린트와 63개 부품을 연결 대조했습니다. 나머지 CN2·D2·D3·D4·D6·J18·U6는 실제 핀·극성 방향을 대조했고, 구매품의 테이프 기준 회전은 공장 확인 대상으로 표시했습니다.</li><li>SMA: 좌측 J2~J11은 90°, 우측 J12~J15/J17은 270°, 상단 J16은 0°입니다. 동일한 3D 모델의 카탈로그 기준 방향과 대조했습니다. CPL의 위치와 실장 면은 유지했습니다.</li><li>새 Gerber의 구리·마스크·페이스트·실크·외곽·드릴 도형이 기존 검증본과 같습니다. 6층, 437개 물리 부품, 704비아, 863개 물리 드릴을 보존했습니다.</li></ul>
<h2>기존 경고 부품 5개</h2><div class="scroll"><table><thead><tr><th>부품</th><th>정확 품번</th><th>정격·검토</th></tr></thead><tbody>WARNROWS</tbody></table></div><p class="muted">품번과 정격의 대조 결과이며, 사용자 정의 라이브러리 경고를 없앴다는 뜻은 아닙니다. R201의 400 ppm/K는 앞선 회로 검토에 반영되어 있습니다.</p>
<h2>주문 순서</h2><ol><li>Gerber ZIP을 올리고 완성 크기 100×154 mm, 6층을 확인합니다. 최소 비아 홀은 0.2 mm, 최소 비아 패드는 약 0.31 mm입니다.</li><li>Standard PCBA · Both Sides를 선택합니다. 공정 레일 5 mm씩을 붙이면 공정 크기는 110×154 mm가 됩니다. 두께 1.6 mm·ENIG는 견적 초안으로, 기존 적층 순서와 DFM을 공장에 확인합니다.</li><li>BOM을 업로드하고 정확한 제조사 품번으로 매칭합니다. 미확정 139개는 Manual Match/Global Sourcing으로 확인합니다. U6는 임의 제외·대체하지 않습니다.</li><li>수정 CPL과 조립도를 올리고 핀 1·극성·SMA 포트·수동 삽입 방향을 확인합니다. Y1/U2/U6의 기존 확장 패드 접촉 면적을 DFM에서 확인합니다.</li><li>Confirm Production File과 Confirm Parts Placement를 켜고 공장 자료를 확인합니다. 최종 수량을 정한 뒤 승인·결제합니다. 웹의 PCB5/실장5는 임시 견적이며 주문은 제출하지 않았습니다.</li></ol>
<p>보드당 BOM 69그룹·412개 = Top333 + Bottom79. DNP 6개(C33/R61/R64/R98/R125/R126)와 베어 테스트 패드 19개는 제외했습니다. <b>437행의 native CPL은 실장 입력 파일로 쓰지 마세요.</b></p>
<details><summary>선정 부품 16종 · JLC 실장 재고 스냅샷</summary><p>2026-10-19 JLCEDA의 LCSC Stock/SMT Stock 중 SMT 열을 확인했습니다. 재고 예약과 공장 매칭 승인은 별도입니다.</p><div class="scroll"><table><thead><tr><th>MPN</th><th>JLC/LCSC 코드</th><th>보드당 수량</th><th>JLC 실장 재고</th><th>상태</th></tr></thead><tbody>STOCKROWS</tbody></table></div></details>
<details><summary>70개 방향 검토</summary><input placeholder="부품 번호·품번으로 검색" oninput="filterRows(this,'rotation')"><div class="scroll"><table id="rotation"><thead><tr><th>부품</th><th>품번</th><th>CPL 회전</th><th>기준</th><th>공장 최종 확인</th></tr></thead><tbody>ROTROWS</tbody></table></div></details>
<details><summary>139개 기존 부품 · 미확정 조달 그룹</summary><div class="scroll"><table><thead><tr><th>레퍼런스</th><th>정확 품번</th><th>보드당 수량</th><th>패키지</th></tr></thead><tbody>RFQROWS</tbody></table></div></details>
<h2>검증 근거</h2><nav><a href="DURABLE_AUDIT.json">CAD 보존 대조</a><a href="CAM_AUDIT.json">제조 도형 대조</a><a href="ROTATION_REVIEW.json">핀 방향 근거</a><a href="native/final/STRICT_DRC_FINAL.json">최종 DRC</a><a href="native/final/ERC_FINAL.json">최종 ERC</a><a href="PACKAGE_VALIDATION.json">파일 수량 검증</a><a href="FILE_MANIFEST.json">파일 해시</a><a href="ORDER_NOTES.txt">공장 전달 메모</a><a href="native/final/STM32H747_JLCPCB_20261019.epro2">전체 원본 복구본</a></nav>
<p class="muted">JLC 부품 매칭·실장 미리보기는 로그인이 필요해 미완료입니다. 사용자에게 로그인과 U6 조달 선택을 요청한 상태입니다. TEST_DAC8562 자료는 이번 변경 범위에 포함하지 않았습니다.</p>
<details><summary>JLCPCB에서 확인한 업로드·설정 초안</summary><p>6층·154×100 mm 인식 화면과 0.2 mm 비아·제조 파일 확인 요청 화면입니다. 제조 파일·실장 방향 확인 요청을 켜고 자동 승인을 해제했습니다. BOM 매칭·실장 가격·공장 승인까지 완료한 화면은 아닙니다.</p><img src="jlcpcb-quote-draft.png" alt="JLCPCB Gerber 업로드 초안"><img src="jlcpcb-settings-draft.png" alt="JLCPCB 제조 확인 요청 및 비아 설정 초안"></details>
<p><a href="https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly">JLCPCB CPL 안내</a> · <a href="https://jlcpcb.com/help/article/pcb-assembly-faqs-part-2">JLCPCB 방향·재고 안내</a> · <a href="https://www.st.com/en/power-transistors/sts5pf30l.html">ST 단종 상태</a> · <a href="https://www.ndk.com/images/products/catalog/c_NX3215SA_e.pdf">NDK 치수 자료</a></p>
<script>function filterRows(input,id){const q=input.value.toLowerCase();document.querySelectorAll('#'+id+' tbody tr').forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(q))}</script></html>'''
for key,value in [('WARNROWS',warnrows),('STOCKROWS',stockrows),('ROTROWS',rotrows),('RFQROWS',rfqrows)]:page=page.replace(key,value)
(OUT/'index.html').write_text(page,encoding='utf-8')
print(json.dumps(validation))
