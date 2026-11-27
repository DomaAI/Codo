"""Windows smoke: `codo ui` HTTP API on a real NTFS disk. No account, no network, no model provider.

usage: python ui_api.py <codo command...>     e.g.  python ui_api.py codo     or   python ui_api.py python codo
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CMD = sys.argv[1:] or [sys.executable, "codo"]
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def req(method, url, body=None, headers=None, raw=False):
    data = None
    h = dict(headers or {})
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
    r = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            payload = resp.read()
            return resp.status, payload if raw else _j(payload)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, payload if raw else _j(payload)


def _j(b):
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return b.decode("utf-8", "replace")[:500]


root = Path(os.environ.get("SMOKE_ROOT") or (Path("C:/") if os.name == "nt" else Path(tempfile.mkdtemp())))
work = root / ("codo próba ąę " + os.urandom(3).hex())   # Polish letters and a space, straight in C:\
proj = work / "mój projekt"
proj.mkdir(parents=True)
cfg = work / "konfig"
cfg.mkdir()
home = work / "dom"
home.mkdir()

# a git repo with CRLF files
git = shutil.which("git")
env_git = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
(proj / "crlf.txt").write_bytes("linia 1\r\nlinia 2 zażółć\r\nlinia 3\r\n".encode("utf-8"))
(proj / "app.py").write_bytes(b"x = 1\r\n")
(proj / "zażółć gęślą jaźń.txt").write_bytes("Zażółć gęślą jaźń\r\nDruga linia\r\n".encode("utf-8"))
if git:
    subprocess.run([git, "init", "-q", "-b", "main"], cwd=proj, check=True)
    subprocess.run([git, "config", "core.autocrlf", "true"], cwd=proj, check=True)
    subprocess.run([git, "add", "-A"], cwd=proj, check=True, env=env_git)
    subprocess.run([git, "commit", "-qm", "start"], cwd=proj, check=True, env=env_git)
    (proj / "crlf.txt").write_bytes("linia 1\r\nlinia 2 zmieniona\r\nlinia 3\r\nlinia 4\r\n".encode("utf-8"))
    (proj / "nowy ąę.txt").write_bytes("nowy\r\n".encode("utf-8"))
outside = work / "poza projektem — plik ł.txt"
outside.write_text("poza projektem", encoding="utf-8")

env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DOMA_CONFIG_DIR=str(cfg), DOMA_API_URL="http://127.0.0.1:9",
           CODO_LANG="pl", CODO_ONLINE="1", DOMA_NO_SYNC="1", CODO_APP_LOCAL_ONLY="1", NO_COLOR="1",
           PYTHONUNBUFFERED="1", CODO_UI_GRACE="120")
port = int(os.environ.get("SMOKE_PORT") or 8790)
p = subprocess.Popen([*CMD, "ui", str(proj), "--no-browser", "--port", str(port)], env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
seen, errs = [], []
threading.Thread(target=lambda: [errs.append(l) for l in p.stderr], daemon=True).start()
url = None
deadline = time.time() + 60
while time.time() < deadline and url is None:
    line = p.stdout.readline()
    if not line:
        break
    seen.append(line)
    m = re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line)
    if m:
        url = m.group(0)
threading.Thread(target=lambda: [seen.append(l) for l in p.stdout], daemon=True).start()
check("ui prints its address", url, "".join(seen)[-800:] + "".join(errs)[-800:])
if not url:
    p.kill()
    sys.exit(1)
base = f"http://127.0.0.1:{port}"
tok = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["t"][0]
T = {"X-Codo-Token": tok}
q = lambda s: urllib.parse.quote(str(s))  # noqa: E731

try:
    st, page = req("GET", url, raw=True)
    check("GET / with token = 200", st == 200 and b"<title>Codo</title>" in page, f"{st}")
    st, _ = req("GET", base + "/", raw=True)
    check("GET / without token = 403", st == 403, f"{st}")

    st, info = req("GET", f"{base}/api/info?t={tok}")
    check("/api/info", st == 200 and isinstance(info, dict), f"{st} {str(info)[:300]}")
    print("   info:", json.dumps(info, ensure_ascii=False)[:600])
    st, lic = req("GET", f"{base}/api/license?t={tok}")
    check("/api/license", st == 200 and "needs_acceptance" in lic, f"{st} {lic}")
    st, r = req("POST", f"{base}/api/license", {"use": "personal"}, T)
    st2, lic2 = req("GET", f"{base}/api/license?t={tok}")
    check("POST /api/license personal", st == 200 and lic2.get("use") == "personal", f"{st} {r} {lic2}")

    f = proj / "zażółć gęślą jaźń.txt"
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(f)}")
    check("/api/file/preview polish+space (absolute)", st == 200 and "Zażółć" in str(prev.get("text", "")),
          f"{st} {str(prev)[:300]}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q('zażółć gęślą jaźń.txt')}")
    check("/api/file/preview polish+space (relative)", st == 200 and "Zażółć" in str(prev.get("text", "")),
          f"{st} {str(prev)[:300]}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(str(f).replace(chr(92), '/'))}")
    check("/api/file/preview forward slashes", st == 200, f"{st} {str(prev)[:300]}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(proj)}")
    check("/api/file/preview of the folder", st == 200 and prev.get("kind") == "dir", f"{st} {str(prev)[:300]}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(outside)}")
    check("/api/file/preview outside project = 403", st == 403, f"{st} {str(prev)[:200]}")
    st, at = req("POST", f"{base}/api/file/attach", {"path": str(outside)}, T)
    check("/api/file/attach outside file", st == 200, f"{st} {at}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(outside)}")
    check("/api/file/preview after attach", st == 200 and "poza projektem" in str(prev.get("text", "")),
          f"{st} {str(prev)[:300]}")
    # quoted path pasted from Explorer "Copy as path"
    st, at = req("POST", f"{base}/api/file/attach", {"path": f'"{outside}"'}, T)
    check("/api/file/attach quoted (Copy as path)", st == 200, f"{st} {at}")
    st, raw = req("GET", f"{base}/api/file/raw?t={tok}&p={q(f)}", raw=True)
    check("/api/file/raw bytes unchanged (CRLF kept)", st == 200 and raw == f.read_bytes(), f"{st} {raw[:80]!r}")
    st, inf = req("POST", f"{base}/api/file/info", {"paths": [str(f), "app.py", "nie ma.txt"]}, T)
    items = inf.get("items", {}) if isinstance(inf, dict) else {}
    check("/api/file/info", st == 200 and items.get(str(f)) and items.get("app.py") and items.get("nie ma.txt") is None,
          f"{st} {str(inf)[:400]}")

    if git:
        st, ch = req("GET", f"{base}/api/changes/list?t={tok}")
        files = {x.get("path"): x for x in (ch.get("files") or [])} if isinstance(ch, dict) else {}
        print("   changes:", json.dumps(ch, ensure_ascii=False)[:900])
        check("/api/changes/list git", st == 200 and ch.get("git") is True and "crlf.txt" in files,
              f"{st} {str(ch)[:500]}")
        check("/api/changes/list untracked polish name", "nowy ąę.txt" in files, f"{list(files)}")
        c = files.get("crlf.txt") or {}
        check("crlf.txt counted +2/-1 (CRLF not whole-file)", c.get("added") == 2 and c.get("removed") == 1, f"{c}")
        st, cf = req("GET", f"{base}/api/changes/file?t={tok}&p={q('crlf.txt')}")
        check("/api/changes/file crlf", st == 200 and cf.get("ok"), f"{st} {str(cf)[:400]}")
        print("   changes/file:", json.dumps(cf, ensure_ascii=False)[:700])
        st, cf = req("GET", f"{base}/api/changes/file?t={tok}&p={q('nowy ąę.txt')}")
        check("/api/changes/file polish untracked", st == 200 and cf.get("ok"), f"{st} {str(cf)[:400]}")

    name = "raport roczny — zażółć.txt"
    st, up = req("POST", f"{base}/api/upload", "treść ąę\r\n".encode("utf-8"),
                 dict(T, **{"Content-Type": "application/octet-stream", "X-Codo-Name": q(name)}))
    saved = Path(up.get("path", "")) if isinstance(up, dict) else Path("")
    check("/api/upload polish name", st == 200 and saved.is_file() and saved.read_bytes() == "treść ąę\r\n".encode(),
          f"{st} {up}")
    check("/api/upload keeps polish name", "zażółć" in saved.name, f"{saved}")
    st, prev = req("GET", f"{base}/api/file/preview?t={tok}&p={q(saved)}")
    check("/api/file/preview of upload", st == 200, f"{st} {str(prev)[:200]}")
    st, up = req("POST", f"{base}/api/upload", b"a", dict(T, **{"Content-Type": "application/octet-stream",
                                                               "X-Codo-Name": q('..\\..\\evil:name?.txt'),
                                                               "X-Codo-Dir": q("Folder\\Pod"), "X-Codo-Group": "abcd1234"}))
    sp = Path(up.get("path", "")) if isinstance(up, dict) else Path("")
    check("/api/upload folder + bad chars stays in zalaczniki", st == 200 and sp.is_file() and "zalaczniki" in str(sp)
          and cfg in sp.parents, f"{st} {up}")
    st, fo = req("GET", f"{base}/api/folders?t={tok}")
    check("/api/folders", st == 200, f"{st} {str(fo)[:200]}")
    st, i18 = req("GET", f"{base}/api/i18n?t={tok}&lang=en")
    check("/api/i18n en", st == 200, f"{st}")

    st, _ = req("POST", f"{base}/api/quit", {}, T)
    check("/api/quit", st == 200, f"{st}")
    try:
        code = p.wait(30)
        check("ui exits 0 after quit", code == 0, f"exit {code}")
    except subprocess.TimeoutExpired:
        check("ui exits after quit", False, "timeout")
finally:
    if p.poll() is None:
        if os.name == "nt":   # codo.exe (PyInstaller) is a bootloader + child: kill the whole tree
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        p.kill()
    print("--- stdout\n" + re.sub(r"\?t=[\w-]+", "?t=<token>", "".join(seen))[-3000:])
    print("--- stderr\n" + "".join(errs)[-4000:])

bad = [r for r in RESULTS if not r[1]]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
for n, _, d in bad:
    print("  FAILED:", n, "|", d[:400])
sys.exit(1 if bad else 0)
