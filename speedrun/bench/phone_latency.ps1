<#
Phone-side latency benchmark (spec section 10 phone targets) — emulator/device.

Measures the SHIPPING signed release build (com.ichi2.anki) via adb:
  * cold start -> first usable screen (DeckPicker), N runs after warmup
  * resident memory (PSS TOTAL) once idle on the deck list
  * interactive UI frame-render latency (gfxinfo p50/p90/p95/p99 + jank) while
    scripted taps drive real UI (open add sheet, nav drawer, back)

Honest notes are written into the report by phone_latency_report.py; this script
just collects raw numbers into speedrun/proof/phone-latency.json.

Prereq: onboarding already completed once (app lands on DeckPicker), device up.

    powershell -File speedrun\bench\phone_latency.ps1 -Iters 7
#>
param(
  [string]$Adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
  [string]$Pkg = "com.ichi2.anki",
  [string]$Launcher = "com.ichi2.anki/.IntentHandler",
  [int]$Iters = 7
)

function Adb { & $Adb @args }

function Get-Prop($name) { (Adb shell getprop $name).Trim() }

function ColdStart {
  Adb shell am force-stop $Pkg | Out-Null
  Start-Sleep -Milliseconds 1500
  $out = Adb shell am start-activity -W -n $Launcher 2>&1
  $total = ($out | Select-String 'TotalTime:\s*(\d+)').Matches.Groups[1].Value
  $wait  = ($out | Select-String 'WaitTime:\s*(\d+)').Matches.Groups[1].Value
  $act   = ($out | Select-String 'Activity:\s*(\S+)').Matches.Groups[1].Value
  [pscustomobject]@{ total = [int]$total; wait = [int]$wait; activity = $act }
}

Write-Host "== device =="
$model = Get-Prop ro.product.model
$sdk   = Get-Prop ro.build.version.sdk
$abi   = Get-Prop ro.product.cpu.abi
$isEmu = (Get-Prop ro.boot.qemu) -eq "1" -or (Get-Prop ro.kernel.qemu) -eq "1"
Write-Host "  model=$model sdk=$sdk abi=$abi emulator=$isEmu"

Write-Host "== warmup (2 discarded cold starts) =="
[void](ColdStart); [void](ColdStart)

Write-Host "== cold start x$Iters =="
$cold = @()
for ($i = 0; $i -lt $Iters; $i++) {
  $r = ColdStart
  $cold += $r
  Write-Host ("  run {0}: TotalTime={1}ms activity={2}" -f ($i+1), $r.total, $r.activity)
  Start-Sleep -Milliseconds 800
}
$totals = ($cold | ForEach-Object { $_.total }) | Sort-Object
$median = $totals[[math]::Floor($totals.Count/2)]

Write-Host "== memory (settle 4s, then meminfo) =="
Adb shell am start-activity -n $Launcher | Out-Null
Start-Sleep -Seconds 4
$mem = Adb shell dumpsys meminfo $Pkg 2>&1
$pss = ($mem | Select-String 'TOTAL PSS:\s*(\d+)').Matches.Groups[1].Value
if (-not $pss) { $pss = ($mem | Select-String 'TOTAL\s+(\d+)').Matches.Groups[1].Value }

Write-Host "== interactive frames (gfxinfo) =="
Adb shell dumpsys gfxinfo $Pkg reset | Out-Null
# Drive real UI: open add sheet (FAB), back, nav drawer, back, repeat.
for ($k = 0; $k -lt 4; $k++) {
  Adb shell input tap 930 2180 | Out-Null   # FAB (+) bottom-right (1080x2400)
  Start-Sleep -Milliseconds 700
  Adb shell input keyevent KEYCODE_BACK | Out-Null
  Start-Sleep -Milliseconds 400
  Adb shell input tap 60 150 | Out-Null      # nav drawer hamburger top-left
  Start-Sleep -Milliseconds 700
  Adb shell input keyevent KEYCODE_BACK | Out-Null
  Start-Sleep -Milliseconds 400
  Adb shell input swipe 540 1600 540 700 250 | Out-Null  # scroll
  Start-Sleep -Milliseconds 400
}
Start-Sleep -Milliseconds 500
$gfx = Adb shell dumpsys gfxinfo $Pkg 2>&1
function Gfx($label) { ($gfx | Select-String ("{0}:\s*([\d.]+)ms" -f $label)).Matches.Groups[1].Value }
$frames = ($gfx | Select-String 'Total frames rendered:\s*(\d+)').Matches.Groups[1].Value
$janky  = ($gfx | Select-String 'Janky frames:\s*(\d+)').Matches.Groups[1].Value
$p50 = Gfx '50th percentile'; $p90 = Gfx '90th percentile'
$p95 = Gfx '95th percentile'; $p99 = Gfx '99th percentile'

$result = [ordered]@{
  device = [ordered]@{ model = $model; sdk = $sdk; abi = $abi; emulator = [bool]$isEmu; package = $Pkg }
  cold_start_ms = [ordered]@{
    runs = @($totals)
    min = $totals[0]; median = $median; max = $totals[-1]
    activity = $cold[0].activity
  }
  memory_pss_kb = [int]$pss
  frames = [ordered]@{
    total = [int]$frames; janky = [int]$janky
    p50_ms = [double]$p50; p90_ms = [double]$p90; p95_ms = [double]$p95; p99_ms = [double]$p99
  }
  generated = (Get-Date).ToUniversalTime().ToString("o")
}

$json = $result | ConvertTo-Json -Depth 6
$outPath = Join-Path $PSScriptRoot "..\proof\phone-latency.json"
$json | Set-Content -Encoding UTF8 $outPath
Write-Host "`n$json"
Write-Host "`nwrote $outPath"
