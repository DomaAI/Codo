# CI: "codo ui" on Windows. Starts the local page server in the background, checks that the page needs
# the token, reads the engine's first event over Server-Sent Events, then quits and checks that no
# Codo process is left behind. No account, no network, no model provider.
$ErrorActionPreference = "Stop"
"PowerShell $($PSVersionTable.PSVersion)"

$port = 8765
$base = "http://127.0.0.1:$port"
$work = Join-Path $env:RUNNER_TEMP ("codo ui " + [guid]::NewGuid().ToString("N").Substring(0, 6))
$proj = Join-Path $work "my project"          # a space in the path, like C:\Users\Jan Kowalski
New-Item -ItemType Directory -Force $proj | Out-Null
Set-Content -Path (Join-Path $proj "app.py") -Value "x = 1" -Encoding ascii
$env:DOMA_CONFIG_DIR = Join-Path $work "config"
$env:CODO_LANG = "en"
$env:DOMA_API_URL = "http://127.0.0.1:9"      # nothing listens there: no network calls leave the runner
$env:CODO_ONLINE = "1"
$env:DOMA_NO_SYNC = "1"
$env:CODO_UI_GRACE = "120"
$out = Join-Path $work "ui.out"
$err = Join-Path $work "ui.err"

function Get-Status([string]$Url, [hashtable]$Headers = @{}, [string]$Method = "Get", [string]$Body = $null) {
    try {
        $params = @{ Uri = $Url; Headers = $Headers; Method = $Method; UseBasicParsing = $true; TimeoutSec = 20 }
        if ($Body) { $params.Body = $Body; $params.ContentType = "application/json" }
        $r = Invoke-WebRequest @params
        return [int]$r.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        throw
    }
}

$codo = Join-Path $PWD "codo"
$p = Start-Process python -ArgumentList "`"$codo`"", "ui", "`"$proj`"", "--no-browser", "--port", "$port" `
    -PassThru -NoNewWindow -RedirectStandardOutput $out -RedirectStandardError $err
$null = $p.Handle                              # keeps the exit code readable after the process ends
$engine = 0
try {
    $url = $null
    $deadline = (Get-Date).AddSeconds(40)
    while (-not $url -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        if (Test-Path $out) {
            $m = [regex]::Match((Get-Content $out -Raw -ErrorAction SilentlyContinue) + "", "http://127\.0\.0\.1:$port/\?t=[\w-]+")
            if ($m.Success) { $url = $m.Value }
        }
        if ($p.HasExited) { break }
    }
    if (-not $url) { throw "codo ui did not print its address" }
    $token = $url.Substring($url.IndexOf("?t=") + 3)
    "page: $base/?t=<token>"

    if ((Get-Status "$base/") -ne 403) { throw "the page opened without the token" }
    if ((Get-Status "$base/?t=wrong") -ne 403) { throw "a wrong token was accepted" }
    if ((Get-Status "$base/api/send" @{ "X-Codo-Token" = $token; "Origin" = "http://evil.example" } "Post" "{}") -ne 403) {
        throw "a foreign Origin was accepted"
    }
    $page = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20
    if ($page.StatusCode -ne 200) { throw "page status $($page.StatusCode)" }
    if ($page.Content -notmatch "<title>Codo</title>" -or $page.Content -notmatch '"lang": "en"') { throw "unexpected page" }
    "page loads with the token"

    # The engine (codo app-server, a child process) says "ready" over Server-Sent Events, in UTF-8.
    Add-Type -AssemblyName System.Net.Http
    $hc = New-Object System.Net.Http.HttpClient
    $hc.Timeout = [TimeSpan]::FromSeconds(90)
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, "$base/api/events?t=$token")
    $resp = $hc.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
    if ([int]$resp.StatusCode -ne 200) { throw "events status $([int]$resp.StatusCode)" }
    $reader = New-Object System.IO.StreamReader($resp.Content.ReadAsStreamAsync().Result, [System.Text.Encoding]::UTF8)
    $ready = $null
    $deadline = (Get-Date).AddSeconds(60)
    while (-not $ready -and (Get-Date) -lt $deadline) {
        $line = $reader.ReadLine()
        if ($null -eq $line) { break }
        if ($line.StartsWith("data: ") -and $line.Contains('"type": "ready"')) { $ready = $line.Substring(6) | ConvertFrom-Json }
    }
    if (-not $ready) { throw "no ready event from the engine" }
    if ($ready.cwd -notlike "*my project") { throw "engine works in $($ready.cwd)" }
    "engine ready in $($ready.cwd), version $($ready.version)"

    $info = Invoke-RestMethod -Uri "$base/api/info?t=$token" -TimeoutSec 20
    $engine = [int]$info.engine_pid
    if (-not (Get-Process -Id $engine -ErrorAction SilentlyContinue)) { throw "engine process $engine not found" }

    if ((Get-Status "$base/api/quit" @{ "X-Codo-Token" = $token } "Post" "{}") -ne 200) { throw "quit refused" }
    $reader.Dispose(); $hc.Dispose()
    if (-not $p.WaitForExit(30000)) { throw "codo ui did not stop after quit" }
    if ($p.ExitCode -ne 0) { throw "codo ui exit code $($p.ExitCode)" }
    Start-Sleep -Seconds 1
    if (Get-Process -Id $engine -ErrorAction SilentlyContinue) { throw "engine process $engine is still running" }
    "stopped cleanly, no process left"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    if ($engine -and (Get-Process -Id $engine -ErrorAction SilentlyContinue)) { Stop-Process -Id $engine -Force -ErrorAction SilentlyContinue }
    "--- stdout"; Get-Content $out -ErrorAction SilentlyContinue | ForEach-Object { $_ -replace "\?t=[\w-]+", "?t=<token>" }
    "--- stderr"; Get-Content $err -ErrorAction SilentlyContinue
}
