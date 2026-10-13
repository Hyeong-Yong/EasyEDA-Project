"""Verify the precise fix and publish the distinction from SPICE nonconvergence."""
import hashlib,html,importlib.util,json,re,sqlite3
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'output/r102-connection-fix'
s=importlib.util.spec_from_file_location('io',root/'scripts/correction-io.py');io=importlib.util.module_from_spec(s);s.loader.exec_module(io)
read=lambda p:json.loads(p.read_text(encoding='utf8'))
before=read(out/'before-native.json');after=read(out/'after-native.json');pcb=read(out/'pcb-netlist-sync.json')
assert all(p['passed'] and not p['details'] for p in after['pages'])
def pinmap(text):
 result={}
 for block in re.findall(r'\(\s*\n(.*?)\n\)',text,re.S):
  rows=block.splitlines();net=rows[0].strip()
  for row in rows[1:]:
   m=re.match(r'([^\s-]+)-([^\s]+)',row.strip())
   if m:result[m[1]+'.'+m[2].split('-')[0]]=net
 return result
old=pinmap(before['pages'][0]['netlist']);now=pinmap(after['pages'][0]['netlist'])
diff={k:[old.get(k),now.get(k)] for k in set(old)|set(now) if old.get(k)!=now.get(k)}
assert diff=={'R102.1':['$2N434','MCU_RECEIVE_A']}
assert now['R102.2']=='MCU_VBIAS'
pd=next(iter(io.documents(pcb['source']).values()));pre=next(iter(io.documents(pcb['beforeSource']).values()))
assert io.data_hash(pd)==io.data_hash(pre),'PCB primitives changed during netlist refresh'
portable=out/'DAC8562_R102_connected.epro2';docs=io.read_export(portable)
sd=docs['e3a1c5f417017755'];branch=sd['records'][('LINE','ad2fc6e173fa4f13')][1]
assert branch['lineGroup']=='13478fd0989e44f0' and io.attrs(sd)[branch['lineGroup']]['NET']=='MCU_RECEIVE_A'
pa=io.attrs(pd);mapping={}
for (t,i),(_,p) in pd['records'].items():
 if t=='PAD_NET':a=json.loads(i);mapping[(a[1],a[3])]=p['padNet']
actual={};padcount=0
for (t,cid),(_,c) in pd['records'].items():
 if t!='COMPONENT':continue
 props=pa[cid];ref=props['Designator'];footprint=docs[props['Footprint']]
 for (kind,pid),(_,pad) in footprint['records'].items():
  if kind!='PAD':continue
  padcount+=1;net=mapping.get((cid,pid))
  if net:actual[ref+'.'+pad['num']]=net
assert actual==now,({k:[now.get(k),actual.get(k)] for k in set(now)|set(actual) if now.get(k)!=actual.get(k)})
target=out/'DAC8562_R102_connected.eprj2'
if not target.exists():
 with sqlite3.connect((root/'DAC8562 module.eprj2').resolve().as_uri()+'?mode=ro',uri=True) as src:
  with sqlite3.connect(target) as dst:src.backup(dst)
with sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True) as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
sim=read(root/'simulation/startup/summary.json');failures=[]
for case in sim['ldoSolverFailures']:
 lines=(root/'simulation/startup/results'/(case+'.log')).read_text(encoding='utf8',errors='replace').splitlines()
 message=next(l for l in lines if 'Timestep too small' in l)
 time=float(re.search(r'time = ([\d.]+)',message)[1]);assert time in (.180758,.250758)
 failures.append({'case':case,'failureTimeMs':time*1000,'error':message,'phase':'final power-off ramp; not the earlier brownout event'})
