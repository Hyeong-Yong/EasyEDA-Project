$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $workspace 'config\source-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$failures = [System.Collections.Generic.List[string]]::new()

function Test-SourceHash {
    param(
        [string]$RelativePath,
        [string]$ExpectedHash
    )
    $path = Join-Path $workspace $RelativePath
    if (!(Test-Path -LiteralPath $path -PathType Leaf)) {
        $failures.Add("Missing source: $RelativePath")
        return
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash
    if ($actual -ne $ExpectedHash) {
        $failures.Add("Hash mismatch: $RelativePath")
    }
}

Test-SourceHash $manifest.schematicSourceOfTruth.path $manifest.schematicSourceOfTruth.sha256
Test-SourceHash $manifest.comparisonSchematic.path $manifest.comparisonSchematic.sha256
Test-SourceHash $manifest.pcbReferences.gerberZip.path $manifest.pcbReferences.gerberZip.sha256
Test-SourceHash $manifest.pcbReferences.gerberReferencePdf.path $manifest.pcbReferences.gerberReferencePdf.sha256
Test-SourceHash $manifest.pcbReferences.step.path $manifest.pcbReferences.step.sha256

$renderDirectory = Join-Path $workspace $manifest.renderedSchematicReference.directory
$renderedPages = @(Get-ChildItem -LiteralPath $renderDirectory -Filter 'page-*.png' -File -ErrorAction SilentlyContinue)
if ($renderedPages.Count -ne $manifest.renderedSchematicReference.pages) {
    $failures.Add("Expected $($manifest.renderedSchematicReference.pages) rendered pages; found $($renderedPages.Count).")
}

$bridgeDirectory = Join-Path $workspace '.tools\easyeda-api'
if (!(Test-Path -LiteralPath $bridgeDirectory -PathType Container)) {
    $failures.Add('Independent EasyEDA bridge is not installed.')
} else {
    $gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
    $gitExecutable = if ($gitCommand) { $gitCommand.Source } else { "$env:ProgramFiles\Git\cmd\git.exe" }
    if (!(Test-Path -LiteralPath $gitExecutable -PathType Leaf)) {
        $failures.Add('git.exe is not available.')
    } else {
        $revision = & $gitExecutable -C $bridgeDirectory rev-parse HEAD
        if ($LASTEXITCODE -ne 0 -or $revision -ne $manifest.bridge.revision) {
            $failures.Add('EasyEDA bridge revision mismatch.')
        }
    }
    if (!(Test-Path -LiteralPath (Join-Path $bridgeDirectory 'node_modules\ws\package.json') -PathType Leaf)) {
        $failures.Add('EasyEDA bridge ws dependency is missing.')
    }
}

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
$nodeExecutable = if ($nodeCommand) { $nodeCommand.Source } else { "$env:ProgramFiles\nodejs\node.exe" }
if (!(Test-Path -LiteralPath $nodeExecutable -PathType Leaf)) { $failures.Add('node.exe is not available.') }
$easyeda = 'C:\Program Files\easyeda-pro\easyeda-pro.exe'
if (!(Test-Path -LiteralPath $easyeda -PathType Leaf)) { $failures.Add('EasyEDA Pro executable was not found.') }

if ($failures.Count -gt 0) {
    Write-Host 'STM32H747 workspace validation failed:' -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "- $_" -ForegroundColor Red }
    exit 1
}

Write-Host 'STM32H747 workspace validation passed.' -ForegroundColor Green
Write-Host "Sources: 5 verified"
Write-Host "Rendered schematic pages: $($renderedPages.Count)"
Write-Host "Bridge revision: $($manifest.bridge.revision)"
Write-Host 'No bridge server was started and no EasyEDA document was accessed.'

