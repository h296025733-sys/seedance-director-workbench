[CmdletBinding()]
param(
    [string]$OutputRoot = (Join-Path $PSScriptRoot 'generated\中文 空格 [特殊]'),
    [string]$Ffmpeg,
    [string]$Ffprobe
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
if ([string]::IsNullOrWhiteSpace($Ffmpeg)) {
    $command = Get-Command ffmpeg -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) { $Ffmpeg = $command.Source }
}
if ([string]::IsNullOrWhiteSpace($Ffprobe)) {
    $command = Get-Command ffprobe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -ne $command) { $Ffprobe = $command.Source }
}
if ([string]::IsNullOrWhiteSpace($Ffmpeg) -or [string]::IsNullOrWhiteSpace($Ffprobe)) {
    Write-Error '缺少 FFmpeg/FFprobe；未生成合成视频，也未自动安装。'
    exit 2
}

New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null

$portrait = Join-Path $OutputRoot '竖屏 无声 5秒.mp4'
& $Ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=blue:s=720x1280:d=5:r=30' -an -c:v libx264 -pix_fmt yuv420p -y $portrait

$square = Join-Path $OutputRoot '方形 静态重复 5秒.mp4'
& $Ffmpeg -hide_banner -loglevel error -f lavfi -i 'color=c=gray:s=720x720:d=5:r=24' -an -c:v libx264 -pix_fmt yuv420p -y $square

$landscape = Join-Path $OutputRoot '横屏 快切 有声 15秒.mp4'
$filter = '[0:v][1:v][2:v][3:v][4:v]concat=n=5:v=1:a=0[v]'
& $Ffmpeg -hide_banner -loglevel error `
    -f lavfi -i 'color=c=red:s=1280x720:d=3:r=30' `
    -f lavfi -i 'color=c=green:s=1280x720:d=3:r=30' `
    -f lavfi -i 'color=c=blue:s=1280x720:d=3:r=30' `
    -f lavfi -i 'color=c=yellow:s=1280x720:d=3:r=30' `
    -f lavfi -i 'color=c=purple:s=1280x720:d=3:r=30' `
    -f lavfi -i 'sine=frequency=880:duration=15:sample_rate=48000' `
    -filter_complex $filter -map '[v]' -map '5:a' -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest -y $landscape

$srt = Join-Path $OutputRoot '中英混合 字幕.srt'
@"
1
00:00:00,200 --> 00:00:01,500
中文钩子 Hook

2
00:00:02,000 --> 00:00:03,500
产品出现 Product appears

3
00:00:04,000 --> 00:00:04,800
行动引导 CTA
"@ | Set-Content -LiteralPath $srt -Encoding utf8

$captioned = Join-Path $OutputRoot '竖屏 有声 中文字幕 5秒.mp4'
& $Ffmpeg -hide_banner -loglevel error `
    -f lavfi -i 'testsrc2=s=720x1280:d=5:r=30' `
    -f lavfi -i 'sine=frequency=440:duration=5:sample_rate=48000' `
    -i $srt -map '0:v' -map '1:a' -map '2:s' -c:v libx264 -pix_fmt yuv420p -c:a aac -c:s mov_text -shortest -y $captioned

$files = @($portrait, $square, $landscape, $captioned)
foreach ($file in $files) {
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $file)) {
        throw "合成素材生成失败：$file"
    }
    & $Ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 $file
}

[ordered]@{
    status = 'generated'
    output_root = $OutputRoot
    files = $files
    coverage = @(
        '中文与空格路径', '特殊字符目录', '竖屏', '横屏', '方形',
        '无声', '有声', '无字幕', '嵌入字幕', '快速切换', '静态重复',
        '前3秒变化', '中文字幕', '英文字幕', '混合语言', '5秒', '15秒'
    )
} | ConvertTo-Json -Depth 5
