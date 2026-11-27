"""Codo: agenci ACP (Agent Client Protocol, JSON-RPC 2.0 po stdio). Bez sieci, bez dostawców SI i bez
prawdziwych agentów: atrapa agenta ACP to mały skrypt Pythona, który prowadzi rozmowę według polecenia."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import signal
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa  # noqa: E402

_CFG = tempfile.mkdtemp(prefix="codo-acp-")
os.environ["DOMA_CONFIG_DIR"] = _CFG
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
_loader = importlib.machinery.SourceFileLoader(
    "codo_acp", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)

# Atrapa agenta ACP: odpowiada na initialize, session/new|load|set_mode|prompt; scenariusz wybiera słowo w poleceniu.
_FAKE_ACP = r'''
import json, os, sys
LOG = open(os.environ["FAKE_LOG"], "a")
NID = [1000]
LOAD = os.environ.get("FAKE_LOAD") == "1"


def send(o):
    sys.stdout.write(json.dumps(dict(jsonrpc="2.0", **o)) + "\n")
    sys.stdout.flush()


def recv():
    line = sys.stdin.readline()
    if not line:
        sys.exit(0)
    m = json.loads(line)
    LOG.write(json.dumps({"argv": sys.argv[1:], "msg": m}) + "\n")
    LOG.flush()
    return m


def request(method, params):
    NID[0] += 1
    send({"id": NID[0], "method": method, "params": params})
    while True:
        m = recv()
        if m.get("id") == NID[0] and "method" not in m:
            return m


def update(sid, u):
    send({"method": "session/update", "params": {"sessionId": sid, "update": u}})


def say(sid, text):
    update(sid, {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}})


def prompt(mid, p):
    sid = p["sessionId"]
    text = " ".join(b.get("text", "") for b in p["prompt"]).rsplit("\n\n", 1)[-1]   # samo polecenie
    app = os.path.join(os.getcwd(), "app.py")
    if "limit" in text:
        send({"id": mid, "error": {"code": -32603, "message": "You've hit your usage limit, resets at 5pm"}})
        return
    if "auth" in text:
        send({"id": mid, "error": {"code": -32000, "message": "Authentication required"}})
        return
    if "edytuj" in text:
        update(sid, {"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Edit app.py", "kind": "edit",
                     "status": "pending", "locations": [{"path": app}], "rawInput": {"file_path": app}})
        old = request("fs/read_text_file", {"sessionId": sid, "path": app})["result"]["content"]
        new = old.replace("x = 1", "x = 2")
        w = request("fs/write_text_file", {"sessionId": sid, "path": app, "content": new})
        if "error" in w:
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "failed"})
            say(sid, "zapis odrzucony: " + w["error"]["message"])
        else:
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed",
                         "content": [{"type": "diff", "path": app, "oldText": old, "newText": new}]})
            say(sid, "Zmieniłem x na 2.")
    if "sam-zapis" in text:
        # agent zapisuje plik sam (bez fs/write_text_file) i melduje diff
        path = os.path.join(os.getcwd(), "inny.py")
        old = open(path).read()
        update(sid, {"sessionUpdate": "tool_call", "toolCallId": "t5", "title": "Edit inny.py", "kind": "edit",
                     "status": "in_progress", "locations": [{"path": path}]})
        open(path, "w").write("y = 3\n")
        update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "t5", "status": "completed",
                     "content": [{"type": "diff", "path": path, "oldText": old, "newText": "y = 3\n"}]})
    if "polecenie" in text:
        r = request("session/request_permission", {
            "sessionId": sid,
            "toolCall": {"toolCallId": "t2", "title": "`rm -rf build`", "kind": "execute",
                         "rawInput": {"command": "rm -rf build"}},
            "options": [{"optionId": "a1", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "a2", "name": "Always", "kind": "allow_always"},
                        {"optionId": "r1", "name": "Reject", "kind": "reject_once"}]})
        out = r["result"]["outcome"]
        say(sid, "wynik: " + (out.get("optionId") or out["outcome"]))
    if "terminal" in text:
        t = request("terminal/create", {"sessionId": sid, "command": "echo", "args": ["ahoj"],
                                        "outputByteLimit": 1000})
        if "error" in t:
            say(sid, "terminal odrzucony")
        else:
            tid = t["result"]["terminalId"]
            update(sid, {"sessionUpdate": "tool_call", "toolCallId": "t3", "title": "echo ahoj", "kind": "execute",
                         "status": "in_progress", "content": [{"type": "terminal", "terminalId": tid}]})
            ex = request("terminal/wait_for_exit", {"sessionId": sid, "terminalId": tid})["result"]
            out = request("terminal/output", {"sessionId": sid, "terminalId": tid})["result"]
            update(sid, {"sessionUpdate": "tool_call_update", "toolCallId": "t3", "status": "completed"})
            request("terminal/release", {"sessionId": sid, "terminalId": tid})
            say(sid, "terminal: %s kod %s" % (out["output"].strip(), ex["exitCode"]))
    if "czytaj-poza" in text:
        r = request("fs/read_text_file", {"sessionId": sid, "path": "/etc/hosts"})
        say(sid, "błąd odczytu" if "error" in r else "przeczytano")
    if "plan" in text:
        update(sid, {"sessionUpdate": "plan", "entries": [
            {"content": "Przeczytać kod", "priority": "high", "status": "completed"},
            {"content": "Poprawić błąd", "priority": "high", "status": "in_progress"}]})
    if "tekst" in text:
        update(sid, {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "Rozważam."}})
        say(sid, "Cześć, ")
        say(sid, "tu atrapa ACP.")
    if "czekaj" in text:
        say(sid, "Zaczynam długą pracę.")
        while True:
            m = recv()
            if m.get("method") == "session/cancel":
                break
        send({"id": mid, "result": {"stopReason": "cancelled"}})
        return
    send({"id": mid, "result": {"stopReason": "end_turn"}})


while True:
    m = recv()
    method, mid, p = m.get("method"), m.get("id"), m.get("params") or {}
    if method == "initialize":
        send({"id": mid, "result": {"protocolVersion": 1, "agentCapabilities": {"loadSession": LOAD},
                                    "authMethods": [], "agentInfo": {"name": "atrapa", "version": "0.1"}}})
    elif method == "session/new":
        send({"id": mid, "result": {"sessionId": "s-1", "modes": {
            "currentModeId": "default", "availableModes": [{"id": "default", "name": "Default"},
                                                           {"id": "plan", "name": "Plan"}]}}})
    elif method == "session/load":
        update(p["sessionId"], {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "stare"}})
        say(p["sessionId"], "STARA ODPOWIEDŹ")
        send({"id": mid, "result": {}})
    elif method == "session/set_mode":
        send({"id": mid, "result": {}})
    elif method == "session/prompt":
        prompt(mid, p)
    elif mid is not None:
        send({"id": mid, "error": {"code": -32601, "message": "Method not found"}})
'''


class CodoAcpTests(unittest.TestCase):
    def setUp(self):
        for f in Path(_CFG).iterdir():
            if f.is_file():
                f.unlink()
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        Path("app.py").write_text("x = 1\n", encoding="utf-8")
        Path("inny.py").write_text("y = 1\n", encoding="utf-8")
        self.log = Path(self.tmp.name) / ".log"
        self.env_saved = dict(os.environ)
        os.environ["FAKE_LOG"] = str(self.log)
        fake = atrapa(self.tmp.name, ".bin-goose", textwrap.dedent(_FAKE_ACP))
        os.environ["CODO_AGENT_GOOSE"] = str(fake)
        for k in ("agent_sid", "agent_limit", "force_provider", "todos"):
            cli.SESSION.pop(k, None)
        cli.SESSION["edited"] = []

    def tearDown(self):
        os.chdir(self.prev)
        os.environ.clear()
        os.environ.update(self.env_saved)
        self.tmp.cleanup()

    def _msgs(self):
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines()] if self.log.exists() else []

    def _sent(self, method):
        return [e["msg"] for e in self._msgs() if e["msg"].get("method") == method]

    def _turn(self, text, mode="ask", auto=False, messages=None, confirm=True):
        messages = messages or [{"role": "system", "content": "sys"}]
        messages.append({"role": "user", "content": text})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), patch.object(cli, "confirm_action", return_value=confirm) as ask:
            ok = cli.agent_turn(None, messages, "agent:goose", auto, mode=mode)
        self.asked = ask.call_args_list
        return ok, buf.getvalue(), messages

    # ── rejestr ──────────────────────────────────────────────────────────
    def test_registry_has_acp_agents_with_commands(self):
        acp = [k for k, v in cli._AGENTS.items() if "acp" in v and not v.get("native")]
        self.assertGreaterEqual(len(acp), 15)
        for k in ("goose", "opencode", "qwen", "kimi", "auggie", "vibe", "copilot", "cursor", "cline", "kiro",
                  "qoder", "droid", "openhands", "docker", "blackbox"):
            self.assertIn(k, acp)
            info = cli._AGENTS[k]
            self.assertTrue(info["label"] and info["install"] and info["login"] and info["plan"])
            self.assertIsInstance(info["acp"], list)
            self.assertTrue(cli._agent_acp(k))
            self.assertEqual(cli.agent_kind("agent:" + k), k)
        self.assertEqual(cli._AGENTS["goose"]["acp"], ["acp"])
        self.assertEqual(cli._AGENTS["gemini"]["acp"], ["--acp"])
        # agenci z własnym trybem zostają na nim, dopóki użytkownik nie włączy ACP
        for k in ("claude", "codex", "gemini", "grok"):
            self.assertFalse(cli._agent_acp(k))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_agents("acp gemini wł"), 0)
        self.assertTrue(cli._agent_acp("gemini"))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.cmd_agents("acp gemini wył")
        self.assertFalse(cli._agent_acp("gemini"))

    def test_agents_list_shows_installed_and_missing(self):
        os.environ["PATH"] = str(Path(self.tmp.name) / "pusty")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.cmd_agents("")
        out = buf.getvalue()
        self.assertIn("goose", out)
        self.assertIn("ACP", out)
        self.assertIn("npm install -g @qwen-code/qwen-code@latest", out)   # niezainstalowany z komendą
        self.assertIn("/model agent:goose", out)                            # wykryty (atrapa)
        self.assertIn("goose", dict(cli.agents_available()))

    # ── rozmowa ACP ──────────────────────────────────────────────────────
    def test_initialize_new_session_and_streamed_text(self):
        ok, out, msgs = self._turn("tekst")
        self.assertTrue(ok, out)
        self.assertIn("tu atrapa ACP.", out)
        self.assertEqual(msgs[-1], {"role": "assistant", "content": "Cześć, tu atrapa ACP."})
        init = self._sent("initialize")[0]["params"]
        self.assertEqual(init["protocolVersion"], 1)
        self.assertEqual(init["clientCapabilities"]["fs"], {"readTextFile": True, "writeTextFile": True})
        self.assertTrue(init["clientCapabilities"]["terminal"])
        new = self._sent("session/new")[0]["params"]
        self.assertEqual(Path(new["cwd"]).resolve(), Path(self.tmp.name).resolve())
        self.assertEqual(new["mcpServers"], [])
        prompt = self._sent("session/prompt")[0]["params"]
        self.assertEqual(prompt["sessionId"], "s-1")
        self.assertIn("Codo", prompt["prompt"][0]["text"])           # instrukcja Codo w nowej sesji
        self.assertEqual(self._msgs()[0]["argv"], ["acp"])           # goose acp
        self.assertNotIn("goose", cli.SESSION.get("agent_sid", {}))  # agent bez session/load: bez wznawiania

    def test_thinking_goes_to_app(self):
        buf = io.StringIO()
        cli._APP["out"] = buf
        try:
            ok, out, _ = self._turn("tekst")
        finally:
            cli._APP["out"] = None
        events = [json.loads(x) for x in buf.getvalue().splitlines()]
        kinds = [e["type"] for e in events]
        self.assertIn("thinking", kinds)
        self.assertIn("delta", kinds)
        self.assertEqual(next(e for e in events if e["type"] == "thinking")["tekst"], "Rozważam.")

    def test_tool_call_with_diff_through_fs_write_has_backup_and_undo(self):
        ok, out, msgs = self._turn("edytuj")
        self.assertTrue(ok, out)
        self.assertEqual(Path("app.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertIn("app.py", out)
        entries = [e for e in cli.EDIT_LOG if e["path"].name == "app.py" and e["path"].parent.resolve()
                   == Path(self.tmp.name).resolve()]
        self.assertEqual(len(entries), 1)                       # fs/write + diff w tool_call = jedna zmiana
        self.assertIn("+x = 2", entries[-1]["diff"])
        _rel, baks = cli._backups_for(Path("app.py").resolve())
        self.assertEqual(len(baks), 1)                           # jedna kopia sprzed zmiany agenta
        self.assertEqual(baks[0].read_text(encoding="utf-8"), "x = 1\n")
        self.assertIn(Path("app.py").resolve(), cli.SESSION["edited"])

    def test_agent_written_file_reported_by_diff(self):
        ok, out, _ = self._turn("sam-zapis")
        self.assertTrue(ok, out)
        entry = [e for e in cli.EDIT_LOG if e["path"].name == "inny.py"][-1]
        self.assertIn("+y = 3", entry["diff"])
        self.assertIn("-y = 1", entry["diff"])
        _rel, baks = cli._backups_for(Path("inny.py").resolve())
        self.assertEqual([b.read_text(encoding="utf-8") for b in baks], ["y = 1\n"])

    def test_permission_allowed_and_rejected(self):
        ok, out, msgs = self._turn("polecenie", confirm=True)
        self.assertIn("wynik: a1", msgs[-1]["content"])
        q = self.asked[0]
        self.assertEqual(q.args[1], "rm -rf build")
        self.assertEqual(q.args[2], ["command", "rm -rf build"])   # ta sama zgoda co dla poleceń Codo
        ok, out, msgs = self._turn("polecenie", confirm=False)
        self.assertIn("wynik: r1", msgs[-1]["content"])
        ok, out, msgs = self._turn("polecenie", auto=True)          # --yes: bez pytania
        self.assertIn("wynik: a1", msgs[-1]["content"])
        self.assertEqual(self.asked, [])

    def test_permission_card_in_app_window(self):
        buf = io.StringIO()
        cli._APP["out"] = buf

        def answer():
            for _ in range(200):
                asks = [json.loads(x) for x in buf.getvalue().splitlines() if '"ask"' in x]
                if asks:
                    a = cli._APP["asks"][asks[0]["id"]]
                    a["value"] = 1
                    a["event"].set()
                    return
                threading.Event().wait(0.05)
        t = threading.Thread(target=answer)
        t.start()
        try:
            messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "polecenie"}]
            with contextlib.redirect_stdout(io.StringIO()):
                cli.agent_turn(None, messages, "agent:goose", False, mode="ask")
        finally:
            t.join(5)
            cli._APP["out"] = None
        ev = next(json.loads(x) for x in buf.getvalue().splitlines() if '"ask"' in x)
        self.assertEqual(ev["szczegol"], "rm -rf build")
        self.assertIn("wynik: a1", messages[-1]["content"])

    def test_read_mode_blocks_writes_commands_and_sets_plan_mode(self):
        ok, out, msgs = self._turn("edytuj polecenie terminal", mode="read")
        self.assertEqual(Path("app.py").read_text(encoding="utf-8"), "x = 1\n")
        text = msgs[-1]["content"]
        self.assertIn("zapis odrzucony", text)
        self.assertIn("wynik: r1", text)
        self.assertIn("terminal odrzucony", text)
        self.assertEqual(self._sent("session/set_mode")[0]["params"]["modeId"], "plan")
        self.assertIn("READ ONLY", self._sent("session/prompt")[0]["params"]["prompt"][0]["text"])

    def test_fs_read_outside_project_is_refused(self):
        ok, out, msgs = self._turn("czytaj-poza")
        self.assertIn("błąd odczytu", msgs[-1]["content"])

    def test_terminal_runs_in_project(self):
        ok, out, msgs = self._turn("terminal")
        self.assertTrue(ok, out)
        self.assertIn("terminal: ahoj kod 0", msgs[-1]["content"])

    def test_plan_becomes_todo_list(self):
        self._turn("plan tekst")
        self.assertEqual([t["status"] for t in cli.SESSION["todos"]], ["completed", "in_progress"])
        self.assertEqual(cli.SESSION["todos"][1]["content"], "Poprawić błąd")

    def test_session_load_resumes_without_replaying(self):
        os.environ["FAKE_LOAD"] = "1"
        ok, out, msgs = self._turn("tekst")
        self.assertEqual(cli.SESSION["agent_sid"]["goose"], "s-1")
        ok, out, msgs = self._turn("tekst", messages=msgs)
        self.assertTrue(ok, out)
        load = self._sent("session/load")
        self.assertEqual(load[0]["params"]["sessionId"], "s-1")
        self.assertNotIn("STARA ODPOWIEDŹ", out)
        self.assertNotIn("STARA ODPOWIEDŹ", msgs[-1]["content"])
        self.assertEqual(len(self._sent("session/new")), 1)

    def test_cancel_sends_session_cancel(self):
        def esc():
            for _ in range(200):
                if "Zaczynam" in "".join(x for x in [self.log.read_text(encoding="utf-8") if self.log.exists() else ""]) or any(
                        e["msg"].get("method") == "session/prompt" for e in self._msgs()):
                    threading.Event().wait(0.3)
                    os.kill(os.getpid(), signal.SIGINT)
                    return
                threading.Event().wait(0.05)
        t = threading.Thread(target=esc)
        t.start()
        with self.assertRaises(KeyboardInterrupt):
            self._turn("czekaj")
        t.join(5)
        cancel = self._sent("session/cancel")
        self.assertEqual(cancel[0]["params"], {"sessionId": "s-1"})
        self.assertNotIn("id", cancel[0])   # powiadomienie, nie żądanie

    def test_auth_error_points_to_login(self):
        ok, out, _ = self._turn("auth")
        self.assertFalse(ok)
        self.assertIn("Authentication required", out)
        self.assertIn("goose configure", out)

    def test_limit_falls_back_message(self):
        ok, out, _ = self._turn("limit")
        self.assertFalse(ok)
        self.assertIn("doszedł do limitu", out)
        self.assertIn("goose", cli.SESSION.get("agent_limit", {}))

    def test_delegate_to_acp_agent_is_quiet(self):
        with contextlib.redirect_stdout(io.StringIO()) as buf, patch.object(cli, "confirm_action", return_value=True):
            res = cli.run_tool("delegate", {"agent": "goose", "task": "tekst", "mode": "review"}, False)
        self.assertIn("Cześć, tu atrapa ACP.", res)
        self.assertNotIn("Cześć", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
