from pathlib import Path
import hashlib,html,json
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/validated-revision'
rows=json.loads((OUT/'verification-summary.json').read_text(encoding='utf8'))
for row in rows:
    folder=OUT/row['name']
    reopen=json.loads((folder/'save-reopen-verification.json').read_text(encoding='utf8'))
    exp=json.loads((folder/'export-verification.json').read_text(encoding='utf8'))
    row['saveCloseReopenErcPassed']=all(x['saved']and x['closed']and x['reopened']and x['passed']and not x['details']for x in reopen['pages'])
    row['officialNativeExportSaved']=exp.get('saved',False)
    row['epro2Sha256']=hashlib.sha256((folder/(row['name']+'.epro2')).read_bytes()).hexdigest()
    row['localProjectSha256']=hashlib.sha256((OUT/(row['name']+'.eprj2')).read_bytes()).hexdigest()
    (folder/'verification-summary.json').write_text(json.dumps(row,indent=2),encoding='utf8')
orig=ROOT/'DAC8562 module.eprj2'
backup=OUT/'original-backup/DAC8562_original_2026-10-12.eprj2'
original_unchanged=hashlib.sha256(orig.read_bytes()).hexdigest()==hashlib.sha256(backup.read_bytes()).hexdigest()=='5481e16c57c5c6162a487e7f8ccfde87bba9f472283f93b6508ea427589d158a'
result={'dateKst':'2026-10-12','originalUnchanged':original_unchanged,'projects':rows,
        'notValidated':['PCB layout/DRC, manufacturing DFM','Hardware startup/brownout transients, relay release with flyback diode','Measured output accuracy, temperature drift and cable settling'],
        'conditionalChangesNotApplied':['R5 remains 100ohm: substitute the TPS65131-recommended ferrite if input rise rate >=275mV/us is measured.','C1/C2 remain 6.8pF: 7.5pF feed-forward optimization requires power-loop qualification.']}
(OUT/'verification-summary.json').write_text(json.dumps(result,indent=2),encoding='utf8')
def project_row(r,label):
    n=r['name'];return f'<tr><td>{label}</td><td>{r["pages"]}</td><td>{r["physicalParts"]}</td><td>{r["nets"]} / {r["connectedPins"]}</td><td>ERC 오류·경고 0 / 재열기 통과</td><td><a href="{n}.eprj2">로컬 프로젝트</a> · <a href="{n}/{n}.epro2">내보내기</a> · <a href="{n}/BOM.tsv">BOM</a> · <a href="{n}/verification-summary.json">검증</a></td></tr>'
