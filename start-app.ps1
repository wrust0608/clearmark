param(
    [string]$ListenAddress = "127.0.0.1",
    [int]$Port = 8765,
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue

if ($pythonCommand) {
    $pythonExe = $pythonCommand.Source
} elseif (Test-Path -LiteralPath $bundledPython) {
    $pythonExe = $bundledPython
} else {
    throw "Không tìm thấy Python 3.10+. Hãy cài Python hoặc truyền đường dẫn phù hợp trong PATH."
}

$env:WATERMARKS_SERVER_API_KEY = $ApiKey
Set-Location -LiteralPath $projectRoot
Write-Host "ClearMark đang chạy tại http://$ListenAddress`:$Port/"
if ($ListenAddress -eq "0.0.0.0") {
    Write-Host "Máy khác trong mạng nội bộ có thể mở http://<IP-của-máy-này>:$Port/"
}
& $pythonExe "service/scripts/server.py" --host $ListenAddress --port $Port
