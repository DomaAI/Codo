#!/usr/bin/env bash
# Codo (komenda: codo; dawne nazwy domaai i doma działają dalej) — instalator CLI · by MADD · Linux + macOS
#   curl -fsSL https://bymadd.pl/install.sh | bash
#   Windows (PowerShell): irm https://bymadd.pl/install.ps1 | iex
#
# Instalator sam dokłada to, czego brakuje, bez pytania o hasło:
#   Python 3.9+   wymagany. Kolejność: Python z systemu → menedżer pakietów (brew, apt, dnf,
#                 pacman, zypper, apk; tylko jako root albo z sudo bez hasła) → prywatna kopia
#                 przez uv w ~/.local/share/codo (bez uprawnień administratora).
#   certyfikaty   wymagane do połączeń HTTPS (ca-certificates albo certifi).
#   git, ripgrep  zalecane; instalowane, gdy jest menedżer pakietów. Codo działa też bez nich.
#
# Zmienne:
#   CODO_BIN_DIR=~/.local/bin   katalog komendy (dawniej DOMA_BIN_DIR)
#   CODO_NO_DEPS=1              niczego nie doinstalowuj, tylko sprawdź i powiedz, czego brakuje
#   CODO_VERSION=v0.22.0        konkretne wydanie (tylko przy źródle „wydanie”)
#   CODO_LANG=pl|en             język komunikatów (domyślnie z ustawień systemu)
set -euo pipefail

DEFAULT_SOURCE="wydanie"          # bymadd: ten serwer; wydanie: pliki wydania z sumami SHA256SUMS
SOURCE="${CODO_SOURCE:-$DEFAULT_SOURCE}"
[ "$SOURCE" = "bymadd" ] || SOURCE="wydanie"
RELEASES_URL="${CODO_RELEASES_URL:-https://github.com/DomaAI/codo/releases}"; RELEASES_URL="${RELEASES_URL%/}"   # adres wydań (źródło „wydanie”)
API_URL="${DOMA_API_URL:-https://bymadd.pl}"; API_URL="${API_URL%/}"
BIN_DIR="${CODO_BIN_DIR:-${DOMA_BIN_DIR:-$HOME/.local/bin}}"
CODO_HOME="${CODO_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/codo}"
TARGET="$BIN_DIR/codo"
NO_DEPS="${CODO_NO_DEPS:-0}"
UV_PYTHON="3.13"                 # wersja prywatnej kopii Pythona
OS="$(uname -s 2>/dev/null || echo unknown)"

if [ "$SOURCE" = "wydanie" ]; then
  if [ -n "${CODO_BASE_URL:-}" ]; then BASE="${CODO_BASE_URL%/}"
  elif [ -z "$RELEASES_URL" ]; then echo "CODO_SOURCE=wydanie: podaj CODO_BASE_URL albo CODO_RELEASES_URL (set CODO_BASE_URL or CODO_RELEASES_URL)." >&2; exit 1
  elif [ -n "${CODO_VERSION:-}" ]; then BASE="$RELEASES_URL/download/$CODO_VERSION"
  else BASE="$RELEASES_URL/latest/download"; fi
  if [ -n "$RELEASES_URL" ]; then INSTALL_CMD="curl -fsSL $RELEASES_URL/latest/download/install.sh | bash"
  else INSTALL_CMD="curl -fsSL $API_URL/install.sh | bash"; fi
else
  INSTALL_CMD="curl -fsSL $API_URL/install.sh | bash"
fi

