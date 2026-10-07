[CmdletBinding()]
param(
    [string]$Python
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$env:PYTHONIOENCODING = 'utf-8'
$workspace = Split-Path -Parent $PSScriptRoot

function Test-PythonExecutable {
    param([Parameter(Mandatory = $true)][string]$Candidate)
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        return $false
    }
    & $Candidate --version *> $null
    return ($LASTEXITCODE -eq 0)
}

function Find-MediaTool {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }
    $vendor = Get-ChildItem -LiteralPath (Join-Path $workspace 'tools\vendor') `
        -Directory -Filter 'ffmpeg-*-essentials_build' -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($null -ne $vendor) {
        $candidate = Join-Path $vendor.FullName "bin\$Name.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    $candidates = @()
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $pythonCommand) {
        $candidates += $pythonCommand.Source
    }
    $candidates += (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    $Python = $candidates | Where-Object { Test-PythonExecutable -Candidate $_ } | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($Python)) {
        Write-Error '系统 PATH 中没有可运行 Python；请传入 -Python <绝对路径>。'
        exit 2
    }
}
elseif (-not (Test-PythonExecutable -Candidate $Python)) {
    Write-Error "指定的 Python 不可执行：$Python"
    exit 2
}

$results = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    python = $Python
    syntax = [ordered]@{}
    unit = [ordered]@{}
    media_integration = [ordered]@{}
}

& $Python -m py_compile `
    (Join-Path $workspace 'tools\doctor.py') `
    (Join-Path $workspace 'tools\build_replication_package.py') `
    (Join-Path $workspace 'tools\validate_skills.py') `
    (Join-Path $workspace 'tools\watch_video.py') `
    (Join-Path $PSScriptRoot 'test_workbench.py')
$results.syntax.exit_code = $LASTEXITCODE
$results.syntax.status = if ($LASTEXITCODE -eq 0) { 'passed' } else { 'failed' }

& $Python -m unittest discover -s $PSScriptRoot -p 'test_*.py' -v
$results.unit.exit_code = $LASTEXITCODE
$results.unit.status = if ($LASTEXITCODE -eq 0) { 'passed' } else { 'failed' }

$ffmpeg = Find-MediaTool -Name 'ffmpeg'
$ffprobe = Find-MediaTool -Name 'ffprobe'
if ([string]::IsNullOrWhiteSpace($ffmpeg) -or [string]::IsNullOrWhiteSpace($ffprobe)) {
    $results.media_integration.status = 'not_run'
    $results.media_integration.reason = 'FFmpeg/FFprobe missing; no installation was authorized or attempted.'
}
else {
    $results.media_integration.ffmpeg = $ffmpeg
    $results.media_integration.ffprobe = $ffprobe
    & (Join-Path $PSScriptRoot 'generate_synthetic_media.ps1') -Ffmpeg $ffmpeg -Ffprobe $ffprobe
    $results.media_integration.generator_exit_code = $LASTEXITCODE
    if ($LASTEXITCODE -eq 0) {
        $source = Join-Path $PSScriptRoot 'generated\中文 空格 [特殊]\竖屏 有声 中文字幕 5秒.mp4'
        $taskName = '合成集成测试-' + (Get-Date).ToString('yyyyMMdd-HHmmss-fff')
        & $Python (Join-Path $workspace 'tools\watch_video.py') --source $source --task-name $taskName --mode HOOK_DENSE
        $results.media_integration.extractor_exit_code = $LASTEXITCODE
        if ($LASTEXITCODE -eq 0) {
            $evidence = Join-Path $workspace "outputs\$taskName\evidence"
            & $Python (Join-Path $workspace 'tools\build_replication_package.py') `
                --evidence $evidence `
                --strategy character-swap `
                --target-subject '虚构成年女性，短发，红色夹克' `
                --rights-status confirmed `
                --identity-consent not-applicable
            $results.media_integration.replication_package_exit_code = $LASTEXITCODE
            $results.media_integration.status = if ($LASTEXITCODE -eq 0) { 'passed' } else { 'failed' }
            $results.media_integration.output = Join-Path $workspace "outputs\$taskName"
        }
        else {
            $results.media_integration.status = 'failed'
        }
    }
    else {
        $results.media_integration.status = 'failed'
        $results.media_integration.reason = 'Synthetic media generation failed.'
    }
}

$results | ConvertTo-Json -Depth 6
if ($results.syntax.status -ne 'passed' -or $results.unit.status -ne 'passed' -or $results.media_integration.status -eq 'failed') {
    exit 1
}
exit 0
