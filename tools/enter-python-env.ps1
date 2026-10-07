[CmdletBinding()]
param(
    [ValidateSet("core", "pose")]
    [string]$Environment = "core"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$cacheRoot = Join-Path $projectRoot "tools\cache"
$modelRoot = Join-Path $projectRoot "models"
$venvName = if ($Environment -eq "pose") { ".venv-pose" } else { ".venv" }
$pythonPath = Join-Path $projectRoot "$venvName\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Python environment is missing: $pythonPath"
}

$env:PIP_CACHE_DIR = Join-Path $cacheRoot "pip"
$env:HF_HOME = Join-Path $modelRoot "huggingface"
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME "hub"
$env:XDG_CACHE_HOME = $cacheRoot
$env:TORCH_HOME = Join-Path $modelRoot "torch"
$env:MEDIAPIPE_MODEL_DIR = Join-Path $modelRoot "mediapipe"
$env:SEEDANCE_PYTHON = $pythonPath

Write-Output $pythonPath