# ── Język komunikatów: polski przy polskich ustawieniach systemu, inaczej angielski ──
PL=0
case "${CODO_LANG:-${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}}" in pl*|PL*) PL=1 ;; esac
L() { if [ "$PL" = 1 ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓ %s\033[0m\n' "$*"; }
note() { printf '  \033[2m%s\033[0m\n' "$*"; }
warn() { printf '  \033[33m! %s\033[0m\n' "$*"; }
step() { printf '  \033[2m… %s\033[0m\n' "$*"; }
fail() { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

TMP="$(mktemp -d 2>/dev/null || mktemp -d -t codo)"
LOG="$TMP/instalacja.log"
: > "$LOG"
trap 'rm -rf "$TMP"' EXIT
# Ostatnie linie dziennika po nieudanej instalacji pakietu: widać powód bez szukania.
log_tail() { tail -n 6 "$LOG" 2>/dev/null | sed 's/^/      /' >&2 || true; }

# ── Znak MADD: napis i koniczyna z madd.im ───────────────────────────────────
# Rysowany WYŁĄCZNIE pełnymi komórkami malowanymi tłem: Terminal.app z interlinią
# tnie glify bloków (█ ▀ ▄) na paski, a tło komórki wypełnia cały wiersz.
# Kolor: biały na ciemnym tle, czarny na jasnym (tło z OSC 11 przez /dev/tty);
# terminal bez odpowiedzi dostaje odwrócone wideo, czyli kolor swojego tekstu.
term_bg_luma() {
  [ -r /dev/tty ] && [ -w /dev/tty ] || return 0
  local old resp="" rgb
  old="$(stty -g </dev/tty 2>/dev/null)" || return 0
  stty raw -echo min 0 time 3 </dev/tty 2>/dev/null || return 0
  printf '\033]11;?\007' >/dev/tty
  IFS= read -r -d $'\a' -t 1 resp </dev/tty 2>/dev/null || true
  stty "$old" </dev/tty 2>/dev/null || true
  case "$resp" in *rgb:*) ;; *) return 0 ;; esac
  rgb="${resp##*rgb:}"
  case "${rgb:0:2}${rgb:5:2}${rgb:10:2}" in *[!0-9a-fA-F]*|"") return 0 ;; esac
  [ ${#rgb} -ge 12 ] || return 0
  echo $(( (16#${rgb:0:2} * 299 + 16#${rgb:5:2} * 587 + 16#${rgb:10:2} * 114) / 1000 ))
}

banner() {
  local tagline
  tagline="$(L "agent programistyczny w Twoim terminalu" "the coding agent in your terminal")"
  if [ ! -t 1 ] || [ "${TERM:-dumb}" = "dumb" ] || [ -n "${NO_COLOR:-}" ]; then
    printf '\nMADD · Codo, %s\n\n' "$tagline"; return
  fi
  local px=(
    "...........................................##.##....##.##.."
    "##.....##...####....######...######.......#######..#######."
    "###...###..##..##...##...##..##...##.......######..######.."
    "##.#.#.##.########..##...##..##...##.............##........"
    "##..#..##.##....##..##...##..##...##.......######..######.."
    "##.....##.##....##..######...######.......#######..#######."
    "...........................................##.##.#..##.##.."
    "................................................#.........."
    "...............................................#..........."
  )
  local columns luma on sub
  columns="$(tput cols 2>/dev/null || echo 80)"
  luma="$(term_bg_luma)"
  if [ -z "$luma" ]; then on='\033[7m'; sub='\033[2m'
  elif [ "$luma" -gt 140 ]; then on='\033[48;2;17;17;19m'; sub='\033[38;2;105;105;112m'
  else on='\033[48;2;255;255;255m'; sub='\033[38;2;170;170;178m'; fi
  if [ "$columns" -lt $(( ${#px[0]} + 4 )) ]; then
    printf '\n  \033[1mMADD\033[0m  %bCodo, %s\033[0m\n\n' "$sub" "$tagline"; return
  fi
  echo
  local row x line
  for row in "${px[@]}"; do
    line="  "
    for ((x = 0; x < ${#row}; x++)); do
      if [ "${row:x:1}" = "#" ]; then line+="${on} \033[0m"; else line+=" "; fi
    done
    printf '%b\n' "$line"
  done
  printf '\n  \033[1mCodo\033[0m  %b%s\033[0m\n\n' "$sub" "$tagline"
}

banner

# ── Menedżer pakietów i uprawnienia ──────────────────────────────────────────
# Zasada: instalator NIGDY nie pyta o hasło. Pakiety systemowe tylko jako root
# albo z sudo bez hasła; Homebrew działa bez uprawnień administratora.
SUDO=""; CAN_ROOT=0
if [ "$(id -u)" = "0" ]; then CAN_ROOT=1
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then SUDO="sudo"; CAN_ROOT=1; fi

PM=""; BREW=""
for b in brew /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
  if command -v "$b" >/dev/null 2>&1; then BREW="$(command -v "$b")"; break; fi
done
if [ "$OS" != "Darwin" ]; then
  for p in apt-get dnf yum pacman zypper apk; do
    if command -v "$p" >/dev/null 2>&1; then PM="$p"; break; fi
  done
fi
# Homebrew nie działa jako root; na Linuksie jest wyjściem, gdy nie ma uprawnień do pakietów systemu.
if [ -n "$BREW" ] && [ "$(id -u)" != "0" ]; then
  if [ -z "$PM" ] || [ "$CAN_ROOT" = 0 ]; then PM="brew"; fi
fi
if [ "$PM" != "brew" ] && [ "$CAN_ROOT" = 0 ]; then PM_USABLE=0; else PM_USABLE=1; fi
[ -n "$PM" ] || PM_USABLE=0

APT_UPDATED=0
# pm_install PAKIET…  → 0, gdy się udało. Wejście z /dev/null: przy `curl | bash`
# polecenie czytające stdin zjadłoby resztę tego skryptu.
pm_install() {
  [ "$NO_DEPS" = "1" ] && return 1
  [ "$PM_USABLE" = 1 ] || return 1
  case "$PM" in
    brew)
      HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1 HOMEBREW_NO_INSTALL_CLEANUP=1 \
        "$BREW" install "$@" </dev/null >>"$LOG" 2>&1 ;;
    apt-get)
      if [ "$APT_UPDATED" = 0 ]; then
        $SUDO apt-get update -qq </dev/null >>"$LOG" 2>&1 || true; APT_UPDATED=1
      fi
      $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@" </dev/null >>"$LOG" 2>&1 ;;
    dnf|yum) $SUDO "$PM" install -y -q "$@" </dev/null >>"$LOG" 2>&1 ;;
    pacman)
      $SUDO pacman -S --needed --noconfirm "$@" </dev/null >>"$LOG" 2>&1 \
        || $SUDO pacman -Sy --needed --noconfirm "$@" </dev/null >>"$LOG" 2>&1 ;;
    zypper) $SUDO zypper --non-interactive --quiet install "$@" </dev/null >>"$LOG" 2>&1 ;;
    apk) $SUDO apk add --no-cache --quiet "$@" </dev/null >>"$LOG" 2>&1 ;;
    *) return 1 ;;
  esac
}

# Polecenie do ręcznej instalacji (do podpowiedzi, gdy instalator nie mógł sam).
pm_hint() {
  local pre=""
  [ "$(id -u)" = "0" ] || pre="sudo "
  case "$PM" in
    brew) echo "brew install $*" ;;
    apt-get) echo "${pre}apt-get install -y $*" ;;
    dnf|yum) echo "${pre}$PM install -y $*" ;;
    pacman) echo "${pre}pacman -S --needed $*" ;;
    zypper) echo "${pre}zypper install $*" ;;
    apk) echo "${pre}apk add $*" ;;
    *) echo "" ;;
  esac
}

