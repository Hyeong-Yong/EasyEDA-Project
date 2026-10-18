# 회로도 페이지별 작업 계획

2026-10-18 최신 상태: 아래 초기 재작성 이후 `06_ADC_TIMER_DAC`에 J2~J11 전체 10채널 DC 결합 버퍼를 적용했습니다. 해당 페이지의 현재 소스는 `output/validation/native-adc10-sch-baseline-20261018.epru`, 최신 전체본은 `output/checkpoints/STM32H747_adc10_routed_verified_20261018.epro2`입니다. 회로도 ERC 및 354부품/1,136핀 SCH↔PCB 대조, PCB 전체 엄격 DRC 0건을 확인했습니다. 다른 4개 페이지는 이번 PCB 작업에서 변경하지 않았습니다. 세부 최신 상태는 `config/adc-dc-corners-j18-status.md`를 참조하십시오.

기준본은 `보드 자료/MCU_BOARD_v19_260827.pdf`입니다. 원본 1페이지 표지/계층 인덱스는 삭제했으며, 원본 2~6페이지를 같은 순서의 A3 가로 5페이지로 구성합니다. 상태 값은 `대기`, `작성 중`, `검증 중`, `완료` 중 하나로 관리합니다.

| 원본 PDF | EasyEDA 페이지명 | 상태 | 초기 재작성 검증 소스 (이력) | 기준 이미지 |
|---:|---|---|---|---|
| 2 | `02_MCU` | 완료 | `output/validation/native-root-visual-repair-page-2.epru` | `reference/schematic-pages/v19_260827/page-2.png` |
| 3 | `03_MCU_POWER` | 완료 | `output/validation/native-root-visual-repair-page-3.epru` | `reference/schematic-pages/v19_260827/page-3.png` |
| 4 | `04_SDRAM` | 완료 | `output/validation/native-root-visual-repair-page-4.epru` | `reference/schematic-pages/v19_260827/page-4.png` |
| 5 | `05_ENET_USB_VCP` | 완료 | `output/validation/native-root-visual-repair-page-5.epru` | `reference/schematic-pages/v19_260827/page-5.png` |
| 6 | `06_ADC_TIMER_DAC` | 완료 | `output/validation/native-root-visual-repair-page-6.epru` | `reference/schematic-pages/v19_260827/page-6.png` |

## 페이지 공통 검증표

- [x] A3 가로 시트와 제목 블록
- [x] 심볼 형상과 핀 번호
- [x] 레퍼런스와 부품 값
- [x] 패키지/MPN 메타데이터(확인 가능한 항목)
- [x] NC/DNP/JUMPER 상태
- [x] 전원 심볼과 PWR_FLAG
- [x] 넷 라벨과 계층 포트
- [x] 버스 이름과 범위
- [x] 접속점/비접속점
- [x] ERC 결과 검토: Fatal 0 / Error 0 / Warning 0 / Info 6
- [x] 회사명/로고 삭제 및 5페이지 저장·재개방 확인
- [x] 추가 WIRE/NET 문자 표시 수정 및 5페이지 저장·재개방 확인
- [x] 네이티브 백업 저장
- [x] 실제 EasyEDA SVG 5페이지 재내보내기 및 기준 영상 시각 비교
- [x] 부품 수와 넷리스트 비교: Protel2 연결 핀 1,057개 일치, NC 110개 별도 확인

## 설계 기준 잠금

원본 PDF 2~6페이지의 도면틀과 회로 표시 글리프는 EasyEDA POLY 벡터로 보존하고, 핀·부품·WIRE·NET은 별도의 네이티브 전기 객체로 작성했습니다. 표시 글리프는 정적 벡터이므로 속성 값을 바꿔도 일반 동적 텍스트처럼 자동 갱신되지 않습니다.

전기 검증과 실제 SVG 시각 검토를 완료했습니다. 회사명/로고, 추가 WIRE/NET 문자, 심볼의 PIN 바와 채움 외곽선 보정을 저장·재개방 확인했습니다. 삭제 요청 영역을 제외한 3픽셀 허용 오차 비교에서 기준 도형 커버리지 100%, 출력 정밀도 99.85~99.96%입니다. NC/DNP 보조 표시의 EasyEDA 기본 색상·스타일 차이는 남아 있으며 전기적 상태는 보존했습니다. 픽셀 단위 완전 동일을 뜻하지 않습니다.

- 회로도 값이 구판 PDF 또는 Gerber와 다르면 2026-08-27 PDF를 우선한다.
- 판독이 불가능한 항목은 추측하지 않고 `확인 필요`로 기록한다.
- 풋프린트는 실물/제조자료와 함께 확인하기 전까지 확정하지 않는다.

