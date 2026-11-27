"""Codo: grupy agentów (codo grupa, group_* w app-serverze). Bez sieci i bez prawdziwych dostawców SI:
sposoby pracy na atrapie procesu członka, a bieg z prawdziwymi procesami `codo app-server` na lokalnej
atrapie zgodnej z /v1 (konto „@atrapa/atrapa-1”) i atrapie Codexa (CODO_AGENT_CODEX)."""
import importlib.machinery
import importlib.util
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
# Codo w procesie potomnym pisze do potoku w UTF-8 (na Windows potok ma stronę kodową ANSI, cp1252).
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import atrapa, zakoncz  # noqa: E402

_ROOT = Path(tempfile.mkdtemp(prefix="codo-grupy-")).resolve()
_HOME = _ROOT / "home"
_CFG = _HOME / ".config" / "doma"
_CFG.mkdir(parents=True)
os.environ.update(HOME=str(_HOME), USERPROFILE=str(_HOME), DOMA_CONFIG_DIR=str(_CFG),
                  DOMA_API_URL="http://127.0.0.1:9", CODO_LANG="pl", DOMA_NO_SYNC="1", CODO_APP_LOCAL_ONLY="1")
for _k in ("CODO_ZESPOL_DIR", "CODO_ZESPOL_CZLONEK", "CODO_PROVIDER", "CODO_APP_MODE", "CODO_NO_HISTORY"):
    os.environ.pop(_k, None)
(_CFG / "settings.json").write_text(json.dumps({"agents_off": True, "lang": "pl"}), encoding="utf-8")

SCRIPT = str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma"))
_loader = importlib.machinery.SourceFileLoader("codo_grupy", SCRIPT)
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
cli = importlib.util.module_from_spec(_spec)
_loader.exec_module(cli)


class FakeMember:
    """Członek bez procesu: odpowiedź układa funkcja testu (id członka, mózg, tekst) → (ok, odpowiedź, kredyty, błąd)."""
    script = None
    live: dict = {}
    peak: dict = {}
    sent: list = []
    lock = threading.Lock()

    def __init__(self, run, member, brain, cwd, mode):
        self.run, self.m, self.brain, self.cwd, self.mode = run, member, brain, str(cwd), mode
        self.q = queue.Queue()
        self.credits = 0
        self.dead = False
        self.cancel = threading.Event()

    def spawn(self):
        self.q.put({"type": "ready", "model": self.brain})
        return 1

    def send_raw(self, obj):
        type(self).sent.append((self.m["id"], obj))
        return True

    def send(self, text):
        type(self).sent.append((self.m["id"], {"type": "send", "text": text}))
        threading.Thread(target=self._answer, args=(text,), daemon=True).start()
        return True

    def _answer(self, text):
        cls = type(self)
        key = cli._group_slot_key(self.brain)
        with cls.lock:
            cls.live[key] = cls.live.get(key, 0) + 1
            cls.peak[key] = max(cls.peak.get(key, 0), cls.live[key])
            cls.live["*"] = cls.live.get("*", 0) + 1
            cls.peak["*"] = max(cls.peak.get("*", 0), cls.live["*"])
        try:
            ok, out, cost, err, delay = (cls.script(self.m["id"], self.brain, text) + (0.15,))[:5]
            self.q.put({"type": "turn_start"})
            if self.cancel.wait(delay):
                self.q.put({"type": "turn_end", "ok": False, "seconds": delay, "credits": self.credits})
                return
            if out:
                self.q.put({"type": "assistant", "tekst": out})
            if err:
                self.q.put({"type": "error", "tekst": err})
            self.credits += cost
            self.q.put({"type": "turn_end", "ok": ok, "seconds": delay, "credits": self.credits})
        finally:
            with cls.lock:
                cls.live[key] -= 1
                cls.live["*"] -= 1

    def interrupt(self):
        self.cancel.set()

    def alive(self):
        return not self.dead

    def stop(self, wait=4):
        self.dead = True