# ── Pobieranie: curl → wget → Python ─────────────────────────────────────────
PY=""; PY_ON_PATH=0
fetch() {  # fetch URL PLIK
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 2 "$1" -o "$2" </dev/null
  elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1" </dev/null
  elif [ -n "$PY" ]; then
    "$PY" -c 'import sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=60) as r, open(sys.argv[2], "wb") as f:
    f.write(r.read())' "$1" "$2" </dev/null
  else return 1; fi
}

# ── Python 3.9+ ──────────────────────────────────────────────────────────────
# Na macOS bez narzędzi wiersza poleceń /usr/bin/python3 i /usr/bin/git to atrapy:
# uruchomione otwierają okno instalacji Xcode. Nie dotykamy ich.
mac_stub() {
  [ "$OS" = "Darwin" ] || return 1
  case "$1" in /usr/bin/python3|/usr/bin/git) ;; *) return 1 ;; esac
  ! xcode-select -p >/dev/null 2>&1
}
py_usable() {
  [ -n "$1" ] && [ -x "$1" ] || return 1
  mac_stub "$1" && return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' </dev/null >/dev/null 2>&1
}
# Ustawia PY. PY_ON_PATH=1, gdy to ten sam Python, który odpali `#!/usr/bin/env python3`;
# inaczej instalator wpisze ścieżkę interpretera do pierwszej linii pliku codo.
find_python() {
  PY=""; PY_ON_PATH=0
  local c p
  p="$(command -v python3 2>/dev/null || true)"
  if py_usable "$p"; then PY="$p"; PY_ON_PATH=1; return 0; fi
  for c in python3.13 python3.12 python3.14 python3.11 python3.10 python3.9 python3.15; do
    p="$(command -v "$c" 2>/dev/null || true)"
    if py_usable "$p"; then PY="$p"; return 0; fi
  done
  for p in "$CODO_HOME/python3" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
           /home/linuxbrew/.linuxbrew/bin/python3 /opt/local/bin/python3 "$HOME/.local/bin/python3" /usr/bin/python3; do
    if py_usable "$p"; then PY="$p"; return 0; fi
  done
  return 1
}

