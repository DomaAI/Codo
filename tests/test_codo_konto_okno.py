"""Codo 23.11.2026: okno „Konto DomaAI” (logowanie hasłem, rejestracja, kod z maila, nowe hasło).
Silnik rozmawia z API i zostawia tylko sparowane urządzenie; hasło nie trafia do zdarzeń ani na dysk.
Bez sieci: _http jest atrapą, która odgrywa kontrakty z routers/auth.py i routers/cli_agent.py."""
import os
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import jako_unittest, pytest  # noqa: E402

loader = importlib.machinery.SourceFileLoader(
    "doma_cli_konto_okno", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)

HASLO = "Tajne-haslo-123"


class Atrapa:
    """Serwer DomaAI w pamięci: konta, kody, plan i wywołania."""

    def __init__(self, plan="pro", zweryfikowane=True, wymaga_kodu=False):
        self.plan, self.zweryfikowane, self.wymaga_kodu = plan, zweryfikowane, wymaga_kodu
        self.calls = []
        self.limit = False
        self.haslo = HASLO

    def __call__(self, method, path, *, token=None, json_body=None, form=None, **_kw):
        self.calls.append((method, path, dict(form or json_body or {}), token))
        f = form or {}
        if self.limit:
            raise cli.ApiError(429, "Zbyt wiele prób. Spróbuj ponownie za 15 minut.", {})
        if path == "/login":
            if f.get("password") != self.haslo:
                raise cli.ApiError(401, "Nieprawidłowy email lub hasło", {})
            if not self.zweryfikowane:
                raise cli.ApiError(403, "Email niezweryfikowany.", {"email_verification_required": True})
            if self.wymaga_kodu and f.get("email_otp") != "123456":
                raise cli.ApiError(403, "Podaj kod", {"requires_email_otp": True})
            return {"access_token": "sesja", "refresh_token": "r", "full_name": "Ala Testowa", "user_id": 7}
        if path == "/cli/pair/self":
            if self.plan == "free":
                det = {"code": "PLAN_REQUIRED", "action": "cli_pair", "plan": "free", "required_plan": "base",
                       "detail": "Parowanie urządzeń wymaga planu Base+."}
                raise cli.ApiError(403, det, {"detail": det})
            return {"ok": True, "device_id": "dev-1", "device_secret": "sek-1", "name": "Mac testowy"}
        if path == "/logout":
            return {"status": "success"}
        if path == "/cli/pair/token":
            return {"access_token": "urz", "expires_in": 180}
        if path == "/cli/whoami":
            return {"imie": "Ala Testowa", "email": "a***@example.com", "plan": self.plan, "saldo": 100}
        if path == "/register":
            if f.get("email") == "jest@example.com":
                return {"status": "success", "message": "Zarejestrowano pomyślnie. Spróbuj się zalogować."}
            if len(f.get("password", "")) < 10:
                raise cli.ApiError(400, "Hasło musi mieć co najmniej 10 znaków", {})
            return {"status": "success", "user_id": 8, "email_verification_required": True}
        if path == "/verify_email":
            if f.get("code") == "999999":
                raise cli.ApiError(400, "Kod wygasł. Poproś o nowy kod (/resend_verification).", {})
            if f.get("code") != "654321":
                raise cli.ApiError(401, "Nieprawidłowy kod weryfikacyjny.", {})
            self.zweryfikowane = True
            return {"status": "success"}
        if path in ("/resend_verification", "/forgot_password"):
            return {"status": "success"}
        if path == "/reset_password":
            if f.get("code") != "111222":
                raise cli.ApiError(401, "Nieprawidłowy kod resetu.", {})
            if len(f.get("new_password", "")) < 10:
                raise cli.ApiError(400, "Nowe hasło musi mieć co najmniej 10 znaków.", {})
            self.haslo = f["new_password"]
            return {"status": "success"}
        raise AssertionError(f"nieoczekiwane {method} {path}")


