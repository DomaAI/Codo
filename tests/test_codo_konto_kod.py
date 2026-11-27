"""Codo 23.11.2026: logowanie i rejestracja kodem z maila z okna (kontrakt /auth/kod).
Atrapa serwera to prawdziwy serwer HTTP na 127.0.0.1 (nie produkcja): sprawdzamy formularze,
nagłówek X-Codo, zapis urządzenia i to, że tokeny nie trafiają do zdarzeń ani na dysk."""
import os
import importlib.machinery
import importlib.util
import io
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

loader = importlib.machinery.SourceFileLoader(
    "doma_cli_konto_kod", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)
STATUS = cli._app_status

TOKEN = "tajny-token-sesji-abc"
DEV_SECRET = "sekret-urzadzenia-xyz"


class Serwer:
    """Stan atrapy: konta, kody, plan, liczniki prób i zapis żądań."""

    def __init__(self):
        self.konta = {"ala@example.com": {"imie": "Ala Kowalska", "plan": "max", "totp": None}}
        self.kody = {}
        self.bilety = {}
        self.proby = {}
        self.zadania = []
        self.wysylki = {}

    def obsluz(self, method, path, form, headers):
        self.zadania.append((method, path, dict(form), dict(headers)))
        auth = headers.get("Authorization", "")
        if path == "/auth/kod":
            e = form.get("email", "").lower()
            if "@" not in e:
                return 400, {"detail": "Nieprawidłowy adres e-mail."}
            if e.endswith("@cloud.com") and not self.wysylki.get("lit:" + e):
                self.wysylki["lit:" + e] = True
                sug = e.replace("@cloud.com", "@icloud.com")
                return 400, {"detail": f"Czy chodziło o {sug}?", "sugestia": sug}
            if self.wysylki.get(e):
                return 429, {"detail": "Za często.", "ponownie_za": 42}
            self.wysylki[e] = True
            self.kody[e] = "123456"
            self.proby[e] = 5
            return 200, {"status": "wyslano", "ponownie_za": 60}
        if path == "/auth/kod/weryfikuj":
            e = form.get("email", "").lower()
            if self.kody.get(e) != form.get("code"):
                self.proby[e] = max(0, self.proby.get(e, 5) - 1)
                return 401, {"detail": "Nieprawidłowy albo wygasły kod.", "pozostalo_prob": self.proby[e]}
            konto = self.konta.get(e)
            if konto is None:
                self.bilety["bilet-1"] = e
                return 200, {"status": "rejestracja", "bilet": "bilet-1", "email": e}
            if konto.get("tos") and form.get("accept_tos") != "1":
                return 403, {"detail": "Zaakceptuj regulamin.", "requires_tos_acceptance": True}
            if konto["totp"]:
                kod = form.get("totp_code")
                if kod != konto["totp"]:
                    return 403, {"detail": "Nieprawidłowy kod weryfikacyjny." if kod else "Podaj kod.",
                                 "requires_2fa": True}
            return 200, {"status": "success", "message": "ok", "access_token": TOKEN, "refresh_token": "r",
                         "full_name": konto["imie"], "user_id": 7}
        if path == "/auth/kod/rejestracja":
            e = self.bilety.pop(form.get("bilet", ""), None)
            if e is None:
                return 410, {"detail": "Bilet wygasł."}
            if form.get("age_acknowledged_16plus") != "true" or form.get("accepted_terms") != "true":
                return 400, {"detail": "Wymagana akceptacja regulaminu."}
            self.konta[e] = {"imie": form["full_name"], "plan": "free", "totp": None}
            return 201, {"status": "success", "message": "ok", "access_token": TOKEN, "refresh_token": "r",
                         "full_name": form["full_name"], "user_id": 9}
        if path == "/cli/pair/self":
            assert auth == f"Bearer {TOKEN}"
            e = next(iter(k for k, v in self.konta.items()), "")
            plan = self._plan_zalogowanego()
            if plan == "free":
                det = {"code": "PLAN_REQUIRED", "action": "cli_pair", "plan": "free", "required_plan": "base",
                       "detail": "Parowanie urządzeń wymaga planu Base+."}
                return 403, {"detail": det}
            return 200, {"ok": True, "device_id": "dev-1", "device_secret": DEV_SECRET, "name": "Mac testowy", "e": e}
        if path == "/logout":
            return 200, {"status": "success"}
        if path == "/cli/pair/token":
            return 200, {"access_token": "urz", "expires_in": 180}
        if path == "/cli/whoami":
            return 200, {"imie": "Ala Kowalska", "email": "a•••a@example.com", "plan": "max", "saldo": 100}
        return 404, {"detail": "brak"}

    def _plan_zalogowanego(self):
        ostatni = [z for z in self.zadania if z[1] in ("/auth/kod/weryfikuj", "/auth/kod/rejestracja")]
        if ostatni and ostatni[-1][1] == "/auth/kod/rejestracja":
            return "free"
        e = ostatni[-1][2].get("email", "") if ostatni else ""
        return self.konta.get(e, {}).get("plan", "free")


