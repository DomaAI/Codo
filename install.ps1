# Codo (komenda: codo; dawne nazwy domaai i doma dzialaja dalej) - instalator CLI, by MADD, Windows 10/11
#   PowerShell:  irm https://bymadd.pl/install.ps1 | iex
#
# Instaluje bez uprawnien administratora i sam doklada to, czego brakuje:
#   Python 3.9+   wymagany. Kolejnosc: Python z systemu -> winget (Python.Python.3.13, tylko dla
#                 tego uzytkownika) -> instalator z python.org (sprawdzany podpis cyfrowy).
#   git, ripgrep  zalecane; instalowane przez winget, gdy jest. Codo dziala tez bez nich.
#
# Zmienne: CODO_BIN_DIR (katalog komendy), CODO_NO_DEPS=1 (niczego nie doinstalowuj),
#          CODO_VERSION=v0.22.0 (konkretne wydanie, tylko przy zrodle "wydanie"), CODO_LANG=pl|en.
#
# UWAGA: ten plik ma zostac w CZYSTYM ASCII. Windows PowerShell 5.1 czyta skrypt bez BOM
# jako ANSI, a bajty polskich liter i dlugich myslnikow z UTF-8 zamieniaja sie wtedy
# w cudzyslowy, ktore psuja skladnie (jest na to test).

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # pasek postepu spowalnia Invoke-WebRequest w 5.1 kilkadziesiat razy
# Windows PowerShell 5.1 domyslnie negocjuje TLS 1.0; serwery przyjmuja tylko TLS 1.2+.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch {}

$DefaultSource = "wydanie"          # bymadd: ten serwer; wydanie: pliki wydania z sumami SHA256SUMS
$Source = if ($env:CODO_SOURCE) { $env:CODO_SOURCE } else { $DefaultSource }
if ($Source -ne "bymadd") { $Source = "wydanie" }
$ReleasesUrl = if ($env:CODO_RELEASES_URL) { $env:CODO_RELEASES_URL.TrimEnd("/") } else { "https://github.com/DomaAI/codo/releases" }   # adres wydan (zrodlo "wydanie")
$ApiUrl = if ($env:DOMA_API_URL) { $env:DOMA_API_URL.TrimEnd("/") } else { "https://bymadd.pl" }
$NoDeps = ($env:CODO_NO_DEPS -eq "1")
$PyWinget = "Python.Python.3.13"
$PyOrgVersion = "3.13.9"           # zapas bez winget: instalator z python.org

if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is not set (this installer is for Windows)." }
if ($Source -eq "wydanie") {
    if (-not $env:CODO_BASE_URL -and -not $ReleasesUrl) { throw "CODO_SOURCE=wydanie: set CODO_BASE_URL or CODO_RELEASES_URL." }
    $Base = if ($env:CODO_BASE_URL) { $env:CODO_BASE_URL.TrimEnd("/") }
            elseif ($env:CODO_VERSION) { "$ReleasesUrl/download/$($env:CODO_VERSION)" }
            else { "$ReleasesUrl/latest/download" }
    $DefaultBin = Join-Path $env:LOCALAPPDATA "Codo\bin"
    $ScriptName = "codo.py"
    $InstallCmd = if ($ReleasesUrl) { "irm $ReleasesUrl/latest/download/install.ps1 | iex" } else { "irm $ApiUrl/install.ps1 | iex" }
} else {
    $DefaultBin = Join-Path $env:LOCALAPPDATA "DomaAI\bin"
    $ScriptName = "doma.py"
    $InstallCmd = "irm $ApiUrl/install.ps1 | iex"
}
$BinDir = if ($env:CODO_BIN_DIR) { $env:CODO_BIN_DIR } elseif ($env:DOMA_BIN_DIR) { $env:DOMA_BIN_DIR } else { $DefaultBin }
$Script = Join-Path $BinDir $ScriptName
$Shim = Join-Path $BinDir "codo.cmd"

# Jezyk komunikatow: polski przy polskim systemie, inaczej angielski.
$script:Pl = $false
try {
    if ($env:CODO_LANG) { $script:Pl = $env:CODO_LANG.ToLower().StartsWith("pl") }
    else { $script:Pl = (Get-UICulture).Name.ToLower().StartsWith("pl") }
} catch {}
# Nazwy parametrow nie moga brzmiec "pl": PowerShell nie rozroznia wielkosci liter,
# wiec parametr $pl przeslonilby przelacznik $Pl i komunikaty byly zawsze po polsku.
function T($textPl, $textEn) { if ($script:Pl) { return $textPl } else { return $textEn } }

