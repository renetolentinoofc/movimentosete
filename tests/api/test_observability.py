from movimento7.services import observability


def test_error_reporting_is_disabled_without_dsn(app, monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("Sentry não deveria ser chamado sem DSN")

    monkeypatch.setattr(observability.sentry_sdk, "capture_exception", unexpected_call)
    monkeypatch.setattr(observability.sentry_sdk, "capture_message", unexpected_call)

    with app.app_context():
        observability.capture_exception(RuntimeError("erro de teste"))
        observability.capture_message("mensagem de teste")


def test_error_reporting_initialization_does_not_send_personal_data(app, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        observability.sentry_sdk,
        "init",
        lambda **kwargs: captured.update(kwargs),
    )
    app.config["ERROR_REPORTING_DSN"] = "https://public@example.invalid/1"
    app.config["ERROR_REPORTING_TRACES_SAMPLE_RATE"] = 0.05

    with app.app_context():
        observability.init_error_reporting()

    assert captured["dsn"] == "https://public@example.invalid/1"
    assert captured["traces_sample_rate"] == 0.05
    assert captured["send_default_pii"] is False
