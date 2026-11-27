"""codo ui: okno Codo w przeglądarce (Windows, Linux, Mac). Bez sieci zewnętrznej i bez dostawców modeli:
atrapa zgodna z /v1 działa lokalnie jako konto „@atrapa/atrapa-1”, a test rozmawia ze stroną tak jak
przeglądarka (token w adresie, POST /api/send, zdarzenia przez Server-Sent Events)."""
import http.client
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa, sprzataj  # noqa: E402

SCRIPT = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))

ANSWER = ("## Struktura projektu\n\nTo odpowiedź **atrapy** modelu. Najważniejsze pliki:\n\n"
          "- `app.py` uruchamia aplikację\n- `tests/` zawiera testy\n\n"
          "```python\ndef main():\n    print(\"hej\")\n```\n\n| Plik | Rola |\n| --- | --- |\n| app.py | start |\n")
NOTE = "# Notatka\n\nPlan na dziś:\n\n1. Testy\n2. Wydanie\n"
DONE = "Zapisałem **notatka.md** i uruchomiłem sprawdzenie. Komenda zwróciła `gotowe`."


def _chunks(text, n=12):
    return [text[i:i + n] for i in range(0, len(text), n)]


class FakeModel(BaseHTTPRequestHandler):
    """Atrapa /v1: zwykła odpowiedź z markdownem, a na „zapisz” dwa narzędzia (plik i komenda)."""
    calls: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json(200, {"data": [{"id": "atrapa-1"}, {"id": "atrapa-mini"}]})
        return self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        type(self).calls.append(body)
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        user = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
        user_text = json.dumps(user.get("content"), ensure_ascii=False).lower()
        calls, text = [], ANSWER
        if last.get("role") == "tool":
            text = DONE
        elif "umow" in user_text and body.get("tools"):
            text = ""
            calls = [{"id": "c1", "type": "function", "function": {"name": "office_edit", "arguments": json.dumps(
                {"path": "umowa.docx", "action": "replace", "find": "Kaucja wynosi 2000 zł.",
                 "replace": "Kaucja wynosi 3000 zł."})}}]
        elif "zapisz" in user_text and body.get("tools"):
            text = ""
            calls = [{"id": "c1", "type": "function", "function": {
                         "name": "write_file", "arguments": json.dumps({"path": "notatka.md", "content": NOTE})}},
                     {"id": "c2", "type": "function", "function": {
                         "name": "run_command", "arguments": json.dumps({"command": "echo gotowe",
                                                                          "reason": "Sprawdzenie, że plik jest gotowy."})}}]
        if not body.get("stream"):
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            return self._json(200, {"model": body.get("model"), "choices": [{"message": msg}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        out = []
        for piece in _chunks(text):
            out.append({"choices": [{"delta": {"content": piece}}]})
        for i, c in enumerate(calls):
            out.append({"choices": [{"delta": {"tool_calls": [{"index": i, "id": c["id"], "type": "function",
                                                               "function": {"name": c["function"]["name"],
                                                                            "arguments": c["function"]["arguments"]}}]}}]})
        out.append({"choices": [{"delta": {}, "finish_reason": "tool_calls" if calls else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        for ev in out:
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")


def make_docx(paragraphs: list) -> bytes:
    """Mały dokument Worda z zipa: tytuł (styl Title), akapity i tabela, jak z Worda (przestrzenie nazw, relacje)."""
    import io
    import zipfile
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    decl = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    rt = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    body = '<w:p><w:pPr><w:pStyle w:val="Tytul"/></w:pPr><w:r><w:t>Umowa najmu</w:t></w:r></w:p>' + "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{t}</w:t></w:r></w:p>' for t in paragraphs) + (
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Pozycja</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Kwota</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>Czynsz</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>2000</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    files = {
        "[Content_Types].xml": decl + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": decl + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rt}officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": decl + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rt}styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": decl + f'<w:document {w}><w:body>{body}<w:sectPr/></w:body></w:document>',
        "word/styles.xml": decl + f'<w:styles {w}><w:style w:type="paragraph" w:styleId="Tytul"><w:name w:val="Title"/></w:style></w:styles>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(zipfile.ZipInfo(name, (2026, 11, 27, 10, 0, 0)), data)
    return buf.getvalue()


def start_fake_model():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


class FakeDomaAI(BaseHTTPRequestHandler):
    """Atrapa serwera DomaAI dla logowania kodem z maila (te same wywołania co `codo login` i aplikacja na Maca):
    123456 konto jest, 222222 nowy adres (bilet rejestracji), 333333 2FA (kod z aplikacji 654321), inne: zły kod."""
    calls: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        FakeDomaAI.calls.append(("GET", self.path.split("?")[0], {}))
        if self.path.startswith("/cli/whoami"):
            return self._json(200, {"plan": "base", "imie": "Marta"})
        return self._json(404, {"detail": "brak"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode() if n else ""
        f = json.loads(raw) if "json" in (self.headers.get("Content-Type") or "") and raw else \
            {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        path = self.path.split("?")[0]
        FakeDomaAI.calls.append(("POST", path, f))
        if path == "/auth/kod":
            if f.get("email", "").endswith("@cloud.com"):
                return self._json(400, {"detail": "literówka", "sugestia": f["email"].replace("@cloud.com", "@icloud.com")})
            return self._json(200, {"ok": True, "ponownie_za": 60})
        if path == "/auth/kod/weryfikuj":
            code = f.get("code")
            if code == "222222":
                return self._json(200, {"status": "rejestracja", "bilet": "b1", "email": f.get("email")})
            if code == "333333" and f.get("totp_code") != "654321":
                return self._json(403, {"detail": "2fa", "requires_2fa": True})
            if code in ("123456", "333333"):
                return self._json(200, {"access_token": "tok", "user": {"full_name": "Marta"}})
            return self._json(401, {"detail": "zły kod", "pozostalo_prob": 4})
        if path == "/auth/kod/rejestracja":
            return self._json(200, {"access_token": "tok", "full_name": f.get("full_name")})
        if path == "/cli/pair/self":
            return self._json(200, {"device_id": "dev1", "device_secret": "sek", "name": "Komputer testowy"})
        if path == "/cli/pair/token":
            return self._json(200, {"access_token": "devtok", "expires_in": 3600})
        if path in ("/logout", "/cli/device/logout"):
            return self._json(200, {"ok": True})
        return self._json(404, {"detail": "brak " + path})


def start_fake_domaai():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeDomaAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def make_env(root: Path, model_url: str, lang: str = "pl") -> dict:
    """Czysty HOME i konfiguracja: jedno konto API (atrapa), bez konta DomaAI i bez lustra sesji."""
    home = root / "home"
    cfg = home / ".config" / "doma"
    cfg.mkdir(parents=True)
    (cfg / "konta.json").write_text(json.dumps({"konta": {"atrapa": {
        "base_url": model_url, "api_key": "sk-test", "name": "Atrapa", "model": "atrapa-1"}}, "aktywne": "atrapa"}), encoding="utf-8")
    (cfg / "settings.json").write_text(json.dumps({"provider": "endpoint", "model_endpoint": "@atrapa/atrapa-1",
                                                   "lang": lang}), encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DOMA_CONFIG_DIR=str(cfg),
               DOMA_API_URL="http://127.0.0.1:9", CODO_LANG=lang, CODO_ONLINE="1", DOMA_NO_SYNC="1",
               CODO_APP_LOCAL_ONLY="1", NO_COLOR="1", PYTHONUNBUFFERED="1")
    for k in ("CODO_PROVIDER", "CODO_APP_MODE", "CODO_NO_HISTORY", "CODO_OFFLINE", "CODO_UI_DEV"):
        env.pop(k, None)
    return env


def start_ui(proj: Path, env: dict, *extra):
    p = subprocess.Popen([sys.executable, SCRIPT, "ui", str(proj), "--no-browser", *extra], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8")
    url, seen = None, []
    deadline = time.time() + 90   # wolne maszyny CI (macOS): silnik okna startuje kilkanaście sekund
    while time.time() < deadline and url is None:
        line = p.stdout.readline()
        if not line:
            break
        seen.append(line)
        m = re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line)
        if m:
            url = m.group(0)
    if url is None:
        p.kill()
        raise AssertionError("codo ui nie podał adresu: " + "".join(seen) + p.stderr.read())
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
    u = urllib.parse.urlparse(url)
    return p, url, u.port, urllib.parse.parse_qs(u.query)["t"][0]


def pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, encoding="utf-8").stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # zombie (już zakończony, czeka na odebranie) to też koniec
    try:
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        return bool(st) and not st.startswith("Z")
    except OSError:
        return True


class Client:
    """Przeglądarka w miniaturze: żądania z tokenem i słuchacz zdarzeń SSE w tle."""

    def __init__(self, port, token):
        self.port, self.token = port, token
        self.events: "queue.Queue" = queue.Queue()
        self.all: list = []
        self.conn = None

    def req(self, method, path, body=None, headers=None, token=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            h["Content-Type"] = "application/json"
        if token and method == "POST":
            h["X-Codo-Token"] = self.token
        h.update(headers or {})
        if token and method == "GET":
            path += ("&" if "?" in path else "?") + "t=" + self.token
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
        r = c.getresponse()
        data = r.read()
        hdrs = dict(r.getheaders())
        c.close()
        return r.status, data, hdrs

    def send(self, msg):
        return self.req("POST", "/api/send", msg)

    def listen(self):
        self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        self.conn.request("GET", f"/api/events?t={self.token}", headers={"Host": f"127.0.0.1:{self.port}"})
        r = self.resp = self.conn.getresponse()
        assert r.status == 200, r.status
        assert r.getheader("Content-Type").startswith("text/event-stream")

        def run():
            buf = {}
            try:
                for raw in r:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if not line:
                        if "data" in buf:
                            ev = json.loads(buf["data"])
                            ev["_sse"] = buf.get("event", "message")
                            self.all.append(ev)
                            self.events.put(ev)
                        buf = {}
                    elif not line.startswith(":") and ":" in line:
                        k, _, v = line.partition(":")
                        buf[k] = v[1:] if v.startswith(" ") else v
            except (OSError, ValueError, AttributeError, http.client.HTTPException):   # karta zamknięta w trakcie czytania
                pass
        threading.Thread(target=run, daemon=True).start()

    def close(self):
        """Jak zamknięcie karty: połączenie SSE znika (strumień HTTP/1.0 trzyma gniazdo w odpowiedzi)."""
        if self.conn is None:
            return
        try:
            self.resp.fp.raw._sock.shutdown(2)
        except (OSError, AttributeError):
            pass
        self.resp.close()
        self.conn.close()

    def wait(self, kind, timeout=30, where=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ev = self.events.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            if ev.get("type") == kind and (where is None or where(ev)):
                return ev
        raise AssertionError(f"brak zdarzenia {kind}; były: {[e.get('type') for e in self.all][-40:]}")


class CodoUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.model_url = start_fake_model()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeModel.calls.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj = self.root / "projekt"
        self.proj.mkdir()
        (self.proj / "app.py").write_bytes(b"x = 1\n")   # bajty: write_text na Windows zapisałby CRLF
        self.env = make_env(self.root, self.model_url)
        self.p = None

    def tearDown(self):
        if self.p is not None and self.p.poll() is None:
            # jak użytkownik: „Zamknij” w oknie; silnik musi zniknąć przed sprzątaniem HOME
            try:
                Client(self.port, self.token).req("POST", "/api/quit", {})
                self.p.wait(20)
            except (OSError, subprocess.TimeoutExpired):
                self.p.kill()
                self.p.wait(5)
        if self.p is not None:
            for s in (self.p.stdout, self.p.stderr):
                try:
                    s.close()
                except (OSError, ValueError):
                    pass
        sprzataj(self.tmp)

    def _start(self, *extra, **env):
        self.env.update(env)
        self.p, self.url, self.port, self.token = start_ui(self.proj, self.env, *extra)
        return Client(self.port, self.token)

    def test_token_host_i_origin_sa_sprawdzane(self):
        c = self._start()
        self.assertEqual(c.req("GET", "/", token=False)[0], 403)
        self.assertEqual(c.req("GET", "/?t=zly-token", token=False)[0], 403)
        self.assertEqual(c.req("GET", "/api/events", token=False)[0], 403)
        self.assertEqual(c.req("GET", "/api/convos", token=False)[0], 403)
        # DNS rebinding: obca nazwa hosta z dobrym tokenem i tak jest odrzucona
        self.assertEqual(c.req("GET", "/", headers={"Host": "zly.example:%d" % self.port})[0], 403)
        self.assertEqual(c.req("POST", "/api/send", {"type": "status"}, token=False)[0], 403)
        self.assertEqual(c.req("POST", "/api/send", {"type": "status"}, headers={"Origin": "http://zly.example"})[0], 403)
        self.assertEqual(c.req("POST", "/api/send", {"type": "status"},
                               headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        # token w adresie nie wystarcza do POST (musi być nagłówek, którego obca strona nie ustawi bez CORS)
        self.assertEqual(c.req("POST", "/api/send?t=" + self.token, {"type": "status"}, token=False)[0], 403)
        # nieznane polecenia silnika nie przechodzą przez most
        self.assertEqual(c.send({"type": "nieznane_polecenie", "key": "dfk_x"})[0], 400)
        self.assertEqual(c.req("POST", "/api/quit", {}, headers={"Host": "localhost:%d" % self.port,
                                                                 "Origin": "http://evil.localhost"})[0], 403)

    def _git(self, *a):
        return subprocess.run(["git", "-C", str(self.proj), *a], capture_output=True, text=True, check=True, encoding="utf-8").stdout

    def test_zmiany_git_autocrlf_bez_falszywych_zmian(self):
        """Windows: core.autocrlf=true, w repo LF, na dysku CRLF. Okno pokazuje tylko naprawdę zmienioną linię,
        a fragment przyjęty do indeksu trafia tam z LF (jak przy git add)."""
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@t"); self._git("config", "user.name", "T")
        self._git("config", "core.autocrlf", "true")
        (self.proj / "w.txt").write_bytes(b"a\r\nb\r\nc\r\n")
        self._git("add", "-A"); self._git("commit", "-qm", "start")
        self.assertEqual(self._git("show", "HEAD:w.txt"), "a\nb\nc\n")
        (self.proj / "w.txt").write_bytes(b"a\r\nB\r\nc\r\n")
        c = self._start()
        f = json.loads(c.req("GET", "/api/changes/file?p=w.txt")[1])
        self.assertEqual((f["head"], f["work"], f["index"]), ("a\r\nb\r\nc\r\n", "a\r\nB\r\nc\r\n", "a\r\nb\r\nc\r\n"))
        st, body, _ = c.req("POST", "/api/changes/apply", {"p": "w.txt", "index": "a\r\nB\r\nc\r\n",
                                                           "expect_work": f["work_sig"]})
        self.assertEqual(st, 200, body)
        self.assertEqual(subprocess.run(["git", "-C", str(self.proj), "show", ":w.txt"], capture_output=True,
                                        check=True).stdout, b"a\nB\nc\n")
        self.assertEqual(self._git("diff", "--name-only"), "")   # plik roboczy = indeks, bez różnicy końców linii

    def test_zmiany_git_przyjmij_odrzuc_cofnij_commit(self):
        """Panel Zmiany: lista względem HEAD, fragment do indeksu, odrzucenie z kopią, cofnij, commit, gałąź."""
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@t"); self._git("config", "user.name", "T")
        self._git("config", "core.autocrlf", "false")   # Windows: Git for Windows ma domyślnie true
        (self.proj / "a.py").write_bytes(b"a\nb\nc\n")
        (self.proj / "stary.txt").write_bytes(b"stary\n")
        self._git("add", "-A"); self._git("commit", "-qm", "start")
        (self.proj / "a.py").write_bytes(b"a\nB\nc\nd\n")
        (self.proj / "nowy.txt").write_text("nowy\n", encoding="utf-8")
        (self.proj / "stary.txt").unlink()
        c = self._start()
        st, body, _ = c.req("GET", "/api/changes/list")
        self.assertEqual(st, 200)
        d = json.loads(body)
        files = {f["path"]: f for f in d["files"]}
        self.assertTrue(d["git"]); self.assertEqual(d["branch"], "main")
        self.assertEqual(files["a.py"]["status"], "modified")
        self.assertEqual((files["a.py"]["added"], files["a.py"]["removed"]), (2, 1))
        self.assertEqual(files["nowy.txt"]["status"], "new")
        self.assertEqual(files["stary.txt"]["status"], "deleted")
        st, body, _ = c.req("GET", "/api/changes/file?p=a.py")
        f = json.loads(body)
        self.assertEqual((f["head"], f["work"], f["index"]), ("a\nb\nc\n", "a\nB\nc\nd\n", "a\nb\nc\n"))
        # fragment przyjęty = nowa treść indeksu (okno ją liczy), plik roboczy bez zmian
        st, body, _ = c.req("POST", "/api/changes/apply", {"p": "a.py", "index": "a\nB\nc\n", "expect_work": f["work_sig"]})
        self.assertEqual(st, 200, body)
        self.assertEqual(self._git("show", ":a.py"), "a\nB\nc\n")
        # plik zmienił się w międzyczasie: zapis odmówiony
        self.assertEqual(c.req("POST", "/api/changes/apply", {"p": "a.py", "work": "x", "expect_work": "zly"})[0], 409)
        # odrzucenie fragmentu w pliku roboczym robi kopię w .doma/backups
        st, _, _ = c.req("POST", "/api/changes/apply", {"p": "a.py", "work": "a\nB\nc\n", "expect_work": f["work_sig"]})
        self.assertEqual(st, 200)
        self.assertEqual((self.proj / "a.py").read_text(encoding="utf-8"), "a\nB\nc\n")
        self.assertTrue(list((self.proj / ".doma" / "backups").glob("a.py.*.bak")))
        # cały plik: odrzuć nowy i usunięty, potem cofnij jednym krokiem
        st, _, _ = c.req("POST", "/api/changes/action", {"action": "reject", "paths": ["nowy.txt", "stary.txt"]})
        self.assertEqual(st, 200)
        self.assertFalse((self.proj / "nowy.txt").exists())
        self.assertEqual((self.proj / "stary.txt").read_text(encoding="utf-8"), "stary\n")
        st, body, _ = c.req("POST", "/api/changes/undo", {})
        self.assertTrue(json.loads(body)["ok"])
        self.assertTrue((self.proj / "nowy.txt").exists())
        self.assertFalse((self.proj / "stary.txt").exists())
        # cofnij odrzucenie fragmentu i przyjęcie fragmentu: wszystko jak na początku
        c.req("POST", "/api/changes/undo", {}); c.req("POST", "/api/changes/undo", {})
        self.assertEqual((self.proj / "a.py").read_text(encoding="utf-8"), "a\nB\nc\nd\n")
        self.assertEqual(self._git("show", ":a.py"), "a\nb\nc\n")
        # przyjmij cały plik = git add, cofnij przyjęcie = reset
        c.req("POST", "/api/changes/action", {"action": "accept", "paths": ["a.py"]})
        self.assertEqual(self._git("diff", "--cached", "--name-only").split(), ["a.py"])
        st, body, _ = c.req("GET", "/api/changes/list")
        self.assertEqual({f["path"]: f["staged"] for f in json.loads(body)["files"]}["a.py"], "full")
        # ścieżki poza projektem i w .git są odrzucane
        self.assertEqual(c.req("GET", "/api/changes/file?p=../poza.txt")[0], 400)
        self.assertEqual(c.req("POST", "/api/changes/apply", {"p": ".git/config", "work": "x"})[0], 400)
        self.assertEqual(c.req("GET", "/api/changes/list", token=False)[0], 403)
        self.assertEqual(c.req("POST", "/api/changes/undo", {}, token=False)[0], 403)
        # gałąź i commit tylko przyjętych plików
        self.assertEqual(c.req("POST", "/api/changes/branch", {"action": "create", "name": "-zla"})[0], 400)
        self.assertEqual(c.req("POST", "/api/changes/branch", {"action": "create", "name": "codo/zmiany"})[0], 200)
        st, body, _ = c.req("POST", "/api/changes/commit", {"message": "Zmiana a.py"})
        self.assertEqual(st, 200, body)
        self.assertEqual(self._git("rev-parse", "--abbrev-ref", "HEAD").strip(), "codo/zmiany")
        self.assertEqual(self._git("show", "--name-only", "--format=%s", "HEAD").split(), ["Zmiana", "a.py", "a.py"])
        self.assertIn("nowy.txt", self._git("status", "--porcelain"))

    def test_zmiany_dokumentu_word_tekst_i_caly_plik(self):
        """office_edit przez atrapę modelu: zdarzenie edit z diffem tekstu i formatem, panel Zmiany z tekstem
        dokumentu (HEAD albo kopia z .doma/backups), fragmentów nie ma, odrzucenie i cofnięcie całego pliku,
        podgląd pliku z nagłówkami i tabelą."""
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "t@t"); self._git("config", "user.name", "T")
        self._git("config", "core.autocrlf", "false")
        before = make_docx(["Najemca płaci 2000 zł.", "Kaucja wynosi 2000 zł."])
        (self.proj / "umowa.docx").write_bytes(before)
        self._git("add", "-A"); self._git("commit", "-qm", "start")
        # dokument spoza repozytorium: „przed” to kopia sprzed zmiany w .doma/backups
        (self.proj / ".doma" / "backups").mkdir(parents=True)
        (self.proj / ".doma" / "backups" / "aneks.docx.20261127-100000.bak").write_bytes(make_docx(["Aneks numer 1."]))
        (self.proj / "aneks.docx").write_bytes(make_docx(["Aneks numer 2."]))
        c = self._start()
        c.listen()
        c.wait("ready")
        c.send({"type": "send", "text": "popraw umowę: kaucja 3000"})
        edit = c.wait("edit", timeout=40)
        self.assertEqual((edit["plik"], edit["format"], edit["dodane"], edit["usuniete"]), ("umowa.docx", "DOCX", 1, 1))
        self.assertIn("-Kaucja wynosi 2000 zł.", edit["diff"])
        self.assertIn("+Kaucja wynosi 3000 zł.", edit["diff"])
        self.assertTrue(c.wait("turn_end", timeout=40)["ok"])
        edited = (self.proj / "umowa.docx").read_bytes()
        files = {f["path"]: f for f in json.loads(c.req("GET", "/api/changes/list")[1])["files"]}
        self.assertEqual({k: files["umowa.docx"][k] for k in ("binary", "office", "added", "removed", "status")},
                         {"binary": False, "office": "DOCX", "added": 1, "removed": 1, "status": "modified"})
        self.assertEqual((files["aneks.docx"]["office"], files["aneks.docx"]["binary"]), ("DOCX", False))
        f = json.loads(c.req("GET", "/api/changes/file?p=umowa.docx")[1])
        self.assertEqual((f["office"], f["whole_file"], f["base_from"], f.get("binary")), ("DOCX", True, "head", None))
        self.assertIn("# Umowa najmu\n", f["head"])
        self.assertIn("Kaucja wynosi 2000 zł.", f["head"]); self.assertIn("Kaucja wynosi 3000 zł.", f["work"])
        self.assertIn("Czynsz | 2000 |", f["work"])
        self.assertEqual(f["index"], f["head"])
        g = json.loads(c.req("GET", "/api/changes/file?p=aneks.docx")[1])
        self.assertEqual((g["base_from"], g["head"].strip().splitlines()[1], g["work"].strip().splitlines()[1]),
                         ("backup", "Aneks numer 1.", "Aneks numer 2."))
        # fragment tekstu nie wraca do zipa: tylko cały plik
        st, body, _ = c.req("POST", "/api/changes/apply", {"p": "umowa.docx", "work": f["head"], "expect_work": f["work_sig"]})
        self.assertEqual((st, json.loads(body)["error"]), (400, "whole_file"))
        self.assertEqual((self.proj / "umowa.docx").read_bytes(), edited)
        # podgląd pliku: tekst dokumentu i HTML z nagłówkiem i tabelą
        p = json.loads(c.req("GET", "/api/file/preview?p=umowa.docx")[1])
        self.assertEqual((p["kind"], p["format"]), ("office", "DOCX"))
        self.assertIn("<h1>Umowa najmu</h1>", p["html"])
        self.assertIn("<td>Czynsz</td>", p["html"])
        self.assertIn("Kaucja wynosi 3000 zł.", p["text"])
        # odrzuć cały plik: wraca HEAD (i kopia z backups dla dokumentu spoza repo), cofnij jednym krokiem
        self.assertEqual(c.req("POST", "/api/changes/action", {"action": "reject", "paths": ["umowa.docx", "aneks.docx"]})[0], 200)
        self.assertEqual((self.proj / "umowa.docx").read_bytes(), before)
        self.assertIn("Aneks numer 1.", json.loads(c.req("GET", "/api/file/preview?p=aneks.docx")[1])["text"])
        self.assertNotIn("umowa.docx", {x["path"] for x in json.loads(c.req("GET", "/api/changes/list")[1])["files"]})
        self.assertTrue(json.loads(c.req("POST", "/api/changes/undo", {})[1])["ok"])
        self.assertEqual((self.proj / "umowa.docx").read_bytes(), edited)
        self.assertIn("Aneks numer 2.", json.loads(c.req("GET", "/api/file/preview?p=aneks.docx")[1])["text"])
        # przyjmij cały plik = git add (indeks to teraz wersja po zmianie)
        c.req("POST", "/api/changes/action", {"action": "accept", "paths": ["umowa.docx"]})
        f = json.loads(c.req("GET", "/api/changes/file?p=umowa.docx")[1])
        self.assertEqual(f["index"], f["work"])

    def test_pr_testy_napraw_i_scal_przez_gh(self):
        """Pilnowanie PR jak PRWatch na Macu: stan testów z gh pr view, logi nieudanych (gh run view --log-failed)
        dla „Napraw teraz”, scalenie auto (repo nie pozwala: Codo scali samo) i od razu. gh to atrapa w PATH."""
        bin_dir = self.root / "bin"
        log = self.root / "gh.log"
        view = json.dumps({"number": 7, "url": "https://github.com/a/b/pull/7", "state": "OPEN",
                           "mergeable": "MERGEABLE", "reviewDecision": "", "headRefOid": "abc", "statusCheckRollup": [
                               {"name": "test", "status": "COMPLETED", "conclusion": "FAILURE",
                                "detailsUrl": "https://github.com/a/b/actions/runs/55/job/1"},
                               {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS", "detailsUrl": ""},
                               {"name": "build", "status": "IN_PROGRESS", "conclusion": ""},
                               {"context": "ci/stary", "state": "SKIPPED"}]})
        atrapa(bin_dir, "gh", exe=True, code="import sys\n"
               "a = sys.argv[1:]\n"
               f"with open({str(log)!r}, 'a', encoding='utf-8') as f:\n"
               "    f.write(' '.join(a) + '\\n')\n"
               "k = ' '.join(a[:2])\n"
               "if k == 'auth status':\n    sys.exit(0)\n"
               f"if k == 'pr view':\n    print({view!r})\n    sys.exit(0)\n"
               "if k == 'run view':\n    print('FAIL test_suma: 99 != 100')\n    sys.exit(0)\n"
               "if k == 'pr merge':\n"
               "    if '--auto' in a:\n"
               "        print('Auto merge is not allowed for this repository', file=sys.stderr)\n"
               "        sys.exit(1)\n"
               "    print('Merged #7')\n    sys.exit(0)\n"
               "sys.exit(1)\n")
        c = self._start(PATH=f"{bin_dir}{os.pathsep}{self.env.get('PATH') or os.environ.get('PATH', '')}")
        c.listen()
        self.assertEqual(c.send({"type": "pr", "action": "watch"})[0], 200)
        w = c.wait("pr", where=lambda e: e.get("action") == "watch")["watch"]
        self.assertEqual((w["number"], w["state"], w["mergeable"], w["head"]), (7, "OPEN", "MERGEABLE", "abc"))
        self.assertEqual([(x["name"], x["state"]) for x in w["checks"]],
                         [("test", "failed"), ("lint", "passed"), ("build", "running"), ("ci/stary", "skipped")])
        c.send({"type": "pr", "action": "logs", "checks": [w["checks"][0]]})
        logs = c.wait("pr", where=lambda e: e.get("action") == "logs")["logs"]
        self.assertEqual(logs[0]["name"], "test")
        self.assertIn("99 != 100", logs[0]["log"])
        c.send({"type": "pr", "action": "merge", "number": 7, "auto": True})
        m = c.wait("pr", where=lambda e: e.get("action") == "merge")
        self.assertFalse(m["merge"]["ok"]); self.assertTrue(m["merge"]["auto_off"])
        c.send({"type": "pr", "action": "merge", "number": 7, "auto": False})
        m = c.wait("pr", where=lambda e: e.get("action") == "merge")
        self.assertTrue(m["merge"]["ok"]); self.assertEqual(m["watch"]["number"], 7)
        c.send({"type": "pr", "action": "merge", "number": 0})
        self.assertTrue(c.wait("pr", where=lambda e: e.get("action") == "merge").get("error"))
        calls = log.read_text(encoding="utf-8")
        self.assertIn("run view 55 --log-failed", calls)
        self.assertIn("pr merge 7 --auto --squash --delete-branch", calls)
        self.assertIn("pr merge 7 --squash --delete-branch", calls)

    def test_zmiany_bez_gita_z_kopii(self):
        """Bez gita: „przed” = kopia w .doma/backups, przyjęcie zapisuje wersję odniesienia, nowy plik z silnika."""
        (self.proj / ".doma" / "backups").mkdir(parents=True)
        (self.proj / ".doma" / "backups" / "app.py.20261127-100000.bak").write_bytes(b"x = 0\n")
        (self.proj / "nowy.md").write_text("# Nowy\n", encoding="utf-8")
        c = self._start()
        st, body, _ = c.req("GET", "/api/changes/list?extra=nowy.md")
        d = json.loads(body)
        self.assertFalse(d["git"])
        self.assertEqual({f["path"]: f["status"] for f in d["files"]}, {"app.py": "modified", "nowy.md": "new"})
        f = json.loads(c.req("GET", "/api/changes/file?p=app.py")[1])
        self.assertEqual((f["head"], f["work"]), ("x = 0\n", "x = 1\n"))
        c.req("POST", "/api/changes/action", {"action": "accept", "paths": ["app.py"]})
        c.req("POST", "/api/changes/action", {"action": "reject", "paths": ["nowy.md"]})
        self.assertFalse((self.proj / "nowy.md").exists())
        d = json.loads(c.req("GET", "/api/changes/list?extra=nowy.md")[1])
        self.assertEqual(d["files"], [])
        c.req("POST", "/api/changes/undo", {})
        self.assertTrue((self.proj / "nowy.md").exists())
        items = json.loads(c.req("GET", "/api/changes/backups?p=app.py")[1])["items"]
        self.assertEqual(items[0]["name"], "app.py.20261127-100000.bak")
        self.assertEqual(c.req("POST", "/api/changes/restore", {"p": "app.py", "name": items[0]["name"]})[0], 200)
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "x = 0\n")

    def test_hive_odczyt_i_zapis_jak_na_macu(self):
        c = self._start()
        code, body, _h = c.req("GET", "/api/hive")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual((d["bots"], d["swarms"]), ([], []))
        bots = [{"id": "A1", "name": "Max", "alwaysOn": True, "kind": "asystent", "shape": "kostka"}]
        self.assertEqual(c.req("POST", "/api/hive", {"bots": bots})[0], 200)
        d = json.loads(c.req("GET", "/api/hive")[1])
        self.assertEqual(d["bots"][0]["name"], "Max")
        # śmieci nie nadpisują pliku
        self.assertEqual(c.req("POST", "/api/hive", {"bots": [{"name": "bez id"}]})[0], 400)
        self.assertEqual(c.req("POST", "/api/hive", {"bots": "x"})[0], 400)
        self.assertEqual(json.loads(c.req("GET", "/api/hive")[1])["bots"][0]["id"], "A1")
        # bez tokenu nic
        self.assertEqual(c.req("GET", "/api/hive", token=False)[0], 403)
        self.assertEqual(c.req("POST", "/api/hive", {"bots": []}, token=False)[0], 403)

    def test_grupy_zapis_odczyt_i_usuwanie_z_okna(self):
        # ekran grup okna: grupa idzie przez silnik do grupy.json (ten sam plik co `codo grupa` i Mac), bez biegu
        c = self._start()
        c.listen()
        c.wait("ready")
        g = {"name": "Przegląd", "strategy": "review", "recipe": "kod", "lead": "Max",
             "members": [{"name": "Max", "agent": "A1-B2"}, {"name": "Josh", "brain": "lopus", "role": "szuka błędów"}],
             "limits": {"rounds": 3, "member_minutes": 15, "per_provider": 2, "budget_kr": 0}}
        self.assertEqual(c.send({"type": "group_save", "group": g})[0], 200)
        saved = c.wait("group_saved")["group"]
        self.assertEqual((saved["lead"], saved["recipe"], saved["limits"]["per_provider"]), ("max", "kod", 2))
        self.assertEqual(saved["members"][0]["agent"], "A1-B2")
        lst = c.wait("group_list")
        self.assertEqual([x["name"] for x in lst["groups"]], ["Przegląd"])
        self.assertIn("review", [s["id"] for s in lst["strategies"]])
        data = json.loads((self.root / "home" / ".config" / "doma" / "grupy.json").read_text(encoding="utf-8"))
        self.assertEqual((data["grupy"][0]["id"], data["grupy"][0]["members"][1]["role"]), (saved["id"], "szuka błędów"))
        # ta sama nazwa drugi raz: błąd zamiast duplikatu
        c.send({"type": "group_save", "group": {"name": "przegląd", "members": [{"name": "A"}]}})
        self.assertIn("już jest", c.wait("group_error")["tekst"])
        c.send({"type": "group_delete", "id": saved["id"]})
        self.assertEqual(c.wait("group_list", where=lambda e: not e["groups"])["groups"], [])

    def test_tlumaczenia_okna(self):
        c = self._start()
        code, body, _h = c.req("GET", "/api/i18n?lang=de")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual(d["lang"], "de")
        self.assertEqual(d["strings"].get("Agents"), "Agenten")
        # napisy z tablic w modułach (nie tylko L("…")) też muszą trafić do osadzonych tłumaczeń
        code, body, _h = c.req("GET", "/api/i18n?lang=pl")
        pl = json.loads(body)["strings"]
        self.assertEqual(pl.get("Describe the presentation: the topic, who it is for, how long"),
                         "Opisz prezentację: temat, dla kogo, jak długa")

    def test_strona_sie_laduje(self):
        c = self._start()
        code, body, hdrs = c.req("GET", "/")
        self.assertEqual(code, 200)
        html = body.decode("utf-8")
        self.assertIn("<title>Codo</title>", html)
        self.assertNotIn("__CODO_BOOT__", html)
        self.assertNotIn("__NONCE__", html)
        self.assertIn('"lang": "pl"', html)
        csp = hdrs.get("Content-Security-Policy", "")
        nonce = re.search(r"'nonce-([\w-]+)'", csp).group(1)
        self.assertIn(f'<script nonce="{nonce}">', html)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(hdrs.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(hdrs.get("Cache-Control"), "no-store")
        # bez myślników w tekstach strony i bez emoji
        self.assertNotIn("—", html)
        self.assertNotIn("–", html)
        self.assertIsNone(re.search("[\U0001F300-\U0001FAFF☀-⛿]", html))
        self.assertEqual(c.req("GET", "/localhost")[0], 404)
        # pliki w rozmowie: podgląd, linki w odpowiedziach, strefa upuszczania, @ z podpowiedziami
        for fn in ("function filePreview", "function pfLinkify", "function deliverDrop", "function fuzzyScore", "function withAttachments"):
            self.assertIn(fn, html)
        self.assertIn("img-src data: blob: 'self'", csp)

    def test_rozmowa_zgoda_i_sprzatanie(self):
        c = self._start()
        c.listen()
        ready = c.wait("ready")
        self.assertTrue(ready["logged_in"])
        self.assertEqual(ready["model"], "@atrapa/atrapa-1")
        self.assertEqual(Path(ready["cwd"]).resolve(), self.proj.resolve())

        self.assertEqual(c.send({"type": "send", "text": "Opisz projekt"})[0], 200)
        user = c.wait("ui_user")
        self.assertEqual(user["tekst"], "Opisz projekt")
        c.wait("turn_start")
        end = c.wait("turn_end")
        self.assertTrue(end["ok"])
        said = "".join(e.get("tekst", "") for e in c.all if e["type"] == "delta") or \
            "".join(e.get("tekst", "") for e in c.all if e["type"] == "assistant")
        self.assertIn("atrapy", said)
        self.assertTrue(FakeModel.calls, "atrapa modelu nie dostała żądania")

        # lista rozmów projektu po pierwszej turze
        code, body, _ = c.req("GET", "/api/convos")
        self.assertEqual(code, 200)
        items = json.loads(body)["items"]
        self.assertEqual(items[0]["id"], end["convo_id"])

        # zgoda: komenda czeka na kartę, „Tak” ją uruchamia, edycja pliku przychodzi z diffem
        c.send({"type": "send", "text": "zapisz notatkę i sprawdź"})
        ask = c.wait("ask")
        self.assertIn("echo gotowe", ask["szczegol"])
        self.assertEqual([o["value"] for o in ask["opcje"]], [1, 2, 0])
        self.assertEqual(c.send({"type": "answer", "id": ask["id"], "value": 1})[0], 200)
        c.wait("ui_answer", where=lambda e: e["id"] == ask["id"] and e["value"] == 1)
        end2 = c.wait("turn_end", timeout=40)
        self.assertTrue(end2["ok"])
        edit = next(e for e in c.all if e["type"] == "edit")
        self.assertEqual(edit["plik"], "notatka.md")
        self.assertIn("+# Notatka", edit["diff"])
        self.assertEqual((self.proj / "notatka.md").read_text(encoding="utf-8"), NOTE)
        tools = [e for e in c.all if e["type"] == "tool"]
        self.assertTrue(any("gotowe" in " ".join(e.get("wynik") or []) for e in tools), tools)
        tool_msgs = [m for m in FakeModel.calls[-1]["messages"] if m.get("role") == "tool"]
        self.assertTrue(any("gotowe" in str(m.get("content")) for m in tool_msgs))

        # nowa karta (przeładowanie): dostaje zaległe zdarzenia jako replay, od „ready”
        late = Client(self.port, self.token)
        late.listen()
        first = late.wait("ready", timeout=10)
        self.assertEqual(first["_sse"], "replay")
        late.wait("ui_user", timeout=10)
        late.close()

        # zamknięcie z okna: serwer i silnik znikają
        code, body, _ = c.req("GET", "/api/info")
        engine = json.loads(body)["engine_pid"]
        self.assertTrue(engine)
        self.assertTrue(pid_alive(engine))
        self.assertEqual(c.req("POST", "/api/quit", {})[0], 200)
        self.assertEqual(self.p.wait(20), 0)
        c.close()
        time.sleep(0.3)
        self.assertFalse(pid_alive(engine), "silnik app-server został po zamknięciu okna")
        self.assertNotIn("Traceback", self.p.stderr.read())

    def test_stop_przerywa_ture_a_zgoda_nie_zostaje(self):
        c = self._start()
        c.listen()
        c.wait("ready")
        c.send({"type": "send", "text": "zapisz notatkę"})
        c.wait("ask")
        self.assertEqual(c.send({"type": "interrupt"})[0], 200)
        end = c.wait("turn_end", timeout=30)
        self.assertIn("ok", end)
        c.req("POST", "/api/quit", {})
        self.p.wait(20)
        c.close()

    def test_porownaj_dwa_modele_tylko_do_odczytu(self):
        """Porównaj (jak na Macu): ta sama wiadomość do dwóch modeli naraz, każdy we własnym silniku tylko do
        odczytu; główny silnik milczy, zdarzenia wracają z numerem pomocnika, pomocnicy kończą się po turze."""
        c = self._start()
        c.listen()
        c.wait("ready")
        targets = [{"provider": "acct:atrapa", "kind": "account", "title": "Atrapa", "model": "@atrapa/atrapa-1",
                    "name": "atrapa-1"},
                   {"provider": "acct:atrapa", "kind": "account", "title": "Atrapa", "model": "@atrapa/atrapa-mini",
                    "name": "atrapa-mini"}]
        self.assertEqual(c.req("POST", "/api/compare", {"text": "", "targets": targets})[0], 400)
        code, body, _h = c.req("POST", "/api/compare", {"text": "zapisz notatkę i opisz projekt", "targets": targets})
        self.assertEqual(code, 200, body)
        cid = json.loads(body)["id"]
        start = c.wait("compare_start")
        self.assertEqual(start["id"], cid)
        self.assertEqual([t["model"] for t in start["targets"]], ["@atrapa/atrapa-1", "@atrapa/atrapa-mini"])
        ends = {}
        for _ in range(2):
            e = c.wait("compare", timeout=40, where=lambda e: e["event"]["type"] == "turn_end" and e["run"] not in ends)
            ends[e["run"]] = e["event"]
        self.assertEqual(sorted(ends), [0, 1])
        evs = [e for e in c.all if e["type"] == "compare"]
        for run in (0, 1):
            said = "".join(e["event"].get("tekst", "") for e in evs if e["run"] == run and e["event"]["type"] in ("delta", "assistant"))
            self.assertTrue(said.strip(), f"pomocnik {run} nic nie powiedział")
        self.assertEqual({b.get("model") for b in FakeModel.calls}, {"atrapa-1", "atrapa-mini"})
        self.assertFalse((self.proj / "notatka.md").exists(), "porównanie zapisało plik (miało być tylko do odczytu)")
        self.assertFalse([e for e in c.all if e["type"] in ("ui_user", "turn_start", "ask")], "główny silnik miał milczeć")
        deadline = time.time() + 15
        while time.time() < deadline and json.loads(c.req("GET", "/api/info")[1])["compare_pids"]:
            time.sleep(0.2)
        self.assertEqual(json.loads(c.req("GET", "/api/info")[1])["compare_pids"], [], "pomocnicy zostali po turze")
        # Stop w trakcie: każdy pomocnik dostaje koniec tury i znika
        c.req("POST", "/api/compare", {"text": "opisz projekt", "targets": targets[:1]})
        c.wait("compare_start", where=lambda e: e["id"] != cid)
        self.assertEqual(c.req("POST", "/api/compare", {"stop": True})[0], 200)
        c.wait("compare", timeout=20, where=lambda e: e["id"] != cid and e["event"]["type"] == "turn_end")
        c.req("POST", "/api/quit", {})
        self.assertEqual(self.p.wait(20), 0)
        c.close()
        self.assertNotIn("Traceback", self.p.stderr.read())

    def test_zamkniecie_karty_konczy_po_chwili(self):
        c = self._start(CODO_UI_GRACE="1")
        c.listen()
        c.wait("ready")
        engine = json.loads(c.req("GET", "/api/info")[1])["engine_pid"]
        c.close()
        self.assertEqual(self.p.wait(20), 0)
        time.sleep(0.3)
        self.assertFalse(pid_alive(engine))

    @unittest.skipIf(os.name == "nt", "Ctrl+C jako sygnał tylko na POSIX")
    def test_ctrl_c_sprzata(self):
        c = self._start()
        c.listen()
        c.wait("ready")
        engine = json.loads(c.req("GET", "/api/info")[1])["engine_pid"]
        self.p.send_signal(signal.SIGINT)
        self.assertEqual(self.p.wait(20), 0)
        c.close()
        time.sleep(0.3)
        self.assertFalse(pid_alive(engine))

    def test_restart_silnika(self):
        c = self._start()
        c.listen()
        c.wait("ready")
        old = json.loads(c.req("GET", "/api/info")[1])["engine_pid"]
        self.assertEqual(c.req("POST", "/api/restart", {})[0], 200)
        c.wait("ready", timeout=20)
        new = json.loads(c.req("GET", "/api/info")[1])["engine_pid"]
        self.assertNotEqual(old, new)
        time.sleep(0.3)
        self.assertFalse(pid_alive(old))
        self.assertFalse([e for e in c.all if e["type"] == "ui_engine_exit"])
        c.req("POST", "/api/quit", {})
        self.assertEqual(self.p.wait(20), 0)
        c.close()

    def test_bez_konta_strona_pokazuje_logowanie(self):
        cfg = Path(self.env["DOMA_CONFIG_DIR"])
        (cfg / "konta.json").unlink()
        (cfg / "settings.json").write_text(json.dumps({"lang": "pl", "agents_off": True}), encoding="utf-8")   # bez agentów z tego komputera
        c = self._start()
        c.listen()
        ready = c.wait("ready")
        self.assertFalse(ready["logged_in"])
        c.req("POST", "/api/quit", {})
        self.p.wait(20)
        c.close()

    def _login_env(self):
        cfg = Path(self.env["DOMA_CONFIG_DIR"])
        (cfg / "konta.json").unlink()
        (cfg / "settings.json").write_text(json.dumps({"lang": "pl", "agents_off": True}), encoding="utf-8")
        srv, url = start_fake_domaai()
        self.addCleanup(srv.shutdown)
        FakeDomaAI.calls.clear()
        return cfg, url

    def test_pierwszy_start_logowanie_kodem_z_maila(self):
        """Okno jak aplikacja na Maca: bez konta status mówi „niezalogowany”, kod z maila loguje i paruje
        komputer (device.json jak `codo login`), literówka w adresie daje podpowiedź, zły kod liczy próby."""
        cfg, url = self._login_env()
        c = self._start(DOMA_API_URL=url)
        c.listen()
        c.wait("ready")
        c.send({"type": "status"})
        st = c.wait("status")
        self.assertFalse(st["domaai"] or st["signed_in"])
        c.send({"type": "account", "action": "send_code", "email": "marta@cloud.com"})
        e = c.wait("account")
        self.assertEqual((e["state"], e["code"], e["suggestion"]), ("failed", "typo", "marta@icloud.com"))
        c.send({"type": "account", "action": "send_code", "email": "marta@example.com"})
        e = c.wait("account")
        self.assertEqual((e["state"], e["cooldown"]), ("sent", 60))
        c.send({"type": "account", "action": "check_code", "email": "marta@example.com", "code": "111111"})
        e = c.wait("account")
        self.assertEqual((e["state"], e["code"], e["attempts_left"]), ("failed", "bad_code", 4))
        c.send({"type": "account", "action": "check_code", "email": "marta@example.com", "code": "123456"})
        e = c.wait("account", where=lambda x: x["state"] == "done")
        self.assertEqual((e["email"], e["plan"], e["device"]), ("marta@example.com", "base", "Komputer testowy"))
        st = c.wait("status", where=lambda x: x.get("domaai"))
        self.assertTrue(st["signed_in"])
        self.assertEqual(json.loads((cfg / "device.json").read_text(encoding="utf-8"))["device_id"], "dev1")
        self.assertEqual(json.loads((cfg / "account.json").read_text(encoding="utf-8"))["email"], "marta@example.com")
        c.req("POST", "/api/quit", {})
        self.p.wait(20)
        c.close()

    def test_nowe_konto_i_dwa_kroki(self):
        cfg, url = self._login_env()
        c = self._start(DOMA_API_URL=url)
        c.listen()
        c.wait("ready")
        c.send({"type": "account", "action": "send_code", "email": "nowa@example.com"})
        c.wait("account", where=lambda x: x["state"] == "sent")
        c.send({"type": "account", "action": "check_code", "email": "nowa@example.com", "code": "222222"})
        c.wait("account", where=lambda x: x["state"] == "new_account")
        c.send({"type": "account", "action": "finish", "name": "Nowa", "accepted": False})
        self.assertEqual(c.wait("account")["code"], "consent")
        c.send({"type": "account", "action": "finish", "name": "Nowa", "accepted": True})
        c.wait("account", where=lambda x: x["state"] == "done")
        reg = [f for m, p, f in FakeDomaAI.calls if p == "/auth/kod/rejestracja"][0]
        self.assertEqual((reg["full_name"], reg["accepted_terms"], reg["zrodlo"]), ("Nowa", "true", "codo"))
        (cfg / "device.json").unlink()
        c.send({"type": "account", "action": "send_code", "email": "dwa@example.com"})
        c.wait("account", where=lambda x: x["state"] == "sent")
        c.send({"type": "account", "action": "check_code", "email": "dwa@example.com", "code": "333333"})
        c.wait("account", where=lambda x: x["state"] == "totp")
        c.send({"type": "account", "action": "check_code", "email": "dwa@example.com", "totp": "654321"})
        c.wait("account", where=lambda x: x["state"] == "done")
        c.req("POST", "/api/quit", {})
        self.p.wait(20)
        c.close()

    def test_licencja_jak_na_macu(self):
        cfg = Path(self.env["DOMA_CONFIG_DIR"])
        c = self._start()
        code, body, _h = c.req("GET", "/api/license")
        lic = json.loads(body)
        self.assertEqual((code, lic["use"], lic["needs_acceptance"]), (200, "", True))
        self.assertEqual(c.req("POST", "/api/license", {"use": "zly"})[0], 400)
        self.assertEqual(c.req("POST", "/api/license", {"use": "company"}, token=False)[0], 403)
        code, body, _h = c.req("POST", "/api/license", {"use": "company"})
        lic = json.loads(body)
        self.assertEqual((code, lic["use"], lic["needs_acceptance"]), (200, "company", False))
        self.assertTrue(lic["company_since"] and lic["accepted_at"])
        self.assertEqual(json.loads((cfg / "license.json").read_text(encoding="utf-8"))["accepted"], 2)
        # strona ma ekran logowania i pytanie o licencję (moduł 45-account)
        html = c.req("GET", "/")[1].decode("utf-8")
        for k in ("acctHoldsCreator", "/api/license", "Sign in to Codo", "How will you use Codo?"):
            self.assertIn(k, html)

    def test_pliki_w_rozmowie_podglad_tylko_w_projekcie(self):
        """Podgląd, miniatury, pobieranie i karty plików: tylko projekt, załączniki okna i ścieżki wklejone przez
        użytkownika; ścieżki ze spacjami i polskimi znakami; link symboliczny nie wyprowadza poza projekt."""
        sub = self.proj / "Dokumenty klienta"
        sub.mkdir()
        (sub / "zamówienie łódź.csv").write_text("nazwa,ilość\njabłka,3\n", encoding="utf-8")
        (self.proj / "obraz.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', encoding="utf-8")
        (self.proj / "faktura.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        (self.proj / "dane.bin").write_bytes(b"\x00\x01\x02" * 50)
        secret = self.root / "poza" / "tajne.txt"
        secret.parent.mkdir()
        secret.write_text("tajne", encoding="utf-8")
        try:
            os.symlink(secret, self.proj / "skrot.txt")
        except (OSError, NotImplementedError):
            pass
        c = self._start()
        q = urllib.parse.quote

        def get_json(path):
            code, body, hdrs = c.req("GET", path)
            return code, json.loads(body or b"{}"), hdrs
        code, j, _h = get_json("/api/file/preview?p=" + q("Dokumenty klienta/zamówienie łódź.csv"))
        self.assertEqual(code, 200)
        self.assertEqual((j["kind"], j["rel"], j["name"]), ("text", "Dokumenty klienta/zamówienie łódź.csv", "zamówienie łódź.csv"))
        self.assertIn("jabłka", j["text"])
        self.assertEqual(get_json("/api/file/preview?p=app.py")[1]["text"], "x = 1\n")
        self.assertEqual(get_json("/api/file/preview?p=dane.bin")[1]["kind"], "binary")
        code, j, _h = get_json("/api/file/preview?p=" + q("Dokumenty klienta"))
        self.assertEqual((code, j["kind"], j["entries"][0]["name"]), (200, "dir", "zamówienie łódź.csv"))
        # poza projektem: ani ścieżką, ani przez .., ani przez link symboliczny
        for bad in (str(secret), "../poza/tajne.txt", "skrot.txt", "~/.ssh/id_rsa"):
            self.assertEqual(get_json("/api/file/preview?p=" + q(bad))[0], 403, bad)
            self.assertEqual(c.req("GET", "/api/file/raw?p=" + q(bad))[0], 404, bad)
        self.assertEqual(c.req("GET", "/api/file/preview?p=app.py", token=False)[0], 403)
        self.assertEqual(c.req("GET", "/api/file/raw?p=app.py", token=False)[0], 403)
        # SVG z projektu nie uruchomi skryptu w adresie okna; PDF może być w ramce podglądu
        code, body, hdrs = c.req("GET", "/api/file/raw?p=obraz.svg")
        self.assertEqual((code, hdrs.get("Content-Type")), (200, "image/svg+xml"))
        self.assertIn("sandbox", hdrs.get("Content-Security-Policy", ""))
        code, body, hdrs = c.req("GET", "/api/file/raw?p=faktura.pdf")
        self.assertEqual((code, hdrs.get("Content-Type"), hdrs.get("X-Frame-Options")), (200, "application/pdf", "SAMEORIGIN"))
        code, body, hdrs = c.req("GET", "/api/file/raw?p=app.py&dl=1")
        self.assertEqual((code, body), (200, b"x = 1\n"))
        self.assertTrue(hdrs.get("Content-Disposition", "").startswith("attachment"))
        # karty: które ścieżki istnieją (linki w odpowiedziach)
        code, body, _h = c.req("POST", "/api/file/info", {"paths": ["app.py", "brak.py", str(secret), "Dokumenty klienta/zamówienie łódź.csv"]})
        items = json.loads(body)["items"]
        self.assertEqual(items["app.py"]["size"], 6)
        self.assertIsNone(items["brak.py"])
        self.assertIsNone(items[str(secret)])
        self.assertEqual(items["Dokumenty klienta/zamówienie łódź.csv"]["ext"], "csv")
        # „Otwórz w systemie” tylko w projekcie (bez uruchamiania aplikacji w teście: plik, którego nie ma)
        self.assertEqual(c.req("POST", "/api/file/open", {"p": str(secret)})[0], 403)
        self.assertEqual(c.req("POST", "/api/file/open", {"p": "brak.txt"})[0], 404)
        self.assertEqual(c.req("POST", "/api/file/open", {"p": "app.py"}, token=False)[0], 403)
        # wklejona ścieżka (w cudzysłowie, jak „Kopiuj jako ścieżkę” w Eksploratorze): od teraz do podglądu
        code, body, _h = c.req("POST", "/api/file/attach", {"path": '"' + str(secret) + '"'})
        self.assertEqual((code, json.loads(body)["name"]), (200, "tajne.txt"))
        self.assertEqual(get_json("/api/file/preview?p=" + q(str(secret)))[1]["text"], "tajne")
        self.assertEqual(c.req("POST", "/api/file/attach", {"path": str(self.root / "nie ma")})[0], 404)

        def upload(name, data, extra=None):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            h = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/octet-stream", "X-Codo-Token": self.token,
                 "X-Codo-Name": q(name)}
            h.update(extra or {})
            conn.request("POST", "/api/upload", body=data, headers=h)
            r = conn.getresponse()
            out = (r.status, json.loads(r.read() or b"{}"))
            conn.close()
            return out
        code, j = upload("zrzut ekranu ąę.png", b"\x89PNG")
        self.assertEqual(code, 200)
        self.assertTrue(j["path"].endswith("zrzut ekranu ąę.png"), j)
        self.assertEqual(get_json("/api/file/preview?p=" + q(j["path"]))[1]["kind"], "image")
        # folder: pliki z podfolderami pod jednym znacznikiem upuszczenia, bez wyjścia przez ..
        code, j = upload("a.py", b"print(1)", {"X-Codo-Group": "grp12345", "X-Codo-Dir": q("Mój projekt/src/../../..")})
        self.assertEqual(code, 200)
        p = Path(j["path"])
        self.assertEqual((p.parent.name, p.parent.parent.name, p.parent.parent.parent.name), ("src", "Mój projekt", "grp12345"))
        code, body, _h = c.req("POST", "/api/file/info", {"paths": [str(p.parent.parent)]})
        self.assertTrue(json.loads(body)["items"][str(p.parent.parent)]["dir"])
        # za duży plik: czytelny błąd zamiast zerwanego połączenia
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/upload", skip_host=True)
        for k, v in {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/octet-stream", "X-Codo-Token": self.token,
                     "Content-Length": str(64 << 20)}.items():
            conn.putheader(k, v)
        conn.endheaders()
        r = conn.getresponse()
        self.assertEqual((r.status, json.loads(r.read())["error"]), (413, "too_big"))
        conn.close()

    def test_zly_folder_i_port(self):
        r = subprocess.run([sys.executable, SCRIPT, "ui", str(self.root / "brak"), "--no-browser"], env=self.env,
                           capture_output=True, text=True, encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Nie ma takiego folderu", r.stdout)
        r = subprocess.run([sys.executable, SCRIPT, "ui", "--port", "x"], env=self.env, cwd=self.proj,
                           capture_output=True, text=True, encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)


class CodoUiOsadzenieTests(unittest.TestCase):
    """Strona jedzie w pliku CLI; osadzona wersja ma się zgadzać ze źródłem static/cli/codo-ui.html."""

    def test_osadzona_strona_aktualna(self):
        src = Path(__file__).resolve().parents[1] / "static/cli/codo-ui.html"
        tool = Path(__file__).resolve().parents[1] / "scripts/osadz-codo-ui.py"
        if os.environ.get("CODO_FILE") or not src.exists() or not tool.exists():
            self.skipTest("poza repozytorium (np. publiczne wydanie z jednym plikiem)")
        r = subprocess.run([sys.executable, str(tool), "--check"], capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_slownik_pl_en_w_stronie(self):
        import base64
        import gzip
        text = Path(SCRIPT).read_text(encoding="utf-8")
        a = text.index("_CODO_UI_GZ = (")
        b = text.index(")\n", a)
        rows = re.findall(r'"([A-Za-z0-9+/=]+)"', text[a:b])
        html = gzip.decompress(base64.b64decode("".join(rows))).decode("utf-8")
        pl = re.search(r"\n  pl: \{(.*?)\n  \},\n  en: \{", html, re.S).group(1)
        en = re.search(r"\n  en: \{(.*?)\n  \}\n\};", html, re.S).group(1)
        keys = lambda block: set(re.findall(r"(\w+): \"", block))   # noqa: E731
        self.assertEqual(keys(pl), keys(en))
        self.assertGreater(len(keys(pl)), 50)


class TestLogoDostawcow(unittest.TestCase):
    """Rozpoznawanie dostawcy w oknie (static/cli/ui/07-sites.js) jak na Macu: id modelu, adres API albo gotowe
    konto → strona marki, i każda taka strona ma obrazek w 06-logos.js."""
    maxDiff = None
    UI = Path(__file__).resolve().parents[1] / "static/cli/ui"

    def setUp(self):
        if not (self.UI / "07-sites.js").exists():
            self.skipTest("poza repozytorium (np. publiczne wydanie z jednym plikiem)")

    MODELE = {
        "lopus": "domaai.pl", "lopus-pro": "domaai.pl",
        "anthropic/claude-opus-5-5": "claude.ai", "claude-sonnet-4-5": "claude.ai", "@anthropic/claude-haiku-4-5": "claude.ai",
        "openai/gpt-5.6-luna": "chatgpt.com", "gpt-5": "chatgpt.com", "o3": "chatgpt.com", "o4-mini": "chatgpt.com",
        "@openrouter/openai/gpt-5": "chatgpt.com", "google/gemini-3.5-flash": "gemini.google.com",
        "gemini-2.5-pro": "gemini.google.com", "gemma-3-27b-it": "gemini.google.com",
        "x-ai/grok-4.7": "grok.com", "grok-4": "grok.com", "@xai/grok-4": "grok.com",
        "mistral/codestral-latest": "mistral.ai", "codestral-latest": "mistral.ai", "magistral-medium": "mistral.ai",
        "devstral-small-2507": "mistral.ai", "mistral-large-latest": "mistral.ai", "open-mixtral-8x22b": "mistral.ai",
        "madd-llm/bielik-11b-v3": "bielik.ai", "bielik-11b-v3": "bielik.ai", "ark-eu/seed-2-0-lite-260428": "seed.bytedance.com",
        "deepseek-chat": "deepseek.com", "deepseek/deepseek-r1": "deepseek.com", "qwen3-coder": "qwen.ai",
        "@groq/llama-3.3-70b-versatile": "llama.com", "meta-llama/llama-4-maverick": "llama.com",
        "@openrouter/moonshotai/kimi-k2": "kimi.com", "kimi-k2-instruct": "kimi.com",
        "z-ai/glm-4.6": "z.ai", "glm-4.5-air": "z.ai",
        "agent:claude": "claude.ai", "agent:codex": "chatgpt.com", "agent:gemini": "gemini.google.com", "agent:grok": "grok.com",
        "agent:vibe": "mistral.ai", "agent:qwen": "qwen.ai", "agent:kimi": "kimi.com", "agent:copilot": "github.com",
        "agent:cursor": "cursor.com", "agent:auggie": "augmentcode.com",
        "@ollama/phi4": "ollama.com", "@lmstudio/local-model": "lmstudio.ai", "@groq/compound-beta": "groq.com",
    }
    ADRESY = {
        "https://api.openai.com/v1": "chatgpt.com", "https://api.anthropic.com/v1": "claude.ai", "https://api.x.ai/v1": "grok.com",
        "https://generativelanguage.googleapis.com/v1beta/openai": "gemini.google.com", "https://api.mistral.ai/v1": "mistral.ai",
        "https://api.deepseek.com/v1": "deepseek.com", "https://api.groq.com/openai/v1": "groq.com",
        "https://openrouter.ai/api/v1": "openrouter.ai", "http://127.0.0.1:11434/v1": "ollama.com",
        "http://localhost:1234/v1": "lmstudio.ai", "https://api.moonshot.ai/v1": "kimi.com", "https://api.z.ai/api/paas/v4": "z.ai",
        "https://open.bigmodel.cn/api/paas/v4": "z.ai", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1": "qwen.ai",
        "https://api.bymadd.pl": "domaai.pl", "openai": "chatgpt.com", "xai": "grok.com", "google": "gemini.google.com",
        "groq": "groq.com", "openrouter": "openrouter.ai", "ollama": "ollama.com", "lmstudio": "lmstudio.ai", "wlasny": "",
    }
    # Strony bez logo w paczce (Mac też ich nie ma): w oknie zostaje cichy kafelek z ikoną
    BEZ_LOGO = {"together.ai", "block.github.io/goose"}

    def _node(self, script):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        code = "\n".join((self.UI / f).read_text(encoding="utf-8") for f in ("06-logos.js", "07-sites.js")) + "\n" + script
        r = subprocess.run([node, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_model_i_adres_na_strone_z_logo(self):
        accts = [{"name": "groq", "url": "https://api.groq.com/openai/v1"}, {"name": "ollama", "url": "http://127.0.0.1:11434/v1"},
                 {"name": "lmstudio", "url": "http://127.0.0.1:1234/v1"}]
        out = self._node("var CX = {status: {accounts: %s}};\nconst M = %s, A = %s;\n"
                         "console.log(JSON.stringify({m: Object.fromEntries(Object.keys(M).map((k) => [k, codoSiteOf(k)])),"
                         " a: Object.fromEntries(Object.keys(A).map((k) => [k, codoSiteForAPI(k)])),"
                         " img: Object.fromEntries(Object.values(M).concat(Object.values(A), Object.values(SITE_AGENT),"
                         " SITE_FAMS.map((f) => f[3]), Object.values(SITE_PRESET)).map((s) => [s, !!codoLogoSrc(s)]))}));"
                         % (json.dumps(accts), json.dumps(self.MODELE), json.dumps(self.ADRESY)))
        self.assertEqual(out["m"], self.MODELE)
        self.assertEqual(out["a"], self.ADRESY)
        brak = sorted(s for s, ok in out["img"].items() if s and not ok and s not in self.BEZ_LOGO)
        self.assertEqual(brak, [], "strony bez logo w 06-logos.js")

    def test_jedno_rozpoznawanie_w_oknie(self):
        """Moduły nie trzymają własnych list rodzin ani aliasów: wszystko idzie przez 07-sites.js."""
        for f in sorted(self.UI.glob("*.js")):
            if f.name in ("06-logos.js", "07-sites.js"):
                continue
            t = f.read_text(encoding="utf-8")
            self.assertNotIn("LOGO_IMG[", t, f.name)
            self.assertNotRegex(t, r'\["anthropic/", "claude\.ai"\]', f.name)
class CodoUiTwarzeTests(unittest.TestCase):
    """Twarze agentów rysowane na żywo (05-orbs.js): kolory płynu, kolor oczu, miny i wzrok, bez gotowych obrazków."""

    UI = Path(__file__).resolve().parents[1] / "static/cli/ui"

    def setUp(self):
        if not (self.UI / "05-orbs.js").exists():
            self.skipTest("poza repozytorium (np. publiczne wydanie z jednym plikiem)")

    def test_bez_gotowych_obrazkow_i_z_oczami_agenta(self):
        orbs = (self.UI / "05-orbs.js").read_text(encoding="utf-8")
        self.assertNotIn("data:image/webp", orbs)
        self.assertIn("webgl2", orbs)
        self.assertIn("prefers-reduced-motion", orbs)
        self.assertIn("IntersectionObserver", orbs)
        shell = (self.UI / "00-shell.js").read_text(encoding="utf-8")
        self.assertIn("function orb(look, size, extraCls, opts)", shell)
        self.assertIn('eyes: b.eyes || ""', (self.UI / "20-agents.js").read_text(encoding="utf-8"))
        cr = (self.UI / "40-creator.js").read_text(encoding="utf-8")
        self.assertIn("eyes: d.eyes", cr)
        self.assertIn('key: "creator"', cr)

    def test_logika_twarzy_w_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        src = (self.UI / "05-orbs.js").read_text(encoding="utf-8")
        shell = (self.UI / "00-shell.js").read_text(encoding="utf-8")
        a = shell.index("const ORB_SHAPES")
        b = shell.index("/* look: {shape")
        prog = ("const performance={now:()=>0};const document={};const window={};\n" + shell[a:b] + "\n" + src + r"""
const out = {};
const viol = orbState({shape: "kostka", colors: ["#FF0000", "#00FF00"], eyes: "#151517"}, 30, {});
out.mix = viol.liquid.rgb.length; out.eyes = viol.eyes; out.shape = viol.shape;
const one = orbState({colors: ["#7C5CFF"]}, 30, {});
out.one = one.liquid.rgb.length;
out.glass = orbState({colors: ["#E9EEF3"]}, 30, {}).liquid.glass;
out.pal = orbState({palette: "amber"}, 30, {}).liquid.rgb.length;
out.def = orbState({shape: "kotek"}, 30, {}).liquid.rgb.length;
out.badEyes = orbState({eyes: "zielone"}, 30, {}).eyes;
out.mood = orbState({}, 30, {mood: "happy"}).mood;
out.blinkOpen = orbBlink(0.01, false)[0];
let shut = 0; for (let t = 0; t < 9; t += 0.01) shut = Math.max(shut, orbBlink(t, false)[0]);
out.blinks = shut;
out.gaze = orbGaze(5, {x: 0.6, y: -0.4}, false)[1];
out.still = orbGaze(null, {x: 1, y: 0}, false)[1];
out.seedSame = String(orbSeed(viol.pal)) === String(orbSeed(viol.pal.slice()));
out.blend = orbBlend([0,0,0,1], [1,1,1,1], 0.5);
console.log(JSON.stringify(out));
""")
        r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, timeout=30, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout)
        self.assertEqual((o["mix"], o["eyes"], o["shape"]), (2, "#151517", "kostka"))
        self.assertEqual(o["one"], 4)                       # jedna barwa: cztery odcienie jak na Macu
        self.assertTrue(o["glass"])
        self.assertEqual((o["pal"], o["def"]), (3, 3))
        self.assertEqual(o["badEyes"], "")
        self.assertEqual(o["mood"], "radosna")
        self.assertGreater(o["blinks"], 0.99)               # mruga
        self.assertLess(abs(o["gaze"]["x"] - 0.6), 0.1)      # patrzy tam, gdzie każe look
        self.assertEqual(o["still"], {"x": 1, "y": 0})
        self.assertTrue(o["seedSame"])
        self.assertEqual(o["blend"], [0.5, 0.5, 0.5, 1])


if __name__ == "__main__":
    unittest.main()


class TestRoznicePanelZmiany(unittest.TestCase):
    """16-diff.js: bloki różnic składają dokładnie obie wersje, przyjęte części rozpoznane, duży plik szybko."""

    def test_roznice_w_node(self):
        import shutil
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        src = Path(__file__).resolve().parents[1] / "static/cli/ui/16-diff.js"
        if not src.exists():
            self.skipTest("poza repozytorium (np. publiczne wydanie z jednym plikiem)")
        prog = src.read_text(encoding="utf-8") + r"""
let rnd = 7; const R = () => { rnd = (rnd * 1103515245 + 12345) % 2147483648; return rnd / 2147483648; };
let bad = 0, foreign = 0;
for (let t = 0; t < 1500; t++) {
  const a = []; for (let i = 0, n = Math.floor(R() * 40); i < n; i++) a.push("l" + Math.floor(R() * 8));
  const b = a.filter(() => R() > 0.2).map((x) => R() < 0.2 ? "x" + Math.floor(R() * 5) : x);
  const A = dfSplit(a.join("\n") + "\n"), B = dfSplit(b.join("\n") + "\n"), bl = dfBlocks(A, B);
  if (dfApply(A, B, bl, () => true) !== B.join("\n") || dfApply(A, B, bl, () => false) !== A.join("\n")) bad++;
  const half = dfApply(A, B, bl, (i) => i % 2 === 0), r = dfSameBlocks(A, B, bl, dfSplit(half));
  const ok = dfApply(A, B, bl, (i) => r.acc.has(i)) === half;
  if (!ok) foreign++;
}
const big = []; for (let i = 0; i < 30000; i++) big.push("x" + i);
const big2 = big.map((x, i) => i % 9 === 0 ? "y" + i : x).reverse();
const t0 = Date.now(), bb = dfBlocks(big, big2), ms = Date.now() - t0;
const hl = dfHighlight('def f():\n    return "x"  # c', "python");
console.log(JSON.stringify({ bad, foreign, ms, big: dfApply(big, big2, bb, () => true) === big2.join("\n"), hl }));
"""
        out = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, timeout=120, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(r["bad"], 0)
        self.assertLess(r["foreign"], 150)      # rzadkie niejednoznaczne: okno wtedy działa na całym pliku
        self.assertTrue(r["big"])
        self.assertLess(r["ms"], 3000)
        self.assertIn('<span class="hk">def</span>', r["hl"][0])
        self.assertIn('<span class="hc"># c</span>', r["hl"][1])


class TestPrzegladIPlikiWOknie(unittest.TestCase):
    """16-review.js: blok ```codo-review w odpowiedzi to karta przeglądu; 14-files.js: binarny plik w karcie zmian
    to rodzaj i rozmiar, nie „+1 −0”; 16-changes.js: podgląd HTML w ramce z piaskownicą; twarz logowania patrzy oczami."""

    UI = Path(__file__).resolve().parents[1] / "static/cli/ui"

    def setUp(self):
        if not (self.UI / "16-review.js").exists():
            self.skipTest("poza repozytorium")

    def test_karta_przegladu_w_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        src = (self.UI / "16-review.js").read_text(encoding="utf-8")
        prog = ("""
const L = (k) => k, Lf = (k, ...a) => { let i = 0; return k.replace(/%(d|@)/g, () => String(a[i++])); };
const Lp = (n, one, other) => Lf(n === 1 ? one : other, n);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]);
const localStorage = { getItem: () => null, setItem: () => {} };
const document = { addEventListener: () => {}, querySelectorAll: () => [], querySelector: () => null, body: { contains: () => false } };
const onEngine = () => {}, onShellReady = () => {}, send = () => {};
let S = { stream: null };
function codeBlock(lang, body) { return "<pre>" + lang + "</pre>"; }
""" + src + r"""
const out = {};
out.card = codeBlock("codo-review", JSON.stringify([{plik: "app.py", linia: 3, waga: "wazne", tytul: "Dzielenie przez zero", opis: "n może być 0", poprawka: "sprawdź n"},
  {file: "b.js", line: 0, severity: "minor", title: "Nazwa", detail: "x"}]));
out.empty = codeBlock("codo-review", "[]");
out.other = codeBlock("python", "x");
out.bad = codeBlock("codo-review", "[{");
S = { stream: { body: { classList: { contains: () => true } } } };
out.wait = codeBlock("codo-review", "[{");
out.parsed = rvParse(JSON.stringify([{plik: "a", linia: 2, waga: "wazne", tytul: "t", opis: "o", poprawka: "p"}]))[0];
out.task = rvTask(out.parsed);
console.log(JSON.stringify(out));
""")
        r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout)
        self.assertIn("Review: 2 findings", o["card"])
        self.assertIn("Apply all fixes", o["card"])
        self.assertIn("app.py:3", o["card"])
        self.assertIn('rv-w imp">important', o["card"])
        self.assertIn('rv-w">minor', o["card"])
        self.assertEqual(o["card"].count('data-rv="one"'), 2)
        self.assertIn("Review: nothing to fix", o["empty"])
        self.assertNotIn("Apply all fixes", o["empty"])
        self.assertEqual((o["other"], o["bad"]), ("<pre>python</pre>", "<pre>codo-review</pre>"))
        self.assertIn("rv-wait", o["wait"])
        self.assertTrue(o["parsed"]["important"])
        self.assertEqual(o["task"], "a:2: t. o Fix: p")

    def test_plik_binarny_w_karcie_zmian(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        src = (self.UI / "14-files.js").read_text(encoding="utf-8")
        a = src.index("const FK_GROUPS")
        b = src.index("/* Serwer */")
        c = src.index("const PF_BIN_EXT")
        d = src.index("if (typeof editCard")
        prog = src[a:b] + src[c:d] + r"""
console.log(JSON.stringify([pfIsBinaryEdit({plik: "faktury/faktura.pdf", diff: "+%PDF-1.7"}), pfIsBinaryEdit({plik: "a.py", diff: "+x"}),
  pfIsBinaryEdit({plik: "dane.dat", diff: "+��"}), FK.of("faktura.pdf").label, pfIsBinaryEdit({plik: "logo.svg", diff: "+<svg>"}),
  pfIsBinaryEdit({plik: "umowa.docx", format: "DOCX", diff: "-Kaucja 2000\n+Kaucja 3000"}), pfIsBinaryEdit({plik: "umowa.docx", diff: ""})]));
"""
        r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        # office_edit: diff tekstu dokumentu i format → zwykła karta z diffem; plik Worda bez diffu → rodzaj i rozmiar
        self.assertEqual(json.loads(r.stdout), [True, False, True, "PDF", False, False, True])
        self.assertIn('meta.textContent = parts().concat(fmtSize(i.size)).join(" · ")', src)

    def test_liczba_mnoga_w_oknie(self):
        """Lp (00-shell.js): Intl.PluralRules języka okna i formy „klucz#kategoria” z i18n-extra; bez nich tekst z Maca."""
        node = shutil.which("node")
        if not node:
            self.skipTest("brak node")
        src = (self.UI / "00-shell.js").read_text(encoding="utf-8")
        part = src[src.index("const I18N = "):src.index("const UI_LANGS")]
        tr = {}
        for lang in ("pl", "ro", "fr", "de", "ja"):
            d = json.loads((self.UI / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
            d.update(json.loads((self.UI / "i18n-extra" / f"{lang}.json").read_text(encoding="utf-8")))
            tr[lang] = d
        prog = part + "const TR = " + json.dumps(tr, ensure_ascii=False) + r""";
const out = {};
const run = (lang, ns) => { I18N.lang = lang; I18N.s = TR[lang] || {}; out[lang] = ns.map((n) => Lp(n, "%d check failed", "%d checks failed")); };
run("en", [1, 2]); run("pl", [1, 2, 4, 5, 12, 22, 25]); run("ro", [1, 2, 20]); run("fr", [0, 1, 2]); run("de", [1, 3]); run("ja", [1, 3]);
I18N.lang = "pl"; I18N.s = TR.pl;
out.files = [1, 3, 5].map((n) => Lp(n, "1 file", "%d files"));
out.left = Lp(2, "%@: %d file was left out (too large or too many)", "%@: %d files were left out (too large or too many)", "Pliki", 2);
I18N.lang = "en"; I18N.s = {};
out.enFiles = [1, 2].map((n) => Lp(n, "1 file", "%d files"));
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        o = json.loads(r.stdout)
        self.assertEqual(o["en"], ["1 check failed", "2 checks failed"])
        self.assertEqual(o["pl"], ["1 test nie przeszedł", "2 testy nie przeszły", "4 testy nie przeszły", "5 testów nie przeszło",
                                   "12 testów nie przeszło", "22 testy nie przeszły", "25 testów nie przeszło"])
        self.assertEqual(o["ro"], ["1 verificare eșuată", "2 verificări eșuate", "20 de verificări eșuate"])
        self.assertEqual(o["fr"], ["0 vérification échouée", "1 vérification échouée", "2 vérifications échouées"])
        self.assertEqual(o["de"], ["1 Prüfung fehlgeschlagen", "3 Prüfungen fehlgeschlagen"])
        self.assertEqual(o["ja"], ["失敗したチェック: 1", "失敗したチェック: 3"])
        self.assertEqual(o["files"], ["1 plik", "3 pliki", "5 plików"])
        self.assertEqual(o["left"], "Pliki: pominięto 2 pliki (za duże albo za dużo)")
        self.assertEqual(o["enFiles"], ["1 file", "2 files"])
        # w oknie nie ma już „%d checks failed” bez liczby mnogiej
        for f in self.UI.glob("*.js"):
            self.assertNotIn('Lf("%d checks failed"', f.read_text(encoding="utf-8"), f.name)

    def test_podglad_html_i_wzrok_twarzy(self):
        chg = (self.UI / "16-changes.js").read_text(encoding="utf-8")
        self.assertIn("md|markdown|html?", chg)
        self.assertIn('<iframe sandbox="" referrerpolicy="no-referrer"', chg)
        acc = (self.UI / "45-account.js").read_text(encoding="utf-8")
        self.assertIn("orbUpdate(w, { look: accLook() })", acc)
        self.assertNotIn("lookX", acc)
        self.assertNotIn("translate(", acc)
