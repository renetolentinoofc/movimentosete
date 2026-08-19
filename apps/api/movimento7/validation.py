import re
from datetime import UTC, datetime
from urllib.parse import unquote, urlsplit
from uuid import UUID


def normalize_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("55") and 12 <= len(digits) <= 13:
        return "+" + digits
    if 10 <= len(digits) <= 11:
        return "+55" + digits
    return None


def normalize_instagram(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", candidate):
        return None
    return candidate.lower()


def safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value.strip()


def safe_next_path(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    for _ in range(3):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    if not candidate.startswith("/") or candidate.startswith("//") or "\\" in candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


def parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
