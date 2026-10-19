# STM32H747 3D 모델 작업 — 2026-10-18 실장 보기 완료

## 2026-10-19 제조 파일 대조에 따른 실장면 판정 정정

아래 과거의 “같은 면 저항 중첩” 판정은 COMPONENT의 layerId만 사용한 관찰이며 실제 구리면을 나타내지 않는다. 현재 embedded footprint의 PAD와 새 Gerber를 대조하면 R78/R79/R80/R81/R82는 앞면, R93/R92/R87/R84/R83는 뒷면이다. 동일 XY의 서로 다른 면이므로 해당 5쌍을 삭제·이동하지 않았다. 실제 면의 근거는 `output/jlcpcb-20261019-review/CAM_AUDIT.json`과 `PLACEMENT_AUDIT.json`이다.

현재 실장 후보 412개는 실제 패드 면 기준 Top 333개 / Bottom 79개다. 원시 네이티브 CPL과 3D 보기의 COMPONENT 면/각도를 그대로 제조 지시로 사용하지 않는다. 후보 CPL은 실제 면을 반영했으며 복합·극성 부품의 핀 1/회전 매칭은 아직 제조 승인 전이다. 회로도와 STM32 원본 배치·구리는 이번 주문 준비에서 수정하지 않았다.

현재 작업 범위는 PCB 부품의 3D 참조/제목/변환값이다. 회로도, 부품 배치, 배선 설계, 6층/18규칙, 기구 치수는 변경 대상이 아니다. TEST_DAC8562 문서·파일·브리지 기본 창·설정은 변경하지 않는다.