# Prywatna kopia Pythona przez uv (astral.sh): bez administratora, wszystko w $CODO_HOME,
# nic nie trafia do PATH ani do ustawień powłoki.
install_python_uv() {
  local uv p
  uv="$(command -v uv 2>/dev/null || true)"
  if [ -z "$uv" ]; then
    if [ ! -x "$CODO_HOME/uv/uv" ]; then
      fetch "https://astral.sh/uv/install.sh" "$TMP/uv-install.sh" >>"$LOG" 2>&1 || return 1
      mkdir -p "$CODO_HOME/uv"
      UV_UNMANAGED_INSTALL="$CODO_HOME/uv" sh "$TMP/uv-install.sh" </dev/null >>"$LOG" 2>&1 || return 1
    fi
    uv="$CODO_HOME/uv/uv"
  fi
  [ -x "$uv" ] || return 1
  # --no-bin: bez dowiązania python3.13 w ~/.local/bin (starsze uv tej flagi nie zna); pamięć podręczna w katalogu tymczasowym.
  UV_CACHE_DIR="$TMP/uv-cache" UV_PYTHON_INSTALL_DIR="$CODO_HOME/python" "$uv" python install --no-bin "$UV_PYTHON" </dev/null >>"$LOG" 2>&1 \
    || UV_CACHE_DIR="$TMP/uv-cache" UV_PYTHON_INSTALL_DIR="$CODO_HOME/python" "$uv" python install "$UV_PYTHON" </dev/null >>"$LOG" 2>&1 || return 1
  p=""
  for c in "$CODO_HOME"/python/cpython-"$UV_PYTHON"*/bin/python"$UV_PYTHON"; do
    [ -x "$c" ] && p="$c"
  done
  [ -n "$p" ] || return 1
  ln -sf "$p" "$CODO_HOME/python3"
}

install_python() {
  [ "$NO_DEPS" = "1" ] && return 1
  if [ "$PM_USABLE" = 1 ]; then
    step "$(L "Brak Pythona 3.9+, instaluję przez $PM" "Python 3.9+ not found, installing with $PM")"
    case "$PM" in
      pacman) pm_install python || true ;;
      apt-get) pm_install python3 ca-certificates || true ;;
      *) pm_install python3 || true ;;
    esac
    hash -r 2>/dev/null || true
    if find_python; then return 0; fi
  fi
  step "$(L "Instaluję prywatną kopię Pythona $UV_PYTHON (uv, bez uprawnień administratora) w $CODO_HOME" \
            "Installing a private copy of Python $UV_PYTHON (uv, no admin rights) in $CODO_HOME")"
  install_python_uv || return 1
  find_python
}

