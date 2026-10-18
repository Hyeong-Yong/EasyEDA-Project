# EasyEDA 실행 코드 위치

EasyEDA에 전달할 JavaScript 본문은 이 디렉터리에만 둡니다. 직접 HTTP 요청을 보내지 말고 상위의 안전 클라이언트를 사용합니다.

```powershell
node .\scripts\easyeda-safe-client.mjs status
node .\scripts\easyeda-safe-client.mjs execute-file scripts/eda/check-schematic-erc.mjs
```

안전 클라이언트는 다음 조건을 모두 만족할 때만 실행합니다.

1. 49620-49629에서 `easyeda-bridge` 핸드셰이크 확인
2. 연결된 모든 창에 명시적 `windowId` 사용
3. 프로젝트 이름 `STM32H747_MCU_BOARD_v19` 확인
4. `config/easyeda-project.json`에 UUID가 기록된 이후에는 UUID도 확인
5. 실제 코드 실행 직전에 EasyEDA 내부에서 같은 조건 재확인

`TEST_DAC8562`의 포트 고정 스크립트나 프로젝트 UUID를 복사하지 않습니다.

최종 회로도는 `416c10313f778784`, 최종 PCB는 `0ac2a19168000d8e`입니다. 기존 초기 PCB `3ca9811d1a42d086`, 직접 만든 staging/probe PCB는 검증된 백업을 남기고 제거했습니다. 이 디렉터리의 `probe-*`, `import-*`, `apply-*`, `repair-*`는 작성 과정의 기록이며 일반적인 재시작·연결 확인 용도가 아닙니다. 검증되지 않은 과거 소스를 최종 프로젝트 위에 재적용하지 마십시오.

2026-10-15 최종본은 부품 330개, 부품 소속 물리 패드 1,234개(별도 패드 포함 runtime 1,238개), 추가 방열 PTH 8개와 기타 복원 패드 50개가 포함됩니다. `create-missing-owned-pad-children.mjs` 등 생성 스크립트를 재실행하지 마십시오. 생성 영수증의 실제 패드 ID와 라이브러리 GUID는 이미 최종 프로젝트에 반영되어 있습니다. `output/native-libraries-durable-qa`는 생성기 검증용이며 최종 프로젝트 위로 재수입하면 안 됩니다.

`save-and-capture-final-pcb.mjs`의 최종 상태 검증 인수는 `final_reconstruction 8 50`입니다. 기본값이나 과거 단계의 수량으로 현재 최종본을 검사하지 마십시오. 최종 전체 체크포인트는 `output/checkpoints/STM32H747_final_reconstruction_20261015.epro2`입니다.

`export-diagnostic-final-pcb-gerber.mjs`는 검증 전용 ZIP을 생성하며 제조 주문 API를 호출하지 않습니다. 최종 DRC는 Connection 0 / Clearance 2,119이므로 제조용으로 승인되지 않았습니다. EasyEDA의 별도 Via 드릴 파일은 전체 PTH 파일과 중복이므로 전체 PTH + NPTH를 기준으로 드릴을 비교한 감사 결과를 확인하십시오.

