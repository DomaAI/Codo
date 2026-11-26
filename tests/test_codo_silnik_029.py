"""Codo 0.29.0: naprawy z przeglądu silnika (26.11.2026). Offline, bez backendu i bez modeli."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["CODO_MADDLABS_DIRECT"] = "1"
os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-test-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
os.environ.setdefault("CODO_LANG", "pl")
loader = importlib.machinery.SourceFileLoader(
    "codo_silnik_029", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class InFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()


class FileTools(InFolder):
    def test_insert_after_last_line_without_newline(self):
        Path("f.txt").write_bytes(b"a\nb")
        cli.t_insert_lines({"path": "f.txt", "line": 2, "new_string": "c"})
        self.assertEqual(Path("f.txt").read_bytes(), b"a\nb\nc\n")

    def test_replace_last_line_keeps_missing_final_newline(self):
        Path("f.txt").write_bytes(b"a\nb")
        cli.t_replace_lines({"path": "f.txt", "start_line": 2, "new_string": "B"})
        self.assertEqual(Path("f.txt").read_bytes(), b"a\nB")

    def test_line_numbers_match_grep_with_form_feed(self):
        Path("f.py").write_text("a=1\n\x0c\nb=2\ntarget=3\n")
        self.assertIn("4\ttarget=3", cli._read_one("f.py", 1, 50))
        cli.t_replace_lines({"path": "f.py", "start_line": 4, "new_string": "target=4"})
        self.assertEqual(Path("f.py").read_text(), "a=1\n\x0c\nb=2\ntarget=4\n")

    def test_read_past_end_says_how_long(self):
        Path("f.txt").write_text("a\nb\n")
        self.assertIn("ma 2 linii", cli._read_one("f.txt", 10, 5))

    def test_edit_mixed_line_endings(self):
        Path("f.txt").write_bytes(b"x\r\ny\r\nz\n")
        out = cli.t_edit_file({"path": "f.txt", "old_string": "x\ny", "new_string": "X\nY"})
        self.assertFalse(out.startswith("BŁĄD"), out)
        self.assertEqual(Path("f.txt").read_bytes(), b"X\r\nY\r\nz\n")

    def test_edit_empty_old_and_replace_all(self):
        Path("f.txt").write_text("a a a\n")
        self.assertIn("pusty old_string", cli.t_edit_file({"path": "f.txt", "old_string": "", "new_string": "x"}))
        self.assertIn("replace_all", cli.t_edit_file({"path": "f.txt", "old_string": "a", "new_string": "b"}))
        cli.t_edit_file({"path": "f.txt", "old_string": "a", "new_string": "b", "replace_all": True})
        self.assertEqual(Path("f.txt").read_text(), "b b b\n")

    def test_edit_near_miss_points_at_lines(self):
        Path("f.py").write_text("def f():\n    return 1\n")
        out = cli.t_edit_file({"path": "f.py", "old_string": "def f():\n  return 1", "new_string": "x"})
        self.assertIn("liniach 1-2", out)

    def test_delete_symlink_keeps_target(self):
        Path("real.txt").write_text("keep")
        os.symlink("real.txt", "lnk")
        out = cli.t_file_op({"action": "delete", "path": "lnk"}, auto_yes=True)
        self.assertFalse(out.startswith("BŁĄD"), out)
        self.assertEqual(Path("real.txt").read_text(), "keep")
        self.assertFalse(os.path.lexists("lnk"))

    def test_tilde_path_never_creates_tilde_folder(self):
        with self.assertRaises(ValueError):
            cli._safe_path("~/x.txt")
        self.assertFalse(Path("~").exists())

    def test_atomic_write_keeps_mode(self):
        Path("run.sh").write_text("echo 1\n")
        os.chmod("run.sh", 0o755)
        cli.t_edit_file({"path": "run.sh", "old_string": "1", "new_string": "2"})
        self.assertEqual(os.stat("run.sh").st_mode & 0o777, 0o755)
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith(".codo-tmp")], [])

    def test_doma_folder_is_git_ignored_and_backups_pruned(self):
        Path("f.txt").write_text("0\n")
        for i in range(cli._BACKUPS_KEEP + 5):
            cli._backup(self.root / "f.txt")
        self.assertIn("*", (self.root / ".doma" / ".gitignore").read_text())
        _, baks = cli._backups_for(self.root / "f.txt")
        self.assertLessEqual(len(baks), cli._BACKUPS_KEEP)

    def test_find_files_skips_build_folders(self):
        (self.root / "target" / "x").mkdir(parents=True)
        (self.root / "target" / "x" / "a.toml").write_text("")
        Path("Cargo.toml").write_text("")
        self.assertEqual(cli.t_find_files({"pattern": "*.toml"}).strip(), "Cargo.toml")

    def test_grep_finds_hidden_but_not_env(self):
        (self.root / ".github").mkdir()
        (self.root / ".github" / "ci.yml").write_text("needle\n")
        Path(".env").write_text("needle=secret\n")
        out = cli.t_grep({"pattern": "needle"})
        self.assertIn("ci.yml", out)
        self.assertNotIn("secret", out)


class PanelJail(InFolder):
    def test_panel_tools_stay_in_project_outside_serve(self):
        self.assertFalse(cli._SERVE["on"])
        home_file = str(Path.home() / "codo-test-nie-istnieje.py")
        self.assertTrue(cli.t_write_text({"path": home_file, "content": "x"}).startswith("BŁĄD"))
        self.assertFalse(Path(home_file).exists())
        names = {t["function"]["name"] for t in cli.enabled_tools()}
        self.assertFalse(names & cli._PANEL_TOOLS)

    def test_write_text_keeps_encoding(self):
        Path("a.txt").write_bytes("zażółć\n".encode("cp1250"))
        cli.t_write_text({"path": "a.txt", "content": cli.t_read_text({"path": "a.txt"}).replace("zażółć", "gęśla")})
        self.assertEqual(Path("a.txt").read_bytes(), "gęśla\n".encode("cp1250"))


class Loop(unittest.TestCase):
    def test_clip_middle_keeps_the_end(self):
        text = "\n".join(str(i) for i in range(20000)) + "\nFINAL_ERROR"
        out = cli._clip_middle(text, 24000)
        self.assertLessEqual(len(out), 24000)
        self.assertTrue(out.endswith("FINAL_ERROR"))
        self.assertIn("pominięto", out)

    def test_missing_and_duplicate_tool_ids_are_fixed(self):
        calls = [{"function": {"name": "list_dir", "arguments": "{}"}},
                 {"id": "", "function": {"name": "list_dir", "arguments": "{}"}}]
        responses = [{"message": {"role": "assistant", "tool_calls": calls}},
                     {"message": {"role": "assistant", "content": "OK"}}]
        messages = [{"role": "user", "content": "task"}]
        with patch.object(cli, "api_step", side_effect=responses), patch.object(cli, "run_tool", return_value="ok"), \
                patch.object(cli, "current_model", return_value=None), contextlib.redirect_stdout(io.StringIO()):
            cli.agent_turn({}, messages, None, False)
        ids = [tc["id"] for tc in next(m for m in messages if m.get("tool_calls"))["tool_calls"]]
        self.assertEqual(len(set(ids)), 2)
        answered = [m["tool_call_id"] for m in messages if m.get("role") == "tool"]
        self.assertEqual(sorted(ids), sorted(answered))

    def test_non_object_arguments_get_an_answer(self):
        responses = [{"message": {"role": "assistant", "tool_calls": [
                        {"id": "1", "function": {"name": "read_file", "arguments": "null"}}]}},
                     {"message": {"role": "assistant", "content": "OK"}}]
        messages = [{"role": "user", "content": "task"}]
        with patch.object(cli, "api_step", side_effect=responses), patch.object(cli, "current_model", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cli.agent_turn({}, messages, None, False))
        self.assertTrue(any(m.get("role") == "tool" and m.get("tool_call_id") == "1" for m in messages))

    def test_crash_in_tool_still_answers_every_call(self):
        responses = [{"message": {"role": "assistant", "tool_calls": [
            {"id": "a", "function": {"name": "list_dir", "arguments": "{}"}},
            {"id": "b", "function": {"name": "list_dir", "arguments": "{}"}}]}}]
        messages = [{"role": "user", "content": "task"}]
        with patch.object(cli, "api_step", side_effect=responses), patch.object(cli, "current_model", return_value=None), \
                patch.object(cli, "run_tool", side_effect=RuntimeError("boom")), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                cli.agent_turn({}, messages, None, False)
        self.assertEqual(sorted(m["tool_call_id"] for m in messages if m.get("role") == "tool"), ["a", "b"])

    def test_cut_answer_continues(self):
        responses = [{"message": {"role": "assistant", "content": "część pierwsza"}, "finish_reason": "length"},
                     {"message": {"role": "assistant", "content": "i koniec"}}]
        messages = [{"role": "user", "content": "task"}]
        with patch.object(cli, "api_step", side_effect=responses), patch.object(cli, "current_model", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cli.agent_turn({}, messages, None, False))
        self.assertEqual(messages[-1]["content"], "i koniec")

    def test_parallel_reads_run_together(self):
        import threading
        import time
        active, peak = [0], [0]
        lock = threading.Lock()

        def slow(name, args, auto_yes):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.2)
            with lock:
                active[0] -= 1
            return "ok"
        calls = [{"id": str(i), "function": {"name": "grep", "arguments": "{\"pattern\": \"x\"}"}} for i in range(4)]
        with patch.object(cli, "run_tool", side_effect=slow):
            out = cli._parallel_reads(calls, "ask")
        self.assertEqual(len(out), 4)
        self.assertGreater(peak[0], 1)

    def test_old_write_arguments_are_shrunk(self):
        big = "x" * 50_000
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "task"},
                    {"role": "assistant", "tool_calls": [{"id": "1", "function": {
                        "name": "write_file", "arguments": json.dumps({"path": "a.txt", "content": big})}}]},
                    {"role": "tool", "tool_call_id": "1", "content": "ok"}]
        messages += [{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}] * 6
        with patch.object(cli, "_CTX_BUDGET", 20_000):
            cli.compact_history(messages)
        args = json.loads(messages[2]["tool_calls"][0]["function"]["arguments"]) if messages[2].get("tool_calls") else {}
        self.assertTrue(not args or "już zapisane" in args["content"])
        self.assertLess(sum(cli._content_len(m) for m in messages), 20_000)

    def test_retry_honours_overload(self):
        attempts = []

        def call(p):
            attempts.append(1)
            if len(attempts) < 3:
                raise cli.ApiError(429, "slow down", {"_retry_after": "0"})
            return {"ok": True}
        with patch("time.sleep"):
            self.assertEqual(cli._with_retry(call, {}), {"ok": True})
        self.assertEqual(len(attempts), 3)

    def test_quote_authorizes_only_named_packages(self):
        msgs = [{"role": "user", "content": "zainstaluj requests"}]
        ok = {"user_authorization": "zainstaluj requests", "packages": ["requests"]}
        self.assertTrue(cli._authorized_install_call("install", ok, msgs))
        self.assertFalse(cli._authorized_install_call("run_command", dict(ok, command="rm -rf /"), msgs))
        cli.SESSION["marathon"] = True
        try:
            self.assertFalse(cli._authorized_install_call("install", ok, msgs))
        finally:
            cli.SESSION.pop("marathon", None)


class Settings(unittest.TestCase):
    def test_save_is_atomic_and_leaves_no_temp(self):
        cli.save_settings({"a": 1})
        cli.save_settings({"a": 2, "b": "ż"})
        self.assertEqual(cli.load_settings(), {"a": 2, "b": "ż"})
        self.assertEqual([p.name for p in cli.CONFIG_DIR.iterdir() if p.name.endswith(".tmp")], [])

    def test_single_pid_alive(self):
        self.assertTrue(cli._pid_alive(os.getpid()))
        self.assertTrue(cli._pid_alive(str(os.getpid())))
        self.assertFalse(cli._pid_alive("x"))
        self.assertFalse(cli._pid_alive(0))


class ReviewFixes(unittest.TestCase):
    """Błędy znalezione w przeglądzie 0.29.0 przed wydaniem."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.prev)
        self.tmp.cleanup()

    def test_reads_after_a_write_see_the_new_content(self):
        calls = [{"id": "w", "function": {"name": "write_file", "arguments": "{}"}},
                 {"id": "r", "function": {"name": "read_file", "arguments": "{}"}},
                 {"id": "g", "function": {"name": "grep", "arguments": "{}"}}]
        self.assertEqual(cli._parallel_reads(calls, "ask"), {})

    def test_scoped_and_url_packages_always_ask(self):
        msgs = [{"role": "user", "content": "zainstaluj requests, prosze."}]
        q = "zainstaluj requests, prosze."
        for bad in (["requests", "@evil/stealer"], ["requests @ https://evil/x.whl"], ["--index-url=x"], ["@"]):
            self.assertFalse(cli._authorized_install_call("install", {"user_authorization": q, "packages": bad}, msgs), bad)
        msgs = [{"role": "user", "content": "zainstaluj @types/node i react@18"}]
        ok = {"user_authorization": "zainstaluj @types/node i react@18", "packages": ["@types/node", "react@18"]}
        self.assertTrue(cli._authorized_install_call("install", ok, msgs))

    def test_restore_oldest_backup_with_full_history(self):
        Path("a.txt").write_text("teraz\n")
        bdir = Path(".doma/backups")
        bdir.mkdir(parents=True)
        for i in range(cli._BACKUPS_KEEP):
            (bdir / f"a.txt.20260101-0000{i:02d}.bak").write_text(f"{i}\n")
        out = cli.t_restore({"path": "a.txt", "version": "20260101-000000"})
        self.assertTrue(out.startswith("Przywrócono"), out)
        self.assertEqual(Path("a.txt").read_text(), "0\n")

    def test_continue_note_never_replaces_the_goal(self):
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "Cel: GOAL"},
                    {"role": "assistant", "content": "uciete"},
                    {"role": "user", "_codo_continue": True, "content": "(kontynuuj)"}]
        for i in range(100):
            messages += [{"role": "assistant", "tool_calls": [{"id": str(i), "function": {"name": "list_dir", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": str(i), "content": "x" * 3000}]
        with patch.object(cli, "_CTX_BUDGET", 50_000):
            cli.compact_history(messages)
        self.assertTrue(any("GOAL" in str(m.get("content")) for m in messages))


if __name__ == "__main__":
    unittest.main()
