# STM32H747 표준 저항 재검토 · 2026-10-19

`index.html`과 `STANDARD_VALUES_REVIEW.xlsx`가 최신 검토 자료다. 사용자의 표준값 재검토 선택에 따라 25개 저항의 실제 품번을 지정하고, 13개 명목값을 회로도와 PCB에 저장했다. 값과 최종 사양은 `standard-resistors-final-specs.json`이 우선한다.

- 입력10개: 4.00k→4.02k, 피드백2.80k10개 유지.
- R197/R200: 4.7Ω 유지, Vishay 0.2W / 100ppm/K 제품.
- R201: 1.0Ω→1.2Ω. LCSC 상품 페이지와 EasyEDA 카탈로그의400ppm/K 상한으로 최종 보정·계산했다.
- R202/R203: 15.8k/10.0k→14.7k/9.31k, 0.1%/10ppm/K.

명목 전달식은 `VADC = 1.6445832 − 0.6965174 × VIN`이다. 이득 크기 변화−0.4975%, 영점 변화−2.704mV이며 합성−3dB 대역은 약3.31kHz로 같다. VIN은 실제 SMA 전압이다. 개방 또는 입력0V의 ADC 출력은 약1.645V다. 펌웨어·실측 보정은 변경하지 않았다.

전체3,941문서/라이브러리/437부품/1,523 PAD_NET/704비아/18규칙/6층/기구/배선/라벨 위치를 보존했고, 엄격 PCB DRC는0이다. ERC는 치명/오류0, 공급사 속성 경고1그룹(5개)이며 전부0으로 표현하지 않는다. 내보낸 Gerber는 실제 도형, 드릴은 가공 명령이 이전 검토본과 같다. 다른 순서의 같은 dark 도형 및 사용하지 않는 aperture 번호 차이는 형상 차이와 구별했다.

`native/final/`만 이번 검증 후 추출한 최종 검토 파일이다. 전체 원본은 `STM32H747_standard_values_verified_20261019.epro2`이며 변경 전 복구본도 함께 보존한다. `BOM_NATIVE.csv`와 `CPL_NATIVE.csv`는 native 원시 출력이다. 원시 BOM에는 기존 라이브러리 품번 상속이 누락될 수 있고, 원시 CPL은 내장된 회전/실장면 문제를 보정하지 않으므로 그대로 주문 파일로 쓰지 않는다.

`BOM_CANDIDATE_REVIEW_ONLY.csv`는412개 실장 후보의 지정 품번과107개 기존 구매 제안을 합친 검토 후보이다. `CPL_CANDIDATE_REVIEW_ONLY.csv`는 실제 실장면 Top333/Bottom79 및 비극성2핀 축 보정을 유지한다. 복합·극성70개 회전,107개 신규 구매 제안의 JLC 매칭/재고 예약, ERC 속성 경고5부품, 적층 및 외부 DFM 승인은 남았다. 현재 자료는 제조/실장 최종 승인본이 아니다.

`standard-resistors-plan.json`은 최초 적용 계획이며 이후 R201 TCR 및 카탈로그 표기 보정에 의해 일부 내용이 대체됐다. `*-receipt.json`의 실패·복구 이력은 그대로 보존한다. 원시 시험 소스/다운로드 HTML/중간 내보내기는 로컬에만 남긴다. 적용·복구 스크립트는 일회성 이력이므로 재실행하지 않는다. 읽기 전용 보고서 재생성·감사는 `scripts/audit-standard-values-20261019.py`, `scripts/build-standard-values-report-20261019.py`, `scripts/build-standard-values-workbook-20261019.mjs`를 사용한다. Git의 artifact 바이트 보존 설정은 SHA-256 검증을 위해 필요하다.
