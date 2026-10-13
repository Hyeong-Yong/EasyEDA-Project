"""Publish completed review and explicit fabrication holds; never imply clean release."""
import hashlib,html,json,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/manufacturing-preflight'
read=lambda p:json.loads(p.read_text(encoding='utf8'))
audit=read(out/'preflight-audit.json');bom=read(out/'BOM-confirmed.json');sch=read(out/'native-validation.json');pcb=read(out/'pcb-restored-rule.json')
physical=read(out/'physical-pcb-audit.json');dfm=read(out/'cam-dfm-final.json');features=read(out/'dfm-native-features.json')
dfm['referenceGerber']=str(out/'DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber_DFM.zip')
(out/'cam-dfm-final.json').write_text(json.dumps(dfm,indent=2),encoding='utf8')
processing=read(out/'gerber-dfm-processing.json')
processing.update(input='DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber.zip',output='DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber_DFM.zip')
(out/'gerber-dfm-processing.json').write_text(json.dumps(processing,indent=2),encoding='utf8')
startup=read(root/'simulation/startup/summary-startup-only.json');mixed=read(root/'simulation/startup/summary.json');checkpoint=read(out/'checkpoint-proof.json')
assert sch['pages'][0]['details']==[{'type':'warn','count':1}]
assert len(pcb['details'])==1 and pcb['details'][0]['name']=='Netlist Error' and pcb['details'][0]['count']==1
assert physical['padNetDifferences']==[{'pin':'R102.1','schematic':['$2N434'],'pcb':'MCU_RECEIVE_A'}]
assert not physical['copperShorts'] and not physical['disconnectedNets']
assert not dfm['soldermaskBridgesBelow01mm'] and len(startup['ldoSolverFailures'])==0 and len(startup['ldoScreenFailures'])==0
limitations=[
 'R102.1 미연결은 사용자 요청으로 수정하지 않았습니다. 회로도 ERC Warning 1건 및 PCB Netlist Error 1건이 남아 있으므로 제작 보류입니다.',
 'U3 솔더마스크는 API 편집 화면/현재 Gerber에서는 1mil로 수정되지만 저장 프로젝트 export의 풋프린트 PAD는 2.008mil을 유지했습니다. 마스크 수정의 CAD 저장은 완료하지 못했습니다. 편집 화면 소스와 실제 export를 대조해 발견한 제한이며, 재생성하면 좁은 간격이 재발할 수 있습니다. CAD 풋프린트에서 10개 패드 상면 확장을 0.0254mm로 저장한 뒤 새 Gerber 재검사가 필요합니다.',
 '현재 검토용 Gerber는 0.10mm 미만 마스크 브리지 0곳입니다. 프로젝트 저장 재현성 문제가 있어 제작 승인 Gerber가 아니며 주문에 사용하지 마십시오.',
 'PCB 부품 번호 실크는 0.762mm로 제조사 권장 1mm보다 작습니다. 실크 패드 간격은 보정했지만 작은 글자는 일부 잘릴 수 있습니다. 제조사 실크 검토 및 조립 참조도가 필요합니다.',
 '마스크 개구와 이웃 네트 트랙의 소유권별 검사, 전체 스텐실/실장 DFM, SMA 케이블·기구물 3D 간섭은 승인하지 않았습니다. 제조사 서버에 업로드하거나 주문하지 않았습니다.',
 'Q2 2N7002P,215는 Nexperia Not For Design In(NRND) 상태입니다. 단종 확인과는 다르며 이번 시제품 BOM에는 유지했습니다. 지속 생산용이면 대체품 조달 검토가 남습니다.',
 '수동 조달되는 Susumu/YAGEO/Samtec 부품은 정확한 설계 MPN을 선택했지만 재고 예약, 납기, 가격, 실장업체 승인까지 확정한 것은 아닙니다.',
 'TPS65131의 공식 스위칭 모델을 제조사 제공 목록에서 찾지 못했습니다. 인덕터 포화/실제 리플/입력 돌입/열/MLCC DC-bias를 포함한 전체 전원 기동 보증은 하지 않습니다.',
 '전원 하강·브라운아웃 27건 중 7건은 TI 모델 UVLO 불연속에서 수렴 실패했습니다. 성공으로 집계하지 않았고 종료 시 출력 무글리치를 보증하지 않습니다.',
 'PGOOD은 DAC 초기화 완료 신호가 아닙니다. 전원 정상 확인 후 mute 상태에서 SPI/DAC 초기화·안정화를 완료하고 출력 enable을 켜야 하며, PGOOD 하강 시 enable을 내리고 회복 때 재초기화해야 합니다. 릴레이/플라이백 다이오드의 지연과 바운스는 모델링하지 않았습니다.',
 '이전 아날로그 58건 시뮬레이션은 R102가 의도대로 연결된 회로를 전제로 합니다. 현재 미연결 회로의 입력 탈락 동작 검증 결과로 사용할 수 없습니다. 측정·보정·케이블 안정성·기동/종료 실측은 이번 범위에서 제외했습니다.'
]
report={'date':'2026-10-13','reviewCompleted':True,'fabricationReleased':False,'status':'Review checkpoint; fabrication HOLD',
 'parts':154,'symbolInstances':158,'bomGroups':53,'schematicGlobalWarnings':1,'schematicErrors':0,'pcbNetlistErrors':1,'otherNativePcbDrcGroups':0,
 'protectedR102NotChanged':True,'physicalCopperShorts':0,'physicalCopperDisconnectedNets':0,
 'startupOnlyCases':24,'startupOnlySolverPasses':24,'startupOnlyRangePasses':24,'startupPeakAvddV':startup['maximumAvddV'],
 'combinedCases':27,'combinedSolverFailures':mixed['ldoSolverFailures'],
 'ldoSupplyAssumptions':'Ideal prescribed 0.1/1/10/100ms input ramps; 2/10/20mA resistive output loads; COUT factor 0.5/1, CNR 10nF, CFF 10nF. TI model VREF 1.192V retained, distinct from datasheet typical 1.185V.',
 'panelDecision':'Single 100x100mm, 2 layers; no panel copies or mouse-bites, Panel1 unchanged','checkpoint':checkpoint,'limitations':limitations,
 'sources':{'manufacturing':'https://jlcpcb.com/capabilities/pcb-','ldo':'https://www.ti.com/product/TPS7A49','model':'https://www.ti.com/lit/zip/sbvm528','dcDc':'https://www.ti.com/product/TPS65131','header':'https://suddendocs.samtec.com/prints/ssw-d.pdf','precisionResistors':'https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf','q2':'https://www.nexperia.com/product/2N7002P'}}