document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DAC8562 / STM32H747 회로 수정 완료 기록</title>
<style>body{font-family:"Malgun Gothic",Arial,sans-serif;color:#172033;line-height:1.7;margin:36px auto;max-width:1200px;padding:0 24px;background:#f8fafc}h1{font-size:27px}h2{margin-top:32px}table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #cbd5e1;padding:9px;text-align:left;vertical-align:top}.good{background:#e6f5ed;padding:16px}.warn{background:#fff1d5;padding:16px;border-left:4px solid #b7791f}a{color:#1d4ed8}code{background:#e2e8f0;padding:2px 4px}li{margin:7px 0}</style>
<h1>DAC8562 전원·정확도 수정본 / STM32H747 SMA 회로</h1><p>2026-10-12 · EasyEDA 3.2.149.88089769 공식 API로 실제 가져오기·저장·재열기·엄격 ERC 확인</p>
<div class="good">원본 SHA-256은 기존 값과 동일합니다. 원본 로컬 프로젝트와 작업 시작 시 열려 있던 상태의 내보내기를 모두 백업했습니다. 최종 부품 제조사 번호 및 풋프린트 미지정 항목 0, 실제 넷리스트와 기대 연결의 불일치 0입니다.</div>
<h2>최종 파일 및 검증 결과</h2><table><tr><th>회로</th><th>페이지</th><th>물리 부품</th><th>넷 / 연결 핀</th><th>검증</th><th>파일</th></tr>'''+''.join(project_row(r,label)for r,label in zip(rows,['DAC8562 수정본','STM32H747 SMA 수신·±10V 변환','MCU 측 SMA 송신 버퍼']))+'''</table>
<p><a href="original-backup/DAC8562_original_2026-10-12.eprj2">원본 백업</a> · <a href="original-backup/DAC8562_live_original_snapshot.epro2">작업 시작 시 열려 있던 상태 백업</a> · <a href="verification-summary.json">전체 검증 및 해시</a></p>
<div class="warn">회로도 수정과 ERC가 완료된 상태입니다. 수정본에는 오래된 배선 PCB가 섞이지 않도록 원본 PCB/초안 도면을 제거했습니다. 이 삭제는 별도 수정본에만 적용했으며 원본과 백업은 보존했습니다. 새 PCB 배선·PCB DRC·제작 승인·실측 정확도 보증은 포함하지 않습니다. SVG 자동 내보내기는 현재 앱에서 완료되지 않아 시각적 UI 검증까지 했다고 주장하지 않습니다.</div>
<h2>DAC8562 실제 반영 사항</h2><ul>
<li>C4(CN)=4.7nF, C5(CP)=10nF로 수정. Q1은 Vishay Si2323DDS-T1-GE3, 제조사 권장 대체품 및 실제 SOT-23 풋프린트로 변경.</li>
<li>LP2985 대신 TPS7A4901DGNR: 34k/10k 피드백, 공칭 AVDD 5.2536V. NR/SS 10nF, 피드포워드 10nF, 입력·출력 10µF 25V, EP 접지. MCU와 릴레이는 이 AVDD로 공급하지 않음.</li>
<li>R12/R14/R17/R19=24.3k, R13/R15/R18/R20=100k. Susumu RG1608N 계열 0.05%, 10ppm/°C의 확정 주문번호 사용. 독립 저항이며 정합 네트워크의 비율 추적 1ppm을 보증하지 않음. 채널별 보정은 여전히 필요.</li>
<li>R8/R9/R10 풀업은 DAC AVDD로 이동. SN74LV125ATPWR 두 개로 SCLK/DIN/SYNC/LDAC/CLR 다섯 신호를 분리. TTL 입력, Ioff 지원, OE 기본 비활성 및 MCU 3.3V 입력 사용. DAC 측 SCLK/DIN에는 R32/R33 10kΩ 풀다운을 추가하여 Hi-Z/무전원 중에도 입력을 LOW로 유지.</li>
<li>TPS3700DDCR 세 개로 +12V, DAC AVDD, -12V 크기를 감시. 음전원 감시는 -12V 기준으로 부유시키고 LTV-817S-TA1로 논리 영역에 전달. 음전압을 MCU나 접지 기준 비교기 입력에 직접 넣지 않음.</li>
<li>G6K-2F-Y DC5, AO3400A 드라이버, 1N4148W-G3-18 코일 보호. 릴레이 무전원 시 양 SMA 출력을 GND에 연결. DC 피드백은 릴레이 앞에서 감지하여 mute 중에도 증폭기가 개방 루프가 되지 않음.</li></ul>
<p>5.2536V LDO와 24.3k 구성에서 SMA 1LSB는 약 0.314mV입니다. 이는 절대 출력 오차 보증이 아닙니다. 이상적인 ±10V 제한 코드는 약 918~64618이고 실제 gain/offset/기준전압/부하로 다시 보정·제한합니다. 빠른 입력 핫플러그용 R5 페라이트 변경 및 C1/C2 7.5pF 보상 최적화는 입력 파형·전원 루프 검증을 조건으로 보류했으며 기존 값을 유지했습니다.</p>
<h2>STM32H747 수신 회로 / 송신 회로</h2><p>수신 회로는 외부 MCU용입니다. MCU 자체는 포함하지 않습니다. 3.3V VREF+ 기준에서 0.25~3.05V를 공칭 ±10V로 바꾸며, 기준 중간점은 실제 MCU VREF+/2입니다. OPA2277UA/2K5 세 개, RG1608N 14k/100k 저항, 입력 및 출력의 별도 G6K 릴레이 두 개를 사용합니다.</p>
<p>입력 릴레이가 무전원 MCU 신호를 수신 버퍼로부터 분리합니다. 입력 릴레이 OFF일 때 수신 버퍼는 VBIAS에 연결됩니다. <b>INPUT_ENABLE 먼저 → 접점·출력 정착 → OUTPUT_ENABLE</b> 순서를 지킵니다. 두 릴레이를 동시에 켜지 않습니다. 출력 OFF 후에는 입력 OFF, 릴레이 해제 여유 시간 후 전원을 내립니다.</p>
<p>MCU 측 별도 송신 회로는 OPA2320AIDR, 100Ω 출력 절연 저항 및 MCU 3.3V 전원을 사용합니다. MCU DAC 핀 바로 근처에 설치하고 SMA 케이블 앞에 둡니다. 수신단 버퍼만으로 MCU 핀의 케이블 용량이 없어지지 않습니다. 모든 SMA는 50Ω 특성 임피던스 커넥터이며 <b>50Ω 저항 종단을 넣지 않습니다</b>. 측정기는 1MΩ 입력 등 고임피던스로 설정합니다.</p>
<h2>인터페이스</h2><table><tr><th>DAC8562 J1 기존 핀</th><th>DAC8562 J4 신규 핀</th><th>STM32 수신 J5 신규 핀</th><th>송신 버퍼 J1</th></tr>
<tr><td>1/2 VIN_RAW 5V<br>3/4/5 GND<br>6 CLR_EXT<br>7 LDAC_EXT<br>8 SYNC_EXT<br>9 SCLK<br>10 DIN</td><td>1 MCU 3V3<br>2 GND<br>3 MCU_INPUT_ENABLE(SPI enable)<br>4 MCU_OUTPUT_ENABLE<br>5 HW_PGOOD<br>6~10 GND</td><td>1 +12V<br>2 GND<br>3 -12V<br>4 GND<br>5 MCU VREF+<br>6 MCU 3V3<br>7 VIN_RAW 5V<br>8 MCU_INPUT_ENABLE<br>9 MCU_OUTPUT_ENABLE<br>10 HW_PGOOD</td><td>1 MCU 3V3(아날로그 전원)<br>2 GND<br>3 원시 DAC1<br>4 원시 DAC2<br>5~10 GND</td></tr></table>
<p>새 헤더는 Samtec TSW-105-07-G-D, 기존 SMA는 STA-10204로 지정했습니다. 이전 초안 J5와 핀 배치가 다르므로 연결표대로 사용합니다. VREF+에 MCU 3V3 논리 전원을 대신 연결하거나, VREF+에서 릴레이를 공급하지 않습니다.</p>
<h2>초기화·사용 순서</h2><ol><li>MCU enable 신호 두 개 LOW. 전원 양호를 연속 확인하고 기동 과도를 충분히 기다림.</li><li>DAC8562: CLR/SYNC/LDAC GPIO HIGH, SCLK/DIN idle을 먼저 준비한 뒤 SPI 버퍼 enable.</li><li><code>0x280001</code> 전체 reset → <code>0x1F8000</code> 두 채널 중간 코드 preload → <code>0x380001</code> 내부 reference enable → <code>0x020000</code> gain=2 명시.</li><li>기준전압·출력 정착과 영점 확인 후 출력 릴레이 ON. <a href="dac8562_startup.h">HAL 연결용 C 콜백 예시</a>는 실제 MCU 프로젝트에 통합·컴파일해야 함.</li><li>STM32 내부 DAC는 ES0445에 따라 MODE 설정 전에 데이터 레지스터에 기록. 버퍼 보정 및 중간 코드 설정 후 입력 릴레이, 정착 확인 후 출력 릴레이 ON.</li><li>정상 종료: 출력 enable LOW → 측정된 릴레이 해제 시간 이상의 여유(초기 10ms 이상) → 입력/SPI enable LOW → 전원 차단. CLR을 0V 명령으로 사용하지 않음.</li></ol>
<h2>아직 보증하지 않는 항목</h2><ul><li>급격한 rail fault 동안의 무과도 출력: 릴레이는 즉시 열리지 않습니다. 감독 회로는 한계 클램프가 아니며 갑작스러운 고장을 0V로 즉시 만드는 보증이 아닙니다.</li><li>전원 루프/MLCC 유효 용량, TPS7A49 overshoot·역류, 케이블 안정성, 릴레이 해제·접점 bounce의 SPICE/실측.</li><li>±10V 최악 절대 오차·온도 변화·장기 drift. 2점 이상 보정과 필요한 다점 LUT, 실제 VREF 측정 및 코드 제한 필요.</li><li>새 PCB 배치/배선/전원 리턴 경로/열 방출/제작 DFM. 이전 PCB의 DRC 통과를 수정본에 적용하지 않음.</li></ul>
<h2>부품 근거</h2><p><a href="https://www.ti.com/lit/ds/symlink/tps65130.pdf">TPS65131</a> · <a href="https://www.ti.com/lit/ds/symlink/tps7a49.pdf">TPS7A49</a> · <a href="https://www.ti.com/lit/ds/symlink/dac8562t.pdf">DAC8562T</a> · <a href="https://www.ti.com/lit/ds/symlink/sn74lv125at.pdf">SN74LV125AT</a> · <a href="https://www.ti.com/lit/ds/symlink/tps3700.pdf">TPS3700</a> · <a href="https://omronfs.omron.com/en_US/ecb/products/pdf/en-g6k.pdf">Omron G6K</a> · <a href="https://www.ti.com/lit/ds/symlink/opa2320.pdf">OPA2320</a> · <a href="https://www.susumu.co.jp/common/pdf/n_catalog_partition01_en.pdf">Susumu RG 주문 체계</a> · <a href="https://www.st.com/resource/en/datasheet/stm32h747ig.pdf">STM32H747</a></p>
<p>BOM의 Manual procurement는 MPN 미확정이 아니라 해당 MPN을 외부 유통사/제조사에서 구매한다는 의미입니다. 존재하지 않는 LCSC 코드를 붙이지 않았습니다. 재고·단가·납기는 발주 시 확인하며 주문은 수행하지 않았습니다.</p></html>'''
(OUT/'revision-completion.html').write_text(document,encoding='utf8')
if not original_unchanged or not all(r['ercAllPagesPassed']and r['saveCloseReopenErcPassed']and r['officialNativeExportSaved']and not r['netlistMismatch']for r in rows):
    raise SystemExit('Final verification incomplete')
print('All original-preservation, netlist, ERC, save/reopen and native-export checks passed.')
