# STM32H747 MCU Board - EasyEDA Pro 작업환경

이 폴더는 기존 `TEST_DAC8562` 작업과 완전히 분리된 STM32H747 보드 전용 작업영역입니다. 모든 브리지 파일, 캐시, 출력물, 백업은 이 폴더 아래에만 둡니다.

2026-10-19 최신 값·조달 검토는 [표준 저항 검토 보고서](output/standard-values-20261019/index.html)와 [Excel](output/standard-values-20261019/STANDARD_VALUES_REVIEW.xlsx)이 우선합니다. 25개 품번 지정/13개 명목값 변경을 원본에 저장했고 엄격 PCB DRC는0입니다. ERC는 공급사 속성 경고1그룹(5부품)이 남으며,107개 기타 구매 후보/70개 복합·극성 CPL 회전 및 외부 제조 승인은 추가 검토 대상입니다. 아래10-18 전달식·검사 기록은 과거 이력입니다. 같은 XY 저항5쌍은 실제 서로 다른 구리면의 부품임을 CAM에서 확인했습니다.

최신 3D 실장 보기와 모델 의존성은 [3D 모델 상태](config/3d-model-status.md)를 확인하십시오. 412개 실장 대상 모델을 연결했고 최종 복구본은 `output/checkpoints/STM32H747_3d_models_412_20261018.epro2`입니다. 전용 STEP 5개는 [세션 로더](native-project/model-library/README.md)가 필요합니다. 패키지 대응 모델/원본의 저항 5쌍 중첩은 제조 전 별도 검토 대상입니다. 2026-10-19 게시 목록은 `config/publication-manifest-20261019.json`이며, TEST_DAC8562를 포함하라는 사용자 지시에 따라 두 프로젝트의 작업 이력을 함께 보존합니다. 과거 WIP·실패·pending 자료의 보존은 제조 승인을 뜻하지 않습니다.

2026-10-18 최신 작업은 [LabTool 원리 ADC 변경 상태](config/labtool-adc-status.md)를 우선 확인하십시오. 10채널 GND 기준 입력/DC·60 Hz 저잡음 회로도와 PCB 변경·배선·저장을 완료했고 전체 ERC/엄격 DRC는 모두 0건입니다. 437부품·1,342핀 전수 일치와 704비아/863드릴·6층·기구·J18 보존도 검증했습니다. 최종 전체 복구본은 `output/checkpoints/STM32H747_labtool_adc10_routed_final_20261018.epro2`입니다. 실제 잡음·기동·정착시간과 전체 CAM/제조 승인은 별도이며 아래 과거 WIP 결과와 구분하십시오.

## 기준 설계 자료

편집 가능한 KiCad/EasyEDA 원본은 제공되지 않았습니다. 최신 PDF의 회로 의미와 벡터 형상으로 회로도를 재작성했습니다. PCB는 이 회로도의 연결 데이터를 사용하고 구판 Gerber의 외형·배치·구리 형상을 참고해 만든 편집 가능한 재구성본입니다. PCB 제조 검증은 아직 완료되지 않았습니다.

- 회로도 기준본: `보드 자료/MCU_BOARD_v19_260827.pdf` - 6페이지, A3 가로
- 구판 비교본: `보드 자료/MCU_BOARD_v19_260616.pdf`
- PCB 제조 참고: `보드 자료/MCU_BOARD_v19_260616_Gerber/` - 2026-06-16, 6층
- PCB 시각 참고: `보드 자료/MCU_BOARD_Gerber.pdf`
- 기구 참고: `보드 자료/MCU_BOARD.step`

최신 회로도는 2026-08-27 판이지만 Gerber는 2026-06-16 판입니다. 두 자료의 넷리스트가 일치한다고 가정하지 않습니다. STEP도 별도 시점의 기구 참고자료입니다.

