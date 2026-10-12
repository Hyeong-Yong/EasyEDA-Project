param([switch]$Check)

$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$bridgeRevision = '20e08dd62ec4faa5eb527332df2c29c9dc0fbaf4'
$bridgeDirectory = Join-Path $projectDirectory '.tools\easyeda-api'

function Find-Node {
    if ($env:EASYEDA_NODE_EXE) {
        if (!(Test-Path -LiteralPath $env:EASYEDA_NODE_EXE -PathType Leaf)) {
            throw 'EASYEDA_NODE_EXE does not point to an existing node.exe.'
        }
        return $env:EASYEDA_NODE_EXE
    }
    $candidates = @(
        "$env:ProgramFiles\nodejs\node.exe",
        "$env:LOCALAPPDATA\Programs\nodejs\node.exe",
        "$env:LOCALAPPDATA\Microsoft\WinGet\Links\node.exe"
    )
    if (${env:ProgramFiles(x86)}) { $candidates += "${env:ProgramFiles(x86)}\nodejs\node.exe" }
    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_*\node-v*-win-*\node.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Node.js was not found. Install Node.js LTS, or set EASYEDA_NODE_EXE in EasyEDA-Bridge.local.cmd.'
}

try {
    $nodeExecutable = Find-Node
    $nodeVersion = & $nodeExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js could not run.' }
    Write-Host "Node: $nodeExecutable ($nodeVersion)"
    if ($env:EASYEDA_BRIDGE_SCRIPT) {
        $bridgeScript = $env:EASYEDA_BRIDGE_SCRIPT
        if (!(Test-Path -LiteralPath $bridgeScript -PathType Leaf)) {
            throw 'EASYEDA_BRIDGE_SCRIPT does not point to an existing bridge script.'
        }
        # Dependencies of a custom external bridge are managed by its owner.
    } else {
        $git = Get-Command git.exe -ErrorAction SilentlyContinue
        if (!$git) { throw 'Git is required to prepare the official bridge. Install Git for Windows, or configure EASYEDA_BRIDGE_SCRIPT.' }
        if (!(Test-Path -LiteralPath $bridgeDirectory)) {
            New-Item -ItemType Directory -Path (Split-Path -Parent $bridgeDirectory) -Force | Out-Null
            & $git.Source clone 'https://github.com/easyeda/easyeda-api-skill.git' $bridgeDirectory
            if ($LASTEXITCODE -ne 0) { throw 'Bridge download failed. Check the network and retry.' }
            & $git.Source -C $bridgeDirectory checkout --detach $bridgeRevision
            if ($LASTEXITCODE -ne 0) { throw 'Could not select the pinned bridge revision.' }
        }
        $actualRevision = & $git.Source -C $bridgeDirectory rev-parse HEAD
        if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $bridgeRevision) {
            throw "Bridge checkout does not match $bridgeRevision. Move .tools\easyeda-api aside and retry, or use EASYEDA_BRIDGE_SCRIPT."
        }
        $bridgeScript = Join-Path $bridgeDirectory 'scripts\bridge-server.mjs'
        if (!(Test-Path -LiteralPath $bridgeScript -PathType Leaf)) { throw 'Official bridge script is missing.' }
        $installedMarker = Join-Path $bridgeDirectory '.dependencies-ready'
        if (!(Test-Path -LiteralPath $installedMarker) -or !(Test-Path -LiteralPath (Join-Path $bridgeDirectory 'node_modules\ws\package.json'))) {
            $npm = Join-Path (Split-Path -Parent $nodeExecutable) 'npm.cmd'
            if (!(Test-Path -LiteralPath $npm)) { throw 'npm.cmd is missing beside node.exe. Install the full Node.js LTS distribution.' }
            $env:PATH = "$(Split-Path -Parent $nodeExecutable);$env:PATH"
            Push-Location $bridgeDirectory
            try {
                & $npm ci --ignore-scripts --no-audit --no-fund
                if ($LASTEXITCODE -ne 0) { throw 'Bridge dependency installation failed. Check the network and retry.' }
                Set-Content -LiteralPath $installedMarker -Value $bridgeRevision -Encoding ASCII
            } finally { Pop-Location }
        }
    }
    Write-Host "Bridge: $bridgeScript"
    & $nodeExecutable --check $bridgeScript
    if ($LASTEXITCODE -ne 0) { throw 'Bridge syntax check failed.' }
    if ($Check) {
        & $nodeExecutable --input-type=module -e "import {createRequire} from 'node:module'; const r=createRequire(process.argv[1]); r('ws');" $bridgeScript
        if ($LASTEXITCODE -ne 0) { throw 'Bridge dependencies could not be loaded.' }
        Write-Host 'Bridge is ready. Run Start-EasyEDA-Bridge.bat to start it.'
        exit 0
    }
    Write-Host 'Starting the bridge. Press Ctrl+C or close this window to stop it.'
    Push-Location (Split-Path -Parent $bridgeScript)
    try {
        & $nodeExecutable $bridgeScript
        $bridgeExit = $LASTEXITCODE
    } finally { Pop-Location }
    exit $bridgeExit
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
