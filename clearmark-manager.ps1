param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "status",
    [string]$ListenAddress = "127.0.0.1",
    [int]$Port = 8765,
    [string]$ApiKey = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$runtimeDir = Join-Path $projectRoot ".run"
$pidFile = Join-Path $runtimeDir "clearmark.pid.json"
$serverScript = Join-Path $projectRoot "service\scripts\server.py"
$modelServer = Join-Path $projectRoot ".runtime\llama-b10985\llama-server.exe"
$modelFile = Join-Path $projectRoot ".runtime\models\qwen2.5-3b-instruct-q4_k_m.gguf"
$modelPort = 8768

function Find-Python {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython) { return $systemPython.Source }

    $bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path -LiteralPath $bundledPython) { return $bundledPython }

    throw "Khong tim thay Python 3.10+. Hay cai Python roi thu lai."
}

function Get-ManagedProcess {
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    try {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$record.pid) -ErrorAction Stop
        if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$record.startTicks) {
            return $null
        }
        return $process
    } catch {
        return $null
    }
}

function Get-ManagedModelProcess {
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    try {
        $record = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        if (-not $record.modelPid) { return $null }
        $process = Get-Process -Id ([int]$record.modelPid) -ErrorAction Stop
        if ($process.StartTime.ToUniversalTime().Ticks -ne [long]$record.modelStartTicks) {
            return $null
        }
        return $process
    } catch {
        return $null
    }
}

function Remove-StaleRecord {
    if (Test-Path -LiteralPath $pidFile) {
        Remove-Item -LiteralPath $pidFile -Force
    }
}

function Stop-ManagedProcessTree([System.Diagnostics.Process]$RootProcess) {
    $taskkill = Join-Path $env:SystemRoot "System32\taskkill.exe"
    try {
        # /T terminates descendants such as ffmpeg/exiftool as well as Python.
        & $taskkill /PID $RootProcess.Id /T /F 2>$null | Out-Null
    } catch {
        Stop-Process -Id $RootProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 150
    $RootProcess.Refresh()
    if (-not $RootProcess.HasExited) {
        Stop-Process -Id $RootProcess.Id -Force -ErrorAction SilentlyContinue
    }
    try { $RootProcess.WaitForExit(5000) | Out-Null } catch { }
}

function Test-Health {
    param([string]$Url, [string]$Key = "")
    $headers = @{}
    if ($Key) { $headers.Authorization = "Bearer $Key" }
    try {
        $response = Invoke-RestMethod -Uri "$Url/health" -Headers $headers -TimeoutSec 2
        return $response.ok -eq $true
    } catch {
        return $false
    }
}

function Test-ModelHealth {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:$modelPort/health" -TimeoutSec 2
        return $null -ne $response
    } catch {
        return $false
    }
}

$managedProcess = Get-ManagedProcess
$managedModelProcess = Get-ManagedModelProcess
if (-not $managedProcess) { Remove-StaleRecord }

switch ($Action) {
    "start" {
        $url = "http://127.0.0.1:$Port"
        if ($managedProcess) {
            Write-Host "ClearMark dang chay (PID $($managedProcess.Id))." -ForegroundColor Green
            if (-not $NoBrowser) { Start-Process $url }
            exit 0
        }
        if (Test-Health -Url $url -Key $ApiKey) {
            throw "Cong $Port dang duoc mot may chu khac su dung. Hay tat tien trinh do truoc."
        }

        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        $modelProcess = $null
        if ((Test-Path -LiteralPath $modelServer) -and (Test-Path -LiteralPath $modelFile)) {
            $modelStartInfo = New-Object System.Diagnostics.ProcessStartInfo
            $modelStartInfo.FileName = $modelServer
            $modelStartInfo.Arguments = '-m "{0}" --host 127.0.0.1 --port {1} -c 4096 -t 6 -ngl 0' -f $modelFile, $modelPort
            $modelStartInfo.WorkingDirectory = Split-Path -Parent $modelServer
            $modelStartInfo.UseShellExecute = $true
            $modelStartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
            $modelProcess = [System.Diagnostics.Process]::Start($modelStartInfo)

            $modelReady = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                if ($modelProcess.HasExited) { break }
                if (Test-ModelHealth) { $modelReady = $true; break }
                Start-Sleep -Milliseconds 500
            }
            if (-not $modelReady) {
                Stop-ManagedProcessTree -RootProcess $modelProcess
                $modelProcess = $null
            }
        }

        $pythonExe = Find-Python
        if ($ApiKey.Contains('"')) { throw "API key cannot contain a double quote." }
        $argumentText = '"{0}" --host "{1}" --port {2}' -f $serverScript, $ListenAddress, $Port
        if ($ApiKey) { $argumentText += ' --api-key "{0}"' -f $ApiKey }
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.FileName = $pythonExe
        $startInfo.Arguments = $argumentText
        $startInfo.WorkingDirectory = $projectRoot
        $startInfo.UseShellExecute = $true
        $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        if ($modelProcess) {
            $env:WATERMARKS_REWRITE_BACKEND = "openai-compatible"
            $env:WATERMARKS_REWRITE_MODEL = "qwen2.5-3b-instruct"
            $env:WATERMARKS_REWRITE_BASE_URL = "http://127.0.0.1:$modelPort"
            $env:WATERMARKS_REWRITE_API_KEY = "local-only"
            $env:WATERMARKS_REWRITE_TIMEOUT = "900"
            $env:WATERMARKS_REWRITE_TEMPERATURE = "0.6"
        }
        $process = [System.Diagnostics.Process]::Start($startInfo)

        $recordData = @{
            pid = $process.Id
            startTicks = $process.StartTime.ToUniversalTime().Ticks
        }
        if ($modelProcess) {
            $recordData.modelPid = $modelProcess.Id
            $recordData.modelStartTicks = $modelProcess.StartTime.ToUniversalTime().Ticks
        }
        $recordData | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

        $ready = $false
        for ($attempt = 0; $attempt -lt 25; $attempt++) {
            if ($process.HasExited) { break }
            if (Test-Health -Url $url -Key $ApiKey) { $ready = $true; break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $ready) {
            Stop-ManagedProcessTree -RootProcess $process
            Stop-ManagedProcessTree -RootProcess $modelProcess
            Remove-StaleRecord
            throw "May chu khong khoi dong duoc."
        }

        Write-Host "ClearMark da mo tai $url" -ForegroundColor Green
        if (-not $NoBrowser) { Start-Process $url }
    }
    "stop" {
        if (-not $managedProcess) {
            Write-Host "ClearMark hien khong chay."
            exit 0
        }
        $stoppedPid = $managedProcess.Id
        Stop-ManagedProcessTree -RootProcess $managedProcess
        if ($managedModelProcess) {
            Stop-ManagedProcessTree -RootProcess $managedModelProcess
        }
        Remove-StaleRecord
        Write-Host "Da tat hoan toan ClearMark (PID $stoppedPid)." -ForegroundColor Green
    }
    "status" {
        if ($managedProcess) {
            $memoryBytes = $managedProcess.WorkingSet64
            if ($managedModelProcess) { $memoryBytes += $managedModelProcess.WorkingSet64 }
            $memoryMb = [math]::Round($memoryBytes / 1MB, 1)
            $modelState = if ($managedModelProcess) { "san sang" } else { "chua chay" }
            Write-Host "Dang chay - PID $($managedProcess.Id) - AI $modelState - RAM $memoryMb MB" -ForegroundColor Green
        } else {
            Write-Host "Da tat - khong chiem tai nguyen may chu."
        }
    }
}
