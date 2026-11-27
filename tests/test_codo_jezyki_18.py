"""Codo na Maca w 18 językach (26.11.2026): CODO_LANG spoza pl/en → napisy CLI po angielsku,
model odpowiada w języku okna. Offline, bez backendu i bez modeli."""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DOMA_CONFIG_DIR"] = tempfile.mkdtemp(prefix="codo-test-cfg-")
os.environ["DOMA_API_URL"] = "http://127.0.0.1:9"
os.environ["DOMA_NO_SYNC"] = "1"
loader = importlib.machinery.SourceFileLoader(
    "codo_jezyki_18", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class ReplyLanguage(unittest.TestCase):
    def lang(self, code):
        cli._LANG[0] = ""
        return patch.dict(os.environ, {"CODO_LANG": code})

    def tearDown(self):
        cli._LANG[0] = ""

    def test_window_language_goes_to_the_model(self):
        for code, name in [("de", "German"), ("pt-BR", "Brazilian Portuguese"), ("zh-Hans", "Simplified Chinese"),
                           ("ja", "Japanese"), ("uk", "Ukrainian")]:
            with self.lang(code):
                self.assertEqual(cli.ui_lang(), "en")
                self.assertIn(f"Reply in {name}", cli._reply_lang_line())

    def test_polish_and_english_stay_as_they_were(self):
        with self.lang("pl"):
            self.assertEqual(cli.ui_lang(), "pl")
            self.assertEqual(cli._reply_lang_line(), "")
        with self.lang("en"):
            self.assertEqual(cli.ui_lang(), "en")
            self.assertEqual(cli._reply_lang_line(), cli._REPLY_LANG_EN)

    def test_unknown_language_falls_back(self):
        with self.lang("xx"):
            self.assertEqual(cli._reply_lang_name(), "")


if __name__ == "__main__":
    unittest.main()
