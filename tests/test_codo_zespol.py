"""Codo: zespoły agentów (codo team, 0.26.0 i etap 2 w 0.27.0). Bez sieci, bez dostawców SI i bez prawdziwych agentów:
atrapa zgodna z /v1 działa lokalnie jako konto „@atrapa/atrapa-1”, a scenariusz członka wybiera jego
identyfikator w prompcie systemowym. Testy git pracują w repozytoriach tymczasowych.

Kontrakt zdarzeń dla okien (Mac, codo ui) to tests/fixtures/zespol_zdarzenia.jsonl; test kontraktu
zapisuje go od nowa z prawdziwego przebiegu, gdy pliku brak albo przy CODO_REGEN=1."""
import importlib.machinery
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa, zamknij_stdin  # noqa: E402

_ROOT = Path(tempfile.mkdtemp(prefix="codo-zespol-")).resolve()
_HOME = _ROOT / "home"
_CFG = _HOME / ".config" / "doma"
_CFG.mkdir(parents=True)
os.environ.update(HOME=str(_HOME), USERPROFILE=str(_HOME), DOMA_CONFIG_DIR=str(_CFG),
                  DOMA_API_URL="http://127.0.0.1:9", CODO_LANG="pl", DOMA_NO_SYNC="1", CODO_APP_LOCAL_ONLY="1")
for _k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL", "GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME", "CODO_ZESPOL_DIR",
           "CODO_ZESPOL_CZLONEK", "CODO_ZESPOL_ROLA", "CODO_PROVIDER", "CODO_APP_MODE", "CODO_NO_HISTORY"):
    os.environ.pop(_k, None)
# Bez agentów z tego komputera: „mix” i katalog mózgów nie mogą sięgnąć po prawdziwego agenta.
(_CFG / "settings.json").write_text(json.dumps({"agents_off": True, "lang": "pl"}), encoding="utf-8")

SCRIPT = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))
_loader = importlib.machinery.SourceFileLoader("codo_zespol", SCRIPT)
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "zespol_zdarzenia.jsonl"

# Kontrakt 3.6: pola wymagane w każdym zdarzeniu danego typu (dodatkowe pola są dozwolone).
CONTRACT = {
    "team_templates": {"templates", "brains"},
    "team_started": {"run_id", "seq", "state"},
    "team_state": {"run_id", "seq", "status", "goal", "name", "created", "elapsed_s", "spent_kr", "limits", "git",
                   "base_branch", "integration_branch", "members", "tasks", "messages_tail", "pending_asks"},
    "team_member": {"run_id", "seq", "member"},
    "team_task": {"run_id", "seq", "task"},
    "team_message": {"run_id", "seq", "message"},
    "team_member_event": {"run_id", "member", "event"},
    "team_ask": {"run_id", "seq", "ask_id", "member", "pytanie", "szczegol", "powod", "opcje"},
    "team_ask_done": {"run_id", "seq", "ask_id", "value", "by"},
    "team_merge": {"run_id", "seq", "task_id", "member", "state", "files", "conflicts"},
    "team_budget": {"run_id", "seq", "spent_kr", "budget_kr", "elapsed_s", "hours", "warn"},
    "team_done": {"run_id", "seq", "status", "summary", "spent_kr", "seconds", "diff_stat", "apply_options"},
    "team_applied": {"run_id", "seq", "how", "ok", "detail"},
    "team_runs": {"runs"},
    "team_error": {"tekst"},
    # etap 2 (features team2)
    "team_plan": {"run_id", "seq", "tasks", "note", "round"},
    "team_question": {"run_id", "seq", "id", "from", "text", "options"},
    "team_question_done": {"run_id", "seq", "id", "by"},
    "team_diff": {"run_id", "scope", "files", "patch", "truncated"},
    "team_member_log": {"run_id", "member", "events", "next"},
}
MERGE_STATES = {"queued", "reviewing", "waiting_human", "rejected", "merging", "checking", "merged", "conflict",
                "check_failed"}
MEMBER_KEYS = {"id", "name", "role", "brain", "brain_label", "writes", "isolation", "worktree", "branch", "status",
               "doing", "task_id", "spent_kr", "turns", "seconds", "edits", "pid", "convo_id", "agent_sid",
               "inbox_seq", "tools", "error"}
TASK_KEYS = {"id", "title", "detail", "kind", "assignee", "created_by", "depends_on", "files", "status", "claimed_by",
             "needs_review", "reviewer", "review", "result", "commit", "merge", "attempts", "created", "updated"}
MESSAGE_KEYS = {"seq", "id", "from", "to", "text", "task_id", "ts"}


def git(path, *args, check=True):
    r = subprocess.run(["git", "-C", str(path), "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8")
    if check and r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


def make_repo(root: Path) -> Path:
    proj = root / "projekt"
    proj.mkdir(parents=True)
    git(proj, "init", "-q", "-b", "main")
    (proj / "README.md").write_text("# Projekt\n\nlinia 1\n", encoding="utf-8")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "start")
    return proj


def tpl(members, lead=True, **policy):
    return {"version": 1, "name": "test", "title": "Test", "lead": {"brain": ""} if lead else None,
            "members": members, "tasks": [], "policy": policy}


def mem(mid, writes=True, **kw):
    return {"id": mid, "name": mid.upper(), "role": "rola " + mid, "brain": "", "writes": writes,
            "isolation": "copy" if writes else "readonly", **kw}


class FakeProc:
    """Członek bez procesu: zapisuje, co nadzorca mu wysłał; zdarzenia wstrzykuje test."""

    def __init__(self, run_dir, member, q, mode):
        self.m, self.q, self.mode = member, q, mode
        self.sent, self.interrupted, self.stopped = [], 0, False

    def spawn(self):
        return 0

    def send(self, text):
        self.sent.append(text)
        return True

    def send_raw(self, obj):
        self.sent.append(obj)
        return True

    def answer(self, ask_id, value):
        self.sent.append(("answer", ask_id, value))

    def interrupt(self):
        self.interrupted += 1

    def alive(self):
        return not self.stopped

    def stop(self, wait=5):
        self.stopped = True

    def emit(self, ev):
        self.q.put((self, ev))


def boot(run_dir):
    sup = cli.TeamSupervisor(run_dir, proc_factory=FakeProc)
    assert sup.boot()
    for p in sup.procs.values():
        p.emit({"type": "ready"})
    sup.tick(0)
    return sup


# ── 1. tablica ─────────────────────────────────────────────────────────────────

class TablicaTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-tab-", dir=_ROOT))
        team = tpl([mem("a"), mem("b"), mem("k", writes=False)])
        self.dir, err = cli._team_create_run(self.root, "Cel testowy", team, shared=True)
        self.assertEqual(err, "")
        self.st = cli.TeamStore(self.dir)

    def test_zaleznosci_paczka_i_cykle(self):
        made, err = self.st.task_create("lead", [{"title": "Pierwsze", "assignee": "a"},
                                                 {"title": "Drugie", "assignee": "b", "depends_on": ["#1"]}])
        self.assertEqual(err, "")
        self.assertEqual([t["id"] for t in made], ["T1", "T2"])
        self.assertEqual(made[1]["depends_on"], ["T1"])
        _m, err = self.st.task_create("lead", [{"title": "X", "depends_on": ["#2"]}, {"title": "Y", "depends_on": ["#1"]}])
        self.assertIn("cykl", err)
        _m, err = self.st.task_create("lead", [{"title": "Z", "depends_on": ["T9"]}])
        self.assertIn("nieistniejącego", err)
        _m, err = self.st.task_create("lead", [{"title": "Z", "assignee": "nikt"}])
        self.assertIn("nie ma członka", err)
        _m, err = self.st.task_create("lead", [{"title": "Z", "depends_on": ["#1"]}])
        self.assertIn("od siebie", err)
        self.assertEqual(len(self.st.board()["tasks"]), 2)   # błędna paczka nie zostawia śladu
        made, _ = self.st.task_create("lead", [{"title": "Czytaj", "assignee": "k", "kind": "build"}])
        self.assertEqual(made[0]["kind"], "research")     # członek tylko do odczytu nie dostaje build
        _m, err = self.st.task_create("lead", [{"title": f"t{i}"} for i in range(40)])
        self.assertIn("limit", err)

    def test_claim_przypisanie_zaleznosci_i_wynik(self):
        self.st.task_create("lead", [{"title": "A1", "assignee": "a"}, {"title": "B1", "assignee": "b", "depends_on": ["#1"]},
                                     {"title": "Wolne", "kind": "build"}])
        t, err = self.st.task_claim("b")
        self.assertEqual((t["id"], err), ("T3", ""))     # T2 czeka na T1, więc b bierze wolne zadanie
        self.assertIsNone(self.st.task_claim("k")[0])     # tylko odczyt: build nie dla niego
        _t, err = self.st.task_claim("b", "T2")
        self.assertIn("czeka na T1", err)
        _t, err = self.st.task_claim("b", "T1")
        self.assertIn("nie jest dla Ciebie", err)
        t, _ = self.st.task_claim("a")
        self.assertEqual(t["id"], "T1")
        _t, err = self.st.task_update("a", "T1", "done", "krótko")
        self.assertIn("10 znaków", err)
        _t, err = self.st.task_update("b", "T1", "done", "Zrobiłem cudze zadanie w całości")
        self.assertIn("nie jest Twoje", err)
        t, err = self.st.task_update("a", "T1", "done", "Zapisałem plik a.txt z treścią")
        self.assertEqual((t["status"], err), ("done", ""))   # bez kopii git: od razu gotowe
        t, _ = self.st.task_claim("b", "T2")
        self.assertEqual(t["status"], "in_progress")

    def test_wyscig_dwoch_procesow(self):
        self.st.task_create("lead", [{"title": f"Zadanie {i}"} for i in range(12)])
        code = ("import importlib.machinery as m, importlib.util as u, json, sys\n"
                "l = m.SourceFileLoader('c', sys.argv[1]); s = u.spec_from_loader('c', l); c = u.module_from_spec(s)\n"
                "l.exec_module(c)\nst = c.TeamStore(sys.argv[2]); got = []\n"
                "while True:\n    t, e = st.task_claim(sys.argv[3])\n    if not t: break\n    got.append(t['id'])\n"
                "print(json.dumps(got))\n")
        procs = [subprocess.Popen([sys.executable, "-c", code, SCRIPT, str(self.dir), who], stdout=subprocess.PIPE,
                                  text=True, env=os.environ, encoding="utf-8") for who in ("a", "b")]
        got = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
        self.assertFalse(set(got[0]) & set(got[1]), got)
        self.assertEqual(sorted(got[0] + got[1], key=lambda x: int(x[1:])), [f"T{i}" for i in range(1, 13)])
        claimed = [t["claimed_by"] for t in self.st.board()["tasks"]]
        self.assertEqual(claimed.count("a") + claimed.count("b"), 12)

    # 2. wiadomości
    def test_wiadomosci_adresaci_i_kursor(self):
        self.st.send("human", "all", "Do wszystkich")
        self.st.send("a", "lead", "Pytanie do prowadzącego")
        self.st.send("lead", "b", "Tylko dla b", "T1")
        self.st.send("b", "human", "Dla człowieka")
        _m, err = self.st.send("a", "ktos", "x")
        self.assertIn("nie ma adresata", err)
        self.assertEqual([m["text"] for m in self.st.inbox("lead")], ["Do wszystkich", "Pytanie do prowadzącego"])
        self.assertEqual(self.st.inbox("lead"), [])      # kursor przesunięty
        self.assertEqual([m["text"] for m in self.st.inbox("b", mark=False)], ["Do wszystkich", "Tylko dla b"])
        self.assertEqual(len(self.st.inbox("b")), 2)
        self.assertEqual([m["text"] for m in self.st.inbox("a")], ["Do wszystkich"])   # własnej nie dostaje
        self.st.send("lead", "all", "Druga runda")
        self.assertEqual([m["text"] for m in self.st.inbox("b")], ["Druga runda"])
        msg = self.st.messages()[0]
        self.assertTrue(MESSAGE_KEYS <= set(msg))
        evs = [e for e in self.st.events() if e["type"] == "team_message"]
        self.assertEqual(len(evs), 5)
        self.assertEqual(evs[0]["message"]["id"], f"m{evs[0]['seq']}")

    def test_szablony_wbudowane_i_wlasne(self):
        for name, t in cli._TEAM_BUILTINS.items():
            ok, err = cli._team_template_check(t)
            self.assertEqual(err, "", name)
        self.assertIsNone(cli._TEAM_BUILTINS["naprawa"]["lead"])
        _t, err = cli._team_template_check(tpl([mem(f"m{i}") for i in range(8)]))
        self.assertIn("Najwyżej 8", err)
        path, err = cli._team_template_save(tpl([mem("x")]) | {"name": "Mój Zespół"}, "project", cwd=self.root)
        self.assertEqual(err, "")
        self.assertTrue(path.endswith("moj-zespol.json"))
        got, err = cli._team_template_get("moj-zespol", cwd=self.root)
        self.assertEqual((got["members"][0]["id"], err), ("x", ""))
        names = {t["name"] for t in cli._team_templates_list(self.root)}
        self.assertTrue({"para", "produkt", "naprawa", "przeglad", "moj-zespol"} <= names)


