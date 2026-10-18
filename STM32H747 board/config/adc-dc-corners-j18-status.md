# ADC DC 결합 회로도 및 PCB 기구/표기 변경 — 최신 2026-10-18

전용 STM32H747 창과 프로젝트 UUID를 검증한 후 공개 EasyEDA API로 수정했습니다. TEST_DAC8562 파일·문서·프로세스·브리지 기본 선택, 펌웨어는 변경하지 않았습니다.

## 최신: J2~J11 PCB 배선 완료 / 엄격 DRC 0건 — 2026-10-18

신규 34개 부품과 REF3325를 보드 내부에 배치하고, 10개 2.2 nF ADC 커패시터를 MCU 가까이 옮겨 전 채널의 입력·버퍼·ADC·바이어스·전원·접지를 배선했습니다. 옛 믹서 구리와 전원 바이어스 우회 경로를 분리했고, 정적 구리의 국부 간격만 조정했습니다. 기존 접지 경로를 보존하며 신호 비아 6개를 추가했습니다. 기존 634개 비아와 전체 793개 드릴은 그대로이며 현재 640비아/799드릴입니다. 원래 6층, 100×154 mm 외곽, 모서리 Ø3.2 mm 홀 중심 5 mm 이격, CN1 1.92 mm 가공부, J18 뒷면 21개 표기를 유지했습니다.

선택된 `JLCPCB Capability(Multiple Layers Board)` 18개 규칙과 검사 범위를 유지한 전체 엄격 DRC는 **202 → 0건**입니다. 저장 후 새 문서 클라이언트의 실제 소스를 다시 읽은 검사도 **0건**입니다. 자동 close/open API 응답은 30초를 초과했으므로 이를 성공 응답으로 기록하지 않았습니다. 재실행 없이 활성 PCB UUID·새 DOCHEAD 클라이언트·전체 소스·DRC를 확인했습니다. 실제 구리는 동일하며 16개 FILL의 빈 `refs`만 `[null] → null` 정규화됐습니다. 회로도 ERC도 통과했습니다.

주요 최종 자료:

- 편집용: `native-project/STM32H747_MCU_BOARD_v19.eprj2`
- 전체 복구본: `output/checkpoints/STM32H747_adc10_routed_verified_20261018.epro2`
- 재읽기 PCB 소스: `output/validation/native-adc10-pcb-routed_reopen_probe-20261018.epru`
- 전체 DRC: `output/validation/native-pcb-drc-0ac2a19168000d8e-adc10_routed_reopened_20261018.json`
- 회로도 ERC/넷: `output/validation/native-adc10-routed-erc-20261018.json`, `native-adc10-routed-Protel2-20261018.net`
- PCB 넷: `output/validation/native-pcb-Protel2_adc10_routed_reopened_20261018.net`
- 세부 적용/독립 검증: `output/candidates/adc10-pcb-finish-20261018/`

최종 검증용 Gerber 한정 감사도 통과했습니다(`adc10-focused-diagnostic-gerber-audit-20261018.json`). 기존 793개 드릴 보존 + 새 Ø0.20 mm 신호 드릴 6개 = 799개, 기존 외곽/CN1 8개 형상 객체와 뒷면의 기존 697개 실크 스트로크 보존을 확인했습니다. 이는 기존 J18 방향의 유지 증거이며 전체 내층 CAM DRC나 전체 구리 동등성 검사·제조 승인이 아닙니다.

사용자는 출력 임피던스 **50 Ω 함수발생기**, 주로 60 Hz·최대 1 MHz 이하라고 확인했습니다. 이번 요청의 우선순위에 따라 기존 회로도를 유지하고 PCB 배선/DRC를 완료했으며, 임의 50 Ω 종단이나 펌웨어 변경은 없습니다. 50 Ω 소스가 연결되면 명목 이득은 약 0.49817입니다. 개방 시 실제 ADC 0 V 기능은 **미반영(현재 약 2.5 V)**이고, 현 약 4.68 kHz 전단 필터와 15.6 kS/s/채널은 **1 MHz 파형 취득용이 아닙니다**. 기존 내층 Gerber 추가 CAM 검토 및 제조사 적층·비아 환형 폭·조립/실측 검증도 남아 있으므로 **배선/DRC 완료 ≠ 제조 승인**입니다.