@pytest.fixture
def serwer(tmp_path, monkeypatch):
    stan = Serwer()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _go(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode() if n else ""
            if self.headers.get("Content-Type", "").startswith("application/json"):
                form = json.loads(raw or "{}")
            else:
                form = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
            path = self.path.split("?")[0]
            code, body = stan.obsluz(self.command, path, form, self.headers)
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _go

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setattr(cli, "API_URL", f"http://127.0.0.1:{httpd.server_address[1]}")
    for name, file in (("CONFIG_DIR", tmp_path), ("CRED_FILE", tmp_path / "credentials.json"),
                       ("DEVICE_FILE", tmp_path / "device.json"), ("SETTINGS_FILE", tmp_path / "settings.json"),
                       ("MADDLABS_FILE", tmp_path / "maddlabs.json"), ("ACCOUNT_FILE", tmp_path / "account.json"),
                       ("AGENT_FILE", tmp_path / "agent.json")):
        monkeypatch.setattr(cli, name, file)
    for fn in ("_app_catalog", "_app_models", "_app_limits"):
        monkeypatch.setattr(cli, fn, lambda: None)
    statusy = []
    monkeypatch.setattr(cli, "_app_status", lambda: statusy.append(1))
    monkeypatch.setattr(cli, "save_agent_profile", lambda who: {})
    monkeypatch.setattr(cli, "_LANG", ["pl"])
    out = io.StringIO()
    monkeypatch.setattr(cli, "_APP", {**cli._APP, "out": out})
    cli._account_forget()

    def zdarzenia():
        return [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    yield stan, tmp_path, zdarzenia
    httpd.shutdown()


def ostatnie(zdarzenia):
    return [e for e in zdarzenia() if e["type"] == "account"][-1]


def test_wyslanie_kodu_z_naglowkiem_codo_i_jezykiem(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": " Ala@Example.com "})
    e = ostatnie(zdarzenia)
    assert e["state"] == "sent" and e["action"] == "send_code" and e["cooldown"] == 60
    assert e["email"] == "ala@example.com"
    method, path, form, headers = stan.zadania[-1]
    assert path == "/auth/kod" and form == {"email": "ala@example.com", "jezyk": "pl"}
    assert headers.get("X-Codo")


def test_za_czesto_podaje_czas(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "resend_code", "email": "ala@example.com"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "too_often" and e["retry_after"] == 42


def test_zly_adres_bez_wysylki(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "ala@"})
    e = ostatnie(zdarzenia)
    assert e["code"] == "bad_email" and e["field"] == "email"
    assert stan.zadania == []


def test_istniejace_konto_kod_paruje_mac_plan_i_email(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "123 456"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done" and e["email"] == "ala@example.com"
    assert e["plan"] == "max" and e["name"] == "Ala Kowalska"
    dev = json.loads((tmp / "device.json").read_text())
    assert dev["device_id"] == "dev-1" and dev["email"] == "ala@example.com"
    info = json.loads((tmp / "account.json").read_text())
    assert info == {"email": "ala@example.com", "name": "Ala Kowalska", "plan": "max"}
    paths = [z[1] for z in stan.zadania]
    assert paths[:4] == ["/auth/kod", "/auth/kod/weryfikuj", "/cli/pair/self", "/logout"]
    # Tokeny ani sekret urządzenia nie trafiają do zdarzeń okna.
    calosc = json.dumps(zdarzenia())
    assert TOKEN not in calosc and DEV_SECRET not in calosc
    assert TOKEN not in (tmp / "account.json").read_text()
    assert not (tmp / "credentials.json").exists()


def test_zly_kod_podaje_pozostale_proby_a_potem_martwy(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "000000"})
    e = ostatnie(zdarzenia)
    assert e["code"] == "bad_code" and e["field"] == "code" and e["attempts_left"] == 4
    assert "4" in e["error"]
    for _ in range(4):
        cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "000000"})
    e = ostatnie(zdarzenia)
    assert e["code"] == "code_dead" and e["attempts_left"] == 0
    assert not (tmp / "device.json").exists()


def test_niepelny_kod_bez_zadania(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "12"})
    assert ostatnie(zdarzenia)["code"] == "bad_code"
    assert stan.zadania == []