python_help() {
  local hint
  hint="$(pm_hint python3)"
  [ "$PM" = "pacman" ] && hint="$(pm_hint python)"
  if [ -z "$hint" ]; then
    if [ "$OS" = "Darwin" ]; then hint="xcode-select --install   $(L "albo" "or")   https://www.python.org/downloads/"
    else hint="https://www.python.org/downloads/"; fi
  fi
  printf '%s' "$hint"
}

if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  find_python || true
  if [ -z "$PY" ]; then
    step "$(L "Brak curl i wget, instaluję curl" "curl and wget not found, installing curl")"
    pm_install curl ca-certificates || pm_install curl \
      || fail "$(L "Potrzebny curl albo wget. Zainstaluj: $(pm_hint curl)" "curl or wget is required. Install: $(pm_hint curl)")"
  fi
fi

if find_python; then
  ok "Python $("$PY" -c 'import platform; print(platform.python_version())' </dev/null) ($PY)"
elif install_python; then
  ok "$(L "Zainstalowano Pythona" "Installed Python") $("$PY" -c 'import platform; print(platform.python_version())' </dev/null) ($PY)"
else
  log_tail
  if [ "$NO_DEPS" = "1" ]; then
    fail "$(L "Brak Pythona 3.9+ (CODO_NO_DEPS=1, nic nie doinstalowuję). Zainstaluj: $(python_help)" \
              "Python 3.9+ not found (CODO_NO_DEPS=1, nothing gets installed). Install: $(python_help)")"
  fi
  fail "$(L "Nie udało się zainstalować Pythona 3.9+. Zainstaluj ręcznie: $(python_help), potem uruchom instalator ponownie." \
            "Could not install Python 3.9+. Install it yourself: $(python_help), then run the installer again.")"
fi

# ── Certyfikaty TLS ──────────────────────────────────────────────────────────
# Bez nich Python nie zestawi żadnego połączenia HTTPS. macOS zawsze ma zapas
# (Codo eksportuje korzenie z pęku kluczy), więc sprawdzamy tylko pozostałe systemy.
has_ca() {
  "$PY" -c 'import os, ssl, sys
p = ssl.get_default_verify_paths()
ok = any(x and os.path.exists(x) for x in (p.cafile, p.openssl_cafile, os.environ.get("SSL_CERT_FILE")))
ok = ok or bool(p.capath and os.path.isdir(p.capath) and os.listdir(p.capath))
ok = ok or any(os.path.exists(x) for x in (
    "/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", "/etc/ssl/ca-bundle.pem", "/etc/ssl/cert.pem"))
if not ok:
    try:
        import certifi
        ok = os.path.exists(certifi.where())
    except Exception:
        pass
sys.exit(0 if ok else 1)' </dev/null >/dev/null 2>&1
}
if [ "$OS" != "Darwin" ] && ! has_ca; then
  if [ "$NO_DEPS" != "1" ]; then
    step "$(L "Brak certyfikatów TLS, instaluję" "TLS certificates not found, installing")"
    pm_install ca-certificates || true
    if ! has_ca; then
      "$PY" -m pip install --user --quiet certifi </dev/null >>"$LOG" 2>&1 \
        || "$PY" -m pip install --user --quiet --break-system-packages certifi </dev/null >>"$LOG" 2>&1 || true
    fi
  fi
  if has_ca; then ok "$(L "Certyfikaty TLS" "TLS certificates")"
  else warn "$(L "Brak certyfikatów TLS, Codo nie połączy się z siecią. Zainstaluj: $(pm_hint ca-certificates)" \
                 "No TLS certificates, Codo cannot reach the network. Install: $(pm_hint ca-certificates)")"; fi
fi

# ── Pobranie i weryfikacja ───────────────────────────────────────────────────
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else "$PY" -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$1" </dev/null; fi
}

NEW="$TMP/codo"
if [ "$SOURCE" = "wydanie" ]; then
  fetch "$BASE/codo" "$NEW" || fail "$(L "Pobieranie nie powiodło się" "Download failed"): $BASE/codo"
  fetch "$BASE/SHA256SUMS" "$TMP/SHA256SUMS" || fail "$(L "Pobieranie nie powiodło się" "Download failed"): $BASE/SHA256SUMS"
  EXPECTED_SHA="$(awk '$2 == "codo" || $2 == "*codo" {print $1}' "$TMP/SHA256SUMS" | head -n 1)"
  [ -n "$EXPECTED_SHA" ] || fail "$(L "W SHA256SUMS nie ma wpisu dla codo" "SHA256SUMS has no entry for codo")"