아래 2026-10-17 미완료 수치와 신호원 미확인 문장은 당시 이력입니다. 현재 상태는 본 절이 우선합니다. TEST_DAC8562 파일·창·브리지 기본 선택 및 해당 작업의 Git 변경은 본 작업에서 조작하지 않았습니다.

## 2026-10-17 이력: J11 포함 10채널 회로도 완료 / PCB ECO 작업 중

사용자가 나머지 7개 모두(J5~J11)를 적용하도록 확인했습니다. J2~J11 전체 10채널(ADC1 3개, ADC2 3개, ADC3 4개)에 같은 6.8 kΩ 0.1% 입력/바이어스, 10 nF C0G 전단 필터, OPA320 단위 이득 버퍼, 47 Ω/2.2 nF C0G ADC 필터를 적용했습니다. 실제 연속 와이어 연결이며 DC를 차단하는 직렬 커패시터는 없습니다. 나머지 DNP R158/R159/R160/R173/R174/R175/R176을 삭제하고 U13~U19/C106~C119를 추가했습니다. 기존 ADC1과 함께 현재 물리 부품은 354개입니다. TIMER/DAC/MCO는 표시 위치만 아래로 정리했고 연결은 유지했습니다. REF 블록 배치/배선 및 J18은 보존했으며, REF 주변 설명 두 문구만 전체 10입력 공유 바이어스로 고쳤습니다.

저장·재개방한 실제 회로도 ERC 통과. 넷리스트 1,136핀/354부품은 독립 연결 계약과 모두 일치합니다. 이번 7채널 추가에서 14 DNP 핀 제거, 기존 28핀의 의도한 재연결, 새 63핀 추가만 있었고 비대상 기존 305개 부품 블록은 바이트 단위 동일합니다. 전체 237개 페이지 연결 핀, 135개 실제 와이어 섬, 10개 입력의 SMA→ADC 연속 경로를 실제 심볼/배선 기하로 독립 확인했습니다. 회로도 체크포인트는 3,924개 문서 중 해당 페이지 하나만 변경됐고 나머지 3,923개(PCB·다른 4장·모든 라이브러리 포함)는 그대로였습니다.

PCB에는 DNP 10개 제거, 기존 ADC 수동소자 40개 풋프린트 교체, 신규 34개 부품 가져오기까지 반영했습니다. 부품 고유 ID와 핀별 넷 1,136개가 회로도와 정확히 일치하며, 넷리스트 오류는 해소됐습니다. 가져오기 후 기존 패드 위치에 맞추기 위해 TOP 바이어스 저항 10개를 90°, 필터 커패시터 10개를 270°(재개방 시 동일 형상인 -90°로 정규화)로 보정했습니다. 중심 좌표·넷·부품 속성은 보존했습니다. 원래 구리 5,422 LINE/2,184 ARC/730 FILL/500 POLY, 비아 634개, 기구 PAD 4개, J18 STRING 21개, 6층 적층과 다층 규칙 18개는 아직 그대로입니다.

**PCB 최종 배치/배선은 미완료이며 제조 금지입니다.** 신규 34개 부품은 보드 밖의 임시 가져오기 위치에 있습니다. MCU 근접 필터 커패시터 위치, 기존 전원 바이어스/믹서 우회 구리 분리, 새 버퍼/기준전압 배선은 아직 적용하지 않았습니다. 마지막 저장·재개방 후 실제 엄격 DRC는 **Clearance Error 41 + Connection Error 161 = 202건**, Netlist Error 0건입니다. 방향 보정 전 ECO 직후에는 90+201=291건이었습니다. 이 수치는 규칙 완화 없이 얻은 중간 상태이지 통과 판정이 아닙니다. 아래 2026-10-16의 DRC 1건/PCB ECO 미반영 기록은 과거 이력입니다.

