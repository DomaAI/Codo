"""Codo 0.22.2: zmiana mózgu w trakcie rozmowy (Lopus ↔ Codex ↔ Claude Code), zapasowy mózg
i praca bez sieci. Bez sieci i bez dostawców LLM: atrapy agentów z test_codo_konta_agenci."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa, zamknij_stdin  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_codo_konta_agenci as base   # noqa: E402

cli = base.cli
SCRIPT = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))


class ZmianaMozguTests(base.CodoKontaAgenciTests):
    def setUp(self):
        super().setUp()
        cli.SESSION.pop("brain_seen", None)
        os.environ["CODO_ONLINE"] = "1"

    def test_other_brain_answers_reach_agent_session(self):
        ok, out, msgs = self._turn("agent:codex", "zacznij")
        self.assertTrue(ok, out)
        # w międzyczasie odpowiadał Lopus (inny mózg z własną pamięcią)
        msgs += [{"role": "user", "content": "co dalej?"}, {"role": "assistant", "content": "Lopus: zrób testy."}]
        cli.brain_mark("lopus", msgs)
        ok, out, msgs = self._turn("agent:codex", "zrób to", messages=msgs)
        self.assertTrue(ok, out)
        call = self._calls()[-1]
        self.assertIn("resume", call["argv"])
        self.assertIn("Lopus: zrób testy.", call["stdin"])
        self.assertIn("W międzyczasie", call["stdin"])
        # kolejna tura bez innego mózgu: tylko polecenie
        ok, out, msgs = self._turn("agent:codex", "i jeszcze", messages=msgs)
        self.assertEqual(self._calls()[-1]["stdin"].strip(), "i jeszcze")

    def test_lopus_gets_what_codex_said(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "a"},
                {"role": "assistant", "content": "Lopus odp"}]
        cli.brain_mark("lopus", msgs)
        msgs += [{"role": "user", "content": "b"}, {"role": "assistant", "content": "Codex zrobił plik."},
                 {"role": "user", "content": "c"}]
        gap = cli.brain_catchup("lopus", msgs)
        self.assertIn("Codex zrobił plik.", gap)
        self.assertNotIn("Lopus odp", gap)

    def test_model_switch_works_offline(self):
        with patch.object(cli, "fetch_models", side_effect=urllib.error.URLError("offline")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_model("agent:codex"), 0)
        self.assertEqual(cli.current_model(None), "agent:codex")

    def test_models_list_from_cache_when_server_down(self):
        cli._models_cache_put("domaai", {"models": [{"id": "lopus", "label": "Lopus"}], "default_model": "lopus"})
        with patch.object(cli, "provider", return_value="domaai"), \
                patch.object(cli, "api_call", side_effect=urllib.error.URLError("offline")):
            models, default = cli.fetch_models()
        ids = [m[0] for m in models]
        self.assertIn("lopus", ids)
        self.assertIn("agent:codex", ids)
        self.assertEqual(default, "lopus")

    def test_backup_choice_and_local_when_offline(self):
        self._login("ollama")
        ep = cli.load_endpoint("ollama")
        self.assertTrue(cli._is_local_url(ep["base_url"]))
        st = cli.load_settings()
        st["backup_brain"] = "agent:codex"
        cli.save_settings(st)
        self.assertEqual(cli._backup_brain(429, {"agent:claude"}), "agent:codex")
        self.assertIsNone(cli._backup_brain(400, {"agent:claude"}))
        os.environ.pop("CODO_ONLINE")
        os.environ["CODO_OFFLINE"] = "1"
        cli._ONLINE["at"] = 0
        local = cli.local_brains()[0]
        self.assertEqual(cli._backup_brain("net", {"agent:claude"}), local)   # Codex bez sieci nie pomoże
        st["backup_brain_off"] = True
        cli.save_settings(st)
        self.assertIsNone(cli._backup_brain("net", set()))


class ZapasAppServerTests(unittest.TestCase):
    def _run(self, settings, env_extra, text="zrób coś"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cfg = root / "cfg"
        cfg.mkdir()
        (cfg / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        proj = root / "proj"
        proj.mkdir()
        (proj / "app.py").write_text("x = 1\n", encoding="utf-8")
        env = dict(os.environ, DOMA_CONFIG_DIR=str(cfg), DOMA_API_URL="http://127.0.0.1:9",
                   FAKE_LOG=str(root / "log"), CODO_LANG="pl", DOMA_NO_SYNC="1", CODO_NO_HISTORY="1")
        for kind, code in base._FAKE.items():
            f = atrapa(root, kind, textwrap.dedent(code))
            env[f"CODO_AGENT_{kind.upper()}"] = str(f)
        env.update(env_extra)
        p = subprocess.Popen([sys.executable, SCRIPT, "app-server"], cwd=proj, env=env, text=True,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        events = [json.loads(p.stdout.readline())]
        p.stdin.write(json.dumps({"type": "send", "text": text}) + "\n")
        p.stdin.flush()
        for line in p.stdout:
            events.append(json.loads(line))
            if events[-1]["type"] == "turn_end":
                break
        zamknij_stdin(p)
        p.wait(10)
        err = p.stderr.read()
        self.assertNotIn("Traceback", err)
        return events

    def test_limit_moves_turn_to_backup_brain(self):
        ev = self._run({"provider": "agent", "model_agent": "agent:claude", "backup_brain": "agent:codex"},
                       {"FAKE_MODE": "limit", "CODO_ONLINE": "1"})
        fb = next(e for e in ev if e["type"] == "fallback" and e.get("model") == "agent:codex")
        self.assertIn("Codex", fb["tekst"])
        self.assertTrue(ev[-1]["ok"])
        self.assertTrue(any(e["type"] in ("assistant", "delta") and "nowy.txt" in json.dumps(e) for e in ev))

    def test_offline_without_local_model_says_why(self):
        ev = self._run({"provider": "agent", "model_agent": "agent:claude"}, {"CODO_OFFLINE": "1"})
        self.assertFalse(ev[-1]["ok"])
        self.assertTrue(any(e["type"] == "error" and "internetu" in e["tekst"] for e in ev))
        self.assertFalse(any(e["type"] == "tool_start" for e in ev))   # agent nie był nawet wołany


if __name__ == "__main__":
    unittest.main()


class FirmaTests(unittest.TestCase):
    """Stanowisko Codo firmy: klucz dfk_ w firma.json (0600), nagłówek X-Codo-Firma przy żądaniach DomaAI."""

    def setUp(self):
        for f in Path(base._CFG).iterdir():
            f.unlink()

    def test_key_saved_private_and_sent_as_header(self):
        cli.save_firma("dfk_abcd_sekret")
        if os.name != "nt":   # prawa POSIX
            self.assertEqual(oct(os.stat(cli.FIRMA_FILE).st_mode & 0o777), "0o600")
        self.assertEqual(cli.firma_headers(), {"X-Codo-Firma": "dfk_abcd_sekret"})
        seen = {}

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b"{}"

        def _open(req, timeout=0, context=None):
            seen.update({k.lower(): v for k, v in req.header_items()})
            return _Resp()
        with patch.object(cli.urllib.request, "urlopen", _open):
            cli._http_once("GET", "/cli/models", token="tok")
        self.assertEqual(seen.get("x-codo-firma"), "dfk_abcd_sekret")
        seen.clear()
        with patch.object(cli.urllib.request, "urlopen", _open):
            cli._http_once("POST", "/cli/login", json_body={})   # bez tokenu (logowanie): bez klucza firmy
        self.assertNotIn("x-codo-firma", seen)
        cli.save_firma(None)
        self.assertEqual(cli.firma_headers(), {})

    def test_bad_key_rejected_and_server_refusal_rolls_back(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_firma("sk-zly"), 1)
        self.assertIsNone(cli.load_firma())
        cli.save_firma("dfk_stary_klucz")
        with patch.object(cli, "firma_stan", return_value={"blad": "Klucz firmy jest nieprawidłowy"}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_firma("dfk_nowy_zly"), 1)
        self.assertEqual(cli.load_firma()["klucz"], "dfk_stary_klucz")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_firma("off"), 0)
        self.assertIsNone(cli.load_firma())


class AgentKreatorTests(unittest.TestCase):
    """Kreator agenta w Codo (20.11): bez konta DomaAI agent zostaje lokalnie (0600) z własną personą."""

    def setUp(self):
        for f in Path(base._CFG).iterdir():
            f.unlink()

    def test_local_agent_saved_with_persona_and_shape(self):
        with patch.object(cli, "device_access_token", return_value=None), \
             patch.object(cli, "load_creds", return_value=None), \
             patch.object(cli, "load_device", return_value=None):
            with self.assertRaises(ValueError):
                cli.save_created_agent({"name": "x"})
            p = cli.save_created_agent({"name": "  Nova ", "colors": ["#7C5CFF", "zly", "#14B8A6"],
                                        "tone": "przyjazny", "traits": ["forma:ty", "forma:pan", "emoji:nie", "x:y"],
                                        "prompt": "Pisz krótko", "shape": "chmurka"})
            self.assertEqual(p["agent"], "Nova")
            self.assertEqual(p["kolory_agenta"], ["#7C5CFF", "#14B8A6"])
            self.assertEqual(p["cechy"], ["forma:ty", "emoji:nie"])
            if os.name != "nt":   # prawa POSIX
                self.assertEqual(oct(os.stat(cli.AGENT_LOCAL_FILE).st_mode & 0o777), "0o600")
            a = cli._app_agent()
            self.assertEqual((a["name"], a["shape"], a["local"]), ("Nova", "chmurka", True))
            self.assertIn("Nova", cli._persona_block())
            self.assertIn("Pisz krótko", cli._persona_block())

    def test_signed_in_agent_goes_to_domaai_profile(self):
        calls = []

        def fake_http(method, path, **kw):
            calls.append((method, path, kw.get("json_body")))
            return {"agent": "Nova", "kolor_agenta": "#7C5CFF", "persona": "x"} if path == "/cli/whoami" else {}

        with patch.object(cli, "device_access_token", return_value="tok"), \
             patch.object(cli, "_http", side_effect=fake_http), \
             patch.object(cli, "load_device", return_value={"id": 1}):
            cli.save_created_agent({"name": "Nova", "tone": "zwiezly", "shape": "kostka"})
        self.assertEqual(calls[0][:2], ("PUT", "/agent/profil"))
        self.assertEqual(calls[0][2]["nazwa"], "Nova")
        self.assertEqual(calls[0][2]["ton"], "zwiezly")
        self.assertEqual(cli.load_settings().get("agent_ksztalt"), "kostka")