두 회로도 PDF를 200 dpi로 비교한 결과 1-4페이지는 픽셀 단위로 동일하고, 5-6페이지만 변경되었습니다. 핵심 변경 내용은 `config/revision-diff.md`에 기록했습니다.

EasyEDA 공식 참고:

- 형식 변환기: https://prodocs.easyeda.com/en/import-export/easyeda-pro-format-converter/
- Gerber는 소스 설계 파일이 아니라는 안내: https://prodocs.easyeda.com/en/faq/fabrication/
- 공식 API 브리지: https://github.com/easyeda/easyeda-api-skill

원본 PDF 1페이지 표지/계층 인덱스는 사용자 요청에 따라 네이티브 프로젝트에서 삭제했습니다. 실제 작업 대상은 원본 2~6페이지의 A3 가로 회로도 5장입니다. 모든 작성 페이지에서 `TECHLABS CO.,LTD` 회사명과 로고를 제외하는 것이 완료 조건입니다.

## 회로도 페이지 구성

| 원본 PDF | EasyEDA 페이지명 | 기준 내용 |
|---:|---|---|
| 2 | `02_MCU` | STM32H747 MCU 및 디버그/클록/부트 |
| 3 | `03_MCU_POWER` | MCU 전원과 전원 레일 |
| 4 | `04_SDRAM` | MEMORY - SDRAM |
| 5 | `05_ENET_USB_VCP` | Ethernet, USB, VCP |
| 6 | `06_ADC_TIMER_DAC` | ADC, Timer, DAC, SPI, SMA I/O |

고해상도 페이지 기준 이미지는 `reference/schematic-pages/v19_260827/`에 생성합니다. 세부 진행 상태와 검증 항목은 `config/page-plan.md`에서 관리합니다.

- 현재 환경 준비 상태: `config/setup-status.md`
- 페이지별 회로 블록/부품 범위: `config/page-components.md`
- 판본 차이: `config/revision-diff.md`

## 설치된 환경과 브리지

- EasyEDA Pro: 3.2.206 실행 확인
- Node.js: 24.20.0 확인
- Git for Windows: 2.52.0 확인
- API 브리지: 공식 저장소 커밋 `20e08dd62ec4faa5eb527332df2c29c9dc0fbaf4`로 고정
- 현재 API 브리지: `127.0.0.1:49620`

`Start-EasyEDA-Bridge.bat`은 이 폴더의 `.tools/easyeda-api`만 사용합니다. 최초 `-Check` 실행 시 공식 저장소와 npm 의존성을 이 폴더 안에 설치합니다.

### 중요한 격리 규칙

별도 EasyEDA 창의 `native-project/STM32H747_MCU_BOARD_v19.eprj2`를 사용합니다. 기존 브리지가 실행 중이면 그 프로세스를 그대로 두고 안전 클라이언트에서 명시적인 STM32H747 창 ID를 사용합니다. 이 폴더의 브리지 실행기는 다른 프로젝트/브리지를 감지하면 추가 서버 실행을 중단합니다. `-Check`는 서버를 시작하거나 EasyEDA 문서를 바꾸지 않고 설치 상태만 검증합니다.

EasyEDA Pro에는 공식 `Run API Gateway` 확장과 External Interaction 권한이 필요합니다. 다른 작업이 열려 있는 동안에는 확장 설치/변경 여부를 확인하지 않습니다.

### 준비 상태 확인

PowerShell 또는 명령 프롬프트에서:

```bat
Start-EasyEDA-Bridge.bat -Check
```

소스 체크섬, 기준 이미지 수, 브리지 버전을 한 번에 확인하려면:

```powershell
powershell -NoProfile -File .\scripts\Test-Workspace.ps1
```

### 실제 작업을 시작할 때

