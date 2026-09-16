$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$sourcePath = Join-Path $PSScriptRoot "Program.cs"
$iconPath = Join-Path $projectRoot "assets\ClearMark.ico"
$outputPath = Join-Path $projectRoot "assets\ClearMark.exe"

$provider = New-Object Microsoft.CSharp.CSharpCodeProvider
$parameters = New-Object System.CodeDom.Compiler.CompilerParameters
$parameters.GenerateExecutable = $true
$parameters.GenerateInMemory = $false
$parameters.OutputAssembly = $outputPath
$parameters.CompilerOptions = "/target:winexe /win32icon:`"$iconPath`" /optimize+"
[void]$parameters.ReferencedAssemblies.Add("System.dll")
[void]$parameters.ReferencedAssemblies.Add("System.Windows.Forms.dll")

$result = $provider.CompileAssemblyFromFile($parameters, $sourcePath)
if ($result.Errors.HasErrors) {
    $messages = $result.Errors | ForEach-Object { $_.ToString() }
    throw ($messages -join [Environment]::NewLine)
}

Write-Host $outputPath