function Say($msg)  { Write-Host $msg -ForegroundColor White }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Note($msg) { Write-Host "  $msg" -ForegroundColor DarkGray }
function Warn($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Step($msg) { Write-Host "  ... $msg" -ForegroundColor DarkGray }
# `throw` zamiast wyjscia z kodem bledu: pod `irm | iex` exit ZAMKNALBY cala sesje i okno.
function Fail($msg) { Write-Host "  [X] $msg" -ForegroundColor Red; throw $msg }

# Zapis pliku .cmd w kodowaniu OEM konsoli (cp852 dla PL): cmd.exe NIE czyta
# UTF-8, wiec litery spoza ASCII w sciezce (C:\Users\Pawel z kreska) rozjechalyby starter.
function Write-CmdFile($path, $body) {
    try {
        $oemCp = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Nls\CodePage" -Name OEMCP).OEMCP
        $enc = [System.Text.Encoding]::GetEncoding([int]$oemCp)
    } catch {
        $enc = [System.Text.Encoding]::Default
    }
    [System.IO.File]::WriteAllText($path, $body, $enc)
}

# Znak MADD: napis i koniczyna z madd.im, pelne komorki malowane tlem (biale).
# Bez obslugi sekwencji VT (stara konsola): sam tekst.
function Show-MaddBanner {
    $rows = @('...........................................##.##....##.##..', '##.....##...####....######...######.......#######..#######.', '###...###..##..##...##...##..##...##.......######..######..', '##.#.#.##.########..##...##..##...##.............##........', '##..#..##.##....##..##...##..##...##.......######..######..', '##.....##.##....##..######...######.......#######..#######.', '...........................................##.##.#..##.##..', '................................................#..........', '...............................................#...........')
    $tagline = T "agent programistyczny w Twoim terminalu" "the coding agent in your terminal"
    $vt = $false
    try { $vt = [bool]$Host.UI.SupportsVirtualTerminal } catch {}
    $wide = $true
    try { $wide = $Host.UI.RawUI.WindowSize.Width -ge ($rows[0].Length + 4) } catch {}
    Write-Host ""
    if ($vt -and $wide -and -not $env:NO_COLOR) {
        $e = [char]27
        foreach ($row in $rows) {
            $line = "  "
            foreach ($ch in $row.ToCharArray()) {
                if ($ch -eq '#') { $line += "$e[48;2;255;255;255m $e[0m" } else { $line += " " }
            }
            Write-Host $line
        }
        Write-Host ""
        Write-Host "  $e[1mCodo$e[0m  $e[38;2;170;170;178m$tagline$e[0m"
    } else {
        Write-Host "  MADD  Codo, $tagline" -ForegroundColor White
    }
    Write-Host ""
}
Show-MaddBanner

# Uruchamia program i zwraca jego wyjscie jako tekst; $null, gdy sie nie udalo.
# Bledy programu (stderr) nie moga przerwac instalatora: atrapa `python.exe` ze
# Sklepu Microsoft pisze tylko na stderr i konczy sie kodem 9009.
function Invoke-Quiet($exe, [string[]]$arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $exe @arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return (($out | Out-String).Trim())
    } catch {
        return $null
    } finally {
        $ErrorActionPreference = $old
    }
}

# ---- Python 3.9+ -------------------------------------------------------------
$MinPython = [version]"3.9"

# Zwraca sciezke prawdziwego python.exe (>= 3.9) albo $null.
function Test-Python($exe, [string[]]$pre) {
    if (-not $exe) { return $null }
    $probe = "import sys;print('%d.%d|%s' % (sys.version_info[0], sys.version_info[1], sys.executable))"
    $out = Invoke-Quiet $exe (@($pre) + @("-c", $probe))
    if (-not $out -or $out -notmatch '^(\d+\.\d+)\|(.+)$') { return $null }
    if ([version]$Matches[1] -lt $MinPython) { return $null }
    $real = $Matches[2].Trim()
    if ($real -and (Test-Path -LiteralPath $real)) { return $real }
    return $null
}

