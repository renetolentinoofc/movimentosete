import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from flask import current_app, g
from sqlalchemy import select

from ..extensions import db
from ..models import CommunicationLog
from .email_delivery import deliver_email
from .email_templates import EmailTemplate
from .observability import capture_exception


@dataclass(frozen=True)
class EmailDispatch:
    status: str
    log_id: UUID
    duplicate: bool


def dispatch_email(
    *,
    recipient: str,
    template: EmailTemplate,
    idempotency_key: str,
    registration_id: UUID | None = None,
    contact_id: UUID | None = None,
    author_id: UUID | None = None,
    reply_to: str | None = None,
) -> EmailDispatch:
    existing = db.session.scalar(
        select(CommunicationLog).where(
            CommunicationLog.idempotency_key == idempotency_key
        )
    )
    if existing:
        return EmailDispatch(status=existing.status, log_id=existing.id, duplicate=True)

    normalized_recipient = recipient.strip().lower()
    try:
        if reply_to:
            delivery = deliver_email(
                recipient=normalized_recipient,
                subject=template.subject,
                text_body=template.text_body,
                reply_to=reply_to,
            )
        else:
            delivery = deliver_email(
                recipient=normalized_recipient,
                subject=template.subject,
                text_body=template.text_body,
            )
        status = delivery.status
    except Exception as error:
        capture_exception(error, context={"component": "email_delivery", "template": template.key})
        current_app.logger.warning(
            "Template email delivery failed: %s (%s)",
            template.key,
            type(error).__name__,
            extra={"request_id": g.get("request_id")},
        )
        status = "failed"

    log = CommunicationLog(
        registration_id=registration_id,
        contact_id=contact_id,
        author_id=author_id,
        channel="email",
        recipient_hash=hashlib.sha256(normalized_recipient.encode("utf-8")).hexdigest(),
        template_key=template.key,
        status=status,
        idempotency_key=idempotency_key[:100],
        created_at=datetime.now(UTC),
    )
    db.session.add(log)
    db.session.flush()
    return EmailDispatch(status=status, log_id=log.id, duplicate=False)
