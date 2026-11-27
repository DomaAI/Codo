"""Codo 21.11.2026: Gmail i Kalendarz przez konektory DomaAI (/cli/google), Dysk Google
jako folder aplikacji Dysk Google na Macu, serwer MCP `codo mcp` dla Codexa i Claude Code.
Bez sieci: api_call podmienione, Dysk to folder tymczasowy."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_codo_konta_agenci as base   # noqa: E402

cli = base.cli
SCRIPT = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))


class GoogleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.dysk = self.home / "Library/CloudStorage/GoogleDrive-ania@example.com/My Drive"
        (self.dysk / "Umowy").mkdir(parents=True)
        (self.dysk / "Umowy" / "umowa-najmu.txt").write_text("Umowa najmu lokalu", encoding="utf-8")
        self.proj = self.home / "projekt"
        self.proj.mkdir()
        (self.proj / "raport.txt").write_text("raport", encoding="utf-8")
        self.cwd = os.getcwd()
        os.chdir(self.proj)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def _wywolania(self, odpowiedzi):
        calls = []

        def fake(creds, path, body, method="POST"):
            calls.append((path, json.loads(json.dumps(body))))
            return odpowiedzi.pop(0)
        return calls, fake

    def test_bramka_pyta_i_po_zgodzie_wysyla(self):
        calls, fake = self._wywolania([{"wynik": "⛔", "blad": True, "bramka": "Wysłać mail do a@b.pl?"},
                                       {"wynik": '{"ok": true}', "blad": False, "bramka": ""}])
        pytania = []
        with patch.object(cli, "api_call", fake), patch.object(cli, "load_device", lambda: {"id": 1}):
            out = cli.google_wywolaj("gmail_wyslij", {"do": "a@b.pl", "zgoda_usera": True},
                                     ask=lambda q: pytania.append(q) or True)
        self.assertEqual(out, '{"ok": true}')
        self.assertEqual(pytania, ["Wysłać mail do a@b.pl?"])
        self.assertNotIn("zgoda_usera", calls[0][1]["args"])          # flaga modelu odpada
        self.assertNotIn("zgoda", calls[0][1])
        self.assertTrue(calls[1][1]["zgoda"])                          # zgoda tylko z karty
        self.assertEqual(calls[0][1]["sesja"], calls[1][1]["sesja"])

    def test_odmowa_nic_nie_wysyla(self):
        calls, fake = self._wywolania([{"wynik": "⛔", "blad": True, "bramka": "Usunąć 2 wydarzenia?"}])
        with patch.object(cli, "api_call", fake), patch.object(cli, "load_device", lambda: {"id": 1}):
            out = cli.google_wywolaj("gkalendarz_zmien", {"szukaj": "stand-up", "akcja": "usun"}, ask=lambda q: False)
        self.assertEqual(len(calls), 1)
        self.assertIn("NIE zgodził", out)

    def test_bez_konta_i_nieznane_narzedzie(self):
        with patch.object(cli, "load_device", lambda: None), patch.object(cli, "load_creds", lambda: None):
            self.assertIn("nie jest zalogowane", cli.google_wywolaj("gmail_szukaj", {}))
        self.assertIn("nie ma narzędzia", cli.google_wywolaj("gmail_usun_konto", {}))

    def test_zalacznik_zapisany_w_projekcie(self):
        import base64
        _, fake = self._wywolania([{"nazwa": "../faktura.pdf", "rozmiar": 3, "dane_b64": base64.b64encode(b"PDF").decode()}])
        with patch.object(cli, "api_call", fake), patch.object(cli, "load_device", lambda: {"id": 1}):
            out = json.loads(cli.google_wywolaj("gmail_zalacznik", {"id": "18f2abcd", "zalacznik_id": "ANGjdJ8"}))
        zapis = self.proj / out["plik"]
        self.assertEqual(zapis.read_bytes(), b"PDF")
        self.assertEqual(zapis.parent, self.proj / "zalaczniki")

    def test_dysk_szukaj_czytaj_i_wiezienie(self):
        with patch.object(cli.Path, "home", lambda: self.home):
            wynik = json.loads(cli.t_dysk({"akcja": "szukaj", "fraza": "najmu"}))
            self.assertEqual(wynik["wyniki"], ["Umowy/umowa-najmu.txt"])
            self.assertEqual(cli.t_dysk({"akcja": "czytaj", "plik": "Umowy/umowa-najmu.txt"}), "Umowa najmu lokalu")
            self.assertIn("poza Dyskiem", cli.t_dysk({"akcja": "czytaj", "plik": "../../../../projekt/raport.txt"}))
            self.assertIn("nie zgodził", cli.t_dysk({"akcja": "zapisz", "z_projektu": "raport.txt", "folder": "Umowy"},
                                                    ask=lambda q: False))
            self.assertFalse((self.dysk / "Umowy" / "raport.txt").exists())
            out = json.loads(cli.t_dysk({"akcja": "zapisz", "z_projektu": "raport.txt", "folder": "Umowy"}, ask=lambda q: True))
            self.assertEqual(out["zapisano"], "Umowy/raport.txt")
            self.assertIn("folderze projektu", cli.t_dysk({"akcja": "zapisz", "z_projektu": "../../etc/hosts"}, ask=lambda q: True))

    def test_bez_dysku_podpowiada_instalacje(self):
        with patch.object(cli.Path, "home", lambda: self.home / "nic"):
            self.assertIn("nie jest zainstalowany", cli.t_dysk({"akcja": "lista"}))

    def test_agenci_dostaja_serwer_mcp(self):
        with patch.object(cli, "_mcp_wlaczony", lambda: True), patch.object(cli, "load_settings", lambda: {}):
            argv, _ = cli._agent_argv("codex", "/bin/codex", "ask", False, None, "hej")
            self.assertTrue(any(a.startswith("mcp_servers.codo.command=") for a in argv))
            self.assertLess(argv.index("-c"), argv.index("-"))
            argv, _ = cli._agent_argv("claude", "/bin/claude", "ask", False, None, "hej")
            cfg = json.loads(argv[argv.index("--mcp-config") + 1])
            self.assertEqual(cfg["mcpServers"]["codo"]["args"][-1], "mcp")
            self.assertIn("mcp__codo", argv)
        with patch.object(cli, "_mcp_wlaczony", lambda: False), patch.object(cli, "load_settings", lambda: {}):
            argv, _ = cli._agent_argv("codex", "/bin/codex", "ask", False, None, "hej")
            self.assertFalse(any("mcp_servers" in a for a in argv))

    def test_serwer_mcp_po_protokole(self):
        wejscie = "\n".join(json.dumps(m) for m in (
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "dysk", "arguments": {"akcja": "lista"}}},
        )) + "\n"
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "DOMA_CONFIG_DIR": str(self.home / "cfg")}   # Windows: Path.home() = USERPROFILE
        r = subprocess.run([sys.executable, SCRIPT, "mcp"], input=wejscie, capture_output=True, text=True, env=env, timeout=60, encoding="utf-8")
        linie = [json.loads(x) for x in r.stdout.splitlines()]
        self.assertEqual([m["id"] for m in linie], [1, 2, 3])
        nazwy = [t["name"] for t in linie[1]["result"]["tools"]]
        self.assertIn("gmail_wyslij", nazwy)
        self.assertIn("dysk", nazwy)
        self.assertIn("Umowy/", linie[2]["result"]["content"][0]["text"])


class KonektoryTests(unittest.TestCase):
    def setUp(self):
        cli._KONEKTORY_CACHE.update(t=0.0, dane=None)

    def test_lista_dla_modelu_i_wywolanie_ze_zgoda(self):
        stan = {"konektory": [{"id": "slack", "nazwa": "Slack", "polaczony": True}],
                "narzedzia": [{"nazwa": "slack_wyslij", "konektor": "slack", "opis": "Wysyła", "tryb": "zapytaj",
                               "schemat": {"type": "object", "properties": {"kanal": {}, "tekst": {}}, "required": ["kanal"]}}]}
        calls = []

        def fake(creds, path, body, method="POST"):
            calls.append((method, path, json.loads(json.dumps(body))))
            if path == "/cli/konektory":
                return stan
            if body.get("zgoda"):
                return {"wynik": '{"ok": true}', "blad": False, "bramka": ""}
            return {"wynik": "⛔", "blad": True, "bramka": "Slack: Pisać. kanal: #ogolny"}
        with patch.object(cli, "api_call", fake), patch.object(cli, "load_device", lambda: {"id": 1}), \
                patch.object(cli, "_save_private_json", lambda *a: None):
            lista = cli.konektor_wywolaj("", {})
            self.assertIn("slack_wyslij (slack) [karta zgody]", lista)
            self.assertIn("kanal*", lista)
            pytania = []
            out = cli.konektor_wywolaj("slack_wyslij", {"kanal": "#ogolny", "zgoda_usera": True},
                                       ask=lambda q: pytania.append(q) or True)
            self.assertEqual(out, '{"ok": true}')
            self.assertEqual(pytania, ["Slack: Pisać. kanal: #ogolny"])
            wyw = [c for c in calls if c[1] == "/cli/konektory/narzedzie"]
            self.assertNotIn("zgoda_usera", wyw[0][2]["args"])
            self.assertTrue(wyw[1][2]["zgoda"])
            calls.clear()
            self.assertIn("NIE zgodził", cli.konektor_wywolaj("slack_wyslij", {"kanal": "#x"}, ask=lambda q: False))
            self.assertEqual(len([c for c in calls if c[1] == "/cli/konektory/narzedzie"]), 1)

    def test_polacz_i_odlacz_ida_do_tras_konektorow(self):
        calls = []

        def fake(creds, path, body, method="POST"):
            calls.append((method, path, body))
            return {"url": "https://bymadd.pl/konektory/notion/polacz?bilet=x"}
        with patch.object(cli, "api_call", fake):
            self.assertIn("url", cli.konektor_polacz("notion"))
            cli.konektor_polacz("todoist", pola={"token": "abc"})
            cli.konektor_odlacz("slack/../x")
        self.assertEqual(calls[0][1], "/cli/konektory/notion/polacz")
        self.assertEqual(calls[1][1:], ("/cli/konektory/todoist/klucz", {"pola": {"token": "abc"}}))
        self.assertEqual(calls[2][:2], ("POST", "/cli/konektory/slackx/odlacz"))


if __name__ == "__main__":
    unittest.main()