function Find-Python {
    foreach ($cand in @("py", "python", "python3")) {
        $cmd = Get-Command $cand -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $cmd) { continue }
        $pre = if ($cand -eq "py") { @("-3") } else { @() }
        $found = Test-Python $cmd.Source $pre
        if ($found) { return $found }
    }
    # Python zainstalowany przed chwila nie jest jeszcze w PATH tej sesji: znane katalogi.
    $roots = @()
    if ($env:LOCALAPPDATA) { $roots += (Join-Path $env:LOCALAPPDATA "Programs\Python") }
    if ($env:ProgramFiles) { $roots += $env:ProgramFiles }
    if (${env:ProgramFiles(x86)}) { $roots += ${env:ProgramFiles(x86)} }
    if ($env:SystemDrive) { $roots += ($env:SystemDrive + "\") }
    $dirs = @()
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $dirs += @(Get-ChildItem -LiteralPath $root -Directory -Filter "Python3*" -ErrorAction SilentlyContinue)
    }
    # Najnowsza wersja pierwsza: Python313 przed Python39 (porownanie liczbowe, nie tekstowe).
    $dirs = $dirs | Sort-Object -Descending { if ($_.Name -match '^Python3(\d+)') { [int]$Matches[1] } else { 0 } }
    foreach ($dir in $dirs) {
        $found = Test-Python (Join-Path $dir.FullName "python.exe") @()
        if ($found) { return $found }
    }
    return $null
}

function Get-Winget {
    $cmd = Get-Command winget -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

# winget install; $true, gdy pakiet jest zainstalowany. Starszy winget nie zna
# --disable-interactivity, wiec druga proba idzie bez tej flagi.
function Install-WithWinget($id, [string[]]$extra) {
    $winget = Get-Winget
    if (-not $winget) { return $false }
    $base = @("install", "-e", "--id", $id, "--silent", "--accept-package-agreements", "--accept-source-agreements") + @($extra)
    foreach ($quiet in @($true, $false)) {
        $argv = if ($quiet) { $base + @("--disable-interactivity") } else { $base }
        $old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & $winget @argv 2>&1 | Out-Null
            $code = $LASTEXITCODE
        } catch { $code = 1 } finally { $ErrorActionPreference = $old }
        # 0 = zainstalowano; -1978335189 = juz zainstalowany, brak nowszej wersji.
        if ($code -eq 0 -or $code -eq -1978335189) { return $true }
    }
    return $false
}

function Install-PythonOrg {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    $suffix = switch ($arch) { "ARM64" { "-arm64" } "AMD64" { "-amd64" } default { "" } }
    $url = "https://www.python.org/ftp/python/$PyOrgVersion/python-$PyOrgVersion$suffix.exe"
    $exe = Join-Path ([System.IO.Path]::GetTempPath()) ("codo-python-" + [guid]::NewGuid().ToString("N") + ".exe")
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $exe
        # Uruchamiamy tylko plik z waznym podpisem Python Software Foundation.
        $sig = Get-AuthenticodeSignature -FilePath $exe
        if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Python Software Foundation") { return $false }
        $p = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
            "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=0", "Include_test=0", "Include_doc=0")
        return ($p.ExitCode -eq 0)
    } catch {
        return $false
    } finally {
        Remove-Item -Force $exe -ErrorAction SilentlyContinue
    }
}

$Python = Find-Python
if ($Python) {
    Ok "Python: $Python"
} else {
    $manual = T "Zainstaluj Pythona z https://www.python.org/downloads/ (zaznacz 'Add python.exe to PATH') i uruchom instalator ponownie." "Install Python from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and run this installer again."
    if ($NoDeps) { Fail ((T "Brak Pythona 3.9+ (CODO_NO_DEPS=1, nic nie doinstalowuje). " "Python 3.9+ not found (CODO_NO_DEPS=1, nothing gets installed). ") + $manual) }
    if (Get-Winget) {
        Step (T "Brak Pythona 3.9+, instaluje przez winget (tylko dla tego uzytkownika, bez administratora)" "Python 3.9+ not found, installing with winget (this user only, no admin rights)")
        [void](Install-WithWinget $PyWinget @("--scope", "user"))
        $Python = Find-Python
    }
    if (-not $Python) {
        Step (T "Pobieram instalator Pythona $PyOrgVersion z python.org (to moze potrwac minute)" "Downloading the Python $PyOrgVersion installer from python.org (this can take a minute)")
        [void](Install-PythonOrg)
        $Python = Find-Python
    }
    if (-not $Python) { Fail ((T "Nie udalo sie zainstalowac Pythona. " "Could not install Python. ") + $manual) }
    Ok ((T "Zainstalowano Pythona: " "Installed Python: ") + $Python)
}