def group(strategy, members, **kw):
    g, err = cli._group_check({"name": kw.pop("name", "Test " + strategy), "strategy": strategy,
                               "members": members, **kw})
    assert not err, err
    return g


def run(g, task="Napisz hasło reklamowe", factory=FakeMember, cwd=None):
    events = []
    r = cli.GroupRun(g, task, cwd or _ROOT, emit=lambda k, d: events.append((k, d)), proc_factory=factory)
    st = r.go()
    return r, st, events


def members3():
    return [{"name": "Ala", "brain": "agent:codex", "role": "pomysły"},
            {"name": "Bob", "brain": "agent:claude", "role": "styl"},
            {"name": "Cezary", "brain": "@atrapa/atrapa-1", "role": "fakty"}]


class _Base(unittest.TestCase):
    def setUp(self):
        FakeMember.live, FakeMember.peak, FakeMember.sent = {}, {}, []
        cli._GROUP_SLOTS.clear()
        self._ready = cli._group_brain_ready
        cli._group_brain_ready = lambda brain: ""   # atrapa: każdy mózg „zainstalowany”

    def tearDown(self):
        cli._group_brain_ready = self._ready


class ZapisTests(_Base):
    def test_zapis_lista_nazwy_i_usuwanie(self):
        g, err = cli._group_save({"name": "Recenzenci", "strategy": "review", "lead": "Bob",
                                  "members": members3() + [{"name": "Ala", "brain": "lopus"}],
                                  "limits": {"rounds": 9, "member_minutes": 0}})
        self.assertEqual(err, "")
        self.assertEqual([m["id"] for m in g["members"]], ["ala", "bob", "cezary", "ala-2"])
        self.assertEqual(g["lead"], "bob")
        self.assertEqual(g["limits"]["rounds"], 5)
        self.assertTrue((_CFG / "grupy.json").exists())
        self.assertEqual(cli._group_get("recenzenci")["id"], g["id"])
        _x, err = cli._group_save({"name": "recenzenci", "members": members3()})
        self.assertIn("już jest", err)
        g["name"] = "Recenzenci 2"
        g2, err = cli._group_save(g)
        self.assertEqual((err, g2["created"]), ("", g["created"]))
        self.assertEqual(len(cli._group_list()), 1)
        self.assertIn("Nieznany sposób", cli._group_check({"name": "x", "strategy": "losowo", "members": members3()})[1])
        self.assertIn("co najmniej", cli._group_check({"name": "x", "members": []})[1])
        self.assertTrue(cli._group_delete(g["id"]))
        self.assertEqual(cli._group_list(), [])

    def test_zapis_z_okna_zachowuje_miejsca_u_dostawcy_i_gotowy_zespol(self):
        # okno (Mac, Windows, Linux) zapisuje ile naraz u dostawcy i z jakiego gotowego zespołu jest grupa
        g, err = cli._group_save({"name": "Burza", "strategy": "chat", "recipe": "burza",
                                  "members": members3(), "limits": {"per_provider": 3, "budget_kr": 40}})
        self.assertEqual(err, "")
        self.assertEqual((g["limits"]["per_provider"], g["limits"]["budget_kr"], g["recipe"]), (3, 40, "burza"))
        again = cli._group_get("Burza")
        self.assertEqual((again["limits"]["per_provider"], again["recipe"]), (3, "burza"))

    def test_miejsca_u_dostawcow(self):
        self.assertEqual(cli._group_slot_key("agent:codex"), "agent:codex")
        self.assertEqual(cli._group_slot_key("lopus-pro"), "domaai")
        self.assertEqual(cli._group_slot_key("@atrapa/atrapa-1"), "konto:atrapa")
        self.assertEqual(cli._group_cost_kind("agent:claude"), "plan")
        self.assertEqual(cli._group_cost_kind("lopus"), "kr")
        self.assertEqual(cli._group_slot_limit("agent:codex"), 2)
        self.assertEqual(cli._group_slot_limit("agent:codex", 5), 5)
        self.assertEqual(cli._group_reason(["Claude AI usage limit reached|1700"]), "limit planu albo zapytań")
        self.assertEqual(cli._group_reason(["Please run /login"]), "brak logowania")
        self.assertEqual(cli._group_parse_vote("GŁOS: B\nDLACZEGO: krótsza", ["A", "B"]), ("B", "krótsza"))
        self.assertEqual(cli._group_parse_vote("wybieram A", ["B"]), ("", ""))
        self.assertEqual(cli._group_parse_split('Plan\n```podzial\n{"ala": "wstęp", "nikt": "x", "Bob": "koniec"}\n```',
                                                ["ala", "bob"]), {"ala": "wstęp", "bob": "koniec"})