미연결 시 **ADC 핀의 실제 전압 0 V** 요구는 확정됐지만 기능은 아직 미반영입니다. 현 회로도는 정상 입력 0 V→ADC 1.25 V, 개방→약 2.5 V입니다. 신호원 종류/모델 및 출력 임피던스가 미확인이라 정상 고임피던스 신호를 개방으로 오인하지 않는 검출/선택 회로를 확정할 수 없습니다. 따라서 이 기능과 최종 PCB 아키텍처/배선 확정은 조건 확인 대기입니다. 임의의 50 Ω 종단·음전원·검출 스위치를 추가하지 않았습니다.

현재 보관본과 주요 검증:

- 수정 전 전체 복구본: `output/checkpoints/STM32H747_before_adc10_20261017.epro2`
- 완료 회로도 단계: `output/checkpoints/STM32H747_adc10_schematic_20261017.epro2` (SHA-256 `769f02d99203e2b48faf94c5c361ccc4b37892ada17354fe90e7e7c17595758c`)
- 최신 회로도+PCB WIP: `output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2` (SHA-256 `c103b3eb8e03556570494d66d1f0a4cd336d9ec0657c38f96b3b204923dc8edf`)
- 실제 회로도 소스: `output/validation/native-adc10-sch-reopened-20261017.epru` (SHA-256 `2040eee2c98254060060ab6ed9f9184f7e80bcd0e7e0e87286471be3e5e6e402`)
- 실제 PCB 소스: `output/validation/native-adc10-pcb-oriented_reopened-20261017.epru` (SHA-256 `b81146c1ff0e60e37a91b62ff257998017ee914828b954f8431e1611b98659cf`)
- 실제 최종 회로도 ERC/넷: `native-adc10-reopened-erc-20261017.json`, `native-adc10-reopened-Protel2-20261017.net` (위 validation 폴더)
- 실제 PCB DRC: `output/validation/native-pcb-drc-0ac2a19168000d8e-adc10_oriented_reopened_20261017.json`
- 실제 PCB 넷: `output/validation/native-pcb-Protel2_adc10_oriented_reopened_20261017.net` (SHA-256 `1851b7dfdd23b2b2c1d643bef9264106cec64cdb62e29cdbbe6b47a1351cc4d5`)
- 독립 실제 회로도 배선/핀 감사: `output/candidates/adc10-dc-buffer-20261017/independent-adc10-reopened-native-graph-audit-20261017.json`
- 회로도 단계 전체 문서 보존: 같은 폴더 `independent-adc10-checkpoint-scope-audit-20261017.json`
- PCB ECO 전기/패드 감사: 같은 폴더 `independent-adc10-pcb-eco-reopened-electrical-audit-20261017.json`, `independent-adc10-pcb-footprint179-pad-audit-20261017.json`
- PCB ECO 비대상 구리 보존: `output/analysis/adc10-pcb-eco-preservation-20261017.json`
- 방향 보정/재개방 보존: `output/analysis/adc10-passive-orientation-reopened-audit-20261017.json`
- 최신 전체 체크포인트 범위: `output/analysis/adc10-final-wip-checkpoint-scope-20261017.json`

후속 **계획일 뿐 적용하지 않은** 파일은 `adc10-pre-copper-isolation-plan-20261017.json`, `independent-adc10-bias-feed-isolation-plan-20261017.json`(위 candidates 폴더), `output/analysis/adc10-new34-placement-plan-20261017.json`, `adc10-bottom-bucket-feasibility-20261017.json`입니다. 기존 믹서 FILL 10개 및 바이어스 LINE 10개 삭제, 상류 LINE 20개 PRE 넷 변경은 아직 실행하지 않았습니다. 새 부품 34개 배치안은 정적 GND FILL의 국부 여유 가공이 필요하고, MCU 뒷면 커패시터는 3개 조건부 초안/7개 미해결로 완성 배치안이 아닙니다. R164의 옛 +3V3 비아와 새 바이어스 패드 간 약 0.135 mm 간격도 0.1524 mm 규칙에 맞는 후속 조정이 필요합니다. 제조 Gerber를 새로 내보내거나 발주하지 않았으며, 기존 CAM 추가 검토 주의사항도 유지합니다.

## 2026-10-16 이력 — ADC1 연속 와이어 / 미실장 저항 삭제

