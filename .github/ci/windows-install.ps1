# CI: run the Windows installer the way users do (irm | iex) against a local release.
param([string]$Name = "codo bin")
$ErrorActionPreference = "Stop"
"PowerShell $($PSVersionTable.PSVersion)"

$errors = $null; $tokens = $null
[void][System.Management.Automation.Language.Parser]::ParseFile("$PWD\install.ps1", [ref]$tokens, [ref]$errors)
$errors | ForEach-Object { Write-Host $_ }
if ($errors.Count) { throw "install.ps1 has syntax errors" }

New-Item -ItemType Directory -Force dist | Out-Null
Copy-Item codo, install.ps1 dist\ -Force
$hash = (Get-FileHash dist\codo -Algorithm SHA256).Hash.ToLower()
[System.IO.File]::WriteAllText("$PWD\dist\SHA256SUMS", "$hash  codo`n")
$server = Start-Process python -ArgumentList "-m", "http.server", "8765", "--bind", "127.0.0.1", "--directory", "dist" -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
try {
    $env:CODO_BASE_URL = "http://127.0.0.1:8765"
    $env:CODO_BIN_DIR = Join-Path $env:RUNNER_TEMP $Name   # a space in the path, like C:\Users\Jan Kowalski
    $env:CODO_LANG = "en"
    $env:CODO_NO_DEPS = "1"
    $shown = (irm http://127.0.0.1:8765/install.ps1 | iex *>&1 | Out-String)
    $shown
    if ($shown -notmatch "Installed Codo" -or $shown -match "Zainstalowano") { throw "CODO_LANG=en was ignored" }
    codo version
    if ($LASTEXITCODE -ne 0) { throw "codo does not start" }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$Name*") { throw "user PATH was not updated" }
    # second run = reinstall, PATH must not grow
    irm http://127.0.0.1:8765/install.ps1 | iex
    $again = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($again -ne $userPath) { throw "PATH changed on reinstall" }
    # a wrong checksum must stop the installation
    [System.IO.File]::WriteAllText("$PWD\dist\SHA256SUMS", ("0" * 64) + "  codo`n")
    $stopped = $false
    try { irm http://127.0.0.1:8765/install.ps1 | iex } catch { $stopped = $true }
    if (-not $stopped) { throw "bad checksum was accepted" }
    "bad checksum stopped the installation, as it should"
} finally { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }

# Python that is not on PATH: py launcher and the known folders.
$env:Path = "$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$text = Get-Content install.ps1 -Raw
$from = $text.IndexOf("function Invoke-Quiet")
Invoke-Expression $text.Substring($from, $text.IndexOf('$Python = Find-Python') - $from)
"Find-Python without PATH: $(Find-Python)"
"winget: $(Get-Winget)"
