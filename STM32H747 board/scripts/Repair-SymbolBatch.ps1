param([int]$Start = 19, [int]$EndExclusive = 99)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$client = Join-Path $PSScriptRoot 'easyeda-safe-client.mjs'
$validation = Join-Path $taskRoot 'output\validation'
if ($Start -lt 0 -or $EndExclusive -gt 483 -or $EndExclusive -le $Start) { throw 'Invalid verified symbol interval' }
for ($symbolOffset = $Start; $symbolOffset -lt $EndExclusive; $symbolOffset += 2) {
    $symbolCount = [Math]::Min(2, $EndExclusive - $symbolOffset)
    $symbolEnd = $symbolOffset + $symbolCount - 1
    $manifestPath = Join-Path $validation ('native-symbol-visual-repair-batch-{0:D4}-{1:D4}.json' -f $symbolOffset,$symbolEnd)
    $requestStart = Get-Date
    $symbolOutput = & 'C:\Program Files\nodejs\node.exe' $client execute-file 'scripts/eda/repair-project-symbol-visuals.mjs' $symbolOffset $symbolCount 2>&1
    $symbolExitCode = $LASTEXITCODE
    if ($symbolExitCode -ne 0) {
        $message = $symbolOutput -join "`n"
        if ($message -notmatch 'timed out|timeout') { throw $message }
        $deadline = (Get-Date).AddSeconds(120)
        while ((Get-Date) -lt $deadline) {
            if ((Test-Path -LiteralPath $manifestPath) -and (Get-Item -LiteralPath $manifestPath).LastWriteTime -ge $requestStart.AddSeconds(-1)) { break }
            Start-Sleep -Seconds 2
        }
        if (-not (Test-Path -LiteralPath $manifestPath) -or (Get-Item -LiteralPath $manifestPath).LastWriteTime -lt $requestStart.AddSeconds(-1)) {
            throw "Unknown native outcome; stopped without overlapping another write. $message"
        }
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    if ($manifest.offset -ne $symbolOffset -or $manifest.completedCount -ne $symbolCount) { throw 'Native reopened verification manifest mismatch' }
    Write-Output "Symbols $symbolOffset-$symbolEnd saved/reopened; verified=$($manifest.completedCount)"
}