1. `native-project/STM32H747_MCU_BOARD_v19.eprj2`를 별도 EasyEDA 창에서 엽니다.
2. 이 창에서 Run API Gateway를 실행합니다.
3. 기존 브리지가 이미 실행 중이면 추가 브리지를 띄우지 않습니다.
4. `node scripts/easyeda-safe-client.mjs status`로 연결된 프로젝트 이름과 UUID를 확인합니다.
5. 이 창의 `windowId`를 `config/easyeda-project.json`의 `expectedWindowId`에 기록합니다.

프로젝트 잠금값은 `config/easyeda-project.json`에 기록되어 있습니다. 프로젝트 UUID는 `761c4fdb8e3e1a273a7eb212bd6961ba8b6efdb0e27d1b0c207735a7e696c24c`이며, 재접속 시 바뀔 수 있는 전용 창 ID는 해당 설정 파일에서 확인합니다. 모든 API 코드는 `scripts/easyeda-safe-client.mjs`를 통해 실행합니다. 이 클라이언트는 브리지 포트를 검색하고, 명시적 EasyEDA 창 ID와 프로젝트 이름/UUID를 두 번 확인한 뒤에만 `scripts/eda/` 아래 코드를 전달합니다. 다른 PC에서는 파일 경로와 전용 창을 다시 연결해야 합니다.

## 현재 검증 상태

### 최신 변경 — 전체 ADC 10채널 PCB 배선 / 엄격 DRC 0건 (2026-10-18)

사용자가 J11까지 포함하도록 확인하여 `06_ADC_TIMER_DAC`의 J2~J11 전체 10개 ADC 입력에 같은 DC 결합 레벨 시프트와 채널별 OPA320 버퍼를 적용했습니다. ADC1 3개, ADC2 3개, ADC3 4개입니다. 명목 변환식은 `VADC = 0.5 × VIN + 1.25 V`이며 입력 −2~+2 V를 0.25~2.25 V로 변환합니다. 입력/바이어스 저항은 6.8 kΩ 0.1%, 버퍼 전단은 10 nF, ADC 핀 앞은 47 Ω + 2.2 nF입니다. 직렬 AC 결합 커패시터는 추가하지 않았습니다. VDDA/VREF+ 전원 경로, MCU 핀 배정과 펌웨어는 그대로입니다.

모든 채널을 SMA→레벨 시프트→OPA320→47 Ω/2.2 nF→ADC 포트의 실제 연속 와이어로 배치했습니다. 미실장 R146/R147/R148/R158/R159/R160/R173/R174/R175/R176 및 회로도 전용 접지 가지를 삭제했습니다. 회로도 ERC 통과, 실제 넷리스트와 독립 계약 1,136핀/354부품 일치를 검증했습니다. 이번 작업은 이 회로도를 유지하고 PCB 배선/DRC를 우선 완료한 단계입니다.

사용자는 신호원이 출력 임피던스 50 Ω인 함수발생기이고 주로 60 Hz, 최대 1 MHz 이하임을 확인했습니다. 50 Ω 종단은 추가하지 않았습니다. **개방 시 ADC 핀 실제 0 V 기능은 아직 미반영이며 현재 약 2.5 V입니다.** 정상 입력 0 V는 ADC 약 1.25 V입니다. 현 전단 필터 약 4.68 kHz와 채널당 15.6 kS/s 설정은 1 MHz 파형 취득용이 아닙니다. 이 기능/대역폭 변경은 이번 PCB 완료와 별도이며, DRC 통과를 해당 성능 보증으로 해석하면 안 됩니다.

PCB의 Ø3.2 mm 모서리 홀 4개는 각 가장자리로부터 중심 4→5 mm로 이동했고, 해당 구리층의 여유 영역도 같이 이동했습니다. J18 뒷면에는 핀 번호와 SCK/PD3, MOSI/PB15, CSn/PC7, GND, +3V3 표기 및 `J18 SPI2` 식별 문구를 추가했습니다. 기존 CN1 1.92 mm 가공부와 외곽·나머지 드릴은 유지했습니다.

