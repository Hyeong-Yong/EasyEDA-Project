# EasyEDA Bridge 실행

`Start-EasyEDA-Bridge.bat`을 더블클릭합니다. 실행 위치와 Windows 사용자 이름에
관계없이 배치 파일이 있는 폴더를 기준으로 동작합니다.

## 새 컴퓨터 준비

1. Node.js LTS와 Git for Windows를 설치합니다.
2. 이 프로젝트를 clone합니다.
3. `Start-EasyEDA-Bridge.bat`을 실행합니다. 최초 실행에는 인터넷이 필요합니다.
   EasyEDA 공식 Bridge와 lockfile 기준 npm 의존성을 `.tools/easyeda-api`에
   내려받습니다. 이후에는 설치된 파일을 사용합니다.
4. EasyEDA Pro에서 **Run API Gateway** 확장을 설치하고 활성화합니다.
   외부 상호작용(External Interaction) 권한도 켭니다.
   확장 다운로드: <https://jlcext.com/item/oshwhub-official/run-api-gateway>
5. Bridge 창의 EDA 연결 메시지를 확인합니다. 서버 실행과 EasyEDA 연결은 별개입니다.

Node는 일반 설치 경로, PATH, WinGet 경로에서 자동 탐색합니다. 일반적인 설치라면
컴퓨터를 옮겨도 배치 파일을 수정할 필요가 없습니다.

## 컴퓨터별 경로 지정

특수한 설치 경로를 사용할 때만 `EasyEDA-Bridge.local.cmd.example`을
`EasyEDA-Bridge.local.cmd`로 복사하고 필요한 `set` 줄의 `rem`을 제거합니다.

```bat
set "EASYEDA_NODE_EXE=D:\Tools\nodejs\node.exe"
set "EASYEDA_BRIDGE_SCRIPT=D:\Tools\easyeda-api\scripts\bridge-server.mjs"
```

두 변수는 각각 선택 사항입니다. 외부 Bridge 경로를 지정하면 해당 Bridge의 npm
의존성은 그 설치 폴더에서 따로 준비해야 합니다. 환경변수로도 지정할 수 있습니다.

## Git 관리

- 공유: 배치 파일, `scripts/Start-EasyEDA-Bridge.ps1`, 설정 예제, 이 문서, `.gitignore`.
- 제외: 컴퓨터별 `EasyEDA-Bridge.local.cmd`, 다운로드한 `.tools/` 전체.

공통 실행 파일 자체를 ignore하지 않습니다. 로컬 설정은 컴퓨터마다 별도로 만듭니다.

## 검증과 버전

서버를 켜지 않고 설치/실행 준비 상태를 확인하려면:

```bat
Start-EasyEDA-Bridge.bat -Check
```

공식 소스: <https://github.com/easyeda/easyeda-api-skill>

Bridge는 커밋 `20e08dd62ec4faa5eb527332df2c29c9dc0fbaf4`로 고정합니다.
업데이트는 공통 PowerShell 파일의 버전을 검토해 변경한 뒤, 기존 `.tools/easyeda-api`
폴더를 다른 곳으로 옮기고 재실행합니다. 버전이 다르면 자동 덮어쓰기 대신 오류를 표시합니다.

서버는 `127.0.0.1`의 49620~49629 중 사용 가능한 포트에서 실행됩니다.
실행 후 `http://127.0.0.1:49620/health`를 확인할 수 있습니다. 해당 포트를 이미
다른 프로그램이 사용한다면 Bridge 창에 표시된 포트를 사용합니다.
