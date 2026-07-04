param(
  [string]$ProxmoxHost = "192.168.50.45",
  [string]$ProxmoxUser = "root",
  [string]$ProxmoxPassword = $env:GPU45_PROXMOX_PASSWORD,
  [string]$PlinkPath = "C:\Program Files\PuTTY\plink.exe",
  [string]$HostKey = "ssh-ed25519 255 SHA256:rRq5YQ0HF+5xmxuuPnA5N/E1KapeWdXgFyAq+bswhfY",
  [int]$ContainerId = 103,
  [string]$ProviderUrl = "http://192.168.50.212:30001",
  [string]$Model = "gpu45-llm",
  [string]$GpuHwmonPath = "/sys/class/drm/card1/device/hwmon/hwmon8",
  [int]$SampleIntervalSeconds = 2,
  [int]$BenchmarkPromptRepeats = 4096,
  [int]$OutputTokens = 8192,
  [string]$BenchmarkSalt = (Get-Date -Format "yyyyMMdd-HHmmss"),
  [double]$CoolDownTargetEdgeC = 38.0,
  [string[]]$PreRunCommands = @(),
  [string[]]$PostRunCommands = @(),
  [string]$OutputDir = (Join-Path $PSScriptRoot "..\outputs\gpu45\sweeps")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PlinkPath)) {
  throw "plink.exe not found at $PlinkPath"
}

if (-not $ProxmoxPassword) {
  throw "Set -ProxmoxPassword or GPU45_PROXMOX_PASSWORD."
}

function Invoke-RemoteCommands {
  param(
    [string[]]$Commands,
    [int]$TimeoutMs = 600000
  )

  if (-not $Commands -or $Commands.Count -eq 0) {
    return [pscustomobject]@{ ExitCode = 0; StdOut = ""; StdErr = "" }
  }

  $scriptFile = [System.IO.Path]::GetTempFileName()
  try {
    Set-Content -LiteralPath $scriptFile -Value ($Commands -join [Environment]::NewLine) -Encoding ASCII
    $stdout = & $PlinkPath -batch -hostkey "$HostKey" -ssh "$ProxmoxUser@$ProxmoxHost" -pw $ProxmoxPassword -m $scriptFile 2>&1 | Out-String
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
      throw "Remote command failed with exit code $exitCode.`n$stdout"
    }
    return [pscustomobject]@{ ExitCode = $exitCode; StdOut = $stdout; StdErr = "" }
  } finally {
    Remove-Item -LiteralPath $scriptFile -Force -ErrorAction SilentlyContinue
  }
}

function Get-GpuSample {
  $commands = @(
    "pct exec $ContainerId -- cat $GpuHwmonPath/temp1_input $GpuHwmonPath/temp2_input $GpuHwmonPath/temp3_input $GpuHwmonPath/power1_average"
  )
  $result = Invoke-RemoteCommands -Commands $commands -TimeoutMs 60000
  $values = @($result.StdOut -split "\r?\n" | Where-Object { $_ -match '^\d+$' })
  if ($values.Count -lt 4) {
    throw "Unexpected sensor output:`n$($result.StdOut)`n$($result.StdErr)"
  }

  [pscustomobject]@{
    Timestamp = (Get-Date).ToString("o")
    EdgeC = [math]::Round([double]$values[0] / 1000, 1)
    JunctionC = [math]::Round([double]$values[1] / 1000, 1)
    MemoryC = [math]::Round([double]$values[2] / 1000, 1)
    PowerW = [math]::Round([double]$values[3] / 1000000, 1)
  }
}

function Wait-ForCoolDown {
  param(
    [double]$TargetEdgeC = 38.0,
    [int]$TimeoutSeconds = 900
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $sample = Get-GpuSample
    if ($sample.EdgeC -le $TargetEdgeC) {
      return $sample
    }
    Start-Sleep -Seconds 5
  }

  throw "GPU did not cool to $TargetEdgeC C edge within $TimeoutSeconds seconds."
}

function Build-BenchmarkPrompt {
  $phrase = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
  $body = [string]::Join(" ", (1..$BenchmarkPromptRepeats | ForEach-Object { $phrase }))
  return @"
Continue the exact token sequence below without adding commentary. Repeat it until you are cut off.

$body

Run salt: $BenchmarkSalt
"@
}