# ---- Pobranie i weryfikacja ---------------------------------------------------
function Get-CliVersion($shimPath) {
    # Numer wersji wzorcem: nazwa programu ma rozna liczbe slow
    # ("DomaAI Code 0.16.5" dawalo wersje "Code").
    $out = Invoke-Quiet $shimPath @("version")
    if ($out -and $out -match '\d+\.\d+\.\d+') { return $Matches[0] }
    return ""
}

$OldVer = ""
foreach ($oldShim in @($Shim, (Join-Path $BinDir "domaai.cmd"), (Join-Path $BinDir "doma.cmd"))) {
    if (-not $OldVer -and (Test-Path -LiteralPath $oldShim)) { $OldVer = Get-CliVersion $oldShim }
}

try { New-Item -ItemType Directory -Force -Path $BinDir | Out-Null }
catch { Fail ((T "Nie moge utworzyc katalogu " "Cannot create folder ") + "$BinDir : $($_.Exception.Message)") }

$Tmp = "$Script.tmp"
$expected = ""
if ($Source -eq "wydanie") {
    try { Invoke-WebRequest -UseBasicParsing -Uri "$Base/codo" -OutFile $Tmp }
    catch { Fail ((T "Pobieranie nie powiodlo sie: " "Download failed: ") + "$Base/codo : $($_.Exception.Message)") }
    try { $sums = (Invoke-WebRequest -UseBasicParsing -Uri "$Base/SHA256SUMS").Content }
    catch { Remove-Item -Force $Tmp -ErrorAction SilentlyContinue; Fail ((T "Pobieranie nie powiodlo sie: " "Download failed: ") + "$Base/SHA256SUMS") }
    if ($sums -is [byte[]]) { $sums = [System.Text.Encoding]::ASCII.GetString($sums) }
    foreach ($line in ($sums -split "`n")) {
        $parts = $line.Trim() -split "\s+"
        if ($parts.Count -ge 2 -and ($parts[1] -eq "codo" -or $parts[1] -eq "*codo")) { $expected = $parts[0].ToLower(); break }
    }
    if (-not $expected) { Remove-Item -Force $Tmp -ErrorAction SilentlyContinue; Fail (T "W SHA256SUMS nie ma wpisu dla codo" "SHA256SUMS has no entry for codo") }
} else {
    try { Invoke-WebRequest -UseBasicParsing -Uri "$ApiUrl/cli/doma" -OutFile $Tmp }
    catch { Fail ((T "Pobieranie CLI nie powiodlo sie: " "Download failed: ") + "$ApiUrl/cli/doma : $($_.Exception.Message)") }
    # Serwer podaje sume aktualnego pliku pod /cli/doma.sha256 (audyt 2026-07-10, M6).
    try {
        $raw = (Invoke-WebRequest -UseBasicParsing -Uri "$ApiUrl/cli/doma.sha256").Content
        if ($raw -is [byte[]]) { $raw = [System.Text.Encoding]::ASCII.GetString($raw) }
        $raw = "$raw".Trim().ToLower()
        if ($raw.Length -ge 64) { $expected = $raw.Substring(0, 64) }
    } catch { }
}
$head = Get-Content -LiteralPath $Tmp -TotalCount 8 -ErrorAction SilentlyContinue
if (-not ($head -join "`n").Contains("doma")) {
    Remove-Item -Force $Tmp -ErrorAction SilentlyContinue
    Fail (T "Pobrany plik wyglada na uszkodzony" "The downloaded file looks broken")
}
if ($expected) {
    $actual = (Get-FileHash -LiteralPath $Tmp -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Remove-Item -Force $Tmp -ErrorAction SilentlyContinue
        Fail (T "Suma kontrolna sie nie zgadza (SHA-256), instalacja przerwana dla bezpieczenstwa." "SHA-256 mismatch, installation stopped for safety.")
    }
    Ok (T "Suma kontrolna zgodna" "Checksum verified")
}
# Probne uruchomienie pobranego pliku PRZED podmiana starego: obciete pobranie albo
# plik, ktory nie rusza na tym Pythonie, nie moze zastapic dzialajacej instalacji.
$probe = Invoke-Quiet $Python @($Tmp, "version")
if (-not $probe -or $probe -notmatch '\d+\.\d+\.\d+') {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $Python $Tmp version 2>&1 | Select-Object -Last 6 | ForEach-Object { Write-Host "      $_" } } catch {}
    $ErrorActionPreference = $old
    Remove-Item -Force $Tmp -ErrorAction SilentlyContinue
    Fail (T "Pobrany plik sie nie uruchamia (obciete pobranie?). Nic nie zmieniono, sprobuj ponownie." "The downloaded file does not start (truncated download?). Nothing was changed, try again.")
}
try { Move-Item -Force -LiteralPath $Tmp -Destination $Script }
catch { Fail ((T "Nie moge zapisac " "Cannot write ") + "$Script. " + (T "Zamknij dzialajace Codo i sprobuj ponownie." "Close any running Codo and try again.")) }

