from dataclasses import dataclass


@dataclass(frozen=True)
class EmailTemplate:
    key: str
    subject: str
    text_body: str


def registration_confirmation(*, name: str, protocol: str, category: str) -> EmailTemplate:
    return EmailTemplate(
        key="registration_received",
        subject=f"Inscrição recebida — {protocol}",
        text_body=(
            f"Olá, {name}.\n\n"
            "Recebemos sua inscrição no Movimento 7.\n\n"
            f"Protocolo: {protocol}\n"
            f"Categoria: {category}\n"
            "Status: recebida\n\n"
            "Guarde o protocolo para qualquer atendimento. "
            "Avisaremos por e-mail quando houver uma atualização.\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def registration_status_update(*, name: str, protocol: str, status: str) -> EmailTemplate:
    labels = {
        "received": "recebida",
        "reviewing": "em análise",
        "approved": "aprovada",
        "waitlisted": "na lista de espera",
        "rejected": "não selecionada",
        "withdrawn": "retirada",
    }
    messages = {
        "received": "Sua inscrição foi registrada e aguarda análise.",
        "reviewing": "Nossa equipe começou a analisar sua inscrição.",
        "approved": (
            "Parabéns! Sua inscrição foi aprovada. "
            "A equipe entrará em contato com os próximos passos."
        ),
        "waitlisted": (
            "Sua inscrição está na lista de espera. "
            "Avisaremos caso haja uma nova atualização."
        ),
        "rejected": "Agradecemos sua participação. Sua inscrição não foi selecionada nesta etapa.",
        "withdrawn": (
            "A inscrição foi marcada como retirada. "
            "Se isso não era esperado, entre em contato conosco."
        ),
    }
    label = labels[status]
    return EmailTemplate(
        key=f"registration_status_{status}",
        subject=f"Inscrição {label} — {protocol}",
        text_body=(
            f"Olá, {name}.\n\n"
            f"{messages[status]}\n\n"
            f"Protocolo: {protocol}\n"
            f"Status: {label}\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def admin_password_reset(*, name: str, reset_url: str, expires_minutes: int) -> EmailTemplate:
    return EmailTemplate(
        key="admin_password_reset",
        subject="Redefinição de senha do painel — Movimento 7",
        text_body=(
            f"Olá, {name}.\n\n"
            "Recebemos uma solicitação para redefinir sua senha administrativa.\n\n"
            f"Abra este endereço em até {expires_minutes} minutos:\n{reset_url}\n\n"
            "O link funciona uma única vez. Se você não fez a solicitação, ignore esta mensagem; "
            "sua senha atual continuará válida.\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def contact_message_received(
    *, name: str, email: str, subject: str, message: str, protocol: str
) -> EmailTemplate:
    return EmailTemplate(
        key="contact_message_received",
        subject=f"[Contato] {subject} — {protocol}",
        text_body=(
            "Uma nova mensagem foi recebida pelo site Movimento 7.\n\n"
            f"Protocolo: {protocol}\n"
            f"Nome: {name}\n"
            f"E-mail: {email}\n"
            f"Assunto: {subject}\n\n"
            "Mensagem:\n"
            f"{message}\n\n"
            "Responda diretamente a este e-mail para falar com a pessoa remetente.\n"
        ),
    )
