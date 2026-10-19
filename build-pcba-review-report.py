"""Package native exports and keep unresolved PCBA release gates visible."""
from pathlib import Path
import csv,hashlib,html,json,zipfile
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/jlcpcb-order-20261019';OUT.mkdir(exist_ok=True,parents=True)
esc=lambda x:html.escape(str(x))
entries=[];sections=[]
for folder in ['STM32H747 board','TEST_DAC8562']:
    base=ROOT/folder/'output/jlcpcb-20261019-review';native=base/'native'
    d=json.loads((base/'review-data.json').read_text(encoding='utf8'));s=d['summary'];board=s['board']
    cam=json.loads((base/'CAM_AUDIT.json').read_text(encoding='utf8'))
    assert not cam['padCentreFailures'] and cam['physicalDrillCount']==(863 if board=='STM32H747' else 198)
    def readcsv(name):
        with (base/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
    bom=readcsv('BOM_CANDIDATE.csv');cpl=readcsv('CPL_CANDIDATE.csv')
    expected={p['ref'] for p in d['parts'] if not p['excluded']}
    assert len(bom)==len(cpl)==len(expected)==s['assemblyParts']
    assert {r['Designator'] for r in bom}=={r['Designator'] for r in cpl}==expected
    assert sum(int(r['Quantity']) for r in bom)==s['assemblyParts']
    assert sum(not r['Manufacturer Part'] for r in bom)==s['unresolvedAfterProposals']
    with zipfile.ZipFile(base/'PCBA_REVIEW.xlsx') as z:assert z.testzip() is None
    erc=json.loads((native/('erc-current.json' if board=='STM32H747' else 'erc-verified.json')).read_text(encoding='utf8'))['result']
    drc=json.loads((native/('drc-before.json' if board=='STM32H747' else 'drc-after-native-mask.json')).read_text(encoding='utf8'))['result']
    assert all(not p['violations'] for p in erc)
    assert not (drc.get('violations',[]) if isinstance(drc,dict) else drc)
    filenames=['BOM_REVIEW.csv','BOM_CANDIDATE.csv','CPL_CANDIDATE.csv','EXCLUDED.csv','PROCUREMENT_REVIEW.csv','PROPOSED_PARTS.csv','UNRESOLVED_PARTS.csv','PCBA_REVIEW.xlsx','CAM_AUDIT.json','PLACEMENT_AUDIT.json','review-data.json','ORDER_HOLD.txt','native/'+board+'_CAM_20261019.zip','native/'+board+'_BOM_20261019.csv','native/'+board+'_CPL_20261019.csv']
    filenames+=['native/erc-current.json','native/drc-before.json'] if board=='STM32H747' else ['native/erc-verified.json','native/drc-after-native-mask.json','native/U3-final-mask-cam.json','native/native-final-change-audit.json']
    links=[]
    for name in filenames:
        p=base/name;rel=p.relative_to(ROOT).as_posix();entries.append({'board':board,'file':rel,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
        links.append('<li><a href="../../'+esc(rel)+'">'+esc(name)+'</a></li>')
    unresolved='<br>'.join(esc(r['Designator']+' · '+r['Value']+' · '+r['TCR']) for r in d['unresolvedParts']) or '없음 — 기존 지정 품번 유지'
    note='동일 XY의 저항 5쌍은 실제로 서로 다른 구리면에 있습니다. 실제 패드와 제조 파일을 확인했으며 부품을 이동하거나 삭제하지 않았습니다.' if board=='STM32H747' else 'J1의 데이터시트 속성을 동기화하고 U3 마스크 확장을 1 mil로 저장했습니다. 실제 Gerber의 최소 마스크 웹은 약 0.150 mm입니다. 편집기 저장 반올림에 의한 U3 패드 중심의 최대 차이는 0.001024 mm입니다.'
    sections.append(f'<section><h2>{board}</h2><table><tr><th>PCB</th><td>{s["layers"]}층 · {s["sizeMm"][0]} × {s["sizeMm"][1]} mm</td><th>실장 후보</th><td>{s["assemblyParts"]}개 / 제외 {s["excluded"]}개</td></tr><tr><th>현재 검사</th><td>전 회로도 ERC 0 / 엄격 PCB DRC 0</td><th>CAM 확인 범위</th><td>구리 {cam["copperLayerCount"]}층, 패드 중심 {cam["padCentreChecks"]}개 대조, 드릴 {cam["physicalDrillCount"]}개</td></tr><tr><th>실장면</th><td>Top {cam["assemblySideCounts"].get("Top",0)} / Bottom {cam["assemblySideCounts"].get("Bottom",0)}</td><th>품번</th><td>CAD 미지정 {s["noExactMpn"]}개 → 신규 후보 {s["proposedNewMpnParts"]}개 → 미확정 {s["unresolvedAfterProposals"]}개</td></tr></table><p>{note}</p><p><b>CPL 방향 확인 대상:</b> {len(cam["rotationReviewRequired"])}개. STM32는 회전이 풋프린트 안에 포함되어 있어 복합/극성 부품의 원시 각도 0°를 그대로 승인할 수 없습니다. 후보 CPL의 면은 보정했으며 최종 핀 1 매칭이 필요합니다.</p><details><summary>품번 미확정 목록</summary><p>{unresolved}</p></details><details><summary>파일 목록</summary><ul>'+''.join(links)+f'</ul></details><p>원본: <code>{esc(s["source"])}</code></p><p>SHA256: <small>{s["sourceSHA256"]}</small></p></section>')
css='body{font:16px/1.65 system-ui,sans-serif;max-width:1120px;margin:32px auto;padding:0 22px;color:#243747;background:#f5f7fa}section{padding:24px;margin:24px 0;background:white;border:1px solid #d8e0e7;border-radius:10px}h1{font-size:28px}h2{color:#143951}.hold{padding:18px;background:#fff0e9;border-left:5px solid #bd4e25}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px;border:1px solid #d8e0e7;text-align:left}th{background:#eaf0f4}a{color:#075f9c}code{overflow-wrap:anywhere}li{margin:7px 0}'
intro='''<h1>JLCPCB 실장 주문 준비 · 2026-10-19</h1><div class="hold"><b>새 제조 파일 추출 완료 · 실장 주문 승인 전 단계</b><p>두 보드의 최신 Gerber, BOM 후보, 좌표 후보와 검토표를 준비했습니다. STM32 정밀저항 25개의 정확한 품번과 복합 부품의 핀 1/회전 매칭이 남아 있어 현재 패키지는 검토·견적용입니다. CPL_CANDIDATE를 최종 좌표 파일로 간주해 바로 결제하지 마십시오.</p></div><p>EasyEDA 3.2.206과 승인된 외부 상호작용 설정으로 추출했습니다. 보드별 ERC/엄격 DRC, 실제 패드 면, 구리 중심과 드릴 수를 확인했습니다. 패드 중심 일치는 모든 구리 다각형의 전기적 동등성이나 외부 DFM 승인을 뜻하지 않습니다.</p>'''
steps='''<section><h2>주문 진행 방법</h2><ol><li>보드별 Gerber ZIP을 각각 별도 주문으로 올립니다. STM32는 6층, DAC는 2층입니다.</li><li>FR-4와 원본 적층/두께를 대조합니다. STM32는 ENIG 기준으로 견적을 확인하고 6층 구리/절연층 두께와 1.6 mm 완성 두께를 대조합니다.</li><li>PCB Assembly를 켭니다. STM32는 양면, DAC는 앞면 실장입니다. THT 커넥터·헤더·SMA까지 포함한 조립 범위를 확인합니다.</li><li>BOM_CANDIDATE에서 정확한 제조사 품번·JLC 번호·재고·패키지를 확인합니다. PROPOSED_PARTS는 신규 품번 제안이며 CAD를 바꾼 목록이 아닙니다. 미확정 25개는 사양을 유지해 별도 조달 대상으로 두었습니다.</li><li>CPL_CANDIDATE의 부품을 실제 패드 번호와 대조합니다. STM32 복합/극성 부품의 회전을 확정한 뒤 최종 CPL로 사용합니다. 원시 네이티브 STM32 CSV는 일부 실장면과 회전을 올바르게 표현하지 못합니다.</li><li>실장 미리보기와 모든 구리층·마스크·실크·외곽·PTH/NPTH/장공 검토를 완료하고 제조/조립 검토 및 최종 견적 후 결제합니다.</li></ol><p>수량은 아직 지정하지 않았습니다. 업로드·부품 구매·발주·결제를 수행하지 않았습니다. 정밀 부품의 저항값·공차·온도계수를 임의 완화하지 않았습니다.</p><p>STM32의 기존 기능 제한도 유지됩니다. 개방 입력은 약 2.5 V이며 현재 필터/샘플링 구성은 1 MHz 파형 취득용이 아닙니다.</p><p>공식 안내: <a href="https://jlcpcb.com/help/article/how-do-i-place-a-pcba-order">PCBA 주문</a> · <a href="https://jlcpcb.com/help/article/bill-of-materials-for-pcb-assembly">BOM</a> · <a href="https://jlcpcb.com/help/article/pick-place-file-for-pcb-assembly">CPL</a> · <a href="https://jlcpcb.com/help/article/jlcpcb-surface-finish">표면 마감</a> · <a href="https://jlcpcb.com/help/article/how-to-use-jlcpcb-global-sourcing-parts-service">별도 조달</a></p></section>'''
body='<!doctype html><html lang="ko"><meta charset="utf-8"><title>JLCPCB 실장 주문 준비</title><style>'+css+'</style>'+intro+''.join(sections)+steps+'</html>'
(OUT/'index.html').write_text(body,encoding='utf8')
manifest={'date':'2026-10-19','manufacturingApproved':False,'nativeGerberAvailable':True,'finalCplApproved':False,'checks':['Native ERC/strict DRC zero','Gerber and XLSX ZIP CRC','BOM/CPL reference and quantity agreement','Physical pad-side and copper-centre checks','Physical drill counts','DNP/bare pad exclusion'],'files':entries}
(OUT/'file-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
readme='JLCPCB PCBA REVIEW PACKAGE - NOT FINAL ORDER APPROVAL\n\nFresh native Gerber files are included for both boards.\nSTM32: 25 exact MPNs unresolved; complex/polarized part rotations require pin-map matching.\nBOM_CANDIDATE includes 107 proposed new passive MPNs external to the CAD.\nRaw native STM32 CPL is not an approved placement file. Read index.html and ORDER_HOLD.txt.\nStock, THT assembly scope, quantity, stackup, full CAM/DFM and assembly preview must be finalized before payment.\nNo order, purchase, upload or payment has been made.\n'
(OUT/'READ_FIRST_NOT_FOR_ORDER.txt').write_text(readme,encoding='utf8')
with zipfile.ZipFile(OUT/'PCBA_PREPARATION_REVIEW_NOT_FOR_ORDER.zip','w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('READ_FIRST_NOT_FOR_ORDER.txt',readme);z.write(OUT/'file-manifest.json','file-manifest.json');z.writestr('index.html',body.replace('href="../../','href="'));z.write(OUT/'summary.json','summary.json')
    for e in entries:z.write(ROOT/e['file'],e['file'])
print(json.dumps({'package':str(OUT/'PCBA_PREPARATION_REVIEW_NOT_FOR_ORDER.zip'),'files':len(entries),'checksPassed':True}))
