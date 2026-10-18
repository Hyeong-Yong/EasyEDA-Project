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
    $candidates += @(
        Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_*\node-v*-win-*\node.exe" -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    throw 'Node.js was not found. Install Node.js LTS, or set EASYEDA_NODE_EXE in EasyEDA-Bridge.local.cmd.'
}

function Find-Git {
    if ($env:EASYEDA_GIT_EXE) {
        if (!(Test-Path -LiteralPath $env:EASYEDA_GIT_EXE -PathType Leaf)) {
            throw 'EASYEDA_GIT_EXE does not point to an existing git.exe.'
        }
        return $env:EASYEDA_GIT_EXE
    }
    $command = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        "$env:ProgramFiles\Git\cmd\git.exe",
        "$env:ProgramFiles\Git\bin\git.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'Git for Windows was not found. Install it, or set EASYEDA_GIT_EXE in EasyEDA-Bridge.local.cmd.'
}

function Find-ExistingBridge {
    foreach ($stmPort in 49620..49629) {
        try {
            $stmHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$stmPort/health" -TimeoutSec 1
            if ($stmHealth.service -eq 'easyeda-bridge') {
                return @{ Port = $stmPort; Health = $stmHealth }
            }
        } catch { }
    }
    return $null
}

try {
    $nodeExecutable = Find-Node
    $gitExecutable = Find-Git
    $nodeVersion = & $nodeExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'Node.js could not run.' }
    $gitVersion = & $gitExecutable --version
    if ($LASTEXITCODE -ne 0) { throw 'Git could not run.' }
    Write-Host "Node: $nodeExecutable ($nodeVersion)"
    Write-Host "Git:  $gitExecutable ($gitVersion)"

    if (!(Test-Path -LiteralPath $bridgeDirectory)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $bridgeDirectory) -Force | Out-Null
        & $gitExecutable clone 'https://github.com/easyeda/easyeda-api-skill.git' $bridgeDirectory
        if ($LASTEXITCODE -ne 0) { throw 'Bridge download failed. Check the network and retry.' }
        & $gitExecutable -C $bridgeDirectory checkout --detach $bridgeRevision
        if ($LASTEXITCODE -ne 0) { throw 'Could not select the pinned bridge revision.' }
    }

    $actualRevision = & $gitExecutable -C $bridgeDirectory rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actualRevision -ne $bridgeRevision) {
        throw "Bridge checkout does not match $bridgeRevision. Move this workspace's .tools\easyeda-api aside and retry."
    }

    $bridgeCandidates = @(
        (Join-Path $bridgeDirectory 'scripts\bridge-server.mjs'),
        (Join-Path $bridgeDirectory 'server\index.mjs')
    )
    $bridgeScript = $bridgeCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (!$bridgeScript) { throw 'Official bridge server script is missing.' }

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
        } finally {
            Pop-Location
        }
    }

    Write-Host "Bridge: $bridgeScript"
    & $nodeExecutable --check $bridgeScript
    if ($LASTEXITCODE -ne 0) { throw 'Bridge syntax check failed.' }

    if ($Check) {
        & $nodeExecutable --input-type=module -e "import {createRequire} from 'node:module'; const r=createRequire(process.argv[1]); r('ws');" $bridgeScript
        if ($LASTEXITCODE -ne 0) { throw 'Bridge dependencies could not be loaded.' }
        Write-Host 'STM32H747 bridge is ready. No server was started and no EasyEDA document was changed.'
        exit 0
    }

    $stmExisting = Find-ExistingBridge
    if ($stmExisting) {
        Write-Host "Existing bridge is healthy on $($stmExisting.Port). No process was changed."
        Write-Host 'STM32H747 calls are routed only through the guarded client; other project/window selections remain untouched.'
        exit 0
    }
    $stmProcess = Start-Process -FilePath $nodeExecutable -ArgumentList ('"' + $bridgeScript + '"') -WorkingDirectory (Split-Path -Parent $bridgeScript) -WindowStyle Hidden -PassThru
    Write-Host "STM32H747 bridge started in the background (PID $($stmProcess.Id))."
    Write-Host 'The installed API Gateway reconnects automatically. No EasyEDA project was switched or closed.'
    exit 0
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