사용자 요청에 따라 ADC1 세 입력을 SMA→입력 6.8 kΩ/2.5 V 바이어스→OPA320→47 Ω→ADC 포트의 한 흐름으로 옮겼습니다. PRE/DRV의 분리된 표시 라벨 대신 실제 연속 와이어로 연결했습니다. 내부 NET 속성 이름은 연결/검증을 위해 숨겨진 상태로 유지되며, 동일 이름만으로 분리된 신호 가지를 이어 쓰지 않습니다. R146/R147/R148(30k_NC)은 해당 심볼·속성·전용 접지 가지를 포함해 삭제했습니다. 최신 사용자 편집 REF3325 배치와 나머지 회로는 보존했습니다.

최신 원본은 `output/validation/native-adc-inline-reopened-20261016.epru`, 전체 백업은 `output/checkpoints/STM32H747_adc_inline_schematic_20261016.epro2`입니다. 수정 전 백업 `STM32H747_before_adc_inline_20261016.epro2`로 복구할 수 있습니다. 이전 아래 ADC 1,093핀/343부품 기록은 R146~148 삭제 전 이력입니다. 이번 수정은 PCB에 반영하지 않았습니다.

최신 네이티브 ERC 통과. 실제 넷리스트는 1,087핀/340부품이며 R146~R148의 6핀만 제거되고 나머지 연결과 340개 부품 블록은 동일합니다. 실제 원본의 세 채널 188핀 배선 그래프, 피드백 및 포트 연결을 독립 검증했습니다. 근거는 `output/candidates/adc-inline-wiring/independent-inline-native-final-audit-20261016.json`, `output/validation/native-adc-inline-after-erc-20261016.json`, `output/validation/native-adc-inline-after-Protel2-20261016.net`입니다. 회로도 검토 이미지는 `output/candidates/adc-inline-wiring/adc-inline-final-channel-1.png` 등 실제 저장 소스 기반 오프라인 렌더입니다.

최신 전체 프로젝트 범위 감사 `output/candidates/adc-inline-wiring/adc-inline-final-project-scope-audit.json` 통과. 최신 수정 전 백업과 비교해 총 3,924개 문서 중 ADC 페이지 하나만 변경됐으며, 나머지 3,923개 문서(PCB·모든 라이브러리·다른 회로도 4장 포함)는 그대로입니다. 현재 사용자가 조정한 REF 블록 배치도 보존했습니다.

최신 전체 백업 SHA-256: `0659c79b12302d41b70edbd8971a5eae2fe750f15a53f0cc16913579c2dd60a6`. 최신 회로도 소스 SHA-256: `24a4bc9a6773479e94e95915fcee5e1439cd8aebcdcd1759b6aa14118e42dfd9`.

### Floating 영점 요구 — 설계 선택 대기, 아직 미반영

현재 수동 가산 회로에서 정상적으로 연결된 입력은 `VADC = (VIN + 2.5 V)/2`입니다. 따라서 입력 0 V에 해당하는 ADC 핀 전압은 1.25 V입니다. 입력을 개방하면 입력 저항에는 전류가 흐르지 않아 바이어스가 노드를 2.5 V로 올립니다. 이 동작은 이번 배치 정리/미실장 저항 삭제로 바뀌지 않습니다.

단순 SMA 풀다운만으로 이 문제를 해결했다고 주장하지 않습니다. 두 저항이 각각 6.8 kΩ일 때 개방 입력에 풀다운 RPD를 추가하면 `VADC = 2.5 × (6800 + RPD) / (13600 + RPD)`입니다. RPD=100 kΩ에서도 ADC는 약 2.35035 V이고, 1 MΩ에서는 약 2.48323 V입니다. 입력 환산 영점 오차 10 mV 이하를 수동 풀다운만으로 얻으려면 약 54.62 Ω 이하가 필요해 신호원을 무겁게 부하합니다.

