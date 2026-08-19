from typing import Any

from flask import Response, g, jsonify


def success(
    data: Any = None, *, meta: dict[str, Any] | None = None, status: int = 200
) -> tuple[Response, int]:
    return jsonify(
        {"data": data, "meta": meta or {}, "error": None, "request_id": g.get("request_id")}
    ), status


def failure(
    code: str,
    message: str,
    *,
    status: int,
    fields: dict[str, list[str]] | None = None,
) -> tuple[Response, int]:
    return (
        jsonify(
            {
                "data": None,
                "meta": {},
                "error": {"code": code, "message": message, "fields": fields or {}},
                "request_id": g.get("request_id"),
            }
        ),
        status,
    )