else
  fetch "$API_URL/cli/doma" "$NEW" || fail "$(L "Pobieranie CLI z $API_URL/cli/doma nie powiodło się" "Download from $API_URL/cli/doma failed")"
  # Serwer podaje sumę aktualnego pliku pod /cli/doma.sha256 (audyt 2026-07-10, M6).
  EXPECTED_SHA=""
  if fetch "$API_URL/cli/doma.sha256" "$TMP/sha" 2>/dev/null; then
    EXPECTED_SHA="$(tr -d '[:space:]' < "$TMP/sha" | cut -c1-64)"
  fi
fi
head -c 400 "$NEW" | grep -q "doma" || fail "$(L "Pobrany plik wygląda na uszkodzony" "The downloaded file looks broken")"
if [ -n "$EXPECTED_SHA" ]; then
  ACTUAL_SHA="$(sha256 "$NEW")"
  [ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] \
    || fail "$(L "Suma kontrolna się nie zgadza (SHA-256), instalacja przerwana dla bezpieczeństwa." \
                 "SHA-256 mismatch, installation stopped for safety.")"
  ok "$(L "Suma kontrolna zgodna" "Checksum verified")"
fi
# Próbne uruchomienie pobranego pliku PRZED podmianą starego: obcięte pobranie albo
# plik, który nie rusza na tym Pythonie, nie może zastąpić działającej instalacji.
"$PY" "$NEW" version </dev/null 2>"$TMP/proba.err" | grep -qE '[0-9]+\.[0-9]+\.[0-9]+' || {
  tail -n 5 "$TMP/proba.err" | sed 's/^/      /' >&2 || true
  fail "$(L "Pobrany plik się nie uruchamia (obcięte pobranie?). Nic nie zmieniono, spróbuj ponownie." \
            "The downloaded file does not start (truncated download?). Nothing was changed, try again.")"
}

# ── Instalacja ───────────────────────────────────────────────────────────────
# Numer wersji wyciągamy wzorcem: nazwa programu ma różną liczbę słów
# („DomaAI Code 0.16.5” dawało wersję „Code”).
ver_of() { "$@" version 2>/dev/null </dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true; }
OLD_VER=""
for old_bin in "$TARGET" "$BIN_DIR/domaai" "$BIN_DIR/doma"; do
  if [ -x "$old_bin" ] && [ -z "$OLD_VER" ]; then OLD_VER="$(ver_of "$old_bin")"; fi
done

mkdir -p "$BIN_DIR" || fail "$(L "Nie mogę utworzyć $BIN_DIR" "Cannot create $BIN_DIR")"
[ -w "$BIN_DIR" ] || fail "$(L "Brak prawa zapisu do $BIN_DIR. Wskaż inny katalog: CODO_BIN_DIR=… " \
                              "No write access to $BIN_DIR. Pick another folder: CODO_BIN_DIR=…")"

if [ "$PY_ON_PATH" = 1 ]; then
  cp "$NEW" "$TARGET.tmp"
else
  # `python3` z PATH nie nadaje się (brak albo za stary): wpisujemy znaleziony
  # interpreter do pierwszej linii. `codo update` tę linię zachowuje.
  case "$PY" in
    *[[:space:]]*) PIN_OK=0 ;;
    *) if [ "${#PY}" -le 120 ]; then PIN_OK=1; else PIN_OK=0; fi ;;
  esac
  if [ "$PIN_OK" = 1 ]; then
    { printf '#!%s\n' "$PY"; tail -n +2 "$NEW"; } > "$TARGET.tmp"
  else
    # Ścieżka ze spacją albo za długa na linię #!: program w $CODO_HOME, w BIN_DIR mały starter.
    mkdir -p "$CODO_HOME"
    cp "$NEW" "$CODO_HOME/codo.py"
    printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "$PY" "$CODO_HOME/codo.py" > "$TARGET.tmp"
  fi
