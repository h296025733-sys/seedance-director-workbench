[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbenchRoot
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding

function New-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Detail,
        [bool]$Required = $true
    )
    [ordered]@{
        name = $Name
        ok = $Ok
        required = $Required
        detail = $Detail
    }
}

function Find-LocalExecutable {
    param([string]$Name)

    $fromPath = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $fromPath) {
        return $fromPath.Source
    }

    $vendorRoot = Join-Path $WorkbenchRoot 'tools\vendor'
    if (Test-Path -LiteralPath $vendorRoot -PathType Container) {
        $candidate = Get-ChildItem -LiteralPath $vendorRoot -Directory -Filter 'ffmpeg-*' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "bin\$Name.exe" } |
            Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
            Select-Object -First 1
        if ($null -ne $candidate) {
            return $candidate
        }
    }
    return $null
}

function Test-PythonEnvironment {
    param(
        [string]$Name,
        [string]$PythonPath,
        [string[]]$Imports
    )

    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        return New-Check -Name $Name -Ok $false -Detail "missing: $PythonPath"
    }

    $code = "import " + ($Imports -join ', ') + "; print('ok')"
    try {
        $version = (& $PythonPath --version 2>&1 | Select-Object -First 1 | Out-String).Trim()
        $importResult = (& $PythonPath -c $code 2>&1 | Out-String).Trim()
        $passed = $LASTEXITCODE -eq 0 -and $importResult -match 'ok'
        $detail = if ($passed) { "$version; imports: $($Imports -join ', ')" } else { $importResult }
        return New-Check -Name $Name -Ok $passed -Detail $detail
    }
    catch {
        return New-Check -Name $Name -Ok $false -Detail $_.Exception.Message
    }
}

try {
    $rootExists = Test-Path -LiteralPath $WorkbenchRoot -PathType Container
    $checks = [System.Collections.Generic.List[object]]::new()
    $checks.Add((New-Check -Name 'workbench' -Ok $rootExists -Detail $WorkbenchRoot))

    $requiredFiles = @(
        'AGENTS.md',
        'tools\watch_video.py',
        'tools\anonymize_face_reference.py'
    )
    foreach ($relative in $requiredFiles) {
        $path = Join-Path $WorkbenchRoot $relative
        $checks.Add((New-Check -Name "file:$relative" -Ok (Test-Path -LiteralPath $path -PathType Leaf) -Detail $path))
    }

    $knowledgeRoot = Join-Path $WorkbenchRoot 'knowledge'
    $knowledgeFiles = @(Get-ChildItem -LiteralPath $knowledgeRoot -File -Filter 'Seedance*.md' -ErrorAction SilentlyContinue)
    $checks.Add((New-Check -Name 'knowledge:seedance' -Ok ($knowledgeFiles.Count -ge 5) -Detail "$($knowledgeFiles.Count) Seedance markdown files in $knowledgeRoot"))

    $corePython = Join-Path $WorkbenchRoot '.venv\Scripts\python.exe'
    $posePython = Join-Path $WorkbenchRoot '.venv-pose\Scripts\python.exe'
    $checks.Add((Test-PythonEnvironment -Name 'python-core' -PythonPath $corePython -Imports @('cv2', 'numpy', 'PIL', 'scenedetect', 'yaml')))
    $checks.Add((Test-PythonEnvironment -Name 'python-pose' -PythonPath $posePython -Imports @('cv2', 'numpy', 'mediapipe')))

    foreach ($exeName in @('ffmpeg', 'ffprobe')) {
        $exePath = Find-LocalExecutable -Name $exeName
        if ($null -eq $exePath) {
            $checks.Add((New-Check -Name $exeName -Ok $false -Detail 'not found in PATH or workbench tools/vendor'))
            continue
        }
        $versionOutput = & $exePath -version 2>&1
        $versionExit = $LASTEXITCODE
        $firstLine = ($versionOutput | Select-Object -First 1 | Out-String).Trim()
        $checks.Add((New-Check -Name $exeName -Ok ($versionExit -eq 0) -Detail "$exePath | $firstLine"))
    }

    $modelChecks = @(
        @{ name = 'model:blazeface'; relative = 'models\mediapipe\blaze_face_short_range.tflite' },
        @{ name = 'model:yunet'; relative = 'models\opencv\face_detection_yunet_2023mar.onnx' },
        @{ name = 'model:pose'; relative = 'models\mediapipe\pose_landmarker_full.task' }
    )
    foreach ($item in $modelChecks) {
        $path = Join-Path $WorkbenchRoot $item.relative
        $present = Test-Path -LiteralPath $path -PathType Leaf
        $detail = if ($present) {
            $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
            "$path | sha256=$hash"
        } else {
            "missing: $path"
        }
        $checks.Add((New-Check -Name $item.name -Ok $present -Detail $detail))
    }

    $driveName = [System.IO.Path]::GetPathRoot($WorkbenchRoot).TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
    if ($null -ne $drive) {
        $freeGb = [math]::Round($drive.Free / 1GB, 2)
        $checks.Add((New-Check -Name 'disk-free' -Ok ($freeGb -ge 2) -Detail "$($drive.Name): free ${freeGb} GB"))
    } else {
        $checks.Add((New-Check -Name 'disk-free' -Ok $false -Detail "drive not found: $driveName"))
    }

    $failed = @($checks | Where-Object { $_.required -and -not $_.ok })
    $report = [ordered]@{
        schema_version = 1
        checked_at = (Get-Date).ToString('o')
        workbench = $WorkbenchRoot
        status = if ($failed.Count -eq 0) { 'ready-local' } else { 'missing-required' }
        checks = $checks
        scope = 'Local dependencies only; JiMeng/Seedance account upload and generation are not tested.'
    }
    $report | ConvertTo-Json -Depth 6
    if ($failed.Count -eq 0) { exit 0 }
    exit 2
}
catch {
    [ordered]@{
        schema_version = 1
        status = 'doctor-error'
        error = $_.Exception.Message
        scope = 'The diagnostic script itself failed.'
    } | ConvertTo-Json -Depth 4
    exit 3
}
