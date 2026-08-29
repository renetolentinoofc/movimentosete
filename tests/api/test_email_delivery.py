from movimento7.services.email_delivery import deliver_email


def test_smtp_delivery_sends_message_without_exposing_credentials(app, monkeypatch):
    app.config.update(
        EMAIL_DELIVERY_MODE="smtp",
        EMAIL_FROM_ADDRESS="sender@example.test",
        EMAIL_FROM_NAME="Movimento 7",
        EMAIL_REPLY_TO="reply@example.test",
        SMTP_HOST="smtp.example.test",
        SMTP_PORT=587,
        SMTP_USERNAME="sender@example.test",
        SMTP_PASSWORD="secret-password",
        SMTP_USE_TLS=True,
    )
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.update(host=host, port=port, timeout=timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            pass

        def starttls(self, context):
            sent["tls"] = context is not None

        def login(self, username, password):
            sent.update(username=username, password=password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setattr("movimento7.services.email_delivery.smtplib.SMTP", FakeSMTP)

    with app.app_context():
        result = deliver_email(
            recipient="customer@example.test",
            subject="Teste",
            text_body="Mensagem transacional",
        )

    assert result.status == "sent"
    assert sent["tls"] is True
    assert sent["message"]["To"] == "customer@example.test"
    assert sent["message"]["Subject"] == "Teste"