fi
chmod 755 "$TARGET.tmp"
mv -f "$TARGET.tmp" "$TARGET"

NEW_VER="$(ver_of "$TARGET")"
if [ -z "$NEW_VER" ]; then
  "$TARGET" version </dev/null 2>&1 | tail -n 5 | sed 's/^/      /' >&2 || true
  fail "$(L "Codo zainstalowane w $TARGET, ale się nie uruchamia (szczegóły wyżej)." \
            "Codo was installed to $TARGET but does not start (details above).")"
fi
if [ -n "$OLD_VER" ] && [ "$OLD_VER" != "$NEW_VER" ]; then
  ok "$(L "Zaktualizowano" "Updated"): $OLD_VER → $NEW_VER ($TARGET)"
elif [ -n "$OLD_VER" ]; then
  ok "$(L "Przeinstalowano" "Reinstalled") $NEW_VER ($TARGET)"
else
  ok "$(L "Zainstalowano Codo" "Installed Codo") $NEW_VER ($TARGET)"
fi

# Dawne nazwy (`domaai`, `doma`, `domaai-code`) zostają jako dowiązania do tego
# samego pliku: skrypty i autostart mostka u obecnych użytkowników działają dalej.
# Stary `domaai` bywa zwykłym plikiem: ln -sf podmienia go na dowiązanie. Instalacja
# ze źródła „wydanie” dokłada je tylko tam, gdzie już były.
for old_name in domaai doma domaai-code; do
  if [ "$SOURCE" != "wydanie" ] || [ -e "$BIN_DIR/$old_name" ] || [ -L "$BIN_DIR/$old_name" ]; then
    ln -sf "$TARGET" "$BIN_DIR/$old_name"
  fi
done

# ── Narzędzia zalecane: git i ripgrep ────────────────────────────────────────
# Codo działa bez nich (szukanie ma zapas w Pythonie), ale z nimi widzi zmiany
# w repozytorium i szuka w kodzie wielokrotnie szybciej.
have_tool() {
  local p
  p="$(command -v "$1" 2>/dev/null || true)"
  [ -n "$p" ] || return 1
  mac_stub "$p" && return 1
  return 0
}
MISSING=""
for pair in git:git rg:ripgrep; do
  tool="${pair%%:*}"; pkg="${pair##*:}"
  if have_tool "$tool"; then continue; fi
  if [ "$NO_DEPS" != "1" ] && [ "$PM_USABLE" = 1 ]; then
    step "$(L "Instaluję $pkg ($PM)" "Installing $pkg ($PM)")"
    if pm_install "$pkg"; then
      hash -r 2>/dev/null || true
      ok "$(L "Zainstalowano" "Installed") $pkg"
      continue
    fi
  fi
  MISSING="$MISSING $pkg"
done
MISSING="${MISSING# }"
if [ -n "$MISSING" ]; then
  # shellcheck disable=SC2086
  HINT="$(pm_hint $MISSING)"
  if [ -z "$HINT" ] && [ "$OS" = "Darwin" ]; then
    case " $MISSING " in *" git "*) HINT="xcode-select --install" ;; esac
    case " $MISSING " in *" ripgrep "*) HINT="${HINT:+$HINT; }https://brew.sh → brew install ripgrep" ;; esac
  fi
  warn "$(L "Zalecane, niezainstalowane: $MISSING. Codo działa bez nich." "Recommended, not installed: $MISSING. Codo works without them.")"
  [ -z "$HINT" ] || note "$(L "Doinstalujesz tak:" "To add them:") $HINT"
fi