# ---- Startery: codo.cmd + dawne domaai.cmd, doma.cmd, domaai-code.cmd ---------
# Instalacja ze zrodla "wydanie" doklada dawne nazwy tylko tam, gdzie juz byly.
$shimBody = "@echo off`r`n`"$Python`" `"$Script`" %*`r`n"
Write-CmdFile $Shim $shimBody
foreach ($oldName in @("domaai.cmd", "doma.cmd", "domaai-code.cmd")) {
    $oldPath = Join-Path $BinDir $oldName
    if ($Source -ne "wydanie" -or (Test-Path -LiteralPath $oldPath)) { Write-CmdFile $oldPath $shimBody }
}

$NewVer = Get-CliVersion $Shim
if (-not $NewVer) {
    # Druga proba wprost przez Pythona, z bledem na ekranie: widac powod.
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { & $Python $Script version 2>&1 | Select-Object -Last 6 | ForEach-Object { Write-Host "      $_" } } catch {}
    $ErrorActionPreference = $old
    Fail ((T "Codo zainstalowane w " "Codo was installed to ") + $BinDir + (T ", ale sie nie uruchamia (szczegoly wyzej)." " but does not start (details above)."))
}
if ($OldVer -and $OldVer -ne $NewVer) { Ok ((T "Zaktualizowano: " "Updated: ") + "$OldVer -> $NewVer ($BinDir)") }
elseif ($OldVer)                      { Ok ((T "Przeinstalowano " "Reinstalled ") + "$NewVer ($BinDir)") }
else                                  { Ok ((T "Zainstalowano Codo " "Installed Codo ") + "$NewVer ($BinDir)") }

