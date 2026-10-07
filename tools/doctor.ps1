[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$workspaceRoot = Split-Path -Parent $PSScriptRoot

function Find-WorkbenchCommand {
    param([Parameter(Mandatory = $true)][string]$Name)
    if ($Name -in @('python', 'pip', 'yt-dlp')) {
        $fileName = switch ($Name) {
            'python' { 'python.exe' }
            'pip' { 'pip.exe' }
            'yt-dlp' { 'yt-dlp.exe' }
        }
        $candidate = Join-Path $workspaceRoot ".venv\Scripts\$fileName"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return [ordered]@{ path = $candidate; origin = 'project_venv' }
        }
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) {
        return [ordered]@{ path = $command.Source; origin = 'PATH' }
    }
    if ($Name -in @('ffmpeg', 'ffprobe')) {
        $vendor = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'tools\vendor') `
            -Directory -Filter 'ffmpeg-*-essentials_build' -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1
        if ($null -ne $vendor) {
            $candidate = Join-Path $vendor.FullName "bin\$Name.exe"
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                return [ordered]@{ path = $candidate; origin = 'project_vendor' }
            }
        }
    }
    return $null
}

function Get-CommandStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$VersionArguments
    )
    $command = Find-WorkbenchCommand -Name $Name
    if ($null -eq $command) {
        return [ordered]@{ name = $Name; status = 'missing'; path = $null; version = $null }
    }
    try {
        $output = & $command.path @VersionArguments 2>&1
        $exit = $LASTEXITCODE
        $first = ($output | Select-Object -First 1 | Out-String).Trim()
        return [ordered]@{
            name = $Name
            status = if ($exit -eq 0 -or $null -eq $exit) { 'available' } else { 'error' }
            path = $command.path
            origin = $command.origin
            version = $first
            returncode = $exit
        }
    }
    catch {
        return [ordered]@{ name = $Name; status = 'error'; path = $command.path; origin = $command.origin; error = $_.Exception.Message }
    }
}

$commands = @(
    Get-CommandStatus -Name 'git' -VersionArguments @('--version')
    Get-CommandStatus -Name 'python' -VersionArguments @('--version')
    Get-CommandStatus -Name 'pip' -VersionArguments @('--version')
    Get-CommandStatus -Name 'node' -VersionArguments @('--version')
    Get-CommandStatus -Name 'npm' -VersionArguments @('--version')
    Get-CommandStatus -Name 'npx' -VersionArguments @('--version')
    Get-CommandStatus -Name 'ffmpeg' -VersionArguments @('-version')
    Get-CommandStatus -Name 'ffprobe' -VersionArguments @('-version')
    Get-CommandStatus -Name 'yt-dlp' -VersionArguments @('--version')
    Get-CommandStatus -Name 'codex' -VersionArguments @('--version')
    Get-CommandStatus -Name 'nvidia-smi' -VersionArguments @('--query-gpu=name,driver_version,memory.total', '--format=csv,noheader')
    Get-CommandStatus -Name 'nvcc' -VersionArguments @('--version')
)

$os = Get-CimInstance Win32_OperatingSystem
$drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($workspaceRoot).Substring(0, 1))
$report = [ordered]@{
    schema_version = 1
    workspace = $workspaceRoot
    platform = [ordered]@{
        caption = $os.Caption
        version = $os.Version
        architecture = $os.OSArchitecture
    }
    commands = $commands
    memory = [ordered]@{
        total_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
        free_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
    }
    disk = [ordered]@{
        drive = $drive.Name
        used_gb = [math]::Round($drive.Used / 1GB, 2)
        free_gb = [math]::Round($drive.Free / 1GB, 2)
    }
    skill_paths = [ordered]@{
        project = Join-Path $workspaceRoot '.agents\skills'
        project_exists = Test-Path -LiteralPath (Join-Path $workspaceRoot '.agents\skills')
        global_checked_but_not_modified = Join-Path $env:USERPROFILE '.codex\skills'
    }
    notes = @(
        '只读检查；不会安装或配置软件。',
        'Codex 桌面捆绑运行时与系统 PATH 安装是不同状态。'
    )
}

$report | ConvertTo-Json -Depth 8
$ffmpeg = $commands | Where-Object { $_.name -eq 'ffmpeg' }
$ffprobe = $commands | Where-Object { $_.name -eq 'ffprobe' }
if ($ffmpeg.status -eq 'available' -and $ffprobe.status -eq 'available') { exit 0 }
exit 2