# ── PATH ─────────────────────────────────────────────────────────────────────
# Bez wpisu w pliku powłoki „codo” nie zadziała w nowym terminalu. Plik wybieramy
# po powłoce użytkownika i TWORZYMY, gdy go nie ma (świeży macOS nie ma ~/.zshrc).
PATH_MARK="# doma CLI (by MADD)"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    ADDED_RC=""
    add_path_rc() {  # add_path_rc PLIK [fish]
      local rc="$1"
      if [ -f "$rc" ] && grep -qE '# doma CLI \(by MADD\)|# codo \(PATH\)' "$rc" 2>/dev/null; then return 0; fi
      mkdir -p "$(dirname "$rc")" 2>/dev/null || return 0
      if [ "${2:-}" = "fish" ]; then
        printf '\n%s\nfish_add_path -g "%s"\n' "$PATH_MARK" "$BIN_DIR" >> "$rc" 2>/dev/null || return 0
      else
        printf '\n%s\nexport PATH="%s:$PATH"\n' "$PATH_MARK" "$BIN_DIR" >> "$rc" 2>/dev/null || return 0
      fi
      ADDED_RC="$ADDED_RC $(basename "$rc")"
    }
    USER_SHELL="$(basename "${SHELL:-}")"
    case "$USER_SHELL" in
      zsh) add_path_rc "${ZDOTDIR:-$HOME}/.zshrc" ;;
      bash)
        add_path_rc "$HOME/.bashrc"
        # Bash logowania (Terminal na macOS, ssh) czyta .bash_profile albo .profile, nie .bashrc.
        if [ -f "$HOME/.bash_profile" ]; then add_path_rc "$HOME/.bash_profile"
        elif [ -f "$HOME/.profile" ]; then add_path_rc "$HOME/.profile"
        elif [ "$OS" = "Darwin" ]; then add_path_rc "$HOME/.bash_profile"; fi ;;
      fish) add_path_rc "${XDG_CONFIG_HOME:-$HOME/.config}/fish/config.fish" fish ;;
      *) add_path_rc "$HOME/.profile" ;;
    esac
    # Pliki innych powłok, których użytkownik też używa (istniejące, bez tworzenia).
    for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
      if [ -f "$rc" ]; then add_path_rc "$rc"; fi
    done
    if [ -n "$ADDED_RC" ]; then
      ok "$(L "Dodano $BIN_DIR do PATH" "Added $BIN_DIR to PATH") (${ADDED_RC# })"
      if [ "$USER_SHELL" = "fish" ]; then note "$(L "W TYM terminalu odśwież:" "In THIS terminal run:") fish_add_path -g \"$BIN_DIR\""
      else note "$(L "W TYM terminalu odśwież:" "In THIS terminal run:") export PATH=\"$BIN_DIR:\$PATH\""; fi
    else
      note "$(L "Katalog $BIN_DIR jest już wpisany w pliku powłoki; otwórz nowy terminal." \
                "$BIN_DIR is already in your shell file; open a new terminal.")"
    fi
    ;;
esac

echo
if [ "$PL" = 1 ]; then
  say "Zaczynamy"
  echo "  codo login        zaloguj się: konto MaddLabs, konto DomaAI albo własny klucz API"
  echo "  cd twój-projekt   przejdź do folderu z kodem"
  echo "  codo              rozmawiaj z agentem w tym folderze"
  echo
  say "Przydatne"
  echo "  codo -p \"…\"       jedno zadanie bez rozmowy, wynik od razu w terminalu"
  echo "  codo work \"…\"     praca do skutku, nawet godzinami (--bg działa w tle)"
  echo "  codo update       aktualizacja do najnowszej wersji"
  echo "  codo doctor       sprawdzenie instalacji, zależności i połączenia"
  echo
  note "W rozmowie: /help pokazuje wszystkie komendy. Ponowna instalacja: $INSTALL_CMD"
else
  say "Get started"
  echo "  codo login        sign in: MaddLabs account, DomaAI account or your own API key"
  echo "  cd your-project   go to the folder with your code"
  echo "  codo              talk to the agent in this folder"
  echo
  say "Useful"
  echo "  codo -p \"…\"       one task without a conversation, result straight in the terminal"
  echo "  codo work \"…\"     keeps working until done, even for hours (--bg runs in the background)"
  echo "  codo update       update to the newest version"
  echo "  codo doctor       check the installation, dependencies and connection"
  echo
  note "In a session: /help lists every command. Reinstall: $INSTALL_CMD"
fi