사용자는 개방 시 **ADC 핀의 실제 전압 0 V**를 원한다고 확인했습니다. 정상 입력 0 V의 ADC 1.25 V와 구분되는 별도 개방 감지/출력 선택 회로가 필요합니다. 비교기로 스위치 이전의 버퍼 출력을 감시하고 SPDT로 정상 신호 또는 GND를 ADC에 선택하는 방식을 검토했으나, 이는 보편적인 물리적 연결 검출기가 아닙니다. 신호원의 출력 임피던스가 높거나 정상 신호가 문턱을 넘으면 연결된 입력도 GND로 오전환할 수 있습니다. 신호원 종류/모델과 출력 임피던스는 아직 확인 대기이며, 개방 검출 회로·50 Ω 종단·음전원을 추가하지 않았습니다.

### 추가 ADC 및 PCB 요청 — 당시 적용 채널/신호원 확인 대기 (현재 채널 범위 확정)

당시 실제 미변경 입력은 ADC2 J5~J7, ADC3 J8~J11의 7개로 확인됐으며, J11도 일반 측정 입력(ADC3_INP8, PF6/K2)이었습니다. 이후 2026-10-17 사용자가 J11 포함 7개 모두 적용하도록 확인했습니다. 최신 회로도/PCB ECO 상태는 이 문서 상단이 우선하며, 신호원 종류/출력 임피던스만 계속 확인 대기입니다.

읽기 전용 검토 근거: `output/candidates/adc-inline-wiring/independent-adc10-openzero-feasibility-20261016.json` 및 `independent-adc-input-inventory.json`. 추가 채널 수가 정해지면 REF3325 총 부하, 채널별 필터/버퍼 및 개방 시 ADC GND 선택의 유효 조건을 재검증하고 회로도→PCB ECO→배치/배선→엄격 DRC/CAM 순서로 진행해야 합니다.

## 반영 범위

- `06_ADC_TIMER_DAC`의 ADC1 입력 3개만 변경. DC 레벨을 차단하는 직렬 커패시터 없음.
- REF3325AIDBZR 2.5 V 기준, 각 채널 OPA320AIDBVR 단위 이득 버퍼. 모두 기존 +3V3 전원 도메인.
- R137/138/139/140/142/144: 6.8 kΩ 0.1%. R141/143/145: 47 Ω. C80/81/82: 2.2 nF C0G.
- 신규 U9~U12, C97~C105: 기준전압, 버퍼 3개, 전단 10 nF C0G 및 로컬 디커플링. 실제 PCB 추가는 아직 하지 않음.
- R146/147/148의 30k_NC는 최신 연속 와이어 정리 단계에서 삭제. PCB의 대응 부품 제거는 ECO 미반영 상태.
- 기존 ADC 포트 PA0_C, PA1_C, PA0 및 MCU 핀 배정 유지. 사용자 표현의 채널 1~3은 회로의 3개 입력 순서를 가리키며 ADC 하드웨어 채널 번호를 재배정하지 않음.
- PCB 모서리 NPTH Ø3.2 mm 4개: (4,4)→(5,5), (4,150)→(5,149), (96,4)→(95,5), (96,150)→(95,149) mm. 각 축 1 mm 안쪽 이동.
- 새 고정 홀 중심 간 피치는 90×144 mm. 참고 원본 STEP는 수정하지 않았으므로 실제 하우징/스탠드오프와의 호환은 새 홀 위치 기준으로 확인 필요.
- 기존 구리 영역 6개에 포함된 모서리 여유 영역도 새 위치에 맞게 수정. 기존 나머지 외곽/윤곽/홀/넷, CN1 1.92×1.92 mm 가공부 보존.
- J18 바닥 실크 21개 텍스트: 10핀 각각의 번호·기능, PD3/PB15/PC7 포트명 및 J18 SPI2 식별. **EasyEDA 3.2.206의 바닥 레이어 자동 반전을 사용하며, 추가 `mirror`는 false입니다.** true로 설정하면 자동 반전이 취소되어 실제 뒷면 글자가 거울상이 되는 것을 출력 비교로 확인하고 바로잡았습니다. 제조 출력의 전체 레이어 `isMirror`도 false를 유지합니다.

## 전기적 의미와 제한