class SposobyTests(_Base):
    def test_rownolegle_i_synteza_prowadzacego(self):
        def script(mid, brain, text):
            if "etap: synteza" in text:
                self.assertIn("=== Ala (Codex) ===", text)
                return True, "Porównanie i Odpowiedź łączona", 7, ""
            return True, f"Odpowiedź {mid}", 3 if brain.startswith("@") else 0, ""
        FakeMember.script = staticmethod(script)
        r, st, ev = run(group("parallel", members3(), lead="cezary"))
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["result"]["kind"], "synthesis")
        self.assertEqual(st["result"]["member"], "cezary")
        self.assertEqual(FakeMember.peak["*"], 3)        # wszyscy naraz
        answers = [e for k, e in ev if k == "group_text" and e["phase"] == "answers"]
        self.assertEqual(sorted(a["member"] for a in answers), ["ala", "bob", "cezary"])
        cez = next(m for m in st["members"] if m["id"] == "cezary")
        self.assertEqual((cez["spent_kr"], cez["cost"], cez["turns"]), (10, "key", 2))
        self.assertEqual(next(m for m in st["members"] if m["id"] == "ala")["cost"], "plan")
        kinds = [k for k, _e in ev]
        self.assertEqual(kinds[0], "group_started")
        self.assertEqual(kinds[-1], "group_done")
        self.assertTrue((cli._group_runs_dir() / r.id / "events.jsonl").exists())
        self.assertEqual(cli._group_runs_list()[0]["run_id"], r.id)
        # Persona i rola idą do członka
        first = next(o for mid, o in FakeMember.sent if mid == "bob" and o["type"] == "send")
        self.assertIn("rola: styl", first["text"])

    def test_limit_u_jednego_dostawcy_i_kolejka(self):
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "ok " + mid, 0, "", 0.3))
        ms = [{"name": f"C{i}", "brain": "agent:codex"} for i in range(4)]
        _r, st, ev = run(group("parallel", ms, limits={"per_provider": 0}))
        self.assertEqual(st["status"], "done")
        self.assertEqual(FakeMember.peak["agent:codex"], 2)   # domyślnie 2 naraz na jednym planie
        queued = [e["member"]["id"] for k, e in ev if k == "group_member" and e["member"]["status"] == "queued"]
        self.assertTrue(queued)
        self.assertIn("Czeka na wolne miejsce", next(e["member"]["doing"] for k, e in ev
                                                    if k == "group_member" and e["member"]["status"] == "queued"))

    def test_limit_planu_u_jednego_nie_wywraca_grupy_i_zapas(self):
        def script(mid, brain, text):
            if brain == "agent:claude":
                return False, "", 0, "Claude AI usage limit reached|1700000000"
            return True, f"Od {mid} na {brain}", 0, ""
        FakeMember.script = staticmethod(script)
        _r, st, _ev = run(group("parallel", members3()))
        bob = next(m for m in st["members"] if m["id"] == "bob")
        self.assertEqual((bob["status"], bob["reason"]), ("failed", "limit planu albo zapytań"))
        self.assertEqual(st["status"], "done")
        # Z mózgiem zapasowym grupy Bob odpowiada dalej
        _r, st, _ev = run(group("parallel", members3(), fallback="lopus", name="Z zapasem"))
        bob = next(m for m in st["members"] if m["id"] == "bob")
        self.assertEqual((bob["status"], bob["fallback_from"], bob["brain_label"]), ("done", "Claude Code", "Lopus"))
        self.assertIn("na lopus", bob["answer"])

    def test_niezainstalowany_pominiety_z_powodem(self):
        cli._group_brain_ready = lambda brain: "Codex nie jest zainstalowany" if brain == "agent:codex" else ""
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "ok " + mid, 0, ""))
        _r, st, _ev = run(group("parallel", members3()))
        ala = next(m for m in st["members"] if m["id"] == "ala")
        self.assertEqual((ala["status"], ala["reason"]), ("skipped", "Codex nie jest zainstalowany"))
        self.assertEqual(st["status"], "done")

    def test_przeglad_krzyzowy_rundy_i_zatwierdzenie(self):
        seen = []

        def script(mid, brain, text):
            seen.append((mid, text.split("etap: ")[1].split("]")[0]))
            if "etap: przegląd" in text:
                if "WERSJA 2" in text:
                    return True, "ZATWIERDZAM, dobrze", 0, ""
                return True, f"UWAGI: {mid} chce krócej", 0, ""
            if "etap: poprawka" in text:
                self.assertIn("ala chce krócej", text.replace("UWAGI: ", ""))
                return True, "WERSJA 2", 0, ""
            return True, "WERSJA 1", 0, ""
        FakeMember.script = staticmethod(script)
        _r, st, ev = run(group("review", members3(), lead="cezary", limits={"rounds": 3}))
        self.assertEqual(st["result"], {"kind": "final", "member": "cezary", "text": "WERSJA 2", "rounds": 2})
        self.assertEqual([s for _m, s in seen].count("przegląd"), 4)   # 2 recenzentów × 2 rundy, potem zgoda
        self.assertEqual([s for _m, s in seen].count("poprawka"), 1)
        self.assertTrue(any(k == "group_note" and "zatwierdzili" in e["tekst"] for k, e in ev))

    def test_glosowanie_bez_glosu_na_siebie_i_remis(self):
        def script(mid, brain, text):
            if "etap: głosowanie" in text:
                self.assertIn("(Twoja)", text)
                return True, {"ala": "GŁOS: B\nDLACZEGO: lepsza", "bob": "GŁOS: B", "cezary": "GŁOS: A\nDLACZEGO: jasna"}[mid], 0, ""
            return True, f"Propozycja od {mid}", 0, ""
        FakeMember.script = staticmethod(script)
        _r, st, _ev = run(group("vote", members3()))
        res = st["result"]
        # Bob nie może głosować na siebie (B): jego głos przepada, Ala wskazuje B, Cezary A → remis 1:1
        self.assertEqual(res["votes"], {"ala": 1, "bob": 1, "cezary": 0})
        self.assertEqual(res["member"], "bob")   # prowadząca Ala głosowała na B
        self.assertIn("głos prowadzącego", res["note"])
        self.assertEqual(res["text"], "Propozycja od bob")

    def test_potok_przekazuje_wynik_i_pomija_nieudany_krok(self):
        def script(mid, brain, text):
            if mid == "bob":
                return False, "", 0, "agent nie odpowiedział"
            prev = text.split("WYNIK POPRZEDNIEGO KROKU")[1][:80] if "WYNIK POPRZEDNIEGO KROKU" in text else ""
            return True, f"[{mid}]" + ("<" + prev.split(":\n")[1].split("\n")[0] + ">" if prev else ""), 0, ""
        FakeMember.script = staticmethod(script)
        _r, st, ev = run(group("pipeline", members3()))
        self.assertEqual(st["result"]["text"], "[cezary]<[ala]>")
        self.assertTrue(any(k == "group_note" and "pominięty" in e["tekst"] for k, e in ev))
        self.assertEqual(FakeMember.peak["*"], 1)   # po kolei

    def test_podzial_pracy_bez_kodu(self):
        def script(mid, brain, text):
            if "etap: podział pracy" in text:
                return True, 'Plan:\n```podzial\n{"bob": "Wstęp", "cezary": "Liczby"}\n```', 0, ""
            if "etap: twoja część" in text:
                return True, f"Część {mid}: " + text.split("prowadzącego):\n")[1].split("\n")[0], 0, ""
            if "etap: złożenie całości" in text:
                return True, "Całość z części", 0, ""
            return True, "?", 0, ""
        FakeMember.script = staticmethod(script)
        _r, st, ev = run(group("split", members3()))
        work = sorted(e["text"] for k, e in ev if k == "group_text" and e["phase"] == "work")
        self.assertEqual(work, ["Część bob: Wstęp", "Część cezary: Liczby"])
        self.assertEqual(st["result"]["kind"], "synthesis")
        self.assertEqual(st["result"]["text"], "Całość z części")

    def test_przerwanie_calosci_i_jednego(self):
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "ok " + mid, 0, "", 5 if mid == "bob" else 0.1))
        g = group("parallel", members3())
        events = []
        r = cli.GroupRun(g, "Zadanie", _ROOT, emit=lambda k, d: events.append((k, d)), proc_factory=FakeMember)
        threading.Timer(0.6, lambda: r.stop("bob")).start()
        t0 = time.monotonic()
        st = r.go()
        self.assertLess(time.monotonic() - t0, 4)
        bob = next(m for m in st["members"] if m["id"] == "bob")
        self.assertEqual(bob["status"], "stopped")
        self.assertEqual(st["status"], "done")
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "ok", 0, "", 5))
        r = cli.GroupRun(g, "Zadanie", _ROOT, emit=lambda k, d: None, proc_factory=FakeMember)
        threading.Timer(0.5, r.stop).start()
        st = r.go()
        self.assertEqual(st["status"], "stopped")

    def test_poprawka_i_przyjecie(self):
        FakeMember.script = staticmethod(lambda mid, brain, text: (
            True, "Poprawione krócej" if "UWAGI UŻYTKOWNIKA" in text else "Długa wersja " + mid, 0, ""))
        r, st, ev = run(group("parallel", members3()[:1]))
        self.assertEqual(st["result"]["kind"], "single")
        ok, out = r.revise("", "Krócej proszę")
        self.assertTrue(ok)
        self.assertEqual(r.result["text"], "Poprawione krócej")
        ok, _d = r.accept("ala")
        self.assertTrue(ok)
        self.assertEqual(r.result["accepted"], "ala")


