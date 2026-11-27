"""Codo 20.11.2026 warsztat w oknie: most do aplikacji (terminal, przeglądarka, komputer),
licznik kontekstu, narzędzia tylko dla okna, telefon jako pilot okna. Bez sieci i bez modeli."""
import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_codo_konta_agenci as base   # noqa: E402

cli = base.cli


class _Out:
    def __init__(self):
        self.lines = []

    def write(self, s):
        for ln in s.splitlines():
            if ln.strip():
                self.lines.append(json.loads(ln))

    def flush(self):
        pass

    def of(self, kind):
        return [x for x in self.lines if x.get("type") == kind]


class WarsztatTests(unittest.TestCase):
    def setUp(self):
        self.out = _Out()
        self.saved = dict(cli._APP)
        cli._APP.update({"out": self.out, "asks": {}, "calls": {}, "n": 0})
        self.inbox, self.wake = [], threading.Event()
        cli._APP["inbox"], cli._APP["wake"] = self.inbox, self.wake
        self.app_flag = cli.SESSION.get("app")
        cli.SESSION["app"] = True

    def tearDown(self):
        cli._APP.clear()
        cli._APP.update(self.saved)
        cli.SESSION["app"] = self.app_flag

    def _reply_later(self, value, delay=0.05):
        def go():
            time.sleep(delay)
            for cid, c in list(cli._APP["calls"].items()):
                c["value"] = value
                c["event"].set()
        threading.Thread(target=go, daemon=True).start()

    def test_most_wysyla_zadanie_i_czeka_na_odpowiedz(self):
        self._reply_later({"ok": True, "tekst": "Serwer działa na porcie 5173"})
        res = cli._app_call("terminal.lista", {}, timeout=3)
        self.assertEqual(res.get("tekst"), "Serwer działa na porcie 5173")
        mosty = self.out.of("bridge")
        self.assertEqual(len(mosty), 1)
        self.assertEqual(mosty[0]["action"], "terminal.lista")

    def test_stop_przerywa_czekanie_na_okno(self):
        threading.Timer(0.3, cli._app_interrupt).start()
        t0 = time.time()
        res = cli._app_call("roj.uruchom", {"cel": "s:1"}, timeout=30)
        self.assertTrue(res.get("stopped"))
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(self.out.of("bridge_cancel")[0]["id"], self.out.of("bridge")[0]["id"])

    def test_most_bez_okna_odmawia(self):
        cli._APP["out"] = None
        res = cli._app_call("terminal.lista", {}, timeout=1)
        self.assertIn("error", res)

    def test_narzedzia_okna_tylko_w_oknie(self):
        names = {t["function"]["name"] if "function" in t else t.get("name") for t in cli.enabled_tools()}
        for n in cli._APP_ONLY_TOOLS:
            self.assertIn(n, names)
        cli._APP["out"] = None
        names = {t["function"]["name"] if "function" in t else t.get("name") for t in cli.enabled_tools()}
        for n in cli._APP_ONLY_TOOLS:
            self.assertNotIn(n, names)

    def test_licznik_kontekstu(self):
        msgs = [{"role": "system", "content": "x" * 4000}, {"role": "user", "content": "y" * 8000}]
        u = cli._context_usage(msgs, False)
        self.assertEqual(u["instrukcje"], 1000)
        self.assertEqual(u["rozmowa"], 2000)
        self.assertGreaterEqual(u["uzyte"], 3000)

    def test_telefon_wiadomosc_trafia_do_kolejki_okna(self):
        cli._remote_message({"rodzaj": "message", "tresc": {"tekst": "dodaj testy do koszyka"}})
        self.assertEqual(self.inbox, [{"type": "send", "text": "dodaj testy do koszyka", "remote": True}])
        self.assertTrue(self.wake.is_set())
        self.assertEqual(self.out.of("remote")[0]["tekst"], "dodaj testy do koszyka")

    def test_telefon_zgoda_zawsze_dziala_jednorazowo(self):
        got = {}

        def ask():
            got["v"] = cli._app_ask("Uruchomić npm test?", "npm test", "", True)
        t = threading.Thread(target=ask, daemon=True)
        t.start()
        for _ in range(50):
            if cli._APP["asks"]:
                break
            time.sleep(0.02)
        cli._remote_message({"rodzaj": "answer", "tresc": {"wybor": 2}})
        t.join(3)
        self.assertEqual(got.get("v"), 1)
        done = self.out.of("ask_done")
        self.assertEqual(done[0]["value"], 1)
        self.assertTrue(done[0]["zdalnie"])

    def test_telefon_stop_zamyka_zgody(self):
        got = {}

        def ask():
            got["v"] = cli._app_ask("Usunąć plik?", "rm a.txt", "", False)
        t = threading.Thread(target=ask, daemon=True)
        t.start()
        for _ in range(50):
            if cli._APP["asks"]:
                break
            time.sleep(0.02)
        cli._remote_message({"rodzaj": "interrupt", "tresc": {}})
        t.join(3)
        self.assertEqual(got.get("v"), 0)
        self.assertEqual(len(self.out.of("remote_stop")), 1)

    def test_przegladarka_obcy_adres_pyta_lokalny_nie(self):
        for u in ("http://localhost:5173", "127.0.0.1:3000/koszyk", "http://app.localhost", "file:///tmp/a.html", ""):
            self.assertTrue(cli._lokalny_url(u), u)
        for u in ("https://example.com", "http://192.168.1.5:8080", "bank.pl/logowanie"):
            self.assertFalse(cli._lokalny_url(u), u)
        pytania = []
        orig = cli.confirm_action
        cli.confirm_action = lambda *a, **k: (pytania.append(a[0]) or False)
        try:
            r = cli.t_przegladarka({"akcja": "otworz", "url": "https://example.com"})
        finally:
            cli.confirm_action = orig
        self.assertTrue(r.startswith("ODRZUCONE"))
        self.assertEqual(len(pytania), 1)
        self.assertEqual(self.out.of("bridge"), [])