신규 34개 부품을 보드 안에 배치하고 10개 ADC 커패시터를 MCU 가까이 이동했습니다. 옛 바이어스/믹서 우회 구리를 분리하고 버퍼·기준전압·전원·접지 및 ADC 배선을 완료했습니다. 기존 접지 연결을 유지하면서 필요한 국부 구리 여유만 가공했습니다. 선택된 18개 다층 규칙을 완화하거나 검사를 제외하지 않았습니다. 전체 엄격 DRC는 **202 → 0건**, 저장 후 새 클라이언트로 다시 읽은 PCB에서도 **0건**입니다. 원래 비아 634개/기구 포함 드릴 793개는 유지하고 신호 비아 6개만 추가하여 현재 640비아/799드릴입니다.

최신 전체 복구본은 `output/checkpoints/STM32H747_adc10_routed_verified_20261018.epro2`, 편집용 작업 파일은 `native-project/STM32H747_MCU_BOARD_v19.eprj2`입니다. 최종 DRC는 `output/validation/native-pcb-drc-0ac2a19168000d8e-adc10_routed_reopened_20261018.json`입니다. 과거 WIP 및 중간 계획은 최신 상태가 아닙니다. 자동 close/open 호출은 응답 시간이 초과되어 재실행하지 않았고, 변경된 문서 클라이언트의 실제 소스와 전체 DRC를 별도로 읽어 재검증했습니다. 구리 형상은 동일하며 FILL의 빈 참조 배열 16개만 `[null] → null`로 정규화됐습니다.

**배선/네이티브 DRC 완료와 제조 승인은 별개입니다.** 개방 0 V·1 MHz 대역 요구, 기존 내층 Gerber의 추가 CAM 검토, 제조사 적층·비아 환형 폭·조립 및 실측 정착시간 검증이 남아 있습니다. 검증용 Gerber는 발주용이 아닙니다. 런타임·캐시·자동 백업과 대부분의 중간 출력은 Git에 포함하지 않습니다.

현재 변경 내용과 검증 근거는 [config/adc-dc-corners-j18-status.md](config/adc-dc-corners-j18-status.md)에 기록합니다. TEST_DAC8562 작업에는 변경이 없습니다.

### ADC 변경 전 다층 규칙 통과 기준본 — 이력

2026-10-16 CN1 기구 변경까지 적용한 다층 규칙 수정본 저장·재개방 및 전체 DRC 통과 확인 완료. 현재 선택된 `JLCPCB Capability(Multiple Layers Board)` 18개 규칙과 검사 범위를 그대로 유지했습니다.

- 실제 PCB DRC: 간격 오류 **2,119 → 0건**, 연결 오류 **0건**, 그 외 오류 **0건**. 승인된 CN1 내부 가공부 확대 후 전체 검사를 통과했습니다.
- 수정 범위: 비아 188개의 구리 Ø0.40 → Ø0.31 mm(드릴 Ø0.20 mm 유지), 배선 폭 최소 0.13 mm와 국부 경로, U4 90개 랜드 Ø0.4064 → Ø0.36 mm, 구리 영역 107개. 중첩 배선 병합 및 연속 중복 좌표 제거는 실제 구리 형상 보존을 확인해 별도 기록했습니다.
- 보존 검증: 회로도 5페이지와 상위 문서, 부품 330개 배치·라이브러리 연결, 넷 280개, 물리 PAD_NET 1,234개, 6층 적층, 드릴 793개의 위치·크기 유지. 새 PCB Protel2도 연결 핀 1,057/1,057개 일치했습니다.
- CN1 가공부는 2026-10-16 사용자 승인에 따라 1.80×1.80 → 1.92×1.92 mm로 확대했습니다. 기존 중심과 Ø1.30 mm 홀, 나머지 외곽·구리·회로·규칙을 보존했습니다.
- DRC 통과는 제조 승인과 별도입니다. 제조사 적층 Dk/Df·임피던스와 신호/전원 무결성, BGA 조립 조건 및 최종 CAM 검토가 필요합니다. 검증용 ZIP은 발주에 사용하지 마십시오.