function Start-BenchmarkJob {
  $prompt = Build-BenchmarkPrompt
  return Start-Job -ArgumentList $ProviderUrl, $Model, $prompt, $OutputTokens -ScriptBlock {
    param($providerUrl, $model, $prompt, $outputTokens)

    $body = @{
      model = $model
      input = @(
        @{
          type = "message"
          role = "user"
          content = @(
            @{
              type = "input_text"
              text = $prompt
            }
          )
        }
      )
      max_output_tokens = $outputTokens
      temperature = 0
    } | ConvertTo-Json -Depth 12

    Invoke-RestMethod -Uri "$providerUrl/v1/responses" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 7200
  }
}

function Invoke-BenchmarkSweep {
  param(
    [string]$RunName
  )

  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
  $runDir = Join-Path $OutputDir $RunName
  New-Item -ItemType Directory -Path $runDir -Force | Out-Null

  if ($PreRunCommands.Count -gt 0) {
    Invoke-RemoteCommands -Commands $PreRunCommands -TimeoutMs 600000 | Out-Null
  }

  $preSample = Wait-ForCoolDown -TargetEdgeC $CoolDownTargetEdgeC -TimeoutSeconds 900
  $samplePath = Join-Path $runDir "samples.csv"
  $resultPath = Join-Path $runDir "result.json"
  $samples = New-Object System.Collections.Generic.List[object]

  $job = Start-BenchmarkJob
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    while ($true) {
      $sample = Get-GpuSample
      $samples.Add($sample)
      Add-Content -LiteralPath $samplePath -Value ("{0},{1},{2},{3},{4}" -f $sample.Timestamp, $sample.EdgeC, $sample.JunctionC, $sample.MemoryC, $sample.PowerW)

      if ($job.State -ne "Running") {
        break
      }
      Start-Sleep -Seconds $SampleIntervalSeconds
    }

    $null = Wait-Job $job
    $benchmark = Receive-Job $job
    $sw.Stop()

    $edges = @($samples | ForEach-Object { [double]$_.EdgeC })
    $junctions = @($samples | ForEach-Object { [double]$_.JunctionC })
    $mems = @($samples | ForEach-Object { [double]$_.MemoryC })
    $powers = @($samples | ForEach-Object { [double]$_.PowerW })

    $usage = $benchmark.usage
    $result = [pscustomobject]@{
      runName = $RunName
      benchmarkSalt = $BenchmarkSalt
      startedAt = $preSample.Timestamp
      durationSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 1)
      sampleCount = $samples.Count
      maxEdgeC = if ($edges.Count) { ($edges | Measure-Object -Maximum).Maximum } else { $null }
      maxJunctionC = if ($junctions.Count) { ($junctions | Measure-Object -Maximum).Maximum } else { $null }
      maxMemoryC = if ($mems.Count) { ($mems | Measure-Object -Maximum).Maximum } else { $null }
      maxPowerW = if ($powers.Count) { ($powers | Measure-Object -Maximum).Maximum } else { $null }
      totalTokens = $usage.total_tokens
      inputTokens = $usage.input_tokens
      outputTokens = $usage.output_tokens
      promptTokensPerSecond = if ($usage.input_tokens -gt 0) { [math]::Round($usage.input_tokens / [math]::Max($sw.Elapsed.TotalSeconds, 0.001), 2) } else { 0 }
      generationTokensPerSecond = if ($usage.output_tokens -gt 0) { [math]::Round($usage.output_tokens / [math]::Max($sw.Elapsed.TotalSeconds, 0.001), 2) } else { 0 }
      benchmark = $benchmark
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultPath -Encoding UTF8
    return $result
  } finally {
    if ($job) {
      Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
    if ($PostRunCommands.Count -gt 0) {
      Invoke-RemoteCommands -Commands $PostRunCommands -TimeoutMs 600000 | Out-Null
    }
  }
}

$result = Invoke-BenchmarkSweep -RunName ("run-{0}" -f $BenchmarkSalt)
$result | ConvertTo-Json -Depth 12