@pytest.fixture
def okno(tmp_path, monkeypatch):
    for name, file in (("CONFIG_DIR", tmp_path), ("CRED_FILE", tmp_path / "credentials.json"),
                       ("DEVICE_FILE", tmp_path / "device.json"), ("SETTINGS_FILE", tmp_path / "settings.json"),
                       ("MADDLABS_FILE", tmp_path / "maddlabs.json"),
                       ("ACCOUNT_FILE", tmp_path / "account.json")):
        monkeypatch.setattr(cli, name, file)
    for fn in ("_app_status", "_app_catalog", "_app_models", "_app_limits"):
        monkeypatch.setattr(cli, fn, lambda: None)
    monkeypatch.setattr(cli, "save_agent_profile", lambda who: {})
    out = io.StringIO()
    monkeypatch.setattr(cli, "_APP", {**cli._APP, "out": out})
    cli._account_forget()

    def zdarzenia():
        return [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    return tmp_path, zdarzenia


def ostatnie(zdarzenia):
    return [e for e in zdarzenia() if e["type"] == "account"][-1]


def test_logowanie_haslem_paruje_i_wylogowuje_sesje(okno, monkeypatch):
    tmp, zdarzenia = okno
    api = Atrapa()
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "login", "email": " Ala@Example.com ", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done" and e["name"] == "Ala Testowa" and e["plan"] == "pro"
    assert e["email"] == "ala@example.com"
    dev = json.loads((tmp / "device.json").read_text(encoding="utf-8"))
    assert dev["device_id"] == "dev-1"
    assert not (tmp / "credentials.json").exists()
    paths = [c[1] for c in api.calls]
    assert paths[:3] == ["/login", "/cli/pair/self", "/logout"]
    assert api.calls[1][3] == "sesja" and api.calls[2][3] == "sesja"
    assert cli._account_pending() is None


def test_haslo_nie_trafia_do_zdarzen_ani_na_dysk(okno, monkeypatch):
    tmp, zdarzenia = okno
    monkeypatch.setattr(cli, "_http", Atrapa(wymaga_kodu=True))
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    cli._app_account({"action": "code", "code": "123456"})
    calosc = json.dumps(zdarzenia())
    assert HASLO not in calosc
    for p in tmp.rglob("*"):
        if p.is_file():
            assert HASLO not in p.read_text(errors="ignore", encoding="utf-8")


def test_zle_haslo_przy_polu_hasla(okno, monkeypatch):
    tmp, zdarzenia = okno
    monkeypatch.setattr(cli, "_http", Atrapa())
    cli._app_account({"action": "login", "email": "ala@example.com", "password": "zle-haslo-1"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "bad_credentials" and e["field"] == "password"
    assert not (tmp / "device.json").exists()


def test_zly_adres_bez_sieci(okno, monkeypatch):
    _, zdarzenia = okno
    api = Atrapa()
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "login", "email": "nie-mail", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["code"] == "bad_email" and e["field"] == "email" and api.calls == []


def test_kod_z_maila_przy_logowaniu(okno, monkeypatch):
    tmp, zdarzenia = okno
    monkeypatch.setattr(cli, "_http", Atrapa(wymaga_kodu=True))
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["state"] == "code" and e["kind"] == "email"
    cli._app_account({"action": "code", "code": "000000"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "bad_code" and e["field"] == "code"
    cli._app_account({"action": "code", "code": "123456"})
    assert ostatnie(zdarzenia)["state"] == "done"
    assert (tmp / "device.json").exists()


def test_plan_wymagany_nic_nie_zapisuje(okno, monkeypatch):
    tmp, zdarzenia = okno
    api = Atrapa(plan="free")
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "plan_required"
    assert e["required_plan"] == "base" and e["url"].startswith("https://")
    assert e["name"] == "Ala Testowa"
    assert not (tmp / "device.json").exists()
    assert "/logout" in [c[1] for c in api.calls]


def test_za_duzo_prob_z_czasem(okno, monkeypatch):
    _, zdarzenia = okno
    api = Atrapa()
    api.limit = True
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["code"] == "rate_limited" and e["retry_after"] == 900


def test_brak_sieci(okno, monkeypatch):
    _, zdarzenia = okno

    def offline(*_a, **_k):
        raise cli.urllib.error.URLError("brak trasy")
    monkeypatch.setattr(cli, "_http", offline)
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    assert ostatnie(zdarzenia)["code"] == "offline"


def test_rejestracja_weryfikacja_i_automatyczne_logowanie(okno, monkeypatch):
    tmp, zdarzenia = okno
    api = Atrapa(zweryfikowane=False)
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "register", "email": "nowa@example.com", "password": HASLO,
                      "name": "", "accepted": True})
    e = ostatnie(zdarzenia)
    assert e["state"] == "verify" and e["email"] == "nowa@example.com"
    reg = api.calls[0][2]
    assert reg["full_name"] == "Nowa"
    assert all(reg[k] == "true" for k in ("accepted_terms", "accepted_privacy",
                                          "accepted_subscription_terms", "age_acknowledged_16plus"))
    cli._app_account({"action": "verify", "email": "nowa@example.com", "code": "12 34 56"})
    assert ostatnie(zdarzenia)["code"] == "bad_code"
    cli._app_account({"action": "verify", "email": "nowa@example.com", "code": "999999"})
    assert ostatnie(zdarzenia)["code"] == "code_expired"
    cli._app_account({"action": "resend", "email": "nowa@example.com"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "sent" and e["cooldown"] == 60
    cli._app_account({"action": "verify", "email": "nowa@example.com", "code": "654321"})
    assert ostatnie(zdarzenia)["state"] == "done"
    assert (tmp / "device.json").exists()


def test_rejestracja_bez_zgody_i_slabe_haslo(okno, monkeypatch):
    _, zdarzenia = okno
    api = Atrapa()
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "register", "email": "nowa@example.com", "password": HASLO, "accepted": False})
    assert ostatnie(zdarzenia)["field"] == "consent" and api.calls == []
    cli._app_account({"action": "register", "email": "nowa@example.com", "password": "krotkie1", "accepted": True})
    e = ostatnie(zdarzenia)
    assert e["field"] == "password" and "10 znaków" in e["error"]


def test_rejestracja_na_istniejacy_adres(okno, monkeypatch):
    _, zdarzenia = okno
    monkeypatch.setattr(cli, "_http", Atrapa())
    cli._app_account({"action": "register", "email": "jest@example.com", "password": HASLO, "accepted": True})
    e = ostatnie(zdarzenia)
    assert e["state"] == "verify" and e["maybe_exists"] is True


def test_niezweryfikowane_konto_przy_logowaniu(okno, monkeypatch):
    _, zdarzenia = okno
    monkeypatch.setattr(cli, "_http", Atrapa(zweryfikowane=False))
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    e = ostatnie(zdarzenia)
    assert e["state"] == "verify" and e["resend"] is True
    cli._app_account({"action": "verify", "email": "ala@example.com", "code": "654321"})
    assert ostatnie(zdarzenia)["state"] == "done"


def test_nowe_haslo_kodem_z_maila(okno, monkeypatch):
    tmp, zdarzenia = okno
    api = Atrapa()
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "forgot", "email": "ala@example.com"})
    assert ostatnie(zdarzenia)["state"] == "sent"
    cli._app_account({"action": "reset", "email": "ala@example.com", "code": "000000", "password": "Nowe-haslo-456"})
    assert ostatnie(zdarzenia)["code"] == "bad_code"
    cli._app_account({"action": "reset", "email": "ala@example.com", "code": "111222", "password": "Nowe-haslo-456"})
    assert ostatnie(zdarzenia)["state"] == "done"
    assert (tmp / "device.json").exists()


def test_poprzednie_urzadzenie_odparowane(okno, monkeypatch):
    tmp, zdarzenia = okno
    cli.save_device({"device_id": "stare", "device_secret": "s", "name": "Mac"})
    api = Atrapa()
    monkeypatch.setattr(cli, "_http", api)
    cli._app_account({"action": "login", "email": "ala@example.com", "password": HASLO})
    assert ostatnie(zdarzenia)["state"] == "done"
    assert "/cli/device/logout" not in [c[1] for c in api.calls[:3]]
    tokeny = [c for c in api.calls if c[1] == "/cli/pair/token"]
    assert tokeny[0][2]["device_id"] == "stare"
    assert json.loads((tmp / "device.json").read_text(encoding="utf-8"))["device_id"] == "dev-1"


def test_czytnik_przyjmuje_konto_od_razu(okno, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "_app_account", lambda m: seen.append(m))
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(json.dumps({"type": "account", "action": "cancel"}) + "\n"))
    inbox = []
    cli._app_reader(inbox, cli.threading.Event())
    import time
    time.sleep(0.1)
    assert seen and seen[0]["action"] == "cancel"
    assert all(m.get("type") != "account" for m in inbox)


load_tests = jako_unittest(globals())
