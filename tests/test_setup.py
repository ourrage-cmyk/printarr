from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import setup as setup_flow
from app.main import create_app
from app.setup import CheckResult, SetupValues, stored_overrides
from app.store import TicketStore

SECRET = "ha-token-do-not-leak-1234"
TG_SECRET = "123456:tg-secret-do-not-leak"


@pytest.fixture
def wizard(settings):
    """Settings with the first-run gate on, on a fresh database."""
    return replace(settings, setup_required=True)


def all_ok(monkeypatch):
    ok = CheckResult(True, "fine")
    monkeypatch.setattr(setup_flow, "check_home_assistant", lambda url, token: ok)
    monkeypatch.setattr(setup_flow, "check_model_server", lambda url, models: ok)
    monkeypatch.setattr(setup_flow, "check_printer", lambda host, port: ok)
    monkeypatch.setattr(setup_flow, "check_telegram", lambda token, chat: ok)
    monkeypatch.setattr(setup_flow, "check_timezone", lambda name: ok)


def form(**overrides):
    values = {
        "timezone": "Europe/London",
        "printer_host": "192.168.1.50",
        "printer_port": 9100,
        "ha_url": "http://192.168.1.10:8123",
        "ha_token": SECRET,
        "llm_enabled": True,
        "llm_base_url": "http://192.168.1.231:11434/v1",
        "llm_model": "d1:latest",
        "llm_text_model": "granite4.2:3b",
        "telegram_token": TG_SECRET,
        "telegram_chat_id": "42",
        "yannic_name": "Yannic",
        "wife_name": "Allyson",
    }
    values.update(overrides)
    return values


def test_gate_closes_the_api_until_setup_is_done(wizard):
    with TestClient(create_app(wizard)) as client:
        blocked = client.get("/api/v1/tickets")
        assert blocked.status_code == 503
        assert blocked.json()["setup"] == "/"
        assert client.get("/healthz").status_code == 200
        page = client.get("/")
        assert page.status_code == 200 and "Set up printarr" in page.text
        status = client.get("/api/v1/setup/status").json()
        assert status["complete"] is False
        assert status["secrets"] == {"ha_token": "not set", "telegram_token": "not set"}


def test_code_is_printed_and_only_kept_as_a_hash(wizard, caplog):
    app = create_app(wizard)
    with TestClient(app):
        code = app.state.setup_code
        assert code and code in caplog.text
        stored = TicketStore(wizard.db_path).get_setting(setup_flow.CODE_HASH_KEY)
        assert stored == setup_flow.code_hash(code) and code not in stored


def test_wrong_code_is_refused(wizard):
    with TestClient(create_app(wizard)) as client:
        for headers in ({}, {"X-Setup-Code": "guess"}):
            response = client.post("/api/v1/setup/check/printer", json=form(), headers=headers)
            assert response.status_code == 401


def test_single_check_reports_and_saves_nothing(wizard, monkeypatch):
    monkeypatch.setattr(setup_flow, "check_home_assistant", lambda url, token: CheckResult(False, "no answer"))
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        result = client.post("/api/v1/setup/check/home_assistant", json=form(), headers=headers).json()
        assert result == {"item": "home_assistant", "ok": False, "detail": "no answer"}
        assert TicketStore(wizard.db_path).get_setting("ha_url") is None


def test_failed_check_blocks_completion_and_lists_what_to_fix(wizard, monkeypatch):
    all_ok(monkeypatch)
    monkeypatch.setattr(setup_flow, "check_printer", lambda host, port: CheckResult(False, "cannot reach printer"))
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        response = client.post("/api/v1/setup/complete", json=form(), headers=headers)
        assert response.status_code == 422
        assert response.json()["detail"] == {"printer": "cannot reach printer"}
        assert client.get("/api/v1/tickets").status_code == 503


