from pathlib import Path
import json, hashlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parent
new=root/'highz'
plt.rcParams.update({'font.family':'Malgun Gothic','axes.unicode_minus':False,'font.size':10})
nom=json.loads((new/'summary-verify.json').read_text());corners=json.loads((new/'summary-corners.json').read_text())
layout=json.loads((new/'layout-verification.json').read_text())
erc_errors=sum(item['count'] for item in layout['schematicDrc'] if item['type']=='error')
erc_warnings=sum(item['count'] for item in layout['schematicDrc'] if item['type']=='warn')
archive_path=new/'plot-waveforms.npz'
archived=dict(np.load(archive_path)) if archive_path.exists() else {}
def load(name):
 raw=new/'results'/(name+'.dat')
 if raw.exists():
  archived[name]=np.loadtxt(raw,skiprows=1,ndmin=2)
 return archived[name]
minimum_pm=min(x['phaseMarginDeg'] for j in nom+corners if j['test']=='loop' for x in j['crossings'])
trans=[j for j in nom+corners if j['test']=='tran'];maximum_overshoot=max(j['overshootPercent'] for j in trans);maximum_settling=max(j['settling1PercentUs'] for j in trans)
fig,axs=plt.subplots(1,2,figsize=(12,4.6))
for cap in [0,470,1000,5000]:
 j=next(j for j in nom if j['test']=='tran' and j['R']==1e6 and j['cap']==cap);a=load(j['name']);sel=(a[:,0]>=50e-6)&(a[:,0]<80e-6);axs[0].plot((a[sel,0]-50e-6)*1e6,a[sel,2]*1000,label=f'추가 {cap} pF')
 j=next(j for j in nom if j['test']=='loop' and j['R']==1e6 and j['cap']==cap);a=load(j['name']);axs[1].semilogx(a[:,0],a[:,2],label=f'{cap} pF')
axs[0].set(xlabel='계단 입력 후 시간 (µs)',ylabel='출력 (mV)',title='OPA2277 + 100Ω / 22pF: 단조로운 작은 신호 응답')
axs[1].set(xlabel='주파수 (Hz)',ylabel='루프 위상 (°)',title='고임피던스 부하의 피드백 루프',xlim=(1e4,2e6),ylim=(-185,-45));axs[1].axhline(-180,color='#dc2626',ls='--')
for ax in axs:ax.grid(alpha=.25);ax.legend(fontsize=9)
fig.tight_layout();fig.savefig(new/'stability-improved.png',dpi=160);plt.close(fig)
fig,ax=plt.subplots(figsize=(10,4))
baseline=root/'results'/'small_highz_c0.dat'
if baseline.exists():archived['baseline_original192']=np.loadtxt(baseline,skiprows=1)
before=archived['baseline_original192'];mask=(before[:,0]>=10e-6)&(before[:,0]<30e-6);ax.plot((before[mask,0]-10e-6)*1e6,before[mask,2]*1000,label='이전 OPA192 / 10Ω / 무보상')
j=next(j for j in nom if j['test']=='tran' and j['R']==1e6 and j['cap']==0);a=load(j['name']);mask=(a[:,0]>=50e-6)&(a[:,0]<80e-6);ax.plot((a[mask,0]-50e-6)*1e6,a[mask,2]*1000,label='수정 OPA2277 / 100Ω / 22pF',lw=2)
ax.set(xlabel='계단 입력 후 시간 (µs)',ylabel='SMA 출력 (mV)',title='DC·저속 제어를 위한 안정성 개선 — 약 100.4mV 계단');ax.legend();ax.grid(alpha=.25);fig.tight_layout();fig.savefig(new/'before-after.png',dpi=160);plt.close(fig)
np.savez_compressed(archive_path,**archived)
rows=''
for R in [1e6,100e3,10e3]:
 dc=next(j for j in nom if j['test']=='dc' and j['R']==R)
 for cap in [0,100,470,1000,5000]:
  loop=next(j for j in nom if j['test']=='loop' and j['R']==R and j['cap']==cap);tr=next(j for j in nom if j['test']=='tran' and j['R']==R and j['cap']==cap)
  rows+=f'<tr><td>{R/1000:g} kΩ</td><td>{cap:g} pF</td><td>{min(x["phaseMarginDeg"] for x in loop["crossings"]):.1f}°</td><td>{max(0,tr["overshootPercent"]):.4f}%</td><td>{tr["settling1PercentUs"]:.2f} µs</td></tr>'
