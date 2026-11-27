"""Standalone CLI auth and terminal regressions; stdlib-only, no live API."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

loader = importlib.machinery.SourceFileLoader("doma_cli_auth_runtime", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class AuthRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for attr, path in (("CONFIG_DIR", root), ("CRED_FILE", root / "credentials.json"), ("DEVICE_FILE", root / "device.json")):
            patcher = patch.object(cli, attr, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        cli._DEV_TOK.update(token=None, ts=0.0, identity=None)

    def test_model_catalog_is_authenticated_and_shows_text_only_capability(self):
        cli.save_device({"device_id": "one", "device_secret": "s"})
        data = {"default_model": "provider/new-model", "models": [
            {"id": "provider/new-model", "label": "New model", "min_plan": "pro", "supports_tools": False}
        ]}
        with patch.object(cli, "_http", side_effect=[{"access_token": "device-jwt"}, data]) as request:
            models, default = cli.fetch_models()
        self.assertEqual(default, "provider/new-model")
        self.assertIn("bez narzędzi", models[0][1])
        self.assertEqual(request.call_args.args, ("GET", "/cli/models"))
        self.assertEqual(request.call_args.kwargs["token"], "device-jwt")
        self.assertIsNone(request.call_args.kwargs["json_body"])

    def test_model_selection_uses_fresh_list_and_persists_choice(self):
        models = [("provider/new-model", "New", "pro")]
        with patch.object(cli, "fetch_models", return_value=(models, models[0][0])) as fetch, patch.object(cli, "load_settings", return_value={}), patch.object(cli, "save_settings") as save, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_model("1"), 0)
        fetch.assert_called_once()
        self.assertEqual(save.call_args.args[0]["model"], "provider/new-model")

    def test_malformed_or_other_server_device_is_ignored(self):
        for value in ([], "text", 42, None, {"device_id": "a"}, {"device_id": "a", "device_secret": "b", "api_url": "https://other.invalid"}):
            cli.DEVICE_FILE.write_text(json.dumps(value), encoding="utf-8")
            self.assertIsNone(cli.load_device())

    def test_save_is_private_and_removes_full_session(self):
        cli.save_creds({"access_token": "a", "refresh_token": "r"})
        cli.save_device({"device_id": "one", "device_secret": "secret"})
        self.assertFalse(cli.CRED_FILE.exists())
        self.assertEqual(cli.load_device()["api_url"], cli.API_URL)
        if os.name != "nt":
            self.assertEqual(cli.DEVICE_FILE.stat().st_mode & 0o777, 0o600)
        self.assertEqual(sorted(p.name for p in cli.CONFIG_DIR.iterdir()), ["device.json"])

    def test_cache_changes_with_device_and_serializes_threads(self):
        from concurrent.futures import ThreadPoolExecutor
        cli.save_device({"device_id": "one", "device_secret": "s"})
        with patch.object(cli, "_http", return_value={"access_token": "token-one"}) as request:
            with ThreadPoolExecutor(max_workers=4) as pool:
                self.assertEqual(list(pool.map(lambda _: cli.device_access_token(), range(12))), ["token-one"] * 12)
            self.assertEqual(request.call_count, 1)
        # Simulate another CLI process replacing the file while this one runs.
        cli._save_private_json(cli.DEVICE_FILE, {"device_id": "two", "device_secret": "s"})
        with patch.object(cli, "_http", return_value={"access_token": "token-two"}):
            self.assertEqual(cli.device_access_token(), "token-two")

    def test_poll_survives_network_failure(self):
        states = [urllib.error.URLError("offline"), {"status": "pending"}, {"status": "confirmed", "device_id": "one", "device_secret": "s"}]
        with patch.object(cli, "_http", side_effect=states), patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._wait_for_pairing({"device_token": "poll", "expires_in": 900}), 0)
        self.assertEqual(cli.load_device()["device_id"], "one")

    def test_already_claimed_is_failure_and_does_not_loop(self):
        with patch.object(cli, "_http", return_value={"status": "claimed"}) as request, patch("time.sleep"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli._wait_for_pairing({"device_token": "poll", "expires_in": 900}), 1)
            self.assertEqual(request.call_count, 1)

    def test_password_otp_and_cleanup(self):
        responses = [cli.ApiError(403, "Kod", {"requires_2fa": True}),
                     {"access_token": "session", "refresh_token": "refresh"},
                     {"device_id": "one", "device_secret": "s"}, {}]
        with patch.object(cli, "_http", side_effect=responses) as request, patch("builtins.input", return_value="a@example.test"), patch("getpass.getpass", side_effect=["password", "123456"]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.login_password(), {"device": True})
        self.assertEqual(request.call_args_list[1].kwargs["form"]["totp_code"], "123456")
        self.assertEqual(request.call_args_list[-1].args[1], "/logout")
        self.assertFalse(cli.CRED_FILE.exists())

    def test_password_pair_failure_does_not_persist_full_session(self):
        responses = [{"access_token": "session", "refresh_token": "refresh"}, cli.ApiError(403, "Plan"), {}]
        with patch.object(cli, "_http", side_effect=responses) as request, patch("builtins.input", return_value="a@example.test"), patch("getpass.getpass", return_value="pw"), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(cli.ApiError):
                cli.login_password()
        self.assertEqual(request.call_args_list[-1].args[1], "/logout")
        self.assertFalse(cli.CRED_FILE.exists())
        self.assertFalse(cli.DEVICE_FILE.exists())

    def test_logout_revokes_server_device_and_clears_cache(self):
        cli.save_device({"device_id": "one", "device_secret": "s"})
        cli._DEV_TOK["token"] = "stale"
        with patch.object(cli, "_http", side_effect=[{"access_token": "t"}, {"ok": True}]) as request, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.logout(), 0)
        self.assertEqual(request.call_args_list[-1].args[1], "/cli/device/logout")
        self.assertFalse(cli.DEVICE_FILE.exists())
        self.assertIsNone(cli._DEV_TOK["token"])

    def test_refusal_stops_remaining_tools_and_returns_to_user(self):
        response = {"message": {"role": "assistant", "tool_calls": [
            {"id": str(i), "function": {"name": "run_command", "arguments": '{"command": "echo test"}'}}
            for i in range(2)
        ]}}
        messages = [{"role": "user", "content": "task"}]
        with patch.object(cli, "api_step", return_value=response) as step, patch.object(cli, "run_tool", return_value="ODRZUCONE przez użytkownika") as run, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(cli.agent_turn({}, messages, None, False))
        self.assertEqual(step.call_count, 1)
        self.assertEqual(run.call_count, 1)
        self.assertEqual([m["tool_call_id"] for m in messages if m["role"] == "tool"], ["0", "1"])

    def test_skill_search_filters_installed_and_matches_descriptions(self):
        skills = [{"id": "frontend", "nazwa": "Frontend", "opis": "Projektowanie stron", "wlaczona": True},
                  {"id": "docs", "nazwa": "Dokumenty", "opis": "Raporty", "wlaczona": False}]
        self.assertEqual(cli._skill_filter(skills, "projektowanie STRON", False), [skills[0]])
        self.assertEqual(cli._skill_filter(skills, "", True), [skills[0]])
        self.assertEqual(cli._skill_filter(skills, "nieistniejące", False), [])

    def test_sse_parser_handles_heartbeats_multiline_and_final_unterminated_frame(self):
        frames = list(cli._sse_frames(io.BytesIO(b': ping\n\nevent: status\ndata: {"text":\ndata: "Working"}\n\ndata: {"type":"done","answer":"OK"}')))
        self.assertEqual(frames, [("status", {"text": "Working"}), ("done", {"type": "done", "answer": "OK"})])

    def test_lopus_dispatches_real_agent_and_keeps_selected_variant(self):
        for model in ("lopus", "lopus-pro"):
            with patch.object(cli, "lopus_turn", return_value=True) as turn, patch.object(cli, "api_step") as single:
                self.assertTrue(cli.agent_turn({}, [{"role": "user", "content": "task"}], model, False))
            self.assertEqual(turn.call_args.args[2], model)
            single.assert_not_called()

    def test_lopus_local_read_mode_blocks_execution_and_reports_result(self):
        bridge = cli._LopusBridge.__new__(cli._LopusBridge)
        bridge.mode, bridge.auto_yes, bridge.creds = "read", False, {}
        with patch.object(cli, "run_tool") as run, patch.object(cli, "api_call") as api, contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(bridge.execute({"id": "job", "tool": "run_command", "args": {"command": "bad"}}))
        run.assert_not_called()
        self.assertFalse(api.call_args.args[2]["ok"])

    def test_input_view_fits_unicode_and_cursor(self):
        for value in ("x" * 400, "ąęółż 世界 👋 " * 50):
            for cursor in (0, 20, len(value)):
                for width in (1, 10, 70):
                    shown, column = cli._input_view(value, cursor, width)
                    self.assertLessEqual(cli._display_width(shown), width)
                    self.assertLessEqual(column, width)

    def test_permission_shows_environment_reason_and_exact_command(self):
        output = io.StringIO()
        with patch.object(cli, "load_settings", return_value={}), patch.object(cli, "_choose_yes_no", return_value=0), contextlib.redirect_stdout(output):
            self.assertFalse(cli.confirm_action("Uruchomić?", "npm test", ["command", "npm test"], reason="Sprawdzenie zmian"))
        for text in ("Środowisko: lokalne", str(Path.cwd()), "Powód: Sprawdzenie zmian", "$ npm test"):
            self.assertIn(text, output.getvalue())


@unittest.skipIf(os.name == "nt", "POSIX PTY")
class PermissionKeyboardTests(unittest.TestCase):
    def choose(self, keys, body=None, marker=b"(Esc)"):
        import pty
        import select
        import subprocess
        import sys
        import time
        master, slave = pty.openpty()
        import fcntl, struct, termios
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        source = f"import runpy; m=runpy.run_path({str(Path(os.environ.get('CODO_FILE') or Path(__file__).resolve().parents[1] / 'static/cli/doma'))!r}, run_name='cli_test'); print('RESULT', m['_choose_yes_no'](True), flush=True)"
        if body:
            source = f"import runpy; m=runpy.run_path({str(Path(os.environ.get('CODO_FILE') or Path(__file__).resolve().parents[1] / 'static/cli/doma'))!r}, run_name='cli_test')\n" + body
        process = subprocess.Popen([sys.executable, "-c", source], stdin=slave, stdout=slave, stderr=slave, env={**os.environ, "TERM": "xterm-256color"})
        os.close(slave)
        output = b""
        try:
            deadline = time.monotonic() + 5
            while marker not in output and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    chunk = os.read(master, 8192)
                    if not chunk:
                        break
                    output += chunk
            self.assertIn(marker, output)
            os.write(master, keys)
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        output += os.read(master, 8192)
                    except OSError:
                        break
            process.wait(timeout=2)
            while select.select([master], [], [], .05)[0]:
                try:
                    chunk = os.read(master, 8192)
                    if not chunk:
                        break
                    output += chunk
                except OSError:
                    break
            return output.decode(errors="replace")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_escape_refuses_without_enter(self):
        self.assertIn("RESULT 0", self.choose(b"\x1b"))

    def test_arrows_select_remember(self):
        self.assertIn("RESULT 2", self.choose(b"\x1b[B\r"))

    def test_number_three_refuses(self):
        self.assertIn("RESULT 0", self.choose(b"3"))

    def test_enter_approves_once(self):
        self.assertIn("RESULT 1", self.choose(b"\r"))

    def test_busy_composer_queues_unicode_and_restores_terminal(self):
        body = """import time, termios
