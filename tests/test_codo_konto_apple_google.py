"""Codo 24.11.2026: Kontynuuj z Apple i z Google w oknie Codo. Okno oddaje silnikowi identity_token
i surowy nonce z arkusza, silnik robi to, co aplikacja na iPhone'a: /auth/<dostawca>/check, logowanie
albo zgody nowego konta, nowy regulamin przez /account/accept_tos. Atrapa serwera na 127.0.0.1."""
import base64
import json

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from codo_atrapy import jako_unittest, pytest  # noqa: E402

import test_codo_konto_kod as base  # noqa: E402
from test_codo_konto_kod import TOKEN, DEV_SECRET, ostatnie, serwer  # noqa: F401  (fixture)

cli = base.cli
NONCE = "n" * 32


def jwt_bez_podpisu(claims: dict) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.podpis"


APPLE_TOK = jwt_bez_podpisu({"sub": "001.apple", "email": "ola@privaterelay.appleid.com"})
GOOGLE_TOK = jwt_bez_podpisu({"sub": "g-1", "email": "ala@example.com", "name": "Ala Kowalska"})


@pytest.fixture
def social(serwer):  # noqa: F811
    stan, tmp, zdarzenia = serwer
    stan.social = {"g-1": {"tos": False}}   # konto Google istnieje, Apple nie
    stary = stan.obsluz

    def obsluz(method, path, form, headers):
        if path in ("/auth/apple/check", "/auth/google/check", "/auth/apple", "/auth/google",
                    "/account/accept_tos"):
            stan.zadania.append((method, path, dict(form), dict(headers)))
            if form.get("nonce") != NONCE:
                return 401, {"detail": "Nieprawidłowy nonce"}
            sub = "001.apple" if form.get("identity_token") == APPLE_TOK else "g-1"
            if path.endswith("/check"):
                return 200, {"exists": sub in stan.social}
            if path == "/account/accept_tos":
                stan.social[sub]["tos"] = False
                return 200, {"status": "success", "user_id": 7}
            konto = stan.social.get(sub)
            if konto is None:
                if form.get("age_acknowledged_16plus") != "true":
                    return 400, {"detail": "Wymagane potwierdzenie wieku (≥16 lat). RODO Art 8."}
                stan.social[sub] = {"tos": False}
                stan.konta.setdefault("ola@privaterelay.appleid.com", {"imie": form.get("full_name"),
                                                                      "plan": "max", "totp": None})
            elif konto["tos"]:
                return 403, {"detail": "Zaktualizowaliśmy Regulamin.", "requires_tos_acceptance": True}
            return 200, {"status": "success", "access_token": TOKEN, "refresh_token": "r",
                         "full_name": form.get("full_name") or "Ala Kowalska", "user_id": 7}
        return stary(method, path, form, headers)

    stan.obsluz = obsluz
    # plan po zalogowaniu: atrapa patrzy na ostatnie /auth/kod*, tu zawsze max
    stan._plan_zalogowanego = lambda: "max"
    return stan, tmp, zdarzenia


def test_google_istniejace_konto_od_razu_paruje(social):
    stan, tmp, zdarzenia = social
    cli._app_account({"action": "google", "identity_token": GOOGLE_TOK, "nonce": NONCE})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done" and e["email"] == "ala@example.com" and e["plan"] == "max"
    paths = [z[1] for z in stan.zadania]
    assert paths[:4] == ["/auth/google/check", "/auth/google", "/cli/pair/self", "/logout"]
    form = stan.zadania[1][2]
    assert form["identity_token"] == GOOGLE_TOK and form["nonce"] == NONCE
    assert "age_acknowledged_16plus" not in form
    dev = json.loads((tmp / "device.json").read_text())
    assert dev["device_id"] == "dev-1"
    calosc = json.dumps(zdarzenia())
    assert TOKEN not in calosc and DEV_SECRET not in calosc and GOOGLE_TOK not in calosc


def test_apple_nowe_konto_zgody_potem_rejestracja(social):
    stan, tmp, zdarzenia = social
    cli._app_account({"action": "apple", "identity_token": APPLE_TOK, "nonce": NONCE, "name": "Ola"})
    e = ostatnie(zdarzenia)
    assert e["state"] == "new_account" and e["provider"] == "apple" and e["name"] == "Ola"
    assert e["email"] == "ola@privaterelay.appleid.com"
    assert [z[1] for z in stan.zadania] == ["/auth/apple/check"]
    cli._app_account({"action": "finish", "name": "Ola", "accepted": False})
    assert ostatnie(zdarzenia)["code"] == "consent"
    cli._app_account({"action": "finish", "name": "Ola", "accepted": True})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done", e
    form = [z for z in stan.zadania if z[1] == "/auth/apple"][-1][2]
    assert form["is_registration"] == "true" and form["age_acknowledged_16plus"] == "true"
    assert form["accepted_terms"] == form["accepted_privacy"] == form["accepted_subscription_terms"] == "true"
    assert form["full_name"] == "Ola" and form["nonce"] == NONCE
    assert cli._account_pending() is None


def test_nowy_regulamin_akceptacja_tym_samym_tokenem(social):
    stan, tmp, zdarzenia = social
    stan.social["g-1"]["tos"] = True
    cli._app_account({"action": "google", "identity_token": GOOGLE_TOK, "nonce": NONCE})
    e = ostatnie(zdarzenia)
    assert e["state"] == "terms" and e["provider"] == "google"
    cli._app_account({"action": "check_code", "accept_tos": True})
    e = ostatnie(zdarzenia)
    assert e["state"] == "done"
    paths = [z[1] for z in stan.zadania]
    assert paths[:5] == ["/auth/google/check", "/auth/google", "/account/accept_tos", "/auth/google",
                         "/cli/pair/self"]
    assert stan.zadania[2][2]["identity_token"] == GOOGLE_TOK


def test_zly_token_bez_zadania(social):
    stan, tmp, zdarzenia = social
    cli._app_account({"action": "apple", "identity_token": "nie-jwt", "nonce": NONCE})
    assert ostatnie(zdarzenia)["code"] == "social_token"
    cli._app_account({"action": "apple", "identity_token": APPLE_TOK, "nonce": "krotki"})
    assert ostatnie(zdarzenia)["code"] == "social_token"
    assert stan.zadania == []


def test_odrzucony_token_mowi_sprobuj_jeszcze_raz(social):
    stan, tmp, zdarzenia = social
    cli._app_account({"action": "google", "identity_token": GOOGLE_TOK, "nonce": "x" * 32})
    e = ostatnie(zdarzenia)
    assert e["state"] == "failed" and e["code"] == "social_token"
    assert not (tmp / "device.json").exists()


def test_kod_z_maila_po_apple_nie_miesza_sie(social):
    """Ktoś zaczął Apple (strona zgód), potem wpisał e-mail: kod z maila działa jak zwykle."""
    stan, tmp, zdarzenia = social
    cli._app_account({"action": "apple", "identity_token": APPLE_TOK, "nonce": NONCE})
    cli._app_account({"action": "send_code", "email": "ala@example.com"})
    cli._app_account({"action": "check_code", "email": "ala@example.com", "code": "123456"})
    assert ostatnie(zdarzenia)["state"] == "done"


load_tests = jako_unittest(globals())