verification={ 'design':'5V input; high-Z DC/slow control; OPA2277UA dual with RISO=100 ohm and local CF=22pF','minimumTestedPhaseMarginDeg':minimum_pm,'maximumSmallSignalOvershootPercent':maximum_overshoot,'maximumSmallSignalSettling1PercentUs':maximum_settling,'nominal':nom,'corners':corners,'assumptions':{'inputSupplyV':5,'amplifierRailsV':[11.97231,-12.13],'loadResistanceOhms':[1e6,1e5,1e4],'extraCableCapacitancePf':[0,100,470,1000,5000],'fixedOutputCapacitancePf':100,'referenceV':2.5,'temperatureC':27,'idealDACRangeV':[0,5],'risotolerancePercent':1,'cftolerancePercent':5},'limitations':['SolsTiS actual input impedance has not been verified; high impedance is the user-selected assumption.','Typical TI macro-model; no guaranteed device worst-case analysis or thermal self-heating.','DAC buffer, DAC gain/INL/glitch, reference and resistor mismatch, supply ripple/startup, PCB parasitics and cable transmission-line effects are not modeled.','Only RISO and CF endpoint tolerances, selected output biases, and the listed loads/capacitances are swept.','50 ohm termination is not supported.','Reject unseeded unphysical DC operating points and initial high-positive-bias transient convergence failures; use physical nodesets and startup ramp retries.'], 'modelSha256':hashlib.sha256((root/'models/pspice/OPAx277.LIB').read_bytes()).hexdigest()}
(new/'verification.json').write_text(json.dumps(verification,indent=2),encoding='utf-8')
html=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DAC8562 고임피던스 안정성 개선</title><style>body{{font-family:"Malgun Gothic",sans-serif;background:#f8fafc;color:#172033;max-width:1100px;margin:36px auto;padding:0 24px;line-height:1.65}}h1{{font-size:28px}}h2{{margin-top:32px}}.ok{{background:#e5f6ed;border-left:5px solid #15803d;padding:16px}}.warn{{background:#fff4dc;border-left:5px solid #d97706;padding:16px}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{border:1px solid #cbd5e1;padding:9px;text-align:right}}td:first-child,th:first-child{{text-align:left}}img{{max-width:100%}}code{{background:#e2e8f0;padding:2px 5px}}</style>
<h1>DAC8562 — 고임피던스 출력 안정성 개선</h1><p>2026-10-12 · 5V 외부 입력 유지 · OPA2277UA 듀얼 · ngspice 47 / TI OPAx277 Final 1.4</p>
<div class="ok">출력단 모델 검증 통과: 고임피던스 ±10V 범위, 시험 최소 위상 여유 {minimum_pm:.1f}°, 작은 신호 오버슈트 {maximum_overshoot:.4f}% 이하, 1% 정착 {maximum_settling:.2f}µs 이하.</div>
<div class="warn">SolsTiS PZT INPUT의 실제 임피던스는 확인하지 못했습니다. 사용자가 선택한 고임피던스 가정입니다. 50Ω 구동·12V 입력 변경은 취소했으며, 이 출력은 50Ω 종단용이 아닙니다. 시뮬레이션 통과는 실물·레이저 연결의 안전 보증이 아닙니다.</div>
<div class="ok">2026-10-12 재연결 후 검증: PCB DRC 0건, 회로도 오류 {erc_errors}건, 회로도/PCB 35개 넷·173개 연결 핀 불일치 0건입니다. C18/C19/C20/C21 주변 전원 넷 플래그 8개의 비어 있던 Name을 VPOS12/VNEG12/GND로 복원했고, 저장 후 다시 열어 오류가 재발하지 않음을 확인했습니다. <a href="highz/schematic-erc-repair.json">오류 수정 기록</a> · <a href="highz/layout-verification.json">배치·핀별 검증 기록</a></div>
<div class="ok">회로도 경고 {erc_warnings}건: 기존 중복 넷 이름 27건과 공급업체 속성 불일치 2건을 수정했습니다. 검사 규칙을 숨기거나 부품을 교체하지 않았으며 저장 후 다시 열어 회로도·PCB 검사와 35개 넷·173개 핀 연결을 확인했습니다. <a href="highz/schematic-drc-clean.txt">최종 검사 로그</a> · <a href="highz/warning-cleanup-verification.json">수정·대조 기록</a> · <a href="../output/highz/DAC8562_highz_BOM.html">수정 BOM (28종 / 60개)</a></div>
<div class="warn">부품 주문 전 확인: J1은 2×5핀 2.54mm 일반 커넥터 라이브러리 항목으로 실제 제조사 SKU를 별도 선정해야 합니다. Q1 SI2323DS-T1-E3는 공급업체 라이브러리에서 단종 표시되어 대체 부품 또는 잔여 재고 검토가 필요합니다. 부품 정보와 DRC 정리는 완료했지만 실물 검증·최종 DFM 검토까지 완료한 제작 승인 상태는 아닙니다.</div>
<h2>1. 채택 회로</h2><p>U4의 A/B 두 증폭기로 기존 U4/U5 두 OPA192를 통합했습니다. R16/R21은 10Ω에서 <b>100Ω, 1%</b>로 바꾸고 C25/C26 <b>22pF, C0G/NP0, 50V, 5%</b>를 추가했습니다. C22/C23의 출력 100pF는 유지했습니다.</p>
<p>저주파·DC에서는 R15/R20 100kΩ가 <b>100Ω 뒤의 SMA 접점</b>을 감지합니다. 100Ω 전압강하를 포함해 DC 출력값을 보정합니다. 고주파에서는 C25/C26이 <b>100Ω 앞의 증폭기 출력 → 반전 입력</b>으로 직접 피드백을 제공합니다. 케이블 용량은 100Ω로 분리하면서 DC 정확도를 유지하는 이중 피드백입니다. 단순 입력 필터만 넣어 발진을 가리는 방식이 아닙니다. 의도적으로 대역폭을 낮추는 대가가 있어 DC·저속 제어에 적합합니다.</p>
<p>공칭 DC 전달식: <code>Vout = (100k / 24.9k) × (Vdac − 2.5V)</code>. R12/R14/R17/R19 24.9kΩ, R13/R15/R18/R20 100kΩ, 0.1%는 유지했습니다. 유한 입력 바이어스 전류가 있는 OPA2277에는 저항 정합과 청결한 입력 주변 배치가 중요합니다.</p><img src="highz/before-after.png" alt="안정성 개선 전후 계단 응답">
<h2>2. 시험 결과</h2><p>1MΩ 공칭 출력: −10.04016V ~ +10.04014V. 10kΩ·100kΩ에서도 공칭 ±10V 범위를 확인했습니다. 이상적인 DAC의 0~5V를 가정한 증폭기 결과로, 실제 DAC 최고 코드·5V LDO 오차·출력 버퍼의 레일 근처 오차는 별도입니다. 약 100.4mV 작은 신호 계단을 시험했습니다. 아래는 공칭 부품값이며 공차 시험까지 포함한 전체 최소 위상 여유는 {minimum_pm:.1f}°입니다.</p>
<table><tr><th>부하</th><th>추가 용량</th><th>위상 여유</th><th>오버슈트</th><th>1% 정착</th></tr>{rows}</table><img src="highz/stability-improved.png" alt="케이블 용량별 안정화된 응답">
<p>출력 약 −9.84V와 +9.74V의 바이어스, RISO 99/101Ω 및 CF 20.9/23.1pF의 조합, 추가 용량 0/470/5000pF를 검사했습니다. 5nF에서 0→−10.04→+10.04V의 느린 전체 범위 램프도 검사했습니다. 양의 바이어스에서 초기 정지 동작점 수렴이 실패한 과도 시험은 제외하고, 0V에서 바이어스로 램프 이동 후 작은 신호를 넣는 방식으로 재검사했습니다. 비현실적 동작점이나 중단된 계산을 통과로 집계하지 않았습니다.</p>
<h2>3. 전원·핀 연결 검토</h2><p>TPS65131: PGND 2/3번, AGND 19번 및 EP 25번은 GND입니다. INN 5/6번은 GND가 아니라 <b>VIN_RAW 5V 입력</b>입니다. INP 1/24번은 승압 스위칭 노드입니다. DAC8562 GND 3번과 VREFIN/VREFOUT 10번의 잘못 바뀐 연결도 수정했습니다. DAC→출력단은 DACA/DACB 넷포트 두 쌍으로 분리하고 그 외 기능 블록의 일반 신호 배선은 와이어를 유지했습니다.</p>
<p>LP2985-50: C13 입력 4.7µF, C15 출력 4.7µF, C14 BYP <b>10nF</b>를 유지했습니다. 이미지의 BYP 30pF는 권장 잡음 저감 값과 다르므로 채택하지 않았습니다. 이미지의 10µF 두 개를 단순히 추가할 필요는 없습니다. 구형 LP2985의 출력 안정성 조건을 고려하여 공차·DC 바이어스를 적용한 유효 C15가 <b>2.2µF 이상</b>이고 데이터시트 ESR 범위를 만족하는지 부품 선정/실물에서 확인해야 합니다. 최신 LP2985는 출력 용량 1µF 이상을 지원하지만, 실제 주문 소자 리비전을 모르는 상태에서 그 조건만 적용하지 않습니다.</p>
<h2>4. PCB와 연결 전 확인</h2><p>PCB는 90×60mm, M3용 비도금 Ø3.2mm 홀 4개를 (5,5), (85,5), (5,55), (85,55)mm에 대칭 배치했습니다. 각 홀 주변은 Ø7mm 구리·부품 금지 영역입니다. J1을 보드 아래쪽으로 옮겼고, 듀얼 증폭기 주변에 고주파 피드백 커패시터와 전원 디커플링 부품을 배치했습니다. 최종 PCB DRC/넷리스트 검증 결과는 별도 검증 JSON을 참조하십시오.</p>
<p>레이저 장비를 연결하기 전에 더미 고임피던스 부하와 실제 케이블로 ±12V 레일, 5V LDO, 기준전압, DC 보정, 계단 응답, 전원 투입·차단 과도를 측정해야 합니다. 수학적 최대 범위는 ±10.04V라 장비 입력 제한이 ±10.00V이면 펌웨어에서 제한·보정해야 합니다. 초기 시험에는 ±9.5V와 느린 램프를 권장합니다. DAC 전원 투입 기본 코드/기준전압 상태에 따라 음의 출력이 나타날 수 있으므로 레이저에 직접 연결한 기동 시험은 피하십시오.</p>
<h2>5. 한계와 재현 파일</h2><p>전원은 공칭 +11.97231V/−12.13V의 이상적인 레일로 두었습니다. TPS65131/LP2985의 스위칭 리플·전원 기동, DAC 자체 모델·INL/글리치, 실제 케이블 전송선·PCB 기생 성분, 온도/전 저항 공차/자체 발열은 모델에 포함하지 않았습니다. 특히 ±10V 범위는 공칭 증폭기 모델 결과이며 실제 부품 전체의 최악 조건 보증이 아닙니다.</p>
<p><a href="highz/verification.json">전체 수치와 조건</a> · <a href="highz/current-schematic.net">수정 회로도 넷리스트</a> · <a href="highz-stability.mjs">재현 시뮬레이션 스크립트</a> · <a href="highz/manifest-verify.json">공칭 시험 목록</a> · <a href="highz/manifest-corners.json">공차·바이어스 시험 목록</a></p>
<p>프로젝트 폴더에서 <code>node simulation/highz-stability.mjs verify dfb_100_22</code>, <code>node simulation/highz-stability.mjs corners</code>, <code>python simulation/analyze-highz.py verify</code>, <code>python simulation/analyze-highz.py corners</code>, <code>python simulation/highz-report.py</code>로 재현합니다. ngspice 실행 파일은 기본 tmp 경로 또는 환경변수 NGSPICE_BIN으로 지정합니다. numpy/matplotlib와 ngspice PSpice 호환 설정이 필요합니다.</p>
<p>출처: <a href="https://www.ti.com/product/OPA2277">TI OPA2277 / 공식 모델</a> · <a href="https://www.ti.com/document-viewer/lit/html/SSZT999/GUID-7ACEA978-4202-4BB8-8E9A-DE4DEC6654C4">TI RISO+이중 피드백 설명</a> · <a href="https://www.ti.com/lit/gpn/TPS65131">TPS65131 데이터시트</a> · <a href="https://www.ti.com/lit/ds/symlink/lp2985.pdf">LP2985 데이터시트</a> · <a href="https://www.ti.com/lit/ds/symlink/dac8562.pdf">DAC8562 데이터시트</a></p></html>'''
(root/'analog-output-report.html').write_text(html,encoding='utf-8')
print(json.dumps({'minimumPM':minimum_pm,'overshoot':maximum_overshoot,'settlingUs':maximum_settling,'report':str(root/'analog-output-report.html')}))
