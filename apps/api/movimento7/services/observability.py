from collections.abc import Mapping
from typing import Any

import sentry_sdk
from flask import Flask, current_app, g


def init_error_reporting(app: Flask | None = None) -> None:
    target = app or current_app
    dsn = str(target.config.get("ERROR_REPORTING_DSN", "")).strip()
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        environment=target.config.get("APP_ENV", "development"),
        release=target.config.get("GIT_COMMIT", "local"),
        traces_sample_rate=float(target.config.get("ERROR_REPORTING_TRACES_SAMPLE_RATE", 0)),
        send_default_pii=False,
    )


def capture_exception(error: BaseException, *, context: Mapping[str, Any] | None = None) -> None:
    if not current_app.config.get("ERROR_REPORTING_DSN"):
        return
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("request_id", g.get("request_id", ""))
        for key, value in (context or {}).items():
            scope.set_tag(key, str(value)[:100])
        sentry_sdk.capture_exception(error)


def capture_message(
    message: str, *, level: str = "warning", context: Mapping[str, Any] | None = None
) -> None:
    if not current_app.config.get("ERROR_REPORTING_DSN"):
        return
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("request_id", g.get("request_id", ""))
        for key, value in (context or {}).items():
            scope.set_tag(key, str(value)[:100])
        sentry_sdk.capture_message(message, level=level)