최신 수정본 근거:

- [전체 체크포인트](output/checkpoints/STM32H747_multilayer_drc_pass_20261016.epro2)
- [최종 DRC — 전체 0건](output/validation/native-pcb-drc-0ac2a19168000d8e-cn1_cutout_192_20261016.json)
- [CN1 변경 및 전체 보존 감사](output/validation/native-cn1-cutout-final-preservation-audit.json)
- [구리 수정 단계 전체 보존 감사](output/validation/native-multilayer-geometry-preservation-audit.json)
- [최신 PCB 넷리스트 비교](output/validation/native-cn1-cutout-netlist-audit-20261016.json)
- [물리 적층 감사](output/validation/native-multilayer-physical-stack-audit.json)
- [최신 검증용 Gerber 드릴 감사](output/validation/native-cn1-cutout-gerber-drill-audit-20261016.json)
- [최신 Gerber 가공부·6층 구리 보존 감사](output/validation/native-cn1-cutout-gerber-audit-20261016.json) — CN1 4변만 1.92 mm로 변경, 바깥 100×154 mm 외곽·6층 구리·드릴 유지
- [외층 패드 중심·특수 패드 한정 감사](output/validation/native-multilayer-gerber-pad-centres-audit.json)
- [구리 영역 107개 전체 윤곽·홀·좌표 감사](output/candidates/multilayer-fill-clearance/native-multilayer-final-fill-path-audit.json)
- [실제 Gerber 변경 구리 한정 감사](output/validation/native-multilayer-gerber-changed-copper-audit.json) — U4 랜드 90개, 수정 비아 188개×6층, 변경 LINE 185개, 대표 FILL 5개의 홀·분리 조각 및 U4/D30 주변 간격. 전체 CAM DRC나 전체 구리 형상 동등성 검사는 아님

아래 `final_reconstruction` 자료와 2,119건 수치는 수정 전 재구성 기준본의 이력입니다.

### 수정 전 재구성 기준본 기록

최종 확인: 2026-10-15 (Asia/Seoul). 편집 가능한 재작성본 저장과 연결 검증은 완료했으며, 제조 승인 상태는 아닙니다.

- 네이티브 회로도 5페이지 작성 및 표지 삭제 완료
- ERC: Fatal 0, Error 0, Warning 0, Info 6. 정보 항목은 원본의 기구 홀/숨은 NC 항목
- EasyEDA Pro Protel2 넷리스트: 연결 핀 1,057개 기준본과 전수 일치. NC 110개는 Protel2 출력에서 생략되는 항목으로 별도 검증
- 최종 PCB `MCU_BOARD_PCB`: 회로도와 같은 `mcu_board`에 연결됨. 물리 부품 330개 모두 네이티브 편집 모델로 로딩하고 저장·재개방 확인
- PCB Protel2 연결 핀 1,057개 전수 일치. 이는 핀의 넷 배정 검증이며 실제 구리 연결·간격의 DRC 통과를 뜻하지 않음
- Gerber 참고 100×154 mm 외형, 13개 기구/비도금 홀, 6층 배치·구리 형상을 네이티브 모델로 적용. 최신 회로도에서 삭제한 직렬 커패시터 10개는 배치하지 않았고 해당 구리 연결 10곳도 최신 넷 기준으로 연결함
- 35개 풋프린트의 원호를 형상이 같은 호환 표현으로 수정함. 프로젝트 저장본에서 84개 원호 형상의 호환 POLY 변환 및 529개 패드 형상 보존 검증 통과
- 저장된 물리 적층: 구리 6층×0.035 mm, FR4 5층(0.10/0.515/0.10/0.515/0.10 mm), 양면 마스크 각 0.02 mm, 합계 약 1.58 mm. 전체 프로젝트 내보내기에서도 17개 적층 레코드 보존 확인
- 현재 PCB에만 `JLCPCB Capability(Multiple Layers Board)` 규칙 적용. 전역 기본값·다른 창은 변경하지 않음
- USB-C 다각형 패드 8개 좌표, 도금 장공 13개, U5/U7 추가 방열 PTH 8개, SMA 추가 접지 PTH 48개, SW1 추가 SMD 패드 2개 복원 및 저장본 검증 완료. 같은 핀 번호를 가진 여러 물리 패드도 부품 소속을 유지함
- 전체 330개 부품의 물리 패드 1,234개와 별도 비도금 패드 4개 확인. SMA 내층 미사용 패드 설정 및 U5/U7 층별 중앙 패드 형상 보존 확인
- 최종 PCB DRC: Connection Error 0, Clearance Error 2,119, 그 외 오류 0. 간격 오류가 남아 있으므로 DRC 전체 통과는 아님
- 검증 전용 네이티브 Gerber ZIP을 내보냄. 드릴 793개(도금 원형 767, 도금 장공 13, 비도금 13)가 기준 위치·크기와 허용오차 0.002 mm 내 전수 일치(최대 위치/슬롯 끝 오차 약 0.000707 mm). 이 검사는 제조 승인이나 전체 구리 형상 검증을 대신하지 않음
- 실제 EasyEDA SVG 5페이지를 다시 내보내고 200 dpi 기준 영상과 시각 검토 완료