# ── 6. tryb tekstowy ──────────────────────────────────────────────────────────

class BlokTekstowyTests(unittest.TestCase):
    def test_parser(self):
        p = cli._team_parse_block
        ok = 'Zrobione.\n```zespol\n{"status":"done","result":"Zapisałem a.txt","messages":[{"to":"lead","text":"hej"}]}\n```'
        self.assertEqual(p(ok)["result"], "Zapisałem a.txt")
        self.assertIsNone(p('```zespol\n{"status": "done", "result": \n```'))   # błędny JSON = brak bloku
        self.assertIsNone(p("Bez bloku."))
        many = '```zespol\n{"status":"blocked"}\n```\ntekst\n```zespol\n{"status":"done","result":"drugi blok"}\n```'
        self.assertEqual(p(many)["result"], "drugi blok")
        self.assertIsNone(p('```zespol\n[1, 2]\n```'))

    def test_blok_zamyka_zadanie_czlonka_tekstowego(self):
        root = Path(tempfile.mkdtemp(prefix="zespol-txt-", dir=_ROOT))
        run_dir, _ = cli._team_create_run(root, "Cel", tpl([mem("a", brain="lopus")], lead=False), shared=True)
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Zadanie", "assignee": "a"}])
        sup = boot(run_dir)
        a = sup.procs["a"]
        self.assertEqual(sup.member("a")["tools"], "text")
        self.assertIn("```zespol", a.sent[-1])
        a.emit({"type": "assistant", "tekst": 'Gotowe.\n```zespol\n{"status":"done","result":"Opisałem przyczynę błędu",'
                                              '"messages":[{"to":"human","text":"Skończyłem"}]}\n```'})
        a.emit({"type": "turn_end", "ok": True, "credits": 0, "seconds": 1})
        sup.tick(0)
        t = st.board()["tasks"][0]
        self.assertEqual((t["status"], t["result"]), ("done", "Opisałem przyczynę błędu"))
        self.assertEqual(st.messages()[-1]["to"], "human")


# ── 3. git w repozytorium tymczasowym ─────────────────────────────────────────

class GitTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-git-", dir=_ROOT))
        self.proj = make_repo(self.root)

    def run_team(self, tasks, **policy):
        run_dir, err = cli._team_create_run(self.proj, "Zmiany w README", tpl([mem("a"), mem("b")], lead=False, **policy))
        self.assertEqual(err, "")
        cli.TeamStore(run_dir).task_create("template", tasks)
        sup = boot(run_dir)
        return run_dir, cli.TeamStore(run_dir), sup

    def finish_task(self, sup, st, who, tid, edit):
        t, _ = st.task_claim(who, tid)
        self.assertIsNotNone(t)
        edit(Path(sup.member(who)["worktree"]))
        t, err = st.task_update(who, tid, "done", f"Zmieniłem pliki w zadaniu {tid}")
        self.assertEqual((t["status"], err), ("merge_queue", ""))
        sup._commit_done(sup.member(who))
        sup._merge_start()
        sup.merge_thread.join(120)
        sup._merge_poll()
        return next(x for x in st.board()["tasks"] if x["id"] == tid)

    def test_kopie_scalanie_konflikt_apply_i_sprzatanie(self):
        run_dir, st, sup = self.run_team([{"title": "Plik A", "assignee": "a"}, {"title": "README od A", "assignee": "a"},
                                          {"title": "README od B", "assignee": "b"}])
        run = st.load_run()
        integ = run["integration_branch"]
        self.assertTrue(re.fullmatch(r"codo/zespol-test-[0-9a-f]{4}", integ), integ)
        branches = git(self.proj, "branch", "--format=%(refname:short)").split()
        self.assertIn(integ, branches)
        self.assertIn(integ + "--a", branches)          # bez kolizji gałęzi „a” i „a/b”
        self.assertIn(".doma/", (self.proj / ".git" / "info" / "exclude").read_text(encoding="utf-8"))
        t = self.finish_task(sup, st, "a", "T1", lambda wt: (wt / "a.txt").write_text("od a\n", encoding="utf-8"))
        self.assertEqual((t["status"], t["merge"]["state"]), ("done", "merged"))
        self.assertEqual(git(self.proj, "show", f"{integ}:a.txt"), "od a")
        self.assertIn("zespół T1", git(self.proj, "log", "--format=%s", integ + "--a"))   # automatyczny commit
        self.assertFalse(list((Path(sup.member("a")["worktree"]) / ".doma").glob("*")) and
                         ".doma" in git(self.proj, "ls-tree", "-r", "--name-only", integ))
        t = self.finish_task(sup, st, "a", "T2", lambda wt: (wt / "README.md").write_text("# Projekt\n\nlinia od a\n", encoding="utf-8"))
        self.assertEqual(t["status"], "done")
        t = self.finish_task(sup, st, "b", "T3", lambda wt: (wt / "README.md").write_text("# Projekt\n\nlinia od b\n", encoding="utf-8"))
        self.assertEqual((t["status"], t["merge"]["state"], t["merge"]["conflicts"]), ("in_progress", "conflict", ["README.md"]))
        self.assertNotEqual(subprocess.run(["git", "-C", run["integration_path"], "rev-parse", "-q", "--verify",
                                            "MERGE_HEAD"], capture_output=True).returncode, 0)   # merge --abort
        self.assertEqual(git(run["integration_path"], "status", "--porcelain"), "")
        merges = [e for e in st.events() if e["type"] == "team_merge"]
        self.assertEqual([e["state"] for e in merges if e["task_id"] == "T3"][-1], "conflict")
        # koniec pracy: apply odmawia przy brudnym projekcie, potem scala
        sup.finalize()
        self.assertEqual(st.load_run()["status"], "review_final")
        done = [e for e in st.events() if e["type"] == "team_done"][-1]
        self.assertEqual(done["diff_stat"]["files"], 2)
        self.assertEqual(done["apply_options"], ["merge", "branch"])
        (self.proj / "README.md").write_text("zmiana człowieka\n", encoding="utf-8")
        ev = cli.team_apply(run_dir, "merge")
        self.assertFalse(ev["ok"])
        self.assertIn("niezatwierdzone", ev["detail"])
        git(self.proj, "checkout", "--", "README.md")
        ev = cli.team_apply(run_dir, "merge")
        self.assertTrue(ev["ok"], ev)
        self.assertEqual((self.proj / "a.txt").read_text(encoding="utf-8"), "od a\n")
        self.assertEqual(st.load_run()["status"], "applied")
        res = cli.team_cleanup(run_dir)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["removed"], 3)
        self.assertEqual(res["branches_left"], [integ + "--b"])   # niescalona praca b zostaje na gałęzi
        self.assertFalse(Path(run["integration_path"]).exists())
        self.assertNotIn(integ, git(self.proj, "branch", "--format=%(refname:short)").split())
        self.assertNotIn("[codo/", git(self.proj, "worktree", "list"))

    def test_check_nie_przeszedl(self):
        run_dir, st, sup = self.run_team([{"title": "Plik", "assignee": "a"}], check="false")
        integ_path = st.load_run()["integration_path"]
        head = git(integ_path, "rev-parse", "HEAD")
        t = self.finish_task(sup, st, "a", "T1", lambda wt: (wt / "x.txt").write_text("x\n", encoding="utf-8"))
        self.assertEqual((t["status"], t["merge"]["state"]), ("in_progress", "check_failed"))
        self.assertEqual(git(integ_path, "rev-parse", "HEAD"), head)    # reset --hard HEAD~1
        self.assertFalse((Path(integ_path) / "x.txt").exists())
        self.assertIn("SPRAWDZENIE", (sup._start_job(sup.member("a")) and sup.procs["a"].sent[-1]))
        sup.finalize("stopped")
        cli.team_cleanup(run_dir)

    def test_brak_commita_i_apply_przed_koncem(self):
        empty = self.root / "pusty"
        empty.mkdir()
        git(empty, "init", "-q")
        _d, err = cli._team_create_run(empty, "Cel", tpl([mem("a")]))
        self.assertIn("commita", err)
        run_dir, err = cli._team_create_run(self.proj, "Cel", tpl([mem("a")], lead=False))
        cli.TeamStore(run_dir).task_create("template", [{"title": "Czeka", "assignee": "a"}])
        sup = boot(run_dir)
        ev = cli.team_apply(run_dir, "merge")
        self.assertFalse(ev["ok"])
        self.assertIn("jeszcze pracuje", ev["detail"])
        sup.finalize("stopped")
        ev = cli.team_apply(run_dir, "branch")
        self.assertFalse(ev["ok"])
        self.assertIn("nie zostawił zmian", ev["detail"])
        self.assertTrue(cli.team_cleanup(run_dir)["ok"])


# ── 4. limity ──────────────────────────────────────────────────────────────────

