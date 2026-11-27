"""Codo 0.21.0: własne konta API (kilka naraz) i agenci zewnętrzni. Bez sieci i bez dostawców LLM:
serwer zgodny z OpenAI działa lokalnie, a claude/codex/gemini to atrapy wypisujące JSONL."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa, zamknij_stdin  # noqa: E402

_CFG = tempfile.mkdtemp(prefix="codo-konta-")
os.environ["DOMA_CONFIG_DIR"] = _CFG
os.environ["CODO_MADDLABS_DIRECT"] = "1"
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
_loader = importlib.machinery.SourceFileLoader(
    "codo_konta_agenci", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)


class _Api(BaseHTTPRequestHandler):
    """Atrapa /v1: modele i czat; zapisuje żądania do sprawdzenia."""
    calls: list = []
    key = "sk-test"
    models = ["grok-test", "text-embedding-3", "grok-mini"]
    need_completion_tokens = False
    stream_chunks: list = []      # gdy niepuste i żądanie ma stream=true: odpowiedź idzie jako SSE
    reject_stream = False

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if self.headers.get("Authorization") != f"Bearer {self.key}":
            self._send(401, {"error": {"message": "bad key"}})
            return False
        return True

    def do_GET(self):
        if not self._auth():
            return
        if self.path.endswith("/models"):
            self._send(200, {"data": [{"id": m} for m in self.models]})
        else:
            self._send(404, {})

    def do_POST(self):
        if not self._auth():
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append(body)
        if type(self).need_completion_tokens and "max_tokens" in body:
            self._send(400, {"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead."}})
            return
        if body.get("stream") and type(self).reject_stream:
            self._send(400, {"error": {"message": "stream is not supported"}})
            return
        if body.get("stream") and type(self).stream_chunks:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for ch in type(self).stream_chunks:
                self.wfile.write(("data: " + json.dumps(ch) + "\n\n").encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._send(200, {"model": body["model"], "choices": [{"message": {
            "role": "assistant", "content": [{"type": "text", "text": f"odpowiedź od {body['model']}"}]}}],
            "usage": {"completion_tokens": 3}})


_FAKE = {
    "claude": r'''
import json, os, sys
prompt = sys.stdin.read()
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": sys.argv[1:], "stdin": prompt}) + "\n")
def out(ev): print(json.dumps(ev), flush=True)
if os.environ.get("FAKE_MODE") == "nosession" and "--resume" in sys.argv:
    print("No conversation found with session ID: stara", file=sys.stderr)
    out({"type": "result", "subtype": "error_during_execution", "is_error": True, "errors": ["No conversation found"], "session_id": "stara"})
    sys.exit(1)
out({"type": "system", "subtype": "init", "session_id": "sid-claude-1"})
if os.environ.get("FAKE_MODE") == "limit":
    out({"type": "result", "subtype": "success", "is_error": True, "result": "Claude AI usage limit reached|1700000000", "session_id": "sid-claude-1"})
    sys.exit(1)
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Poprawiam app.py."},
     {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": os.path.abspath("app.py"), "old_string": "1", "new_string": "2"}}]}})
open("app.py", "w").write("x = 2\n")
out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}})
out({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}]}})
out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": [{"type": "text", "text": "1 passed"}]}]}})
out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Gotowe: x = 2."}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Gotowe: x = 2.", "session_id": "sid-claude-1"})
''',
    "codex": r'''
import json, os, sys
prompt = sys.stdin.read()
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": sys.argv[1:], "stdin": prompt}) + "\n")
def out(ev): print(json.dumps(ev), flush=True)
out({"type": "thread.started", "thread_id": "th-9"})
out({"type": "turn.started"})
out({"type": "item.started", "item": {"id": "i1", "type": "command_execution", "command": "ls", "status": "in_progress"}})
out({"type": "item.completed", "item": {"id": "i1", "type": "command_execution", "command": "ls", "aggregated_output": "app.py", "exit_code": 0, "status": "completed"}})
out({"type": "item.started", "item": {"id": "i2", "type": "file_change", "changes": [{"path": "nowy.txt", "kind": "add"}], "status": "in_progress"}})
open("nowy.txt", "w").write("hej\n")
out({"type": "item.completed", "item": {"id": "i2", "type": "file_change", "changes": [{"path": "nowy.txt", "kind": "add"}], "status": "completed"}})
out({"type": "item.completed", "item": {"id": "i3", "type": "agent_message", "text": "Dodałem nowy.txt."}})
out({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
''',
    "gemini": r'''
import json, os, sys
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": sys.argv[1:]}) + "\n")
def out(ev): print(json.dumps(ev), flush=True)
out({"type": "init", "session_id": "g1", "model": "gemini-x"})
out({"type": "message", "role": "assistant", "content": "Prze", "delta": True})
out({"type": "message", "role": "assistant", "content": "glądam.", "delta": True})
out({"type": "tool_use", "tool_name": "read_file", "tool_id": "r1", "parameters": {"absolute_path": os.path.abspath("app.py")}})
out({"type": "tool_result", "tool_id": "r1", "status": "success", "output": "x = 1"})
out({"type": "message", "role": "assistant", "content": "Kod jest w porządku.", "delta": True})
out({"type": "result", "status": "success", "stats": {}})
''',
}


class CodoKontaAgenciTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/v1"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        for f in Path(_CFG).iterdir():
            f.unlink()
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        Path("app.py").write_text("x = 1\n", encoding="utf-8")
        self.bin = Path(self.tmp.name) / ".bin"
        self.bin.mkdir()
        self.log = Path(self.tmp.name) / ".log"
        self.env_saved = dict(os.environ)
        os.environ["FAKE_LOG"] = str(self.log)
        for kind, code in _FAKE.items():
            p = atrapa(self.bin, kind, textwrap.dedent(code))
            os.environ[f"CODO_AGENT_{kind.upper()}"] = str(p)
        _Api.calls.clear()
        _Api.need_completion_tokens = False
        _Api.stream_chunks = []
        _Api.reject_stream = False
        cli._NO_STREAM.clear()
        cli._ENDPOINT_MODELS_CACHE.clear()
        for k in ("agent_sid", "agent_limit", "force_provider", "login_spec"):
            cli.SESSION.pop(k, None)
        cli.SESSION["edited"] = []

    def tearDown(self):
        os.chdir(self.prev)
        os.environ.clear()
        os.environ.update(self.env_saved)
        self.tmp.cleanup()

    def _login(self, name="xai", model="grok-test"):
        os.environ["CODO_ENDPOINT_KEY"] = _Api.key
        os.environ["CODO_ENDPOINT_MODEL"] = model
        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys, "stdin", io.StringIO("")):
            return cli.login_endpoint(self.url, name)

    def _calls(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()]

    def _turn(self, model, text, mode="ask", auto=False, messages=None):
        messages = messages or [{"role": "system", "content": "sys"}]
        messages.append({"role": "user", "content": text})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = cli.agent_turn(None, messages, model, auto, mode=mode)
        return ok, buf.getvalue(), messages

    # ── konta API ────────────────────────────────────────────────────────
    def test_login_two_accounts_and_models_from_both(self):
        self.assertEqual(self._login("xai"), 0)
        self.assertEqual(self._login("firma", "grok-mini"), 0)
        accts = cli.endpoint_accounts()
        self.assertEqual(set(accts), {"xai", "firma"})
        if os.name != "nt":   # prawa POSIX
            self.assertEqual(oct(os.stat(cli.ENDPOINTS_FILE).st_mode & 0o777), "0o600")
        self.assertEqual(cli.provider(), "endpoint")
        models, default = cli.fetch_models()
        ids = [m[0] for m in models]
        self.assertIn("@xai/grok-test", ids)
        self.assertIn("@firma/grok-mini", ids)
        self.assertFalse(any("embedding" in i for i in ids))
        self.assertEqual(default, "@firma/grok-mini")
        self.assertIn("agent:claude", ids)

    def test_step_routes_by_account_and_flattens_content(self):
        self._login("xai")
        self._login("firma", "grok-mini")
        r = cli.api_step(None, {"model": "@xai/grok-test", "messages": [{"role": "user", "content": "hej"}],
                                "tools": [{"type": "function", "function": {"name": "x", "parameters": {}}}]})
        self.assertEqual(r["message"]["content"], "odpowiedź od grok-test")
        self.assertEqual(r["credits_spent"], 0)
        self.assertEqual(_Api.calls[-1]["model"], "grok-test")
        self.assertIn("tools", _Api.calls[-1])

    # ── pisanie na żywo (strumień kroku z narzędziami w aplikacji) ───────────
    def test_partial_json_string_of_unfinished_arguments(self):
        f = cli._partial_json_str
        self.assertIsNone(f('{"path": "a.html"', "content"))
        self.assertEqual(f('{"path": "a.html", "content": "<h1>Za\\u01', "content"), "<h1>Za")
        self.assertEqual(f('{"path": "a.html", "content": "<h1>Za\\u017c\\u00f3\\n\\"x\\" \\', "content"), '<h1>Zażó\n"x" ')
        self.assertEqual(f('{"content": "gotowe", "path": "b"}', "content"), "gotowe")
        self.assertEqual(f('{"content": "\\ud83d', "content"), "")            # połówka emoji nie psuje tekstu
        self.assertEqual(f('{"content": "\\ud83d\\ude00!', "content"), "😀!")

    def _tools_body(self):
        return {"model": "@xai/grok-test", "messages": [{"role": "user", "content": "napisz"}],
                "tools": [{"type": "function", "function": {"name": "write_file", "parameters": {}}}]}

    def test_stream_shows_file_while_it_is_written(self):
        self._login("xai")
        args = json.dumps({"path": "Oferta.doc.html", "content": "<article>\n<h1>Oferta</h1>\n<p>Zażółć gęślą jaźń.</p>\n</article>"})
        parts = [args[i:i + 9] for i in range(0, len(args), 9)]
        _Api.stream_chunks = (
            [{"model": "grok-test", "choices": [{"delta": {"role": "assistant", "content": "Piszę."}}]},
             {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                                     "function": {"name": "write_file", "arguments": ""}}]}}]}]
            + [{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": p}}]}}]} for p in parts]
            + [{"choices": [], "usage": {"completion_tokens": 40}}])
        out = io.StringIO()
        with patch.dict(cli._APP, {"out": out}), patch.dict(cli._WRITING, {"t": -1e9, "len": -1}), \
                patch("time.monotonic", side_effect=(float(i) for i in range(10000))):
            r = cli.api_step(None, self._tools_body())
        self.assertTrue(_Api.calls[-1]["stream"])
        call = r["message"]["tool_calls"][0]
        self.assertEqual(call["function"]["name"], "write_file")
        self.assertEqual(json.loads(call["function"]["arguments"])["path"], "Oferta.doc.html")
        self.assertEqual(r["message"]["content"], "Piszę.")
        self.assertEqual(r["usage"], {"completion_tokens": 40})
        events = [json.loads(x) for x in out.getvalue().splitlines()]
        writing = [e for e in events if e["type"] == "writing"]
        self.assertGreater(len(writing), 3)
        self.assertTrue(all(e["plik"] == "Oferta.doc.html" and e["tryb"] == "write" for e in writing))
        texts = [e["tekst"] for e in writing]
        self.assertTrue(all(b.startswith(a) for a, b in zip(texts, texts[1:])))     # tekst tylko przyrasta
        self.assertEqual(texts[-1], "<article>\n<h1>Oferta</h1>\n<p>Zażółć gęślą jaźń.</p>\n</article>")

    def test_server_deltas_are_joined_for_the_app(self):
        out, state = io.StringIO(), {}
        with patch.dict(cli._APP, {"out": out}):
            cli._lopus_writing(state, {"plik": "a.doc.html", "tryb": "write", "od": 0, "delta": "<h1>Of", "index": 1})
            cli._lopus_writing(state, {"plik": "a.doc.html", "tryb": "write", "od": 6, "delta": "erta</h1>", "index": 1})
            cli._lopus_writing(state, {"plik": "b.deck.html", "tryb": "edit", "od": 0, "delta": "<h2>No", "stary": "<h2>Stary</h2>", "index": 2})
            cli._lopus_writing(state, {"plik": "b.deck.html", "tryb": "edit", "od": 6, "delta": "wy</h2>", "index": 2})
        ev = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([e["tekst"] for e in ev], ["<h1>Of", "<h1>Oferta</h1>", "<h2>No", "<h2>Nowy</h2>"])
        self.assertEqual(ev[3]["stary"], "<h2>Stary</h2>")
        self.assertNotIn("stary", ev[1])

    def test_stream_is_app_only_and_falls_back_when_refused(self):
        self._login("xai")
        cli.api_step(None, self._tools_body())                        # terminal: zwykłe żądanie
        self.assertNotIn("stream", _Api.calls[-1])
        _Api.reject_stream = True
        with patch.dict(cli._APP, {"out": io.StringIO()}):
            r = cli.api_step(None, self._tools_body())
            self.assertEqual(r["message"]["content"], "odpowiedź od grok-test")
            self.assertEqual([c.get("stream") for c in _Api.calls[-2:]], [True, None])
            cli.api_step(None, self._tools_body())                    # zapamiętane: bez drugiej próby
            self.assertNotIn("stream", _Api.calls[-1])
            self.assertEqual(len(_Api.calls), 4)

    def test_max_completion_tokens_retry_is_remembered(self):
        self._login("openai")
        _Api.need_completion_tokens = True
        r = cli.endpoint_step({"model": "@openai/grok-test", "messages": [{"role": "user", "content": "a"}]})
        self.assertIn("grok-test", r["message"]["content"])
        self.assertIn("max_completion_tokens", _Api.calls[-1])
        self.assertEqual(cli.load_endpoint("openai").get("max_field"), "max_completion_tokens")

    def test_bad_key_rejected_and_http_only_local(self):
        os.environ["CODO_ENDPOINT_KEY"] = "zly"
        os.environ["CODO_ENDPOINT_MODEL"] = "grok-test"
        with contextlib.redirect_stdout(io.StringIO()) as out, patch.object(sys, "stdin", io.StringIO("")):
            self.assertEqual(cli.login_endpoint(self.url, "xai"), 1)
        self.assertIn("klucz", out.getvalue())
        self.assertIsNone(cli._endpoint_base_ok("http://api.example.com/v1"))
        self.assertEqual(cli._endpoint_base_ok("http://192.168.1.5:8000/v1/chat/completions"), "http://192.168.1.5:8000/v1")
        self.assertIsNone(cli._endpoint_base_ok("https://user:pass@x.com/v1"))
        self.assertEqual(cli._endpoint_base_ok("https://api.x.ai/v1/"), "https://api.x.ai/v1")

    def test_accounts_remove_and_use(self):
        self._login("xai")
        self._login("firma", "grok-mini")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_accounts("użyj xai"), 0)
            self.assertEqual(cli.current_model(None), "@xai/grok-test")
            self.assertEqual(cli.cmd_accounts("usuń xai"), 0)
        self.assertEqual(set(cli.endpoint_accounts()), {"firma"})
        self.assertIsNone(cli.load_settings().get("model_endpoint"))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.logout_endpoint()
        self.assertEqual(cli.provider(), "domaai")   # bez kont: zwykłe logowanie, tryb agentów tylko z wyboru

    # ── agenci zewnętrzni ───────────────────────────────────────────────
    def test_claude_turn_edits_with_undo_and_resumes_session(self):
        ok, out, msgs = self._turn("agent:claude", "zmień x na 2")
        self.assertTrue(ok, out)
        self.assertIn("Gotowe: x = 2.", out)
        self.assertIn("app.py", out)
        self.assertEqual(msgs[-1]["role"], "assistant")
        self.assertTrue(any(e["path"].name == "app.py" and e["added"] == 1 for e in cli.EDIT_LOG))
        self.assertTrue(cli._backups_for(Path("app.py").resolve()))   # /undo ma kopię sprzed zmiany agenta
        first = self._calls()[-1]
        self.assertIn("acceptEdits", first["argv"])
        self.assertNotIn("--resume", first["argv"])
        self._turn("agent:claude", "a teraz testy", messages=msgs)
        second = self._calls()[-1]
        self.assertEqual(second["argv"][second["argv"].index("--resume") + 1], "sid-claude-1")
        self.assertEqual(second["stdin"], "a teraz testy")

    def test_permission_modes(self):
        self._turn("agent:claude", "przejrzyj", mode="read")
        self.assertIn("plan", self._calls()[-1]["argv"])
        cli.SESSION.pop("agent_sid", None)
        self._turn("agent:claude", "rób", auto=True)
        self.assertIn("bypassPermissions", self._calls()[-1]["argv"])
        self._turn("agent:codex", "przejrzyj", mode="read")
        argv = self._calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self._turn("agent:gemini", "rób", auto=True)
        argv = self._calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("--approval-mode") + 1], "yolo")

    def test_codex_turn_new_file_and_context_carried(self):
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "co to za projekt?"},
                {"role": "assistant", "content": "Projekt w Pythonie."}]
        ok, out, msgs = self._turn("agent:codex", "dodaj plik", messages=msgs)
        self.assertTrue(ok, out)
        self.assertIn("Dodałem nowy.txt.", out)
        call = self._calls()[-1]
        self.assertEqual(call["argv"][:2], ["exec", "--json"])
        self.assertIn("Projekt w Pythonie.", call["stdin"])   # zmiana modelu w trakcie nie gubi wątku
        self.assertEqual(cli.SESSION["agent_sid"]["codex"], "th-9")
        self.assertTrue(any(e["path"].name == "nowy.txt" and e["new_file"] for e in cli.EDIT_LOG))
        self._turn("agent:codex", "dalej", messages=msgs)
        argv = self._calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("resume") + 1], "th-9")
        self.assertLess(argv.index("-s"), argv.index("resume"))   # codex odrzuca -s po resume

    def test_lost_session_restarts_with_context(self):
        cli.SESSION["agent_sid"] = {"claude": "stara"}
        os.environ["FAKE_MODE"] = "nosession"
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "pierwsze"},
                {"role": "assistant", "content": "Pierwsza odpowiedź."}]
        ok, out, _ = self._turn("agent:claude", "drugie", messages=msgs)
        self.assertTrue(ok, out)
        calls = self._calls()
        self.assertIn("--resume", calls[-2]["argv"])
        self.assertNotIn("--resume", calls[-1]["argv"])
        self.assertIn("Pierwsza odpowiedź.", calls[-1]["stdin"])

    def test_gemini_deltas_joined(self):
        ok, out, msgs = self._turn("agent:gemini", "sprawdź")
        self.assertTrue(ok, out)
        self.assertIn("Przeglądam.", out)
        self.assertIn("Kod jest w porządku.", msgs[-1]["content"])

    def test_limit_falls_back_to_own_account_then_sticks(self):
        self._login("xai")
        os.environ["FAKE_MODE"] = "limit"
        ok, out, msgs = self._turn("agent:claude", "zrób coś")
        self.assertTrue(ok, out)
        self.assertIn("doszedł do limitu", out)
        self.assertEqual(msgs[-1]["content"], "odpowiedź od grok-test")
        self.assertNotIn("force_provider", cli.SESSION)
        n = len(self._calls())
        ok, out, _ = self._turn("agent:claude", "dalej", messages=msgs)
        self.assertTrue(ok)
        self.assertEqual(len(self._calls()), n)   # w limicie agent nie jest wołany ponownie
        self.assertIn("czeka na odnowienie", out)

    def test_limit_without_account_points_to_login(self):
        os.environ["FAKE_MODE"] = "limit"
        ok, out, _ = self._turn("agent:claude", "zrób coś")
        self.assertFalse(ok)
        self.assertIn("codo login", out)

    def test_missing_agent_and_no_account_provider(self):
        os.environ["CODO_AGENT_CLAUDE"] = str(self.bin / "brak")
        self.assertNotIn("claude", dict(cli.agents_available()))
        self.assertEqual(cli.provider(), "domaai")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.use_local_agents(), 0)   # jeden wybór naraz: brak okna, bierze pierwszego
        self.assertEqual(cli.provider(), "agent")
        self.assertEqual(cli._model_key(), "model_agent")
        models, default = cli.fetch_models()
        self.assertEqual(default, "agent:codex")

    def test_delegate_review_is_quiet_and_returns_summary(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = cli.run_tool("delegate", {"agent": "codex", "task": "sprawdź app.py", "mode": "review"}, False)
        self.assertIn("Dodałem nowy.txt.", res)
        self.assertIn("2 kroków", res)
        argv = self._calls()[-1]["argv"]
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("BŁĄD", cli.run_tool("delegate", {"agent": "nieznany", "task": "x"}, False))
        self.assertIn("delegate", [t["function"]["name"] for t in cli.TOOLS])



class CodoAppServerTests(unittest.TestCase):
    """codo app-server: silnik aplikacji okienkowej, protokół JSON w liniach (bez sieci, atrapa Claude)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Path(self.tmp.name) / "cfg"
        self.cfg.mkdir()
        (self.cfg / "settings.json").write_text(json.dumps({"provider": "agent", "model_agent": "agent:claude"}), encoding="utf-8")
        self.proj = Path(self.tmp.name) / "proj"
        self.proj.mkdir()
        (self.proj / "app.py").write_text("x = 1\n", encoding="utf-8")
        fake = atrapa(self.tmp.name, "claude", textwrap.dedent(_FAKE["claude"]))
        self.env = dict(os.environ, DOMA_CONFIG_DIR=str(self.cfg), CODO_AGENT_CLAUDE=str(fake),
                        CODO_AGENT_CODEX="/brak", CODO_AGENT_GEMINI="/brak", DOMA_API_URL="http://127.0.0.1:9",
                        FAKE_LOG=str(Path(self.tmp.name) / "log"), CODO_LANG="en", DOMA_NO_SYNC="1")

    def tearDown(self):
        self.tmp.cleanup()

    def test_turn_streams_events_and_saves_conversation(self):
        import subprocess
        script = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))
        cmds = [{"type": "mode", "mode": "auto"}, {"type": "send", "text": "zmień x na 2"}]
        p = subprocess.Popen([sys.executable, script, "app-server"], cwd=self.proj, env=self.env, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        events = []
        ready = json.loads(p.stdout.readline())
        self.assertEqual(ready["type"], "ready")
        self.assertEqual(ready["model"], "agent:claude")
        self.assertTrue(ready["logged_in"])
        for c in cmds:
            p.stdin.write(json.dumps(c) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            events.append(json.loads(line))
            if events[-1]["type"] == "turn_end":
                break
        zamknij_stdin(p)
        p.wait(10)
        kinds = [e["type"] for e in events]
        for k in ("mode", "turn_start", "delta", "assistant", "tool_start", "tool", "edit", "turn_end"):
            self.assertIn(k, kinds)
        edit = next(e for e in events if e["type"] == "edit")
        self.assertEqual(edit["plik"], "app.py")
        self.assertIn("+x = 2", edit["diff"])
        self.assertTrue(events[-1]["ok"])
        self.assertTrue(events[-1]["convo_id"])
        self.assertEqual((self.proj / "app.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertNotIn("Traceback", p.stderr.read())

    def test_ask_waits_for_answer_from_app(self):
        buf = io.StringIO()
        cli._APP["out"] = buf
        try:
            res = []
            t = threading.Thread(target=lambda: res.append(cli._app_ask("Run command?", "rm -rf build", "", True)))
            t.start()
            for _ in range(50):
                if buf.getvalue():
                    break
                threading.Event().wait(0.02)
            ev = json.loads(buf.getvalue().splitlines()[0])
            self.assertEqual(ev["type"], "ask")
            self.assertEqual([o["value"] for o in ev["opcje"]], [1, 2, 0])
            a = cli._APP["asks"][ev["id"]]
            a["value"] = 2
            a["event"].set()
            t.join(3)
            self.assertEqual(res, [2])
            self.assertEqual(cli._APP["asks"], {})
        finally:
            cli._APP["out"] = None


class CodoFirstRunLoginTests(unittest.TestCase):
    """Pierwszy start bez konta: MaddLabs z darmowymi kredytami na górze listy."""

    def test_first_run_puts_maddlabs_free_credits_first(self):
        found = [("claude", "/usr/bin/claude")]
        ways = cli._login_ways(True, found)
        self.assertEqual([k for k, _ in ways][:4], ["maddlabs", "endpoint", "agent", "domaai"])
        self.assertIn(cli._L("Zaloguj się kontem MaddLabs: darmowe kredyty na start"), ways[0][1])
        self.assertEqual(len(ways), len(cli._LOGIN_WAYS) + 1)

    def test_logged_in_keeps_regular_order(self):
        ways = cli._login_ways(False, [])
        self.assertEqual(ways, list(cli._LOGIN_WAYS))

    def test_english_label(self):
        self.assertEqual(cli._EN["Zaloguj się kontem MaddLabs: darmowe kredyty na start"],
                         "Sign in with MaddLabs: free credits to start")


if __name__ == "__main__":
    unittest.main()


class CodoAgentDomaaiTests(CodoAppServerTests):
    """Agent SI z DomaAI w Codo (persona na każdym mózgu) i własna nazwa rozmowy z okna."""

    def setUp(self):
        super().setUp()
        (self.cfg / "device.json").write_text(json.dumps({"device_id": "d1", "device_secret": "s1",
                                                           "api_url": "http://127.0.0.1:9"}), encoding="utf-8")
        (self.cfg / "agent.json").write_text(json.dumps({"agent": "Tomi", "kolory_agenta": ["#FF0000"],
                                                          "ton": "przyjazny",
                                                          "persona": "TWOJA TOŻSAMOŚĆ: masz na imię Tomi"}), encoding="utf-8")
        self.env["CODO_PROVIDER"] = "agent"   # konto DomaAI jest, ale mózgiem jest Claude Code z atrapy

    def _run(self, cmds, until="turn_end"):
        import subprocess
        script = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))
        p = subprocess.Popen([sys.executable, script, "app-server"], cwd=self.proj, env=self.env, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        events = [json.loads(p.stdout.readline())]
        for c in cmds:
            p.stdin.write(json.dumps(c) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            events.append(json.loads(line))
            if events[-1]["type"] == until:
                break
        zamknij_stdin(p)
        p.wait(10)
        return events

    def test_persona_reaches_external_agent_and_rename_sticks(self):
        events = self._run([{"type": "rename", "title": "  Moja   strona "},
                            {"type": "mode", "mode": "auto"}, {"type": "send", "text": "zmień x na 2"}])
        renamed = next(e for e in events if e["type"] == "renamed")
        self.assertEqual(renamed["title"], "Moja strona")
        self.assertEqual(events[-1]["title"], "Moja strona")
        saved = next((self.cfg / "rozmowy").rglob("*.json"))
        data = json.loads(saved.read_text(encoding="utf-8"))
        self.assertEqual(data["custom_title"], "Moja strona")
        argv = json.loads(Path(self.env["FAKE_LOG"]).read_text(encoding="utf-8").splitlines()[0])["argv"]
        sysp = argv[argv.index("--append-system-prompt") + 1]
        self.assertIn("TWÓJ AGENT SI Z DOMAAI", sysp)
        self.assertIn("masz na imię Tomi", sysp)

    def test_persona_off_and_status_shows_agent(self):
        events = self._run([{"type": "persona", "on": False}], until="status")
        st = events[-1]
        self.assertEqual(st["agent"]["name"], "Tomi")
        self.assertFalse(st["agent"]["on"])
        self.assertTrue(st["agent"]["persona_ready"])
        self.assertIs(json.loads((self.cfg / "settings.json").read_text(encoding="utf-8"))["domaai_agent"], False)
        events = self._run([{"type": "mode", "mode": "auto"}, {"type": "send", "text": "zmień x na 2"}])
        argv = json.loads(Path(self.env["FAKE_LOG"]).read_text(encoding="utf-8").splitlines()[-1])["argv"]
        self.assertNotIn("TWÓJ AGENT SI Z DOMAAI", argv[argv.index("--append-system-prompt") + 1])


class CodoMaszynaTests(unittest.TestCase):
    """Projekt na maszynie DomaAI: pakowanie bez sekretów i zależności, pobranie zmian z kopią."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / ".env").write_text("SECRET=1\n", encoding="utf-8")
        (self.root / ".env.example").write_text("SECRET=\n", encoding="utf-8")
        (self.root / "node_modules" / "a").mkdir(parents=True)
        (self.root / "node_modules" / "a" / "i.js").write_text("//", encoding="utf-8")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        self.cwd = os.getcwd()
        os.chdir(self.root)
        cli.SESSION["edited"] = []

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()
        cli.SESSION.pop("maszyna", None)

    def test_pack_skips_secrets_deps_and_git(self):
        import io
        import tarfile
        data, n, _total, _skipped = cli.maszyna_spakuj()
        names = sorted(tarfile.open(fileobj=io.BytesIO(data)).getnames())
        self.assertEqual(names, [".env.example", "src/app.py"])
        self.assertEqual(n, 2)

    def test_pull_writes_changes_with_backup_and_blocks_escape(self):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("src/app.py", "x = 2\n")
            zf.writestr("src/nowy.py", "print(1)\n")
            zf.writestr("../poza.txt", "zle")
            zf.writestr("node_modules/b.js", "zle")
        with patch.object(cli, "_maszyna_req", return_value=buf.getvalue()), \
             patch.object(cli, "_chat_id", return_value="0b6c2f8e-1d2a-4c3b-9e8f-123456789abc"):
            changed = cli.maszyna_pobierz()
        self.assertEqual(sorted(c[0] for c in changed), ["src/app.py", "src/nowy.py"])
        self.assertEqual((self.root / "src" / "app.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertFalse((self.root.parent / "poza.txt").exists())
        self.assertFalse((self.root / "node_modules" / "b.js").exists())
        backups = list((self.root / ".doma").rglob("app.py.*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "x = 1\n")

    def test_machine_mode_turn_goes_to_lopus(self):
        cli.SESSION["maszyna"] = True
        with patch.object(cli, "lopus_turn", return_value=True) as lt, \
             patch.object(cli, "external_turn") as ext:
            self.assertTrue(cli.agent_turn(None, [{"role": "user", "content": "x"}], "agent:claude", False))
        ext.assert_not_called()
        self.assertIn(lt.call_args.args[2], ("lopus", "lopus-pro"))


class CodoPrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        import subprocess as sp
        sp.run(["git", "init", "-q", "-b", "main"], check=True)
        sp.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "a"], check=True)
        (self.root / "a.txt").write_text("x", encoding="utf-8")

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_status_lists_changes_and_needs_github(self):
        st = cli.pr_status()
        self.assertTrue(st["git"])
        self.assertEqual(st["branch"], "main")
        self.assertIn("a.txt", st["files"])
        self.assertFalse(st["github"])
        with self.assertRaises(ValueError):
            cli.pr_create("Napraw logowanie", "")

    def test_slug_is_ascii_branch_name(self):
        self.assertEqual(cli._slug("Zażółć gęślą jaźń: logowanie!"), "zazolc-gesla-jazn-logowanie")
