param(
    [Parameter(Mandatory=$true)][string]$FirstStage,
    [Parameter(Mandatory=$true)][string]$LastStage
)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
if ((Get-Location).Path -ne $projectRoot) { throw 'Run from the STM32H747 board directory only' }
$candidateRoot='output/candidates/adc10-labtool-20261018'
$manifestPath=$candidateRoot+'/pcb-final-copper-v5-execution.json'
$manifestSha='84bd0fea5a837d85510430d358ab0076e264f5ad8e65abd5997afc169ee57aa3'
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant() -ne $manifestSha) { throw 'Frozen manifest changed' }
$manifest=Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$names=@($manifest.batches | ForEach-Object { $_.stage })
$first=[Array]::IndexOf($names,$FirstStage); $last=[Array]::IndexOf($names,$LastStage)
if ($first -lt 1 -or $last -lt $first -or ($last-$first) -ge 4) { throw 'Only 1-4 subsequent ordered stages are allowed' }
for ($index=$first; $index -le $last; $index++) {
    $stage=$names[$index]; $prior=$names[$index-1]
    $receiptPath=$candidateRoot+'/native-pcb-'+$stage+'-receipt.json'
    $journalPath=$candidateRoot+'/native-pcb-'+$stage+'-journal.json'
    if ((Test-Path -LiteralPath $receiptPath) -or (Test-Path -LiteralPath $journalPath)) { throw 'Refuse retry of an existing stage; reconcile actual PCB first' }
    $prev=Get-Content -Raw -LiteralPath ($candidateRoot+'/native-pcb-'+$prior+'-receipt.json') | ConvertFrom-Json
    if (-not $prev.containmentPassed) { throw 'Previous containment failure' }
    $previousAudit=Get-ChildItem -LiteralPath ($candidateRoot+'/audits') -Filter ('copper-readback-'+$prior+'-*.json') | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $previousAudit) { throw 'Previous independent audit missing' }
    $proof=Get-Content -Raw -LiteralPath $previousAudit.FullName | ConvertFrom-Json
    if (-not $proof.passed -or $proof.stage -ne $prior -or $proof.actualSha256 -ne $prev.sourceSha256 -or $proof.manifestSha256 -ne $manifestSha) { throw 'Previous independent proof is not bound to this predecessor' }
    $priorPath='output/validation/native-adc10-pcb-labtool_'+$prior+'-20261018.epru'
    node scripts/easyeda-safe-client.mjs execute-file scripts/eda/apply-adc10-labtool-pcb-batch-20261018.mjs $stage $manifestPath $manifestSha $priorPath $prev.sourceSha256
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($index -ge [Array]::IndexOf($names,'copper_wire12')) {
        & '.tools/geometry-venv/Scripts/python.exe' -X utf8 -B scripts/audit-adc10-labtool-copper-readback-20261018.py --manifest pcb-final-copper-v5-execution.json --stage $stage --junction-review root-wire10-junction-serialization-review.json --junction-review-sha 90aab429165937b7b16143fc041defbb12ffe92b176bdb65ffd184dd806d6918 --junction-review root-wire12-junction-serialization-review.json --junction-review-sha f3425d761d6434e76fa992c5dd500e7e3b79f97759bcb2c87d0868d81bc90f00
    } elseif ($index -ge [Array]::IndexOf($names,'copper_wire10')) {
        & '.tools/geometry-venv/Scripts/python.exe' -X utf8 -B scripts/audit-adc10-labtool-copper-readback-20261018.py --manifest pcb-final-copper-v5-execution.json --stage $stage --junction-review root-wire10-junction-serialization-review.json --junction-review-sha 90aab429165937b7b16143fc041defbb12ffe92b176bdb65ffd184dd806d6918
    } else {
        & '.tools/geometry-venv/Scripts/python.exe' -X utf8 -B scripts/audit-adc10-labtool-copper-readback-20261018.py --manifest pcb-final-copper-v5-execution.json --stage $stage
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
exit 0
