# 다층 제조 규칙 수정 상태 — 2026-10-16

## 최신 상태에 대한 주의

이 문서 아래의 수치와 파일은 ADC 변경 전 CN1 승인 반영 기준본의 이력입니다. 2026-10-18에는 전체 10채널 ADC ECO·배치·배선을 완료했으며, 동일한 18개 규칙의 전체 엄격 DRC 0건, 354부품/1,136핀 일치를 확인했습니다. 과거 Netlist Error 1건 및 이후 202건 WIP는 현재 상태가 아닙니다. 최신 상태는 `config/adc-dc-corners-j18-status.md` 상단과 `STM32H747_adc10_routed_verified_20261018.epro2`를 참조하십시오. 배선/DRC 완료와 제조 승인은 별개이며 검증 ZIP은 발주용이 아닙니다.

## ADC 변경 전 기준본 결과

`STM32H747_MCU_BOARD_v19` 전용 EasyEDA 창에서 수정본을 저장하고 재개방했습니다. TEST_DAC8562 문서·파일·브리지 기본 선택은 변경하지 않았습니다.

- 선택 규칙: `JLCPCB Capability(Multiple Layers Board)` 18개 그대로 유지
- 실제 DRC: Clearance **0**, Connection **0**, 기타 **0** — 현재 선택된 다층 규칙 전체 통과
- 수정 범위: 비아 188개 구리 Ø0.40 → Ø0.31 mm(드릴 Ø0.20 mm 유지), 배선 최소 0.13 mm 및 국부 경로, U4 랜드 90개 Ø0.36 mm, 구리 영역 107개
- 보존 확인: 회로도 5페이지·상위 문서, 부품 330개 배치/라이브러리 연결, 넷 280개, 물리 PAD_NET 1,234개, 물리 드릴 793개, 6층 적층
- 새 PCB Protel2: 기준 연결 핀 1,057/1,057개 일치. NC 110개는 해당 출력 형식에서 생략됨을 별도 계수
- Gerber 드릴: 793/793개 위치·크기 일치, 최대 위치/장공 끝 오차 약 0.000707 mm
- Gerber 외층 패드 중심 1,353/1,353개, SMA 층별 접지 패드 및 U5/U7 특수 패드 한정 검사 통과
- 수정 구리 영역 107개의 전체 윤곽/홀/순서/방향을 실제 적용한 최종 후보와 전수 대조. 비대상 623개 구리 영역은 body 완전 불변
- 실제 Gerber의 U4 랜드 90개, 수정 비아 188개×6층(1,128 flashes), 변경 LINE 185개의 크기·중심·경로 확인. 대표 FILL 5개의 홀/분리 조각 보존 및 U4/D30 주변 한정 간격 검사 통과(전체 CAM DRC 아님)
- 2026-10-16 승인된 CN1 가공부 확대 적용, 저장·재개방 및 전체 DRC 0건 확인. 새 전체 저장본과 넷리스트·드릴 재검증 통과
- 새 Gerber의 가공부도 1.92×1.92 mm로 확인. 기존 중심·바깥 100×154 mm 외곽 유지, 6층 구리 전체 형상과 드릴 출력은 이전 검증본과 동일

## 승인된 CN1 기구 변경 완료

사용자가 2026-10-16 명시 승인한 CN1 내부 사각 가공부 **1.80×1.80 → 1.92×1.92 mm** 확대를 적용했습니다. 기존 사각 중심과 Ø1.30 mm 비도금 홀은 그대로입니다. 네이티브 좌표로 표현된 크기는 1.91999870×1.92000124 mm이며, 중심 이동은 0입니다. 다층 규칙의 약 0.30 mm 요구 간격에 대해 약 0.31 mm를 확보했고 관련 4건을 포함한 실제 전체 DRC가 0건으로 통과했습니다.