회사명과 로고는 5페이지에서 제거했고 저장·재개방 확인을 마쳤습니다. 심볼 483개, 핀 1,312개, 채움 벡터 10,612개의 표시 보정은 전기 데이터 보존 검증을 통과했습니다. 실제 최종 SVG는 삭제 요청 영역을 제외한 3픽셀 허용 오차 비교에서 기준 도형 커버리지 100%, 출력 도형 정밀도 99.85~99.96%였습니다. NC/DNP 보조 표시의 기본 색상·스타일은 원본과 일부 다르며, 전기적 NC/DNP 상태는 유지했습니다. 따라서 픽셀 단위로 완전히 동일하다는 의미는 아닙니다.

PDF의 글자 모양은 정적 POLY 벡터로 보존되므로 화면에 보이는 글자는 일반 편집 가능한 동적 텍스트가 아닙니다. 부품의 값/레퍼런스 속성은 네이티브 데이터로 편집 가능하지만 변경 시 대응하는 표시 벡터도 별도로 수정해야 합니다.

### 최종 파일과 검증 근거

- 작업 원본: [native-project/STM32H747_MCU_BOARD_v19.eprj2](native-project/STM32H747_MCU_BOARD_v19.eprj2)
- 전체 프로젝트 체크포인트: [STM32H747_final_reconstruction_20261015.epro2](output/checkpoints/STM32H747_final_reconstruction_20261015.epro2)
- 최종 회로도 ERC: [native-schematic-final-erc-20261015.json](output/validation/native-schematic-final-erc-20261015.json)
- 최종 PCB 연결 핀 비교: [native-final-pcb-netlist-20261015-check.json](output/validation/native-final-pcb-netlist-20261015-check.json)
- 물리 패드 위치 비교: [native-final-component-copper-centres-audit.json](output/validation/native-final-component-copper-centres-audit.json)
- 최신판 변경 반영: [native-final-reconstruction-latest-revision-gap-audit.json](output/validation/native-final-reconstruction-latest-revision-gap-audit.json)
- 저장된 물리 적층: [native-final-physical-stack-audit.json](output/validation/native-final-physical-stack-audit.json)
- 최종 DRC 원본: [native-pcb-final-reconstruction-20261015-drc.json](output/validation/native-pcb-final-reconstruction-20261015-drc.json)
- 간격 오류 분류: [native-final-clearance-disposition-20261015.json](output/validation/native-final-clearance-disposition-20261015.json)
- 실제 Gerber 드릴 비교: [native-final-diagnostic-gerber-drill-audit.json](output/validation/native-final-diagnostic-gerber-drill-audit.json)
- 실제 Gerber 구리층 한정 검사: [native-final-diagnostic-gerber-copper-audit.json](output/validation/native-final-diagnostic-gerber-copper-audit.json) — 6층 파일, 외층 부품 패드 중심 1,353/1,353개, SMA 내층 패드 유무와 U5/U7 층별 특수 패드 확인. 전체 구리 폴리곤 동등성 검사는 아님
- 회로도 시각 비교: [native-svg-final-pixel-qa.json](output/validation/native-svg-final-pixel-qa.json)