class LimityTests(unittest.TestCase):
    def make(self, members, **policy):
        root = Path(tempfile.mkdtemp(prefix="zespol-lim-", dir=_ROOT))
        run_dir, err = cli._team_create_run(root, "Cel", tpl(members, lead=False, **policy), shared=True)
        self.assertEqual(err, "")
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Dla a", "assignee": "a"}, {"title": "Dla b", "assignee": "b"}])
        return st, boot(run_dir)

    def test_budzet_zespolu(self):
        st, sup = self.make([mem("a"), mem("b")], budget_kr=40)
        a, b = sup.procs["a"], sup.procs["b"]
        self.assertTrue(sup.rt["a"]["busy"] and sup.rt["b"]["busy"])
        a.emit({"type": "turn_end", "ok": True, "credits": 50, "seconds": 2})
        sup.tick(0)
        run = st.load_run()
        self.assertEqual((run["status"], run["spent_kr"]), ("over_budget", 50))
        self.assertGreaterEqual(b.interrupted, 1)
        self.assertTrue(a.stopped and b.stopped)
        evs = st.events()
        self.assertTrue(any(e["type"] == "team_budget" and e["warn"] for e in evs))
        self.assertEqual([e for e in evs if e["type"] == "team_done"][-1]["status"], "over_budget")

    def test_budzet_i_czas_czlonka(self):
        st, sup = self.make([mem("a", budget_kr=10), mem("b")], budget_kr=1000, member_turn_minutes=0.0005)
        a, b = sup.procs["a"], sup.procs["b"]
        a.emit({"type": "turn_end", "ok": True, "credits": 15, "seconds": 1})
        time.sleep(0.05)
        sup.tick(0)
        self.assertEqual(sup.member("a")["status"], "over_budget")
        self.assertEqual(st.board()["tasks"][0]["status"], "failed")
        self.assertGreaterEqual(b.interrupted, 1)          # tura dłuższa niż limit: interrupt
        b.emit({"type": "turn_end", "ok": False, "credits": 0, "seconds": 1})
        sup.tick(0)
        t = st.board()["tasks"][1]
        self.assertEqual(t["status"], "failed")
        self.assertIn("Przerwane", t["result"])
        # oba zadania zamknięte (nieudane), prowadzącego nie ma: zespół kończy się sam, bez zmian do scalenia
        self.assertEqual(st.load_run()["status"], "done")
        self.assertEqual(sup.member("a")["status"], "over_budget")

    def test_pauza_i_zgoda(self):
        st, sup = self.make([mem("a"), mem("b")])
        a = sup.procs["a"]
        a.emit({"type": "ask", "id": "1", "pytanie": "Uruchomić npm test?", "szczegol": "npm test", "powod": "",
                "opcje": [{"value": 1, "label": "Tak"}]})
        sup.tick(0)
        self.assertEqual(sup.member("a")["status"], "waiting_approval")
        st.control(type="answer", ask_id="a:1", value=1, by="terminal")
        sup.tick(0)
        self.assertIn(("answer", "1", 1), a.sent)
        done = [e for e in st.events() if e["type"] == "team_ask_done"][-1]
        self.assertEqual((done["ask_id"], done["value"], done["by"]), ("a:1", 1, "terminal"))
        st.control(type="pause", by="terminal")
        sup.tick(0)
        run = st.load_run()
        self.assertEqual((run["status"], run["paused_from"]), ("paused", "running"))
        self.assertTrue(sup.exit and a.stopped)
        self.assertEqual(run["status"] in cli._TEAM_RESUMABLE, True)
        # proste wznowienie: nowy nadzorca, członek dostaje „resume”, zadanie w toku wraca z promptem wznowienia
        st2 = cli.TeamStore(st.dir)
        r = st2.load_run()
        r["members"][0]["convo_id"] = "rozmowa-a"
        st2.save_run(r)
        sup2 = boot(st.dir)
        self.assertEqual(sup2.procs["a"].sent[0], {"type": "resume", "id": "rozmowa-a"})
        self.assertIn("WZNOWIENIE", sup2.procs["a"].sent[-1])
        sup2.finalize("stopped")


# ── etap 2: przeglądy, zgody, konflikty, prowadzący (bez procesów) ─────────────

def turn(sup, who, text="", **ev):
    """Koniec tury członka (atrapa): opcjonalny tekst asystenta, potem turn_end i jeden tick nadzorcy."""
    p = sup.procs[who]
    if text:
        p.emit({"type": "assistant", "tekst": text})
    p.emit({"type": "turn_end", "ok": True, "credits": 0, "seconds": 1, **ev})
    sup.tick(0)


def task(st, tid):
    return next(t for t in st.board()["tasks"] if t["id"] == tid)


def events(st, kind, **match):
    return [e for e in st.events() if e["type"] == kind and all(e.get(k) == v for k, v in match.items())]


class member_env:
    """Narzędzia team_* tak, jak widzi je członek (zmienne środowiska procesu członka)."""

    def __init__(self, run_dir, who, cwd=None):
        self.env = {"CODO_ZESPOL_DIR": str(run_dir), "CODO_ZESPOL_CZLONEK": who,
                    "CODO_ZESPOL_ROLA": "lead" if who == "lead" else "member"}
        self.cwd = cwd

    def __enter__(self):
        self.prev = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.prev_cwd = os.getcwd()
        if self.cwd:
            os.chdir(self.cwd)
        return self

    def __exit__(self, *a):
        os.chdir(self.prev_cwd)
        for k, v in self.prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class PrzegladTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-rev-", dir=_ROOT))

    def test_przeglad_krzyzowy_w_kopiach(self):
        proj = make_repo(self.root)
        run_dir, _ = cli._team_create_run(proj, "Cel", tpl([mem("a"), mem("b"), mem("k", writes=False)], lead=False,
                                                           review="cross"))
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Plik A", "assignee": "a", "detail": "Utwórz a.txt"}])
        sup = boot(run_dir)
        wt = Path(sup.member("a")["worktree"])
        (wt / "a.txt").write_text("pierwsza wersja\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Zapisałem a.txt w swojej kopii")
        turn(sup, "a")
        t = task(st, "T1")
        self.assertEqual((t["status"], t["reviewer"]), ("review", "k"))   # najpierw członek tylko do odczytu
        self.assertEqual(events(st, "team_merge", task_id="T1")[-1]["state"], "reviewing")
        prompt = sup.procs["k"].sent[-1]
        self.assertIn("[ZESPÓŁ: PRZEGLĄD T1]", prompt)
        self.assertIn("+pierwsza wersja", prompt)                          # diff integracja...kopia wykonawcy
        _t, err = st.task_review("b", "T1", "approve")
        self.assertIn("należy do k", err)
        _t, err = st.task_review("k", "T1", "changes", "krótko")
        self.assertIn("uwagi", err)
        st.task_review("k", "T1", "changes", "Dopisz drugą linię w a.txt")
        turn(sup, "k")
        t = task(st, "T1")
        self.assertEqual((t["status"], t["review"]["round"], t["commit"]), ("in_progress", 1, ""))
        self.assertIn("[ZESPÓŁ: POPRAWKI T1]", sup.procs["a"].sent[-1])
        self.assertIn("Dopisz drugą linię", sup.procs["a"].sent[-1])
        (wt / "a.txt").write_text("pierwsza wersja\ndruga linia\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Dopisałem drugą linię w a.txt")
        turn(sup, "a")
        self.assertEqual(task(st, "T1")["status"], "review")
        self.assertIn("+druga linia", sup.procs["k"].sent[-1])
        st.task_review("k", "T1", "approve", "Teraz dobrze.")
        turn(sup, "k")
        sup.merge_thread.join(60)
        sup.tick(0)
        t = task(st, "T1")
        self.assertEqual((t["status"], t["merge"]["state"], t["review"]["verdict"]), ("done", "merged", "approve"))
        self.assertEqual(git(proj, "show", f"{st.load_run()['integration_branch']}:a.txt"), "pierwsza wersja\ndruga linia")
        sup.finalize("stopped")
        cli.team_cleanup(run_dir)

    def test_trzy_rundy_blokuja_i_tryb_tekstowy(self):
        run_dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a"), mem("k", writes=False, brain="lopus")],
                                                                lead=False, review="cross"), shared=True)
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Zmiana", "assignee": "a"}])
        sup = boot(run_dir)
        for rnd in (1, 2, 3):
            st.task_update("a", "T1", "done", f"Zrobiłem zmianę, runda {rnd}")
            turn(sup, "a")
            self.assertEqual(task(st, "T1")["status"], "review")                 # wspólny folder: przegląd bez kopii
            self.assertIn("```zespol", sup.procs["k"].sent[-1])                  # recenzent w trybie tekstowym
            turn(sup, "k", 'Uwagi.\n```zespol\n{"verdict":"changes","notes":"Brakuje testu dla pustego pliku"}\n```')
        t = task(st, "T1")
        self.assertEqual((t["status"], t["review"]["round"]), ("blocked", 3))
        _t, err = st.task_review("k", "T1", "approve")
        self.assertIn("nie czeka", err)
        t, err = st.task_review("lead", "T1", "approve", "Prowadzący przyjmuje mimo uwag.")
        self.assertEqual((t["status"], err), ("done", ""))
        sup.finalize("stopped")

    def test_przeglad_prowadzacego_i_przypomnienie(self):
        run_dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a")], review="lead"), shared=True)
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Zmiana", "assignee": "a"}])
        sup = boot(run_dir)
        turn(sup, "lead", "Plan jest na tablicy.")                               # tura planu
        self.assertEqual(st.load_run()["status"], "running")
        st.task_update("a", "T1", "done", "Zrobiłem zmianę w pliku")
        turn(sup, "a")
        self.assertEqual(task(st, "T1")["reviewer"], "lead")
        self.assertIn("[ZESPÓŁ: PRZEGLĄD T1]", sup.procs["lead"].sent[-1])
        turn(sup, "lead", "Przejrzałem.")                                         # bez werdyktu: przypomnienie
        self.assertIn("Zakończ przegląd T1", sup.procs["lead"].sent[-1])
        turn(sup, "lead", "Nadal bez werdyktu, ale wszystko wygląda dobrze.")    # drugi raz: przegląd pominięty
        t = task(st, "T1")
        self.assertEqual((t["status"], t["review"]["by"]), ("done", "nadzorca"))
        sup.finalize("stopped")


class ZgodyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-zgody-", dir=_ROOT))

    def test_plan_do_zatwierdzenia(self):
        run_dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a"), mem("b")], approve_plan=True), shared=True)
        st = cli.TeamStore(run_dir)
        sup = boot(run_dir)
        self.assertIn("[ZESPÓŁ: PLAN]", sup.procs["lead"].sent[-1])
        st.task_create("lead", [{"title": "Pierwsze", "assignee": "a"}, {"title": "Drugie", "assignee": "b"}])
        turn(sup, "lead", "Dwa zadania.")
        run = st.load_run()
        self.assertEqual(run["status"], "waiting_human")
        plan = events(st, "team_plan")[-1]
        self.assertEqual(([t["id"] for t in plan["tasks"]], plan["note"], plan["round"]), (["T1", "T2"], "Dwa zadania.", 0))
        sup.tick(0)
        self.assertFalse([x for x in sup.procs["a"].sent if isinstance(x, str)])   # praca czeka na decyzję
        st.control(type="plan_decide", approve=False, notes="Dodaj zadanie na testy.")
        sup.tick(0)
        self.assertEqual(st.load_run()["status"], "planning")
        self.assertIn("Dodaj zadanie na testy.", sup.procs["lead"].sent[-1])
        turn(sup, "lead", "Poprawiony plan.")
        self.assertEqual((st.load_run()["status"], events(st, "team_plan")[-1]["round"]), ("waiting_human", 1))
        self.assertIn("cykl", st.plan_apply("human", [{"id": "T1", "depends_on": ["T2"]}, {"id": "T2", "depends_on": ["T1"]}], dry=True))
        st.control(type="plan_decide", approve=True, tasks=[{"id": "T1", "title": "Pierwsze, poprawione"},
                                                             {"title": "Testy", "assignee": "b", "depends_on": ["T1"]}])
        sup.tick(0)
        tasks = {t["id"]: t for t in st.board()["tasks"]}
        self.assertEqual((tasks["T1"]["title"], tasks["T2"]["status"], tasks["T3"]["created_by"], tasks["T3"]["depends_on"]),
                         ("Pierwsze, poprawione", "cancelled", "human", ["T1"]))
        self.assertEqual(st.load_run()["status"], "running")
        self.assertIn("[ZESPÓŁ: ZADANIE T1]", sup.procs["a"].sent[-1])
        sup.finalize("stopped")

    def test_plan_odrzucony_bez_uwag_konczy(self):
        run_dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a")], approve_plan=True), shared=True)
        st = cli.TeamStore(run_dir)
        sup = boot(run_dir)
        st.task_create("lead", [{"title": "Jedno", "assignee": "a"}])
        turn(sup, "lead", "Plan.")
        st.control(type="plan_decide", approve=False)
        sup.tick(0)
        self.assertEqual(st.load_run()["status"], "stopped")
        self.assertIn("Plan odrzucony", events(st, "team_done")[-1]["summary"])

    def test_zgoda_na_kazde_scalenie(self):
        proj = make_repo(self.root)
        run_dir, _ = cli._team_create_run(proj, "Cel", tpl([mem("a")], lead=False, approve_merge="each"))
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": f"Plik {i}", "assignee": "a", **({"depends_on": [f"#{i - 1}"]} if i > 1 else {})}
                                    for i in (1, 2, 3)])
        sup = boot(run_dir)
        wt = Path(sup.member("a")["worktree"])
        integ = st.load_run()["integration_branch"]
        for i in (1, 2, 3):
            (wt / f"p{i}.txt").write_text(f"plik {i}\n", encoding="utf-8")
            st.task_update("a", f"T{i}", "done", f"Zapisałem p{i}.txt w kopii")
            turn(sup, "a")
            self.assertEqual(task(st, f"T{i}")["merge"]["state"], "waiting_human")
            self.assertEqual(events(st, "team_merge", task_id=f"T{i}")[-1]["state"], "waiting_human")
            self.assertIsNone(sup.merge_thread)                                   # bez zgody nic się nie scala
            if i == 1:
                st.control(type="merge_decide", task_id="T1", approve=True)
                sup.tick(0)
                sup.merge_thread.join(60)
                sup.tick(0)
                self.assertEqual((task(st, "T1")["status"], task(st, "T1")["merge"]["approved"]), ("done", True))
                self.assertEqual(git(proj, "show", f"{integ}:p1.txt"), "plik 1")
            elif i == 2:
                st.control(type="merge_decide", task_id="T2", approve=False, notes="Plik ma mieć dwie linie.")
                sup.tick(0)
                t = task(st, "T2")
                self.assertEqual((t["status"], t["review"]["by"], t["review"]["verdict"]), ("in_progress", "human", "changes"))
                self.assertIn("Człowiek nie przyjął", sup.procs["a"].sent[-1])
                self.assertEqual(events(st, "team_merge", task_id="T2")[-1]["state"], "rejected")
                (wt / "p2.txt").write_text("plik 2\ndruga linia\n", encoding="utf-8")
                turn(sup, "a", "Poprawiłem plik p2.txt, teraz dwie linie.")      # wynik z ostatniej wiadomości
                self.assertEqual(task(st, "T2")["merge"]["state"], "waiting_human")
                st.control(type="merge_decide", task_id="T2", approve=True)
                sup.tick(0)
                sup.merge_thread.join(60)
                sup.tick(0)
                self.assertEqual(git(proj, "show", f"{integ}:p2.txt"), "plik 2\ndruga linia")
            else:
                st.control(type="merge_decide", task_id="T3", approve=False)
                sup.tick(0)
                self.assertEqual(task(st, "T3")["status"], "cancelled")
        sup.finalize("stopped")
        cli.team_cleanup(run_dir)


class KonfliktTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-konf-", dir=_ROOT))
        self.proj = make_repo(self.root)

    def merge(self, sup):
        sup.tick(0)
        if sup.merge_thread:
            sup.merge_thread.join(60)
        sup.tick(0)

    def test_wykonawca_rozwiazuje_konflikt_u_siebie(self):
        run_dir, _ = cli._team_create_run(self.proj, "Cel", tpl([mem("a"), mem("b")], lead=False))
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "README od A", "assignee": "a"}, {"title": "README od B", "assignee": "b"}])
        sup = boot(run_dir)
        wa, wb = Path(sup.member("a")["worktree"]), Path(sup.member("b")["worktree"])
        (wa / "README.md").write_text("# Projekt\n\nlinia od a\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Zmieniłem README w kopii a")
        turn(sup, "a")
        self.merge(sup)
        (wb / "README.md").write_text("# Projekt\n\nlinia od b\n", encoding="utf-8")
        st.task_update("b", "T2", "done", "Zmieniłem README w kopii b")
        turn(sup, "b")
        self.merge(sup)
        prompt = sup.procs["b"].sent[-1]
        self.assertIn("[ZESPÓŁ: KONFLIKT T2]", prompt)
        self.assertIn("README.md", prompt)
        self.assertEqual(subprocess.run(["git", "-C", str(wb), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                                        capture_output=True).returncode, 0)    # scalanie trwa w kopii wykonawcy
        self.assertIn("<<<<<<<", (wb / "README.md").read_text(encoding="utf-8"))
        st.task_update("b", "T2", "done", "Konflikt bez zmian, znaczniki zostały")   # znaczniki: kolejna próba
        turn(sup, "b")
        t = task(st, "T2")
        self.assertEqual((t["status"], t["merge"]["state"]), ("in_progress", "conflict"))
        # merge --abort i od razu kolejna próba: nadzorca znów zaczyna scalanie w kopii b
        self.assertEqual(sum("[ZESPÓŁ: KONFLIKT T2]" in x for x in sup.procs["b"].sent if isinstance(x, str)), 2)
        self.assertIn("<<<<<<<", (wb / "README.md").read_text(encoding="utf-8"))
        (wb / "README.md").write_text("# Projekt\n\nlinia od a\nlinia od b\n", encoding="utf-8")
        st.task_update("b", "T2", "done", "Połączyłem obie linie w README")
        turn(sup, "b")
        self.merge(sup)
        t = task(st, "T2")
        self.assertEqual((t["status"], t["merge"]["state"]), ("done", "merged"))
        integ = st.load_run()["integration_branch"]
        self.assertEqual(git(self.proj, "show", f"{integ}:README.md"), "# Projekt\n\nlinia od a\nlinia od b")
        sup.finalize("stopped")
        cli.team_cleanup(run_dir)

    def test_scalanie_na_koncu(self):
        run_dir, _ = cli._team_create_run(self.proj, "Cel", tpl([mem("a"), mem("b")], lead=False, merge="at_end"))
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Plik A", "assignee": "a"},
                                    {"title": "Plik B", "assignee": "b", "depends_on": ["#1"]}])
        sup = boot(run_dir)
        integ = st.load_run()["integration_branch"]
        head = git(self.proj, "rev-parse", integ)
        (Path(sup.member("a")["worktree"]) / "a.txt").write_text("od a\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Zapisałem a.txt w kopii a")
        turn(sup, "a")
        self.assertEqual((task(st, "T1")["status"], git(self.proj, "rev-parse", integ)), ("merge_queue", head))
        sup.tick(0)
        self.assertIn("[ZESPÓŁ: ZADANIE T2]", sup.procs["b"].sent[-1])          # zależność czeka w kolejce
        wb = Path(sup.member("b")["worktree"])
        self.assertEqual((wb / "a.txt").read_text(encoding="utf-8"), "od a\n")                  # commit zależności w kopii b
        (wb / "b.txt").write_text("od b\n", encoding="utf-8")
        st.task_update("b", "T2", "done", "Zapisałem b.txt w kopii b")
        turn(sup, "b")
        for _ in range(20):
            if st.load_run()["status"] in cli._TEAM_RUN_END:
                break
            self.merge(sup)
        self.assertIn("merging", [e["status"] for e in events(st, "team_state")])
        self.assertEqual([task(st, x)["status"] for x in ("T1", "T2")], ["done", "done"])
        self.assertEqual(st.load_run()["status"], "review_final")
        self.assertEqual(git(self.proj, "show", f"{integ}:b.txt"), "od b")
        cli.team_cleanup(run_dir)


class ProwadzacyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-lead-", dir=_ROOT))
        self.dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a"), mem("b")]), shared=True)
        self.st = cli.TeamStore(self.dir)
        self.sup = boot(self.dir)
        self.st.task_create("lead", [{"title": "Zajęcie b", "assignee": "b"}])
        turn(self.sup, "lead", "Plan: jedno zadanie dla b.")
        self.assertEqual(self.sup.rt["b"]["task"], "T1")

    def tearDown(self):
        self.sup.finalize("stopped")

    def test_narzedzia_prowadzacego(self):
        st, sup = self.st, self.sup
        with member_env(self.dir, "a"):
            names = {t["function"]["name"] for t in cli.enabled_tools()}
            self.assertIn("team_review", names)
            self.assertFalse(names & {"team_member_add", "team_task_edit", "team_ask_human", "team_finish", "team_run"})
            self.assertIn("ODRZUCONE", cli.run_tool("team_member_add", {"name": "X", "role": "y"}, True))
        with member_env(self.dir, "lead"):
            self.assertTrue({"team_member_add", "team_task_edit", "team_ask_human"} <= {t["function"]["name"] for t in cli.enabled_tools()})
            out = cli.run_tool("team_member_add", {"name": "Tester", "role": "Testy", "writes": False}, True)
            self.assertIn("tester", out)
            st.task_create("lead", [{"title": "Długie", "assignee": "a"}])
            sup.tick(0)
            self.assertEqual(sup.rt["a"]["task"], "T2")
            self.assertIn("Zapisano", cli.run_tool("team_task_edit", {"id": "T2", "patch": {"status": "cancelled"}}, True))
            out = cli.run_tool("team_ask_human", {"question": "Który kolor?", "options": ["jasny", "ciemny"]}, True)
            qid = re.search(r"q-[0-9a-f]{4}", out).group(0)
        sup.tick(0)
        m = sup.member("tester")
        self.assertEqual((m["status"], m["isolation"], m["writes"]), ("starting", "readonly", False))
        self.assertIn("tester", sup.procs)
        self.assertGreaterEqual(sup.procs["a"].interrupted, 1)                  # anulowane zadanie przerywa turę
        q = events(st, "team_question")[-1]
        self.assertEqual((q["id"], q["from"], q["options"]), (qid, "lead", ["jasny", "ciemny"]))
        self.assertEqual(st.state()["pending_questions"][0]["id"], qid)
        self.assertEqual(cli._team_say(st, "lead", "Jasny.", reply_to=qid), "")
        sup.tick(0)
        self.assertEqual(st.state()["pending_questions"], [])
        self.assertEqual(events(st, "team_question_done")[-1]["id"], qid)
        for i in range(5):
            st.control(type="member_add", member={"name": f"Dodatkowy {i}"}, by="human")
        sup.tick(0)
        self.assertEqual(len(st.load_run()["members"]), 8)                     # limit razem z prowadzącym
        self.assertTrue(events(st, "team_error"))

    def test_czlowiek_dodaje_poprawia_i_zatrzymuje(self):
        st, sup = self.st, self.sup
        made, err = st.task_create("human", [{"title": "Od człowieka", "assignee": "a"}])
        self.assertEqual((made[0]["created_by"], err), ("human", ""))
        _t, err = st.task_edit("human", "T2", {"status": "done"})
        self.assertIn("cancelled albo open", err)
        sup.tick(0)
        self.assertEqual(task(st, "T2")["status"], "in_progress")
        _t, err = st.task_edit("human", "T2", {"assignee": "b"})
        self.assertIn("tylko w zadaniu open", err)
        t, err = st.task_edit("human", "T2", {"title": "Od człowieka, poprawione"})
        self.assertEqual((t["title"], err), ("Od człowieka, poprawione", ""))
        st.control(type="member_stop", member="a", by="human")
        sup.tick(0)
        t = task(st, "T2")
        self.assertEqual((sup.member("a")["status"], t["status"], t["claimed_by"], t["assignee"]), ("stopped", "open", "", ""))
        self.assertIsNone(sup.procs.get("a"))
        st.task_update("b", "T1", "done", "Zadanie b skończone")
        turn(sup, "b")
        self.assertEqual(task(st, "T2")["claimed_by"], "b")                    # wolne zadanie bierze inny członek


class RezerwacjeTests(unittest.TestCase):
    def test_pliki_zadania_w_toku_sa_zarezerwowane(self):
        root = Path(tempfile.mkdtemp(prefix="zespol-rez-", dir=_ROOT))
        run_dir, _ = cli._team_create_run(root, "Cel", tpl([mem("a"), mem("b")], lead=False), shared=True)
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Backend", "assignee": "a", "files": ["src/api/", "*.css"]},
                                    {"title": "Frontend", "assignee": "b"}])
        st.task_claim("a", "T1")
        (root / "src" / "api").mkdir(parents=True)
        with member_env(run_dir, "b", cwd=root):
            out = cli.run_tool("write_file", {"path": "src/api/cart.py", "content": "x = 1\n"}, True)
            self.assertIn("ODRZUCONE: plik src/api/cart.py należy do zadania T1 (A)", out)
            self.assertIn("ODRZUCONE", cli.run_tool("write_file", {"path": "styl.css", "content": "a{}\n"}, True))
            self.assertNotIn("ODRZUCONE", cli.run_tool("write_file", {"path": "src/web.py", "content": "y = 2\n"}, True))
            run = cli._AcpRun("goose", True, "ask", True)
            with self.assertRaises(cli._AcpError) as ctx:
                run.handle("fs/write_text_file", {"path": str(root / "src" / "api" / "x.py"), "content": "z"})
            self.assertIn("T1", str(ctx.exception.args[0]))
        with member_env(run_dir, "a", cwd=root):
            self.assertNotIn("ODRZUCONE", cli.run_tool("write_file", {"path": "src/api/cart.py", "content": "x\n"}, True))


class AgentSidTests(unittest.TestCase):
    def test_sesje_agentow_w_zapisie_rozmowy(self):
        import contextlib
        import io
        root = Path(tempfile.mkdtemp(prefix="zespol-sid-", dir=_ROOT))
        prev = os.getcwd()
        os.chdir(root)
        try:
            cli.SESSION.pop("convo_id", None)
            cli.SESSION["agent_sid"] = {"codex": "sesja-codex-1", "claude": "sesja-claude-2"}
            cli._convo_save([{"role": "system", "content": "s"}, {"role": "user", "content": "Cześć"}])
            data = next(d for d in cli._convo_list() if d["id"] == cli.SESSION["convo_id"])
            self.assertEqual(data["agent_sid"]["codex"], "sesja-codex-1")
            cli.SESSION.pop("agent_sid", None)
            with contextlib.redirect_stdout(io.StringIO()):
                cli._convo_restore(data, [])
            self.assertEqual(cli.SESSION["agent_sid"], {"codex": "sesja-codex-1", "claude": "sesja-claude-2"})
        finally:
            cli.SESSION.pop("agent_sid", None)
            cli.SESSION.pop("convo_id", None)
            os.chdir(prev)


class DiffLogTests(unittest.TestCase):
    def test_diff_calosci_czlonka_zadania_i_dziennik(self):
        root = Path(tempfile.mkdtemp(prefix="zespol-diff-", dir=_ROOT))
        proj = make_repo(root)
        run_dir, _ = cli._team_create_run(proj, "Cel", tpl([mem("a"), mem("b")], lead=False))
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Plik A", "assignee": "a"}, {"title": "W toku", "assignee": "b"}])
        sup = boot(run_dir)
        (Path(sup.member("a")["worktree"]) / "a.txt").write_text("od a\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Zapisałem a.txt w kopii")
        sup.procs["a"].emit({"type": "tool", "naglowek": "write_file a.txt"})
        turn(sup, "a")
        sup.merge_thread.join(60)
        sup.tick(0)
        wb = Path(sup.member("b")["worktree"])
        (wb / "README.md").write_text("# Projekt\n\nzmiana b\n", encoding="utf-8")
        (wb / "nowy.txt").write_text("raz\ndwa\n", encoding="utf-8")
        d = cli._team_diff(run_dir)
        self.assertEqual((d["scope"], [(f["path"], f["status"], f["added"]) for f in d["files"]]), ("all", [("a.txt", "A", 1)]))
        d = cli._team_diff(run_dir, member="b")
        got = {f["path"]: (f["status"], f["added"], f["removed"]) for f in d["files"]}
        self.assertEqual(got, {"README.md": ("M", 1, 1), "nowy.txt": ("A", 2, 0)})
        self.assertIn("+zmiana b", d["patch"])
        self.assertIn("+dwa", d["patch"])
        d = cli._team_diff(run_dir, task_id="T1")
        self.assertEqual((d["scope"], [f["path"] for f in d["files"]]), ("task:T1", ["a.txt"]))
        self.assertIn("error", cli._team_diff(run_dir, member="nikt"))
        log = cli._team_member_log(run_dir, "a")
        self.assertEqual([e["type"] for e in log["events"]][-2:], ["tool", "turn_end"])
        self.assertEqual(cli._team_member_log(run_dir, "a", since=log["next"])["events"], [])
        self.assertEqual(cli._team_member_log(run_dir, "../run")["events"], [])
        sup.finalize("stopped")
        cli.team_cleanup(run_dir)


class PrIKanalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-pr-", dir=_ROOT))
        self.proj = make_repo(self.root)

    def finished_run(self, **policy):
        run_dir, _ = cli._team_create_run(self.proj, "Dodaj plik", tpl([mem("a")], lead=False, **policy),
                                          source={"kind": "kanal", "channel": "telegram", "reply_to": "12345"})
        st = cli.TeamStore(run_dir)
        st.task_create("template", [{"title": "Plik", "assignee": "a"}])
        sup = boot(run_dir)
        (Path(sup.member("a")["worktree"]) / "x.txt").write_text("x\n", encoding="utf-8")
        st.task_update("a", "T1", "done", "Zapisałem x.txt w kopii")
        turn(sup, "a")
        sup.merge_thread.join(60)
        for _ in range(5):
            sup.tick(0)
        return run_dir, st

    def test_apply_pr(self):
        run_dir, st = self.finished_run()
        done = events(st, "team_done")[-1]
        self.assertEqual((done["status"], done["source"]["channel"], done["source"]["reply_to"]),
                         ("review_final", "telegram", "12345"))
        self.assertEqual(done["apply_options"], ["merge", "branch"])          # bez origin nie ma PR
        ev = cli.team_apply(run_dir, "pr")
        self.assertFalse(ev["ok"])
        self.assertIn("origin", ev["detail"])
        bare = self.root / "zdalne.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        git(self.proj, "remote", "add", "origin", str(bare))
        with unittest.mock.patch.object(cli, "_gh_bin", return_value=None):
            ev = cli.team_apply(run_dir, "pr")
        self.assertIn("gh", ev["detail"])
        log = self.root / "gh.log"
        gh = atrapa(self.root, "gh", "import sys\n"
                    f"with open({str(log)!r}, 'a', encoding='utf-8') as f:\n"
                    "    f.write(' '.join(sys.argv[1:]) + '\\n')\n"
                    "if sys.argv[1:2] == ['pr']:\n"
                    "    print('https://github.com/test/projekt/pull/7')\n")
        with unittest.mock.patch.object(cli, "_gh_bin", return_value=str(gh)):
            ev = cli.team_apply(run_dir, "pr", title="Plik x")
        self.assertTrue(ev["ok"], ev)
        self.assertEqual(ev["pr_url"], "https://github.com/test/projekt/pull/7")
        integ = st.load_run()["integration_branch"]
        self.assertIn(integ, subprocess.run(["git", "-C", str(bare), "branch"], capture_output=True, text=True, encoding="utf-8").stdout)
        self.assertIn(f"--head {integ}", log.read_text(encoding="utf-8"))
        self.assertIn("--base main", log.read_text(encoding="utf-8"))
        self.assertEqual(git(self.proj, "rev-parse", "--abbrev-ref", "HEAD"), "main")   # projekt bez zmiany gałęzi
        cli.team_cleanup(run_dir, keep_branches=True)

    def test_z_kanalu_w_terminalu(self):
        prev = os.getcwd()
        os.chdir(self.proj)
        try:
            with unittest.mock.patch.object(cli, "_team_spawn_supervisor", return_value=0), \
                    unittest.mock.patch.object(cli, "load_endpoint", return_value={"model": "x"}):
                code = cli.cmd_team(["run", "Zrób", "--szablon", "para", "--bg", "--z-kanalu", "discord",
                                     "--odpowiedz-do", "kanal-9"])
            self.assertEqual(code, 0)
            run_dir = max((self.proj / ".doma" / "zespoly").iterdir())
            self.assertEqual(cli.TeamStore(run_dir).load_run()["source"],
                             {"kind": "kanal", "convo_id": "", "channel": "discord", "reply_to": "kanal-9"})
            with unittest.mock.patch.object(cli, "_team_cmd_run", return_value=0) as run:
                cli._team_slash("para Napraw logowanie", False)
                cli._team_slash('"Cały cel w cudzysłowie"', True)
            self.assertEqual(run.call_args_list[0].args, (["Napraw logowanie", "--szablon", "para"], False))
            self.assertEqual(run.call_args_list[1].args, (["Cały cel w cudzysłowie"], True))
        finally:
            os.chdir(prev)