def git(path, *args):
    r = subprocess.run(["git", "-C", str(path), "-c", "user.name=T", "-c", "user.email=t@e.pl", *args],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class KopieTests(_Base):
    def test_kazdy_w_swojej_kopii_i_scalenie_wybranego(self):
        proj = _ROOT / "repo-kopie"
        proj.mkdir()
        git(proj, "init", "-q", "-b", "main")
        (proj / "a.txt").write_text("start\n", encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "start")

        class Writer(FakeMember):
            def _answer(self, text):
                Path(self.cwd, f"{self.m['id']}.txt").write_text("od " + self.m["id"] + "\n", encoding="utf-8")
                super()._answer(text)
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "Zrobione " + mid, 0, ""))
        ms = [dict(m, writes=True) for m in members3()[:2]]
        r, st, _ev = run(group("vote", ms, files="copies"), factory=Writer, cwd=proj)
        cwds = {r.members[m]["worktree"] for m in ("ala", "bob")}
        self.assertEqual(len(cwds), 2)   # każdy w swojej kopii
        self.assertEqual(next(m for m in st["members"] if m["id"] == "ala")["files"]["files"], 1)
        self.assertFalse((proj / "ala.txt").exists())
        ok, detail = r.accept("bob")
        self.assertTrue(ok, detail)
        self.assertTrue((proj / "bob.txt").exists())
        self.assertFalse((proj / "ala.txt").exists())
        self.assertIn("Scalono", detail)
        self.assertFalse(any(Path(c).exists() for c in cwds))   # kopie sprzątnięte


