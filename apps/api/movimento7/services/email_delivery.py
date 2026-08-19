import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from flask import current_app


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    delivered_to: str


def valid_email(value: str) -> bool:
    _, address = parseaddr(value)
    return bool(address and address == value and "@" in address and len(address) <= 180)


def mask_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "não configurado"
    visible = local[:2]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def email_configuration() -> dict[str, object]:
    mode = str(current_app.config["EMAIL_DELIVERY_MODE"])
    username = str(current_app.config["SMTP_USERNAME"])
    password = str(current_app.config["SMTP_PASSWORD"])
    from_address = str(current_app.config["EMAIL_FROM_ADDRESS"])
    sandbox_recipient = str(current_app.config["EMAIL_SANDBOX_RECIPIENT"])
    smtp_required = mode in {"sandbox", "live"}
    configured = bool(
        valid_email(from_address)
        and (not smtp_required or (username and password and current_app.config["SMTP_HOST"]))
        and (mode != "sandbox" or valid_email(sandbox_recipient))
    )
    return {
        "mode": mode,
        "configured": configured,
        "smtp_host": current_app.config["SMTP_HOST"] if smtp_required else None,
        "smtp_port": current_app.config["SMTP_PORT"] if smtp_required else None,
        "smtp_username": mask_email(username) if username else "não configurado",
        "smtp_password_set": bool(password),
        "from_address": from_address or "não configurado",
        "reply_to": current_app.config["EMAIL_REPLY_TO"] or None,
        "contact_recipient": (
            mask_email(str(current_app.config["EMAIL_CONTACT_RECIPIENT"]))
            if current_app.config["EMAIL_CONTACT_RECIPIENT"]
            else "não configurado"
        ),
        "sandbox_recipient": (
            mask_email(sandbox_recipient) if sandbox_recipient else "não configurado"
        ),
    }


def deliver_email(
    *, recipient: str, subject: str, text_body: str, reply_to: str | None = None
) -> DeliveryResult:
    config = email_configuration()
    if not config["configured"]:
        raise RuntimeError("Configuração de e-mail incompleta")
    mode = str(config["mode"])
    delivered_to = (
        str(current_app.config["EMAIL_SANDBOX_RECIPIENT"])
        if mode == "sandbox"
        else recipient.strip().lower()
    )
    if not valid_email(delivered_to):
        raise ValueError("Destinatário inválido")
    if mode == "log":
        return DeliveryResult(status="logged", delivered_to=delivered_to)

    message = EmailMessage()
    message["From"] = formataddr(
        (str(current_app.config["EMAIL_FROM_NAME"]), str(current_app.config["EMAIL_FROM_ADDRESS"]))
    )
    message["To"] = delivered_to
    message["Subject"] = f"[SANDBOX] {subject}" if mode == "sandbox" else subject
    resolved_reply_to = (reply_to or str(current_app.config["EMAIL_REPLY_TO"])).strip().lower()
    if resolved_reply_to:
        if not valid_email(resolved_reply_to):
            raise ValueError("Endereço de resposta inválido")
        message["Reply-To"] = resolved_reply_to
    message.set_content(text_body)

    with smtplib.SMTP(
        str(current_app.config["SMTP_HOST"]),
        int(current_app.config["SMTP_PORT"]),
        timeout=15,
    ) as smtp:
        smtp.ehlo()
        if current_app.config["SMTP_USE_TLS"]:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        smtp.login(
            str(current_app.config["SMTP_USERNAME"]),
            str(current_app.config["SMTP_PASSWORD"]),
        )
        smtp.send_message(message)
    return DeliveryResult(status="sent", delivered_to=delivered_to)