class TeamRunTerminalTests(unittest.TestCase):
    def test_narzedzie_czatu_za_zgoda_i_wynik_w_kolejnej_turze(self):
        import contextlib
        import io
        root = Path(tempfile.mkdtemp(prefix="zespol-czat-", dir=_ROOT))
        proj = make_repo(root)
        prev = os.getcwd()
        os.chdir(proj)
        try:
            self.assertIn("team_run", {t["function"]["name"] for t in cli.enabled_tools()})
            with unittest.mock.patch.object(cli, "confirm_action", return_value=False):
                self.assertTrue(cli.run_tool("team_run", {"goal": "Napraw logowanie"}, False).startswith("ODRZUCONE"))
            self.assertFalse((proj / ".doma" / "zespoly").exists())
            with unittest.mock.patch.object(cli, "confirm_action", return_value=True) as ask, \
                    unittest.mock.patch.object(cli, "_team_spawn_supervisor", return_value=0) as spawn, \
                    unittest.mock.patch.object(cli, "_team_watch") as watch, \
                    unittest.mock.patch.object(cli, "load_endpoint", return_value={"model": "x"}):
                out = cli.run_tool("team_run", {"goal": "Napraw logowanie", "template": "para", "budget_kr": "300"}, False)
            self.assertTrue(ask.called and spawn.called, out)
            self.assertIn("Wynik przyjdzie sam", out)
            run_dir = next((proj / ".doma" / "zespoly").iterdir())
            run = cli.TeamStore(run_dir).load_run()
            self.assertEqual((run["source"]["kind"], run["policy"]["budget_kr"]), ("chat", 300))
            for _ in range(50):
                if watch.called:
                    break
                time.sleep(0.05)
            self.assertEqual(watch.call_args.args[0], run_dir)
            run.update(status="review_final", summary="Logowanie naprawione.")
            cli.TeamStore(run_dir).save_run(run)
            cli.SESSION.pop("pending_context", None)
            with contextlib.redirect_stdout(io.StringIO()), unittest.mock.patch("time.sleep"):
                cli._team_watch(run_dir)
            self.assertIn("Logowanie naprawione.", cli.SESSION["pending_context"][-1])
            with member_env(run_dir, "lead"):
                self.assertIn("ODRZUCONE", cli.run_tool("team_run", {"goal": "x"}, True))
        finally:
            cli.SESSION.pop("pending_context", None)
            os.chdir(prev)


class McpZespolTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-mcp-", dir=_ROOT))
        self.dir, _ = cli._team_create_run(self.root, "Cel", tpl([mem("a"), mem("b")]), shared=True)
        self.st = cli.TeamStore(self.dir)

    def rpc(self, who, *msgs):
        p = subprocess.run([sys.executable, SCRIPT, "mcp", "--zespol", str(self.dir), "--czlonek", who],
                           input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True,
                           timeout=60, env=os.environ, cwd=self.root, encoding="utf-8")
        return [json.loads(x) for x in p.stdout.splitlines() if x.strip()]

    def test_serwer_mcp_tylko_z_narzedziami_zespolu(self):
        self.st.task_create("lead", [{"title": "Zadanie a", "assignee": "a"}])
        self.st.task_claim("a", "T1")
        out = self.rpc("a", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                       {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                       {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "team_task_update", "arguments": {
                           "id": "T1", "status": "done", "result": "Zrobione przez agenta przez MCP"}}},
                       {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "team_finish", "arguments": {}}})
        names = {t["name"] for t in out[1]["result"]["tools"]}
        self.assertTrue(names and all(n.startswith("team_") for n in names), names)
        self.assertIn("team_review", names)
        self.assertNotIn("team_finish", names)
        self.assertIn("Zapisano: T1", out[2]["result"]["content"][0]["text"])
        self.assertTrue(out[3]["result"]["isError"])
        self.assertEqual(task(self.st, "T1")["status"], "done")
        lead = self.rpc("lead", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertIn("team_finish", {t["name"] for t in lead[0]["result"]["tools"]})

    def test_agenci_zewnetrzni_dostaja_serwer_zespolu(self):
        self.assertEqual([cli._team_tools_mode(b) for b in ("agent:claude", "agent:codex", "agent:goose", "agent:gemini",
                                                             "lopus", "@atrapa/atrapa-1")],
                         ["mcp", "mcp", "mcp", "text", "text", "native"])
        self.assertEqual(cli._agent_mcp_servers(), {})
        with member_env(self.dir, "a"), unittest.mock.patch.object(cli, "_mcp_wlaczony", return_value=False):
            argv, _ = cli._agent_argv("claude", "claude", "ask", False, None, "x")
            cfg = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
            self.assertEqual(list(cfg), ["zespol"])
            self.assertEqual(cfg["zespol"]["args"][-4:], ["--zespol", str(self.dir), "--czlonek", "a"])
            self.assertEqual(argv[argv.index("--allowedTools") + 1], "mcp__zespol")
            self.assertIn("Praca w zespole agentów", argv[argv.index("--append-system-prompt") + 1])
            argv, _ = cli._agent_argv("codex", "codex", "ask", False, None, "x")
            self.assertTrue(any(a.startswith("mcp_servers.zespol.command=") for a in argv))
            servers = cli._acp_mcp_servers()
            self.assertEqual((servers[0]["name"], servers[0]["args"][-1]), ("zespol", "a"))


_FAKE_ACP_MEMBER = r"""
import json, os, sys
log = open(os.environ["FAKE_LOG"], "a")
def send(o):
    sys.stdout.write(json.dumps(dict(jsonrpc="2.0", **o)) + "\n"); sys.stdout.flush()
for line in sys.stdin:
    m = json.loads(line); method, mid, p = m.get("method"), m.get("id"), m.get("params") or {}
    log.write(json.dumps({"method": method, "params": p}) + "\n"); log.flush()
    if method == "initialize":
        send({"id": mid, "result": {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []}})
    elif method == "session/new":
        send({"id": mid, "result": {"sessionId": "s-1"}})
    elif method == "session/prompt":
        send({"method": "session/update", "params": {"sessionId": p["sessionId"], "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Sprawdziłem projekt, wszystko jest w porządku."}}}})
        send({"id": mid, "result": {"stopReason": "end_turn"}})
    elif mid is not None:
        send({"id": mid, "result": {}})
"""


# ── 5 i 9. prawdziwe procesy z atrapą modelu ──────────────────────────────────

class FakeTeamModel(BaseHTTPRequestHandler):
    """Atrapa /v1: scenariusz po identyfikatorze członka (prompt systemowy) i nagłówku tury od nadzorcy."""
    calls: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._json(200, {"data": [{"id": "atrapa-1"}]})
        return self._json(404, {})

    @staticmethod
    def plan(body):
        msgs = body.get("messages") or []
        system = next((m.get("content") for m in msgs if m.get("role") == "system"), "") or ""
        who = (re.search(r"identyfikator w zespole: `([\w-]+)`", str(system)) or [None, "?"])[1]
        user = next((m for m in reversed(msgs) if m.get("role") == "user"), {})
        text = json.dumps(user.get("content"), ensure_ascii=False)
        if msgs and msgs[-1].get("role") == "tool":
            return f"Gotowe ({who}): zrobione zgodnie z poleceniem.", []
        if "[ZESPÓŁ: PLAN]" in text:
            calls = [("team_task_create", {"tasks": [
                {"title": "Plik A", "detail": "Utwórz a.txt", "assignee": "a", "files": ["a.txt"]},
                {"title": "Plik B", "detail": "Utwórz b.txt", "assignee": "b", "depends_on": ["#1"], "files": ["b.txt"]}]})]
            if "z pytaniem" in text:
                calls.append(("team_ask_human", {"question": "Jaki ma być nagłówek plików?", "options": ["krótki", "długi"]}))
            return "Plan: dwa pliki, B po A.", calls
        m = re.search(r"\[ZESPÓŁ: (?:PRZEGLĄD (T\d+)|PRZYPOMNIENIE\] Zakończ przegląd (T\d+))", text)
        if m:
            return "", [("team_review", {"id": m.group(1) or m.group(2), "verdict": "approve", "notes": "Zmiany są poprawne."})]
        if who == "?" and "Uruchom zespół" in text:
            return "", [("team_run", {"goal": "Dodaj pliki a i b", "template": "e2e"})]
        m = re.search(r"\[ZESPÓŁ: (?:ZADANIE|PRZYPOMNIENIE|WZNOWIENIE)[^\]]*?(T\d+)", text.replace("\\n", "\n"))
        if m:
            tid = m.group(1)
            calls = [("write_file", {"path": f"{who}.txt", "content": f"plik od {who}\n"})]
            if who == "a":
                calls.append(("team_send", {"to": "lead", "text": "Plik a.txt jest gotowy.", "task_id": tid}))
            if who == "b":
                calls.append(("run_command", {"command": "echo sprawdzam", "reason": "Sprawdzenie pliku."}))
            calls.append(("team_task_update", {"id": tid, "status": "done", "result": f"Zapisałem {who}.txt w swojej kopii"}))
            return "", calls
        if "[ZESPÓŁ: KONIEC]" in text:
            return "", [("team_finish", {"summary": "Zespół dodał pliki a.txt i b.txt."})]
        return "Przyjąłem, nic więcej nie trzeba.", []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        type(self).calls.append(body)
        text, calls = self.plan(body) if body.get("tools") else ("Odpowiedź atrapy.", [])
        calls = [{"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}}
                 for i, (n, a) in enumerate(calls)]
        if not body.get("stream"):
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = calls
            return self._json(200, {"model": body.get("model"), "choices": [{"message": msg}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        out = [{"choices": [{"delta": {"content": text[i:i + 16]}}]} for i in range(0, len(text), 16)]
        for i, c in enumerate(calls):
            out.append({"choices": [{"delta": {"tool_calls": [{"index": i, **c}]}}]})
        out.append({"choices": [{"delta": {}, "finish_reason": "tool_calls" if calls else "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        for ev in out:
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


def model_env(root: Path) -> dict:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeTeamModel)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    home = root / "home"
    cfg = home / ".config" / "doma"
    cfg.mkdir(parents=True)
    (cfg / "konta.json").write_text(json.dumps({"konta": {"atrapa": {
        "base_url": f"http://127.0.0.1:{srv.server_address[1]}/v1", "api_key": "sk-test", "name": "Atrapa",
        "model": "atrapa-1"}}, "aktywne": "atrapa"}), encoding="utf-8")
    (cfg / "settings.json").write_text(json.dumps({"provider": "endpoint", "model_endpoint": "@atrapa/atrapa-1",
                                                   "lang": "pl", "agents_off": True}), encoding="utf-8")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DOMA_CONFIG_DIR=str(cfg), CODO_LANG="pl",
               CODO_ONLINE="1", NO_COLOR="1", PYTHONUNBUFFERED="1", CODO_TEAM_SCRIPT=SCRIPT)
    return srv, env


def kill_run(run_dir: Path):
    """Sprzątanie po teście: nadzorca i członkowie nie mogą zostać w tle."""
    try:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    pids = [run.get("supervisor_pid")] + [m.get("pid") for m in run.get("members") or []]
    alive = []
    for pid in [p for p in pids if p]:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        if st and not st.startswith("Z"):
            alive.append(pid)
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    return alive


class _ProcesyBase(unittest.TestCase):
    """Repozytorium tymczasowe z szablonem e2e (prowadzący, a, b) i atrapą modelu; po teście nic nie zostaje w tle."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-e2e-", dir=_ROOT))
        self.srv, self.env = model_env(self.root)
        FakeTeamModel.calls.clear()
        self.proj = make_repo(self.root)
        (self.proj / ".codo" / "zespoly").mkdir(parents=True)
        (self.proj / ".codo" / "zespoly" / "e2e.json").write_text(json.dumps(
            tpl([mem("a"), mem("b")], check="git status --short") | {"name": "e2e"}), encoding="utf-8")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "szablon")
        self.run_dirs = []

    def tearDown(self):
        left = []
        for d in self.run_dirs:
            time.sleep(0.5)
            left += kill_run(d)
        self.srv.shutdown()
        self.assertEqual(left, [], "procesy zespołu zostały w tle")


class E2ETests(_ProcesyBase):
    def test_codo_team_run_do_konca(self):
        r = subprocess.run([sys.executable, SCRIPT, "team", "run", "Dodaj pliki a i b", "--szablon", "e2e", "--yes"],
                           cwd=self.proj, env=self.env, capture_output=True, text=True, timeout=180,
                           stdin=subprocess.DEVNULL, encoding="utf-8")
        self.assertTrue((self.proj / ".doma" / "zespoly").exists(), r.stdout + r.stderr)
        runs = sorted((self.proj / ".doma" / "zespoly").iterdir())
        self.run_dirs += runs
        log = (runs[0] / "praca.log").read_text(encoding="utf-8") if runs else ""
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr + log)
        self.assertIn("Zespół skończył", r.stdout)
        st = cli.TeamStore(runs[0])
        run = st.load_run()
        self.assertEqual(run["status"], "review_final")
        integ = run["integration_branch"]
        self.assertEqual(git(self.proj, "show", f"{integ}:a.txt"), "plik od a")
        self.assertEqual(git(self.proj, "show", f"{integ}:b.txt"), "plik od b")
        done = [e for e in st.events() if e["type"] == "team_done"][-1]
        self.assertEqual(done["diff_stat"], {"files": 2, "added": 2, "removed": 0})
        self.assertEqual(done["summary"], "Zespół dodał pliki a.txt i b.txt.")
        tasks = st.board()["tasks"]
        self.assertEqual([(t["id"], t["status"], t["claimed_by"]) for t in tasks], [("T1", "done", "a"), ("T2", "done", "b")])
        self.assertFalse((self.proj / "a.txt").exists())          # projekt nietknięty do apply
        lead_calls = [c for c in FakeTeamModel.calls if "identyfikator w zespole: `lead`" in json.dumps(c, ensure_ascii=False)]
        self.assertTrue(lead_calls)
        self.assertTrue(all("team_task_create" in json.dumps(c.get("tools")) for c in lead_calls))
        r = subprocess.run([sys.executable, SCRIPT, "team", "status", "--json"], cwd=self.proj, env=self.env,
                           capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(json.loads(r.stdout)["status"], "review_final")
        r = subprocess.run([sys.executable, SCRIPT, "team", "apply", runs[0].name, "--branch"], cwd=self.proj,
                           env=self.env, capture_output=True, text=True, timeout=60, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout)


class WznowienieTests(_ProcesyBase):
    """8 (proste wznawianie z etapu 1): SIGKILL nadzorcy w trakcie, potem codo team resume; członek dostaje resume."""

    def cli(self, *args, timeout=60):
        return subprocess.run([sys.executable, SCRIPT, "team", *args], cwd=self.proj, env=self.env, capture_output=True,
                              text=True, timeout=timeout, stdin=subprocess.DEVNULL, encoding="utf-8")

    def wait_for(self, st, pred, timeout=90):
        end = time.time() + timeout
        while time.time() < end:
            hit = [e for e in st.events() if pred(e)]
            if hit:
                return hit[-1]
            time.sleep(0.2)
        raise AssertionError("nie doczekałem się zdarzenia: " + str([e["type"] for e in st.events()][-10:]))

    def test_sigkill_nadzorcy_i_resume(self):
        r = self.cli("run", "Dodaj pliki a i b", "--szablon", "e2e", "--bg")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run_dir = next((self.proj / ".doma" / "zespoly").iterdir())
        self.run_dirs.append(run_dir)
        st = cli.TeamStore(run_dir)
        self.wait_for(st, lambda e: e["type"] == "team_ask")          # b czeka na zgodę na polecenie
        run = st.load_run()
        b_pid = next(m["pid"] for m in run["members"] if m["id"] == "b")
        os.kill(run["supervisor_pid"], 9)
        for _ in range(100):                                          # członkowie kończą się po zamknięciu stdin
            if not cli._pid_alive(b_pid):
                break
            time.sleep(0.1)
        self.assertFalse(cli._pid_alive(b_pid))
        self.assertIn(st.load_run()["status"], cli._TEAM_RESUMABLE)
        r = self.cli("resume", run_dir.name, "--bg")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        seq = st.seq()
        ask = self.wait_for(st, lambda e: e["type"] == "team_ask" and e["seq"] > seq)
        log_b = (run_dir / "log" / "b.jsonl").read_text(encoding="utf-8")
        self.assertIn('"resumed"', log_b)                             # członek wrócił do swojej rozmowy
        r = self.cli("answer", run_dir.name, ask["ask_id"], "t")
        self.assertEqual(r.returncode, 0, r.stderr)
        done = self.wait_for(st, lambda e: e["type"] == "team_done", 120)
        self.assertEqual(done["status"], "review_final")
        integ = st.load_run()["integration_branch"]
        self.assertEqual(git(self.proj, "show", f"{integ}:b.txt"), "plik od b")


class _AppBase(unittest.TestCase):
    """codo app-server z atrapą modelu w repozytorium tymczasowym; po teście nic nie zostaje w tle."""

    def prepare(self):
        pass

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="zespol-app-", dir=_ROOT))
        self.srv, self.env = model_env(self.root)
        FakeTeamModel.calls.clear()
        self.proj = make_repo(self.root)
        self.prepare()
        self.p = subprocess.Popen([sys.executable, SCRIPT, "app-server"], cwd=self.proj, env=self.env,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  text=True, encoding="utf-8")
        self.q = queue.Queue()
        threading.Thread(target=lambda: [self.q.put(json.loads(x)) for x in self.p.stdout if x.strip()],
                         daemon=True).start()
        self.seen, self.other = [], []

    def tearDown(self):
        try:
            zamknij_stdin(self.p)
        except OSError:
            pass
        try:
            self.p.wait(15)
        except subprocess.TimeoutExpired:
            self.p.kill()
        left = []
        for d in (self.proj / ".doma" / "zespoly").glob("*"):
            time.sleep(0.5)
            left += kill_run(d)
        self.srv.shutdown()
        self.assertEqual(left, [], "procesy zespołu zostały w tle")

    def send(self, **msg):
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def wait(self, kind, timeout=120, on=None):
        end = time.time() + timeout
        while time.time() < end:
            try:
                ev = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if str(ev.get("type", "")).startswith("team_"):
                self.seen.append(ev)
            else:
                self.other.append(ev)
            if on:
                on(ev)
            if ev.get("type") == kind:
                return ev
        raise AssertionError(f"brak {kind}; ostatnie: {[e.get('type') for e in self.seen[-15:]]}")


class AppEtap2Tests(_AppBase):
    """Zespół z rozmowy (team_run), członek przez ACP i węzeł „team” workflowu, wszystko na atrapach."""

    def prepare(self):
        (self.proj / ".codo" / "zespoly").mkdir(parents=True)
        (self.proj / ".codo" / "zespoly" / "e2e.json").write_text(json.dumps(
            tpl([mem("a"), mem("b")], check="git status --short") | {"name": "e2e"}), encoding="utf-8")
        (self.proj / ".codo" / "zespoly" / "acp.json").write_text(json.dumps(
            tpl([mem("a"), mem("b", brain="agent:goose")]) | {"name": "acp"}), encoding="utf-8")
        git(self.proj, "add", "-A")
        git(self.proj, "commit", "-q", "-m", "szablony")
        fake = atrapa(self.root, "bin-goose", _FAKE_ACP_MEMBER)
        self.acp_log = self.root / "acp.log"
        self.env.update(CODO_AGENT_GOOSE=str(fake), FAKE_LOG=str(self.acp_log))

    def answer_all(self, ev):
        if ev.get("type") == "team_ask":
            self.send(type="team_answer", run_id=ev["run_id"], ask_id=ev["ask_id"], value=1)
        elif ev.get("type") == "ask":
            self.asked.append(ev)
            self.send(type="answer", id=ev["id"], value=1)

    def test_team_run_z_rozmowy(self):
        self.asked = []
        self.wait("ready", 60)
        self.send(type="send", text="Uruchom zespół do plików a i b")
        self.wait("team_started", 120, self.answer_all)
        self.assertTrue(self.asked and "zespół" in self.asked[0]["pytanie"].lower(), self.asked)   # za zgodą
        done = self.wait("team_done", 180, self.answer_all)
        self.assertEqual((done["status"], done["source"]["kind"]), ("review_final", "chat"))
        tool = next(e for e in self.other if e.get("type") == "tool" and str(e.get("naglowek")).startswith("Zespół"))
        self.assertIn("Wynik przyjdzie sam", json.dumps(tool, ensure_ascii=False))
        cfg = Path(self.env["DOMA_CONFIG_DIR"])
        saved = ""
        for _ in range(40):
            saved = "".join(p.read_text(encoding="utf-8") for p in (cfg / "rozmowy").rglob("*.json")
                            if json.loads(p.read_text(encoding="utf-8")).get("cwd") == str(self.proj))
            if "Zespół zakończył pracę" in saved:
                break
            time.sleep(0.25)
        self.assertIn("Zespół dodał pliki a.txt i b.txt.", saved)

    def test_czlonek_przez_acp_dostaje_serwer_zespolu(self):
        self.wait("ready", 60)
        self.send(type="team_start", goal="Dodaj pliki a i b", template="acp", mode="auto", source={"kind": "app"})
        done = self.wait("team_done", 180)
        self.assertEqual(done["status"], "review_final", [e for e in self.seen if e["type"] == "team_task"][-2:])
        st = cli.TeamStore(self.proj / ".doma" / "zespoly" / done["run_id"])
        self.assertEqual(next(m for m in st.load_run()["members"] if m["id"] == "b")["tools"], "mcp")
        t2 = task(st, "T2")
        self.assertEqual((t2["status"], t2["claimed_by"]), ("done", "b"))
        self.assertIn("Sprawdziłem projekt", t2["result"])                       # wynik z ostatniej wiadomości agenta
        log = [json.loads(x) for x in self.acp_log.read_text(encoding="utf-8").splitlines()]
        new = next(e["params"] for e in log if e["method"] == "session/new")
        zespol = next(m for m in new["mcpServers"] if m["name"] == "zespol")
        self.assertEqual(zespol["args"][-4:], ["--zespol", str(st.dir), "--czlonek", "b"])
        prompt = json.dumps([e["params"] for e in log if e["method"] == "session/prompt"], ensure_ascii=False)
        self.assertIn("[ZESPÓŁ: ZADANIE T2]", prompt)

    def test_wezel_zespolu_i_model_na_ture_w_workflowie(self):
        self.wait("ready", 60)
        settings = (Path(self.env["DOMA_CONFIG_DIR"]) / "settings.json").read_text(encoding="utf-8")
        nodes = [{"id": "s", "kind": "start"},
                 {"id": "z", "kind": "team", "title": "Zespół", "prompt": "Dodaj pliki a i b ({{input}})",
                  "template": "e2e", "mode": "auto", "apply": True},
                 {"id": "p", "kind": "agent", "title": "Podsumowanie", "prompt": "Podsumuj: {{last}}",
                  "model": "@atrapa/atrapa-2"}]
        edges = [{"from": "s", "port": "out", "to": "z"}, {"from": "z", "port": "out", "to": "p"}]
        self.send(type="workflow", name="Z zespołem", input="na próbę", nodes=nodes, edges=edges)
        flow = []
        end = self.wait("turn_end", 240, lambda ev: flow.append(ev) if ev.get("type") == "workflow" else None)
        for _ in range(20):
            if any(e.get("state") in ("done", "failed") for e in flow):
                break
            try:
                ev = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if ev.get("type") == "workflow":
                flow.append(ev)
        states = [(e.get("node"), e.get("state")) for e in flow]
        self.assertIn(("z", "running"), states)
        self.assertIn(("z", "node_done"), states, (states, end))
        self.assertNotIn("failed", [s for _n, s in states])
        rid = next(e["run_id"] for e in flow if e.get("node") == "z" and e.get("state") == "running")
        self.assertTrue(any(e["type"] == "team_started" and e["run_id"] == rid for e in self.seen))
        self.assertEqual(cli.TeamStore(self.proj / ".doma" / "zespoly" / rid).load_run()["source"]["kind"], "workflow")
        self.assertEqual((self.proj / "b.txt").read_text(encoding="utf-8"), "plik od b\n")   # apply: kolejne kroki widzą pliki
        last = [c for c in FakeTeamModel.calls if "Podsumuj:" in json.dumps(c.get("messages"), ensure_ascii=False)]
        self.assertTrue(last and last[-1]["model"] == "atrapa-2", [c.get("model") for c in last])
        self.assertIn("Zespół dodał pliki", json.dumps(last[-1]["messages"], ensure_ascii=False))
        self.assertEqual((Path(self.env["DOMA_CONFIG_DIR"]) / "settings.json").read_text(encoding="utf-8"), settings)
        self.assertFalse([e for e in self.other if e.get("type") == "model"])


class KontraktTests(_AppBase):
    """9. app-server: team_start → zdarzenia zgodne z kontraktem; zapis fixture dla okna Maca."""

    def test_kontrakt_zdarzen(self):
        ready = self.wait("ready", 60)
        self.assertIn("team1", ready.get("features") or [])
        self.assertIn("team2", ready.get("features") or [])
        self.wait("team_runs", 30)
        self.send(type="team_templates")
        names = {t["name"] for t in self.wait("team_templates", 30)["templates"]}
        self.assertTrue({"para", "produkt", "naprawa", "przeglad"} <= names)
        # etap 2: plan do zatwierdzenia, pytanie prowadzącego, przegląd krzyżowy i zgoda na każde scalenie
        team = tpl([mem("a"), mem("b"), mem("k", writes=False)], check="git status --short", review="cross",
                   approve_merge="each", approve_plan=True)
        self.send(type="team_start", goal="Dodaj pliki a i b z pytaniem", team=team, mode="ask", budget_kr=500,
                  source={"kind": "chat"})
        asks, plans, merges = [], [], []

        def on(ev):
            kind = ev.get("type")
            if kind == "team_ask":
                asks.append(ev["ask_id"])
                self.send(type="team_answer", run_id=ev["run_id"], ask_id=ev["ask_id"], value=1)
            elif kind == "team_plan":
                plans.append(ev)
                self.send(type="team_plan_decide", run_id=ev["run_id"], approve=True)
            elif kind == "team_question":
                self.send(type="team_message", run_id=ev["run_id"], to=ev["from"], text="Krótki nagłówek.",
                          reply_to=ev["id"])
            elif kind == "team_merge" and ev.get("state") == "waiting_human":
                merges.append(ev["task_id"])
                self.send(type="team_merge_decide", run_id=ev["run_id"], task_id=ev["task_id"], approve=True)
        done = self.wait("team_done", 240, on)
        rid = done["run_id"]
        self.assertEqual(done["status"], "review_final")
        self.assertEqual(done["source"]["kind"], "chat")
        self.assertTrue(asks, "członek b w trybie ask powinien pytać o polecenie")
        self.assertEqual([t["id"] for t in plans[0]["tasks"]], ["T1", "T2"])
        self.assertEqual(sorted(merges), ["T1", "T2"])
        reviews = [e for e in self.seen if e["type"] == "team_merge" and e["state"] == "reviewing"]
        self.assertEqual({(e["task_id"], e["reviewer"]) for e in reviews}, {("T1", "k"), ("T2", "k")})
        self.assertTrue(any(e["type"] == "team_question_done" for e in self.seen))
        self.send(type="team_diff", run_id=rid)
        diff = self.wait("team_diff", 30)
        self.assertEqual(({f["path"] for f in diff["files"]}, diff["scope"]), ({"a.txt", "b.txt"}, "all"))
        self.send(type="team_diff", run_id=rid, task_id="T1")
        self.assertEqual([f["path"] for f in self.wait("team_diff", 30)["files"]], ["a.txt"])
        self.send(type="team_member_log", run_id=rid, member="a")
        log = self.wait("team_member_log", 30)
        self.assertTrue(log["next"] > 0 and any(e.get("type") == "turn_end" for e in log["events"]))
        self.send(type="team_apply", run_id=rid, how="merge")
        applied = self.wait("team_applied", 60)
        self.assertTrue(applied["ok"], applied)
        self.assertEqual((self.proj / "b.txt").read_text(encoding="utf-8"), "plik od b\n")
        # zespół z rozmowy: cel i podsumowanie są w historii rozmowy, ale okno nie dostaje ich jako assistant/delta
        cfg = Path(self.env["DOMA_CONFIG_DIR"])
        saved = ""
        for _ in range(40):
            saved = ""
            for p in (cfg / "rozmowy").rglob("*.json"):
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("cwd") == str(self.proj):    # rozmowa okna, nie członków
                    saved += json.dumps([(m["role"], m["content"]) for m in d["messages"]], ensure_ascii=False)
            if "Zespół dodał pliki a.txt i b.txt." in saved:
                break
            time.sleep(0.25)
        self.assertIn("Zespół dodał pliki a.txt i b.txt.", saved)
        self.assertIn('["user", "Dodaj pliki a i b z pytaniem"]', saved)
        self.send(type="team_runs")
        runs = self.wait("team_runs", 30)["runs"]
        self.assertEqual((runs[0]["run_id"], runs[0]["status"], runs[0]["resumable"]), (rid, "applied", False))
        self.send(type="team_attach")
        self.wait("team_error", 30)
        types = [e["type"] for e in self.seen]
        for kind in ("team_started", "team_state", "team_member", "team_task", "team_message", "team_member_event",
                     "team_ask", "team_ask_done", "team_merge", "team_budget", "team_done", "team_applied",
                     "team_plan", "team_question", "team_question_done", "team_diff", "team_member_log"):
            self.assertIn(kind, types)
        self.assertLess(types.index("team_started"), types.index("team_member"))
        self.assertLess(types.index("team_ask"), types.index("team_ask_done"))
        self.assertLess(types.index("team_done"), types.index("team_applied"))
        check_contract(self, self.seen)
        self.assertFalse([e for e in self.other if e.get("type") in ("assistant", "delta")
                          and "Zespół dodał" in str(e.get("tekst"))])
        if os.environ.get("CODO_REGEN") or not FIXTURE.exists():
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.seen), encoding="utf-8")
        fixture = [json.loads(x) for x in FIXTURE.read_text(encoding="utf-8").splitlines() if x.strip()]
        check_contract(self, fixture)
        self.assertTrue({e["type"] for e in fixture} <= set(CONTRACT))
        self.assertEqual({e["type"] for e in fixture}, set(types))   # fixture pokrywa te same rodzaje zdarzeń


def check_contract(tc, events):
    seqs = {}
    for ev in events:
        kind = ev.get("type")
        tc.assertIn(kind, CONTRACT, kind)
        tc.assertTrue(CONTRACT[kind] <= set(ev), f"{kind}: brak {CONTRACT[kind] - set(ev)}")
        if kind == "team_member":
            tc.assertTrue(MEMBER_KEYS <= set(ev["member"]), MEMBER_KEYS - set(ev["member"]))
        if kind == "team_task":
            tc.assertTrue(TASK_KEYS <= set(ev["task"]), TASK_KEYS - set(ev["task"]))
        if kind == "team_message":
            tc.assertTrue(MESSAGE_KEYS <= set(ev["message"]))
        if kind == "team_state":
            for m in ev["members"]:
                tc.assertTrue(MEMBER_KEYS <= set(m))
        if kind == "team_merge":
            tc.assertIn(ev["state"], MERGE_STATES)
        if kind == "team_member_event":
            tc.assertIn(ev["event"].get("type"), ("delta", "assistant", "tool_start", "tool", "edit", "turn_start",
                                                  "turn_end", "info", "error", "subagents", "fallback"))
        if "seq" in ev and kind not in ("team_state",):
            prev = seqs.get(ev["run_id"], 0)
            tc.assertGreater(ev["seq"], prev, f"seq nie rośnie: {kind}")
            seqs[ev["run_id"]] = ev["seq"]


def tearDownModule():
    shutil.rmtree(_ROOT, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