(out/'review-summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
note='''FABRICATION HOLD / 제작 보류 — 2026-10-13
This is a DFM REFERENCE ONLY, NOT AN APPROVED ORDER ZIP.
R102.1 remains intentionally unmodified/unconnected at the user's instruction.
Native ERC has 1 warning and PCB has 1 schematic-netlist mismatch.
U3 mask edits appear in this reference CAM but did not persist in the project's
exported footprint PAD definitions. Regeneration may restore the 8 close gaps.
The exact CAD footprint must be fixed, saved and regenerated before fabrication.
Native top-CAM pad generation also has micron-level rounding differences; the
native copper master records were not edited. See review-summary and CAM proof.
Silkscreen ref text 0.762mm is below the manufacturer's 1mm recommendation.
Manufacturer DFM / assembler approval / procurement stock are not confirmed.
Combined PTH contains vias; Via-only DRL is redundant, not a second drill pass.
Do not order from this ZIP. Use the reviewed, regenerated, synchronized release.
'''
(out/'READ_BEFORE_FABRICATION.txt').write_text(note,encoding='utf8')
target=out/'DFM_REFERENCE_ONLY_NOT_FOR_FABRICATION.zip'
if not target.exists():
 with zipfile.ZipFile(out/'DAC8562_RUNTIME_MASK_REFERENCE_ONLY_Gerber_DFM.zip') as src,zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as dst:
  for n in src.namelist():dst.writestr(n,src.read(n))
  dst.writestr('READ_BEFORE_FABRICATION.txt',note)
e=lambda v:html.escape(str(v if v is not None else ''))
css='body{font:16px/1.65 "Malgun Gothic",sans-serif;max-width:1160px;margin:40px auto;padding:0 24px;color:#23364a}h1,h2{line-height:1.3}h2{margin-top:32px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #d5dde4;padding:7px;text-align:left;vertical-align:top}th{background:#eaf0f4}a{color:#176aa1}.hold{padding:18px;background:#fff2db;border-left:5px solid #bd5c00}img{max-width:100%;border:1px solid #dae1e7}li{margin:8px 0}'
rows=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in [', '.join(p['refs']),p['quantity'],p['value'],p['manufacturer'],p['manufacturerPart'],p['supplierPart'] or '수동 조달',p['tolerance'],p['footprintName'],' / '.join(p['notes'])])+'</tr>' for p in bom['grouped'])
(out/'BOM-confirmed.html').write_text(f'<!doctype html><html lang="ko"><meta charset="utf-8"><title>확정 설계 BOM</title><style>{css}</style><h1>확정 설계 BOM: 154개 / 53그룹</h1><p>정확한 제조사 MPN과 패키지 기준입니다. 재고 예약·주문·실장 승인은 아닙니다. 다중 유닛 심볼 158개를 중복 합산하지 않았습니다. 수동 조달 저항에 표시된 범용 라이브러리 부품을 대신 주문하지 마십시오.</p><p>J1: Samtec SSW-105-02-G-D. 정밀 저항 100k/10k는 실제 주문코드 RG1608N-104-W-T5 / RG1608N-103-W-T5로 정리했습니다. 저항값과 출력 변환 이득은 그대로입니다. R30/R34는 확인 가능한 115k/261k 주문 부품으로 바꿔 PG 하한 명목값은 AVDD 5.00V / 음전원 크기 10.84V입니다. Q2는 NRND이며 이번 시제품에는 유지했습니다.</p><table><tr>'+''.join('<th>'+x+'</th>' for x in ['위치','수량','값','제조사','MPN','LCSC/조달','허용오차','풋프린트','주의'])+'</tr>'+rows+'</table></html>',encoding='utf8')
links='<a href="BOM-confirmed.html">확정 설계 BOM</a> · <a href="BOM-confirmed.json">BOM 데이터</a> · <a href="review-summary.json">검토 결과 데이터</a>'
limits=''.join('<li>'+e(x)+'</li>' for x in limitations)
text=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>제작 전 검토 — 제작 보류</title><style>{css}</style>
<h1>DAC8562 / DAC_MCU 제작 전 검토</h1><p>2026-10-13 · 원본 DAC8562 module의 Page 1 / Page 2 · Board1, 100×100mm 2층</p>
<div class="hold"><b>검토 결과 정리 / 제작 보류</b><br>회로도 ERC: Error 0, Warning 1. PCB: Netlist Error 1, 그 외 Native DRC 오류 그룹 0. R102는 요청대로 수정하지 않았습니다. 마스크 CAD 저장 재현성도 해결되지 않아 제작 승인본이 아닙니다.</div>
<h2>질문 1–3의 답변</h2><p><b>1.</b> +5.214V LDO는 OUT–R22/C27–FB–R23와 출력/NR 커패시터를 직접 와이어로 정리했습니다. IN/EN은 같은 VPOS12이고 NR과의 교차에는 접속점이 없습니다. 전기적 핀 네트는 유지했습니다.</p>
<p><b>2.</b> R102 아래 핀은 MCU_VBIAS이지만 윗핀은 MCU_RECEIVE_A가 아니라 독립 자동 네트 <code>$2N434</code>입니다. 따라서 현재 그 10MΩ 경로는 연결되지 않았습니다. 점 색만으로 모든 교차를 판단하지 말고 핀 네트로 확인해야 합니다. 이 경우 회색 T점은 실제 미연결입니다. 사용자 요청대로 이 분기는 변경하지 않았습니다.</p>
<p><b>3.</b> 업로드된 한 핀 네트 경고를 일괄 무시하면 안 됩니다. 실제 누락된 SPI/MCU 분기의 네트 연결은 복구했고 R102 한 건만 유지했습니다. 전체 핀 네트를 이전 검증본과 대조한 결과 R102.1만 다릅니다. PCB는 이 핀을 원래 MCU_RECEIVE_A에 연결했으므로 회로도와의 불일치도 한 건 남습니다. <a href="preflight-audit.json">보존·핀 대조 증거</a></p>
<h2>회로도 가독성과 BOM</h2><p>일반 와이어를 블록 내부의 기본으로 사용하고, 반복 전원과 블록 경계에는 포트/라벨을 사용했습니다. 실제 EasyEDA SVG export를 렌더링하여 레귤레이터, 06 제어, MCU A/B 채널 및 릴레이 영역을 확인했습니다. 캐시 썸네일을 최신 검증 이미지로 사용하지 않았습니다. 렌더러가 무시한 삽입 로고 1개는 회로 연결과 무관합니다.</p><p>{links}</p>
<img src="regulator-native-crop.png" alt="실제 native SVG의 일반 와이어 LDO"><p><a href="native-final-schematic-proof.zip">EasyEDA native SVG 두 페이지</a> · <a href="DAC8562-native.png">Page 1</a> · <a href="DAC_MCU-native.png">Page 2</a></p>
<h2>전원 기동 시뮬레이션</h2><p>TI의 수정하지 않은 TPS7A4901 unencrypted model 1.2로 입력 상승 0.1/1/10/100ms × 부하 2/10/20mA × 출력 유효 C 0.5/1.0을 계산했습니다. <b>기동 전용 24/24건 수렴 및 전압 범위 선별 통과</b>, 모델 출력 최대 {startup['maximumAvddV']:.6f}V입니다. 모델의 기준전압 1.192V와 데이터시트의 전형값 1.185V 차이를 그대로 유지했습니다. 이것은 최악조건 정확도 보증이 아닙니다. <a href="https://www.ti.com/product/TPS7A49">TI 제품·모델</a></p>
<p>기동+종료+브라운아웃 27건 중 7건은 모델 UVLO 불연속에서 수렴 실패했습니다. 이를 통과로 세지 않았습니다. VIN/음전원은 이상적인 주어진 램프이며 TPS65131 스위칭 전체 회로의 검증이 아닙니다. PG 안정 2ms + 초기화 5ms는 논리 선별용 가정이며 DAC 초기화 보증 시간이 아닙니다. Enable을 미리 HIGH로 유지하면 초기화 이전 노출 및 브라운아웃 자동 재활성화가 가능합니다.</p><p><a href="../../simulation/startup/summary-startup-only.json">24건 수치</a> · <a href="../../simulation/startup/summary.json">종료 실패 포함 27건</a> · <a href="../../simulation/startup/README.txt">모델·재실행·제한</a></p>
<h2>제작 전 DFM / PCB</h2><p>실제 패드 489개, 연결된 패드 481개, 90개 네트를 동박·비아·GND 영역 기준으로 별도 검사했습니다. 현재 PCB 동박 단락/단선 0건, 회로도 대조 차이는 R102.1 하나입니다. 배치·패드 네트·배선 원본은 유지하고 부품표 메타데이터만 동기화했습니다.</p>
<p>선폭 최소 {features['minimumTrackWidthMm']:.3f}mm, 비아 드릴 {features['viaDrillRangeMm'][0]:.3f}mm, 비아 홀→다른 네트 트랙 최소 {features['minimumViaHoleToDifferentNetTrackMm']:.3f}mm, 비아 홀간 {features['minimumViaHoleToViaHoleMm']:.3f}mm입니다. 동박→기판 외곽 최소 {dfm['minimumCopperToRoutedBoardEdgeMm']:.3f}mm. Samtec J1은 2.54mm 피치/행 간격, 기존 홀 1.100mm/패드 1.7mm와 대조했습니다. 마스크 브리지 간격 8곳의 약 0.098mm 문제는 검토 CAM에서 0.10mm 미만 0곳으로 보완되지만, 저장 프로젝트 master에는 반영되지 않았으므로 반드시 CAD에서 해결해야 합니다. 실크는 패드 마스크에서 약 0.15mm 이격하도록 검토 사본에서만 잘랐습니다. <a href="https://jlcpcb.com/capabilities/pcb-">JLC 규격</a></p>
<p><a href="dfm-native-features.json">홀·선폭 검사</a> · <a href="cam-dfm-final.json">CAM 최소 간격</a> · <a href="physical-pcb-audit.json">패드·물리적 동박 검사</a>. Gerber 상면 생성 패드에는 이전 export 대비 약 0.0016mm 수준의 반올림 차이가 있어 바이트 동일을 주장하지 않습니다. 제조 파일은 새로 재생성해 검토해야 합니다.</p>
<p>가격 고려 결정은 기존 단일 100×100mm 보드를 유지합니다. 시제품 수량이 지정되지 않았고 현재 보드는 단일 소형 특가 구간인 반면 마우스바이트 패널은 면적·라우팅 비용이 늘어납니다. 고정 견적을 제시하거나 주문하지 않았습니다. Panel1은 변경하지 않았습니다. <a href="https://jlcpcb.com/help/article/in-what-cases-will-there-be-charged-extra">제조사 요금 구분</a></p>
<h2>저장 파일 / 남은 제한</h2><p><a href="DAC8562_review_checkpoint_R102_pending.eprj2">Native 검토 체크포인트</a> · <a href="DAC8562_review_checkpoint_R102_pending.epro2">이식용 검토 export</a> · <a href="DFM_REFERENCE_ONLY_NOT_FOR_FABRICATION.zip">주문 금지 DFM 참고 ZIP</a>. 원본 작업 전 SQLite 및 live export 백업은 backups에 보존했습니다. 이전 final-review 파일은 과거 검토 기록이며 현재 제작 상태가 아닙니다.</p><ul>{limits}</ul><p>Git 전달은 실제 commit 및 origin/main 일치로 확인합니다. 보고서 자체가 향후 push 성공을 예측하지 않습니다.</p></html>'''
(out/'preflight-report.html').write_text(text,encoding='utf8')
print(json.dumps({'report':str(out/'preflight-report.html'),'bomGroups':53,'fabricationReleased':False,'holds':['R102','CAD mask persistence','manufacturer DFM/assembly approval']},ensure_ascii=False))