# ---- Skrot "Codo" w menu Start: okno aplikacji (codo okno), jak po instalatorze .exe ----
if ($ScriptName -eq "codo.py" -and -not $env:CODO_NO_SHORTCUT) {
    try {
        $programs = [Environment]::GetFolderPath("Programs")
        $ico = Join-Path $BinDir "codo.ico"
        try { Invoke-WebRequest -UseBasicParsing -Uri "https://raw.githubusercontent.com/DomaAI/Codo/main/assets/codo.ico" -OutFile $ico -TimeoutSec 20 } catch {}
        $sh = New-Object -ComObject WScript.Shell
        $lnk = $sh.CreateShortcut((Join-Path $programs "Codo.lnk"))
        $lnk.TargetPath = $Python
        $lnk.Arguments = "`"$Script`" okno"
        $lnk.WorkingDirectory = $HOME
        $lnk.WindowStyle = 7
        $lnk.Description = "Codo"
        if (Test-Path -LiteralPath $ico) { $lnk.IconLocation = "$ico,0" }
        $lnk.Save()
        Ok (T "Skrot Codo w menu Start: otwiera okno Codo" "Codo shortcut in the Start menu: opens the Codo window")
    } catch { Note (T "Nie udalo sie dodac skrotu w menu Start (codo ui dziala z terminala)." "Could not add the Start menu shortcut (codo ui works from a terminal).") }
}

# ---- Narzedzia zalecane: git i ripgrep ----------------------------------------
# Codo dziala bez nich, ale z gitem widzi zmiany w repozytorium (i ma bash do
# polecen), a z ripgrep szuka w kodzie wielokrotnie szybciej.
$missing = @()
foreach ($tool in @(@("git", "Git.Git"), @("rg", "BurntSushi.ripgrep.MSVC"))) {
    if (Get-Command $tool[0] -CommandType Application -ErrorAction SilentlyContinue) { continue }
    $done = $false
    if (-not $NoDeps -and (Get-Winget)) {
        Step ((T "Instaluje " "Installing ") + $tool[1] + " (winget)")
        $done = Install-WithWinget $tool[1] @()
        if ($done) { Ok ((T "Zainstalowano " "Installed ") + $tool[1]) }
    }
    if (-not $done) { $missing += $tool[1] }
}
if ($missing.Count -gt 0) {
    Warn ((T "Zalecane, niezainstalowane: " "Recommended, not installed: ") + ($missing -join ", ") + (T ". Codo dziala bez nich." ". Codo works without them."))
    foreach ($id in $missing) { Note "winget install -e --id $id" }
}

# ---- PATH uzytkownika (idempotentnie, bez administratora) ---------------------
# Piszemy przez rejestr z zachowaniem typu wartosci: jesli Path byl REG_EXPAND_SZ
# (zawiera %USERPROFILE% itp.), SetEnvironmentVariable splaszczylby go do REG_SZ.
$pathAdded = $false
try {
    $envKey = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)
    if (-not $envKey) { $envKey = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey("Environment") }
    $rawPath = $envKey.GetValue("Path", "", [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    try { if ($rawPath -ne "") { $kind = $envKey.GetValueKind("Path") } } catch {}
    $parts = @($rawPath -split ";" | Where-Object { $_ -ne "" })
    if (-not ($parts | Where-Object { $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })) {
        $newPath = if ($rawPath -ne "") { "$BinDir;$rawPath" } else { $BinDir }
        $envKey.SetValue("Path", $newPath, $kind)
        $pathAdded = $true
    }
    $envKey.Close()
} catch {
    Warn ((T "Nie udalo sie dopisac do PATH automatycznie. Dodaj recznie: " "Could not update PATH automatically. Add it yourself: ") + $BinDir)
}
if ($pathAdded) {
    # Sam zapis w rejestrze nie wystarcza: Eksplorator i nowe okna terminala biora
    # zmienne z pamieci, dopoki nie dostana komunikatu WM_SETTINGCHANGE. Bez niego
    # komenda `codo` dzialala dopiero po wylogowaniu. Zapis dowolnej zmiennej
    # uzytkownika przez .NET rozsyla ten komunikat.
    try {
        [Environment]::SetEnvironmentVariable("CODO_PATH_REFRESH", "1", "User")
        [Environment]::SetEnvironmentVariable("CODO_PATH_REFRESH", $null, "User")
    } catch {}
    Ok ((T "Dodano do PATH uzytkownika: " "Added to your PATH: ") + $BinDir)
}
# W TEJ sesji komenda dziala od razu (irm | iex wykonuje sie w biezacym oknie).
if (-not (($env:Path -split ";") | Where-Object { $_.TrimEnd("\") -ieq $BinDir.TrimEnd("\") })) {
    $env:Path = "$BinDir;" + $env:Path
}
# Narzedzia doinstalowane przez winget trafiaja do PATH dopiero w nowym oknie.
$wingetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
if ((Test-Path -LiteralPath $wingetLinks) -and -not (($env:Path -split ";") -contains $wingetLinks)) { $env:Path += ";$wingetLinks" }

Write-Host ""
if ($script:Pl) {
    Say "Zaczynamy"
    Write-Host "  codo login        zaloguj sie: konto MaddLabs, konto DomaAI albo wlasny klucz API"
    Write-Host "  cd twoj-projekt   przejdz do folderu z kodem"
    Write-Host "  codo              rozmawiaj z agentem w tym folderze"
    Write-Host ""
    Say "Przydatne"
    Write-Host "  codo -p `"...`"     jedno zadanie bez rozmowy, wynik od razu w terminalu"
    Write-Host "  codo work `"...`"   praca do skutku, nawet godzinami (--bg dziala w tle)"
    Write-Host "  codo update       aktualizacja do najnowszej wersji"
    Write-Host "  codo doctor       sprawdzenie instalacji, zaleznosci i polaczenia"
    Write-Host ""
    Note "W tym oknie komenda codo dziala od razu. W innych: otworz NOWE okno terminala."
    Note "Ponowna instalacja: $InstallCmd"
} else {
    Say "Get started"
    Write-Host "  codo login        sign in: MaddLabs account, DomaAI account or your own API key"
    Write-Host "  cd your-project   go to the folder with your code"
    Write-Host "  codo              talk to the agent in this folder"
    Write-Host ""
    Say "Useful"
    Write-Host "  codo -p `"...`"     one task without a conversation, result straight in the terminal"
    Write-Host "  codo work `"...`"   keeps working until done, even for hours (--bg runs in the background)"
    Write-Host "  codo update       update to the newest version"
    Write-Host "  codo doctor       check the installation, dependencies and connection"
    Write-Host ""
    Note "The codo command works in this window right away. Elsewhere: open a NEW terminal window."
    Note "Reinstall: $InstallCmd"
}
