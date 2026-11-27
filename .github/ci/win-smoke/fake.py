"""Helpers for the Windows smoke scripts: a local fake OpenAI-compatible model (127.0.0.1, no real provider),
a clean Codo config with that one API account, and `codo ui` started the way a program starts it (stdin = NUL)."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = os.environ.get("CODO_FILE") or str(Path(__file__).resolve().parents[3] / "codo")

ANSWER = ("## Struktura projektu\n\nTo odpowiedź **atrapy** modelu. Najważniejsze pliki:\n\n"
          "- `app.py` uruchamia aplikację\n- `tests/` zawiera testy\n\n"
          "```python\ndef main():\n    print(\"hej\")\n```\n\n| Plik | Rola |\n| --- | --- |\n| app.py | start |\n")
NOTE = "# Notatka\n\nPlan na dziś:\n\n1. Testy\n2. Wydanie\n"
DONE = "Zapisałem **notatka.md** i uruchomiłem sprawdzenie. Komenda zwróciła `gotowe`."


class FakeModel(BaseHTTPRequestHandler):
    """Plain answer with markdown; on "zapisz" two tool calls (write a file, run a command)."""

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
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        user = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
        user_text = json.dumps(user.get("content"), ensure_ascii=False).lower()
        calls, text = [], ANSWER
        if last.get("role") == "tool":
            text = DONE
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
        out = [{"choices": [{"delta": {"content": text[i:i + 12]}}]} for i in range(0, len(text), 12)]
        for i, c in enumerate(calls):
            out.append({"choices": [{"delta": {"tool_calls": [{"index": i, "id": c["id"], "type": "function",
                                                               "function": c["function"]}]}}]})
        out.append({"choices": [{"delta": {}, "finish_reason": "tool_calls" if calls else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        for ev in out:
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
            self.wfile.flush()
            time.sleep(0.01)
        self.wfile.write(b"data: [DONE]\n\n")


def start_fake_model():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


def make_env(root: Path, model_url: str, lang: str = "pl") -> dict:
    home = root / "home"
    cfg = home / ".config" / "doma"
    cfg.mkdir(parents=True)
    (cfg / "konta.json").write_text(json.dumps({"konta": {"atrapa": {
        "base_url": model_url, "api_key": "sk-test", "name": "Atrapa", "model": "atrapa-1"}}, "aktywne": "atrapa"}),
        encoding="utf-8")
    (cfg / "settings.json").write_text(json.dumps({"provider": "endpoint", "model_endpoint": "@atrapa/atrapa-1",
                                                   "lang": lang}), encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DOMA_CONFIG_DIR=str(cfg),
               DOMA_API_URL="http://127.0.0.1:9", CODO_LANG=lang, CODO_ONLINE="1", DOMA_NO_SYNC="1",
               CODO_APP_LOCAL_ONLY="1", NO_COLOR="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
    for k in ("CODO_PROVIDER", "CODO_APP_MODE", "CODO_NO_HISTORY", "CODO_OFFLINE", "CODO_UI_DEV"):
        env.pop(k, None)
    return env


def start_ui(proj: Path, env: dict, *extra):
    p = subprocess.Popen([sys.executable, SCRIPT, "ui", str(proj), "--no-browser", *extra], env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    url, seen = None, []
    deadline = time.time() + 30
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
        raise AssertionError("codo ui did not print its address: " + "".join(seen) + p.stderr.read())
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
    threading.Thread(target=lambda: [None for _ in p.stderr], daemon=True).start()
    u = urllib.parse.urlparse(url)
    return p, url, u.port, urllib.parse.parse_qs(u.query)["t"][0]
