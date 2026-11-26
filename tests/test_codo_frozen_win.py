"""Codo jako pojedynczy plik (PyInstaller, codo-windows-x64.exe) i dwuklik na Windows (26.11.2026).
Offline, bez backendu i bez modeli."""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-test-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
os.environ.setdefault("CODO_LANG", "pl")
loader = importlib.machinery.SourceFileLoader(
    "codo_frozen_win", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class Frozen(unittest.TestCase):
    def test_frozen_exe_restarts_itself_without_script(self):
        with patch.object(cli, "FROZEN", True), patch.object(sys, "executable", "C:\\Codo\\codo.exe"):
            self.assertEqual(cli._self_cmd("C:\\tmp\\_MEI\\codo_main.py"), ["C:\\Codo\\codo.exe"])
            self.assertEqual(cli._self_cmd(), ["C:\\Codo\\codo.exe"])

    def test_script_restarts_with_python_and_script(self):
        with patch.object(cli, "FROZEN", False):
            self.assertEqual(cli._self_cmd("/x/codo"), [sys.executable, "/x/codo"])

    def test_python_for_foreign_code_is_not_the_exe(self):
        with patch.object(cli, "FROZEN", True), patch.object(sys, "executable", "/opt/codo/codo-linux-x64"):
            self.assertNotEqual(cli._python_cmd(), "/opt/codo/codo-linux-x64")
        with patch.object(cli, "FROZEN", False):
            self.assertEqual(cli._python_cmd(), sys.executable)

    def test_double_click_only_on_windows(self):
        with patch.object(cli, "IS_WIN", False):
            self.assertFalse(cli._win_own_console())


class OknoAplikacji(unittest.TestCase):
    def test_okno_z_osobnym_profilem(self):
        cmd = cli._app_window_cmd("C:\\Edge\\msedge.exe", "http://127.0.0.1:5000/?t=x")
        self.assertEqual(cmd[0], "C:\\Edge\\msedge.exe")
        self.assertIn("--app=http://127.0.0.1:5000/?t=x", cmd)
        self.assertTrue(any(a.startswith("--user-data-dir=") and "okno" in a for a in cmd))

    def test_mac_i_wymuszona_karta_bez_okna(self):
        with patch.object(cli, "IS_WIN", False), patch.object(cli.sys, "platform", "darwin"):
            self.assertIsNone(cli._app_window_browser())
        with patch.dict(os.environ, {"CODO_UI_TAB": "1"}):
            self.assertIsNone(cli._app_window_browser())
        with patch.object(cli, "_app_window_browser", return_value=None):
            self.assertFalse(cli._open_app_window("http://127.0.0.1:1/"))

    def test_teksty_okna_po_angielsku(self):
        with patch.object(cli, "ui_lang", return_value="en"):
            self.assertTrue(cli._L("Folder projektów: {0}").startswith("Projects"))


class Kompilacja(unittest.TestCase):
    def test_brak_ostrzezen_skladni(self):
        # 0.29.1: "napis" (f"...") bez + robił z napisu wywołanie i `codo link` padał na Windows
        import warnings
        src = Path(loader.path).read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(src, "doma", "exec")


if __name__ == "__main__":
    unittest.main()