before = termios.tcgetattr(0)
m['SESSION']['interactive'] = True
with m['Spinner']():
    time.sleep(0.7)
print('RESULT', m['SESSION'].get('queued'), (before[3] & (termios.ECHO | termios.ICANON | termios.ISIG)) == (termios.tcgetattr(0)[3] & (termios.ECHO | termios.ICANON | termios.ISIG)), flush=True)
"""
        output = self.choose("zażółć 世界\r".encode(), body, "esc przerywa".encode())
        self.assertIn("RESULT ['zażółć 世界'] True", output)
        self.assertNotIn("Traceback", output)

    def test_busy_escape_restores_terminal(self):
        body = """import time, termios
before = termios.tcgetattr(0)
m['SESSION']['interactive'] = True
try:
    with m['Spinner']():
        time.sleep(3)
except KeyboardInterrupt:
    print('RESULT interrupted', (before[3] & (termios.ECHO | termios.ICANON | termios.ISIG)) == (termios.tcgetattr(0)[3] & (termios.ECHO | termios.ICANON | termios.ISIG)), flush=True)
"""
        self.assertIn("RESULT interrupted True", self.choose(b"\x1b", body, "esc przerywa".encode()))

    def test_shift_tab_preserves_composer_text(self):
        body = """m['_interactive_input'].__globals__['current_model'] = lambda _: 'test-model'
value = m['_interactive_input']()
print('RESULT', value, m['_interactive_input'].__globals__['_INPUT_MODE'], flush=True)
"""
        output = self.choose(b"hello\x1b[Z\r", body, "Napisz".encode())
        self.assertIn("RESULT hello auto", output)


if __name__ == "__main__":
    unittest.main()