report={'date':'2026-10-13','r102CorrectConnection':'MCU_RECEIVE_A -> R102 (10Mohm) -> MCU_VBIAS','schematicErcPassed':True,'schematicErcWarnings':0,'schematicErcErrors':0,'pinChanges':diff,'redTJunctionVerifiedInNativeSvg':True,'savedClosedReopened':True,'portableExportPersistsConnection':True,'nativeCheckpoint':target.name,'nativeSha256':hashlib.sha256(target.read_bytes()).hexdigest(),'portableExport':portable.name,'portableSha256':hashlib.sha256(portable.read_bytes()).hexdigest(),'pcbPrimitivesUnchanged':True,'pcbPadCount':padcount,'connectedPcbPinsMatchingSchematic':len(actual),'electricalPinNetDifferences':0,'nativePcbDrcPassed':pcb['passed'],'nativePcbDrcDetails':pcb['details'],'pcbRemainingLimitation':'Native Netlist Error indicator remains 1 despite 481 actual connected pin nets matching. No cause is asserted without the GUI change-comparison details. PCB copper/layout/parts were not altered.','simulationMeaning':'Nonconvergence is an incomplete mathematical calculation, not an observed board malfunction. These seven runs abort near the LDO UVLO/enable model mode transition on final power-off. Discontinuous model behavior/numerical convergence is a supported inference, not proof of the exact root cause or actual shutdown safety.','startupOnlyScreensPassed':24,'mixedSolverFailures':failures,'source':'https://techweb.rohm.com/product/circuit-design/simulation/8143/','fabricationReleased':False,'otherExistingHolds':'Native soldermask persistence and manufacturer silk/assembly DFM remain unchanged; see prior manufacturing-preflight review.'}
(out/'fix-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
css='body{font:16px/1.7 "Malgun Gothic",sans-serif;max-width:1080px;margin:40px auto;padding:0 24px;color:#243746}.note{background:#fff2da;padding:16px}img{max-width:100%}a{color:#176ba1}'
page=f'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>R102 연결 수정 / 수렴 실패 설명</title><style>{css}</style><h1>R102 연결 수정 완료</h1><p>2026-10-13 · 기존 DAC8562 module 프로젝트의 DAC_MCU 페이지</p><p><b>연결되는 것이 맞습니다.</b> MCU_RECEIVE_A 전체가 끊긴 것이 아니라, R102의 윗핀 분기만 그 네트와 미연결이었습니다. MCU_RECEIVE_A → R102(10MΩ) → MCU_VBIAS가 맞는 경로입니다. 이번에 일반 와이어의 실제 T접속으로 합쳤고 빨간 접속점이 표시됩니다. 입력이 부동이 되는 것을 완화하는 약한 바이어스 경로이며, 정밀한 탈선 시 0V 출력 보증을 의미하지는 않습니다.</p><p>저장→닫기→재열기 후 두 페이지 ERC 경고·오류 0건. 프로젝트 export에도 연결이 보존됩니다. R102.1 외 다른 핀 네트, 부품 값/속성 및 PCB 동박은 변경하지 않았습니다.</p><img src="channel-A-native-crop.png" alt="실제 native SVG의 R102 빨간 T접속"><p><a href="DAC8562_R102_connected.eprj2">Native 수정본</a> · <a href="DAC8562_R102_connected.epro2">프로젝트 export</a> · <a href="fix-verification.json">검증 데이터</a></p><h2>모델 수렴 실패는 보드 고장 판정이 아닙니다</h2><p>시뮬레이터는 매 시간점에서 전압·전류 방정식을 반복 계산합니다. 7건은 전원이 내려가는 종료 구간 약 180.758ms/250.758ms에서 계산 간격을 계속 줄이다 <code>Timestep too small</code>로 중단됐습니다. 브라운아웃 시나리오 1건도 실패 지점은 앞의 순간 저하가 아니라 마지막 종료 구간입니다.</p><p>로그와 모델의 UVLO/enable IF 전환에 비춰 모델의 급격한 모드 전환과 수치 수렴 문제가 유력합니다. 이는 추정이며 특정 원인의 확정은 아닙니다. 모델·계산 알고리즘·설정 때문에 계산이 멈출 수 있다는 설명은 <a href="https://techweb.rohm.com/product/circuit-design/simulation/8143/">ROHM의 SPICE 기술 문서</a>에도 나옵니다.</p><p><b>그러므로 “이것 때문에 보드가 작동하지 않는다”는 뜻이 아닙니다.</b> 기동 전용 24건은 모델의 전압 범위 선별을 통과했습니다. 반대로, 계산이 중단된 7건의 종료 동작이 정상이라는 보증도 할 수 없습니다. 전원 종료 시 출력 튐/뮤트 지연 여부는 별도 검증 대상입니다. R102의 실제 도면 미연결과 SPICE 계산 중단은 서로 별개의 문제입니다.</p><div class="note">PCB의 실제 연결 핀 481개는 수정된 회로도와 모두 일치합니다. 다만 EasyEDA의 Native PCB Netlist Error 표시 1건은 남아 있으며 비교 창 상세 원인은 확인하지 못했습니다. PCB 배선/부품은 변경하지 않았습니다. 기존 마스크 CAD 저장 재현성 및 제조사 DFM 제한도 그대로이므로 전체 제작 승인본은 아닙니다.</div><p><a href="../manufacturing-preflight/preflight-report.html">이전 제작 전 검토 기록</a> · 작업 전 SQLite 및 live export 백업은 backups에 별도로 보관했습니다.</p></html>'''
(out/'fix-status.html').write_text(page,encoding='utf8')
print(json.dumps({k:report[k] for k in ('schematicErcPassed','pinChanges','portableExportPersistsConnection','pcbPrimitivesUnchanged','connectedPcbPinsMatchingSchematic','electricalPinNetDifferences','nativePcbDrcPassed','fabricationReleased')},ensure_ascii=False))
