# 페이지별 회로 블록 및 부품 범위

기준: `MCU_BOARD_v19_260827.pdf`. 아래 목록은 재작성 시작점이며, 실제 완료 판정은 기준 이미지와 넷리스트 검증으로 합니다.

## 1 - 01_HIERARCHY

- `MCU BOARD REV 1.0` 표지
- 하위 블록 5개: `MCU#1`, `MCU#2`, `MEM`, `ENET USB VCP`, `ADC TIM SPI`
- TECHLABS A3 도면틀과 타이틀 블록

## 2 - 02_MCU

- `U1A/U1B/U1C STM32H747XIH6`
- 32.768 kHz 크리스털, 25 MHz 오실레이터
- SWD 14핀 헤더, Reset, Boot0
- 상태 LED 3개
- MCU 직렬저항/점퍼 및 미사용 핀 No Connect
- 주 레퍼런스 범위: `R1-R70`, `C1-C4`, `U1`, `J1`

## 3 - 03_MCU_POWER

- `U1D STM32H747XIH6` 전원 유닛
- MCU decoupling, 내부 SMPS, VCAP, VDDA/VREF, USB 전원 핀
- DC Jack `CN1`, +5 V 입력
- +3.3 V `ST1L05CPU33R`
- +1.8 V `LD1117S18TR`
- TVS, 전원 LED, `TP17-TP19`
- 주 레퍼런스 범위: `R71-R73`, `C5-C47`, `U2-U3`, `CN1`

## 4 - 04_SDRAM

- `U4 IS42S32160F-6BLI`
- 32-bit 데이터 버스, 주소 버스, `DQM0-DQM3`
- FMC/SDRAM 제어선
- `C48-C61` decoupling

## 5 - 05_ENET_USB_VCP

- `U5 LAN8742A` RMII Ethernet PHY
- RJ45/magnetics 및 ESD/termination
- `U7 USB3320C-EZK` ULPI PHY
- USB-C 커넥터 2개와 ESD 보호
- `U8 CH340C` VCP
- 24 MHz 오실레이터, USB 전원 스위치
- 주 레퍼런스 범위: `R74-R136`, `C62-C76`, `U5-U8`, `CN2-CN4`
- 최신판 주의: `C69 = 470p`, `R129` 주변 `NEED TO CHANGE BOM`

## 6 - 06_ADC_TIM_SPI

- ADC 입력 SMA 10채널
- Timer 출력 SMA 4개
- DAC 출력, MCO 출력
- 2×5 SPI 헤더 `J18`
- `TP1-TP16`
- 주 레퍼런스 범위: `R137-R176`, `C77-C96`, `J2-J18`
- 최신판 주의: ADC 상단 bias `7.5k`, 하단 `30k_NC`, 출력 `100R + 10n`

## 도면 기호 판독 규칙

- 빨간 X: DNP/NC 또는 미실장 부품 표시로 취급하고 속성에 반영
- 파란 X: MCU 미사용 핀의 No Connect로 취급
- 두 표시를 서로 바꾸지 않는다.