def test_nowe_konto_imie_zgody_i_logowanie(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "nowa@example.com"})
    cli._app_account({"action": "check_code", "email": "nowa@example.com", "code": "123456"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "new_account" and e["email"] == "nowa@example.com"
    assert "bilet" not in json.dumps(e)
    cli._app_account({"action": "finish", "name": "Ola", "accepted": False})
    assert ostatnie(zdarzenia)["code"] == "consent"
    cli._app_account({"action": "finish", "name": "", "accepted": True})
    assert ostatnie(zdarzenia)["code"] == "bad_name"
    cli._app_account({"action": "finish", "name": "Ola", "accepted": True})
    e = ostatnie(zdarzenia)
    # Nowe konto jest na planie Free: parowanie odmawia, ale konto jest potwierdzone (signed_in).
    assert e["state"] == "failed" and e["code"] == "plan_required" and e["signed_in"] is True
    form = [z for z in stan.zadania if z[1] == "/auth/kod/rejestracja"][-1][2]
    assert form == {"bilet": "bilet-1", "full_name": "Ola", "accepted_terms": "true", "accepted_privacy": "true",
                    "accepted_subscription_terms": "true", "age_acknowledged_16plus": "true", "zrodlo": "codo"}
    info = json.loads((tmp / "account.json").read_text())
    assert info["email"] == "nowa@example.com" and info["plan"] == "free"
    assert not (tmp / "device.json").exists()


def test_bilet_zuzyty_wraca_do_adresu(serwer):
    stan, tmp, zdarzenia = serwer
    cli._account_remember("nowa@example.com", kind="register", bilet="stary")
    cli._app_account({"action": "finish", "name": "Ola", "accepted": True})
    assert ostatnie(zdarzenia)["code"] == "ticket_expired"


def test_finish_bez_biletu(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "finish", "name": "Ola", "accepted": True})
    assert ostatnie(zdarzenia)["code"] == "ticket_expired"
    assert stan.zadania == []


def test_dwuetapowe_totp_po_kodzie_z_maila(serwer):
    stan, tmp, zdarzenia = serwer
    stan.konta["ala@example.com"]["totp"] = "777888"
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "123456"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "totp" and e["kind"] == "totp"
    cli._app_account({"action": "check_code", "totp": "111111"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "bad_totp"
    cli._app_account({"action": "check_code", "totp": "777888"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done" and e["plan"] == "max"
    forms = [z[2] for z in stan.zadania if z[1] == "/auth/kod/weryfikuj"]
    assert forms[-1] == {"email": "ala@example.com", "code": "123456", "totp_code": "777888"}


def test_brak_sieci(serwer, monkeypatch):
    stan, tmp, zdarzenia = serwer
    monkeypatch.setattr(cli, "API_URL", "http://127.0.0.1:9")
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    assert ostatnie(zdarzenia)["code"] == "offline"


def test_status_pokazuje_email_i_plan(serwer, monkeypatch):
    stan, tmp, zdarzenia = serwer
    cli.save_account_info({"email": "ala@example.com", "name": "Ala", "plan": "max"})
    assert cli.load_account_info()["plan"] == "max"
    # Wylogowanie zdejmuje też podpis konta.
    monkeypatch.setattr(cli, "print", lambda *a, **k: None, raising=False)
    cli.logout()
    assert not (tmp / "account.json").exists()


def test_zdarzenie_status_niesie_konto_i_plan(serwer, monkeypatch):
    stan, tmp, zdarzenia = serwer
    monkeypatch.setattr(cli, "online", lambda: True)
    monkeypatch.setattr(cli, "local_brains", lambda: [])
    STATUS()
    s = [e for e in zdarzenia() if e["type"] == "status"][-1]
    assert s["signed_in"] is False and s["domaai_email"] == "" and s["domaai_plan"] == ""
    cli.save_account_info({"email": "nowa@example.com", "name": "Ola", "plan": "free"})
    STATUS()
    s = [e for e in zdarzenia() if e["type"] == "status"][-1]
    assert s["signed_in"] is True and s["domaai"] is False
    assert s["domaai_email"] == "nowa@example.com" and s["domaai_plan"] == "free"


def test_mozg_z_domaai_trafia_do_profilu_agenta(serwer, monkeypatch):
    stan, tmp, zdarzenia = serwer
    monkeypatch.setattr(cli, "_models_cache_get", lambda k: {"models": [
        {"id": "lopus"}, {"id": "openai/gpt-5.6-terra"}, {"id": "x-ai/grok-4.7"},
        {"id": "anthropic/claude-opus-5-5"}]} if k == "domaai" else None)
    assert cli._domaai_brain_family("openai/gpt-5.6-terra") == "gpt"
    assert cli._domaai_brain_family("x-ai/grok-4.7") == "grok"
    assert cli._domaai_brain_family("anthropic/claude-opus-5-5") == "opus"
    assert cli._domaai_brain_family("lopus") == ""
    assert cli._domaai_brain_family("agent:codex") is None
    assert cli._domaai_brain_family("acct:moje/gpt-4o") is None
    zapisy = []

    def http(method, path, *, token=None, json_body=None, **_kw):
        zapisy.append((method, path, json_body))
        if path == "/cli/whoami":
            return {"agent": "Nova", "plan": "max"}
        return {}
    monkeypatch.setattr(cli, "_http", http)
    monkeypatch.setattr(cli, "device_access_token", lambda *a, **k: "urz")
    monkeypatch.setattr(cli, "save_agent_profile", lambda who: who)
    cli.save_created_agent({"name": "Nova", "brain": "openai/gpt-5.6-terra"})
    puts = [b for m, p, b in zapisy if m == "PUT"]
    assert puts[-1] == {"model_glowny": "gpt"}
    zapisy.clear()
    cli.save_created_agent({"name": "Nova", "brain": "agent:codex"})
    assert [b for m, p, b in zapisy if m == "PUT" and "model_glowny" in b] == []


def test_nowy_regulamin_akceptacja_tym_samym_kodem(serwer):
    stan, tmp, zdarzenia = serwer
    stan.konta["ala@example.com"]["tos"] = True
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "123456"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "terms"
    cli._app_account({"action": "check_code", "accept_tos": True})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done"
    forms = [z[2] for z in stan.zadania if z[1] == "/auth/kod/weryfikuj"]
    assert forms[-1] == {"email": "ala@example.com", "code": "123456", "accept_tos": "1"}


def test_naglowek_codo_na_wszystkich_trzech(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "nowa@example.com"})
    cli._app_account({"action": "check_code", "email": "nowa@example.com", "code": "123456"})
    cli._app_account({"action": "finish", "name": "Ola", "accepted": True})
    for path in ("/auth/kod", "/auth/kod/weryfikuj", "/auth/kod/rejestracja"):
        assert all(z[3].get("X-Codo") for z in stan.zadania if z[1] == path)


def test_literowka_w_adresie_podpowiada_i_drugi_raz_wysyla(serwer):
    stan, tmp, zdarzenia = serwer
    cli._app_account({"action": "send_code", "email": "ala@cloud.com"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "typo" and e["field"] == "email"
    assert e["suggestion"] == "ala@icloud.com" and "ala@icloud.com" in e["error"]
    cli._app_account({"action": "send_code", "email": "ala@cloud.com"})
    assert stan.kody.get("ala@cloud.com") == "123456"