- PCB UUID: `0ac2a19168000d8e`
- CN1 홀 객체: `8dfdc04036ba85c3e6`
- 외곽 POLY 4개: `5b55024cb3a23233`, `6e8dd66b3e3db1b0`, `e94386c2e1a58187`, `f614cce4900c7115`
- 승인 좌표 manifest: `output/candidates/cn1-cutout-192/cn1-cutout-192-plan.json`
- 적용 API 영수증: `output/validation/native-cn1-cutout-192-apply-receipt-20261016.json`
- 승인된 4개 POLY의 경로와 명시된 네이티브 zIndex 정규화 외의 비UI PCB/회로도/라이브러리/적층/드릴/규칙 변경 없음
- 완료 검사: 동일 18개 규칙의 실제 전체 DRC, 저장·재개방, 기구 치수·793개 드릴 보존, 새 전체 체크포인트·검증용 출력, 연결 핀 1,057개 전수 일치

## 최신 파일

- 작업 원본: `native-project/STM32H747_MCU_BOARD_v19.eprj2`
- 수정 전 백업: `output/checkpoints/STM32H747_before_multilayer_clearance_20261015.epro2`
- CN1 수정 전 백업: `output/checkpoints/STM32H747_before_cn1_cutout_192_20261016.epro2`
- 최신 수정본 백업: `output/checkpoints/STM32H747_multilayer_drc_pass_20261016.epro2`
- 최신 PCB 소스: `output/validation/native-multilayer-cn1_cutout_192_20261016-reopened.epru`
- 실제 DRC: `output/validation/native-pcb-drc-0ac2a19168000d8e-cn1_cutout_192_20261016.json`
- 최신 전체 보존 감사: `output/validation/native-cn1-cutout-final-preservation-audit.json`
- CN1 네 경로·중심·간격 독립 감사: `output/validation/native-cn1-cutout-192-postapply-static-audit-20261016.json`
- 구리 수정 단계 보존 감사: `output/validation/native-multilayer-geometry-preservation-audit.json`
- 최신 PCB 넷리스트: `output/validation/native-cn1-cutout-netlist-audit-20261016.json`
- 적층 감사: `output/validation/native-multilayer-physical-stack-audit.json`
- 최신 Gerber 드릴 감사: `output/validation/native-cn1-cutout-gerber-drill-audit-20261016.json`
- 최신 Gerber 가공부·6층 구리 보존 감사: `output/validation/native-cn1-cutout-gerber-audit-20261016.json`
- Gerber 패드 중심 감사: `output/validation/native-multilayer-gerber-pad-centres-audit.json`
- 구리 영역 107개 전체 경로 감사: `output/candidates/multilayer-fill-clearance/native-multilayer-final-fill-path-audit.json`
- 실제 Gerber 변경 구리 한정 감사: `output/validation/native-multilayer-gerber-changed-copper-audit.json`
- 최신 내보내기 후 비UI PCB 데이터 변경 없음: `output/validation/native-cn1-cutout-post-export-preservation-20261016.json`
- 최신 검증용 ZIP: `output/validation/STM32H747_multilayer_drc_pass_20261016_DIAGNOSTIC_NOT_FOR_FAB.zip`

최신 수정본 백업 SHA-256: `4ec5d37528c985430fe67b0230bc50eae9ef5ed62ecfd32dc0384c8122dd38af`.

최신 검증용 ZIP SHA-256: `9a9205244fcbcc592fbcb566f768f1ac6bbf494bb8f3c78c778452ffd018a2c1`.

## 주의

전체 DRC 통과와 제조 승인은 별도입니다. 제조사 적층 Dk/Df·임피던스, SI/PI, BGA 조립 조건과 최종 CAM 검토는 남아 있으며 이 ZIP은 검증 전용입니다. `Drill_PTH_Through_Via.DRL`의 비아 634개는 `Drill_PTH_Through.DRL`에도 포함되므로 함께 중복 가공하지 마십시오. 주문·결제는 하지 않았습니다.

전체 배치 실행과 검증은 `scripts/easyeda-safe-client.mjs`의 고정 창 ID·프로젝트 UUID 이중 가드를 사용했습니다. 기본 활성 창을 바꾸거나 다른 EasyEDA 작업을 중지하지 않았습니다. API의 자동 중첩 배선 정리와 FILL 재개방 시 정확한 연속 중복 좌표 제거는 복구 전/후 원본 및 검증 영수증에 보존했습니다.
