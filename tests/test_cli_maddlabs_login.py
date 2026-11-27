"""Codo 0.18.0: /login z wyborem DomaAI albo MaddLabs; bez konta DomaAI agent woła API MaddLabs.
Testy offline: _maddlabs_http jest podmieniony, nic nie idzie do sieci."""
import os
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

loader = importlib.machinery.SourceFileLoader(
    "doma_cli_maddlabs", str(Path(os.environ.get("CODO_FILE") or Path(__file__).resolve().parents[1] / "static/cli/doma")))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


@pytest.fixture
def konfig(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cli, "CRED_FILE", tmp_path / "credentials.json")
    monkeypatch.setattr(cli, "DEVICE_FILE", tmp_path / "device.json")
    monkeypatch.setattr(cli, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "MADDLABS_FILE", tmp_path / "maddlabs.json")
    return tmp_path


def test_bez_logowania_dostawca_domaai(konfig):
    assert cli.provider() == "domaai"
    assert cli._model_key() == "model"


def test_klucz_api_zapisany_prywatnie_i_aktywny(konfig, monkeypatch):
    calls = []

    def fake(method, path, **kw):
        calls.append((method, path, kw.get("key")))
        return {"data": {"name": "moj klucz"}}

    monkeypatch.setattr(cli, "_maddlabs_http", fake)
    assert cli.login_maddlabs_key("sk-test-123") == 0
    assert calls == [("GET", "/key", "sk-test-123")]
    zapis = json.loads((konfig / "maddlabs.json").read_text())
    assert zapis["api_key"] == "sk-test-123" and zapis["how"] == "klucz"
    assert oct((konfig / "maddlabs.json").stat().st_mode & 0o777) == "0o600"
    assert cli.provider() == "maddlabs" and cli._model_key() == "model_maddlabs"


def test_zly_klucz_nic_nie_zapisuje(konfig, monkeypatch):
    def fake(*_a, **_k):
        raise cli.ApiError(401, "Klucz MaddLabs jest nieważny")

    monkeypatch.setattr(cli, "_maddlabs_http", fake)
    assert cli.login_maddlabs_key("sk-zly") == 1
    assert not (konfig / "maddlabs.json").exists()
    assert cli.provider() == "domaai"


def test_krok_agenta_idzie_do_maddlabs_z_narzedziami(konfig, monkeypatch):
    cli._maddlabs_save({"api_key": "sk-x", "base_url": "https://maddlabs.co/v1"})
    seen = {}

    def fake(method, path, **kw):
        if path == "/models":
            return {"data": [{"id": "qwen/off", "is_ready": False}, {"id": "speakleash/bielik", "is_ready": True}]}
        seen.update(path=path, body=kw["json_body"], key=kw["key"], base=kw["base"])
        return {"model": "speakleash/bielik", "usage": {"completion_tokens": 3},
                "choices": [{"message": {"role": "assistant", "content": None, "reasoning": "x",
                                         "tool_calls": [{"id": "1", "type": "function",
                                                         "function": {"name": "read_file", "arguments": "{}"}}]}}]}

    monkeypatch.setattr(cli, "_maddlabs_http", fake)
    resp = cli.api_step(None, {"messages": [{"role": "user", "content": "hej"}], "tools": cli.TOOLS})
    assert seen["path"] == "/chat/completions" and seen["key"] == "sk-x"
    assert seen["body"]["model"] == "speakleash/bielik"  # pierwszy gotowy model
    assert seen["body"]["tools"] is cli.TOOLS
    assert resp["message"] == {"role": "assistant", "tool_calls": resp["message"]["tool_calls"]}
    assert resp["credits_spent"] == 0


def test_konto_maddlabs_przez_przegladarke(konfig, monkeypatch):
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda *_: None)
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    odp = iter([{"status": "pending"}, {"status": "confirmed", "api_key": "sk-konto", "account": "ML123456",
                                        "email": "a@b.c", "key_name": "Codo · mac", "base_url": "https://maddlabs.co/v1"}])

    def fake(method, path, **kw):
        if path == "/api/cli/start":
            assert kw["json_body"]["client"] == "codo"
            return {"device_code": "d", "user_code": "ABCD-1234", "expires_in": 600, "interval": 1,
                    "verification_url": "https://maddlabs.co/cli?code=ABCD-1234"}
        assert path == "/api/cli/poll" and kw["json_body"] == {"device_code": "d"}
        return next(odp)

    monkeypatch.setattr(cli, "_maddlabs_http", fake)
    assert cli.login_maddlabs_account() == 0
    zapis = json.loads((konfig / "maddlabs.json").read_text())
    assert zapis["api_key"] == "sk-konto" and zapis["how"] == "konto" and zapis["account"] == "ML123456"
    assert cli.provider() == "maddlabs"