class PodzialKoduTests(_Base):
    def test_podzial_w_kodzie_przejmuje_silnik_zespolow(self):
        proj = _ROOT / "repo-zespol"
        proj.mkdir()
        git(proj, "init", "-q", "-b", "main")
        (proj / "a.txt").write_text("start\n", encoding="utf-8")
        git(proj, "add", "-A")
        git(proj, "commit", "-q", "-m", "start")
        spawned = []
        old = cli._team_spawn_supervisor
        cli._team_spawn_supervisor = lambda d: spawned.append(d) or 0
        try:
            FakeMember.script = staticmethod(lambda mid, brain, text: (True, "nie powinno paść", 0, ""))
            ms = [dict(m, writes=True) for m in members3()]
            _r, st, ev = run(group("split", ms, files="copies", lead="cezary"), cwd=proj)
        finally:
            cli._team_spawn_supervisor = old
        self.assertEqual(st["status"], "handoff")
        self.assertEqual(len(spawned), 1)
        team = cli.TeamStore(spawned[0]).load_run()
        self.assertEqual(team["goal"], "Napisz hasło reklamowe")
        self.assertEqual([m["id"] for m in team["members"]], ["lead", "ala", "bob"])
        self.assertEqual(team["members"][0]["brain"], "@atrapa/atrapa-1")
        self.assertTrue(any(k == "group_handoff" for k, _e in ev))
        self.assertFalse(FakeMember.sent)   # nikt z grupy nie dostał tury
        self.assertNotIn("grupa-", git(proj, "branch"))   # kopie grupy sprzątnięte