- 수정 전 전체 체크포인트: `output/checkpoints/STM32H747_before_3d_models_20261018.epro2`
- 총 437개 부품 중 실제 형상 대상 412개. DNP 6개(C33/R61/R64/R98/R125/R126)와 bare TP 19개는 제외한다.
- 407개 시스템 라이브러리 모델은 명시적 크기·방향·높이 보정 및 실제 OBJ 형상 검증을 완료했다. 검증 색인은 `output/3d-models-20261018/audits/final407-geometry-verification-index.json`이다. 일부는 정확 MPN이 아닌 패키지 대응 모델이며 제조공차/기구 간격 인증이 아니다.
- 407개 단계 저장본: `output/checkpoints/STM32H747_3d_models_calibrated407_20261018.epro2`. 3,941문서 분류 감사는 `audits/checkpoint-scope-calibrated407-exact-classified.json`이며 회로·패드·전기 연결·기구 형상을 보존했다. footprint 2개에 빈 NET 기본 metadata가 1개씩 추가된 차이를 명시한다.
- CN1/CN2/CN3/CN4/L1 전용 STEP은 `native-project/model-library`에 준비했다. 승인된 검색 경로 추가를 시도했으나 앱 전체 재시작 요구에 따라 취소했고, 재확인한 설정에는 기존 경로만 남아 있다. TEST_DAC8562 보호를 위해 전체 재시작하지 않았다.
- 공식 `registerExtendLibrary`를 이용한 STM32 전용 런타임 라이브러리 등록에 성공했고 CN1 시범 실측 후 5개 전체를 적용했다. 현재 412개 모델 모두 명시적 변환값으로 연결·저장했다. 이 기능은 세션 의존적이며 영구 검색 경로 등록과 구분한다.
- 런타임 모델 로더: `scripts/eda/load-stm32-public-3d-library-20261018.mjs`. 모든 콜백에서 정확한 STM32 프로젝트 이름/UUID와 전용 파일 SHA를 확인한다. 새 실행 시 로더를 다시 실행해야 하며 반환 library UUID가 달라지면 5개 참조를 새 계획으로 다시 연결해야 한다. 자동 영구 재연결을 주장하지 않는다.
- 현재 공개 시스템 모델은 외부 라이브러리 참조이다. 프로젝트 체크포인트가 STEP/OBJ 원본 형상을 내장한다고 주장하지 않는다.
- 407개 단계에서 네이티브 편집기가 기존 LINE 16개를 같은 전기·물리 경로의 32개 선분으로 직렬화하고 zIndex를 초기화했다. 정확한 유리수 중심선 합집합 보존을 감사했으며, 모든 레코드가 바이트 단위 동일하다고 주장하지 않는다. 고정 예외는 `output/3d-models-20261018/audits/line-reserialization-calibrated407-reviewed.json`이다.
- 407개 보정 완료 단계 strict 네이티브 DRC: 0건. 증거 `output/3d-models-20261018/audits/native-drc-model-stage-calibrated407.json`.
- 최종 412개 단계 strict 네이티브 DRC: 0건. 증거 `output/3d-models-20261018/audits/native-drc-model-stage-final412.json`.
- 최종 소스 `output/validation/pcb-3d-final412-20261018.epru` SHA256 `38914fb1d3ba32b849e81f86794cd80af28fdbcb26e6307d17b08d6afbd047af`. 정확 412개 모델/6개 최종 계획의 문자열과 비3D 전수 보존을 확인했다. 증거 `output/3d-models-20261018/audits/model-metadata-final412-reviewed-case-reuse.json`.
- 최종 전체 체크포인트 `output/checkpoints/STM32H747_3d_models_412_20261018.epro2` (21,187,530 bytes). STEP/OBJ 원본과 런타임 라이브러리가 프로젝트에 내장되는 것은 아니다. 재실행 시 위 로더가 필요하다.
- 최종 저장본 SHA256 `938b9d8b35b41ffb993433892a83609ebdf813bdbf6b04b1398d19d781c6bebb`. 3,941문서 분류/412개 모델 저장 감사 PASS: `output/3d-models-20261018/audits/checkpoint-scope-final412-exact-classified.json`. 비PCB 3,938문서는 정확히 동일하고 나머지 2개 footprint에는 앞서 기록한 빈 NET 기본값만 추가됐다. 새 세션 재등록·재연결 성공까지 검증한 것은 아니다.
- 최종 통합 검증 색인: `output/3d-models-20261018/audits/final412-geometry-verification-index.json`. 412개 실장 보기 형상 전부 확인, 미연결 0. 기존 407개+PCB의 760,928개 삼각형 좌표·재질은 정확히 보존됐고 추가 5개의 7,120개 삼각형은 전용 STEP에 대응한다.
- 전용 STEP 5개는 뷰어 위치·크기·방향·핀 깊이 확인을 통과했다. 네이티브 삼각분할은 원본 해석 STEP 표면과 최대 약 0.085 mm 차이가 있으므로 정밀 기구 적합성/핀 단면/실장면 일치를 인증하지 않는다. CN2 제조사 모델의 원본 footprint 등록은 근사이며 관련 편차도 자산 색인에 유지한다. 엄격 원본 일치 검사 실패 기록을 삭제하거나 제조 승인으로 바꾸지 않았다.
- 실제 EasyEDA 3D 화면 전달 이미지: `output/validation/STM32H747_assembly_412_top_native_capture_20261018.jpg`, `output/validation/STM32H747_assembly_412_bottom_native_capture_20261018.jpg`. 생성 이미지나 과거 보드 조립체 렌더가 아닌 최신 네이티브 뷰어의 원본 캡처다. PNG 내보내기 UI 시도에서 파일 생성을 확인하지 못했으므로 해당 PNG를 전달물로 표시하지 않는다.

## 원래 존재하던 실장 중첩 — 제조 전 별도 검토 필요

R78/R93, R79/R92, R80/R87, R81/R84, R82/R83는 이번 3D 작업 이전부터 같은 면/좌표에 겹쳐 있다. DNP=no이며 일부 서로 다른 넷도 포함한다. 네이티브 DRC 0건과 별개로 물리 실장/전기적 검토가 필요하다. 이번 3D 요청에서 임의로 부품을 이동하거나 삭제하지 않았다. 증거: `output/3d-models-20261018/audits/inherited-coincident-resistors.json`.

## 원본 모델 자료

원본 `보드 자료/MCU_BOARD.step`은 과거 전체 조립체로서 실제 부품 형상 추출에만 사용한다. 옛 PCB 형상·옛 배치·옛 BOM을 최신 PCB로 덮어쓰지 않는다. 별도 격리 CAD 커널과 검증된 파생 STEP/제조사 원본/해시는 `output/3d-models-20261018/source-models` 아래에 보존한다.
