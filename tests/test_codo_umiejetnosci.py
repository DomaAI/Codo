"""Codo 20.11.2026: umiejętności, które agent sam zapisuje i poprawia (SKILL.md w .codo/skills projektu
albo globalnie w ~/.config/doma/skills/wlasne), indeks w instrukcji systemowej, licznik użyć, porządki
(stara po 30 dniach, archiwum po 90), /skills i wiadomości app-servera. Bez sieci i bez modeli: tury agenta
dostają atrapę api_step."""
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_codo_konta_agenci as base   # noqa: E402

cli = base.cli
_CLI_FILE = Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")

_BODY = ("## Kiedy\nWdrożenie na staging.\n\n## Kroki\n1. `make build`\n2. `./deploy.sh staging`\n\n"
         "## Pułapki\nNajpierw migracje.\n\n## Sprawdzenie\n`curl -fsS localhost:8001/health`")


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


class UmiejetnosciTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="codo-umiej-")).resolve()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        self.cwd = os.getcwd()
        os.chdir(self.proj)
        self.patches = [patch.object(cli, "OWN_SKILLS_DIR", self.tmp / "global" / "wlasne"),
                        patch.object(cli, "SKILLS_DIR", self.tmp / "global"),
                        patch.object(cli, "_INPUT_MODE", "ask"),
                        patch.object(cli, "ui_lang", return_value="pl")]
        for p in self.patches:
            p.start()
        cli._OWN_TIDIED.clear()
        self._settings({"skills_off": [], "disabled_tools": []})
        self.saved_app = dict(cli._APP)
        self.out = _Out()
        cli._APP["out"] = self.out

    def tearDown(self):
        cli._APP.clear()
        cli._APP.update(self.saved_app)
        for p in self.patches:
            p.stop()
        os.chdir(self.cwd)
        self._settings({"skills_off": [], "disabled_tools": []})

    def _settings(self, values):
        st = cli.load_settings()
        st.update(values)
        cli.save_settings(st)

    def _save(self, auto_yes=False, **kw):
        args = {"name": "Wdrożenie na staging", "description": "Jak wdrożyć ten projekt na staging.", "content": _BODY}
        args.update(kw)
        return cli.t_skill_save(args, auto_yes)

    def _set_dates(self, path: Path, days_ago: int):
        day = (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat()
        text = path.read_text(encoding="utf-8")
        path.write_text(cli._own_set_fields(text, {"created": day, "updated": day, "last_used": day}), encoding="utf-8")

    # ── format i zapis ────────────────────────────────────────────────────
    def test_nazwa_bez_polskich_znakow_i_ucieczek(self):
        self.assertEqual(cli._own_skill_name("Wdrożenie na Staging!"), "wdrozenie-na-staging")
        self.assertEqual(cli._own_skill_name("../../etc/passwd"), "etc-passwd")
        self.assertEqual(cli._own_skill_name("Łódź"), "lodz")
        self.assertEqual(cli._own_skill_name("  ...  "), "")
        self.assertEqual(len(cli._own_skill_name("a" * 200)), 60)

    def test_zapis_w_projekcie_zgodny_z_naglowkiem_skill_md(self):
        res = self._save()
        self.assertTrue(res.startswith("Zapisano"), res)
        path = self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md"
        self.assertTrue(path.is_file())
        meta = cli._skill_meta(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["name"], "wdrozenie-na-staging")
        self.assertEqual(meta["description"], "Jak wdrożyć ten projekt na staging.")
        self.assertEqual(meta["source"], "agent")
        self.assertEqual(meta["uses"], "0")
        self.assertEqual(meta["created"], datetime.date.today().isoformat())
        self.assertIn("./deploy.sh staging", path.read_text(encoding="utf-8"))
        # zapis jak edycja pliku: wpis w dzienniku zmian (diff, /undo)
        self.assertTrue(any(Path(e["path"]) == path.resolve() for e in cli.EDIT_LOG))
        ev = self.out.of("skill_saved")[-1]
        self.assertEqual((ev["id"], ev["scope"], ev["updated"]), ("projekt:wdrozenie-na-staging", "projekt", False))

    def test_aktualizacja_zachowuje_historie(self):
        self._save()
        path = self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md"
        self._set_dates(path, 10)
        path.write_text(cli._own_set_fields(path.read_text(encoding="utf-8"), {"uses": 7}), encoding="utf-8")
        res = self._save(name="wdrozenie-na-staging", description="", content=_BODY + "\n3. Sprawdź logi.")
        self.assertTrue(res.startswith("Zaktualizowano"), res)
        meta = cli._skill_meta(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["uses"], "7")
        self.assertEqual(meta["description"], "Jak wdrożyć ten projekt na staging.")   # pusty opis = poprzedni
        self.assertEqual(meta["updated"], datetime.date.today().isoformat())
        self.assertNotEqual(meta["created"], meta["updated"])
        self.assertTrue(self.out.of("skill_saved")[-1]["updated"])

    def test_limity_i_bledne_dane(self):
        self.assertTrue(self._save(content="x" * (cli._OWN_SKILL_MAX + 1)).startswith("BŁĄD"))
        self.assertTrue(self._save(content="krótko").startswith("BŁĄD"))
        self.assertTrue(self._save(content=_BODY + "\x00").startswith("BŁĄD"))
        self.assertTrue(self._save(name="!!!").startswith("BŁĄD"))
        self.assertTrue(self._save(description="").startswith("BŁĄD"))
        self.assertFalse((self.proj / ".codo").exists())

    def test_naglowek_w_tresci_nie_jest_dublowany(self):
        self._save(content="---\nname: zle\ndescription: z treści\n---\n" + _BODY, description="")
        text = (self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("---\n"), 2)
        self.assertEqual(cli._skill_meta(text)["description"], "z treści")

    def test_globalnie_pyta_o_zgode(self):
        with patch.object(cli, "confirm_action", return_value=False) as ask:
            res = self._save(scope="globalnie")
        ask.assert_called_once()
        self.assertTrue(res.startswith("ODRZUCONE"), res)
        self.assertFalse((self.tmp / "global/wlasne").exists())
        with patch.object(cli, "confirm_action", return_value=True):
            res = self._save(scope="globalnie")
        self.assertTrue(res.startswith("Zapisano"), res)
        self.assertTrue((self.tmp / "global/wlasne/wdrozenie-na-staging/SKILL.md").is_file())
        self.assertFalse((self.proj / ".codo").exists())
        # tryb auto: bez pytania; poprzednia wersja zostaje obok
        with patch.object(cli, "confirm_action") as ask:
            res = cli.t_skill_save({"name": "wdrozenie-na-staging", "scope": "globalnie", "content": _BODY + "\nDopisek."}, True)
        ask.assert_not_called()
        self.assertTrue(res.startswith("Zaktualizowano"), res)
        self.assertTrue((self.tmp / "global/wlasne/wdrozenie-na-staging/.SKILL.md.poprzednia").is_file())

    def test_tryb_odczytu_blokuje_zapis(self):
        self.assertNotIn("skill_save", cli._READ_ONLY_TOOLS)
        call = {"id": "1", "function": {"name": "skill_save", "arguments": json.dumps(
            {"name": "x-proc", "description": "d", "content": _BODY})}}
        responses = [{"message": {"role": "assistant", "tool_calls": [call]}},
                     {"message": {"role": "assistant", "content": "OK"}}]
        messages = [{"role": "user", "content": "zrób"}]
        with patch.object(cli, "api_step", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cli.agent_turn({}, messages, None, True, mode="read"))
        self.assertIn("tryb tylko do odczytu", messages[2]["content"])
        self.assertFalse((self.proj / ".codo").exists())

    def test_tura_agenta_zapisuje_przez_narzedzie(self):
        call = {"id": "1", "function": {"name": "skill_save", "arguments": json.dumps(
            {"name": "testy-projektu", "description": "Jak uruchomić testy.", "content": _BODY})}}
        responses = [{"message": {"role": "assistant", "tool_calls": [call]}},
                     {"message": {"role": "assistant", "content": "Zapisałem umiejętność."}}]
        messages = [{"role": "user", "content": "zrób"}]
        with patch.object(cli, "api_step", side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(cli.agent_turn({}, messages, None, False, mode="ask"))
        self.assertTrue((self.proj / ".codo/skills/testy-projektu/SKILL.md").is_file())
        self.assertIn("skill_save", [t["function"]["name"] for t in cli.enabled_tools()])

    def test_wylaczona_grupa_umiejetnosci(self):
        self._settings({"disabled_tools": ["skills"]})
        self.assertNotIn("skill_save", [t["function"]["name"] for t in cli.enabled_tools()])
        self.assertTrue(cli.run_tool("skill_save", {"name": "a", "description": "b", "content": _BODY}, True)
                        .startswith("ODRZUCONE"))
        self.assertNotIn("UCZENIE SIĘ", cli._local_skills_prompt())

    # ── wczytywanie i indeks ──────────────────────────────────────────────
    def test_wczytanie_liczy_uzycia_projekt_przed_globalna(self):
        self._save()
        with patch.object(cli, "confirm_action", return_value=True):
            cli.t_skill_save({"name": "wdrozenie-na-staging", "description": "globalna", "scope": "globalnie",
                              "content": _BODY + "\nWERSJA GLOBALNA"}, False)
        path = self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md"
        self._set_dates(path, 5)
        text = cli.run_tool("local_skill", {"name": "wdrozenie-na-staging"}, False)
        self.assertIn("Twoja umiejętność (projekt)", text)
        meta = cli._skill_meta(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["uses"], "1")
        self.assertEqual(meta["last_used"], datetime.date.today().isoformat())
        cli.t_local_skill({"name": "Wdrożenie na staging"})   # nazwa z polskimi znakami też trafia
        self.assertEqual(cli._skill_meta(path.read_text(encoding="utf-8"))["uses"], "2")
        g = cli.t_local_skill({"name": "globalnie:wdrozenie-na-staging"})
        self.assertIn("Twoja umiejętność (globalnie)", g)
        listing = cli.t_local_skill({})
        self.assertLess(listing.index("projekt"), listing.index("globalnie"))

    def test_wczytanie_w_trybie_odczytu_nie_zmienia_pliku(self):
        self._save()
        path = self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md"
        before = path.read_text(encoding="utf-8")
        with patch.object(cli, "_INPUT_MODE", "read"):
            cli.t_local_skill({"name": "wdrozenie-na-staging"})
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_plik_poza_folderem_odrzucony(self):
        self._save()
        res = cli.t_local_skill({"name": "wdrozenie-na-staging", "file": "../../../etc/hosts"})
        self.assertTrue(res.startswith("BŁĄD"), res)

    def test_indeks_w_instrukcji_systemowej(self):
        for i in range(25):
            cli.t_skill_save({"name": f"proc-{i:02d}", "description": f"Opis procedury {i}.", "content": _BODY}, False)
        with patch.object(cli, "confirm_action", return_value=True):
            cli.t_skill_save({"name": "globalna-a", "description": "Globalna.", "content": _BODY, "scope": "globalnie"}, False)
        with patch.object(cli, "_project_notes", return_value=""), patch.object(cli, "_env_context", return_value=""):
            sysmsg = cli.system_message("BAZA")["content"]
        self.assertIn("TWOJE UMIEJĘTNOŚCI", sysmsg)
        self.assertIn("UCZENIE SIĘ NA ZADANIACH", sysmsg)
        self.assertIn("skill_save", sysmsg)
        self.assertEqual(sysmsg.count("(projekt): Opis procedury"), cli._OWN_PROMPT_MAX)
        self.assertNotIn("globalna-a", sysmsg)   # 20 z projektu wypełnia indeks, projekt przed globalnymi
        for i in range(25):
            cli.own_skill_action("remove", f"proc-{i:02d}")
        cli._OWN_TIDIED.clear()
        self.assertIn("globalna-a (globalna)", cli._local_skills_prompt())

    def test_wylaczona_umiejetnosc_znika_z_indeksu(self):
        self._save()
        self.assertIn("Wyłączono", cli.own_skill_action("off", "wdrozenie-na-staging"))
        self.assertNotIn("wdrozenie-na-staging", cli._local_skills_prompt())
        self.assertTrue(cli.t_local_skill({"name": "wdrozenie-na-staging"}).startswith("BŁĄD"))
        cli.own_skill_action("on", "projekt:wdrozenie-na-staging")
        self.assertIn("wdrozenie-na-staging", cli._local_skills_prompt())

    # ── porządki ──────────────────────────────────────────────────────────
    def test_stara_po_30_dniach_archiwum_po_90(self):
        cli.t_skill_save({"name": "swieza", "description": "a", "content": _BODY}, False)
        cli.t_skill_save({"name": "stara-proc", "description": "b", "content": _BODY}, False)
        cli.t_skill_save({"name": "zapomniana", "description": "c", "content": _BODY}, False)
        root = self.proj / ".codo/skills"
        self._set_dates(root / "stara-proc/SKILL.md", 40)
        self._set_dates(root / "zapomniana/SKILL.md", 95)
        cli._OWN_TIDIED.clear()
        items = {x["name"]: x for x in cli.own_skills_list()}
        self.assertFalse(items["swieza"]["stale"])
        self.assertTrue(items["stara-proc"]["stale"])
        self.assertTrue(items["zapomniana"]["archived"])
        self.assertFalse((root / "zapomniana").exists())
        self.assertTrue((root / ".archiwum/zapomniana/SKILL.md").is_file())   # nie skasowana
        self.assertNotIn("zapomniana", cli._local_skills_prompt())
        # przywrócenie liczy wiek od dziś, więc porządki nie odsyłają jej od razu
        self.assertIn("Przywrócono", cli.own_skill_action("restore", "zapomniana"))
        cli._OWN_TIDIED.clear()
        items = {x["name"]: x for x in cli.own_skills_list()}
        self.assertFalse(items["zapomniana"]["archived"])
        self.assertEqual(items["zapomniana"]["idle_days"], 0)

    def test_usun_do_archiwum_potem_na_zawsze(self):
        self._save()
        root = self.proj / ".codo/skills"
        self.assertIn("archiwum", cli.own_skill_action("remove", "wdrozenie-na-staging"))
        self.assertTrue((root / ".archiwum/wdrozenie-na-staging/SKILL.md").is_file())
        self.assertIn("na zawsze", cli.own_skill_action("remove", "wdrozenie-na-staging"))
        self.assertFalse((root / ".archiwum/wdrozenie-na-staging").exists())
        with self.assertRaises(ValueError):
            cli.own_skill_action("restore", "wdrozenie-na-staging")

    def test_zapis_pod_nazwa_z_archiwum_ja_przywraca(self):
        self._save()
        path = self.proj / ".codo/skills/wdrozenie-na-staging/SKILL.md"
        path.write_text(cli._own_set_fields(path.read_text(encoding="utf-8"), {"uses": 4}), encoding="utf-8")
        cli.own_skill_action("remove", "wdrozenie-na-staging")
        self._save(description="", content=_BODY + "\nPoprawka.")
        self.assertTrue(path.is_file())
        self.assertFalse((self.proj / ".codo/skills/.archiwum/wdrozenie-na-staging").exists())
        self.assertEqual(cli._skill_meta(path.read_text(encoding="utf-8"))["uses"], "4")

    def test_pakiet_github_nie_moze_usunac_wlasnych(self):
        with patch.object(cli, "confirm_action", return_value=True):
            self._save(scope="globalnie")
        cli.skills_remove("wlasne")
        self.assertTrue((self.tmp / "global/wlasne/wdrozenie-na-staging/SKILL.md").is_file())
        self.assertEqual(cli.skills_list(), [])   # folder własnych nie udaje pakietu z GitHuba

    def test_komenda_skills(self):
        self._save()
        cli.t_skill_save({"name": "stara-proc", "description": "b", "content": _BODY}, False)
        self._set_dates(self.proj / ".codo/skills/stara-proc/SKILL.md", 45)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(cli.cmd_skills(""), 0)
        out = buf.getvalue()
        self.assertIn("Własne w projekcie", out)
        self.assertIn("wdrozenie-na-staging", out)
        self.assertIn("stara", out)
        self.assertIn("Z GitHuba", out)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.cmd_skills("wylacz stara-proc"), 0)
            self.assertEqual(cli.cmd_skills("usun stara-proc"), 0)
            self.assertEqual(cli.cmd_skills("przywroc stara-proc"), 0)
            self.assertEqual(cli.cmd_skills("usun nie-ma-takiej"), 1)
        self.assertIn("projekt:stara-proc", cli.load_settings()["skills_off"])
        self.assertIn("/skills", cli._SLASH)

    def test_tlumaczenia_nowych_tekstow(self):
        for key in ("Zapisać umiejętność dla wszystkich projektów?", "Własne w projekcie", "użycia: {0}",
                    "Zapisuję umiejętność", "własne umiejętności agenta i te z GitHuba"):
            self.assertIn(key, cli._EN)


class AppServerUmiejetnosciTests(unittest.TestCase):
    """Prawdziwy `codo app-server` w podprocesie (bez sieci): lista, wyłączenie i usunięcie własnej umiejętności."""

    def test_wiadomosci_own_skills(self):
        tmp = Path(tempfile.mkdtemp(prefix="codo-umiej-app-")).resolve()
        proj = tmp / "proj"
        skill = proj / ".codo/skills/demo"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: \"Pokaz\"\nuses: 2\nlast_used: {datetime.date.today().isoformat()}\n---\n\nKroki.\n",
            encoding="utf-8")
        env = dict(os.environ, HOME=str(tmp), DOMA_CONFIG_DIR=str(tmp / ".config/doma"), CODO_LANG="pl",
                   DOMA_API_URL="http://127.0.0.1:9", DOMA_NO_SYNC="1", CODO_NO_HISTORY="1")
        proc = subprocess.Popen([sys.executable, str(_CLI_FILE), "app-server"], cwd=proj, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        lines = []
        try:
            def wait_for(kind, n=1):
                deadline = time.time() + 30
                while time.time() < deadline:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    ev = json.loads(line)
                    lines.append(ev)
                    if ev.get("type") == kind and sum(1 for x in lines if x.get("type") == kind) >= n:
                        return ev
                self.fail(f"brak zdarzenia {kind}: {lines}")
            wait_for("ready")
            proc.stdin.write(json.dumps({"type": "own_skills"}) + "\n")
            proc.stdin.flush()
            ev = wait_for("own_skills")
            self.assertEqual([(x["id"], x["uses"], x["enabled"]) for x in ev["items"]], [("projekt:demo", 2, True)])
            self.assertTrue(ev["project_dir"].endswith(".codo/skills"))
            proc.stdin.write(json.dumps({"type": "own_skill", "id": "projekt:demo", "action": "off"}) + "\n")
            proc.stdin.flush()
            ev = wait_for("own_skills", 2)
            self.assertFalse(ev["items"][0]["enabled"])
            proc.stdin.write(json.dumps({"type": "own_skill", "id": "projekt:demo", "action": "remove"}) + "\n")
            proc.stdin.flush()
            ev = wait_for("own_skills", 3)
            self.assertTrue(ev["items"][0]["archived"])
            self.assertTrue((proj / ".codo/skills/.archiwum/demo/SKILL.md").is_file())
            proc.stdin.write(json.dumps({"type": "own_skill", "id": "projekt:nie-ma", "action": "restore"}) + "\n")
            proc.stdin.flush()
            ev = wait_for("own_skills", 4)
            self.assertTrue(ev["error"])
            proc.stdin.write(json.dumps({"type": "quit"}) + "\n")
            proc.stdin.flush()
            proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
