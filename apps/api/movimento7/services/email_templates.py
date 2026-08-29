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
            "Sua inscrição está na lista de espera. Avisaremos caso haja uma nova atualização."
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


def privacy_verification(*, protocol: str, verify_url: str, expires_minutes: int) -> EmailTemplate:
    return EmailTemplate(
        key="privacy_request_verification",
        subject=f"Confirme sua solicitação de privacidade — {protocol}",
        text_body=(
            "Recebemos uma solicitação relacionada aos seus dados no Movimento 7.\n\n"
            f"Protocolo: {protocol}\n"
            f"Confirme sua identidade em até {expires_minutes} minutos:\n{verify_url}\n\n"
            "Se você não fez esta solicitação, ignore esta mensagem.\n\n"
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


def contact_reply(*, name: str, subject: str, message: str, protocol: str) -> EmailTemplate:
    return EmailTemplate(
        key="contact_reply",
        subject=subject,
        text_body=(
            f"Olá, {name}.\n\n"
            f"{message}\n\n"
            f"Protocolo do atendimento: {protocol}\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def order_created(*, name: str, order_code: str, total: str, expires_at: str) -> EmailTemplate:
    return EmailTemplate(
        key="order_created",
        subject=f"Pedido recebido — {order_code}",
        text_body=(
            f"Olá, {name}.\n\n"
            "Recebemos seu pedido no Movimento 7.\n\n"
            f"Pedido: {order_code}\n"
            f"Total: {total}\n"
            f"A reserva de estoque é válida até: {expires_at}\n\n"
            "O pagamento ainda não foi aprovado. Nossa equipe enviará as instruções "
            "e a confirmação.\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def order_payment_update(*, name: str, order_code: str, status: str, total: str) -> EmailTemplate:
    labels = {
        "paid": "confirmado",
        "failed": "não confirmado",
        "refunded": "estornado",
    }
    label = labels[status]
    return EmailTemplate(
        key=f"order_payment_{status}",
        subject=f"Pagamento {label} — {order_code}",
        text_body=(
            f"Olá, {name}.\n\n"
            f"O pagamento do pedido {order_code} foi {label}.\n\n"
            f"Total do pedido: {total}\n\n"
            "Acompanhe novas atualizações por e-mail.\n\n"
            "Equipe Movimento 7\n"
        ),
    )


def order_status_update(*, name: str, order_code: str, status: str) -> EmailTemplate:
    labels = {
        "shipped": (
            "enviado",
            "Seu pedido foi enviado. A equipe informará o rastreamento quando disponível.",
        ),
        "delivered": (
            "entregue",
            "Esperamos que você aproveite sua compra. Obrigado por apoiar o Movimento 7.",
        ),
        "expired": (
            "expirado",
            "A reserva de estoque expirou porque o pagamento não foi confirmado dentro do prazo.",
        ),
    }
    label, message = labels[status]
    return EmailTemplate(
        key=f"order_status_{status}",
        subject=f"Pedido {label} — {order_code}",
        text_body=f"Olá, {name}.\n\n{message}\n\nPedido: {order_code}\n\nEquipe Movimento 7\n",
    )