명목 식은 `VADC = 0.5 × VIN + 1.25 V`, 역변환은 `VIN = 2 × (VADC − 1.25 V)`입니다. 입력 −2~+2 V는 0.25~2.25 V가 됩니다. ADC 0~3.3 V 전체 범위를 모두 쓰는 설계가 아니므로 여유 범위와 유효 해상도의 절충이 있습니다. 펌웨어 변환 계수 변경은 사용자가 담당합니다.

전단은 6.8 kΩ 병렬 등가 3.4 kΩ와 10 nF로 약 4.68 kHz 저역통과를 형성합니다. DC 이득을 유지하며 60 Hz 감쇠는 명목 약 0.0082%, 위상 지연은 약 0.73°입니다. 채널별 버퍼와 47 Ω/2.2 nF는 ADC 샘플링 전하의 앞단 유입 및 채널 간 영향을 줄이기 위한 구성입니다. 이 한 단으로 15.6 kS/s에 필요한 모든 대역외 신호의 앨리어싱을 보장하지는 않습니다.

기존 VDDA/VREF+ 공급 경로는 변경하지 않았으므로 ADC 이득 기준의 전원 잡음까지 제거한 것은 아닙니다. 소스 임피던스, ADC 취득시간, 배선/접지, 부품 공차와 실제 잡음에 대한 실측 검증이 필요하며 16비트 정확도를 보증하지 않습니다. 신규 풋프린트는 데이터시트 기반이며 제조 전 별도 조립/CAM 검토가 필요합니다.

## 검증 상태

- ADC 변경 회로도 저장·재개방 및 ERC 통과. 18개 레퍼런스/값 표시 속성 위치만 추가 정리.
- 새 회로도 넷리스트 1,093핀: 기존 비대상 1,042핀 유지, 승인된 기존 15핀 변경, 신규 36핀. 기존 318개 부품 블록 그대로.
- 회로도 물리 부품은 R146~148 삭제 전 343개, 삭제 후 340개 / PCB 330개. **ADC PCB ECO 미반영.**
- 모서리 홀·실크 수정 후 선택된 다층 규칙 18개 유지. 실제 엄격 DRC 결과: **Netlist Error 1건**, 그 외 간격·연결 오류 없음. 넷리스트 불일치를 숨기거나 검사 범위를 줄이지 않음.
- 제조 파일은 검증 전용이며 발주·결제를 하지 않음. PCB에 ADC ECO를 적용하고 다시 ERC/DRC·넷 비교·기구/실크/CAM 검토하기 전 제조 불가.

### Gerber 출력의 추가 CAM 검토 항목

실제 출력 드릴 793개 중 요청한 4개 NPTH만 이동하고 나머지 789개 위치·크기가 유지됐습니다. 새 모서리 폐곡선 여유 영역 23개와 외곽 보존을 확인했습니다. 다만 수정 대상 내층 평면 REGION의 **모서리 밖 출력 형상이 구판 검증 ZIP과 완전히 같지는 않습니다.** In1/In4의 REGION 대칭차 면적은 각각 약 0.00110434 mm², In3는 약 0.06156083 mm²입니다. 해석된 불변 구리와의 중첩을 제외한 값은 각각 약 0.00044389 / 0.05944926 / 0.00044389 mm²이나, 이 계산은 RoundRect macro flash 전체를 모델링하지 않았으므로 실제 구리 차이의 상한이며 전기적 결함 면적을 뜻하지 않습니다. 주요 위치는 (75~78, 65~68) mm 및 In3의 (52~54, 36~38) mm 주변이며 자세한 좌표는 아래 실제 Gerber 감사 보고서에 있습니다.

네이티브 원본에서 비대상 윤곽·명령·좌표가 그대로인 점은 독립 확인했으나, 출력 차이의 원인은 확정하지 않았습니다. 단순 부동소수점/내보내기 표현 차이라고 단정하지 않으며, 원인과 간격·연결 영향에 대한 추가 CAM 검토 전 이 ZIP을 제조에 사용하면 안 됩니다. 따라서 전체 Gerber 구리 형상 동등성 통과를 주장하지 않습니다.

## 근거 파일