# ── prawdziwe procesy: dwa mózgi (konto /v1 i agent Codex), oba atrapy ──

class FakeV1(BaseHTTPRequestHandler):
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
        self._json(200, {"data": [{"id": "atrapa-1"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        user = json.dumps([m for m in body.get("messages") or [] if m.get("role") == "user"][-1:], ensure_ascii=False)
        text = "Synteza: najlepsze z obu." if "etap: synteza" in user else "Konto mówi: krótko i jasno."
        if not body.get("stream"):
            return self._json(200, {"choices": [{"message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 5, "completion_tokens": 5}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for ev in ({"choices": [{"delta": {"content": text}}]},
                   {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}}):
            self.wfile.write(("data: " + json.dumps(ev) + "\n\n").encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")


_FAKE_CODEX = r'''
import json, sys, time
prompt = sys.stdin.read()
def out(ev): print(json.dumps(ev), flush=True)
out({"type": "thread.started", "thread_id": "th-1"})
out({"type": "turn.started"})
time.sleep(0.3)
out({"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": "Codex mówi: z przykładem."}})
out({"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 3}})
'''


class ProcesyTests(unittest.TestCase):
    def setUp(self):
        cli._GROUP_SLOTS.clear()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeV1)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.root = Path(tempfile.mkdtemp(prefix="grupy-proc-", dir=_ROOT))
        home = self.root / "home"
        cfg = home / ".config" / "doma"
        cfg.mkdir(parents=True)
        (cfg / "konta.json").write_text(json.dumps({"konta": {"atrapa": {
            "base_url": f"http://127.0.0.1:{self.srv.server_address[1]}/v1", "api_key": "sk-test", "name": "Atrapa",
            "model": "atrapa-1"}}, "aktywne": "atrapa"}), encoding="utf-8")
        (cfg / "settings.json").write_text(json.dumps({"provider": "endpoint", "model_endpoint": "@atrapa/atrapa-1",
                                                       "lang": "pl"}), encoding="utf-8")
        codex = atrapa(self.root, "codex", _FAKE_CODEX)
        self.env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), DOMA_CONFIG_DIR=str(cfg), CODO_LANG="pl",
                        CODO_ONLINE="1", NO_COLOR="1", PYTHONUNBUFFERED="1", CODO_TEAM_SCRIPT=SCRIPT,
                        CODO_AGENT_CODEX=str(codex), CODO_AGENT_CLAUDE="/brak", CODO_AGENT_GEMINI="/brak")
        self.cfg = cfg
        self.proj = self.root / "proj"
        self.proj.mkdir()

    def tearDown(self):
        self.srv.shutdown()

    def test_app_server_grupa_z_dwoch_dostawcow(self):
        p = subprocess.Popen([sys.executable, SCRIPT, "app-server"], cwd=self.proj, env=self.env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        seen = []

        def send(**o):
            p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
            p.stdin.flush()

        def wait(kind, timeout=90, pred=lambda e: True):
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                line = p.stdout.readline()
                if not line:
                    break
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                seen.append(e)
                if e.get("type") == kind and pred(e):
                    return e
            raise AssertionError(f"brak {kind}: {[x.get('type') for x in seen[-12:]]}")
        try:
            ready = wait("ready")
            self.assertIn("group1", ready["features"])
            send(type="group_save", group={"name": "Duet", "strategy": "parallel", "lead": "Konto", "members": [
                {"name": "Codex", "brain": "agent:codex", "role": "przykłady"},
                {"name": "Konto", "brain": "@atrapa/atrapa-1", "role": "zwięzłość"}]})
            lst = wait("group_list")
            self.assertEqual(lst["groups"][0]["name"], "Duet")
            self.assertEqual({s["id"] for s in lst["strategies"]}, set(cli._GROUP_STRATEGIES))
            send(type="group_start", group="Duet", task="Jak opisać grupy agentów?", run_id="g-okno-1")
            done = wait("group_done", 120)
            self.assertEqual(done["status"], "done", done)
            self.assertEqual(done["run_id"], "g-okno-1")
            self.assertEqual(done["result"]["kind"], "synthesis")
            self.assertEqual(done["result"]["text"], "Synteza: najlepsze z obu.")
            texts = {e["member"]: e["text"] for e in seen if e.get("type") == "group_text" and e["phase"] == "answers"}
            self.assertEqual(texts, {"codex": "Codex mówi: z przykładem.", "konto": "Konto mówi: krótko i jasno."})
            self.assertTrue(any(e.get("type") == "group_member_event" for e in seen))
            labels = {m["id"]: (m["brain_label"], m["cost"]) for m in done["members"]}
            self.assertEqual(labels["codex"], ("Codex", "plan"))
            send(type="group_runs")
            runs = wait("group_runs")
            self.assertEqual(runs["runs"][0]["group"], "Duet")
            send(type="group_attach", run_id=done["run_id"])
            wait("group_started")
            self.assertTrue((self.cfg / "grupy.json").exists())
        finally:
            zakoncz(p)

    def test_codo_grupa_w_terminalu(self):
        r = subprocess.run([sys.executable, SCRIPT, "grupa", "nowa", "Para", "agent:codex=Kodeks", "@atrapa/atrapa-1=Konto",
                            "--sposob", "pipeline"], cwd=self.proj, env=self.env, capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, SCRIPT, "grupa", "run", "Para", "Opisz potok"], cwd=self.proj, env=self.env,
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Krok 2 z 2: Konto", r.stdout)
        self.assertIn("Konto mówi", r.stdout)
        r = subprocess.run([sys.executable, SCRIPT, "grupa", "list"], cwd=self.proj, env=self.env, capture_output=True,
                           text=True, timeout=60, stdin=subprocess.DEVNULL, encoding="utf-8")
        self.assertIn("Kodeks", r.stdout)


if __name__ == "__main__":
    unittest.main()


class RozmowaTests(_Base):
    def test_rozmowa_kazdy_odpisuje_po_kolei_bez_syntezy(self):
        prompts = {}

        def script(mid, brain, text):
            prompts[mid] = text
            return (True, "Hej, tu " + mid, 0, "")
        FakeMember.script = script
        g = group("chat", members3())
        g["history"] = "Ty: wcześniej\nAla: coś"
        r, st, events = run(g, task="hejka")
        self.assertEqual(st["status"], "done")
        said = [e["member"] for e in r.entries if e["phase"] == "chat"]
        self.assertEqual(sorted(said), sorted(m["id"] for m in g["members"]))
        self.assertEqual(r.result["kind"], "chat")
        self.assertIn("Na czacie są też: Ala, Cezary", prompts[g["members"][1]["id"]])
        self.assertIn("Odpisz zawsze", prompts[g["members"][2]["id"]])
        self.assertNotIn("CISZA", prompts[g["members"][2]["id"]])
        self.assertIn("WCZEŚNIEJ NA CZACIE", prompts[g["members"][0]["id"]])
        self.assertFalse(any(e["phase"] == "synthesis" for e in r.entries))

    def test_rozmowa_reakcja_emotka(self):
        def script(mid, brain, text):
            if mid.startswith("a"):
                return (True, "REAKCJA: 👍", 0, "")
            return (True, "REAKCJA: 🎉\nSuper pomysł!", 0, "")
        FakeMember.script = script
        g = group("chat", members3())
        r, st, events = run(g, task="mam nową pracę")
        chat = [e for e in r.entries if e["phase"] == "chat"]
        self.assertEqual(len(chat), 3)
        only = [e for e in chat if e["member"].startswith("a")][0]
        self.assertEqual(only.get("reaction"), "👍")
        self.assertEqual(only["text"], "")
        other = [e for e in chat if not e["member"].startswith("a")][0]
        self.assertEqual(other.get("reaction"), "🎉")
        self.assertEqual(other["text"], "Super pomysł!")
        self.assertNotIn("REAKCJA", r.result["text"])

    def test_rozmowa_zlecenia_miedzy_agentami(self):
        prompts = {}

        def script(mid, brain, text):
            prompts.setdefault(mid, []).append(text)
            if "ZLECA CI" in text:
                return (True, "Zrobione, sprawdziłem testy.", 0, "")
            if mid == g["members"][0]["id"]:
                return (True, "Biorę plan.\nZLECAM " + g["members"][1]["name"] + ": uruchom testy\nZLECAM Nikt: coś", 0, "")
            return (True, "Ok", 0, "")
        FakeMember.script = script
        g = group("chat", members3())
        r, st, events = run(g, task="zróbcie to razem")
        chat = [e for e in r.entries if e["phase"] == "chat"]
        first = [e for e in chat if e["member"] == g["members"][0]["id"]][0]
        self.assertEqual(first["text"], "Biorę plan.")
        self.assertEqual(first["assigns"], [{"to": g["members"][1]["id"], "task": "uruchom testy"}])
        done = [e for e in chat if e.get("from") == g["members"][0]["id"]]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["member"], g["members"][1]["id"])
        self.assertEqual(done[0]["round"], 2)
        self.assertIn("ZLECA CI: uruchom testy", prompts[g["members"][1]["id"]][-1])
        self.assertIn("Biorę plan.", prompts[g["members"][1]["id"]][-1])

    def test_rozmowa_zlecenia_sie_nie_zapetlaja(self):
        calls = []

        def script(mid, brain, text):
            calls.append(mid)
            nxt = [m for m in g["members"] if m["id"] != mid][0]["name"]
            return (True, "Ty to zrób\nZLECAM " + nxt + ": dalej", 0, "")
        FakeMember.script = script
        g = group("chat", members3())
        r, st, events = run(g, task="start")
        self.assertLessEqual(len(calls), 3 + 6)
        self.assertEqual(st["status"], "done")

    def test_rozmowa_wszyscy_naraz(self):
        import time
        FakeMember.script = staticmethod(lambda mid, brain, text: (True, "Hej", 0, "", 0.4))
        g = group("chat", members3())
        g["limits"]["per_provider"] = 6
        t = time.time()
        r, st, events = run(g, task="hejka")
        self.assertEqual(len([e for e in r.entries if e["phase"] == "chat"]), 3)
        self.assertLess(time.time() - t, 1.0)

    def test_rozmowa_wolany_po_imieniu_odpisuje_sam(self):
        FakeMember.script = lambda mid, brain, text: (True, "Jestem, " + mid, 0, "")
        g = group("chat", members3())
        who = g["members"][2]
        r, st, events = run(g, task="@" + who["name"].split()[0] + " co słychać?")
        said = [e["member"] for e in r.entries if e["phase"] == "chat"]
        self.assertEqual(said, [who["id"]])
        self.assertEqual(r.members[g["members"][0]["id"]]["status"], "skipped")
