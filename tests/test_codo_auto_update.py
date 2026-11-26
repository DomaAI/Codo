"""Codo 0.29.2: aktualizacje same, dla skryptu i dla pojedynczego pliku (26.11.2026). Offline."""
import hashlib
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
os.environ.pop("CI", None)
loader = importlib.machinery.SourceFileLoader(
    "codo_auto_update", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class Pojedynczy(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.exe = self.dir / "codo-linux-x64"
        self.exe.write_bytes(b"stary")

    def _sums(self, data, name="codo-linux-x64"):
        return f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()

    def test_ten_sam_plik_nic_nie_robi(self):
        def dl(url, timeout=0):
            return self._sums(b"stary")
        with patch.object(cli, "FROZEN", True), patch.object(cli, "_update_target", return_value=self.exe), \
                patch.object(cli, "_frozen_asset_name", return_value="codo-linux-x64"), patch.object(cli, "_download", dl):
            self.assertEqual(cli._fetch_update(), (b"", None))

    def test_nowy_plik_sprawdzony_i_podmieniony(self):
        def dl(url, timeout=0):
            return self._sums(b"nowy") if url.endswith("SHA256SUMS") else b"nowy"
        with patch.object(cli, "FROZEN", True), patch.object(cli, "IS_WIN", False), \
                patch.object(cli, "_update_target", return_value=self.exe), \
                patch.object(cli, "_frozen_asset_name", return_value="codo-linux-x64"), patch.object(cli, "_download", dl):
            data, _ = cli._fetch_update()
            cli._install_update(data)
        self.assertEqual(self.exe.read_bytes(), b"nowy")
        self.assertTrue(os.access(self.exe, os.X_OK))

    def test_zla_suma_nie_podmienia(self):
        def dl(url, timeout=0):
            return self._sums(b"inny") if url.endswith("SHA256SUMS") else b"podrobiony"
        with patch.object(cli, "FROZEN", True), patch.object(cli, "_update_target", return_value=self.exe), \
                patch.object(cli, "_frozen_asset_name", return_value="codo-linux-x64"), patch.object(cli, "_download", dl):
            with self.assertRaises(RuntimeError):
                cli._fetch_update()
        self.assertEqual(self.exe.read_bytes(), b"stary")


class Zgoda(unittest.TestCase):
    def test_wylaczone_w_aplikacji_na_maca_i_w_repo(self):
        for p in ("/Applications/Codo.app/Contents/Resources/codo", "/x/doma/static/cli/doma"):
            with patch.object(cli, "_update_target", return_value=Path(p)):
                self.assertFalse(cli._auto_update_allowed())

    def test_wylaczone_zmienna_i_ustawieniem(self):
        with patch.dict(os.environ, {"CODO_NO_AUTO_UPDATE": "1"}):
            self.assertFalse(cli._auto_update_allowed())
        with patch.object(cli, "load_settings", return_value={"auto_update": False}):
            self.assertFalse(cli._auto_update_allowed())

    def test_komunikat_po_aktualizacji(self):
        saved = {}
        with patch.object(cli, "load_settings", return_value={"auto_updated_to": cli.VERSION}), \
                patch.object(cli, "save_settings", side_effect=lambda st: saved.update(st)), \
                patch.object(cli, "_auto_update_allowed", return_value=False), \
                patch("builtins.print") as pr:
            cli.auto_update_start()
        self.assertIn(cli.VERSION, str(pr.call_args))
        self.assertNotIn("auto_updated_to", saved)


if __name__ == "__main__":
    unittest.main()