- 수정 전 전체 백업: `output/checkpoints/STM32H747_before_adc_dc_buffer_20261016.epro2`
- 최종 전체 백업: `output/checkpoints/STM32H747_adc_dc_corners_j18_direction_v2_20261016.epro2` (기존 `...final...` 백업은 실크 방향 보정 전 이력)
- 최종 ADC 소스: `output/validation/native-adc-dc-display-final-reopened-20261016.epru`
- ADC 표시 속성 보존: `output/validation/native-adc-display-labels-receipt-20261016.json`
- ADC ERC: `output/validation/native-adc-dc-erc-20261016.json`
- ADC 넷리스트: `output/validation/native-adc-dc-Protel2-20261016.net`
- ADC 독립 전기 감사: `output/candidates/adc-dc-buffer/independent-adc-final-qa.json`
- 최종 전체 프로젝트 범위 감사: `output/candidates/adc-dc-buffer/independent-final-project-direction-v2-audit.json` 및 이전 단계 `independent-final-project-scope-audit.json` — 기존 3,905개 문서 중 ADC 페이지/PCB만 변경, 나머지 3,903개 문서 및 기존 라이브러리 보존, 신규 라이브러리 19개 확인. 방향 보정 단계에서는 PCB의 새 문자열 21개 mirror 필드만 변경했고 ADC는 그대로임.
- ADC 별도 독립 감사: `output/candidates/adc-dc-buffer/st-research-final-independent-audit.json`
- 모서리 이동 계획 및 기하 감사: `output/candidates/corner-holes-inward/plan.json`, `report.json`
- J18 배치/납땜 패드 여유 검토: `output/candidates/corner-holes-inward/j18-bottom-label-layout-review-20261016.json`
- PCB 독립 전수 보존/표기 감사: `output/candidates/corner-holes-inward/final-native-corners-j18-direction-v2-audit-20261016.json` — 비UI 비대상 12,719개 body 완전 보존, 4 PAD/6 FILL/21 STRING만 요청 범위 변경
- 최종 PCB 소스: `output/validation/native-multilayer-corners_j18_direction_v2_20261016-reopened.epru`
- 실제 PCB DRC: `output/validation/native-pcb-drc-0ac2a19168000d8e-corners_j18_direction_v2_20261016.json`
- 검증 전용 Gerber: `output/validation/STM32H747_corners_j18_direction_v2_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip`
- 실제 Gerber 드릴·모서리 및 잔여 CAM 차이 감사: `output/candidates/corner-holes-inward/actual-gerber-final-audit.json` (방향 보정 전 ZIP의 기구/구리 감사; 실크 정상 읽기 검증은 아래 v2만 유효)
- 최종 방향 보정 후 실제 Gerber 감사: `output/candidates/corner-holes-inward/actual-gerber-direction-v2-audit.json` — 보정 전 대비 6층 구리·외곽의 해석 형상 및 드릴 그대로, 바닥 실크만 보정. 793개 드릴/23개 모서리 폐곡선 검증과 미확정 CAM 차이 주의사항은 유지.
- J18 실제 Gerber 뒷면 미리보기: `output/candidates/corner-holes-inward/j18-direction-v2-actual-gerber-backside.png` — 실제 뒷면 투영에서 정상 읽기 확인
- 뒷면 실크 자동 반전 구현 근거: `output/candidates/adc-dc-buffer/installed-pcb-bottom-text-mirror-audit.json`
- 모서리 실제 Gerber 미리보기: `output/candidates/corner-holes-inward/corner-1-actual-gerber.png` ~ `corner-4-actual-gerber.png`

회로도 표시 검토는 저장된 실제 소스와 프로젝트 심볼을 이용한 오프라인 렌더입니다. 해당 시점의 네이티브 SVG 내보내기는 시간초과되어 새 SVG로 검증했다고 주장하지 않습니다. 전기 검증은 실제 저장·재개방 소스와 네이티브 ERC/넷리스트에 근거합니다.

최종 전체 백업 SHA-256: `8b0cc407cfe833c47e9c6be3d6c9c967b726a47aaa52edac716bae137058c1b9`.

최종 재개방 PCB 소스 SHA-256: `106a37094bd8b2a383af5c7fb76101a64ade8cb55e3d55dda590abebfbc1f7a9`.