### 수정 전 기준본의 미통과 항목과 진단 이력

간격 오류 2,119건은 현재 PCB에 선택한 다층 제조 규칙에 대한 실제 미통과 항목입니다. 전부 양의 간격이며 DRC가 보고한 0/음수 간격은 없습니다. 구판 Gerber Job을 참고한 비교용 0.10 mm 진단 기준과 현재 규칙(주요 구리 간격 약 0.152 mm, 객체별 예외 있음)이 다릅니다. Job은 외층 pad/track/region과 내층 track/region에 0.10 mm를 선언하지만 내층 일부 항목은 0 또는 미기재여서 보편적인 제조 승인 기준이 아닙니다. 2,078건은 0.10 mm 이상이지만 현재 규칙에는 미달하고, 41건은 수치상 0.10 mm 바로 아래입니다(최솟값 0.09999853 mm). 이것만으로 단락이 없거나 제조 가능하다고 승인하지 않습니다.

이 기록 이후 사용자가 다층 규칙 레이아웃 수정 및 CN1 기구 변경을 승인해 위의 DRC 전체 0건 상태까지 진행했습니다. 규칙은 낮추지 않았습니다. 적층 Dk/Df는 원자료에 없어 기본값이며 임피던스 검증도 필요합니다.

`output/validation/STM32H747_DIAGNOSTIC_NOT_FOR_FAB.zip`은 검증 전용이며 발주에 사용하지 마십시오. EasyEDA가 `Drill_PTH_Through.DRL`의 비아 634개를 `Drill_PTH_Through_Via.DRL`에도 별도 중복 출력했습니다. 드릴 793개 비교는 전체 PTH 파일과 NPTH 파일을 기준으로 했고, 별도 Via 파일이 전체 PTH의 부분집합인 것도 확인했습니다. 제조용 파일을 준비할 때는 중복 드릴을 이중 적용하지 않도록 출력 구성을 다시 확인해야 합니다. 제조 주문은 하지 않았습니다.

## 페이지별 완료 조건

각 페이지마다 다음 순서로 완료합니다.

1. 기준 PDF와 같은 A3 가로 시트 및 제목 블록 설정
2. 심볼/레퍼런스/값/핀 번호/NC 상태 대조
3. 넷 라벨, 버스, 계층 포트, 전원 플래그 대조
4. ERC 실행 및 의도된 예외 기록
5. EasyEDA 네이티브 백업 저장
6. 페이지 SVG 또는 PDF 내보내기
7. 기준 이미지와 시각 비교
8. 추출 넷리스트 및 부품 목록 비교

PCB 제조 완료 판정은 라우팅 적용, DRC, 회로도-보드 넷리스트 비교, 최종 제조 출력 검증을 모두 통과한 뒤에만 합니다.

## 폴더 구조

```text
STM32H747 board/
  보드 자료/                  원본 참고자료(수정 금지)
  reference/                  페이지별 렌더링 등 읽기용 기준자료
  config/                     소스 목록과 페이지 체크리스트
  scripts/                    독립 브리지 실행 스크립트
  backups/                    EasyEDA 체크포인트
  output/                     검증 결과와 최종 내보내기
  tmp/                        재생성 가능한 임시 파일(Git 제외)
  .tools/                     독립 API 브리지(Git 제외)
```

