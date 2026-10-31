"""Unit tests for first-name resolution in tempo_certo.notifiers."""

import requests

from tempo_certo import config, notifiers


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self._json_data


def test_resolve_first_name_uses_config_and_skips_api(monkeypatch):
    monkeypatch.setattr(config, "USER_FIRST_NAME", "Stéfane")
    monkeypatch.setattr(config, "NOTIFY_METHOD", "telegram")

    def _boom(*args, **kwargs):
        raise AssertionError("the Telegram API must not be called when USER_FIRST_NAME is set")

    monkeypatch.setattr(notifiers.requests, "get", _boom)

    assert notifiers.resolve_first_name() == "Stéfane"


def test_resolve_first_name_falls_back_to_telegram_api(monkeypatch):
    monkeypatch.setattr(config, "USER_FIRST_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_METHOD", "telegram")

    def _fake_get(url, params=None, timeout=None):
        return _FakeResponse({"ok": True, "result": {"first_name": "Léo"}})

    monkeypatch.setattr(notifiers.requests, "get", _fake_get)

    assert notifiers.resolve_first_name() == "Léo"


def test_resolve_first_name_none_when_api_fails(monkeypatch):
    monkeypatch.setattr(config, "USER_FIRST_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_METHOD", "telegram")

    def _fake_get(url, params=None, timeout=None):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(notifiers.requests, "get", _fake_get)

    assert notifiers.resolve_first_name() is None


def test_resolve_first_name_none_when_not_telegram(monkeypatch):
    monkeypatch.setattr(config, "USER_FIRST_NAME", "")
    monkeypatch.setattr(config, "NOTIFY_METHOD", "ntfy")

    def _boom(*args, **kwargs):
        raise AssertionError("the Telegram API must not be called when NOTIFY_METHOD isn't telegram")

    monkeypatch.setattr(notifiers.requests, "get", _boom)

    assert notifiers.resolve_first_name() is None


def test_get_telegram_first_name_none_on_not_ok_response(monkeypatch):
    def _fake_get(url, params=None, timeout=None):
        return _FakeResponse({"ok": False})

    monkeypatch.setattr(notifiers.requests, "get", _fake_get)

    assert notifiers.get_telegram_first_name() is None


def test_get_telegram_first_name_none_on_missing_field(monkeypatch):
    def _fake_get(url, params=None, timeout=None):
        return _FakeResponse({"ok": True, "result": {}})

    monkeypatch.setattr(notifiers.requests, "get", _fake_get)

    assert notifiers.get_telegram_first_name() is None


def test_ntfy_reports_http_errors_and_logs_failed_delivery(monkeypatch, caplog):
    import pytest

    monkeypatch.setattr(config, "NOTIFY_METHOD", "ntfy")
    monkeypatch.setattr(config, "FALLBACK_NOTIFY_METHODS", [])
    monkeypatch.setattr(notifiers.requests, "post", lambda *a, **k: _FakeResponse({}, 429))
    with pytest.raises(requests.HTTPError, match="429"):
        notifiers.notify("Synthetic weather message")
    assert "Notification via ntfy failed: 429 error" in caplog.text


def test_ntfy_http_failure_uses_configured_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "NOTIFY_METHOD", "ntfy")
    monkeypatch.setattr(config, "FALLBACK_NOTIFY_METHODS", ["email"])
    monkeypatch.setattr(notifiers.requests, "post", lambda *a, **k: _FakeResponse({}, 503))
    monkeypatch.setitem(notifiers.NOTIFY_SENDERS, "email", calls.append)
    notifiers.notify("Synthetic weather message")
    assert calls == ["Synthetic weather message"]


def test_ntfy_success_keeps_plain_text_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "NTFY_TOPIC", "synthetic-topic")
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse({}, 200)
    monkeypatch.setattr(notifiers.requests, "post", post)
    notifiers.send_ntfy("*Bonjour* été")
    assert calls == [("https://ntfy.sh/synthetic-topic", {
        "data": "Bonjour été".encode("utf-8"),
        "headers": {"Title": "Tempo Certo", "Tags": "sunny,shirt"},
        "timeout": 10,
    })]


def test_main_exits_nonzero_when_ntfy_rejects_notification(monkeypatch, caplog):
    import importlib
    import logging
    import pytest
    from tempo_certo import log_setup

    monkeypatch.setattr(log_setup, "setup_logging", lambda: logging.getLogger("tempo-test"))
    entry = importlib.import_module("tempo_certo.__main__")
    monkeypatch.setattr(config, "NOTIFY_METHOD", "ntfy")
    monkeypatch.setattr(config, "FALLBACK_NOTIFY_METHODS", [])
    monkeypatch.setattr(config, "DRY_RUN", False)
    monkeypatch.setattr(entry, "validate_credentials", lambda: None)
    monkeypatch.setattr(entry, "fetch_forecast", lambda: {})
    monkeypatch.setattr(entry, "hours_today", lambda data: [{"hour": 9}])
    monkeypatch.setattr(entry, "sunrise_hour", lambda data: 7)
    monkeypatch.setattr(entry, "analyze_windows", lambda *args: {})
    monkeypatch.setattr(entry, "analyze_clothing", lambda *args: {})
    monkeypatch.setattr(entry, "build_message", lambda *args: "Synthetic weather message")
    monkeypatch.setattr(entry, "send_error_email", lambda *args: None)
    monkeypatch.setattr(entry, "send_report_email", lambda **kwargs: None)
    monkeypatch.setattr(notifiers.requests, "post", lambda *a, **k: _FakeResponse({}, 503))
    with pytest.raises(SystemExit) as exc:
        entry.main()
    assert exc.value.code == 1
    assert "503 error" in caplog.text