def test_completion_opens_the_api_and_hides_secrets(wizard, monkeypatch):
    all_ok(monkeypatch)
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        done = client.post("/api/v1/setup/complete", json=form(timezone="Europe/Paris"), headers=headers)
        assert done.status_code == 200
        assert done.json() == {"complete": True, "restart_needed": True}

        assert client.get("/api/v1/tickets").status_code == 200
        assert "Printarr" in client.get("/").text and "Set up printarr" not in client.get("/").text

        # After setup the same code still opens /setup, so settings can be changed later.
        assert client.get("/setup").status_code == 200
        wrong = client.post("/api/v1/setup/complete", json=form(), headers={"X-Setup-Code": "guess"})
        assert wrong.status_code == 401

        everything = " ".join(
            [
                client.get("/api/v1/setup/status").text,
                client.get("/api/v1/settings/ha").text,
                client.get("/api/v1/settings/alerts").text,
            ]
        )
        assert SECRET not in everything and TG_SECRET not in everything
        assert client.get("/api/v1/settings/ha").json()["token_configured"] is True


def test_saved_printer_and_timezone_apply_on_next_start(wizard, monkeypatch):
    all_ok(monkeypatch)
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        client.post("/api/v1/setup/complete", json=form(printer_host="10.0.0.9", timezone="Europe/Paris"), headers=headers)
    restarted = stored_overrides(replace(wizard, printer_host="", timezone="Europe/London"))
    assert restarted.printer_host == "10.0.0.9"
    assert restarted.printer_mode == "tcp"
    assert restarted.timezone == "Europe/Paris"


def test_legacy_install_skips_the_wizard(settings):
    store = TicketStore(settings.db_path)
    store.init()
    store.set_setting("llm_enabled", "true")  # what an earlier release wrote on its first start
    legacy = replace(settings, setup_required=True)
    with TestClient(create_app(legacy)) as client:
        assert client.get("/api/v1/tickets").status_code == 200
        assert client.get("/api/v1/setup/status").json()["complete"] is True


def test_overrides_do_nothing_on_a_fresh_install(settings):
    assert stored_overrides(settings) == settings


def test_values_are_validated(wizard):
    with TestClient(create_app(wizard)) as client:
        bad = client.post(
            "/api/v1/setup/check/printer",
            json={"printer_port": 70000},
            headers={"X-Setup-Code": "anything"},
        )
        assert bad.status_code == 422
        extra = client.post(
            "/api/v1/setup/check/printer",
            json={"printer_host": "x", "password": "nope"},
            headers={"X-Setup-Code": "anything"},
        )
        assert extra.status_code == 422


def test_model_server_check_needs_both_models(monkeypatch):
    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"data": [{"id": "d1:latest"}]}'

    monkeypatch.setattr(setup_flow.urllib.request, "urlopen", lambda url, timeout: Reply())
    result = setup_flow.check_model_server("http://ollama:11434/v1", ["d1:latest", "granite4.2:3b"])
    assert result.ok is False and "granite4.2:3b" in result.detail


def test_settings_can_be_changed_after_setup(wizard, monkeypatch):
    all_ok(monkeypatch)
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        client.post("/api/v1/setup/complete", json=form(), headers=headers)
        # A blank token keeps the saved one; the printer moves to the real device.
        changed = client.post(
            "/api/v1/setup/complete",
            json=form(printer_host="192.168.1.77", ha_token=""),
            headers=headers,
        )
        assert changed.status_code == 200
        store = TicketStore(wizard.db_path)
        assert store.get_setting("printer_host") == "192.168.1.77"
        assert store.get_setting("ha_token") == SECRET


def test_clear_removes_a_saved_secret(wizard, monkeypatch):
    all_ok(monkeypatch)
    app = create_app(wizard)
    with TestClient(app) as client:
        headers = {"X-Setup-Code": app.state.setup_code}
        client.post("/api/v1/setup/complete", json=form(), headers=headers)
        client.post(
            "/api/v1/setup/complete",
            json=form(ha_url="", ha_token="", clear=["ha_token"]),
            headers=headers,
        )
        assert TicketStore(wizard.db_path).get_setting("ha_token") == ""


def test_fill_secrets_keeps_saved_values_only_when_blank(wizard):
    store = TicketStore(wizard.db_path)
    store.init()
    store.set_setting("ha_token", SECRET)
    kept = setup_flow.fill_secrets(SetupValues(ha_token=""), store)
    assert kept.ha_token == SECRET
    replaced = setup_flow.fill_secrets(SetupValues(ha_token="new-token"), store)
    assert replaced.ha_token == "new-token"