class KsztaltAgentaTests(unittest.TestCase):
    """Kształt agenta przeżywa zamknięcie okna: app-server na czystym katalogu konfiguracji, bez konta."""

    def _serwer(self, cfg, wiadomosci, czekaj_na):
        """Wysyła wiadomości i czyta odpowiedzi, aż przyjdzie `czekaj_na` (stdin zostaje otwarty, jak w oknie)."""
        import subprocess
        env = dict(os.environ, DOMA_CONFIG_DIR=cfg, DOMA_NO_SYNC="1", CODO_NO_HISTORY="1", HOME=cfg)
        p = subprocess.Popen([sys.executable, str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")), "app-server"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, env=env, cwd=cfg)
        for m in wiadomosci:
            p.stdin.write(json.dumps(m) + "\n")
        p.stdin.flush()
        out, koniec = [], time.time() + 40
        try:
            while time.time() < koniec:
                ln = p.stdout.readline()
                if not ln:
                    break
                if ln.startswith("{"):
                    out.append(json.loads(ln))
                    if out[-1].get("type") == czekaj_na:
                        break
        finally:
            p.stdin.write(json.dumps({"type": "quit"}) + "\n")
            p.stdin.close()
            p.wait(20)
        return out

    def test_ksztalt_zostaje_po_ponownym_uruchomieniu(self):
        import tempfile
        with tempfile.TemporaryDirectory() as cfg:
            self._serwer(cfg, [{"type": "agent_create", "name": "Kuba", "color": "#7C5CFF", "shape": "kula"},
                               {"type": "agent_shape", "shape": "kostka"}, {"type": "status"}], "status")
            st = json.loads(Path(cfg, "settings.json").read_text())
            self.assertEqual(st.get("agent_ksztalt"), "kostka")
            out = self._serwer(cfg, [{"type": "status"}], "status")
            agenci = [m.get("agent") for m in out if m.get("type") == "status" and m.get("agent")]
            self.assertTrue(agenci)
            self.assertEqual(agenci[-1]["shape"], "kostka")
            self.assertEqual(agenci[-1]["name"], "Kuba")


class ZapisAgentaPrzyBledzieSerweraTests(unittest.TestCase):
    """24.11.2026: błąd PUT /agent/profil wywracał app-server, a okno kręciło „Zapisuję…” bez końca.
    Teraz zapis kończy się zawsze: przy błędzie serwera agent zostaje na tym Macu, silnik żyje dalej."""

    def test_blad_serwera_zapisuje_lokalnie_i_silnik_zyje(self):
        import subprocess
        import tempfile
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _odp(self, kod, cialo):
                data = json.dumps(cialo).encode()
                self.send_response(kod)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._odp(400, {"detail": "zly profil"})

            def do_GET(self):
                self._odp(404, {"detail": "brak"})

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                self._odp(404, {"detail": "brak"})

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as cfg:
                Path(cfg, "credentials.json").write_text(json.dumps({"access_token": "t", "refresh_token": "r"}))
                env = dict(os.environ, DOMA_CONFIG_DIR=cfg, DOMA_NO_SYNC="1", CODO_NO_HISTORY="1", HOME=cfg,
                           DOMA_API_URL=f"http://127.0.0.1:{srv.server_address[1]}")
                p = subprocess.Popen([sys.executable, str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")),
                                      "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, env=env, cwd=cfg)
                p.stdin.write(json.dumps({"type": "agent_create", "name": "Kuba", "color": "#7C5CFF",
                                          "shape": "kula"}) + "\n")
                p.stdin.flush()
                out, koniec, zapis, po = [], time.time() + 40, None, False
                try:
                    while time.time() < koniec:
                        ln = p.stdout.readline()
                        if not ln:
                            break
                        if not ln.startswith("{"):
                            continue
                        m = json.loads(ln)
                        if m.get("type") == "agent_saved":
                            zapis = m
                            p.stdin.write(json.dumps({"type": "status"}) + "\n")
                            p.stdin.flush()
                        elif zapis and m.get("type") == "status":
                            po = True
                            break
                finally:
                    if p.poll() is None:
                        p.stdin.write(json.dumps({"type": "quit"}) + "\n")
                        p.stdin.close()
                        p.wait(20)
                self.assertIsNotNone(zapis)
                self.assertTrue(zapis.get("ok"))
                self.assertTrue(zapis.get("lokalnie"))
                self.assertEqual((zapis.get("agent") or {}).get("name"), "Kuba")
                self.assertTrue(po, "silnik musi odpowiadać po nieudanym zapisie na serwerze")
        finally:
            srv.shutdown()


class WorkflowKanalyTests(unittest.TestCase):
    """Krok „Wyślij” w workflowie: wiadomość idzie przez okno na kanał, bez modelu i bez sieci."""

    def _run(self, nodes, edges, odpowiedz, wejscie="raport tygodnia"):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as cfg:
            env = dict(os.environ, DOMA_CONFIG_DIR=cfg, DOMA_NO_SYNC="1", CODO_NO_HISTORY="1", HOME=cfg)
            p = subprocess.Popen([sys.executable, str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")), "app-server"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, env=env, cwd=cfg)
            p.stdin.write(json.dumps({"type": "workflow", "name": "Powiadom", "input": wejscie,
                                      "nodes": nodes, "edges": edges}) + "\n")
            p.stdin.flush()
            out, mosty, koniec = [], [], time.time() + 40
            try:
                while time.time() < koniec:
                    ln = p.stdout.readline()
                    if not ln:
                        break
                    if not ln.startswith("{"):
                        continue
                    m = json.loads(ln)
                    out.append(m)
                    if m.get("type") == "bridge":
                        mosty.append(m)
                        p.stdin.write(json.dumps({"type": "bridge_reply", "id": m["id"], "result": odpowiedz}) + "\n")
                        p.stdin.flush()
                    if m.get("type") == "workflow" and m.get("state") in ("done", "failed"):
                        break
            finally:
                p.stdin.write(json.dumps({"type": "quit"}) + "\n")
                p.stdin.close()
                p.wait(20)
            return out, mosty

    def test_krok_wyslij_idzie_na_kanal(self):
        nodes = [{"id": "a", "kind": "start"},
                 {"id": "b", "kind": "send", "channel": "telegram", "prompt": "Przypomnienie: {{input}}"},
                 {"id": "c", "kind": "send", "channel": "imessage", "to": "+48500100200", "prompt": "Też tutaj"}]
        edges = [{"from": "a", "port": "out", "to": "b"}, {"from": "b", "port": "out", "to": "c"}]
        out, mosty = self._run(nodes, edges, {"ok": True, "tekst": "Wysłano."})
        self.assertEqual([m["action"] for m in mosty], ["kanal.wyslij", "kanal.wyslij"])
        self.assertEqual(mosty[0]["args"], {"kanal": "telegram", "tekst": "Przypomnienie: raport tygodnia", "do": ""})
        self.assertEqual(mosty[1]["args"]["do"], "+48500100200")
        wf = [m for m in out if m.get("type") == "workflow"]
        self.assertEqual([m["state"] for m in wf], ["sending", "node_done", "sending", "node_done", "done"])
        self.assertEqual(wf[1]["sent"], "Przypomnienie: raport tygodnia")
        self.assertEqual(wf[1]["error"], "")

    def test_blad_kanalu_widac_w_kroku(self):
        nodes = [{"id": "a", "kind": "start"}, {"id": "b", "kind": "send", "channel": "discord", "prompt": "x"}]
        out, _ = self._run(nodes, [{"from": "a", "port": "out", "to": "b"}], {"error": "Discord nie jest połączony."})
        done = [m for m in out if m.get("type") == "workflow" and m.get("state") == "node_done"]
        self.assertEqual(done[0]["error"], "Discord nie jest połączony.")
        self.assertEqual(done[0]["channel"], "discord")

    def test_krok_roju_przekazuje_wynik_dalej(self):
        nodes = [{"id": "a", "kind": "start"},
                 {"id": "b", "kind": "swarm", "title": "Badacze", "target": "s:1234", "prompt": "Zbadaj {{input}}"},
                 {"id": "c", "kind": "send", "channel": "telegram", "prompt": "Raport: {{last}}"}]
        edges = [{"from": "a", "port": "out", "to": "b"}, {"from": "b", "port": "out", "to": "c"}]
        out, mosty = self._run(nodes, edges, {"ok": True, "tekst": "Trzy błędy w module płatności.", "nazwa": "Badacze"})
        self.assertEqual(mosty[0]["action"], "roj.uruchom")
        self.assertEqual(mosty[0]["args"], {"cel": "s:1234", "zadanie": "Zbadaj raport tygodnia"})
        self.assertEqual(mosty[1]["action"], "kanal.wyslij")
        self.assertEqual(mosty[1]["args"]["tekst"], "Raport: Trzy błędy w module płatności.")
        stany = [(m.get("node_kind"), m["state"]) for m in out if m.get("type") == "workflow"]
        self.assertEqual(stany[:2], [("swarm", "running"), ("swarm", "node_done")])
        self.assertEqual(stany[-1], (None, "done"))

    def test_blad_roju_konczy_workflow(self):
        nodes = [{"id": "a", "kind": "start"}, {"id": "b", "kind": "swarm", "target": "b:9", "prompt": "x"},
                 {"id": "c", "kind": "send", "channel": "telegram", "prompt": "nie powinno pójść"}]
        edges = [{"from": "a", "port": "out", "to": "b"}, {"from": "b", "port": "out", "to": "c"}]
        out, mosty = self._run(nodes, edges, {"error": "Ten bot zniknął."})
        self.assertEqual([m["action"] for m in mosty], ["roj.uruchom"])
        fail = [m for m in out if m.get("type") == "workflow" and m.get("state") == "failed"]
        self.assertEqual(fail[0]["error"], "Ten bot zniknął.")

    def test_pusty_krok_bez_odpowiedzi_nie_wysyla(self):
        nodes = [{"id": "a", "kind": "start"}, {"id": "b", "kind": "send", "channel": "notification"}]
        out, mosty = self._run(nodes, [{"from": "a", "port": "out", "to": "b"}], {"ok": True})
        self.assertEqual(mosty, [])
        done = [m for m in out if m.get("type") == "workflow" and m.get("state") == "node_done"]
        self.assertTrue(done[0]["error"])


if __name__ == "__main__":
    unittest.main()


class StaliAgenciTests(unittest.TestCase):
    """20.11.2026: stały agent w oknie Codo (rola w prompcie, narzędzie agenci tylko u niego)."""

    def setUp(self):
        self.saved_app = dict(cli._APP)
        self.saved_persona = cli.SESSION.pop("app_persona", None)
        self.env = os.environ.pop("CODO_APP_AGENT", None)

    def tearDown(self):
        cli._APP.clear()
        cli._APP.update(self.saved_app)
        cli.SESSION.pop("app_persona", None)
        if self.saved_persona is not None:
            cli.SESSION["app_persona"] = self.saved_persona
        os.environ.pop("CODO_APP_AGENT", None)
        if self.env is not None:
            os.environ["CODO_APP_AGENT"] = self.env

    def test_rola_agenta_w_prompcie_systemowym(self):
        cli.SESSION["app_persona"] = "KIM JESTEŚ W TEJ ROZMOWIE: jesteś «Badacz»."
        self.assertIn("«Badacz»", cli.system_message("BAZA")["content"])
        cli.SESSION.pop("app_persona")
        self.assertNotIn("«Badacz»", cli.system_message("BAZA")["content"])

    def test_rola_trafia_tez_do_agentow_zewnetrznych(self):
        # Bot na Codexie albo Claude Code dostaje instrukcje z _agent_system, nie z system_message.
        cli.SESSION["app_persona"] = "KIM JESTEŚ W TEJ ROZMOWIE: jesteś «Strażnik stron». Pilnujesz https://example.com"
        self.assertIn("https://example.com", cli._agent_system())
        cli.SESSION.pop("app_persona")
        self.assertNotIn("Strażnik stron", cli._agent_system())

    def test_narzedzie_agenci_tylko_u_stalego_agenta(self):
        cli._APP["out"] = _Out()
        names = lambda: {t["function"]["name"] for t in cli.enabled_tools()}   # noqa: E731
        self.assertNotIn("agenci", names())
        os.environ["CODO_APP_AGENT"] = "1"
        self.assertIn("agenci", names())
        cli._APP["out"] = None
        self.assertNotIn("agenci", names())   # w terminalu nie ma okna, więc nie ma agentów

    def test_napisz_czeka_na_odpowiedz_przez_most(self):
        calls = []

        def fake(action, args=None, timeout=60):
            calls.append((action, args, timeout))
            return {"text": "Odpowiedź od «Badacz»: Paryż"}
        orig = cli._app_call
        cli._app_call = fake
        try:
            out = cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "stolica Francji?"})
            self.assertIn("Paryż", out)
            self.assertEqual(calls[0][0], "agenci.napisz")
            self.assertTrue(calls[0][1]["czekaj"])
            self.assertGreater(calls[0][2], 1200)
            cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "na później", "czekaj": False})
            self.assertFalse(calls[1][1]["czekaj"])
            self.assertLess(calls[1][2], 60)
            self.assertIn("BŁĄD", cli.t_agenci({"akcja": "napisz", "agent": "", "tekst": "x"}))
        finally:
            cli._app_call = orig

    def test_przekazanie_zadania_i_odpowiedz_pozniej(self):
        # 21.11.2026: agenci piszą do siebie bez czekania i przekazują sobie całe zadania (z plikami).
        calls = []

        def fake(action, args=None, timeout=60):
            calls.append((action, args, timeout))
            return {"text": "ok"}
        orig = cli._app_call
        cli._app_call = fake
        try:
            cli.t_agenci({"akcja": "przekaz", "agent": "Badacz", "tytul": "Raport cen", "tekst": "Zbierz ceny",
                          "pliki": ["dane/ceny.csv", ""]})
            self.assertEqual(calls[0][0], "agenci.przekaz")
            self.assertEqual(calls[0][1]["tytul"], "Raport cen")
            self.assertEqual(calls[0][1]["pliki"], ["dane/ceny.csv"])
            self.assertLess(calls[0][2], 60)   # przekazanie nie czeka na wynik
            cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "sprawdź to", "odpowiedz": "pozniej",
                          "pliki": "notatka.md"})
            self.assertEqual(calls[1][1]["odpowiedz"], "pozniej")
            self.assertFalse(calls[1][1]["czekaj"])
            self.assertEqual(calls[1][1]["pliki"], ["notatka.md"])
            self.assertLess(calls[1][2], 60)
            cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "pytanie"})
            self.assertEqual(calls[2][1]["odpowiedz"], "teraz")
            self.assertGreater(calls[2][2], 1200)
            cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "fyi", "czekaj": False})
            self.assertEqual(calls[3][1]["odpowiedz"], "nie")
            cli.t_agenci({"akcja": "zadania"})
            self.assertEqual(calls[4][0], "agenci.zadania")
            self.assertIn("BŁĄD", cli.t_agenci({"akcja": "przekaz", "agent": "Badacz", "tekst": ""}))
            self.assertIn("BŁĄD", cli.t_agenci({"akcja": "oddaj"}))
            self.assertEqual(len(calls), 5)
        finally:
            cli._app_call = orig

    def test_agent_zewnetrzny_dostaje_agenci_przez_mcp(self):
        # 21.11.2026: stały agent na Claude Code/Codexie nie miał narzędzia agenci (było tylko w narzędziach Codo).
        saved = {k: os.environ.get(k) for k in ("CODO_ZGODY_SOCK", "CODO_ZGODY_TOKEN")}
        orig_wl, orig_most = cli._mcp_wlaczony, cli._most_przez_gniazdo
        cli._mcp_wlaczony = lambda: False   # bez konta i bez Google: serwer MCP ma i tak dać agenci
        calls = []
        cli._most_przez_gniazdo = lambda action, args=None, timeout=60: (calls.append((action, args, timeout)) or {"text": "ok"})
        try:
            os.environ.pop("CODO_ZGODY_SOCK", None)
            self.assertEqual(cli._agent_mcp_servers(), {})          # zwykła rozmowa bez konta: bez serwera
            self.assertEqual(cli._mcp_narzedzia(), [])
            os.environ["CODO_APP_AGENT"] = "1"
            self.assertIn("codo", cli._agent_mcp_servers())         # stały agent: serwer zawsze
            self.assertEqual(cli._mcp_narzedzia(), [])              # bez gniazda do okna nie ma jak pisać
            os.environ["CODO_ZGODY_SOCK"], os.environ["CODO_ZGODY_TOKEN"] = "/tmp/nie-ma.sock", "t"
            self.assertEqual([t["name"] for t in cli._mcp_narzedzia()], ["agenci", "przegladarka"])
            self.assertEqual(cli._agent_mcp_env()["CODO_ZGODY_SOCK"], "/tmp/nie-ma.sock")
            # przez MCP czeka krócej niż limit narzędzi agenta zewnętrznego i mówi oknu, ile
            cli.t_agenci({"akcja": "napisz", "agent": "Badacz", "tekst": "ile?"}, most=cli._most_przez_gniazdo, czekaj_max=480)
            self.assertEqual(calls[0][1]["limit"], 480)
            self.assertLess(calls[0][2], 600)
            # brak gniazda: jasny błąd, nie wyjątek
            self.assertIn("error", orig_most("agenci.lista", {}, 1))
        finally:
            cli._mcp_wlaczony, cli._most_przez_gniazdo = orig_wl, orig_most
            for k, v in saved.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_uprawnienia_agentow_zewnetrznych_dla_mcp(self):
        # Codex bez trybu zatwierdzania odrzuca każde narzędzie MCP; Claude w trybie planowania też.
        orig = cli._agent_mcp_servers
        cli._agent_mcp_servers = lambda: {"codo": ["python3", "codo", "mcp"]}
        try:
            argv, _ = cli._agent_argv("codex", "/bin/codex", "ask", False, None, "hej")
            self.assertIn('mcp_servers.codo.default_tools_approval_mode="approve"', argv)
            argv, _ = cli._agent_argv("claude", "/bin/claude", "read", False, None, "hej")
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")       # zwykła rozmowa: jak było
            os.environ["CODO_APP_AGENT"] = "1"
            argv, _ = cli._agent_argv("claude", "/bin/claude", "read", False, None, "hej")
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "default")    # stały agent, który tylko czyta
            self.assertIn("Write", argv[argv.index("--disallowedTools") + 1])
            self.assertEqual(argv[argv.index("--allowedTools") + 1], "mcp__codo")
            argv, _ = cli._agent_argv("claude", "/bin/claude", "auto", True, None, "hej")
            self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
            self.assertNotIn("--disallowedTools", argv)
        finally:
            cli._agent_mcp_servers = orig

    def test_stop_przed_startem_tury_dotyczy_tej_tury(self):
        # Znacznik czasu przerwania jest zapisywany także wtedy, gdy tura jeszcze nie ruszyła.
        cli.SESSION.pop("app_interrupt_at", None)
        cli.SESSION["app_busy"] = False
        t0 = time.monotonic()
        cli._app_interrupt()
        self.assertGreaterEqual(cli.SESSION["app_interrupt_at"], t0)
        cli.SESSION.pop("app_interrupt_at", None)

    def test_narzedzie_agenci_ma_przekazanie_w_schemacie(self):
        t = next(t for t in cli.TOOLS if t["function"]["name"] == "agenci")["function"]
        self.assertEqual(t["parameters"]["properties"]["akcja"]["enum"], ["lista", "napisz", "przekaz", "zadania", "umiejetnosc", "szukaj", "profil"])
        self.assertIn("pliki", t["parameters"]["properties"])
        self.assertIn("przekaz", t["description"])
