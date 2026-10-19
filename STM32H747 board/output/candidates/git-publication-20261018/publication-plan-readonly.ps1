param()
$ErrorActionPreference = 'Stop'
$stmScope = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$stmRepo = Split-Path -Parent $stmScope
$stmReportPath = Join-Path $PSScriptRoot 'git-publication-plan-readonly-20261018.json'
$stmFiles = @(Get-ChildItem -LiteralPath $stmScope -Force -Recurse -File)
function Get-StmRelative([string]$Path) {
    return $Path.Substring($stmScope.Length + 1).Replace('\','/')
}
function Get-StmGroups($Files, [string]$Prefix = '') {
    return @($Files | Group-Object {
        $stmRel = Get-StmRelative $_.FullName
        if ($Prefix) { $stmRel = $stmRel.Substring($Prefix.Length) }
        ($stmRel -split '/')[0]
    } | ForEach-Object { [ordered]@{ path=$_.Name; files=$_.Count; bytes=[long](($_.Group | Measure-Object Length -Sum).Sum) } } | Sort-Object { $_.bytes } -Descending)
}
$stmAllMeta = @($stmFiles | ForEach-Object { [ordered]@{ path=Get-StmRelative $_.FullName; bytes=$_.Length } })
$stmNoisePatterns = @(
    '^\.tools/', '^tmp/', '(^|/)__pycache__/', '\.py[co]$', '\.(log|tmp)$',
    '^native-project/[^/]+_backup/', '^STM32H747 board/', '^EasyEDA-Bridge\.local\.cmd$',
    '(^|/)node_modules/', '(^|/)\.git/', '(^|/)\.env($|\.)', '\.(pem|key)$', '(-wal|-shm)$'
)
function Test-StmNoise([string]$Path) {
    foreach ($stmPattern in $stmNoisePatterns) { if ($Path -match $stmPattern) { return $true } }
    return $false
}
# Concrete current snapshot proposal; root must substitute the NEWEST saved,
# reopened and audited 18Oct WIP export after PCB work finishes before staging.
$stmCheckpointPaths = @(
    'output/checkpoints/STM32H747_adc10_pcb_orientation_wip_20261017.epro2',
    'output/checkpoints/STM32H747_adc10_schematic_20261017.epro2',
    'output/checkpoints/STM32H747_before_adc10_20261017.epro2',
    'output/checkpoints/STM32H747_multilayer_drc_pass_20261016.epro2'
)
$stmEvidenceExact = @(
    'output/validation/native-adc10-sch-reopened-20261017.epru',
    'output/validation/native-adc10-sch-before-20261017.epru',
    'output/validation/native-adc10-reopened-Protel2-20261017.net',
    'output/validation/native-adc10-reopened-erc-20261017.json',
    'output/validation/native-pcb-Protel2_adc10_oriented_reopened_20261017.net',
    'output/validation/native-pcb-drc-0ac2a19168000d8e-adc10_oriented_reopened_20261017.json'
)
$stmSelected = @()
$stmCategoryCounter = @{}
foreach ($stmFile in $stmFiles) {
    $stmRel = Get-StmRelative $stmFile.FullName
    if (Test-StmNoise $stmRel) { continue }
    $stmCategory = $null
    if ($stmRel -in @('.gitignore','AGENTS.md','README.md','EasyEDA-Bridge.local.cmd.example','Start-EasyEDA-Bridge.bat')) { $stmCategory = 'project documentation and launchers' }
    elseif ($stmRel -match '^config/') { $stmCategory = 'configuration and status' }
    elseif ($stmRel -match '^scripts/') { $stmCategory = 'reproducible scripts without caches' }
    elseif ($stmRel -match '^보드 자료/') { $stmCategory = 'user-provided reference PDF STEP and Gerber' }
    elseif ($stmRel -match '^reference/') { $stmCategory = 'small reference renders' }
    elseif ($stmRel -eq 'native-project/STM32H747_MCU_BOARD_v19.eprj2') { $stmCategory = 'authoritative editable live project - freeze after save' }
    elseif ($stmRel -in $stmCheckpointPaths) { $stmCategory = 'four selected full-project recovery checkpoints' }
    elseif ($stmRel -in $stmEvidenceExact) { $stmCategory = 'selected current electrical evidence' }
    elseif ($stmRel -match '^output/candidates/(adc10-dc-buffer-20261017|git-publication-20261018)/' -and $stmRel -match '\.(py|ps1|json|md|png)$') { $stmCategory = 'current ADC10 audit scripts plans and previews' }
    elseif ($stmRel -match '^output/candidates/adc-dc-buffer/' -and $stmRel -match '(adc-dc-library-manifest\.json|adc-dc-runtime-library-map\.json|\.efoo$|\.esym$|\.edevice$)') { $stmCategory = 'ADC library provenance and portable definitions' }
    if ($stmCategory) {
        $stmSelected += [ordered]@{ path=$stmRel; bytes=$stmFile.Length; category=$stmCategory }
    }
}
$stmReadGit = {
    param([string[]]$GitArguments)
    $stmResult = & git --no-optional-locks -C $stmRepo @GitArguments
    if ($LASTEXITCODE -ne 0) { throw ('Read-only git command failed: ' + ($GitArguments -join ' ')) }
    return @($stmResult)
}
$stmBranch = & $stmReadGit @('branch','--show-current')
$stmHead = & $stmReadGit @('rev-parse','HEAD')
$stmOrigin = & $stmReadGit @('config','--get','remote.origin.url')
$stmAheadBehind = & $stmReadGit @('rev-list','--left-right','--count','HEAD...@{upstream}')
$stmStatusNamesOnly = & $stmReadGit @('status','--short','--untracked-files=no')
$stmRootInstructions = Test-Path -LiteralPath (Join-Path $stmRepo 'AGENTS.md')
$stmProposedIgnores = @(
    '/.tools/', '/tmp/', '/EasyEDA-Bridge.local.cmd', '*.log', '*.tmp',
    '**/__pycache__/', '*.py[cod]', '/native-project/*_backup/', '/STM32H747 board/',
    '**/node_modules/', '*.eprj2-wal', '*.eprj2-shm', '*.lock',
    '/output/validation/', '/output/native-libraries*/', '/output/native-pcb/',
    '/output/native-schematics/', '/output/semantic/', '/output/page1/'
)
$stmReport = [ordered]@{
    schema='stm32h747-readonly-git-publication-plan-20261018-v1'
    generatedAt=(Get-Date).ToString('o')
    scope=$stmScope
    repository=$stmRepo
    localGitSnapshot=[ordered]@{
        branch=$stmBranch; head=$stmHead; origin=$stmOrigin
        cachedUpstreamAheadBehind=$stmAheadBehind
        noFetchPerformed=$true
        trackedStatusNamesOnly=$stmStatusNamesOnly
        rootAgentsFileExists=$stmRootInstructions
        stmFolderPreviouslyTracked=$false
    }
    safety=[ordered]@{
        gitWrites=0; stageOperations=0; commits=0; pushes=0; remoteMutations=0
        testDac8562ContentReads=0; testDac8562Writes=0
        ignoreFilesModified=$false; onlyOwnDiagnosticReportWritten=$true
    }
    inventory=[ordered]@{
        files=$stmFiles.Count; bytes=[long](($stmFiles | Measure-Object Length -Sum).Sum)
        topLevel=Get-StmGroups $stmFiles
        outputSubdirectories=Get-StmGroups @($stmFiles | Where-Object { (Get-StmRelative $_.FullName) -match '^output/' }) 'output/'
        filesOver50MiB=@($stmAllMeta | Where-Object bytes -gt 52428800)
        filesOver100MiB=@($stmAllMeta | Where-Object bytes -gt 104857600)
        reparsePoints=@(Get-ChildItem -LiteralPath $stmScope -Force -Recurse -Attributes ReparsePoint | ForEach-Object { Get-StmRelative $_.FullName })
    }
    proposedCurrentAllowlist=[ordered]@{
        files=$stmSelected.Count; bytes=[long](($stmSelected | ForEach-Object { $_.bytes } | Measure-Object -Sum).Sum)
        pathsAndSizes=$stmSelected
        missingOptionalEvidencePaths=@($stmEvidenceExact | Where-Object { -not (Test-Path -LiteralPath (Join-Path $stmScope $_)) })
        checkpointSubstitutionRequiredAfter18OctWork=$true
        liveProjectCopyMustBeSavedAndConsistentBeforeStaging=$true
        publicationManifestShouldRecordFinalNativeAndCheckpointSha256=$true
    }
    suggestedExclusions=$stmProposedIgnores
    exclusionApplication='PROPOSAL ONLY. Root may edit only STM-scoped .gitignore or use explicit allowlisted paths; do not alter root TEST_DAC8562 ignore behavior. If output/validation is ignored, exact selected evidence must be explicit -f additions or relocated to a deliberate publication snapshot by root. Never force-add entire output.'
    largeFileDecision=[ordered]@{
        onlyCurrentOver50MiB='native-project/STM32H747_MCU_BOARD_v19.eprj2'
        regularGitCurrentFileBelow100MiB=$true
        noLfsConfigurationOrMigrationPerformed=$true
        recommendation='Current84.38MB native file can be intentionally included in regular Git with a warning; use the compressed self-contained20.6MB epro2 as reproducible recovery authority. If long-term native DB history grows, explicitly choose LFS or snapshot-only export workflow before crossing100MiB. Do not silently introduce quota/billing or migrate other project history.'
    }
    secretAndNoiseReview=[ordered]@{
        filenameScan='No candidate secret/key/env/credential filenames found outside ignored tools/tmp; cache .pyc files found and should be excluded.'
        configAndScriptsPatternScan='No secret-pattern matches; paths/UUIDs in config/easyeda-project.json are machine/project guards, not credentials.'
        broaderTextPatternScan='No matches for private-key headers or recognizable GitHub/OpenAI/Slack/AWS token patterns in nonignored readable STM text; excluded binary project/archive/PDF/STEP/image files were not content-scanned.'
        scannerIsNotSecretFreeGuarantee=$true
        nativeBinaryAndArchivesRequireFinalUserScopePrivacyReview=$true
        repositoryVisibilityNotQueried=$true
        thirdPartyDatasheets='Do not publish downloaded TI PDFs under old candidate output by default; preserve links and derived library evidence instead.'
        nestedAccidentalOutput='STM32H747 board/output/validation/tmp-placed-schema.json is nested under the STM scope again; exclude it, do not delete it in this publication step.'
        localConfigPortability='Current config/easyeda-project.json includes absolute path and live window/project IDs. Document rebind-on-clone or publish a portable example after root review; do not change live safety guards during PCB work.'
    }
    recommendedRootSequence=@(
        'Finish the authorized PCB edit, save/reopen/validate and export a uniquely named18Oct WIP epro2; do not label unfinished PCB fabrication-ready.',
        'Update README/status to exact current DRC and incomplete functionality, and select current plus needed recovery checkpoints explicitly.',
        'Apply only STM-scoped ignore improvements or use the concrete allowlist. Exclude runtime/tmp/cache/autobackup/historical output. Preserve all on disk.',
        'Record SHA256/size for final native project and epro2 snapshot; verify no WAL/SHM/lock artifacts and checkpoint opens independently.',
        'Stage explicit STM32H747 paths only; inspect git diff --cached --name-only and require every path begins STM32H747 board/ and none begins TEST_DAC8562/. Do not use git add . or git add -A.',
        'Inspect staged diff and large blobs; then commit/push according to user authorization. Root must verify remote state immediately before push; this report only knows cached origin/main.',
        'After push, verify published commit/remote hash and leave the pre-existing TEST_DAC8562 tracked modification untouched.'
    )
    officialPolicySources=@(
        'https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github',
        'https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits'
    )
    policySummary='GitHub warns for files above50MiB and blocks regular-Git files above100MiB. Push payload limit is2GB. Raw workspace3.5GB is not the compressed push size, but blanket publication is unnecessarily large and noisy.'
    noPublicationOrDesignApprovalImplied=$true
}
$stmJson = $stmReport | ConvertTo-Json -Depth 12
[System.IO.File]::WriteAllText($stmReportPath, $stmJson + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
[ordered]@{ path=$stmReportPath; sha256=(Get-FileHash -LiteralPath $stmReportPath -Algorithm SHA256).Hash.ToLowerInvariant(); totalFiles=$stmFiles.Count; totalBytes=$stmReport.inventory.bytes; proposedFiles=$stmSelected.Count; proposedBytes=$stmReport.proposedCurrentAllowlist.bytes; over100MiB=$stmReport.inventory.filesOver100MiB.Count } | ConvertTo-Json