def test_login_menu_aliasy_i_powrot_do_domaai(konfig, monkeypatch):
    cli._maddlabs_save({"api_key": "sk-x"})
    monkeypatch.setattr(cli, "login", lambda: 0)
    assert cli.login_menu("domaai") == 0
    assert cli.provider() == "domaai"
    monkeypatch.setattr(cli, "login_maddlabs_key", lambda: 7)
    assert cli.login_menu("api") == 7
    assert "/login" in cli._SLASH


# ── 0.18.2: MaddLabs z narzędziami DomaAI ───────────────────────────────────

def _maddlabs_i_domaai(konfig, monkeypatch):
    monkeypatch.delenv("CODO_MADDLABS_DIRECT", raising=False)
    cli._maddlabs_save({"api_key": "sk-x", "base_url": "https://maddlabs.co/v1"})
    (konfig / "device.json").write_text(json.dumps({"device_id": "d1", "device_secret": "t", "name": "mac"}))
    cli.SESSION.pop("maddlabs_direct", None)
    cli.SESSION.update(turn_steps=0, turn_spent=0)


def test_samo_maddlabs_bez_konta_domaai_idzie_wprost(konfig, monkeypatch):
    cli._maddlabs_save({"api_key": "sk-x"})
    cli.SESSION.pop("maddlabs_direct", None)
    assert cli.load_device() is None
    assert not cli.maddlabs_with_domaai_tools("qwen/qwen3.8-27b")


def test_maddlabs_z_kontem_domaai_dostaje_narzedzia_domaai(konfig, monkeypatch):
    _maddlabs_i_domaai(konfig, monkeypatch)
    assert cli.load_device()
    assert cli.maddlabs_with_domaai_tools("qwen/qwen3.8-27b")
    seen = {}

    def fake_lopus(creds, messages, model, auto_yes, mode, mozg=None):
        seen.update(model=model, mozg=mozg)
        return True

    monkeypatch.setattr(cli, "lopus_turn", fake_lopus)
    monkeypatch.setattr(cli, "api_step", lambda *_a, **_k: pytest.fail("krok nie może iść wprost do API"))
    assert cli._agent_turn(None, [{"role": "user", "content": "hej"}], "qwen/qwen3.8-27b", False) is True
    assert seen == {"model": "qwen/qwen3.8-27b", "mozg": "madd"}
    monkeypatch.setenv("CODO_MADDLABS_DIRECT", "1")
    assert not cli.maddlabs_with_domaai_tools("qwen/qwen3.8-27b")


def test_odmowa_serwera_przelacza_na_api_maddlabs_do_konca_sesji(konfig, monkeypatch, capsys):
    _maddlabs_i_domaai(konfig, monkeypatch)
    proby = []

    def fake_lopus(creds, messages, model, auto_yes, mode, mozg=None):
        proby.append(model)
        raise cli.ApiError(409, "Narzędzia DomaAI działają z modelem qwen3.8-27b. Wybrany model pracuje bez nich.")

    monkeypatch.setattr(cli, "lopus_turn", fake_lopus)
    monkeypatch.setattr(cli, "api_step", lambda creds, body: {"message": {"role": "assistant", "content": "ok"},
                                                            "model": "speakleash/bielik", "credits_spent": 0})
    model = "speakleash/bielik-11b-v3.0-instruct"
    for _ in range(2):
        assert cli._agent_turn(None, [{"role": "system", "content": "s"}, {"role": "user", "content": "hej"}],
                               model, False) is True
    assert proby == [model]  # druga tura już nie pyta serwera DomaAI
    assert "wprost przez API MaddLabs" in capsys.readouterr().out
    assert cli.maddlabs_with_domaai_tools("qwen/qwen3.8-27b")  # inny model znów próbuje narzędzi DomaAI
    cli.SESSION.pop("maddlabs_direct", None)


def test_lopus_turn_wysyla_mozg_madd(konfig, monkeypatch):
    _maddlabs_i_domaai(konfig, monkeypatch)
    wyslane = {}

    class Most:
        id = "daemon-12345678"

        def __init__(self, *_a, **_k):
            import queue
            import threading
            self.errors, self.jobs, self.stop = queue.Queue(), queue.Queue(), threading.Event()

        def close(self):
            pass

    def fake_urlopen(request, **_k):
        wyslane.update(json.loads(request.data.decode()))
        raise cli.urllib.error.HTTPError(request.full_url, 503, "x", {}, __import__("io").BytesIO(
            json.dumps({"detail": "Model MaddLabs jest teraz wyłączony."}).encode()))

    monkeypatch.setattr(cli, "_LopusBridge", Most)
    monkeypatch.setattr(cli, "device_access_token", lambda force=False: "tok")
    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(cli, "api_call", lambda *_a, **_k: {})
    with pytest.raises(cli.ApiError) as blad:
        cli.lopus_turn(None, [{"role": "user", "content": "znajdź w sieci"}], "qwen/qwen3.8-27b", False, "ask", mozg="madd")
    assert blad.value.status == 503
    assert wyslane["mozg"] == "madd" and wyslane["model_maddlabs"] == "qwen/qwen3.8-27b"
    assert wyslane["variant"] == "pro" and wyslane["description"] == "znajdź w sieci"
